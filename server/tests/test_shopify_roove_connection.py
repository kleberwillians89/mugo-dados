"""Shopify — conexão da Roove (tenant-scoped, idempotente, sem expor token)."""

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "t" * 48)

from routes import shopify_oauth as shopify_routes
from services import generic_connections, shopify_oauth
from services.crypto import decrypt_secret
from services.integration_errors import IntegrationError

ROOVE_SHOP = "0vi1gx-ja.myshopify.com"
TOKEN = "shpat_roove_private_token_value"
CODE = "roove-authorization-code-value"
GRANTED = "read_orders,read_all_orders,read_customers,read_products"


def failing_graphql(*_args, **_kwargs):
    raise httpx.ConnectError("graphql indisponível")


class ScopeValidationFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_graphql_failure_falls_back_to_scopes_granted_in_token_exchange(self):
        with patch.object(shopify_oauth.httpx, "AsyncClient", side_effect=failing_graphql):
            granted = await shopify_oauth.validate_shopify_oauth_scopes(
                shop_domain=ROOVE_SHOP,
                access_token=TOKEN,
                required_scopes=tuple(shopify_oauth.SHOPIFY_REQUIRED_CONNECTION_SCOPES),
                granted_scopes=GRANTED,
            )
        self.assertTrue(granted["read_orders"])
        self.assertTrue(granted["read_customers"])
        self.assertTrue(granted["read_products"])

    async def test_graphql_failure_without_granted_scopes_still_rejects(self):
        # Comportamento anterior no callback: fallback vazio rejeitava tudo.
        with patch.object(shopify_oauth.httpx, "AsyncClient", side_effect=failing_graphql):
            with self.assertRaises(IntegrationError) as raised:
                await shopify_oauth.validate_shopify_oauth_scopes(
                    shop_domain=ROOVE_SHOP,
                    access_token=TOKEN,
                    required_scopes=tuple(shopify_oauth.SHOPIFY_REQUIRED_CONNECTION_SCOPES),
                )
        self.assertEqual(raised.exception.code, "SHOPIFY_INSUFFICIENT_SCOPE")

    async def test_missing_required_scope_in_token_exchange_is_still_rejected(self):
        with patch.object(shopify_oauth.httpx, "AsyncClient", side_effect=failing_graphql):
            with self.assertRaises(IntegrationError):
                await shopify_oauth.validate_shopify_oauth_scopes(
                    shop_domain=ROOVE_SHOP,
                    access_token=TOKEN,
                    required_scopes=tuple(shopify_oauth.SHOPIFY_REQUIRED_CONNECTION_SCOPES),
                    granted_scopes="read_orders",
                )


class RooveCallbackTests(unittest.IsolatedAsyncioTestCase):
    def request(self):
        return type("Request", (), {"query_params": {
            "code": CODE, "state": "signed-state", "shop": ROOVE_SHOP, "hmac": "valid",
        }})()

    async def run_callback(self, *, save=None, env=None):
        background_tasks = type("BackgroundTasks", (), {"add_task": Mock()})()
        session = {
            "user_id": "user-admin", "client_id": "roove",
            "redirect_uri": shopify_oauth.SHOPIFY_PRODUCTION_REDIRECT_URI,
            "context": {"shop_domain": ROOVE_SHOP},
        }
        save = save or AsyncMock(return_value={"id": "shopify-roove"})
        output = io.StringIO()
        with (
            patch.object(shopify_routes, "verify_callback_hmac", return_value=True),
            patch.object(shopify_routes, "consume_oauth_state", AsyncMock(return_value=session)),
            patch.object(shopify_routes, "safe_oauth_configuration", return_value={
                "redirect_uri": shopify_oauth.SHOPIFY_PRODUCTION_REDIRECT_URI,
            }),
            patch.object(shopify_routes, "require_user_client_access", AsyncMock()),
            patch.object(shopify_routes, "exchange_code", AsyncMock(return_value={
                "access_token": TOKEN, "scope": GRANTED,
            })),
            patch.object(shopify_routes, "fetch_shop", AsyncMock(return_value={"id": 7, "name": "Roove"})),
            # Validação REAL de escopos, com a consulta GraphQL indisponível.
            patch.object(shopify_oauth.httpx, "AsyncClient", side_effect=failing_graphql),
            patch.object(shopify_routes, "save_shopify_connection", save),
            patch.object(shopify_routes, "register_webhooks", AsyncMock(side_effect=RuntimeError("webhook recusado"))),
            patch.dict(os.environ, env or {"FRONTEND_URL": "https://dados.mugoagencia.com.br"}, clear=False),
            redirect_stdout(output),
        ):
            response = await shopify_routes.callback(self.request(), background_tasks)
        return response, save, background_tasks, output.getvalue()

    async def test_valid_callback_persists_roove_even_if_scope_check_and_webhook_fail(self):
        response, save, background_tasks, logs = await self.run_callback()

        location = response.headers["location"]
        self.assertIn("shopify_oauth=success", location)
        self.assertIn("client_id=roove", location)
        self.assertIn("connection_id=shopify-roove", location)
        save.assert_awaited_once()
        self.assertEqual(save.await_args.kwargs["client_id"], "roove")
        self.assertEqual(save.await_args.kwargs["shop_domain"], ROOVE_SHOP)
        background_tasks.add_task.assert_called_once()
        for secret in (TOKEN, CODE):
            self.assertNotIn(secret, location)
            self.assertNotIn(secret, logs)

    async def test_frontend_redirect_falls_back_to_allow_origin_not_localhost(self):
        env = {"FRONTEND_URL": "", "ALLOW_ORIGIN": "https://dados.mugoagencia.com.br,http://localhost:5173"}
        response, *_ = await self.run_callback(env=env)
        self.assertTrue(response.headers["location"].startswith("https://dados.mugoagencia.com.br/?onboarding=1&"))

    async def test_initial_sync_failure_never_undoes_connection(self):
        output = io.StringIO()
        with (
            patch.object(shopify_routes, "sync_shopify_connection", AsyncMock(side_effect=RuntimeError("boom"))),
            patch.object(shopify_routes, "disconnect_generic_connection", AsyncMock()) as disconnect,
            redirect_stdout(output),
        ):
            await shopify_routes._run_initial_sync_isolated(
                client_id="roove", connection_id="shopify-roove", shop_domain=ROOVE_SHOP,
            )
        disconnect.assert_not_awaited()
        self.assertIn("stage=initial_sync", output.getvalue())


class SaveShopifyConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def save(self, *, store_rows, connection_rows):
        writes = {"update": [], "insert": []}

        async def fake_select(table, **kwargs):
            if table == "shopify_stores":
                return store_rows
            if table == "integration_connections":
                return connection_rows
            return []

        async def fake_update(table, *, filters, patch, returning="minimal"):
            writes["update"].append((table, filters, patch))
            return [{"id": "shopify-roove", "client_id": "roove", "provider": "shopify", **patch}]

        async def fake_insert(table, row, returning="minimal"):
            writes["insert"].append((table, row))
            return {"id": "shopify-roove", **row}

        with (
            patch.object(shopify_oauth, "sb_select", AsyncMock(side_effect=fake_select)),
            patch.object(shopify_oauth, "sb_update", AsyncMock(side_effect=fake_update)),
            patch.object(shopify_oauth, "sb_insert", AsyncMock(side_effect=fake_insert)),
            patch.object(generic_connections, "sb_select", AsyncMock(side_effect=fake_select)),
            patch.object(generic_connections, "sb_update", AsyncMock(side_effect=fake_update)),
            patch.object(generic_connections, "sb_insert", AsyncMock(side_effect=fake_insert)),
            patch.object(generic_connections, "invalidate_namespace", AsyncMock()),
            patch.object(shopify_oauth, "select_shopify_connection", AsyncMock(return_value={"id": "shopify-roove"})),
        ):
            await shopify_oauth.save_shopify_connection(
                client_id="roove", user_id="user-admin", shop_domain=f"https://{ROOVE_SHOP}/",
                token={"access_token": TOKEN, "scope": GRANTED}, shop={"id": 7, "name": "Roove"},
            )
        return writes

    async def test_reauthorization_updates_the_same_roove_connection_with_encrypted_token(self):
        existing_connection = [{"id": "shopify-roove", "client_id": "roove", "provider": "shopify", "external_key": ROOVE_SHOP}]
        existing_store = [{"id": "store-1", "client_id": "roove", "shop_domain": ROOVE_SHOP}]
        writes = await self.save(store_rows=existing_store, connection_rows=existing_connection)

        connection_updates = [w for w in writes["update"] if w[0] == "integration_connections"]
        self.assertEqual(len(connection_updates), 1)
        _table, filters, patch_row = connection_updates[0]
        self.assertEqual(filters["client_id"], "eq.roove")
        self.assertEqual(patch_row["status"], "connected")
        self.assertEqual(patch_row["external_key"], ROOVE_SHOP)
        self.assertNotIn(TOKEN, patch_row["encrypted_token"])
        self.assertEqual(json.loads(decrypt_secret(patch_row["encrypted_token"]))["access_token"], TOKEN)
        self.assertFalse([w for w in writes["insert"] if w[0] in {"integration_connections", "shopify_stores"}])
        store_updates = [w for w in writes["update"] if w[0] == "shopify_stores"]
        self.assertEqual(store_updates[0][2]["client_id"], "roove")

    async def test_store_owned_by_amalie_is_never_attached_to_roove(self):
        with self.assertRaisesRegex(RuntimeError, "outra empresa"):
            await self.save(
                store_rows=[{"id": "store-1", "client_id": "amalie", "shop_domain": ROOVE_SHOP}],
                connection_rows=[],
            )


class RooveConnectionLookupTests(unittest.IsolatedAsyncioTestCase):
    def roove_row(self, **overrides):
        row = {
            "id": "shopify-roove", "client_id": "roove", "provider": "shopify", "status": "connected",
            "external_key": ROOVE_SHOP, "metadata": {"shop_domain": ROOVE_SHOP, "selected_for_reporting": True},
            "scopes": GRANTED.split(","), "disconnected_at": None,
        }
        row.update(overrides)
        return row

    async def test_lookup_is_scoped_by_tenant_and_resolves_roove(self):
        select = AsyncMock(return_value=[self.roove_row()])
        with (
            patch.object(shopify_oauth, "sb_select", select),
            patch.object(shopify_oauth, "get_connection", AsyncMock(
                return_value={**self.roove_row(), "_token": json.dumps({"access_token": TOKEN})}
            )),
        ):
            context = await shopify_oauth.resolve_shopify_connection_context(
                "roove", required_scopes=("read_orders", "read_products"),
            )
        self.assertEqual(context.client_id, "roove")
        self.assertEqual(context.shop_domain, ROOVE_SHOP)
        filters = select.await_args.kwargs["filters"]
        self.assertEqual(filters, {"client_id": "eq.roove", "provider": "eq.shopify"})

    async def test_missing_connection_keeps_404_not_found(self):
        with patch.object(shopify_oauth, "sb_select", AsyncMock(return_value=[])):
            with self.assertRaises(IntegrationError) as raised:
                await shopify_oauth.resolve_shopify_connection_context("roove")
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.code, "SHOPIFY_CONNECTION_NOT_FOUND")

    async def test_roove_cannot_read_amalie_connection_by_id(self):
        amalie = self.roove_row(id="shopify-amalie", client_id="amalie", external_key="amalie-6421.myshopify.com")
        with patch.object(shopify_oauth, "get_connection", AsyncMock(side_effect=IntegrationError(
            "A conexão selecionada pertence a outra empresa.", status_code=403,
            code="OAUTH_CONNECTION_TENANT_MISMATCH", provider="integration",
        ))):
            with self.assertRaises(IntegrationError) as raised:
                await shopify_oauth.resolve_shopify_connection_context("roove", connection_id=amalie["id"])
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.code, "SHOPIFY_CONNECTION_NOT_FOUND")

    async def test_fbits_row_of_same_tenant_is_never_used_as_shopify(self):
        fbits = self.roove_row(id="fbits-roove", provider="fbits", external_key="fbits-store")
        with patch.object(shopify_oauth, "sb_select", AsyncMock(return_value=[fbits])):
            with self.assertRaises(IntegrationError) as raised:
                await shopify_oauth.resolve_shopify_connection_context("roove")
        self.assertNotEqual(raised.exception.status_code, 200)


if __name__ == "__main__":
    unittest.main()
