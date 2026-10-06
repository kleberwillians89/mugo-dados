"""Refresh por membership, tenant isolation e resposta sem payload do provider."""
from __future__ import annotations

import json
import sys
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from fastapi import FastAPI, HTTPException
from routes import integrations
from services import provider_refresh as refresh, tenant, fbits_connections, intelligence
from services.fbits_client import _retry_after_seconds
from services.integration_errors import IntegrationError

CID = "curavino-test"
PERIOD = {"start": "2026-09-01", "end": "2026-09-30"}


class RefreshAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = FastAPI()
        app.include_router(integrations.router)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)
        self.work = AsyncMock(return_value={"ok": True, "client_id": CID, "provider": "fbits"})
        async def membership(uid, requested_client_id=None):
            if requested_client_id != CID:
                raise PermissionError("Outro tenant")
            return CID
        self.patches = [
            patch.object(tenant, "require_user_id", AsyncMock(return_value="viewer")),
            patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=[{"client_id": CID, "role": "viewer"}])),
            patch.object(tenant, "sb_get_client_id_for_user", AsyncMock(side_effect=membership)),
            patch("services.platform_admin.is_platform_admin", AsyncMock(return_value=False)),
            patch.object(integrations, "refresh_provider_data", self.work),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    async def post(self, provider="fbits", cid=CID, **kwargs):
        return await self.client.post(f"/api/clients/{cid}/data-refresh/{provider}", headers={"Authorization": "Bearer viewer"}, json=kwargs.pop("json", PERIOD), **kwargs)

    async def test_viewer_curavino_can_refresh_each_allowed_provider(self):
        for provider in ["fbits", "shopify", "meta", "google"]:
            response = await self.post(provider)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.work.await_args.args, (CID, provider, PERIOD["start"], PERIOD["end"]))

    async def test_cross_tenant_is_403_before_sync(self):
        for provider in ["fbits", "shopify", "meta", "google"]:
            response = await self.post(provider, "other-tenant")
            self.assertEqual(response.status_code, 403)
        self.work.assert_not_awaited()

    async def test_credentials_and_arbitrary_assets_are_rejected(self):
        for field in ["credentials", "access_token", "account_id", "business_id", "property_id", "shop", "domain", "connection_id"]:
            response = await self.post(json={**PERIOD, field: "arbitrary"})
            self.assertEqual(response.status_code, 422)
            response = await self.post(params={field: "arbitrary"})
            self.assertEqual(response.status_code, 400)
        self.work.assert_not_awaited()

    async def test_unknown_provider_and_unbounded_period_rejected(self):
        self.assertEqual((await self.post("openai")).status_code, 422)
        self.assertEqual((await self.post(json={"start": "2025-01-01", "end": "2026-09-30"})).status_code, 422)
        self.assertEqual((await self.post(json={"start": "2026-10-01", "end": "2026-09-30"})).status_code, 422)
        self.work.assert_not_awaited()

    async def test_admin_still_can_refresh(self):
        with patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=[{"client_id": CID, "role": "client_admin"}])):
            self.assertEqual((await self.post()).status_code, 200)

    async def test_viewer_still_cannot_read_admin_integrations(self):
        response = await self.client.get(f"/api/clients/{CID}/integrations", headers={"Authorization": "Bearer viewer"})
        self.assertEqual(response.status_code, 403)


@asynccontextmanager
async def no_lock(**kwargs):
    yield "lock"


class ProviderRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ai = AsyncMock(side_effect=AssertionError("Refresh não pode chamar OpenAI"))
        self.addCleanup(self.ai.assert_not_called)
        self.patches = [patch.object(intelligence, "_call_provider", self.ai), patch.object(refresh, "guarded_sync", no_lock), patch.object(refresh, "acquire_sync_lock", AsyncMock(return_value=True))]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    async def run_refresh(self, provider):
        return await refresh.refresh_provider_data(CID, provider, **PERIOD)

    async def test_fbits_only_and_response_never_contains_credentials(self):
        with patch.object(refresh, "list_generic_connections", AsyncMock(return_value=[{"provider": "fbits", "status": "connected"}])), patch.object(refresh, "sync_fbits_connection", AsyncMock(return_value={"access_token": "secret", "account_id": "private"})) as sync, patch.object(refresh, "invalidate_official_kpis", AsyncMock()), patch.object(refresh, "sync_shopify_connection", AsyncMock()) as shopify:
            result = await self.run_refresh("fbits")
            sync.assert_awaited_once_with(client_id=CID)
            shopify.assert_not_awaited()
            self.assertEqual(result, {"ok": True, "client_id": CID, "provider": "fbits"})
            self.assertNotIn("secret", json.dumps(result))

    async def test_shopify_resolves_persisted_selection_without_browser_id(self):
        with patch.object(refresh, "list_generic_connections", AsyncMock(return_value=[{"provider": "shopify", "status": "connected"}])), patch.object(refresh, "resolve_generic_connection", AsyncMock(return_value={"id": "persisted"})) as resolve, patch.object(refresh, "resolve_shopify_reconciliation_since", AsyncMock(return_value="watermark")), patch.object(refresh, "sync_shopify_connection", AsyncMock()) as sync:
            await self.run_refresh("shopify")
            resolve.assert_awaited_once_with(client_id=CID, provider="shopify", prefer_metadata_flag="selected_for_reporting", require_token=False)
            sync.assert_awaited_once_with(client_id=CID, connection_id="persisted", updated_at_min="watermark")

    async def test_inactive_ecommerce_cannot_sync(self):
        with patch.object(refresh, "list_generic_connections", AsyncMock(return_value=[])), patch.object(refresh, "sync_fbits_connection", AsyncMock()) as sync:
            with self.assertRaises(HTTPException) as error:
                await self.run_refresh("fbits")
            self.assertEqual(error.exception.status_code, 409)
            sync.assert_not_awaited()

    async def test_server_cooldown_prevents_all_external_work(self):
        with patch.object(refresh, "acquire_sync_lock", AsyncMock(return_value=False)), patch.object(refresh, "list_generic_connections", AsyncMock()) as resolve:
            for provider in ["fbits", "shopify", "meta", "google"]:
                with self.assertRaises(HTTPException) as error:
                    await self.run_refresh(provider)
                self.assertEqual(error.exception.status_code, 429)
                self.assertEqual(error.exception.headers["Retry-After"], "60")
            resolve.assert_not_awaited()

    async def test_meta_syncs_only_persisted_meta_sources_and_sanitizes_failure(self):
        async def connection(**kwargs):
            self.assertEqual(kwargs["client_id"], CID)
            self.assertNotIn("requested_connection_id", kwargs)
            return {"connection_id": "organic" if kwargs["platform"] == "instagram" else "paid", "row": {"ig_user_id": "persisted"}}
        with patch.object(refresh, "resolve_connection_for_scope", AsyncMock(side_effect=connection)), patch.object(refresh, "sync_instagram_for_client", AsyncMock(return_value={"ok": True})) as organic, patch.object(refresh, "sync_ads_for_client_period", AsyncMock(side_effect=RuntimeError("secret token"))) as paid, patch.object(refresh, "sync_shopify_connection", AsyncMock()) as shopify:
            with self.assertRaises(HTTPException) as error:
                await self.run_refresh("meta")
            self.assertNotIn("secret", error.exception.detail)
            organic.assert_awaited_once_with(CID, limit=200, preferred_connection_id="organic", persisted_only=True)
            paid.assert_awaited_once_with(client_id=CID, connection_id="paid", since=PERIOD["start"], until=PERIOD["end"], persisted_only=True)
            shopify.assert_not_awaited()

    async def test_google_uses_persisted_property_and_ads_with_independent_syncs(self):
        with patch.object(refresh, "list_generic_connections", AsyncMock(return_value=[{"provider": "ga4"}, {"provider": "google_ads"}])), patch.object(refresh, "resolve_ga4_connection_context", AsyncMock(return_value=SimpleNamespace(connection_id="ga4", property_id="persisted-property"))), patch.object(refresh, "resolve_google_ads_context", AsyncMock(return_value=SimpleNamespace(connection_id="ads"))), patch.object(refresh, "get_google_access_token", AsyncMock(return_value="secret")), patch.object(refresh, "sync_ga4_for_period", AsyncMock(side_effect=RuntimeError("secret"))) as ga4, patch.object(refresh, "sync_google_ads", AsyncMock(return_value={"ok": True})) as ads:
            with self.assertRaises(HTTPException) as error:
                await self.run_refresh("google")
            self.assertNotIn("secret", error.exception.detail)
            self.assertEqual(ga4.await_args.kwargs["property_id"], "persisted-property")
            self.assertEqual(ga4.await_args.kwargs["client_id"], CID)
            self.assertEqual(ads.await_args.kwargs["connection_id"], "ads")

    async def test_google_projection_failure_is_not_announced_as_updated(self):
        error = IntegrationError('projection failed', status_code=502, code='GOOGLE_ADS_PROJECTION_FAILED', provider='google_ads')
        with patch.object(refresh, 'list_generic_connections', AsyncMock(return_value=[{'provider': 'google_ads'}])), \
             patch.object(refresh, 'resolve_google_ads_context', AsyncMock(return_value=SimpleNamespace(connection_id='ads'))), \
             patch.object(refresh, 'sync_google_ads', AsyncMock(side_effect=error)) as sync, \
             patch.object(refresh, 'invalidate_namespace', AsyncMock()) as invalidate:
            with self.assertRaises(HTTPException) as raised:
                await self.run_refresh('google')
        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn('Mantendo a última leitura disponível', raised.exception.detail)
        sync.assert_awaited_once()
        invalidate.assert_not_awaited()


class FbitsCooldownTests(unittest.IsolatedAsyncioTestCase):
    async def test_persisted_cooldown_blocks_before_token_or_provider(self):
        now = datetime.now(timezone.utc)
        row = {"id": "fbits", "metadata": {"rate_limit_until": (now + timedelta(minutes=5)).isoformat()}}
        with patch.object(fbits_connections, "load_fbits_connection", AsyncMock(return_value=row)), patch.object(fbits_connections, "get_connection", AsyncMock()) as token:
            with self.assertRaises(IntegrationError) as error:
                await fbits_connections.sync_fbits_connection(client_id=CID, now=now)
            self.assertEqual(error.exception.status_code, 429)
            token.assert_not_awaited()

    def test_expired_cooldown_and_retry_after_http_date(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(fbits_connections.fbits_cooldown_remaining({"metadata": {"rate_limit_until": (now - timedelta(seconds=2)).isoformat()}}, now), 0)
        self.assertEqual(_retry_after_seconds(httpx.Response(429, headers={"Retry-After": "120"})), 120)
        from email.utils import format_datetime
        value = _retry_after_seconds(httpx.Response(429, headers={"Retry-After": format_datetime(now + timedelta(minutes=2), usegmt=True)}))
        self.assertTrue(119 <= value <= 120)


class RefreshConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_requests_never_start_two_syncs(self):
        import asyncio
        from services.sync_locks import guarded_sync
        held = set()
        async def rpc(name, payload):
            key = (payload["p_client_id"], payload["p_job_name"])
            if name == "acquire_client_job_lock":
                if key in held:
                    return False
                held.add(key)
            else:
                held.discard(key)
            return True
        entered, finish = asyncio.Event(), asyncio.Event()
        async def sync(**kwargs):
            entered.set()
            await finish.wait()
            return {"ok": True}
        with patch("services.sync_locks.sb_rpc", AsyncMock(side_effect=rpc)), patch.object(refresh, "guarded_sync", guarded_sync), patch.object(refresh, "acquire_sync_lock", AsyncMock(return_value=True)), patch.object(refresh, "list_generic_connections", AsyncMock(return_value=[{"provider": "fbits", "status": "connected"}])), patch.object(refresh, "sync_fbits_connection", AsyncMock(side_effect=sync)) as work, patch.object(refresh, "invalidate_official_kpis", AsyncMock()):
            first = asyncio.create_task(refresh.refresh_provider_data(CID, "fbits", **PERIOD))
            await asyncio.wait_for(entered.wait(), 1)
            try:
                with self.assertRaises(IntegrationError) as error:
                    await asyncio.wait_for(refresh.refresh_provider_data(CID, "fbits", **PERIOD), 1)
                self.assertEqual(error.exception.code, "SYNC_ALREADY_RUNNING")
                work.assert_awaited_once()
            finally:
                finish.set()
                await first
            self.assertFalse(held)


class MetaPersistedOnlyTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_without_instagram_identity_never_discovers_or_syncs(self):
        async def resolve(**kwargs):
            return {"connection_id": "organic", "row": {}} if kwargs["platform"] == "instagram" else {"connection_id": None}
        with patch.object(refresh, "guarded_sync", no_lock), patch.object(refresh, "acquire_sync_lock", AsyncMock(return_value=True)), patch.object(refresh, "resolve_connection_for_scope", AsyncMock(side_effect=resolve)), patch.object(refresh, "sync_instagram_for_client", AsyncMock()) as sync:
            with self.assertRaises(HTTPException) as error:
                await refresh.refresh_provider_data(CID, "meta", **PERIOD)
            self.assertEqual(error.exception.status_code, 409)
            sync.assert_not_awaited()

    async def test_restricted_token_never_uses_global_fallback(self):
        from services import meta_tokens
        with patch.object(meta_tokens, "get_connection_by_id", AsyncMock(return_value={"id": "conn", "client_id": CID, "status": "needs_reauth"})), patch.object(meta_tokens, "_env_access_token", return_value="global-secret") as global_token, patch.object(meta_tokens, "_disable_token_refresh", return_value=True):
            with self.assertRaises(IntegrationError):
                await meta_tokens.ensure_valid_meta_token(CID, connection_id="conn", persisted_only=True)
            global_token.assert_not_called()

    async def test_restricted_instagram_missing_identity_never_reads_legacy_or_discovers(self):
        from services import instagram_sync
        with patch.object(instagram_sync, "_resolve_connection_by_id", AsyncMock(return_value={"id": "conn", "client_id": CID, "platform": "instagram"})), patch.object(instagram_sync, "sb_get_one", AsyncMock()) as legacy, patch.object(instagram_sync, "discover_instagram_identity_for_connection", AsyncMock()) as discovery:
            with self.assertRaises(RuntimeError):
                await instagram_sync._sync_instagram_connection("conn", persisted_only=True)
            legacy.assert_not_awaited()
            discovery.assert_not_awaited()


class GoogleSyncBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_ga4_real_sync_accepts_connection_and_shares_lock_with_legacy_callers(self):
        from services import ga4_sync
        identities = []
        @asynccontextmanager
        async def lock(**kwargs):
            identities.append(kwargs["connection_id"])
            yield "lock"
        # Só a chamada ao Google é simulada; executa wrapper e sync reais.
        with patch.object(ga4_sync, "guarded_sync", lock), patch.object(ga4_sync, "_run_named_report", AsyncMock(return_value={"rows": [], "row_count": 0})) as upstream:
            for connection in ["persisted-connection", None]:
                result = await ga4_sync.sync_ga4_for_period(client_id=CID, property_id="properties/123", connection_id=connection, access_token="test-secret", since=PERIOD["start"], until=PERIOD["end"], record_job_run=False)
                self.assertTrue(result["ok"])
            self.assertEqual(identities, ["property:123", "property:123"])
            self.assertTrue(upstream.await_count > 0)
            self.assertEqual(upstream.await_args.kwargs["property_id"], "123")

    async def test_ads_legacy_request_resolves_persisted_connection_before_lock(self):
        from services import google_ads
        identities = []
        @asynccontextmanager
        async def lock(**kwargs):
            identities.append(kwargs["connection_id"])
            yield "lock"
        with patch.object(google_ads, "resolve_google_ads_context", AsyncMock(return_value=SimpleNamespace(connection_id="persisted"))) as resolve, patch.object(google_ads, "guarded_sync", lock), patch.object(google_ads, "_sync_google_ads", AsyncMock(return_value={"ok": True, "connection_id": "persisted", "rows_upserted": 0})), patch.object(google_ads, "_record_sync_outcome", AsyncMock()):
            await google_ads.sync_google_ads(client_id=CID, connection_id=None, start=PERIOD["start"], end=PERIOD["end"], days=30, record_job_run=False)
            resolve.assert_awaited_once_with(CID)
            self.assertEqual(identities, ["persisted"])


class IndependentMetaSourcesTests(unittest.IsolatedAsyncioTestCase):
    async def run_sources(self, ads):
        async def resolve(**kwargs):
            return {"connection_id": "organic" if kwargs["platform"] == "instagram" else "paid", "row": {"ig_user_id":"persisted"}}
        with patch.object(refresh,"guarded_sync",no_lock), patch.object(refresh,"acquire_sync_lock",AsyncMock(return_value=True)), patch.object(refresh,"resolve_connection_for_scope",AsyncMock(side_effect=resolve)), patch.object(refresh,"sync_instagram_for_client",AsyncMock(return_value={"ok":True,"read_model_refreshed":True})), patch.object(refresh,"sync_ads_for_client_period",ads):
            return await refresh.refresh_provider_data(CID,"meta",**PERIOD)

    async def test_organic_and_ads_success_are_independent(self):
        ads=AsyncMock(return_value={"ok":True,"sync_outcome":"success"})
        result=await self.run_sources(ads)
        self.assertEqual(result["sources"],{"Instagram":{"status":"success"},"Meta Ads":{"status":"success"}})
        self.assertEqual(ads.await_args.kwargs["client_id"],CID)
        self.assertEqual(ads.await_args.kwargs["connection_id"],"paid")
        self.assertTrue(ads.await_args.kwargs["persisted_only"])

    async def test_ads_failure_is_identified_after_organic_success(self):
        with self.assertRaises(HTTPException) as error:
            await self.run_sources(AsyncMock(side_effect=RuntimeError("secret token upstream")))
        self.assertEqual(error.exception.status_code,502)
        self.assertIn("Meta Ads",error.exception.detail)
        self.assertNotIn("secret",error.exception.detail)
        self.assertNotIn("Instagram",error.exception.detail)

    async def test_no_data_is_valid_consultation_not_missing_sync(self):
        result=await self.run_sources(AsyncMock(return_value={"ok":True,"sync_outcome":"no_data"}))
        self.assertEqual(result["sources"]["Meta Ads"]["status"],"no_data")
