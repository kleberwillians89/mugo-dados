import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from server.services import connection_resolver, ga4_client, ga4_sync, generic_connections, google_oauth, meta_oauth
from server.services.integration_errors import google_api_error
from server.services.meta_http import MetaApiError
from server.routes import google_oauth as google_routes, meta_legacy as meta_routes


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

    async def test_ga4_route_rejects_empty_property_list_with_safe_diagnostics(self):
        row = {
            "id": "ga4-1", "client_id": "amalie", "provider": "ga4", "status": "connected",
            "scopes": ["https://www.googleapis.com/auth/analytics.readonly"],
            "account_name": "analytics@amalie.example",
        }
        diagnostics = {
            "connection_id": "ga4-1", "client_id": "amalie", "provider": "ga4",
            "access_token_available": True, "refresh_token_available": True,
            "authorized_email": "analytics@amalie.example",
        }
        with (
            patch.object(google_routes, "require_client_read", AsyncMock(return_value="amalie")),
            patch.object(google_routes, "get_connection", AsyncMock(return_value=row)),
            patch.object(google_routes, "get_google_connection_diagnostics", AsyncMock(return_value=diagnostics)),
            patch.object(google_routes, "list_ga4_properties", AsyncMock(return_value=[])),
        ):
            with self.assertRaises(RuntimeError) as raised:
                await google_routes.ga4_properties(
                    "ga4-1", request=SimpleNamespace(state=SimpleNamespace(request_id="req-empty")),
                    client_id="amalie", authorization="Bearer safe",
                )
        self.assertEqual(raised.exception.code, "GOOGLE_NO_PROPERTIES_AVAILABLE")
        self.assertEqual(raised.exception.diagnostics["authorized_email"], "analytics@amalie.example")
        self.assertNotIn("token", str(raised.exception.diagnostics).lower().replace("access_token_available", "").replace("refresh_token_available", ""))


class MetaOrganicActivationTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_validation_accepts_connected_instagram_account_link(self):
        with (
            patch.object(meta_oauth, "_manual_meta_connection", AsyncMock(return_value=({}, "safe-token", {}))),
            patch.object(meta_oauth, "_meta_get", AsyncMock(side_effect=[
                {
                    "id": "123", "name": "Amalie",
                    "connected_instagram_account": {"id": "999", "username": "amalie"},
                },
                {"id": "999", "username": "amalie", "name": "Amalie"},
            ])),
        ):
            result = await meta_oauth.validate_manual_meta_assets(
                client_id="amalie", connection_id="meta-auth",
                page_id="123", instagram_id="999",
            )
        self.assertEqual(result["instagram"]["id"], "999")

    async def test_activation_updates_one_projection_and_preserves_ads_metadata(self):
        authorization = {
            "id": "meta-auth", "client_id": "amalie", "provider": "meta",
            "scopes": ["instagram_basic"], "token_expires_at": None,
        }
        previous = {
            "selected_ad_account_id": "act_673785144083881",
            "ad_account_ids": ["act_673785144083881"], "ads_status": "connected",
        }
        updates = AsyncMock(return_value=[])
        with (
            patch.object(meta_oauth, "_manual_meta_connection", AsyncMock(return_value=(authorization, "safe-token", previous))),
            patch.object(meta_oauth, "validate_manual_meta_assets", AsyncMock(return_value={
                "page": {"id": "page-1", "name": "Amalie"},
                "instagram": {"id": "ig-1", "username": "amalie"},
            })),
            patch.object(meta_oauth, "sb_select", AsyncMock(side_effect=[[{
                "id": "organic-1", "client_id": "amalie", "platform": "instagram",
                "connection_type": "organic", "status": "error", "is_active": True,
            }], [{
                "id": "organic-1", "client_id": "amalie", "platform": "instagram",
                "connection_type": "organic", "status": "pending", "is_active": True,
                "ig_user_id": "ig-1",
            }]])),
            patch.object(meta_oauth, "sb_update", updates),
            patch.object(meta_oauth, "sb_insert", AsyncMock()) as insert,
            patch.object(meta_oauth, "audit_connection", AsyncMock()),
            patch.object(meta_oauth, "invalidate_namespace", AsyncMock()),
            patch.object(meta_oauth, "encrypt_secret", return_value="encrypted"),
        ):
            result = await meta_oauth.activate_meta_organic_assets(
                user_id="user-1", client_id="amalie", connection_id="meta-auth",
                page_id="page-1", instagram_id="ig-1",
            )
        self.assertEqual(result["organic_connection_id"], "organic-1")
        insert.assert_not_awaited()
        integration_patch = updates.await_args_list[1].kwargs["patch"]
        self.assertEqual(integration_patch["metadata"]["selected_ad_account_id"], "act_673785144083881")
        self.assertEqual(integration_patch["metadata"]["ads_status"], "connected")
        self.assertEqual(integration_patch["metadata"]["organic_status"], "syncing")

    async def test_activation_route_does_not_report_success_when_initial_sync_fails(self):
        with (
            patch.object(meta_routes, "require_user_id", AsyncMock(return_value="user-1")),
            patch.object(meta_routes, "require_client_role", AsyncMock(return_value="amalie")),
            patch.object(meta_routes, "activate_meta_organic_assets", AsyncMock(return_value={
                "authorization_connection_id": "meta-auth", "organic_connection_id": "organic-1",
                "page_id": "page-1", "instagram_id": "ig-1",
            })),
            patch.object(meta_routes, "sync_instagram_connection", AsyncMock(side_effect=RuntimeError("upstream"))),
            patch.object(meta_routes, "finalize_meta_organic_activation", AsyncMock()) as finalize,
        ):
            result = await meta_routes.api_activate_meta_organic(
                "meta-auth", {"page_id": "page-1", "instagram_id": "ig-1"},
                SimpleNamespace(state=SimpleNamespace(request_id="req-meta")),
                client_id="amalie", authorization="Bearer safe",
            )
        self.assertFalse(result["ok"])
        self.assertFalse(result["initial_sync"]["ok"])
        self.assertEqual(result["code"], "META_GRAPH_UNAVAILABLE")
        self.assertFalse(finalize.await_args.kwargs["succeeded"])


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

    async def test_connection_resolver_rejects_ambiguous_active_connections(self):
        rows = [
            {"id": "organic-a", "client_id": "amalie", "provider": "meta", "status": "connected", "is_active": True},
            {"id": "organic-b", "client_id": "amalie", "provider": "meta", "status": "connected", "is_active": True},
        ]
        with self.assertRaises(connection_resolver.IntegrationError) as raised:
            await connection_resolver.resolve_generic_connection(
                client_id="amalie", provider="meta", candidate_rows=rows,
            )
        self.assertEqual(raised.exception.code, "CONNECTION_AMBIGUOUS")
        self.assertEqual(raised.exception.status_code, 409)

    async def test_connection_resolver_never_falls_back_to_disconnected_connection(self):
        with self.assertRaises(connection_resolver.IntegrationError) as raised:
            await connection_resolver.resolve_generic_connection(
                client_id="amalie", provider="meta",
                requested_connection_id="organic-old",
                candidate_rows=[{"id": "organic-old", "client_id": "amalie", "provider": "meta", "status": "disconnected", "is_active": False}],
            )
        self.assertEqual(raised.exception.code, "CONNECTION_DISCONNECTED")

    def test_meta_sanitization_exposes_real_token_availability(self):
        sanitized = generic_connections.sanitize_connection({
            "id": "meta-1", "client_id": "amalie", "provider": "meta",
            "status": "connected", "encrypted_token": "",
        })
        self.assertFalse(sanitized["token_available"])


class MetaOrganicConfigurationTests(unittest.IsolatedAsyncioTestCase):
    async def test_link_assets_rejects_multiple_instagram_selection_before_persistence(self):
        handoff = {
            "handoff": "handoff-1", "user_id": "user-amalie", "client_id": "amalie",
            "encrypted_access_token": "encrypted",
            "instagram_accounts_json": [
                {"ig_user_id": "ig-1", "business_id": "page-1"},
                {"ig_user_id": "ig-2", "business_id": "page-2"},
            ],
            "ad_accounts_json": [],
        }
        insert = AsyncMock()
        with (
            patch.object(meta_oauth, "_load_handoff_row", AsyncMock(return_value=handoff)),
            patch.object(meta_oauth, "decrypt_secret", return_value="safe-token"),
            patch.object(meta_oauth, "sb_insert", insert),
        ):
            with self.assertRaises(meta_oauth.IntegrationError) as raised:
                await meta_oauth.save_connections(
                    user_id="user-amalie", client_id="amalie", handoff="handoff-1",
                    page_ids=["page-1", "page-2"],
                    instagram_ig_user_ids=["ig-1", "ig-2"], ad_account_ids=[],
                )
        self.assertEqual(raised.exception.code, "META_INSTAGRAM_SELECTION_AMBIGUOUS")
        insert.assert_not_awaited()

    async def test_page_discovery_follows_all_pages_without_auto_selecting_tenant(self):
        first_pages = {
            "data": [{"id": "page-amalie", "name": "Amalie", "instagram_business_account": {"id": "ig-amalie", "username": "amalie"}}],
            "paging": {"next": "https://graph.facebook.com/next-pages"},
        }
        second_pages = {
            "data": [{"id": "page-roove", "name": "Roove", "instagram_business_account": {"id": "ig-roove", "username": "roove"}}],
        }
        with (
            patch.object(meta_oauth, "_meta_get", AsyncMock(side_effect=[
                {"id": "julia", "name": "Julia"}, first_pages,
                first_pages["data"][0], second_pages["data"][0],
            ])),
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
            {"id": "page-1", "name": "Amalie", "instagram_business_account": {"id": "ig-1", "username": "amalie"}},
            {"id": "page-2", "name": "Sem Instagram"},
        ]
        with patch.object(meta_oauth, "_meta_get", AsyncMock(side_effect=responses)):
            result = await meta_oauth.fetch_instagram_identity("safe-token")
        self.assertEqual([page["page_id"] for page in result["pages"]], ["page-1", "page-2"])
        self.assertEqual([item["ig_user_id"] for item in result["instagram_accounts"]], ["ig-1"])

    async def test_handoff_diagnostic_keeps_amalie_and_roove_unselected_and_tenant_scoped(self):
        row = {
            "handoff": "fresh-amalie-handoff", "user_id": "user-julia", "client_id": "amalie",
            "meta_user_json": {"id": "julia", "name": "Julia", "business_managers": [{"business_id": "bm-1", "business_name": "Mugô"}]},
            "pages_json": [
                {"page_id": "page-amalie", "page_name": "Amalie"},
                {"page_id": "page-roove", "page_name": "Roove"},
            ],
            "instagram_accounts_json": [
                {"ig_user_id": "ig-amalie", "username": "amalie", "business_id": "page-amalie", "business_name": "Amalie"},
                {"ig_user_id": "ig-roove", "username": "roove", "business_id": "page-roove", "business_name": "Roove"},
            ],
            "ad_accounts_json": [
                {"ad_account_id": "act_1", "ad_account_name": "Ads Amalie"},
                {"ad_account_id": "act_2", "ad_account_name": "Ads Roove"},
            ],
            "scopes_json": ["pages_show_list", "instagram_basic", "ads_read"],
        }
        load = AsyncMock(return_value=row)
        with patch.object(meta_oauth, "_load_handoff_row", load):
            result = await meta_oauth.read_discovery_handoff(
                handoff="fresh-amalie-handoff", user_id="user-julia", client_id="amalie"
            )
        self.assertEqual(result["client_id"], "amalie")
        self.assertEqual(result["authorized_user_name"], "Julia")
        self.assertEqual(result["page_count"], 2)
        self.assertEqual(result["ad_account_count"], 2)
        self.assertEqual([page["name"] for page in result["pages"]], ["Amalie", "Roove"])
        self.assertTrue(all("selected" not in page for page in result["pages"]))
        load.assert_awaited_once_with(handoff="fresh-amalie-handoff")

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
            patch.object(meta_oauth, "sb_select", AsyncMock(side_effect=[[], [], [], [previous]])),
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
            "status": "connected", "disconnected_at": None,
            "metadata": metadata or {}, "_token": json.dumps({"access_token": "safe-token"}),
        }

    async def test_manual_assets_reject_disconnected_meta_connection_before_graph_call(self):
        connection = {**self._manual_connection(), "status": "disconnected", "disconnected_at": "2026-08-04T00:00:00Z"}
        graph = AsyncMock()
        with (
            patch.object(meta_oauth, "get_connection", AsyncMock(return_value=connection)),
            patch.object(meta_oauth, "_meta_get", graph),
        ):
            with self.assertRaises(meta_oauth.IntegrationError) as raised:
                await meta_oauth.validate_manual_meta_assets(
                    client_id="amalie", connection_id="meta-old", page_id="123"
                )
        self.assertEqual(raised.exception.code, "META_CONNECTION_DISCONNECTED")
        graph.assert_not_awaited()

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
    def test_property_id_normalization_never_duplicates_prefix(self):
        self.assertEqual(ga4_client.normalize_ga4_property_id("123456789"), "123456789")
        self.assertEqual(ga4_client.normalize_ga4_property_id("properties/123456789"), "123456789")

    def test_run_report_body_omits_empty_dimensions_and_null_fields(self):
        body = ga4_client._build_run_report_body(
            start_date="2026-08-01", end_date="2026-08-02",
            dimensions=(), metrics=("activeUsers",), limit=100, offset=0,
        )
        self.assertNotIn("dimensions", body)
        self.assertNotIn(None, body.values())
        self.assertNotIn("stream_id", str(body))


class Ga4ReportIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_builds_seven_valid_report_payloads(self):
        report = AsyncMock(return_value={"rows": [], "row_count": 0})
        with patch.object(ga4_sync, "run_ga4_report", report):
            result = await ga4_sync._sync_ga4_for_period(
                client_id="amalie", property_id="properties/123456789",
                access_token="safe", days=1, record_job_run=False,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(report.await_count, 7)
        for call in report.await_args_list:
            self.assertEqual(call.kwargs["property_id"], "123456789")
            self.assertLessEqual(len(call.kwargs["metrics"]), 10)
            self.assertNotIn("stream_id", call.kwargs)
            self.assertTrue(all(call.kwargs["metrics"]))
            self.assertTrue(all(call.kwargs["dimensions"]))

    async def test_sync_identifies_the_exact_failing_report(self):
        error = google_oauth.IntegrationError(
            "Métrica inválida.", status_code=400,
            code="GA4_INVALID_METRIC", provider="google",
        )
        report = AsyncMock(side_effect=[{"rows": [], "row_count": 0}, error])
        with patch.object(ga4_sync, "run_ga4_report", report):
            with self.assertRaises(google_oauth.IntegrationError) as raised:
                await ga4_sync._sync_ga4_for_period(
                    client_id="amalie", property_id="123456789",
                    access_token="safe", days=1, record_job_run=False,
                )
        self.assertEqual(raised.exception.diagnostics["report"], "channels")

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

    async def test_valid_token_paginates_all_three_properties(self):
        responses = [
            httpx.Response(
                200, request=httpx.Request("GET", "https://analyticsadmin.googleapis.com/v1beta/accountSummaries"),
                json={
                    "accountSummaries": [{
                        "account": "accounts/1", "displayName": "Amalie",
                        "propertySummaries": [
                            {"property": "properties/1", "displayName": "Site"},
                            {"property": "properties/2", "displayName": "App"},
                        ],
                    }],
                    "nextPageToken": "page-2",
                },
            ),
            httpx.Response(
                200, request=httpx.Request("GET", "https://analyticsadmin.googleapis.com/v1beta/accountSummaries"),
                json={"accountSummaries": [{
                    "account": "accounts/2", "displayName": "Loja",
                    "propertySummaries": [{"property": "properties/3", "displayName": "E-commerce"}],
                }]},
            ),
        ]

        class FakeClient:
            def __init__(self): self.calls = []
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return None
            async def get(self, *args, **kwargs):
                self.calls.append(kwargs.get("params") or {})
                return responses[len(self.calls) - 1]

        fake = FakeClient()
        row = {
            "provider": "ga4", "status": "connected", "disconnected_at": None,
            "_token": json.dumps({"access_token": "valid", "expires_at": "2099-01-01T00:00:00+00:00"}),
        }
        with (
            patch.object(google_oauth, "get_connection", AsyncMock(return_value=row)),
            patch.object(google_oauth.httpx, "AsyncClient", return_value=fake),
        ):
            properties = await google_oauth.list_ga4_properties("amalie", "ga4-1", request_id="req-pages")
        self.assertEqual([item["property"] for item in properties], ["properties/1", "properties/2", "properties/3"])
        self.assertNotIn("pageToken", fake.calls[0])
        self.assertEqual(fake.calls[1]["pageToken"], "page-2")

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
