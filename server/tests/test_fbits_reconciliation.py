"""Reconciliação FBITS pedido a pedido (diagnóstico somente leitura).

Fixture SINTÉTICA e sanitizada de setembro/2026 — não são os pedidos reais da
Curavino. Ela reproduz os mecanismos que o diagnóstico precisa detectar:
paginação (65 pedidos > 50), situação pós-pagamento fora de
revenue_status_ids, pedido não sincronizado, situação desatualizada no Mugô,
pedido inválido, cancelado e borda de fuso no dia 1º.
"""

import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "t" * 48)

from services import fbits_reconciliation
from services.fbits_client import FbitsClient
from services.fbits_connections import normalize_order
from services.fbits_reporting import FbitsPeriod

TOKEN = "fbits-reconcile-secret-token"
PERIOD = FbitsPeriod("2026-09-01", "2026-09-30")
STATUSES = [
    {"situacaoPedidoId": 1, "nome": "Pagamento aprovado"},
    {"situacaoPedidoId": 2, "nome": "Aguardando pagamento"},
    {"situacaoPedidoId": 3, "nome": "Pedido Cancelado"},
    {"situacaoPedidoId": 7, "nome": "Faturado"},
]
STATUS_NAMES = {str(s["situacaoPedidoId"]): s["nome"] for s in STATUSES}
OFFICIAL = {"indicadorReceita": 6700.0, "indicadorPedido": 62, "indicadorTicketMedio": 108.0645}


def api_order(pedido_id, *, status=1, data="2026-09-10T10:00:00", total=100.0, valido=True, paid=True):
    return {
        "pedidoId": pedido_id,
        "situacaoPedidoId": status,
        "data": data,
        "dataPagamento": data if paid else None,
        "dataUltimaAtualizacao": data,
        "valorTotalPedido": total,
        "valorSubTotalSemDescontos": total,
        "valorDesconto": 5.0,
        "valorFrete": 10.0,
        "valido": valido,
        "usuario": {"usuarioId": 900 + pedido_id, "nome": "Cliente Sigiloso", "email": "cliente@example.com", "cpf": "12345678900"},
        "pedidoEndereco": [{"endereco": "Rua Sigilosa"}],
        "itens": [],
    }


def september_orders():
    orders = [api_order(1000 + i, data=f"2026-09-{2 + i % 27:02d}T12:{i % 60:02d}:00") for i in range(55)]
    orders += [api_order(2000 + i, status=7, total=200.0) for i in range(5)]
    orders += [api_order(3000 + i, status=3, total=150.0, paid=False) for i in range(2)]
    orders.append(api_order(4000, valido=False, total=50.0))
    orders.append(api_order(5000, data="2026-09-01T01:00:00"))  # madrugada do dia 1º (borda de fuso)
    orders.append(api_order(5001, data="2026-09-30T23:30:00"))  # fim do dia 30
    return orders


MISSING = {"1001", "1002", "1003"}
STALE = "1004"


class FakeWake:
    def __init__(self, orders):
        self.orders = orders
        self.requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.method == "GET"
        path = request.url.path
        if path == "/situacoesPedido":
            return httpx.Response(200, json=STATUSES)
        if path == "/dashboard/faturamento":
            return httpx.Response(200, json=OFFICIAL)
        if path == "/pedidos":
            params = request.url.params
            start = datetime.strptime(params["dataInicial"], "%Y-%m-%d %H:%M:%S")
            end = datetime.strptime(params["dataFinal"], "%Y-%m-%d %H:%M:%S")
            field = "dataPagamento" if params["enumTipoFiltroData"] == "DataAprovacao" else "data"
            matching = [o for o in self.orders if o.get(field) and start <= datetime.fromisoformat(o[field]) <= end]
            size, page = int(params["quantidadeRegistros"]), int(params["pagina"])
            return httpx.Response(
                200, json=matching[(page - 1) * size: page * size], headers={"x-total-count": str(len(matching))},
            )
        return httpx.Response(404, json={})

    def client_factory(self, token):
        assert token == TOKEN
        return FbitsClient(token, transport=httpx.MockTransport(self.handler), sleep=AsyncMock())


def persisted_rows(client_id, orders):
    """Linhas como a sincronização real grava (normalize_order)."""
    rows = []
    for order in orders:
        if str(order["pedidoId"]) in MISSING:
            continue
        row = normalize_order(client_id, order, STATUS_NAMES)
        if row["order_id"] == STALE:
            row["status_id"] = "2"  # ficou "aguardando" no Mugô; na FBITS já foi pago
        rows.append(row)
    return rows


def in_dashboard_period(row):
    # Mesmo recorte de _period_filter: 01/09 00:00 a 01/10 00:00 em São Paulo (UTC-3).
    value = datetime.fromisoformat(row["order_date"])
    return datetime(2026, 9, 1, 3, tzinfo=timezone.utc) <= value < datetime(2026, 10, 1, 3, tzinfo=timezone.utc)


class Harness(unittest.IsolatedAsyncioTestCase):
    async def run_reconcile(self, client_id="curavino", orders=None):
        orders = september_orders() if orders is None else orders
        wake = FakeWake(orders)
        db = persisted_rows(client_id, orders) + persisted_rows("outro-tenant", orders)
        self.db_filters = []

        async def sb_select(table, *, select="*", filters=None, order=None, limit=None, offset=None):
            self.assertEqual(table, "fbits_orders")
            self.db_filters.append(dict(filters))
            cid = filters["client_id"].removeprefix("eq.")
            ids = set(filters["order_id"].removeprefix("in.(").removesuffix(")").split(","))
            return [dict(r) for r in db if r["client_id"] == cid and r["order_id"] in ids]

        async def read_period(*, client_id, period):
            return [dict(r) for r in db if r["client_id"] == client_id and in_dashboard_period(r)]

        connection = {
            "id": f"fbits-{client_id}", "client_id": client_id, "provider": "fbits", "status": "connected",
            "last_sync_at": "2026-09-20T12:00:00+00:00",
            "metadata": {"revenue_status_ids": ["1", "11", "14"], "revenue_rule_confirmed": False},
        }
        get_connection = AsyncMock(return_value={**connection, "_token": json.dumps({"token": TOKEN})})
        with (
            patch.object(fbits_reconciliation, "load_fbits_connection", AsyncMock(return_value=connection)) as load,
            patch.object(fbits_reconciliation, "get_connection", get_connection),
            patch.object(fbits_reconciliation, "sb_select", AsyncMock(side_effect=sb_select)),
            patch.object(fbits_reconciliation, "_read_persisted_orders", AsyncMock(side_effect=read_period)),
        ):
            report = await fbits_reconciliation.collect_fbits_reconciliation(
                client_id=client_id, period=PERIOD, client_factory=wake.client_factory,
            )
        self.load = load
        self.get_connection = get_connection
        return report, wake


class ReconciliationTests(Harness):
    async def test_official_indicators_come_from_dashboard_faturamento(self):
        report, wake = await self.run_reconcile()
        self.assertEqual(report["official"], {"receita": 6700.0, "pedidos": 62, "ticket_medio": 108.06, "error": None})
        call = next(r for r in wake.requests if r.url.path == "/dashboard/faturamento")
        self.assertEqual(call.url.params["dataInicial"], "2026-09-01")
        self.assertEqual(call.url.params["dataFinal"], "2026-09-30")

    async def test_pagination_reads_every_page_and_matches_x_total_count(self):
        report, wake = await self.run_reconcile()
        api = report["api"]
        self.assertEqual(api["x_total_count"], 65)
        self.assertEqual(api["pages"], 2)
        self.assertEqual(api["unique_orders"], 65)
        self.assertEqual(api["duplicates"], 0)
        pages = [r for r in wake.requests if r.url.path == "/pedidos" and r.url.params["enumTipoFiltroData"] == "DataPedido"]
        self.assertEqual([p.url.params["pagina"] for p in pages], ["1", "2"])

    async def test_full_local_days_are_queried_including_the_end_of_day_30(self):
        report, _wake = await self.run_reconcile()
        self.assertEqual(report["api"]["query"], {"dataInicial": "2026-09-01 00:00:00", "dataFinal": "2026-09-30 23:59:59"})
        ids = {row["order_id"] for row in report["orders"] if row["in_api_period"]}
        self.assertIn("5001", ids)  # 30/09 23:30

    async def test_status_breakdown_and_values_by_status(self):
        report, _wake = await self.run_reconcile()
        by_status = {row["status_id"]: row for row in report["by_status_api"]}
        self.assertEqual(by_status["1"]["pedidos"], 58)
        self.assertEqual(by_status["1"]["invalidos"], 1)
        self.assertEqual(by_status["7"], {
            "status_id": "7", "status": "Faturado", "in_revenue_rule": False, "pedidos": 5, "valor": 1000.0, "invalidos": 0,
        })
        self.assertEqual(by_status["3"]["valor"], 300.0)

    async def test_every_excluded_order_has_a_reason(self):
        report, _wake = await self.run_reconcile()
        rows = {row["order_id"]: row for row in report["orders"]}
        self.assertTrue(all(row["exclusion_reason"] for row in report["orders"] if not row["included_in_revenue"]))
        self.assertIn("não persistido", rows["1001"]["exclusion_reason"])
        self.assertEqual(rows[STALE]["exclusion_reason"],
                         "situação 2 (Aguardando pagamento) fora de revenue_status_ids; na API agora é 1")
        self.assertTrue(rows[STALE]["status_stale"])
        self.assertIn("situação 7 (Faturado)", rows["2000"]["exclusion_reason"])
        self.assertEqual(rows["4000"]["exclusion_reason"], "marcado inválido (valido=false)")
        self.assertIn("fora do período do dashboard", rows["5000"]["exclusion_reason"])
        self.assertTrue(rows["1010"]["included_in_orders"])

    async def test_mugo_gaps_are_counted(self):
        report, _wake = await self.run_reconcile()
        self.assertEqual(report["mugo"]["missing_in_mugo"], 3)
        self.assertEqual(report["mugo"]["status_stale"], 1)
        self.assertEqual(report["mugo"]["persisted_outside_period"], 1)
        self.assertEqual(report["mugo"]["only_in_mugo"], 0)

    async def test_candidate_rules_are_compared_to_the_official_numbers(self):
        report, _wake = await self.run_reconcile()
        c = report["candidates"]
        self.assertEqual(c["dashboard_atual_mugo"]["pedidos"], 52)
        self.assertFalse(c["dashboard_atual_mugo"]["bate_com_oficial"])
        self.assertEqual(c["regra_atual_com_dados_frescos"]["pedidos"], 57)
        self.assertFalse(c["todos_por_data_pedido"]["bate_com_oficial"])
        self.assertTrue(c["sem_cancelados_por_nome"]["bate_com_oficial"])
        self.assertEqual(c["sem_cancelados_por_nome"]["ticket_medio"], 108.06)

    async def test_status_subset_search_finds_the_rule_that_matches_exactly(self):
        report, _wake = await self.run_reconcile()
        matches = report["status_subsets"]["matches"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["status_ids"], ["1", "7"])
        self.assertEqual(matches[0]["status_names"], ["Pagamento aprovado", "Faturado"])
        self.assertTrue(matches[0]["only_valid"])
        self.assertEqual(matches[0]["value_field"], "total")

    async def test_timezone_evidence_is_reported(self):
        report, _wake = await self.run_reconcile()
        self.assertEqual(report["timezone"]["api_dates_without_offset"], 65)
        self.assertEqual(report["timezone"]["api_dates_with_offset"], 0)
        self.assertGreaterEqual(report["timezone"]["orders_within_3h_of_boundary"], 2)

    async def test_no_token_and_no_personal_data_in_the_report(self):
        report, _wake = await self.run_reconcile()
        text = json.dumps(report, ensure_ascii=False, default=str)
        for secret in (TOKEN, "cliente@example.com", "12345678900", "Cliente Sigiloso", "Rua Sigilosa"):
            self.assertNotIn(secret, text)

    async def test_tenant_isolation(self):
        await self.run_reconcile(client_id="curavino")
        self.load.assert_awaited_once_with("curavino")
        self.assertEqual(self.get_connection.await_args.args[0], "curavino")
        self.assertTrue(self.db_filters)
        self.assertTrue(all(f["client_id"] == "eq.curavino" for f in self.db_filters))

    async def test_only_get_requests_are_made(self):
        _report, wake = await self.run_reconcile()
        self.assertTrue(all(r.method == "GET" for r in wake.requests))

    def test_module_never_writes(self):
        source = Path(fbits_reconciliation.__file__).read_text(encoding="utf-8")
        for writer in ("sb_upsert", "sb_update", "sb_insert", "sb_delete", "upsert_connection"):
            self.assertNotIn(writer, source)


class PureBuildTests(unittest.TestCase):
    def test_official_unavailable_never_claims_a_match(self):
        api_rows = {"1": fbits_reconciliation.api_order_row(api_order(1))}
        report = fbits_reconciliation.build_reconciliation(
            period=PERIOD, official_payload=None, official_error="FBITS_REQUEST_REJECTED",
            by_order_date={"orders": api_rows}, by_approval_date=None,
            persisted_in_period=[], persisted_by_id={}, revenue_status_ids={"1"},
            status_names=STATUS_NAMES, connection_state={},
        )
        self.assertEqual(report["official"]["error"], "FBITS_REQUEST_REJECTED")
        self.assertFalse(any(c["bate_com_oficial"] for c in report["candidates"].values()))
        self.assertEqual(report["status_subsets"]["matches"], [])

    def test_discount_and_freight_are_kept_separate_from_total(self):
        row = fbits_reconciliation.api_order_row({**api_order(1, total=120.0), "valorFrete": None, "frete": {"valorFreteCliente": 12.5}})
        self.assertEqual((row["total"], row["freight"], row["discount"]), (120.0, 12.5, 5.0))
        self.assertEqual(row["values"]["total_sem_frete"], 107.5)


class CliTests(unittest.TestCase):
    # Sem importar run_jobs: o import carrega .env local (ensure_env_loaded).
    def test_cli_exposes_read_only_reconcile_command(self):
        source = (Path(SERVER_DIR) / "run_jobs.py").read_text(encoding="utf-8")
        self.assertIn('"fbits-reconcile"', source)
        self.assertIn("collect_fbits_reconciliation(", source)
        for flag in ('"--client-id", required=True', '"--start", required=True', '"--end", required=True', '"--orders"'):
            self.assertIn(flag, source)


if __name__ == "__main__":
    unittest.main()
