import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import api_support
from routes import google_oauth as google_routes
from routes import meta_legacy as meta_routes
from routes import shopify_oauth as shopify_routes
from server.services import ga4_connections, shopify_oauth
from server.services.generic_connections import google_capabilities
from server.services.integration_errors import (
    IntegrationError,
    from_httpx_error,
    provider_http_error,
)
from server.services import shopify_config


def google_row(*, metadata=None, status="connected", client_id="roove"):
    return {
        "id": "google-connection",
        "client_id": client_id,
        "provider": "ga4",
        "status": status,
        "external_key": "google-user",
        "scopes": [ga4_connections.GA4_READ_SCOPE],
        "metadata": metadata or {},
        "updated_at": "2026-07-31T00:00:00Z",
    }


def shopify_row(
    *,
    client_id="roove",
    token_payload=None,
    scopes=None,
    status="connected",
):
    return {
        "id": "shopify-connection",
        "client_id": client_id,
        "provider": "shopify",
        "status": status,
        "external_key": "Minha-Loja.myshopify.com",
        "scopes": scopes
        if scopes is not None
        else ["read_orders", "read_customers", "read_products"],
        "metadata": {
            "shop_domain": "https://Minha-Loja.myshopify.com/",
            "selected_for_reporting": True,
        },
        "_token": token_payload
        if token_payload is not None
        else json.dumps({"access_token": "private-shopify-token"}),
    }


class GA4ConnectionResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_ads_only_connection_stops_before_ga4_property_request(self):
        ads_only = google_row() | {
            "scopes": ["https://www.googleapis.com/auth/adwords"],
        }
        with (
            patch.object(google_routes, "require_client_read", AsyncMock(return_value="roove")),
            patch.object(google_routes, "get_connection", AsyncMock(return_value=ads_only)),
            patch.object(google_routes, "list_ga4_properties", AsyncMock()) as list_properties,
        ):
            with self.assertRaises(RuntimeError) as raised:
                await google_routes.ga4_properties(
                    "google-connection",
                    client_id="roove",
                    authorization="Bearer safe",
                )
        self.assertEqual(getattr(raised.exception, "code", ""), "GOOGLE_SCOPE_INSUFFICIENT")
        list_properties.assert_not_awaited()

    async def test_ga4_property_discovery_uses_tenant_read_permission(self):
        read_access = AsyncMock(return_value="roove")
        properties = AsyncMock(return_value=[{"property": "properties/123"}])
        with (
            patch.object(google_routes, "require_client_read", read_access),
            patch.object(
                google_routes,
                "get_connection",
                AsyncMock(return_value=google_row()),
            ),
            patch.object(google_routes, "list_ga4_properties", properties),
        ):
            result = await google_routes.ga4_properties(
                "google-connection",
                client_id="roove",
                authorization="Bearer safe",
            )
        self.assertEqual(result["properties"], [{"property": "properties/123"}])
        read_access.assert_awaited_once_with("roove", "Bearer safe")

    async def test_ga4_selection_persists_property_account_and_name(self):
        with (
            patch.object(google_routes, "require_client_role", AsyncMock(return_value="roove")),
            patch.object(google_routes, "require_user_id", AsyncMock(return_value="user-roove")),
            patch.object(
                google_routes,
                "get_connection",
                AsyncMock(
                    return_value=google_row()
                    | {"scopes": ["https://www.googleapis.com/auth/analytics.readonly"]}
                ),
            ),
            patch.object(
                google_routes,
                "update_connection_selection",
                AsyncMock(return_value={"id": "google-connection"}),
            ) as update,
            patch.object(
                google_routes,
                "list_ga4_streams",
                AsyncMock(return_value=[{"name": "properties/123456/dataStreams/stream-1", "display_name": "Web"}]),
            ),
        ):
            await google_routes.select_ga4(
                "google-connection",
                {
                    "property_id": "properties/123456",
                    "account_id": "accounts/789",
                    "property_name": "Roove Web",
                    "stream_id": "stream-1",
                },
                client_id="roove",
                authorization="Bearer safe",
            )
        metadata = update.await_args.kwargs["metadata_patch"]
        self.assertEqual(metadata["ga4_property_id"], "123456")
        self.assertEqual(metadata["ga4_account_id"], "accounts/789")
        self.assertEqual(metadata["ga4_property_name"], "Roove Web")

    def test_ads_only_token_keeps_ga4_incomplete(self):
        capabilities = google_capabilities(
            google_row(
                metadata={"google_ads_customer_id": "1234567890", "ads_developer_token_configured": True},
                status="connected",
            )
            | {
                "provider": "google_ads",
                "scopes": ["openid", "email", "https://www.googleapis.com/auth/adwords"],
            }
        )
        self.assertTrue(capabilities["ads_authorized"])
        self.assertTrue(capabilities["ads_configured"])
        self.assertEqual(capabilities["ads_status"], "connected")
        self.assertFalse(capabilities["ga4_authorized"])
        self.assertEqual(capabilities["ga4_status"], "authorization_required")

    def test_ads_oauth_without_developer_token_is_setup_required(self):
        capabilities = google_capabilities(
            google_row(metadata={"ads_developer_token_configured": False})
            | {
                "provider": "google_ads",
                "scopes": ["https://www.googleapis.com/auth/adwords"],
            }
        )
        self.assertTrue(capabilities["ads_authorized"])
        self.assertFalse(capabilities["ads_configured"])
        self.assertEqual(capabilities["ads_status"], "setup_required")

    def test_ga4_scope_requires_property_before_connected(self):
        capabilities = google_capabilities(
            google_row()
            | {"scopes": ["https://www.googleapis.com/auth/analytics.readonly"]}
        )
        self.assertTrue(capabilities["ga4_authorized"])
        self.assertFalse(capabilities["ga4_configured"])
        self.assertEqual(capabilities["ga4_status"], "property_required")

    async def test_ga4_property_comes_from_oauth_metadata(self):
        select = AsyncMock(
            return_value=[
                google_row(metadata={"ga4_property_id": "properties/123456"})
            ]
        )
        with patch.object(ga4_connections, "sb_select", select):
            context = await ga4_connections.resolve_ga4_connection_context("roove")
        self.assertEqual(context.client_id, "roove")
        self.assertEqual(context.property_id, "123456")
        self.assertEqual(context.connection_id, "google-connection")
        self.assertEqual(context.auth_mode, "oauth")
        self.assertEqual(select.await_args.kwargs["filters"]["client_id"], "eq.roove")

    async def test_ga4_legacy_environment_is_fallback_only_without_oauth(self):
        with (
            patch.object(ga4_connections, "sb_select", AsyncMock(return_value=[])),
            patch.object(
                ga4_connections,
                "resolve_ga4_context_for_client",
                return_value=("roove", "properties/legacy-987"),
            ),
        ):
            context = await ga4_connections.resolve_ga4_connection_context("roove")
        self.assertEqual(context.property_id, "legacy-987")
        self.assertIsNone(context.connection_id)
        self.assertEqual(context.auth_mode, "legacy")

    async def test_ga4_property_selection_pending_is_409(self):
        with patch.object(
            ga4_connections,
            "sb_select",
            AsyncMock(return_value=[google_row(status="selection_required")]),
        ):
            with self.assertRaises(IntegrationError) as raised:
                await ga4_connections.resolve_ga4_connection_context("roove")
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.code, "ACCOUNT_SELECTION_REQUIRED")
        self.assertEqual(raised.exception.provider, "ga4")

    async def test_ga4_connection_cannot_cross_tenants(self):
        with patch.object(
            ga4_connections,
            "sb_select",
            AsyncMock(
                return_value=[
                    google_row(
                        client_id="other-company",
                        metadata={"ga4_property_id": "123"},
                    )
                ]
            ),
        ):
            with self.assertRaises(IntegrationError) as raised:
                await ga4_connections.resolve_ga4_connection_context("roove")
        self.assertEqual(raised.exception.status_code, 403)


class MetaCallbackPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_callback_persists_pending_connection_before_success_redirect(self):
        request = type("Request", (), {"url": type("URL", (), {"scheme": "https", "netloc": "api.example"})()})()
        pending = AsyncMock(return_value={"id": "meta-base"})
        with (
            patch.object(
                meta_routes,
                "consume_oauth_state",
                AsyncMock(return_value={"user_id": "user-roove", "client_id": "roove"}),
            ),
            patch.object(meta_routes, "require_user_client_access", AsyncMock()),
            patch.object(meta_routes, "resolve_meta_redirect_uri", return_value="https://api.example/api/oauth/meta/callback"),
            patch.object(
                meta_routes,
                "exchange_code_for_token",
                AsyncMock(return_value={"access_token": "secret-token", "expires_at": "2026-09-01T00:00:00Z"}),
            ),
            patch.object(
                meta_routes,
                "discover_assets",
                AsyncMock(return_value={"meta_user": {"id": "meta-user"}, "instagram_accounts": [], "ad_accounts": [], "scopes": []}),
            ),
            patch.object(meta_routes, "create_discovery_handoff", AsyncMock(return_value="safe-handoff")),
            patch.object(meta_routes, "save_pending_meta_authorization", pending),
            patch.dict(os.environ, {"FRONTEND_URL": "https://dados.mugoagencia.com.br"}, clear=False),
        ):
            response = await meta_routes.api_oauth_meta_callback(request, code="secret-code", state="secret-state")
        self.assertEqual(response.status_code, 302)
        self.assertIn("meta_oauth=success", response.headers["location"])
        self.assertIn("handoff=safe-handoff", response.headers["location"])
        pending.assert_awaited_once()
        self.assertEqual(pending.await_args.kwargs["handoff"], "safe-handoff")

    async def test_callback_never_redirects_success_when_persistence_fails(self):
        request = type("Request", (), {"url": type("URL", (), {"scheme": "https", "netloc": "api.example"})()})()
        with (
            patch.object(
                meta_routes,
                "consume_oauth_state",
                AsyncMock(return_value={"user_id": "user-roove", "client_id": "roove"}),
            ),
            patch.object(meta_routes, "require_user_client_access", AsyncMock()),
            patch.object(meta_routes, "resolve_meta_redirect_uri", return_value="https://api.example/api/oauth/meta/callback"),
            patch.object(meta_routes, "exchange_code_for_token", AsyncMock(return_value={"access_token": "secret-token"})),
            patch.object(
                meta_routes,
                "discover_assets",
                AsyncMock(return_value={"meta_user": {"id": "meta-user"}, "instagram_accounts": [], "ad_accounts": [], "scopes": []}),
            ),
            patch.object(meta_routes, "create_discovery_handoff", AsyncMock(return_value="safe-handoff")),
            patch.object(meta_routes, "save_pending_meta_authorization", AsyncMock(side_effect=RuntimeError("database unavailable"))),
            patch.dict(os.environ, {"FRONTEND_URL": "https://dados.mugoagencia.com.br"}, clear=False),
        ):
            response = await meta_routes.api_oauth_meta_callback(request, code="secret-code", state="secret-state")
        self.assertEqual(response.status_code, 302)
        self.assertIn("meta_oauth=error", response.headers["location"])
        self.assertNotIn("meta_oauth=success", response.headers["location"])


class GoogleCallbackPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_ga4_callback_persists_product_before_success_redirect(self):
        request = SimpleNamespace(state=SimpleNamespace())
        save = AsyncMock(return_value={"id": "ga4-connection"})
        with (
            patch.object(
                google_routes,
                "consume_oauth_state",
                AsyncMock(
                    return_value={
                        "user_id": "user-roove",
                        "client_id": "roove",
                        "redirect_uri": "https://api.example/api/oauth/google/callback",
                        "context": {"integration_product": "ga4"},
                    }
                ),
            ),
            patch.object(google_routes, "require_user_client_access", AsyncMock()),
            patch.object(
                google_routes,
                "exchange_code",
                AsyncMock(return_value={"access_token": "secret-token", "refresh_token": "secret-refresh"}),
            ),
            patch.object(
                google_routes,
                "fetch_google_identity",
                AsyncMock(return_value={"sub": "google-user", "email": "roove@example.com"}),
            ),
            patch.object(google_routes, "save_google_authorization", save),
            patch.dict(os.environ, {"FRONTEND_URL": "https://dados.mugoagencia.com.br"}, clear=False),
        ):
            response = await google_routes.callback(request, code="secret-code", state="secret-state", error=None)
        self.assertEqual(response.status_code, 302)
        self.assertIn("google_oauth=success", response.headers["location"])
        self.assertIn("integration_product=ga4", response.headers["location"])
        self.assertEqual(save.await_args.kwargs["product"], "ga4")
        self.assertEqual(request.state.integration_product, "ga4")

    async def test_google_callback_reports_error_when_database_save_fails(self):
        request = SimpleNamespace(state=SimpleNamespace())
        with (
            patch.object(
                google_routes,
                "consume_oauth_state",
                AsyncMock(
                    return_value={
                        "user_id": "user-roove",
                        "client_id": "roove",
                        "redirect_uri": "https://api.example/api/oauth/google/callback",
                        "context": {"integration_product": "google_ads"},
                    }
                ),
            ),
            patch.object(google_routes, "require_user_client_access", AsyncMock()),
            patch.object(google_routes, "exchange_code", AsyncMock(return_value={"access_token": "secret-token"})),
            patch.object(
                google_routes,
                "fetch_google_identity",
                AsyncMock(return_value={"sub": "google-user", "email": "roove@example.com"}),
            ),
            patch.object(
                google_routes,
                "save_google_authorization",
                AsyncMock(side_effect=RuntimeError("database unavailable")),
            ),
            patch.dict(os.environ, {"FRONTEND_URL": "https://dados.mugoagencia.com.br"}, clear=False),
        ):
            response = await google_routes.callback(request, code="secret-code", state="secret-state", error=None)
        self.assertIn("google_oauth=error", response.headers["location"])
        self.assertNotIn("google_oauth=success", response.headers["location"])


class ShopifyConnectionResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_shopify_start_logs_only_safe_configuration_fields(self):
        output = io.StringIO()
        authorization = (
            "https://roove.myshopify.com/admin/oauth/authorize?"
            "client_id=public-client&scope=read_orders%2Cread_customers%2Cread_products&"
            "redirect_uri=https%3A%2F%2Fapi.dados.mugoagencia.com.br%2Fapi%2Foauth%2Fshopify%2Fcallback&"
            "state=secret-state-value"
        )
        with (
            patch.object(shopify_routes, "require_client_role", AsyncMock(return_value="roove")),
            patch.object(shopify_routes, "require_user_id", AsyncMock(return_value="user-roove")),
            patch.object(shopify_routes, "authorization_url", AsyncMock(return_value=authorization)),
            patch.object(
                shopify_routes,
                "safe_oauth_configuration",
                return_value={
                    "redirect_uri": "https://api.dados.mugoagencia.com.br/api/oauth/shopify/callback",
                    "client_id_hint": "...client",
                },
            ),
            redirect_stdout(output),
        ):
            result = await shopify_routes.start(
                shop="roove.myshopify.com",
                client_id="roove",
                authorization="Bearer safe",
            )
        log = output.getvalue()
        self.assertEqual(result["authorization_url"], authorization)
        self.assertIn("shop=roove.myshopify.com", log)
        self.assertIn("client_id_present=yes", log)
        self.assertIn("state_present=yes", log)
        self.assertNotIn("secret-state-value", log)

    async def _resolve(self, full_row, *, required_scopes=()):
        summary = {key: value for key, value in full_row.items() if key != "_token"}
        with (
            patch.object(shopify_oauth, "sb_select", AsyncMock(return_value=[summary])) as select,
            patch.object(shopify_oauth, "get_connection", AsyncMock(return_value=full_row)),
        ):
            context = await shopify_oauth.resolve_shopify_connection_context(
                "roove",
                required_scopes=required_scopes,
            )
        self.assertEqual(select.await_args.kwargs["filters"]["client_id"], "eq.roove")
        return context

    async def test_valid_shopify_oauth_connection_is_used(self):
        context = await self._resolve(
            shopify_row(),
            required_scopes=("read_orders", "read_products"),
        )
        self.assertEqual(context.connection_id, "shopify-connection")
        self.assertEqual(context.shop_domain, "minha-loja.myshopify.com")
        self.assertEqual(context.auth_mode, "oauth")
        self.assertTrue(context.access_token)

    def test_shopify_domain_is_normalized(self):
        self.assertEqual(
            shopify_oauth.normalize_shop_domain(
                "  https://Minha-Loja.myshopify.com///  "
            ),
            "minha-loja.myshopify.com",
        )

    def test_shopify_admin_api_version_is_centralized(self):
        self.assertEqual(shopify_config.SHOPIFY_ADMIN_API_VERSION, "2026-07")
        self.assertEqual(
            shopify_config.shopify_admin_url(
                "minha-loja.myshopify.com",
                "orders.json",
            ),
            "https://minha-loja.myshopify.com/admin/api/2026-07/orders.json",
        )

    async def test_missing_shopify_connection_is_404(self):
        with (
            patch.object(shopify_oauth, "sb_select", AsyncMock(return_value=[])),
            patch.dict(os.environ, {}, clear=False),
        ):
            for name in (
                "SHOPIFY_SHOP_DOMAIN",
                "SHOPIFY_STORE_DOMAIN",
                "SHOPIFY_ACCESS_TOKEN",
                "SHOPIFY_ADMIN_ACCESS_TOKEN",
            ):
                os.environ.pop(name, None)
            with self.assertRaises(IntegrationError) as raised:
                await shopify_oauth.resolve_shopify_connection_context("roove")
        self.assertEqual(raised.exception.status_code, 404)

    async def test_invalid_shopify_token_is_401(self):
        with self.assertRaises(IntegrationError) as raised:
            await self._resolve(shopify_row(token_payload="{invalid"))
        self.assertEqual(raised.exception.status_code, 401)

    async def test_insufficient_shopify_scope_is_403(self):
        with self.assertRaises(IntegrationError) as raised:
            await self._resolve(
                shopify_row(scopes=["read_products"]),
                required_scopes=("read_orders",),
            )
        self.assertEqual(raised.exception.status_code, 403)

    async def test_explicit_connection_from_another_tenant_is_hidden(self):
        with patch.object(
            shopify_oauth,
            "get_connection",
            AsyncMock(side_effect=RuntimeError("other tenant")),
        ):
            with self.assertRaises(IntegrationError) as raised:
                await shopify_oauth.resolve_shopify_connection_context(
                    "roove",
                    connection_id="other-company-connection",
                )
        self.assertEqual(raised.exception.status_code, 404)
        self.assertNotIn("other tenant", str(raised.exception))

    async def test_legacy_shopify_fallback_is_supported(self):
        with (
            patch.object(shopify_oauth, "sb_select", AsyncMock(return_value=[])),
            patch.dict(
                os.environ,
                {
                    "SHOPIFY_STORE_DOMAIN": "https://legacy.myshopify.com/",
                    "SHOPIFY_ACCESS_TOKEN": "legacy-private-token",
                },
                clear=False,
            ),
        ):
            context = await shopify_oauth.resolve_shopify_connection_context(
                "roove",
                required_scopes=("read_orders",),
            )
        self.assertEqual(context.shop_domain, "legacy.myshopify.com")
        self.assertEqual(context.auth_mode, "legacy")

    async def test_valid_callback_persists_connection_and_starts_first_sync(self):
        background_tasks = type("BackgroundTasks", (), {"add_task": Mock()})()
        request = type(
            "Request",
            (),
            {
                "query_params": {
                    "code": "secret-code",
                    "state": "secret-state",
                    "shop": "roove.myshopify.com",
                    "hmac": "valid-hmac",
                }
            },
        )()
        session = {
            "user_id": "user-roove",
            "client_id": "roove",
            "redirect_uri": shopify_oauth.SHOPIFY_PRODUCTION_REDIRECT_URI,
            "context": {"shop_domain": "roove.myshopify.com"},
        }
        with (
            patch.object(shopify_routes, "verify_callback_hmac", return_value=True),
            patch.object(shopify_routes, "consume_oauth_state", AsyncMock(return_value=session)),
            patch.object(
                shopify_routes,
                "safe_oauth_configuration",
                return_value={"redirect_uri": shopify_oauth.SHOPIFY_PRODUCTION_REDIRECT_URI},
            ),
            patch.object(shopify_routes, "require_user_client_access", AsyncMock()),
            patch.object(
                shopify_routes,
                "exchange_code",
                AsyncMock(return_value={"access_token": "secret-token", "scope": "read_orders"}),
            ),
            patch.object(shopify_routes, "fetch_shop", AsyncMock(return_value={"id": 1, "name": "Roove"})),
            patch.object(shopify_routes, "register_webhooks", AsyncMock()),
            patch.object(
                shopify_routes,
                "save_shopify_connection",
                AsyncMock(return_value={"id": "shopify-connection"}),
            ) as save,
            patch.object(shopify_routes, "sync_shopify_connection", AsyncMock(return_value={"ok": True})) as sync,
            patch.dict(os.environ, {"FRONTEND_URL": "https://dados.mugoagencia.com.br"}, clear=False),
        ):
            response = await shopify_routes.callback(request, background_tasks)
        self.assertEqual(response.status_code, 302)
        self.assertIn("shopify_oauth=success", response.headers["location"])
        for secret in ("secret-code", "secret-state", "secret-token"):
            self.assertNotIn(secret, response.headers["location"])
        save.assert_awaited_once()
        background_tasks.add_task.assert_called_once_with(
            sync,
            client_id="roove",
            connection_id="shopify-connection",
        )
        sync.assert_not_awaited()


class IntegrationErrorSafetyTests(unittest.TestCase):
    def test_shopify_429_and_upstream_failures_keep_safe_statuses(self):
        limited = provider_http_error(
            "shopify",
            429,
            operation="consultar pedidos",
        )
        failed = provider_http_error(
            "shopify",
            500,
            operation="consultar pedidos",
        )
        unavailable = provider_http_error(
            "shopify",
            503,
            operation="consultar pedidos",
        )
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(failed.status_code, 502)
        self.assertEqual(unavailable.status_code, 503)

    def test_error_response_and_logs_never_contain_secrets(self):
        secret = "private-token-for-test"
        request = httpx.Request(
            "GET",
            "https://store.myshopify.com/admin/api/2026-07/shop.json",
            headers={"X-Shopify-Access-Token": secret},
        )
        response = httpx.Response(
            401,
            request=request,
            json={"errors": f"invalid token {secret}"},
        )
        error = from_httpx_error(
            "shopify",
            httpx.HTTPStatusError(
                "unauthorized",
                request=request,
                response=response,
            ),
            operation="consultar a loja",
        )
        response = api_support._structured_error_response(
            endpoint="/api/shopify/report",
            exc=error,
            status_code=error.status_code,
            code="shopify_report_runtime_error",
        )
        body = response.body.decode("utf-8")
        output = io.StringIO()
        with redirect_stdout(output):
            api_support._log_endpoint_error(
                endpoint="/api/shopify/report",
                exc=error,
                user_id="user",
                x_client_id=None,
                client_id="roove",
            )
        self.assertNotIn(secret, body)
        self.assertNotIn(secret, output.getvalue())
        self.assertNotIn("Authorization", output.getvalue())
        self.assertNotIn("refresh_token", output.getvalue())


if __name__ == "__main__":
    unittest.main()
