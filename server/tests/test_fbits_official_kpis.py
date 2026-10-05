"""KPIs executivos oficiais da FBITS (GET /dashboard/faturamento).

Valores sintéticos: os números reais de aceite (Curavino, setembro/2026) NÃO
aparecem no código nem nos testes — vêm da API em produção.
"""

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import BackgroundTasks

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "t" * 48)

from routes import fbits as fbits_routes
from services import fbits_official_kpis, fbits_reporting, runtime_cache
from services.fbits_client import FbitsClient
from services.fbits_official_kpis import OfficialKpisUnavailable, parse_revenue_indicators
from services.fbits_reporting import FbitsPeriod

TOKENS = {"loja-a": "token-loja-a-secreto", "loja-b": "token-loja-b-secreto"}


def indicators(receita=1000.0, pedidos=3, ticket=300.0, receita_ant=500.0, pedidos_ant=2, ticket_ant=250.0):
    return {
        "indicadorReceita": receita, "indicadorPedido": pedidos, "indicadorTicketMedio": ticket,
        "indicadorReceitaComparativo": receita_ant, "indicadorPedidoComparativo": pedidos_ant,
        "indicadorTicketMedioComparativo": ticket_ant,
        "indicadorReceitaFormatado": "ignorado",
    }


class FakeDashboard:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.path == "/dashboard/faturamento"
        if self.responses:
            return self.responses.pop(0)
        return httpx.Response(200, json=indicators())

    def factory(self, token):
        return FbitsClient(token, transport=httpx.MockTransport(self.handler), sleep=AsyncMock())


def connection(client_id, **overrides):
    return {"id": f"fbits-{client_id}", "client_id": client_id, "provider": "fbits", "status": "connected",
            "disconnected_at": None, **overrides}


class OfficialBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        runtime_cache._CACHE.clear()
        runtime_cache._INFLIGHT.clear()
        fbits_official_kpis._FAILURES.clear()
        self.connections = {cid: connection(cid) for cid in TOKENS}
        self.tokens_requested = []
        self.api = FakeDashboard()

        async def load(cid):
            return self.connections.get(cid)

        async def get_conn(cid, connection_id, include_token=False):
            assert connection_id == f"fbits-{cid}"
            self.tokens_requested.append(cid)
            return {"_token": json.dumps({"token": TOKENS[cid]})} if TOKENS.get(cid) else {"_token": ""}

        self.patches = [
            patch.object(fbits_official_kpis, "sb_update", AsyncMock()),
            patch.object(fbits_official_kpis, "load_fbits_connection", AsyncMock(side_effect=load)),
            patch.object(fbits_official_kpis, "get_connection", AsyncMock(side_effect=get_conn)),
            patch.object(fbits_official_kpis, "client_factory", lambda token: self.api.factory(token)),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in self.patches])

    async def fetch(self, cid="loja-a", period=FbitsPeriod("2026-09-01", "2026-09-30")):
        previous = fbits_reporting._previous_period(period)
        return await fbits_official_kpis.fetch_official_kpis(
            client_id=cid, start=period.start, end=period.end,
            previous_start=previous.start, previous_end=previous.end,
        )


class ParseTests(unittest.TestCase):
    def test_maps_the_three_indicators_and_keeps_the_official_ticket(self):
        parsed = parse_revenue_indicators(indicators(receita=1000.0, pedidos=3, ticket=300.0))
        # 1000/3 = 333,33: o ticket exibido é o da FBITS, não recalculado.
        self.assertEqual(parsed["current"], {"receita_oficial": 1000.0, "pedidos": 3, "ticket_medio": 300.0})
        self.assertEqual(parsed["previous"], {"receita_oficial": 500.0, "pedidos": 2, "ticket_medio": 250.0})

    def test_rounds_like_the_panel(self):
        parsed = parse_revenue_indicators({"indicadorReceita": 61592.678, "indicadorPedido": 37, "indicadorTicketMedio": 1664.667})
        self.assertEqual(parsed["current"], {"receita_oficial": 61592.68, "pedidos": 37, "ticket_medio": 1664.67})
        self.assertIsNone(parsed["previous"])

    def test_invalid_response_is_never_a_zero(self):
        for payload in ({}, {"indicadorPedido": 3}, {"indicadorReceita": "abc", "indicadorPedido": 1}, {"indicadorReceita": True, "indicadorPedido": 1}):
            with self.subTest(payload=payload), self.assertRaises(OfficialKpisUnavailable) as ctx:
                parse_revenue_indicators(payload)
            self.assertEqual(ctx.exception.code, "FBITS_DASHBOARD_INVALID_RESPONSE")


class FetchTests(OfficialBase):
    def test_default_client_fails_fast_without_retries(self):
        client = fbits_official_kpis._default_client_factory("token-x")
        self.assertEqual(client._server_error_retries, 0)
        self.assertEqual(client._timeout, fbits_official_kpis.OFFICIAL_TIMEOUT_SECONDS)

    async def test_full_september_and_previous_period_in_one_call(self):
        await self.fetch(period=FbitsPeriod("2026-09-01", "2026-09-30"))
        params = dict(self.api.requests[0].url.params)
        self.assertEqual(params, {
            "dataInicial": "2026-09-01", "dataFinal": "2026-09-30",
            "dataInicialComparativo": "2026-08-02", "dataFinalComparativo": "2026-08-31",
        })

    async def test_custom_period_sends_plain_dates_without_time_or_timezone(self):
        await self.fetch(period=FbitsPeriod("2026-09-10", "2026-09-12"))
        params = dict(self.api.requests[0].url.params)
        self.assertEqual(params["dataInicial"], "2026-09-10")
        self.assertEqual(params["dataFinal"], "2026-09-12")
        self.assertEqual((params["dataInicialComparativo"], params["dataFinalComparativo"]), ("2026-09-07", "2026-09-09"))
        self.assertNotIn(":", "".join(params.values()))

    async def test_cache_hit_and_invalidation(self):
        await self.fetch()
        await self.fetch()
        self.assertEqual(len(self.api.requests), 1)
        await fbits_official_kpis.invalidate_official_kpis("loja-a")
        await self.fetch()
        self.assertEqual(len(self.api.requests), 2)

    async def test_tenant_isolation_of_token_and_cache(self):
        await self.fetch("loja-a")
        await self.fetch("loja-b")
        self.assertEqual(len(self.api.requests), 2)
        self.assertEqual([r.headers["Authorization"] for r in self.api.requests],
                         [f"Basic {TOKENS['loja-a']}", f"Basic {TOKENS['loja-b']}"])
        await fbits_official_kpis.invalidate_official_kpis("loja-a")
        await self.fetch("loja-b")
        self.assertEqual(len(self.api.requests), 2)  # B continua em cache

    async def test_not_connected_or_disconnected_makes_no_request(self):
        self.connections["loja-a"] = connection("loja-a", status="disconnected", disconnected_at="2026-09-01T00:00:00Z")
        with self.assertRaises(OfficialKpisUnavailable) as ctx:
            await self.fetch("loja-a")
        self.assertEqual(ctx.exception.code, "FBITS_NOT_CONNECTED")
        self.connections.pop("loja-b")
        with self.assertRaises(OfficialKpisUnavailable):
            await self.fetch("loja-b")
        self.assertEqual(self.api.requests, [])

    async def test_missing_token_requires_reauth(self):
        with patch.dict(TOKENS, {"loja-a": ""}), self.assertRaises(OfficialKpisUnavailable) as ctx:
            await self.fetch("loja-a")
        self.assertEqual(ctx.exception.code, "FBITS_REAUTH_REQUIRED")

    async def test_api_failure_backs_off_without_hammering_the_token(self):
        self.api.responses = [httpx.Response(401, json={})]
        with self.assertRaises(OfficialKpisUnavailable) as ctx:
            await self.fetch()
        self.assertEqual(ctx.exception.code, "FBITS_INVALID_TOKEN")
        with self.assertRaises(OfficialKpisUnavailable):
            await self.fetch()
        self.assertEqual(len(self.api.requests), 1)
        # Sincronizar libera a nova tentativa (não é 429).
        await fbits_official_kpis.invalidate_official_kpis("loja-a")
        await self.fetch()
        self.assertEqual(len(self.api.requests), 2)

    async def test_rate_limit_backoff_survives_invalidation(self):
        self.api.responses = [httpx.Response(429, headers={"Retry-After": "120"}, json={})]
        with self.assertRaises(OfficialKpisUnavailable) as ctx:
            await self.fetch()
        self.assertEqual(ctx.exception.code, "FBITS_RATE_LIMITED")
        await fbits_official_kpis.invalidate_official_kpis("loja-a")
        with self.assertRaises(OfficialKpisUnavailable):
            await self.fetch()
        self.assertEqual(len(self.api.requests), 1)

    async def test_token_never_logged(self):
        output = io.StringIO()
        with redirect_stdout(output):
            await self.fetch()
            self.api.responses = [httpx.Response(500, json={})] * 3
            await fbits_official_kpis.invalidate_official_kpis("loja-a")
            with self.assertRaises(OfficialKpisUnavailable):
                await self.fetch()
        self.assertNotIn(TOKENS["loja-a"], output.getvalue())


ROWS = [
    {"order_id": "a", "status_id": "1", "status_name": "Pago", "order_date": "2026-09-05T15:00:00Z",
     "total_value": 400, "discount_value": 10, "freight_value": 20, "products_count": 2,
     "customer_id": "c1", "is_valid": True, "raw": {}},
    {"order_id": "b", "status_id": "7", "status_name": "Faturado", "order_date": "2026-09-06T15:00:00Z",
     "total_value": 600, "discount_value": 0, "freight_value": 30, "products_count": 1,
     "customer_id": "c2", "is_valid": True, "raw": {}},
]


class SummaryTests(unittest.IsolatedAsyncioTestCase):
    async def summary(self, official, *, rows=ROWS, previous_rows=(), connected=True):
        state = {"connected": connected, "connection": {"metadata": {"revenue_status_ids": ["1"]}, "last_sync_at": None}}
        self.official = official if isinstance(official, AsyncMock) else AsyncMock(return_value=official)
        with (
            patch.object(fbits_reporting, "fbits_connection_state", AsyncMock(return_value=state)),
            patch.object(fbits_reporting, "sb_select", AsyncMock(side_effect=[list(rows), list(previous_rows)])),
            patch.object(fbits_reporting, "fetch_official_kpis", self.official),
        ):
            return await fbits_reporting.build_fbits_summary(client_id="loja-a", period=FbitsPeriod("2026-09-01", "2026-09-30"))

    async def test_executive_kpis_come_from_the_official_endpoint(self):
        payload = await self.summary(parse_revenue_indicators(indicators(receita=1000.0, pedidos=3, ticket=300.0)))
        self.assertEqual(payload["kpi_source"], "fbits_dashboard")
        self.assertIsNone(payload["kpi_fallback_reason"])
        s = payload["summary"]
        self.assertEqual((s["receita_oficial"], s["pedidos"], s["ticket_medio"]), (1000.0, 3, 300.0))
        # A regra de situações sobre os pedidos fica só como referência analítica.
        self.assertEqual(payload["derived_kpis"], {"receita_oficial": 400.0, "pedidos": 1, "ticket_medio": 400.0})
        self.official.assert_awaited_once_with(
            client_id="loja-a", start="2026-09-01", end="2026-09-30",
            previous_start="2026-08-02", previous_end="2026-08-31",
        )

    async def test_previous_period_comparison_uses_the_same_official_concept(self):
        payload = await self.summary(parse_revenue_indicators(indicators(receita=1000.0, pedidos=4, ticket=250.0,
                                                                         receita_ant=500.0, pedidos_ant=2, ticket_ant=250.0)))
        self.assertEqual(payload["comparison"]["receita_oficial"], {"current": 1000.0, "previous": 500.0, "change_percent": 100.0})
        self.assertEqual(payload["comparison"]["pedidos"]["change_percent"], 100.0)
        self.assertEqual(payload["comparison"]["ticket_medio"]["change_percent"], 0.0)

    async def test_missing_official_comparison_is_not_a_false_change(self):
        payload = await self.summary({"current": {"receita_oficial": 10.0, "pedidos": 1, "ticket_medio": 10.0}, "previous": None})
        self.assertEqual(payload["comparison"]["receita_oficial"], {"current": 10.0, "previous": None, "change_percent": None})

    async def test_derived_analytics_are_unchanged(self):
        payload = await self.summary(parse_revenue_indicators(indicators()))
        s = payload["summary"]
        self.assertEqual((s["clientes"], s["produtos_vendidos"], s["descontos"], s["frete"]), (1, 2, 10.0, 20.0))
        self.assertEqual({item["status"]: item["pedidos"] for item in payload["status_distribution"]}, {"Pago": 1, "Faturado": 1})
        self.assertEqual(sum(point["revenue"] for point in payload["trend"]["items"]), 400.0)

    async def test_official_failure_uses_an_identified_fallback(self):
        payload = await self.summary(AsyncMock(side_effect=OfficialKpisUnavailable("FBITS_UNAVAILABLE")))
        self.assertEqual(payload["kpi_source"], "fbits_orders_fallback")
        self.assertEqual(payload["kpi_fallback_reason"], "FBITS_UNAVAILABLE")
        self.assertEqual(payload["summary"]["receita_oficial"], 400.0)
        self.assertEqual(payload["summary"]["pedidos"], 1)

    async def test_not_connected_never_calls_the_official_endpoint(self):
        payload = await self.summary(AsyncMock(), connected=False)
        self.official.assert_not_awaited()
        self.assertEqual(payload["kpi_fallback_reason"], "FBITS_NOT_CONNECTED")

    async def test_official_sales_before_first_sync_are_not_hidden(self):
        payload = await self.summary(parse_revenue_indicators(indicators()), rows=[])
        self.assertEqual(payload["summary"]["pedidos"], 3)
        self.assertIsNone(payload["message"])

    async def test_official_zero_says_no_sales(self):
        payload = await self.summary(parse_revenue_indicators(indicators(receita=0, pedidos=0, ticket=0)), rows=[])
        self.assertEqual(payload["message"], "Não houve vendas neste período.")


class SyncInvalidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_now_invalidates_before_scheduling_and_after_finishing(self):
        invalidate = AsyncMock()
        tasks = BackgroundTasks()
        with (
            patch.object(fbits_routes, "invalidate_official_kpis", invalidate),
            patch.object(fbits_routes, "load_fbits_connection", AsyncMock(return_value=connection("loja-a"))),
        ):
            result = await fbits_routes._schedule_tenant_sync("loja-a", tasks)
        self.assertTrue(result["scheduled"])
        invalidate.assert_awaited_once_with("loja-a")

        for outcome in (AsyncMock(return_value={"ok": True}), AsyncMock(side_effect=RuntimeError("falhou"))):
            invalidate.reset_mock()
            with (
                patch.object(fbits_routes, "invalidate_official_kpis", invalidate),
                patch.object(fbits_routes, "sync_fbits_connection", outcome),
                redirect_stdout(io.StringIO()),
            ):
                await fbits_routes._run_fbits_sync_isolated("loja-a")
            invalidate.assert_awaited_once_with("loja-a")

    async def test_disconnect_invalidates_the_tenant_cache(self):
        invalidate = AsyncMock()
        with (
            patch.object(fbits_routes, "invalidate_official_kpis", invalidate),
            patch.object(fbits_routes, "require_client_role", AsyncMock(return_value="loja-a")),
            patch.object(fbits_routes, "require_user_id", AsyncMock(return_value="user-1")),
            patch.object(fbits_routes, "disconnect_fbits", AsyncMock(return_value={"id": "fbits-loja-a"})),
        ):
            await fbits_routes.fbits_disconnect("loja-a", authorization="Bearer x")
        invalidate.assert_awaited_once_with("loja-a")


class NoHardcodedAcceptanceNumbersTests(unittest.TestCase):
    def test_acceptance_values_are_not_in_the_code(self):
        for name in ("fbits_official_kpis.py", "fbits_reporting.py", "fbits_client.py"):
            source = (Path(SERVER_DIR) / "services" / name).read_text(encoding="utf-8")
            for value in ("34255", "34.255", "469.25", "469,25"):
                self.assertNotIn(value, source, f"{name} contém {value}")


if __name__ == "__main__":
    unittest.main()
