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
from services import generic_connections
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


class ShopifyReauthorizationPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_shop_updates_existing_connection_id_instead_of_inserting(self):
        existing = {
            "id": "shopify-connection-amalie",
            "client_id": "amalie",
            "provider": "shopify",
            "external_key": "amalie-6421.myshopify.com",
            "status": "connected",
            "metadata": {"shop_domain": "amalie-6421.myshopify.com"},
            "scopes": ["read_orders"],
        }
        insert = AsyncMock()
        with (
            patch.object(generic_connections, "sb_select", AsyncMock(return_value=[existing])),
            patch.object(
                generic_connections, "sb_update",
                AsyncMock(return_value=[{**existing, "scopes": list(shopify_oauth.SHOPIFY_SCOPES)}]),
            ) as update,
            patch.object(generic_connections, "sb_insert", insert),
            patch.object(generic_connections, "encrypt_secret", return_value="encrypted-token"),
            patch.object(generic_connections, "audit_connection", AsyncMock()),
            patch.object(generic_connections, "invalidate_namespace", AsyncMock()),
        ):
            result = await generic_connections.upsert_connection(
                client_id="amalie",
                provider="shopify",
                external_key="amalie-6421.myshopify.com",
                token_payload='{"access_token":"secret-token"}',
                user_id="user-amalie",
                status="connected",
                scopes=list(shopify_oauth.SHOPIFY_SCOPES),
                metadata={"shop_domain": "amalie-6421.myshopify.com"},
            )

        self.assertEqual(result["id"], "shopify-connection-amalie")
        self.assertEqual(update.await_args.kwargs["filters"]["id"], "eq.shopify-connection-amalie")
        insert.assert_not_awaited()


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
            context = await ga4_connections.resolve_ga4_connection_context(
                "roove", connection_id="google-connection"
            )
        self.assertEqual(context.client_id, "roove")
        self.assertEqual(context.property_id, "123456")
        self.assertEqual(context.connection_id, "google-connection")
        self.assertEqual(context.auth_mode, "oauth")
        self.assertEqual(select.await_args.kwargs["filters"]["id"], "eq.google-connection")

    async def test_ga4_without_connection_id_reports_not_found_when_tenant_has_none(self):
        with (
            patch.object(ga4_connections, "sb_select", AsyncMock(return_value=[])),
        ):
            with self.assertRaises(IntegrationError) as raised:
                await ga4_connections.resolve_ga4_connection_context("roove")
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.code, "CONNECTION_NOT_FOUND")

    async def test_ga4_property_selection_pending_is_409(self):
        with patch.object(
            ga4_connections,
            "sb_select",
            AsyncMock(return_value=[google_row(status="selection_required")]),
        ):
            with self.assertRaises(IntegrationError) as raised:
                await ga4_connections.resolve_ga4_connection_context(
                    "roove", connection_id="google-connection"
                )
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
                await ga4_connections.resolve_ga4_connection_context(
                    "roove", connection_id="google-connection"
                )
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
            "client_id=public-client&scope=read_orders%2Cread_all_orders%2Cread_customers%2Cread_products&"
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
            patch.object(shopify_oauth, "get_connection", AsyncMock(return_value=full_row)) as get_connection,
        ):
            context = await shopify_oauth.resolve_shopify_connection_context(
                "roove",
                connection_id=str(full_row["id"]),
                required_scopes=required_scopes,
            )
        select.assert_not_awaited()
        get_connection.assert_awaited_with("roove", str(full_row["id"]), include_token=True)
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

    def test_shopify_domain_normalization_accepts_bare_full_and_scheme_prefixed_forms(self):
        # As três formas de entrada esperadas do formulário de conexão devem
        # convergir para exatamente o mesmo domínio, uma única vez.
        expected = "amalie-6421.myshopify.com"
        self.assertEqual(shopify_oauth.normalize_shop_domain("amalie-6421"), expected)
        self.assertEqual(shopify_oauth.normalize_shop_domain("amalie-6421.myshopify.com"), expected)
        self.assertEqual(shopify_oauth.normalize_shop_domain("https://amalie-6421.myshopify.com"), expected)

    def test_shopify_domain_normalization_never_doubles_suffix_or_scheme(self):
        expected = "amalie-6421.myshopify.com"
        self.assertEqual(shopify_oauth.normalize_shop_domain("https://https://amalie-6421.myshopify.com"), expected)
        with self.assertRaises(RuntimeError):
            # Sufixo já duplicado na entrada nunca é aceito silenciosamente.
            shopify_oauth.normalize_shop_domain("amalie-6421.myshopify.com.myshopify.com")

    def test_shopify_admin_api_version_is_centralized(self):
        self.assertEqual(shopify_config.SHOPIFY_ADMIN_API_VERSION, "2026-07")
        self.assertEqual(
            shopify_config.shopify_admin_url(
                "minha-loja.myshopify.com",
                "orders.json",
            ),
            "https://minha-loja.myshopify.com/admin/api/2026-07/orders.json",
        )

    async def test_shopify_without_connection_id_reports_not_found_when_tenant_has_none(self):
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
        self.assertEqual(raised.exception.code, "SHOPIFY_CONNECTION_NOT_FOUND")

    async def test_multiple_shopify_stores_use_single_backend_reporting_preference(self):
        stores = [
            shopify_row(),
            shopify_row() | {
                "id": "shopify-second",
                "external_key": "segunda-loja.myshopify.com",
                "metadata": {"shop_domain": "segunda-loja.myshopify.com"},
            },
        ]
        select = AsyncMock(return_value=stores)
        with patch.object(shopify_oauth, "sb_select", select):
            context = await shopify_oauth.resolve_shopify_connection_context("roove")
        self.assertEqual(context.connection_id, stores[0]["id"])
        select.assert_awaited()

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

    async def test_legacy_shopify_environment_does_not_bypass_explicit_selection(self):
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
            with self.assertRaises(IntegrationError) as raised:
                await shopify_oauth.resolve_shopify_connection_context(
                    "roove",
                    required_scopes=("read_orders",),
                )
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.code, "SHOPIFY_CONNECTION_NOT_FOUND")

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
                AsyncMock(return_value={"access_token": "secret-token", "scope": "read_orders,read_all_orders,read_customers,read_products"}),
            ),
            patch.object(shopify_routes, "fetch_shop", AsyncMock(return_value={"id": 1, "name": "Roove"})),
            patch.object(shopify_routes, "validate_shopify_oauth_scopes", AsyncMock(return_value={
                "read_orders": True, "read_all_orders": True,
                "read_customers": True, "read_products": True,
            })) as validate_scopes,
            patch.object(shopify_routes, "register_webhooks", AsyncMock(return_value={"registered": [], "skipped": [], "failed": []})),
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
        validate_scopes.assert_awaited_once()
        background_tasks.add_task.assert_called_once_with(
            shopify_routes._run_initial_sync_isolated,
            client_id="roove",
            connection_id="shopify-connection",
            shop_domain="roove.myshopify.com",
        )
        sync.assert_not_awaited()

    async def test_webhook_registration_failure_never_erases_a_valid_oauth_connection(self):
        # Guerra room — PRIORIDADE 1: se o token exchange e o shop fetch
        # funcionaram, a conexão precisa ficar persistida mesmo que o
        # registro de webhooks falhe (ex.: um tópico de compliance rejeitado
        # pela Shopify). O fluxo antigo envolvia tudo num único try/except e
        # nunca chamava save_shopify_connection nesse caso.
        background_tasks = type("BackgroundTasks", (), {"add_task": Mock()})()
        request = type(
            "Request",
            (),
            {
                "query_params": {
                    "code": "secret-code",
                    "state": "secret-state",
                    "shop": "amalie-6421.myshopify.com",
                    "hmac": "valid-hmac",
                }
            },
        )()
        session = {
            "user_id": "user-amalie",
            "client_id": "amalie",
            "redirect_uri": shopify_oauth.SHOPIFY_PRODUCTION_REDIRECT_URI,
            "context": {"shop_domain": "amalie-6421.myshopify.com"},
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
                AsyncMock(return_value={"access_token": "secret-token", "scope": "read_orders,read_all_orders,read_customers,read_products"}),
            ),
            patch.object(shopify_routes, "fetch_shop", AsyncMock(return_value={"id": 1, "name": "Amalie"})),
            patch.object(shopify_routes, "validate_shopify_oauth_scopes", AsyncMock(return_value={
                "read_orders": True, "read_all_orders": True,
                "read_customers": True, "read_products": True,
            })),
            patch.object(
                shopify_routes,
                "register_webhooks",
                AsyncMock(side_effect=RuntimeError("tópico de compliance rejeitado")),
            ),
            patch.object(
                shopify_routes,
                "save_shopify_connection",
                AsyncMock(return_value={"id": "shopify-connection-amalie"}),
            ) as save,
            patch.dict(os.environ, {"FRONTEND_URL": "https://dados.mugoagencia.com.br"}, clear=False),
        ):
            response = await shopify_routes.callback(request, background_tasks)

        self.assertEqual(response.status_code, 302)
        self.assertIn("shopify_oauth=success", response.headers["location"])
        save.assert_awaited_once()
        # Mesmo com a falha de webhook, o backfill continua sendo agendado —
        # a conexão está válida e utilizável.
        background_tasks.add_task.assert_called_once_with(
            shopify_routes._run_initial_sync_isolated,
            client_id="amalie",
            connection_id="shopify-connection-amalie",
            shop_domain="amalie-6421.myshopify.com",
        )

    async def test_initial_sync_failure_never_disconnects_the_shopify_connection(self):
        # A conexão já foi persistida antes do backfill rodar em background;
        # uma falha no backfill (ex.: timeout, rate limit) só deve aparecer
        # como log isolado — nunca reverter o status para desconectado.
        with patch.object(
            shopify_routes,
            "sync_shopify_connection",
            AsyncMock(side_effect=RuntimeError("backfill timeout")),
        ):
            # Não deve levantar — a falha é capturada e só logada.
            await shopify_routes._run_initial_sync_isolated(
                client_id="amalie", connection_id="shopify-connection-amalie", shop_domain="amalie-6421.myshopify.com",
            )

    async def test_token_exchange_404_raises_humanized_error_and_logs_safely(self):
        output = io.StringIO()
        request_obj = httpx.Request("POST", "https://amalie-6421.myshopify.com/admin/oauth/access_token")
        not_found_response = httpx.Response(404, request=request_obj, json={"error": "not_found"})

        async def fake_post(self, url, json=None, **kwargs):
            return not_found_response

        with (
            patch.object(
                shopify_oauth,
                "settings",
                return_value={
                    "client_id": "public-client",
                    "client_secret": "super-secret-value",
                    "redirect_uri": shopify_oauth.SHOPIFY_PRODUCTION_REDIRECT_URI,
                },
            ),
            patch("httpx.AsyncClient.post", new=fake_post),
            redirect_stdout(output),
        ):
            with self.assertRaises(IntegrationError) as raised:
                await shopify_oauth.exchange_code(
                    shop_domain="amalie-6421.myshopify.com", code="super-secret-code",
                )

        self.assertEqual(raised.exception.status_code, 404)
        log = output.getvalue()
        self.assertIn(
            "[shopify_oauth] stage=token_exchange shop=amalie-6421.myshopify.com "
            "path=/admin/oauth/access_token status=404",
            log,
        )
        self.assertNotIn("super-secret-value", log)
        self.assertNotIn("super-secret-code", log)

    async def test_callback_with_token_exchange_404_returns_error_redirect_without_persisting(self):
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
        not_found = IntegrationError(
            "O recurso solicitado não foi encontrado na Shopify.",
            status_code=404, code="SHOPIFY_RESOURCE_NOT_FOUND", provider="shopify",
        )
        with (
            patch.object(shopify_routes, "verify_callback_hmac", return_value=True),
            patch.object(shopify_routes, "consume_oauth_state", AsyncMock(return_value=session)),
            patch.object(
                shopify_routes,
                "safe_oauth_configuration",
                return_value={"redirect_uri": shopify_oauth.SHOPIFY_PRODUCTION_REDIRECT_URI},
            ),
            patch.object(shopify_routes, "require_user_client_access", AsyncMock()),
            patch.object(shopify_routes, "exchange_code", AsyncMock(side_effect=not_found)),
            patch.object(shopify_routes, "save_shopify_connection", AsyncMock()) as save,
            patch.dict(os.environ, {"FRONTEND_URL": "https://dados.mugoagencia.com.br"}, clear=False),
        ):
            response = await shopify_routes.callback(request, background_tasks)

        self.assertEqual(response.status_code, 302)
        self.assertIn("shopify_oauth=error", response.headers["location"])
        save.assert_not_awaited()
        background_tasks.add_task.assert_not_called()


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
        request_id_token = api_support._set_request_id("req-shopify-safe")
        try:
            response = api_support._structured_error_response(
                endpoint="/api/shopify/report",
                exc=error,
                status_code=error.status_code,
                code="shopify_report_runtime_error",
            )
        finally:
            api_support._reset_request_id(request_id_token)
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
        self.assertIn('"request_id":"req-shopify-safe"', body)


if __name__ == "__main__":
    unittest.main()
