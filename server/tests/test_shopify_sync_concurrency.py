from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import shopify_oauth
from services.integration_errors import IntegrationError


def _context(connection_id: str = "shopify-conn-1") -> SimpleNamespace:
    return SimpleNamespace(
        shop_domain="amalie.myshopify.com",
        connection_id=connection_id,
        access_token="test-token",
        scopes=frozenset({"read_orders", "read_customers", "read_products"}),
    )


def _granted_scopes() -> AsyncMock:
    return AsyncMock(return_value={"read_orders": True, "read_customers": True, "read_products": True})


def _fake_job_run() -> AsyncMock:
    return AsyncMock(return_value={"id": "job-run-1"})


class ShopifySyncConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    """
    sync_shopify_connection não tinha nenhum lock — dois cliques (ou um
    clique coincidindo com uma chamada automática) disparavam duas
    sincronizações Shopify em paralelo para a mesma loja. Esses testes
    travam o comportamento de exclusão mútua adicionado.
    """

    async def test_second_concurrent_sync_for_same_connection_is_rejected(self):
        held: set[tuple[str, str]] = set()

        async def rpc(name, payload):
            key = (payload["p_client_id"], payload["p_job_name"])
            if name == "acquire_client_job_lock":
                if key in held:
                    return False
                held.add(key)
                return True
            held.discard(key)
            return True

        entered = __import__("asyncio").Event()
        release = __import__("asyncio").Event()

        async def slow_first_sync(*_args, **_kwargs):
            entered.set()
            await release.wait()
            return []

        with (
            patch("services.sync_locks.sb_rpc", side_effect=rpc),
            patch.object(shopify_oauth, "resolve_shopify_connection_context", AsyncMock(return_value=_context())),
            patch.object(shopify_oauth, "_check_shopify_scopes", _granted_scopes()),
            patch.object(shopify_oauth, "_fetch_shopify_collection", slow_first_sync),
            patch.object(shopify_oauth, "sb_update", AsyncMock(return_value=[])),
            patch.object(shopify_oauth, "start_job_run", _fake_job_run()),
            patch.object(shopify_oauth, "finish_job_run", AsyncMock()),
        ):
            first = __import__("asyncio").create_task(
                shopify_oauth.sync_shopify_connection(client_id="amalie", connection_id="shopify-conn-1")
            )
            await entered.wait()

            with self.assertRaises(IntegrationError) as raised:
                await shopify_oauth.sync_shopify_connection(client_id="amalie", connection_id="shopify-conn-1")
            self.assertEqual(raised.exception.code, "SYNC_ALREADY_RUNNING")

            release.set()
            await first
            self.assertFalse(held)

    async def test_different_connections_sync_concurrently_without_blocking(self):
        async def fake_rpc(name, _payload):
            return True

        async def empty_collection(*_args, **_kwargs):
            return []

        with (
            patch("services.sync_locks.sb_rpc", side_effect=fake_rpc),
            patch.object(
                shopify_oauth,
                "resolve_shopify_connection_context",
                AsyncMock(side_effect=lambda client_id, connection_id, required_scopes: _context(connection_id)),
            ),
            patch.object(shopify_oauth, "_check_shopify_scopes", _granted_scopes()),
            patch.object(shopify_oauth, "_fetch_shopify_collection", empty_collection),
            patch.object(shopify_oauth, "sb_update", AsyncMock(return_value=[])),
            patch.object(shopify_oauth, "start_job_run", _fake_job_run()),
            patch.object(shopify_oauth, "finish_job_run", AsyncMock()),
        ):
            result_a = await shopify_oauth.sync_shopify_connection(client_id="amalie", connection_id="conn-a")
            result_b = await shopify_oauth.sync_shopify_connection(client_id="ruah", connection_id="conn-b")

        self.assertTrue(result_a["ok"])
        self.assertTrue(result_b["ok"])

    async def test_lock_is_released_after_sync_completes(self):
        calls: list[str] = []

        async def fake_rpc(name, _payload):
            calls.append(name)
            return True

        async def empty_collection(*_args, **_kwargs):
            return []

        with (
            patch("services.sync_locks.sb_rpc", side_effect=fake_rpc),
            patch.object(shopify_oauth, "resolve_shopify_connection_context", AsyncMock(return_value=_context())),
            patch.object(shopify_oauth, "_check_shopify_scopes", _granted_scopes()),
            patch.object(shopify_oauth, "_fetch_shopify_collection", empty_collection),
            patch.object(shopify_oauth, "sb_update", AsyncMock(return_value=[])),
            patch.object(shopify_oauth, "start_job_run", _fake_job_run()),
            patch.object(shopify_oauth, "finish_job_run", AsyncMock()),
        ):
            await shopify_oauth.sync_shopify_connection(client_id="amalie", connection_id="shopify-conn-1")

        self.assertEqual(calls, ["acquire_client_job_lock", "release_client_job_lock"])

    async def test_lock_is_released_even_when_sync_fails(self):
        async def fake_rpc(name, _payload):
            return True

        async def failing_collection(*_args, **_kwargs):
            raise RuntimeError("Shopify API indisponível")

        with (
            patch("services.sync_locks.sb_rpc", side_effect=fake_rpc) as rpc_mock,
            patch.object(shopify_oauth, "resolve_shopify_connection_context", AsyncMock(return_value=_context())),
            patch.object(shopify_oauth, "_check_shopify_scopes", _granted_scopes()),
            patch.object(shopify_oauth, "_fetch_shopify_collection", failing_collection),
            patch.object(shopify_oauth, "start_job_run", _fake_job_run()),
            patch.object(shopify_oauth, "finish_job_run", AsyncMock()),
            patch.object(shopify_oauth, "sb_update", AsyncMock(return_value=[])),
        ):
            with self.assertRaises(RuntimeError):
                await shopify_oauth.sync_shopify_connection(client_id="amalie", connection_id="shopify-conn-1")

            release_calls = [c for c in rpc_mock.call_args_list if c.args[0] == "release_client_job_lock"]
            self.assertEqual(len(release_calls), 1)


if __name__ == "__main__":
    unittest.main()
