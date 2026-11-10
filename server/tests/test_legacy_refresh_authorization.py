"""HTTP authorization checks for the publishable tree; all IO is mocked."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routes import google, meta_legacy, integrations, google_oauth, shopify_oauth, fbits
from services import tenant, platform_admin, ig_supabase

CID = 'tenant-a'
PERIOD = {'start': '2026-05-01', 'end': '2026-05-01'}


class LegacyRefreshAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.role = 'viewer'
        self.modules = [google, meta_legacy, integrations, google_oauth, shopify_oauth, fbits]
        app = FastAPI()
        for module in self.modules:
            app.include_router(module.router)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://offline')
        self.addAsyncCleanup(self.client.aclose)
        self.work = []

        def install(module, name, value):
            item = patch.object(module, name, value)
            item.start()
            self.addCleanup(item.stop)
            return value

        async def membership(_uid, requested_client_id=None):
            if requested_client_id != CID:
                raise PermissionError('Tenant não autorizado')
            return CID

        install(tenant, 'require_user_id', AsyncMock(return_value='synthetic-user'))
        install(tenant, 'sb_get_client_id_for_user', AsyncMock(side_effect=membership))
        install(tenant, 'sb_get_client_memberships', AsyncMock(side_effect=lambda _uid: [{'client_id': CID, 'role': self.role}]))
        install(platform_admin, 'is_platform_admin', AsyncMock(return_value=False))
        install(platform_admin, 'require_user_id', AsyncMock(return_value='synthetic-user'))
        # Fail closed if a denied route reaches database IO unexpectedly.
        install(ig_supabase, '_request', AsyncMock(side_effect=AssertionError('External DB IO forbidden')))
        for module in self.modules:
            if hasattr(module, 'require_user_id'):
                install(module, 'require_user_id', AsyncMock(return_value='synthetic-user'))
            if hasattr(module, '_log_endpoint_call'):
                install(module, '_log_endpoint_call', AsyncMock(return_value='synthetic-user'))
            if hasattr(module, 'invalidate_namespace'):
                install(module, 'invalidate_namespace', AsyncMock())
        for module, name in [
            (google, 'sync_google_ads'), (google, 'sync_ga4_for_period'),
            (meta_legacy, 'refresh_all'), (meta_legacy, 'sync_ads_for_client_period'),
            (meta_legacy, 'refresh_meta_token_for_connection'),
            (integrations, 'refresh_provider_data'), (shopify_oauth, 'sync_shopify_connection'),
            (fbits, '_schedule_tenant_sync'),
        ]:
            self.work.append(install(module, name, AsyncMock(return_value={'ok': True, 'client_id': CID})))
        install(meta_legacy, '_validated_connection_id', AsyncMock(return_value='conn'))
        self.context = install(google, 'resolve_ga4_connection_context', AsyncMock(return_value=SimpleNamespace(
            client_id=CID, property_id='123', connection_id='conn', auth_mode='oauth')))
        install(google, 'get_google_access_token', AsyncMock(return_value='synthetic'))
        install(google, 'resolve_google_ads_context', AsyncMock(return_value=SimpleNamespace(client_id=CID, connection_id='conn')))
        install(shopify_oauth, 'resolve_shopify_reconciliation_since', AsyncMock(return_value='2026-05-01'))

    async def request(self, method, path, cid=CID, body=None):
        return await self.client.request(method, path.replace('{client_id}', cid).replace('{connection_id}', 'conn').replace('{authorization_connection_id}', 'conn'),
            params={} if '/data-refresh/' in path else {'client_id': cid, 'start': PERIOD['start'], 'end': PERIOD['end'], 'shop': 'synthetic.myshopify.com'},
            headers={'Authorization': 'Bearer synthetic'}, **({'json': body} if body is not None else {}))

    def mutation_routes(self):
        for module in self.modules:
            for route in module.router.routes:
                if route.path.startswith('/api/cron/') or route.path.endswith('/connect_meta'):
                    continue  # Dedicated machine authentication / already-retired 410 route.
                for method in route.methods & {'POST', 'PUT', 'PATCH', 'DELETE'}:
                    if '{provider}' in route.path:
                        for provider in ['meta', 'google', 'shopify', 'fbits']:
                            yield method, route.path.replace('{provider}', provider)
                    else:
                        yield method, route.path

    async def test_viewer_is_403_for_every_legacy_mutation_before_provider_or_db(self):
        for method, path in self.mutation_routes():
            with self.subTest(method=method, path=path):
                response = await self.request(method, path, body=PERIOD if '/data-refresh/' in path else {**PERIOD, 'client_id': CID})
                self.assertEqual(response.status_code, 403, response.text)
        for mock in self.work:
            mock.assert_not_awaited()
        ig_supabase._request.assert_not_awaited()

    async def test_client_admin_other_tenant_is_denied_before_work(self):
        self.role = 'client_admin'
        for method, path in self.mutation_routes():
            with self.subTest(method=method, path=path):
                response = await self.request(method, path, cid='tenant-b', body=PERIOD if '/data-refresh/' in path else {**PERIOD, 'client_id': 'tenant-b'})
                self.assertEqual(response.status_code, 403, response.text)
        for mock in self.work:
            mock.assert_not_awaited()
        self.context.assert_not_awaited()
        google.get_google_access_token.assert_not_awaited()
        ig_supabase._request.assert_not_awaited()

    async def test_admin_can_sync_current_and_legacy_own_tenant(self):
        self.role = 'client_admin'
        cases = [('/api/google/ads/sync', None, 200), ('/api/google/ga4/sync', None, 200),
            ('/api/ig/refresh_all', None, 200), ('/api/ig/sync', None, 200),
            ('/api/clients/{client_id}/meta-ads/sync', {}, 200),
            ('/api/oauth/shopify/conn/sync', None, 200),
            ('/api/clients/{client_id}/fbits/sync', None, 202), ('/api/fbits/sync', None, 202)]
        for provider in ['meta', 'google', 'shopify', 'fbits']:
            cases.append(('/api/clients/{client_id}/data-refresh/' + provider, PERIOD, 200))
        for path, body, expected in cases:
            with self.subTest(path=path):
                before = sum(mock.await_count for mock in self.work)
                response = await self.request('POST', path, body=body)
                self.assertEqual(response.status_code, expected, response.text)
                self.assertEqual(sum(mock.await_count for mock in self.work), before + 1)

    async def test_ga4_viewer_is_denied_before_connection_resolution(self):
        response = await self.request('POST', '/api/google/ga4/sync')
        self.assertEqual(response.status_code, 403)
        self.context.assert_not_awaited()
        google.get_google_access_token.assert_not_awaited()
        google.sync_ga4_for_period.assert_not_awaited()
        ig_supabase._request.assert_not_awaited()

    async def test_identity_debug_get_is_a_mutation_and_requires_admin(self):
        # The identity helper defaults to persisting Meta connection/client IDs.
        with patch.object(meta_legacy, 'discover_instagram_identity_for_connection', AsyncMock(return_value={'ok': True})) as discover:
            response = await self.request('GET', '/api/ig/debug/identity')
            self.assertEqual(response.status_code, 403)
            discover.assert_not_awaited()
            meta_legacy._validated_connection_id.assert_not_awaited()
            ig_supabase._request.assert_not_awaited()
            self.role = 'client_admin'
            self.assertEqual((await self.request('GET', '/api/ig/debug/identity', cid='tenant-b')).status_code, 403)
            discover.assert_not_awaited()
            meta_legacy._validated_connection_id.assert_not_awaited()
            self.assertEqual((await self.request('GET', '/api/ig/debug/identity')).status_code, 200)
            discover.assert_awaited_once_with('conn')

    async def test_viewer_reads_google_meta_and_health_with_tenant_scope(self):
        cases = [(google, 'build_google_ads_report', '/api/google/ads/report'),
                 (meta_legacy, 'list_connections', '/api/clients/{client_id}/connections')]
        for module, name, path in cases:
            with self.subTest(path=path), patch.object(module, name, AsyncMock(return_value=[] if name == 'list_connections' else {'ok': True})) as read:
                self.assertEqual((await self.request('GET', path)).status_code, 200)
                self.assertEqual((await self.request('GET', path, cid='tenant-b')).status_code, 403)
                read.assert_awaited_once()
        with patch('services.data_health.client_data_health', AsyncMock(return_value={'client_id': CID})) as read:
            self.assertEqual((await self.request('GET', '/api/clients/{client_id}/data-health')).status_code, 200)
            self.assertEqual((await self.request('GET', '/api/clients/{client_id}/data-health', cid='tenant-b')).status_code, 403)
            read.assert_awaited_once_with(CID, PERIOD['start'], PERIOD['end'])

    async def test_oauth_start_rejects_viewer_without_creating_state(self):
        for path in ['/api/oauth/meta/start', '/api/oauth/google/ga4/start', '/api/oauth/google/ads/start', '/api/oauth/google/start', '/api/oauth/shopify/start']:
            with self.subTest(path=path):
                self.assertEqual((await self.request('GET', path)).status_code, 403)
        ig_supabase._request.assert_not_awaited()
