"""FBITS/Wake multiempresa: conexão por tenant, sincronização, isolamento e PII."""

import io
import json
import os
import sys
import unittest
from contextlib import asynccontextmanager, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "t" * 48)

from routes import fbits as fbits_routes
from services import fbits_client, fbits_connections, fbits_reporting, generic_connections, tenant
from services.crypto import decrypt_secret, encrypt_secret
from services.fbits_client import FbitsApiError, FbitsClient, FbitsRateLimiter
from services.integration_errors import IntegrationError

TOKEN = "fbits-curavino-secret-token"
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
STATUSES = [
    {"situacaoPedidoId": 1, "nome": "Pago", "descricao": "Pago"},
    {"situacaoPedidoId": 3, "nome": "Pedido Cancelado", "descricao": "Cancelado"},
    {"situacaoPedidoId": 11, "nome": "Entregue", "descricao": "Entregue"},
]


def order(pedido_id, *, status=1, data="2026-09-20T10:00:00Z", total=120.5, valido=True):
    return {
        "pedidoId": pedido_id,
        "situacaoPedidoId": status,
        "data": data,
        "dataPagamento": data,
        "dataUltimaAtualizacao": data,
        "valorTotalPedido": total,
        "valorSubTotalSemDescontos": 130.0,
        "valorDesconto": 15.5,
        "valorFrete": 6.0,
        "cupomDesconto": "BEMVINDO",
        "valido": valido,
        "primeiraCompra": True,
        "canalNome": "Loja",
        "usuario": {
            "usuarioId": 555, "tipoPessoa": "Fisica", "nome": "Cliente Sigiloso",
            "email": "cliente@example.com", "cpf": "12345678900", "telefoneCelular": "11999999999",
        },
        "pedidoEndereco": [{"endereco": "Rua Sigilosa", "cep": "01000-000"}],
        "pagamento": [{"formaPagamentoId": 1, "cartaoCredito": [{"numeroCartao": "4111"}]}],
        "itens": [
            {
                "produtoVarianteId": 9001, "sku": "VINHO-1", "nome": "Vinho Tinto", "quantidade": 2,
                "precoVenda": 70.0, "precoPor": 65.0, "desconto": 10.0, "isBrinde": False,
                "totais": {"precoVenda": 140.0, "precoPor": 130.0, "desconto": 10.0},
                "personalizacoes": [{"valor": "texto livre"}],
            },
        ],
    }


class FakeFbitsApi:
    """Simula a API oficial: /situacoesPedido e /pedidos paginado."""

    def __init__(self, orders=None, *, statuses_status=200, orders_responses=None):
        self.orders = list(orders or [])
        self.statuses_status = statuses_status
        self.orders_responses = list(orders_responses or [])
        self.requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/situacoesPedido":
            if self.statuses_status != 200:
                return httpx.Response(self.statuses_status, json={"mensagem": "token inválido"})
            return httpx.Response(200, json=STATUSES)
        if request.url.path == "/pedidos":
            if self.orders_responses:
                return self.orders_responses.pop(0)
            params = request.url.params
            start = datetime.strptime(params["dataInicial"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            end = datetime.strptime(params["dataFinal"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            matching = [
                row for row in self.orders
                if start <= datetime.fromisoformat(row["data"].replace("Z", "+00:00")) < end
            ]
            size = int(params["quantidadeRegistros"])
            page = int(params["pagina"])
            return httpx.Response(200, json=matching[(page - 1) * size: page * size])
        return httpx.Response(404, json={})

    def client_factory(self, token):
        return FbitsClient(token, transport=httpx.MockTransport(self.handler), sleep=AsyncMock())


class FakeDb:
    """integration_connections + tabelas FBITS em memória, filtradas por client_id."""

    def __init__(self, connections=None):
        self.connections = list(connections or [])
        self.upserts = {"fbits_orders": [], "fbits_order_items": [], "fbits_order_daily_stats": []}
        self.updates = []

    async def select(self, table, *, select="*", filters=None, order=None, limit=None, offset=None):
        filters = filters or {}
        if table == "integration_connections":
            rows = self.connections
            for key in ("client_id", "provider", "id"):
                if key in filters:
                    rows = [row for row in rows if str(row.get(key)) == filters[key].removeprefix("eq.")]
            return [dict(row) for row in rows]
        if table == "fbits_orders":
            cid = filters["client_id"].removeprefix("eq.")
            latest = {}
            for batch in self.upserts["fbits_orders"]:
                for row in batch:
                    if row["client_id"] == cid:
                        latest[row["order_id"]] = row
            return list(latest.values())
        return []

    async def upsert(self, table, rows, on_conflict):
        self.upserts[table].append([dict(row) for row in rows])
        return {"ok": True}

    async def update(self, table, *, filters, patch, returning="minimal"):
        self.updates.append((table, dict(filters), dict(patch)))
        for row in self.connections:
            if f"eq.{row['id']}" == filters.get("id") and f"eq.{row['client_id']}" == filters.get("client_id"):
                row.update(patch)
        return [dict(patch)]


def connection_row(client_id="curavino", **overrides):
    row = {
        "id": f"fbits-{client_id}", "client_id": client_id, "provider": "fbits", "status": "connected",
        "external_key": f"fbits:{client_id}", "encrypted_token": encrypt_secret(json.dumps({"token": TOKEN})),
        "metadata": {
            "order_statuses": [{"id": "1", "nome": "Pago"}, {"id": "3", "nome": "Pedido Cancelado"}, {"id": "11", "nome": "Entregue"}],
            "revenue_status_ids": ["1", "11"],
        },
        "disconnected_at": None, "last_sync_at": None, "last_error": None,
    }
    row.update(overrides)
    return row


@asynccontextmanager
async def no_lock(**_kwargs):
    yield "lock"


class SyncHarness(unittest.IsolatedAsyncioTestCase):
    async def run_sync(self, db, api, *, client_id="curavino"):
        output = io.StringIO()

        async def get_connection(cid, connection_id, include_token=False):
            row = next(r for r in db.connections if r["id"] == connection_id and r["client_id"] == cid)
            out = dict(row)
            if include_token:
                out["_token"] = decrypt_secret(row["encrypted_token"]) if row.get("encrypted_token") else ""
            return out

        with (
            patch.object(fbits_connections, "sb_select", AsyncMock(side_effect=db.select)),
            patch.object(fbits_connections, "sb_upsert", AsyncMock(side_effect=db.upsert)),
            patch.object(fbits_connections, "sb_update", AsyncMock(side_effect=db.update)),
            patch.object(fbits_connections, "get_connection", AsyncMock(side_effect=get_connection)),
            patch.object(fbits_connections, "invalidate_namespace", AsyncMock()),
            patch.object(fbits_connections, "guarded_sync", no_lock),
            redirect_stdout(output),
        ):
            try:
                result = await fbits_connections.sync_fbits_connection(
                    client_id=client_id, client_factory=api.client_factory, now=NOW,
                )
                error = None
            except Exception as exc:  # noqa: BLE001
                result, error = None, exc
        return result, error, output.getvalue()


# ---------------------------------------------------------------------------
# Cliente FBITS
# ---------------------------------------------------------------------------

class FbitsClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_basic_auth_header_and_valid_token(self):
        api = FakeFbitsApi()
        statuses = await api.client_factory(TOKEN).list_order_statuses()
        self.assertEqual([s["id"] for s in statuses], ["1", "3", "11"])
        self.assertEqual(api.requests[0].headers["Authorization"], f"Basic {TOKEN}")
        self.assertEqual(str(api.requests[0].url), "https://api.fbits.net/situacoesPedido")

    async def test_invalid_token_is_sanitized(self):
        api = FakeFbitsApi(statuses_status=401)
        with self.assertRaises(FbitsApiError) as raised:
            await api.client_factory(TOKEN).list_order_statuses()
        self.assertEqual(raised.exception.code, "FBITS_INVALID_TOKEN")
        self.assertNotIn(TOKEN, str(raised.exception))

    async def test_pagination_uses_official_params_and_stops_on_short_page(self):
        orders = [order(i, data=f"2026-09-2{i % 5}T10:00:00Z") for i in range(1, 113)]
        api = FakeFbitsApi(orders)
        client = api.client_factory(TOKEN)
        pages = [
            page async for page in client.iter_order_pages(
                start=datetime(2026, 9, 1, tzinfo=timezone.utc), end=NOW, date_filter="DataPedido",
            )
        ]
        self.assertEqual([len(page) for page in pages], [50, 50, 12])
        params = [dict(request.url.params) for request in api.requests]
        self.assertEqual([p["pagina"] for p in params], ["1", "2", "3"])
        self.assertTrue(all(p["quantidadeRegistros"] == "50" for p in params))
        self.assertTrue(all(p["direcaoOrdenacao"] == "ASC" for p in params))
        self.assertEqual(params[0]["enumTipoFiltroData"], "DataPedido")
        self.assertEqual(params[0]["dataInicial"], "2026-09-01 00:00:00")

    async def test_exact_multiple_stops_on_following_empty_page(self):
        api = FakeFbitsApi([order(i) for i in range(1, 51)])
        pages = [
            page async for page in api.client_factory(TOKEN).iter_order_pages(
                start=datetime(2026, 9, 1, tzinfo=timezone.utc), end=NOW,
            )
        ]
        self.assertEqual([len(page) for page in pages], [50])
        self.assertEqual(len(api.requests), 2)

    async def test_429_respects_retry_after_and_stops_without_retrying(self):
        api = FakeFbitsApi(orders_responses=[httpx.Response(429, headers={"Retry-After": "37"})])
        client = api.client_factory(TOKEN)
        with self.assertRaises(FbitsApiError) as raised:
            async for _page in client.iter_order_pages(start=datetime(2026, 9, 1, tzinfo=timezone.utc), end=NOW):
                pass
        self.assertEqual(raised.exception.code, "FBITS_RATE_LIMITED")
        self.assertEqual(raised.exception.retry_after, 37)
        self.assertEqual(len(api.requests), 1)  # nunca martela a API após 429

    async def test_server_errors_retry_a_limited_number_of_times(self):
        api = FakeFbitsApi(orders_responses=[httpx.Response(500)] * 5)
        client = api.client_factory(TOKEN)
        with self.assertRaises(FbitsApiError) as raised:
            async for _page in client.iter_order_pages(start=datetime(2026, 9, 1, tzinfo=timezone.utc), end=NOW):
                pass
        self.assertEqual(raised.exception.code, "FBITS_UNAVAILABLE")
        self.assertEqual(len(api.requests), 1 + fbits_client.FBITS_SERVER_ERROR_RETRIES)

    async def test_repeated_page_is_treated_as_pagination_loop(self):
        page = [order(i) for i in range(1, 51)]
        api = FakeFbitsApi(orders_responses=[httpx.Response(200, json=page), httpx.Response(200, json=page)])
        with self.assertRaises(FbitsApiError) as raised:
            async for _page in api.client_factory(TOKEN).iter_order_pages(
                start=datetime(2026, 9, 1, tzinfo=timezone.utc), end=NOW,
            ):
                pass
        self.assertEqual(raised.exception.code, "FBITS_PAGINATION_LOOP")

    async def test_rate_limiter_waits_before_exceeding_budget(self):
        clock = {"now": 0.0}
        sleeps = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)
            clock["now"] += seconds

        limiter = FbitsRateLimiter(max_per_minute=3, clock=lambda: clock["now"], sleep=fake_sleep)
        for _ in range(4):
            await limiter.acquire()
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 60.0)
        self.assertLessEqual(fbits_client.FBITS_MAX_REQUESTS_PER_MINUTE, 100)

    def test_client_repr_never_contains_token(self):
        self.assertNotIn(TOKEN, repr(FbitsClient(TOKEN)))


# ---------------------------------------------------------------------------
# Normalização e PII
# ---------------------------------------------------------------------------

class NormalizationTests(unittest.TestCase):
    def test_financial_fields_are_normalized(self):
        row = fbits_connections.normalize_order("curavino", order(42), {"1": "Pago"})
        self.assertEqual(row["order_id"], "42")
        self.assertEqual(row["status_id"], "1")
        self.assertEqual(row["status_name"], "Pago")
        self.assertEqual(row["total_value"], 120.5)
        self.assertEqual(row["subtotal_value"], 130.0)
        self.assertEqual(row["discount_value"], 15.5)
        self.assertEqual(row["freight_value"], 6.0)
        self.assertEqual(row["coupon_code"], "BEMVINDO")
        self.assertTrue(row["is_valid"])
        self.assertTrue(row["first_purchase"])
        self.assertEqual(row["sales_channel"], "Loja")
        self.assertEqual(row["customer_id"], "555")
        self.assertEqual(row["products_count"], 2)
        self.assertEqual(row["order_date"], "2026-09-20T10:00:00+00:00")
        items = fbits_connections.normalize_items("curavino", row)
        self.assertEqual(items[0]["item_id"], "9001:1")
        self.assertEqual(items[0]["unit_value"], 65.0)
        self.assertEqual(items[0]["total_value"], 130.0)
        self.assertEqual(items[0]["discount_value"], 10.0)
        self.assertFalse(items[0]["is_gift"])

    def test_pii_is_never_persisted(self):
        row = fbits_connections.normalize_order("curavino", order(42), {})
        items = fbits_connections.normalize_items("curavino", row)
        serialized = json.dumps({"order": row, "items": items}, ensure_ascii=False)
        for secret in ("Cliente Sigiloso", "cliente@example.com", "12345678900", "11999999999",
                       "Rua Sigilosa", "01000-000", "4111", "texto livre"):
            self.assertNotIn(secret, serialized)
        self.assertNotIn("customer_name", row)
        self.assertNotIn("customer_email", row)
        self.assertEqual(row["raw"]["usuario"], {"usuarioId": 555, "tipoPessoa": "Fisica"})

    def test_reprocessing_is_deterministic(self):
        first = fbits_connections.normalize_order("curavino", order(42), {"1": "Pago"})
        second = fbits_connections.normalize_order("curavino", order(42), {"1": "Pago"})
        self.assertEqual(first, second)
        self.assertEqual(
            fbits_connections.normalize_items("curavino", first),
            fbits_connections.normalize_items("curavino", second),
        )

    def test_daily_stats_use_only_revenue_statuses_and_zero_empty_days(self):
        rows = [
            {"order_date": "2026-09-20T10:00:00+00:00", "total_value": 100, "products_count": 2, "customer_id": "1", "status_id": "1", "is_valid": True},
            {"order_date": "2026-09-20T11:00:00+00:00", "total_value": 50, "products_count": 1, "customer_id": "1", "status_id": "11", "is_valid": None},
            {"order_date": "2026-09-20T12:00:00+00:00", "total_value": 999, "products_count": 9, "customer_id": "2", "status_id": "3", "is_valid": True},
            {"order_date": "2026-09-20T13:00:00+00:00", "total_value": 777, "products_count": 7, "customer_id": "3", "status_id": "1", "is_valid": False},
        ]
        stats = {s["stat_date"]: s for s in fbits_connections.daily_stats_rows("curavino", rows, ["2026-09-20", "2026-09-21"], ["1", "11"])}
        self.assertEqual(stats["2026-09-20"]["receita_oficial"], 150.0)
        self.assertEqual(stats["2026-09-20"]["pedidos"], 2)
        self.assertEqual(stats["2026-09-20"]["ticket_medio"], 75.0)
        self.assertEqual(stats["2026-09-20"]["clientes"], 1)
        self.assertEqual(stats["2026-09-21"]["pedidos"], 0)


# ---------------------------------------------------------------------------
# Conexão por tenant
# ---------------------------------------------------------------------------

class ConnectTests(unittest.IsolatedAsyncioTestCase):
    async def connect(self, api, db):
        writes = {"insert": [], "update": []}

        async def fake_insert(table, row, returning="minimal"):
            writes["insert"].append((table, dict(row)))
            return {"id": "fbits-curavino", **row}

        async def fake_update(table, *, filters, patch, returning="minimal"):
            writes["update"].append((table, dict(filters), dict(patch)))
            return [{"id": "fbits-curavino", "client_id": "curavino", "provider": "fbits", **patch}]

        output = io.StringIO()
        with (
            patch.object(generic_connections, "sb_select", AsyncMock(side_effect=db.select)),
            patch.object(generic_connections, "sb_insert", AsyncMock(side_effect=fake_insert)),
            patch.object(generic_connections, "sb_update", AsyncMock(side_effect=fake_update)),
            patch.object(generic_connections, "invalidate_namespace", AsyncMock()),
            redirect_stdout(output),
        ):
            try:
                result = await fbits_connections.connect_fbits(
                    client_id="curavino", user_id="user-admin", token=TOKEN, client_factory=api.client_factory,
                )
                error = None
            except Exception as exc:  # noqa: BLE001
                result, error = None, exc
        return result, error, writes, output.getvalue()

    async def test_valid_token_is_encrypted_and_persisted_for_the_tenant(self):
        result, error, writes, logs = await self.connect(FakeFbitsApi(), FakeDb())
        self.assertIsNone(error)
        table, row = next(w for w in writes["insert"] if w[0] == "integration_connections")
        self.assertEqual(row["client_id"], "curavino")
        self.assertEqual(row["provider"], "fbits")
        self.assertEqual(row["external_key"], "fbits:curavino")
        self.assertEqual(row["status"], "connected")
        self.assertNotIn(TOKEN, row["encrypted_token"])
        self.assertEqual(json.loads(decrypt_secret(row["encrypted_token"]))["token"], TOKEN)
        self.assertNotIn(TOKEN, row["external_key"])
        self.assertEqual(row["metadata"]["revenue_status_ids"], ["1", "11"])
        self.assertFalse(row["metadata"]["revenue_rule_confirmed"])
        self.assertNotIn(TOKEN, json.dumps(result, default=str))
        self.assertNotIn("encrypted_token", result["connection"])
        self.assertNotIn(TOKEN, logs)

    async def test_invalid_token_is_never_persisted(self):
        result, error, writes, logs = await self.connect(FakeFbitsApi(statuses_status=401), FakeDb())
        self.assertIsInstance(error, IntegrationError)
        self.assertEqual(error.code, "FBITS_INVALID_TOKEN")
        self.assertEqual(writes, {"insert": [], "update": []})
        self.assertNotIn(TOKEN, str(error))
        self.assertNotIn(TOKEN, logs)

    async def test_reconnect_updates_the_same_row(self):
        db = FakeDb([connection_row()])
        _result, error, writes, _logs = await self.connect(FakeFbitsApi(), db)
        self.assertIsNone(error)
        self.assertFalse([w for w in writes["insert"] if w[0] == "integration_connections"])
        _table, filters, _patch = next(w for w in writes["update"] if w[0] == "integration_connections")
        self.assertEqual(filters["client_id"], "eq.curavino")

    async def test_shopify_row_of_same_tenant_is_not_touched(self):
        shopify = {"id": "shopify-curavino", "client_id": "curavino", "provider": "shopify", "external_key": "loja.myshopify.com"}
        db = FakeDb([shopify])
        _result, error, writes, _logs = await self.connect(FakeFbitsApi(), db)
        self.assertIsNone(error)
        self.assertFalse([w for w in writes["update"] if "shopify" in str(w[1].get("id", ""))])
        self.assertEqual(db.connections, [shopify])


class RouteAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_viewer_cannot_connect(self):
        connect = AsyncMock()
        with (
            patch.object(tenant, "require_user_id", AsyncMock(return_value="user-viewer")),
            patch.object(tenant, "resolve_client_id", AsyncMock(return_value="curavino")),
            patch.object(tenant, "_has_agency_admin_membership", AsyncMock(return_value=False)),
            patch("services.platform_admin.is_platform_admin", AsyncMock(return_value=False)),
            patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=[{"client_id": "curavino", "role": "viewer"}])),
            patch.object(fbits_routes, "connect_fbits", connect),
        ):
            with self.assertRaises(HTTPException) as raised:
                await fbits_routes.fbits_connect(
                    "curavino", {"token": TOKEN}, background_tasks=type("BT", (), {"add_task": lambda *a, **k: None})(),
                    authorization="Bearer viewer",
                )
        self.assertEqual(raised.exception.status_code, 403)
        connect.assert_not_awaited()

    async def test_connect_uses_only_the_authorized_tenant_and_hides_token(self):
        tasks = []
        connect = AsyncMock(return_value={"connection": {"id": "fbits-curavino", "client_id": "curavino"}, "order_statuses_count": 3})
        with (
            patch.object(fbits_routes, "require_client_role", AsyncMock(return_value="curavino")),
            patch.object(fbits_routes, "require_user_id", AsyncMock(return_value="user-admin")),
            patch.object(fbits_routes, "connect_fbits", connect),
        ):
            response = await fbits_routes.fbits_connect(
                "curavino", {"token": TOKEN},
                background_tasks=type("BT", (), {"add_task": lambda self, *a, **k: tasks.append(a)})(),
                authorization="Bearer admin",
            )
        self.assertEqual(connect.await_args.kwargs["client_id"], "curavino")
        self.assertNotIn(TOKEN, json.dumps(response))
        self.assertEqual(tasks[0][1], "curavino")

    async def test_tenant_without_connection_cannot_sync_even_with_global_env_token(self):
        with (
            patch.dict(os.environ, {"CLIENT_FBITS_API_TOKEN": "global-token", "FBITS_API_TOKEN": "global-token"}),
            patch.object(fbits_routes, "require_client_role", AsyncMock(return_value="empresa-b")),
            patch.object(fbits_routes, "load_fbits_connection", AsyncMock(return_value=None)),
        ):
            with self.assertRaises(IntegrationError) as raised:
                await fbits_routes.fbits_sync(
                    background_tasks=type("BT", (), {"add_task": lambda *a, **k: None})(),
                    client_id="empresa-b", x_client_id=None, authorization="Bearer admin",
                )
        self.assertEqual(raised.exception.code, "FBITS_CONNECTION_NOT_FOUND")

    async def test_legacy_debug_endpoints_are_disabled(self):
        with self.assertRaises(HTTPException) as raised:
            await fbits_routes.fbits_debug_orders()
        self.assertEqual(raised.exception.status_code, 410)

    def test_global_env_token_is_not_an_operational_path(self):
        for module in (fbits_client, fbits_connections, fbits_reporting, fbits_routes):
            source = Path(module.__file__).read_text()
            self.assertNotIn("CLIENT_FBITS_API_TOKEN", source)
            self.assertNotIn("os.getenv", source)
            self.assertNotIn("os.environ", source)


# ---------------------------------------------------------------------------
# Sincronização
# ---------------------------------------------------------------------------

class SyncTests(SyncHarness):
    async def test_initial_history_is_90_days_in_7_day_windows_and_persists_orders(self):
        orders = [order(1, data="2026-07-10T10:00:00Z"), order(2, status=3, data="2026-09-20T10:00:00Z")]
        api = FakeFbitsApi(orders)
        db = FakeDb([connection_row()])
        result, error, logs = await self.run_sync(db, api)

        self.assertIsNone(error)
        self.assertEqual(result["mode"], "historical")
        self.assertEqual(result["orders_upserted"], 2)
        pedidos = [dict(r.url.params) for r in api.requests if r.url.path == "/pedidos"]
        self.assertEqual(pedidos[0]["dataInicial"], (NOW - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S"))
        self.assertEqual(pedidos[-1]["dataFinal"], NOW.strftime("%Y-%m-%d %H:%M:%S"))
        self.assertTrue(all(p["enumTipoFiltroData"] == "DataPedido" for p in pedidos))
        self.assertEqual(len(pedidos), len(fbits_connections.plan_windows(NOW - timedelta(days=90), NOW)))
        state = db.connections[0]
        self.assertEqual(state["status"], "connected")
        self.assertIsNone(state["last_error"])
        self.assertTrue(state["metadata"]["history_completed_at"])
        self.assertEqual(state["metadata"]["incremental_marker"], NOW.isoformat())
        self.assertNotIn(TOKEN, logs)
        daily = {row["stat_date"]: row for batch in db.upserts["fbits_order_daily_stats"] for row in batch}
        self.assertEqual(daily["2026-07-10"]["pedidos"], 1)
        self.assertEqual(daily["2026-09-20"]["pedidos"], 0)  # cancelado não entra na receita

    async def test_incremental_uses_marker_minus_two_hours_and_data_alteracao(self):
        marker = NOW - timedelta(hours=6)
        db = FakeDb([connection_row(metadata={
            **connection_row()["metadata"],
            "history_completed_at": (NOW - timedelta(days=1)).isoformat(),
            "incremental_marker": marker.isoformat(),
        })])
        api = FakeFbitsApi([order(7, data=(NOW - timedelta(hours=3)).isoformat())])
        result, error, _logs = await self.run_sync(db, api)
        self.assertIsNone(error)
        self.assertEqual(result["mode"], "incremental")
        params = dict(next(r for r in api.requests if r.url.path == "/pedidos").url.params)
        self.assertEqual(params["enumTipoFiltroData"], "DataAlteracao")
        self.assertEqual(params["dataInicial"], (marker - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"))

    async def test_resync_is_idempotent(self):
        api = FakeFbitsApi([order(1, data="2026-09-20T10:00:00Z")])
        db = FakeDb([connection_row()])
        await self.run_sync(db, api)
        db.connections[0]["metadata"].pop("history_completed_at")
        db.connections[0]["metadata"].pop("incremental_marker")
        await self.run_sync(db, api)
        batches = db.upserts["fbits_orders"]
        self.assertEqual(batches[0], batches[1])
        stored = await db.select("fbits_orders", filters={"client_id": "eq.curavino"})
        self.assertEqual(len(stored), 1)

    async def test_rate_limit_stops_cycle_keeps_progress_and_sanitizes_error(self):
        api = FakeFbitsApi(orders_responses=[
            httpx.Response(200, json=[]),
            httpx.Response(429, headers={"Retry-After": "45"}),
        ])
        db = FakeDb([connection_row()])
        _result, error, logs = await self.run_sync(db, api)
        self.assertIsInstance(error, IntegrationError)
        self.assertEqual(error.status_code, 429)
        self.assertEqual(len([r for r in api.requests if r.url.path == "/pedidos"]), 2)
        state = db.connections[0]
        self.assertEqual(state["status"], "sync_error")
        self.assertIn("Limite de requisições", state["last_error"])
        self.assertNotIn(TOKEN, state["last_error"])
        self.assertTrue(state["metadata"]["history_cursor"])  # próxima execução retoma daqui
        self.assertNotIn(TOKEN, logs)

    async def test_tenant_a_sync_never_reads_or_writes_tenant_b(self):
        db = FakeDb([connection_row("curavino"), connection_row("empresa-b")])
        api = FakeFbitsApi([order(1, data="2026-09-20T10:00:00Z")])
        await self.run_sync(db, api, client_id="curavino")
        written = [row for batch in db.upserts["fbits_orders"] for row in batch]
        self.assertTrue(written)
        self.assertTrue(all(row["client_id"] == "curavino" for row in written))
        touched = [u for u in db.updates if u[0] == "integration_connections"]
        self.assertTrue(all(u[1]["client_id"] == "eq.curavino" for u in touched))
        self.assertIsNone(db.connections[1]["last_sync_at"])

    async def test_tenant_without_connection_makes_no_api_call(self):
        api = FakeFbitsApi([order(1)])
        with patch.dict(os.environ, {"CLIENT_FBITS_API_TOKEN": "global-token"}):
            _result, error, _logs = await self.run_sync(FakeDb([]), api, client_id="empresa-b")
        self.assertEqual(error.code, "FBITS_CONNECTION_NOT_FOUND")
        self.assertEqual(api.requests, [])

    async def test_disconnected_connection_cannot_sync(self):
        api = FakeFbitsApi([order(1)])
        db = FakeDb([connection_row(status="disconnected", encrypted_token="", disconnected_at="2026-09-01T00:00:00Z")])
        _result, error, _logs = await self.run_sync(db, api)
        self.assertEqual(error.code, "FBITS_CONNECTION_DISCONNECTED")
        self.assertEqual(api.requests, [])


class DisconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_clears_token_and_preserves_history(self):
        db = FakeDb([connection_row()])
        disconnect = AsyncMock(return_value={"id": "fbits-curavino", "status": "disconnected"})
        with (
            patch.object(fbits_connections, "sb_select", AsyncMock(side_effect=db.select)),
            patch.object(fbits_connections, "disconnect_generic_connection", disconnect),
            patch.object(fbits_connections, "sb_upsert", AsyncMock()) as upsert,
        ):
            await fbits_connections.disconnect_fbits(client_id="curavino", user_id="user-admin")
        disconnect.assert_awaited_once_with("curavino", "fbits-curavino", "user-admin")
        upsert.assert_not_awaited()
        self.assertFalse(hasattr(fbits_connections, "sb_delete"))


class Migration037Tests(unittest.TestCase):
    def test_migration_037_is_additive_only(self):
        path = Path(SERVER_DIR).parent / "supabase" / "migrations" / "20261001_000037_fbits_order_financials.sql"
        sql = "\n".join(
            line for line in path.read_text().lower().splitlines() if not line.strip().startswith("--")
        )
        for forbidden in ("drop ", "delete ", "truncate", "alter column", "rename "):
            self.assertNotIn(forbidden, sql)
        for column in ("subtotal_value", "discount_value", "freight_value", "coupon_code", "is_valid",
                       "first_purchase", "sales_channel", "source_updated_at", "is_gift"):
            self.assertIn(f"add column if not exists {column}", sql)
        self.assertIn("on public.fbits_orders(client_id, source_updated_at)", sql)


class ReportingTests(unittest.IsolatedAsyncioTestCase):
    async def test_summary_reports_tenant_connection_state_not_global_env(self):
        with (
            patch.dict(os.environ, {"CLIENT_FBITS_API_TOKEN": "global-token"}),
            patch.object(fbits_reporting, "fbits_connection_state", AsyncMock(return_value={"connected": False, "connection": None})),
            patch.object(fbits_reporting, "sb_select", AsyncMock(return_value=[])),
        ):
            summary = await fbits_reporting.build_fbits_summary(
                client_id="empresa-b", period=fbits_reporting.FbitsPeriod("2026-09-01", "2026-09-30"),
            )
        self.assertFalse(summary["connected"])
        self.assertEqual(summary["summary"]["pedidos"], 0)
        self.assertEqual(summary["kpi_source"], "fbits_orders_fallback")
        self.assertEqual(summary["kpi_fallback_reason"], "FBITS_NOT_CONNECTED")

    def test_revenue_filter_excludes_cancelled_and_invalid_orders(self):
        ids = {"1", "11"}
        self.assertTrue(fbits_reporting._counts_as_revenue({"status_id": "1", "raw": {"valido": True}}, ids))
        self.assertFalse(fbits_reporting._counts_as_revenue({"status_id": "3", "raw": {}}, ids))
        self.assertFalse(fbits_reporting._counts_as_revenue({"status_id": "1", "raw": {"valido": False}}, ids))

    def test_period_validation_and_sao_paulo_boundaries(self):
        period = fbits_reporting.resolve_fbits_period(start="2026-09-01", end="2026-09-30")
        self.assertEqual(
            fbits_reporting._period_filter(period, "order_date"),
            "(order_date.gte.2026-09-01T03:00:00Z,order_date.lt.2026-10-01T03:00:00Z)",
        )
        with self.assertRaisesRegex(RuntimeError, "start deve ser anterior"):
            fbits_reporting.resolve_fbits_period(start="2026-09-30", end="2026-09-01")
        with self.assertRaisesRegex(RuntimeError, "start e end juntos"):
            fbits_reporting.resolve_fbits_period(start="2026-09-01", end=None)

    async def test_summary_uses_order_date_rows_and_previous_equivalent_period(self):
        current = [
            {
                "order_id": "paid", "status_id": "1", "status_name": "Pago",
                "order_date": "2026-09-01T03:30:00Z", "total_value": 200,
                "discount_value": 20, "freight_value": 12, "products_count": 2,
                "customer_id": "customer-a", "is_valid": True, "raw": {},
            },
            {
                "order_id": "cancelled", "status_id": "3", "status_name": "Cancelado",
                "order_date": "2026-09-02T15:00:00Z", "total_value": 900,
                "discount_value": 0, "freight_value": 0, "products_count": 1,
                "customer_id": "customer-b", "is_valid": False, "raw": {},
            },
        ]
        previous = [
            {
                "order_id": "previous", "status_id": "1", "status_name": "Pago",
                "order_date": "2026-08-30T15:00:00Z", "total_value": 100,
                "discount_value": 5, "freight_value": 8, "products_count": 1,
                "customer_id": "customer-a", "is_valid": True, "raw": {},
            },
        ]
        state = {
            "connected": True,
            "connection": {"metadata": {"revenue_status_ids": ["1"]}, "last_sync_at": "2026-09-30T12:00:00Z"},
        }
        select = AsyncMock(side_effect=[current, previous])
        # Oficial indisponível: o fallback derivado dos pedidos é identificado.
        official = AsyncMock(side_effect=fbits_reporting.OfficialKpisUnavailable("FBITS_UNAVAILABLE"))
        with (
            patch.object(fbits_reporting, "fbits_connection_state", AsyncMock(return_value=state)),
            patch.object(fbits_reporting, "sb_select", select),
            patch.object(fbits_reporting, "fetch_official_kpis", official),
        ):
            summary = await fbits_reporting.build_fbits_summary(
                client_id="curavino", period=fbits_reporting.FbitsPeriod("2026-09-01", "2026-09-02"),
            )
        self.assertEqual(summary["kpi_source"], "fbits_orders_fallback")
        self.assertEqual(summary["kpi_fallback_reason"], "FBITS_UNAVAILABLE")
        self.assertEqual(summary["summary"]["receita_oficial"], 200)
        self.assertEqual(summary["summary"]["pedidos"], 1)
        self.assertEqual(summary["summary"]["ticket_medio"], 200)
        self.assertEqual(summary["comparison"]["receita_oficial"]["change_percent"], 100)
        self.assertEqual(summary["previous_period"], {"start": "2026-08-30", "end": "2026-08-31"})
        cancelled = next(item for item in summary["status_distribution"] if item["status"] == "Cancelado")
        self.assertEqual(cancelled["invalid_orders"], 1)
        self.assertEqual(summary["trend"]["items"][0]["date"], "2026-09-01")
        filters = [call.kwargs["filters"]["and"] for call in select.await_args_list]
        self.assertIn("order_date.gte.2026-09-01T03:00:00Z", filters[0])
        self.assertIn("order_date.gte.2026-08-30T03:00:00Z", filters[1])

    def test_comparison_without_previous_base_is_not_false_zero_percent(self):
        self.assertIsNone(fbits_reporting._comparison_value(250, 0)["change_percent"])

    def test_sales_trend_selects_daily_weekly_and_monthly_granularity(self):
        row = {"status_id": "1", "is_valid": True, "order_date": "2026-01-01T15:00:00Z", "total_value": 10}
        self.assertEqual(fbits_reporting._sales_trend(fbits_reporting.FbitsPeriod("2026-01-01", "2026-01-31"), [row], {"1"})["granularity"], "day")
        self.assertEqual(fbits_reporting._sales_trend(fbits_reporting.FbitsPeriod("2026-01-01", "2026-02-01"), [row], {"1"})["granularity"], "week")
        self.assertEqual(fbits_reporting._sales_trend(fbits_reporting.FbitsPeriod("2026-01-01", "2026-05-01"), [row], {"1"})["granularity"], "month")


if __name__ == "__main__":
    unittest.main()
