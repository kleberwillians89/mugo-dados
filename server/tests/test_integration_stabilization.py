import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from server.services import ga4_sync, generic_connections, google_oauth, meta_oauth
from server.services.integration_errors import google_api_error
from server.services.meta_http import MetaApiError


class GoogleProductIsolationTests(unittest.IsolatedAsyncioTestCase):
    def test_ga4_provider_without_scope_is_not_authorized(self):
        capabilities = generic_connections.google_capabilities(
            {"provider": "ga4", "status": "connected", "scopes": ["openid"]}
        )
        self.assertFalse(capabilities["ga4_authorized"])

    def test_ads_scope_on_ga4_connection_does_not_authorize_ads(self):
        capabilities = generic_connections.google_capabilities(
            {
                "provider": "ga4",
                "status": "connected",
                "scopes": ["https://www.googleapis.com/auth/adwords"],
            }
        )
        self.assertFalse(capabilities["ads_authorized"])

    async def test_ga4_api_rejects_google_ads_connection_before_external_call(self):
        with patch.object(
            google_oauth,
            "get_connection",
            AsyncMock(
                return_value={
                    "provider": "google_ads",
                    "status": "connected",
                    "_token": '{"access_token":"not-used"}',
                }
            ),
        ):
            with self.assertRaises(google_oauth.IntegrationError) as raised:
                await google_oauth.list_ga4_properties("amalie", "ads-connection")
        self.assertEqual(raised.exception.code, "GOOGLE_SCOPE_INSUFFICIENT")


class ConnectionTenantIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_connection_from_another_tenant_has_specific_error(self):
        with patch.object(
            generic_connections,
            "sb_select",
            AsyncMock(side_effect=[[], [{"id": "connection-1", "client_id": "roove"}]]),
        ):
            with self.assertRaises(generic_connections.IntegrationError) as raised:
                await generic_connections.get_connection("amalie", "connection-1")
        self.assertEqual(raised.exception.code, "OAUTH_CONNECTION_TENANT_MISMATCH")
        self.assertEqual(raised.exception.status_code, 403)


class MetaOrganicConfigurationTests(unittest.IsolatedAsyncioTestCase):
    async def test_page_discovery_follows_all_pages_without_auto_selecting_tenant(self):
        first_pages = {
            "data": [{"id": "page-amalie", "name": "Amalie", "instagram_business_account": {"id": "ig-amalie", "username": "amalie"}}],
            "paging": {"next": "https://graph.facebook.com/next-pages"},
        }
        second_pages = {
            "data": [{"id": "page-roove", "name": "Roove", "instagram_business_account": {"id": "ig-roove", "username": "roove"}}],
        }
        with (
            patch.object(meta_oauth, "_meta_get", AsyncMock(side_effect=[{"id": "julia", "name": "Julia"}, first_pages])),
            patch.object(meta_oauth, "meta_get_json", AsyncMock(return_value=second_pages)),
        ):
            result = await meta_oauth.fetch_instagram_identity("safe-token")
        self.assertEqual([item["business_id"] for item in result["instagram_accounts"]], ["page-amalie", "page-roove"])
        self.assertNotIn("selected", result)

    async def test_lists_pages_and_only_linked_professional_instagram(self):
        responses = [
            {"id": "meta-user", "name": "Amalie"},
            {"data": [
                {"id": "page-1", "name": "Amalie", "instagram_business_account": {"id": "ig-1", "username": "amalie"}},
                {"id": "page-2", "name": "Sem Instagram"},
            ]},
        ]
        with patch.object(meta_oauth, "_meta_get", AsyncMock(side_effect=responses)):
            result = await meta_oauth.fetch_instagram_identity("safe-token")
        self.assertEqual([page["page_id"] for page in result["pages"]], ["page-1", "page-2"])
        self.assertEqual([item["ig_user_id"] for item in result["instagram_accounts"]], ["ig-1"])

    async def test_missing_page_permission_is_structured(self):
        connection = {
            "provider": "meta", "scopes": ["ads_read"],
            "_token": json.dumps({"access_token": "safe-token"}),
        }
        with patch.object(meta_oauth, "get_connection", AsyncMock(return_value=connection)):
            with self.assertRaises(meta_oauth.IntegrationError) as raised:
                await meta_oauth.discover_existing_meta_organic_assets(
                    user_id="user-amalie", client_id="amalie", connection_id="meta-1"
                )
        self.assertEqual(raised.exception.code, "META_PERMISSION_MISSING")

    async def test_selecting_instagram_preserves_existing_meta_ads(self):
        handoff = {
            "handoff": "handoff-1", "user_id": "user-amalie", "client_id": "amalie",
            "encrypted_access_token": "encrypted", "meta_user_json": {"id": "meta-user", "name": "Amalie"},
            "instagram_accounts_json": [{
                "ig_user_id": "ig-1", "username": "amalie", "business_id": "page-1", "business_name": "Amalie",
            }],
            "ad_accounts_json": [], "scopes_json": ["instagram_basic", "instagram_manage_insights"],
        }
        previous = {"metadata": {
            "selected_ad_account_id": "act_673785144083881",
            "selected_ad_account_name": "Amalie Ads",
            "ad_account_ids": ["act_673785144083881"],
        }}
        upsert = AsyncMock(return_value={"id": "generic-meta"})
        with (
            patch.object(meta_oauth, "_load_handoff_row", AsyncMock(return_value=handoff)),
            patch.object(meta_oauth, "decrypt_secret", return_value="safe-token"),
            patch.object(meta_oauth, "encrypt_secret", return_value="encrypted"),
            patch.object(meta_oauth, "sb_select", AsyncMock(side_effect=[[], [], [previous]])),
            patch.object(meta_oauth, "sb_insert", AsyncMock(return_value={"id": "organic-1", "ig_user_id": "ig-1"})),
            patch.object(meta_oauth, "sb_update", AsyncMock()),
            patch.object(meta_oauth, "upsert_connection", upsert),
            patch.object(meta_oauth, "invalidate_namespace", AsyncMock()),
        ):
            await meta_oauth.save_connections(
                user_id="user-amalie", client_id="amalie", handoff="handoff-1",
                page_ids=["page-1"], instagram_ig_user_ids=["ig-1"], ad_account_ids=[],
            )
        metadata = upsert.await_args.kwargs["metadata"]
        self.assertEqual(metadata["selected_ad_account_id"], "act_673785144083881")
        self.assertEqual(metadata["ad_account_ids"], ["act_673785144083881"])
        self.assertEqual(metadata["coverage"], "full")

    def _manual_connection(self, metadata=None):
        return {
            "provider": "meta", "client_id": "amalie", "scopes": ["pages_show_list", "instagram_basic", "ads_read"],
            "metadata": metadata or {}, "_token": json.dumps({"access_token": "safe-token"}),
        }

    async def test_manual_page_id_is_validated_and_named(self):
        with (
            patch.object(meta_oauth, "get_connection", AsyncMock(return_value=self._manual_connection())),
            patch.object(meta_oauth, "_meta_get", AsyncMock(return_value={"id": "123", "name": "Amalie"})),
        ):
            result = await meta_oauth.validate_manual_meta_assets(
                client_id="amalie", connection_id="meta-1", page_id="123"
            )
        self.assertEqual(result["page"]["name"], "Amalie")

    async def test_manual_page_without_access_is_rejected(self):
        denied = MetaApiError("denied", status_code=403)
        with (
            patch.object(meta_oauth, "get_connection", AsyncMock(return_value=self._manual_connection())),
            patch.object(meta_oauth, "_meta_get", AsyncMock(side_effect=denied)),
        ):
            with self.assertRaises(meta_oauth.IntegrationError) as raised:
                await meta_oauth.validate_manual_meta_assets(
                    client_id="amalie", connection_id="meta-1", page_id="123"
                )
        self.assertEqual(raised.exception.code, "META_ASSET_PERMISSION_DENIED")

    async def test_manual_instagram_must_match_page(self):
        responses = [
            {"id": "123", "name": "Amalie", "instagram_business_account": {"id": "999"}},
            {"id": "456", "username": "amalie"},
        ]
        with (
            patch.object(meta_oauth, "get_connection", AsyncMock(return_value=self._manual_connection())),
            patch.object(meta_oauth, "_meta_get", AsyncMock(side_effect=responses)),
        ):
            with self.assertRaises(meta_oauth.IntegrationError) as raised:
                await meta_oauth.validate_manual_meta_assets(
                    client_id="amalie", connection_id="meta-1", page_id="123", instagram_id="456"
                )
        self.assertEqual(raised.exception.code, "META_PAGE_INSTAGRAM_MISMATCH")

    async def test_manual_ad_account_accepts_numeric_and_normalizes_prefix(self):
        with (
            patch.object(meta_oauth, "get_connection", AsyncMock(return_value=self._manual_connection())),
            patch.object(meta_oauth, "_meta_get", AsyncMock(return_value={
                "id": "act_789", "name": "Amalie Ads", "account_status": 1,
            })),
        ):
            result = await meta_oauth.validate_manual_meta_assets(
                client_id="amalie", connection_id="meta-1", ad_account_id="789"
            )
        self.assertEqual(result["ad_account"]["id"], "act_789")

    async def test_manual_disabled_ad_account_is_rejected(self):
        with (
            patch.object(meta_oauth, "get_connection", AsyncMock(return_value=self._manual_connection())),
            patch.object(meta_oauth, "_meta_get", AsyncMock(return_value={
                "id": "act_789", "name": "Disabled", "account_status": 2,
            })),
        ):
            with self.assertRaises(meta_oauth.IntegrationError) as raised:
                await meta_oauth.validate_manual_meta_assets(
                    client_id="amalie", connection_id="meta-1", ad_account_id="act_789"
                )
        self.assertEqual(raised.exception.code, "META_AD_ACCOUNT_DISABLED")


class Ga4StructuredErrorTests(unittest.TestCase):
    def test_admin_api_disabled_has_specific_code(self):
        request = httpx.Request("GET", "https://analyticsadmin.googleapis.com/v1beta/accountSummaries")
        response = httpx.Response(403, request=request, json={"error": {
            "message": "Analytics Admin API has not been used in project",
            "details": [{"reason": "SERVICE_DISABLED"}],
        }})
        error = google_api_error(
            response, api="Analytics Admin API",
            unavailable_code="GOOGLE_PROPERTY_UNAVAILABLE", operation="listar propriedades",
        )
        self.assertEqual(error.code, "GOOGLE_ADMIN_API_DISABLED")

    def test_data_api_disabled_has_specific_code(self):
        request = httpx.Request("POST", "https://analyticsdata.googleapis.com/v1beta/properties/1:runReport")
        response = httpx.Response(403, request=request, json={"error": {
            "message": "Google Analytics Data API has not been used",
            "details": [{"reason": "SERVICE_DISABLED"}],
        }})
        error = google_api_error(
            response, api="Analytics Data API",
            unavailable_code="GOOGLE_PROPERTY_UNAVAILABLE", operation="sincronizar",
        )
        self.assertEqual(error.code, "GOOGLE_DATA_API_DISABLED")

    def test_daily_persistence_keeps_client_and_period(self):
        rows = ga4_sync._daily_upsert_rows(
            client_id="amalie", property_id="123",
            daily_rows=[{"values": {"date": "20260803", "sessions": "2"}}],
            funnel_by_date={},
        )
        self.assertEqual(rows[0]["client_id"], "amalie")
        self.assertEqual(rows[0]["stat_date"], "2026-08-03")


class Ga4RefreshTests(unittest.IsolatedAsyncioTestCase):
    def test_legacy_encrypted_refresh_token_is_read_without_inventing_value(self):
        with patch.object(google_oauth, "decrypt_secret", return_value="legacy-refresh"):
            token = google_oauth._connection_token_payload({
                "_token": json.dumps({"access_token": "expired"}),
                "encrypted_refresh_token": "encrypted-legacy",
                "token_expires_at": "2026-08-03T10:00:00+00:00",
            })
        self.assertEqual(token["refresh_token"], "legacy-refresh")
        self.assertEqual(token["expires_at"], "2026-08-03T10:00:00+00:00")

    def test_missing_legacy_refresh_token_remains_missing(self):
        token = google_oauth._connection_token_payload({"_token": "{}"})
        self.assertNotIn("refresh_token", token)

    async def test_expired_connection_without_refresh_has_explicit_code(self):
        row = {
            "provider": "ga4", "status": "connected", "disconnected_at": None,
            "_token": json.dumps({"access_token": "expired", "expires_at": "2020-01-01T00:00:00+00:00"}),
        }
        with patch.object(google_oauth, "get_connection", AsyncMock(return_value=row)):
            with self.assertRaises(google_oauth.IntegrationError) as raised:
                await google_oauth.get_google_access_token("amalie", "ga4-1", request_id="req-missing")
        self.assertEqual(raised.exception.code, "GOOGLE_REAUTH_REQUIRED_REFRESH_MISSING")

    async def test_expired_access_token_refreshes_and_lists_properties(self):
        token_response = httpx.Response(
            200, request=httpx.Request("POST", "https://oauth2.googleapis.com/token"),
            json={"access_token": "new-access", "expires_in": 3600},
        )
        admin_response = httpx.Response(
            200, request=httpx.Request("GET", "https://analyticsadmin.googleapis.com/v1beta/accountSummaries"),
            json={"accountSummaries": [{"account": "accounts/1", "displayName": "Amalie", "propertySummaries": [{"property": "properties/2", "displayName": "Site"}]}]},
        )

        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return None
            async def post(self, *args, **kwargs): return token_response
            async def get(self, *args, **kwargs): return admin_response

        row = {
            "provider": "ga4", "status": "connected", "disconnected_at": None,
            "_token": "", "encrypted_token": "",
            "encrypted_access_token": "encrypted-access",
            "encrypted_refresh_token": "encrypted-refresh",
            "token_expires_at": "2020-01-01T00:00:00+00:00",
        }
        update = AsyncMock()
        with (
            patch.object(google_oauth, "get_connection", AsyncMock(return_value=row)),
            patch.object(google_oauth, "settings", return_value={"client_id": "id", "client_secret": "secret"}),
            patch.object(google_oauth, "encrypt_secret", return_value="encrypted-new-token"),
            patch.object(google_oauth, "decrypt_secret", side_effect=lambda value: {
                "encrypted-access": "expired-access",
                "encrypted-refresh": "valid-refresh",
            }[value]),
            patch.object(google_oauth, "sb_update", update),
            patch.object(google_oauth.httpx, "AsyncClient", return_value=FakeClient()),
        ):
            properties = await google_oauth.list_ga4_properties("amalie", "ga4-1", request_id="req-1")
        self.assertEqual(properties[0]["property"], "properties/2")
        update.assert_awaited_once()

    async def test_revoked_refresh_token_requires_reconnection(self):
        response = httpx.Response(
            400,
            request=httpx.Request("POST", "https://oauth2.googleapis.com/token"),
            json={"error": "invalid_grant"},
        )

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def post(self, *args, **kwargs):
                return response

        row = {
            "provider": "ga4", "status": "connected",
            "_token": json.dumps({"refresh_token": "revoked"}),
        }
        with (
            patch.object(google_oauth, "get_connection", AsyncMock(return_value=row)),
            patch.object(google_oauth, "settings", return_value={"client_id": "id", "client_secret": "secret"}),
            patch.object(google_oauth.httpx, "AsyncClient", return_value=FakeClient()),
        ):
            with self.assertRaises(google_oauth.IntegrationError) as raised:
                await google_oauth.get_google_access_token("amalie", "ga4-1")
        self.assertEqual(raised.exception.code, "GOOGLE_REAUTH_REQUIRED_INVALID_GRANT")
        self.assertEqual(raised.exception.status_code, 409)
