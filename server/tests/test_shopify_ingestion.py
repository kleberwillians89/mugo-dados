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
            patch.object(shopify_oauth, "peek_sync_lock", AsyncMock(return_value=None)),
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
        customer_upsert_calls = []

        async def fake_sb_upsert(table, rows, on_conflict=None):
            if table == "shopify_customers":
                customer_upsert_calls.append(rows)
            return {"ok": True}

        with (
            patch.object(shopify_oauth, "resolve_shopify_connection_context", AsyncMock(return_value=_context())),
            patch.object(shopify_oauth, "peek_sync_lock", AsyncMock(return_value=None)),
            patch.object(shopify_oauth, "_check_shopify_scopes", AsyncMock(return_value={"read_orders": True, "read_customers": True, "read_products": True})),
            patch.object(shopify_oauth, "_fetch_shopify_collection", fake_collection),
            patch.object(shopify_webhooks, "_handle_order_topic", handle_order),
            patch.object(shopify_webhooks, "sb_upsert", fake_sb_upsert),
            patch.object(shopify_oauth, "sb_update", AsyncMock(return_value=[])) as sb_update_mock,
            patch.object(shopify_oauth, "start_job_run", _fake_job_run()),
            patch.object(shopify_oauth, "finish_job_run", AsyncMock()) as finish_mock,
            patch("services.sync_locks.sb_rpc", AsyncMock(return_value=True)),
        ):
            result = await shopify_oauth.sync_shopify_connection(client_id="amalie", connection_id="conn-1")

        self.assertTrue(result["ok"])
        self.assertEqual(result["synced"]["orders"], 3)
        self.assertEqual(handle_order.await_count, 3)
        # Clientes persistidos em UMA chamada em lote, não uma por cliente.
        self.assertEqual(len(customer_upsert_calls), 1)
        self.assertEqual(len(customer_upsert_calls[0]), 1)
        self.assertEqual(result["synced"]["customers"], 1)
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
            patch.object(shopify_oauth, "peek_sync_lock", AsyncMock(return_value=None)),
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
            patch.object(shopify_oauth, "peek_sync_lock", AsyncMock(return_value=None)),
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
            patch.object(shopify_oauth, "peek_sync_lock", AsyncMock(return_value=None)),
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


class DiagnosticsPersistedCountsTests(unittest.IsolatedAsyncioTestCase):
    async def test_reports_count_and_date_range_per_table_without_pii(self):
        from services import shopify_reporting

        async def fake_select(table, *, select=None, filters=None, limit=None):
            if table == "shopify_orders":
                self.assertNotIn("raw_payload", select)
                self.assertNotIn("email", select)
                return [
                    {"shopify_order_id": "1", "created_at_shopify": "2026-08-01T00:00:00Z"},
                    {"shopify_order_id": "2", "created_at_shopify": "2026-08-05T00:00:00Z"},
                ]
            if table == "shopify_customers":
                return [{"shopify_customer_id": "10", "created_at_shopify": "2026-08-01T00:00:00Z"}]
            if table == "shopify_order_items":
                return [{"shopify_line_item_id": "100"}, {"shopify_line_item_id": "101"}]
            if table == "shopify_refunds":
                return []
            return []

        with patch.object(shopify_reporting, "sb_select", fake_select):
            result = await shopify_reporting.build_shopify_sync_diagnostics(
                client_id="amalie", shop_domain="amalie-6421.myshopify.com",
            )

        self.assertEqual(result["shopify_orders"]["count"], 2)
        self.assertEqual(result["shopify_orders"]["min_created_at_shopify"], "2026-08-01T00:00:00Z")
        self.assertEqual(result["shopify_orders"]["max_created_at_shopify"], "2026-08-05T00:00:00Z")
        self.assertEqual(result["shopify_customers"]["count"], 1)
        self.assertEqual(result["shopify_order_items"]["count"], 2)
        self.assertEqual(result["shopify_refunds"]["count"], 0)
        self.assertIsNone(result["shopify_refunds"]["min_created_at_shopify"])

    async def test_zero_orders_persisted_is_reported_as_zero_not_an_error(self):
        from services import shopify_reporting

        with patch.object(shopify_reporting, "sb_select", AsyncMock(return_value=[])):
            result = await shopify_reporting.build_shopify_sync_diagnostics(
                client_id="amalie", shop_domain="amalie-6421.myshopify.com",
            )

        self.assertEqual(result["shopify_orders"]["count"], 0)


class SyncDiagnosticsEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_endpoint_combines_last_job_run_and_persisted_counts(self):
        from routes import shopify as shopify_routes

        last_run = {
            "id": "job-run-1", "status": "error", "connection_id": "8e1780ef-17b0-4b0a-843e-f8c323141412",
            "payload_json": {
                "scope_check": {"read_orders": True, "read_customers": True, "read_products": True},
                "orders_received": 12, "orders_upserted": 0, "orders_failed": 12,
                "first_order_error": {"error_type": "HTTPStatusError", "error_code": "400", "db_message": "column mismatch"},
            },
        }
        persisted = {
            "shopify_orders": {"count": 0, "min_created_at_shopify": None, "max_created_at_shopify": None},
            "shopify_customers": {"count": 0, "min_created_at_shopify": None, "max_created_at_shopify": None},
            "shopify_order_items": {"count": 0, "min_created_at_shopify": None, "max_created_at_shopify": None},
            "shopify_refunds": {"count": 0, "min_created_at_shopify": None, "max_created_at_shopify": None},
        }

        with (
            patch.object(shopify_routes, "resolve_client_id", AsyncMock(return_value="amalie")),
            patch.object(shopify_routes, "resolve_shopify_connection_context", AsyncMock(return_value=_context())),
            patch.object(shopify_routes, "list_job_runs", AsyncMock(return_value={"runs": [last_run]})),
            patch.object(shopify_routes, "build_shopify_sync_diagnostics", AsyncMock(return_value=persisted)),
        ):
            payload = await shopify_routes.shopify_sync_diagnostics(
                client_id="amalie", connection_id="8e1780ef-17b0-4b0a-843e-f8c323141412",
                compare_graphql=False, x_client_id=None, authorization="Bearer valid",
            )

        self.assertEqual(payload["last_sync"]["payload_json"]["orders_received"], 12)
        self.assertEqual(payload["last_sync"]["payload_json"]["orders_upserted"], 0)
        self.assertEqual(payload["persisted"]["shopify_orders"]["count"], 0)
        self.assertIsNone(payload["graphql_scope_check"])

    async def test_endpoint_never_calls_graphql_unless_explicitly_requested(self):
        from routes import shopify as shopify_routes

        with (
            patch.object(shopify_routes, "resolve_client_id", AsyncMock(return_value="amalie")),
            patch.object(shopify_routes, "resolve_shopify_connection_context", AsyncMock(return_value=_context())),
            patch.object(shopify_routes, "list_job_runs", AsyncMock(return_value={"runs": []})),
            patch.object(shopify_routes, "build_shopify_sync_diagnostics", AsyncMock(return_value={})),
            patch.object(shopify_routes, "build_shopify_scope_diagnostic", AsyncMock()) as graphql_mock,
        ):
            await shopify_routes.shopify_sync_diagnostics(
                client_id="amalie", connection_id=None, compare_graphql=False,
                x_client_id=None, authorization="Bearer valid",
            )

        graphql_mock.assert_not_awaited()


class SyncDiagnosticsPropagationTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_order_error_is_captured_in_job_run_payload_on_total_failure(self):
        orders = [{"id": 1001}, {"id": 1002}]

        async def fake_collection(context, resource, *, params=None):
            return orders if resource == "orders.json" else []

        async def failing_handle_order(*, client_id, shop_domain, payload):
            raise RuntimeError("valor de total_price fora do esperado")

        with (
            patch.object(shopify_oauth, "resolve_shopify_connection_context", AsyncMock(return_value=_context())),
            patch.object(shopify_oauth, "peek_sync_lock", AsyncMock(return_value=None)),
            patch.object(shopify_oauth, "_check_shopify_scopes", AsyncMock(return_value={"read_orders": True, "read_customers": True, "read_products": True})),
            patch.object(shopify_oauth, "_fetch_shopify_collection", fake_collection),
            patch.object(shopify_webhooks, "_handle_order_topic", failing_handle_order),
            patch.object(shopify_oauth, "sb_update", AsyncMock(return_value=[])),
            patch.object(shopify_oauth, "start_job_run", _fake_job_run()),
            patch.object(shopify_oauth, "finish_job_run", AsyncMock()) as finish_mock,
            patch("services.sync_locks.sb_rpc", AsyncMock(return_value=True)),
        ):
            with self.assertRaises(IntegrationError):
                await shopify_oauth.sync_shopify_connection(client_id="amalie", connection_id="conn-1")

        error_payload = finish_mock.await_args.kwargs["payload_json"]
        self.assertEqual(error_payload["orders_received"], 2)
        self.assertEqual(error_payload["orders_upserted"], 0)
        self.assertIsNotNone(error_payload["first_order_error"])
        self.assertEqual(error_payload["first_order_error"]["error_type"], "RuntimeError")

    async def test_scope_check_result_is_captured_in_job_run_payload_even_on_early_failure(self):
        with (
            patch.object(shopify_oauth, "resolve_shopify_connection_context", AsyncMock(return_value=_context())),
            patch.object(shopify_oauth, "peek_sync_lock", AsyncMock(return_value=None)),
            patch.object(
                shopify_oauth, "_check_shopify_scopes",
                AsyncMock(return_value={"read_orders": False, "read_customers": True, "read_products": True}),
            ),
            patch.object(shopify_oauth, "start_job_run", _fake_job_run()),
            patch.object(shopify_oauth, "finish_job_run", AsyncMock()) as finish_mock,
            patch("services.sync_locks.sb_rpc", AsyncMock(return_value=True)),
        ):
            with self.assertRaises(IntegrationError):
                await shopify_oauth.sync_shopify_connection(client_id="amalie", connection_id="conn-1")

        error_payload = finish_mock.await_args.kwargs["payload_json"]
        self.assertFalse(error_payload["scope_check"]["read_orders"])


class ObservabilityNeverBreaksTheSyncTests(unittest.IsolatedAsyncioTestCase):
    """Bug real de produção: start_job_run era chamado FORA do try/except —
    se ele lançasse (schema incompatível, Supabase fora do ar), a exceção
    escapava de sync_shopify_connection inteira, sem nunca alcançar o
    tratamento de erro, sem gravar last_error, e a rota devolvia um 500
    opaco com last_sync permanecendo null. Estes testes travam a correção:
    job_run é estritamente best-effort em toda a função."""

    async def test_job_run_creation_failure_never_prevents_the_sync_from_running(self):
        async def fake_collection(context, resource, *, params=None):
            return [{"id": 1001}] if resource == "orders.json" else []

        with (
            patch.object(shopify_oauth, "resolve_shopify_connection_context", AsyncMock(return_value=_context())),
            patch.object(shopify_oauth, "peek_sync_lock", AsyncMock(return_value=None)),
            patch.object(shopify_oauth, "start_job_run", AsyncMock(side_effect=RuntimeError("cron_job_runs schema mismatch"))),
            patch.object(shopify_oauth, "finish_job_run", AsyncMock()) as finish_mock,
            patch.object(shopify_oauth, "_check_shopify_scopes", AsyncMock(return_value={"read_orders": True, "read_customers": True, "read_products": True})),
            patch.object(shopify_oauth, "_fetch_shopify_collection", fake_collection),
            patch.object(shopify_webhooks, "_handle_order_topic", AsyncMock(return_value={"order_id": "1001", "items_upserted": 0})),
            patch.object(shopify_oauth, "sb_update", AsyncMock(return_value=[])) as sb_update_mock,
            patch("services.sync_locks.sb_rpc", AsyncMock(return_value=True)),
        ):
            result = await shopify_oauth.sync_shopify_connection(client_id="amalie", connection_id="conn-1")

        self.assertTrue(result["ok"])
        self.assertEqual(result["synced"]["orders_upserted"], 1)
        # last_sync_at é gravado normalmente mesmo com o job_run quebrado.
        success_patch = sb_update_mock.await_args.kwargs["patch"]
        self.assertIsNotNone(success_patch["last_sync_at"])
        # finish_job_run nunca é chamado (job_run nunca existiu) — nem isso quebra nada.
        finish_mock.assert_not_awaited()

    async def test_unexpected_exception_never_escapes_as_a_raw_error_and_last_error_is_recorded(self):
        # Simula exatamente o bug real: uma exceção não-IntegrationError
        # nascendo bem no início da sincronização (ex.: dentro da própria
        # observabilidade) — nunca pode virar um 500 sem causa registrada.
        with (
            patch.object(shopify_oauth, "resolve_shopify_connection_context", AsyncMock(return_value=_context())),
            patch.object(shopify_oauth, "peek_sync_lock", AsyncMock(return_value=None)),
            patch.object(shopify_oauth, "start_job_run", AsyncMock(side_effect=KeyError("unexpected"))),
            patch.object(shopify_oauth, "finish_job_run", AsyncMock()),
            patch.object(shopify_oauth, "_check_shopify_scopes", AsyncMock(side_effect=RuntimeError("falha inesperada de rede"))),
            patch.object(shopify_oauth, "sb_update", AsyncMock(return_value=[])) as sb_update_mock,
            patch("services.sync_locks.sb_rpc", AsyncMock(return_value=True)),
        ):
            with self.assertRaises(IntegrationError) as raised:
                await shopify_oauth.sync_shopify_connection(client_id="amalie", connection_id="conn-1")

        # A causa real (RuntimeError) nunca escapa crua — vira um
        # IntegrationError com código/status previsíveis para a rota tratar.
        self.assertEqual(raised.exception.code, "SHOPIFY_SYNC_UNEXPECTED_ERROR")
        self.assertEqual(raised.exception.status_code, 502)
        # last_error é gravado com a causa real, sem exigir novo OAuth
        # (status da conexão nunca é tocado aqui).
        failure_patch = sb_update_mock.await_args.kwargs["patch"]
        self.assertIn("falha inesperada de rede", failure_patch["last_error"])
        self.assertNotIn("status", failure_patch)

    async def test_lock_still_releases_when_job_run_and_the_sync_both_fail(self):
        rpc_calls = []

        async def fake_rpc(name, _payload):
            rpc_calls.append(name)
            return True

        with (
            patch("services.sync_locks.sb_rpc", side_effect=fake_rpc),
            patch.object(shopify_oauth, "resolve_shopify_connection_context", AsyncMock(return_value=_context())),
            patch.object(shopify_oauth, "peek_sync_lock", AsyncMock(return_value=None)),
            patch.object(shopify_oauth, "start_job_run", AsyncMock(side_effect=RuntimeError("job infra down"))),
            patch.object(shopify_oauth, "_check_shopify_scopes", AsyncMock(side_effect=RuntimeError("Shopify indisponível"))),
            patch.object(shopify_oauth, "sb_update", AsyncMock(return_value=[])),
        ):
            with self.assertRaises(IntegrationError):
                await shopify_oauth.sync_shopify_connection(client_id="amalie", connection_id="conn-1")

        self.assertIn("acquire_client_job_lock", rpc_calls)
        self.assertIn("release_client_job_lock", rpc_calls)


if __name__ == "__main__":
    unittest.main()
