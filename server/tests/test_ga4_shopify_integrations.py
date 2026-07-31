import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import api_support
from server.services import ga4_connections, shopify_oauth
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
        self.assertEqual(raised.exception.code, "GA4_PROPERTY_SELECTION_REQUIRED")

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


class ShopifyConnectionResolutionTests(unittest.IsolatedAsyncioTestCase):
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
