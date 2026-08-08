from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import shopify_oauth  # noqa: E402
from services import shopify_webhooks  # noqa: E402
from services.integration_errors import IntegrationError  # noqa: E402


def _context(**overrides) -> SimpleNamespace:
    base = dict(
        shop_domain="amalie-6421.myshopify.com",
        connection_id="8e1780ef-17b0-4b0a-843e-f8c323141412",
        access_token="test-token",
        scopes=frozenset({"read_orders", "read_customers", "read_products"}),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _fake_job_run() -> AsyncMock:
    return AsyncMock(return_value={"id": "job-run-1"})


class ReadOrdersScopeGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_read_orders_scope_raises_instead_of_returning_silently_zero(self):
        # DB tem read_orders persistido, mas a Shopify (via GraphQL,
        # consultado ao vivo) não concede mais o escopo — nunca pode virar
        # "0 pedidos" silencioso.
        orders_fetch = AsyncMock(return_value=[{"id": 1}])
        with (
            patch.object(shopify_oauth, "resolve_shopify_connection_context", AsyncMock(return_value=_context())),
            patch.object(
                shopify_oauth,
                "_check_shopify_scopes",
                AsyncMock(return_value={"read_orders": False, "read_customers": True, "read_products": True}),
            ),
            patch.object(shopify_oauth, "_fetch_shopify_collection", orders_fetch),
            patch.object(shopify_oauth, "start_job_run", _fake_job_run()),
            patch.object(shopify_oauth, "finish_job_run", AsyncMock()) as finish_mock,
            patch.object(shopify_oauth, "sb_update", AsyncMock()),
            patch("services.sync_locks.sb_rpc", AsyncMock(return_value=True)),
        ):
            with self.assertRaises(IntegrationError) as raised:
                await shopify_oauth.sync_shopify_connection(client_id="amalie", connection_id="conn-1")

        self.assertEqual(raised.exception.code, "SHOPIFY_MISSING_READ_ORDERS_SCOPE")
        orders_fetch.assert_not_awaited()  # nunca chega a consultar pedidos
        finish_mock.assert_awaited_once()
        self.assertEqual(finish_mock.await_args.kwargs["status"], "error")

    async def test_scope_check_reports_real_scopes_via_graphql_response(self):
        response = httpx.Response(
            200,
            json={"data": {"currentAppInstallation": {"accessScopes": [
                {"handle": "read_orders"}, {"handle": "read_products"},
            ]}}},
            request=httpx.Request("POST", "https://amalie-6421.myshopify.com/admin/api/2026-07/graphql.json"),
        )

        async def fake_post(self, url, headers=None, json=None, **kwargs):
            return response

        with patch("httpx.AsyncClient.post", new=fake_post):
            result = await shopify_oauth._check_shopify_scopes(_context())

        self.assertTrue(result["read_orders"])
        self.assertTrue(result["read_products"])
        self.assertFalse(result["read_customers"])  # não presente na resposta


class BackfillPersistsOrdersTests(unittest.IsolatedAsyncioTestCase):
    async def test_shopify_200_with_orders_persists_them_and_reports_success(self):
        orders = [{"id": 1001}, {"id": 1002}, {"id": 1003}]
        customers = [{"id": 2001}]

        async def fake_collection(context, resource, *, params=None):
            if resource == "orders.json":
                return orders
            if resource == "customers.json":
                return customers
            return []

        handle_order = AsyncMock(return_value={"order_id": "1001", "items_upserted": 2})
        handle_customer = AsyncMock(return_value={"customer_id": "2001"})

        with (
            patch.object(shopify_oauth, "resolve_shopify_connection_context", AsyncMock(return_value=_context())),
            patch.object(shopify_oauth, "_check_shopify_scopes", AsyncMock(return_value={"read_orders": True, "read_customers": True, "read_products": True})),
            patch.object(shopify_oauth, "_fetch_shopify_collection", fake_collection),
            patch.object(shopify_webhooks, "_handle_order_topic", handle_order),
            patch.object(shopify_webhooks, "_handle_customer_topic", handle_customer),
            patch.object(shopify_oauth, "sb_update", AsyncMock(return_value=[])) as sb_update_mock,
            patch.object(shopify_oauth, "start_job_run", _fake_job_run()),
            patch.object(shopify_oauth, "finish_job_run", AsyncMock()) as finish_mock,
            patch("services.sync_locks.sb_rpc", AsyncMock(return_value=True)),
        ):
            result = await shopify_oauth.sync_shopify_connection(client_id="amalie", connection_id="conn-1")

        self.assertTrue(result["ok"])
        self.assertEqual(result["synced"]["orders"], 3)
        self.assertEqual(handle_order.await_count, 3)
        self.assertEqual(handle_customer.await_count, 1)
        # Confirma que o sucesso persiste last_sync_at (nunca deixa null).
        success_patch = sb_update_mock.await_args.kwargs["patch"]
        self.assertIsNotNone(success_patch["last_sync_at"])
        self.assertEqual(success_patch["status"], "connected")
        finish_mock.assert_awaited_once()
        self.assertEqual(finish_mock.await_args.kwargs["status"], "success")

    async def test_one_bad_order_never_aborts_the_rest_of_the_batch(self):
        # Regressão específica pedida pelo war room: antes, uma exceção em
        # QUALQUER pedido abortava o loop inteiro — os demais pedidos
        # válidos (mesmo vindo DEPOIS do problemático) nunca chegavam a ser
        # tentados, e o sync inteiro virava "erro" sem indicar quantos
        # pedidos realmente existiam.
        orders = [{"id": 1001}, {"id": 1002}, {"id": 1003}]

        async def fake_collection(context, resource, *, params=None):
            return orders if resource == "orders.json" else []

        async def flaky_handle_order(*, client_id, shop_domain, payload):
            if payload["id"] == 1002:
                raise RuntimeError("payload inesperado da Shopify")
            return {"order_id": str(payload["id"]), "items_upserted": 1}

        with (
            patch.object(shopify_oauth, "resolve_shopify_connection_context", AsyncMock(return_value=_context())),
            patch.object(shopify_oauth, "_check_shopify_scopes", AsyncMock(return_value={"read_orders": True, "read_customers": True, "read_products": True})),
            patch.object(shopify_oauth, "_fetch_shopify_collection", fake_collection),
            patch.object(shopify_webhooks, "_handle_order_topic", flaky_handle_order),
            patch.object(shopify_oauth, "sb_update", AsyncMock(return_value=[])),
            patch.object(shopify_oauth, "start_job_run", _fake_job_run()),
            patch.object(shopify_oauth, "finish_job_run", AsyncMock()) as finish_mock,
            patch("services.sync_locks.sb_rpc", AsyncMock(return_value=True)),
        ):
            result = await shopify_oauth.sync_shopify_connection(client_id="amalie", connection_id="conn-1")

        self.assertTrue(result["ok"])
        self.assertEqual(result["synced"]["orders_received"], 3)
        self.assertEqual(result["synced"]["orders_upserted"], 2)
        self.assertEqual(result["synced"]["orders_failed"], 1)
        self.assertEqual(finish_mock.await_args.kwargs["status"], "success")

    async def test_all_orders_failing_to_persist_is_reported_as_error_not_silent_success(self):
        # Se a Shopify devolveu pedidos mas NENHUM foi persistido, isso
        # nunca pode terminar como "sucesso" com orders=0 — precisa ficar
        # visível como falha operacional real.
        orders = [{"id": 1001}, {"id": 1002}]

        async def fake_collection(context, resource, *, params=None):
            return orders if resource == "orders.json" else []

        async def always_failing_handle_order(*, client_id, shop_domain, payload):
            raise RuntimeError("schema incompatível")

        with (
            patch.object(shopify_oauth, "resolve_shopify_connection_context", AsyncMock(return_value=_context())),
            patch.object(shopify_oauth, "_check_shopify_scopes", AsyncMock(return_value={"read_orders": True, "read_customers": True, "read_products": True})),
            patch.object(shopify_oauth, "_fetch_shopify_collection", fake_collection),
            patch.object(shopify_webhooks, "_handle_order_topic", always_failing_handle_order),
            patch.object(shopify_oauth, "sb_update", AsyncMock(return_value=[])) as sb_update_mock,
            patch.object(shopify_oauth, "start_job_run", _fake_job_run()),
            patch.object(shopify_oauth, "finish_job_run", AsyncMock()) as finish_mock,
            patch("services.sync_locks.sb_rpc", AsyncMock(return_value=True)),
        ):
            with self.assertRaises(IntegrationError) as raised:
                await shopify_oauth.sync_shopify_connection(client_id="amalie", connection_id="conn-1")

        self.assertEqual(raised.exception.code, "SHOPIFY_ORDERS_PERSISTENCE_FAILED")
        self.assertEqual(finish_mock.await_args.kwargs["status"], "error")
        # Nunca escreve status=connected/last_sync_at como se tivesse dado certo.
        for call in sb_update_mock.await_args_list:
            self.assertNotIn("last_sync_at", call.kwargs.get("patch", {}))


class PaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_pages_are_collected_and_persisted(self):
        page_1 = httpx.Response(
            200,
            json={"orders": [{"id": 1}, {"id": 2}]},
            headers={"Link": '<https://amalie-6421.myshopify.com/admin/api/2026-07/orders.json?page_info=abc>; rel="next"'},
            request=httpx.Request("GET", "https://amalie-6421.myshopify.com/admin/api/2026-07/orders.json"),
        )
        page_2 = httpx.Response(
            200,
            json={"orders": [{"id": 3}]},
            request=httpx.Request("GET", "https://amalie-6421.myshopify.com/admin/api/2026-07/orders.json?page_info=abc"),
        )
        responses = [page_1, page_2]

        async def fake_get(self, url, headers=None, params=None, **kwargs):
            return responses.pop(0)

        with patch("httpx.AsyncClient.get", new=fake_get):
            rows = await shopify_oauth._fetch_shopify_collection(
                _context(), "orders.json", params={"status": "any", "limit": 250},
            )

        self.assertEqual(len(rows), 3)
        self.assertEqual([row["id"] for row in rows], [1, 2, 3])


class ShopifyErrorNeverBecomesZeroTests(unittest.IsolatedAsyncioTestCase):
    async def test_401_from_shopify_raises_instead_of_returning_empty_list(self):
        response = httpx.Response(
            401,
            json={"errors": "Invalid API key or access token"},
            request=httpx.Request("GET", "https://amalie-6421.myshopify.com/admin/api/2026-07/orders.json"),
        )

        async def fake_get(self, url, headers=None, params=None, **kwargs):
            return response

        with patch("httpx.AsyncClient.get", new=fake_get):
            with self.assertRaises(IntegrationError) as raised:
                await shopify_oauth._fetch_shopify_collection(_context(), "orders.json", params={"status": "any"})

        self.assertEqual(raised.exception.status_code, 401)

    async def test_sync_propagates_orders_fetch_error_and_records_it_without_faking_success(self):
        async def fake_collection(context, resource, *, params=None):
            raise IntegrationError(
                "A Shopify recusou a solicitação.", status_code=403, code="SHOPIFY_INSUFFICIENT_SCOPE", provider="shopify",
            )

        with (
            patch.object(shopify_oauth, "resolve_shopify_connection_context", AsyncMock(return_value=_context())),
            patch.object(shopify_oauth, "_check_shopify_scopes", AsyncMock(return_value={"read_orders": True, "read_customers": True, "read_products": True})),
            patch.object(shopify_oauth, "_fetch_shopify_collection", fake_collection),
            patch.object(shopify_oauth, "sb_update", AsyncMock()) as sb_update_mock,
            patch.object(shopify_oauth, "start_job_run", _fake_job_run()),
            patch.object(shopify_oauth, "finish_job_run", AsyncMock()) as finish_mock,
            patch("services.sync_locks.sb_rpc", AsyncMock(return_value=True)),
        ):
            with self.assertRaises(IntegrationError):
                await shopify_oauth.sync_shopify_connection(client_id="amalie", connection_id="conn-1")

        # Nunca escreve status=connected/last_sync_at como se tivesse dado certo.
        sb_update_mock.assert_awaited_once()
        failure_patch = sb_update_mock.await_args.kwargs["patch"]
        self.assertIn("last_error", failure_patch)
        self.assertNotIn("status", failure_patch)
        self.assertEqual(finish_mock.await_args.kwargs["status"], "error")


class ReportSyncStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_route_marks_has_synced_false_when_connection_never_synced(self):
        from routes import shopify as shopify_routes

        with (
            patch.object(shopify_routes, "resolve_client_id", AsyncMock(return_value="amalie")),
            patch.object(
                shopify_routes,
                "resolve_shopify_connection_context",
                AsyncMock(return_value=_context()),
            ),
            patch.object(
                shopify_routes,
                "build_shopify_report",
                AsyncMock(return_value={"ok": True, "summary": {"orders": 0, "revenue_total": 0}}),
            ),
            patch.object(shopify_routes, "get_connection", AsyncMock(return_value={"last_sync_at": None, "last_error": None})),
        ):
            payload = await shopify_routes.shopify_report(
                start="2026-08-01", end="2026-08-31", days=31,
                client_id="amalie", connection_id="8e1780ef-17b0-4b0a-843e-f8c323141412",
                x_client_id=None, authorization="Bearer valid",
            )

        self.assertFalse(payload["sync_state"]["has_synced"])
        self.assertIsNone(payload["sync_state"]["last_sync_at"])

    async def test_report_route_marks_has_synced_true_after_successful_backfill(self):
        from routes import shopify as shopify_routes

        with (
            patch.object(shopify_routes, "resolve_client_id", AsyncMock(return_value="amalie")),
            patch.object(
                shopify_routes,
                "resolve_shopify_connection_context",
                AsyncMock(return_value=_context()),
            ),
            patch.object(
                shopify_routes,
                "build_shopify_report",
                AsyncMock(return_value={"ok": True, "summary": {"orders": 12, "revenue_total": 3500.0}}),
            ),
            patch.object(
                shopify_routes,
                "get_connection",
                AsyncMock(return_value={"last_sync_at": "2026-08-08T12:00:00Z", "last_error": None}),
            ),
        ):
            payload = await shopify_routes.shopify_report(
                start="2026-08-01", end="2026-08-31", days=31,
                client_id="amalie", connection_id="8e1780ef-17b0-4b0a-843e-f8c323141412",
                x_client_id=None, authorization="Bearer valid",
            )

        self.assertTrue(payload["sync_state"]["has_synced"])
        self.assertEqual(payload["summary"]["orders"], 12)


class WebhookProcessingUpdatesCountersTests(unittest.IsolatedAsyncioTestCase):
    async def test_orders_create_webhook_marks_event_processed(self):
        status_calls = []

        async def fake_mark_status(event_id, *, status, error_message=None):
            status_calls.append((event_id, status))

        with (
            patch.object(shopify_webhooks, "_handle_order_topic", AsyncMock(return_value={"order_id": "555", "items_upserted": 1})),
            patch.object(shopify_webhooks, "_mark_shopify_webhook_status", fake_mark_status),
        ):
            await shopify_webhooks.process_shopify_webhook_event(
                event_id="event-1", client_id="amalie", topic="orders/create",
                shop_domain="amalie-6421.myshopify.com", webhook_id="wh-1",
                payload_json={"id": 555},
            )

        self.assertIn(("event-1", "processed"), status_calls)

    async def test_orders_create_failure_marks_event_error_not_processed(self):
        status_calls = []

        async def fake_mark_status(event_id, *, status, error_message=None):
            status_calls.append((event_id, status))

        with (
            patch.object(shopify_webhooks, "_handle_order_topic", AsyncMock(side_effect=RuntimeError("upstream down"))),
            patch.object(shopify_webhooks, "_mark_shopify_webhook_status", fake_mark_status),
        ):
            await shopify_webhooks.process_shopify_webhook_event(
                event_id="event-2", client_id="amalie", topic="orders/create",
                shop_domain="amalie-6421.myshopify.com", webhook_id="wh-2",
                payload_json={"id": 556},
            )

        self.assertIn(("event-2", "error"), status_calls)
        self.assertNotIn(("event-2", "processed"), status_calls)


class WebhookSubscriptionIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_failing_topic_never_blocks_registration_of_the_others(self):
        call_log = []

        async def fake_post(self, url, headers=None, json=None, **kwargs):
            topic = json["webhook"]["topic"]
            call_log.append(topic)
            if topic == "customers/data_request":
                return httpx.Response(
                    422, json={"errors": "not a valid topic"},
                    request=httpx.Request("POST", url),
                )
            return httpx.Response(201, json={"webhook": {"id": 1}}, request=httpx.Request("POST", url))

        with (
            patch("httpx.AsyncClient.post", new=fake_post),
            patch.dict("os.environ", {"SHOPIFY_WEBHOOK_URL": "https://api.dados.mugoagencia.com.br/api/webhooks/shopify"}),
        ):
            result = await shopify_oauth.register_webhooks("amalie-6421.myshopify.com", "test-token")

        # Todos os tópicos foram tentados, mesmo o que falhou não impede os demais.
        self.assertEqual(set(call_log), set(shopify_oauth.SHOPIFY_WEBHOOK_TOPICS))
        self.assertIn("orders/create", result["registered"])
        self.assertIn("orders/updated", result["registered"])
        self.assertTrue(any(item["topic"] == "customers/data_request" for item in result["failed"]))


if __name__ == "__main__":
    unittest.main()
