"""Prova de ponta a ponta da Inteligência numa empresa com todas as fontes.

Empresa fictícia (`loja-vinho`), nunca um tenant real: FBITS como comércio,
mais Meta, Google Ads, GA4 e Instagram. Verifica que o contexto chega
completo, que os KPIs oficiais da FBITS não são recalculados, que a falta de
uma fonte não derruba a leitura, e que a análise é persistida mesmo com a
migration 039 ainda não aplicada no remoto.
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import httpx

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import business_context, commerce_context, external_research, intelligence

CLIENT = "loja-vinho"
FBITS_TOKEN = "token-fbits-que-nunca-pode-ir-ao-modelo"
OFFICIAL_REVENUE = 34255.22
OFFICIAL_ORDERS = 73
OFFICIAL_TICKET = 469.25


def connection(provider: str, **overrides: Any) -> Dict[str, Any]:
    row = {
        "id": f"{provider}-1", "client_id": CLIENT, "provider": provider,
        "status": "connected", "disconnected_at": None, "updated_at": "2026-10-01T09:00:00Z",
        "_token": FBITS_TOKEN,
    }
    row.update(overrides)
    return row


ALL_CONNECTIONS = [connection(p) for p in ("fbits", "meta", "google_ads", "ga4", "instagram")]


def fbits_summary(kpi_source: str = "fbits_dashboard") -> Dict[str, Any]:
    return {
        "ok": True, "connected": True, "client_id": CLIENT,
        "period": {"start": "2026-09-01", "end": "2026-09-30"},
        "summary": {
            "receita_oficial": OFFICIAL_REVENUE, "pedidos": OFFICIAL_ORDERS,
            "ticket_medio": OFFICIAL_TICKET, "clientes": 40,
            "produtos_vendidos": 120, "descontos": 1430.88, "frete": 828.67,
        },
        "kpi_source": kpi_source,
        "comparison": {
            "receita_oficial": {"current": OFFICIAL_REVENUE, "previous": 30000.0, "change_percent": 14.2},
            "pedidos": {"current": OFFICIAL_ORDERS, "previous": 65, "change_percent": 12.3},
            "ticket_medio": {"current": OFFICIAL_TICKET, "previous": 461.54, "change_percent": 1.7},
        },
        "last_sync_at": "2026-10-02T17:00:00Z",
        "status_distribution": [{"status": "Pago", "pedidos": 70, "valor": OFFICIAL_REVENUE}],
    }


def executive_context(*, meta=True, google=True, ga4=True, instagram=True) -> Dict[str, Any]:
    """Como o read model entrega: comércio da FBITS NÃO passa por aqui."""
    def source(available: bool, last: str) -> Dict[str, Any]:
        return {"connected": True, "data_available": available, "last_success_at": last, "data_max_available": "2026-09-30"}

    return {
        # Loja FBITS: o read model não tem receita Shopify, e isso é o certo.
        "shopify": {"connected": False, "data_available": False, "net_revenue": 0, "orders": 0,
                    "average_order_value": None, "new_customers": 0, "returning_customers": None,
                    "last_success_at": None, "data_max_available": None},
        "meta": {**source(meta, "2026-10-02T16:00:00Z"), "spend": 8200.0 if meta else None,
                 "attributed_revenue": 21000.0 if meta else None, "roas_real": None, "attributed_roas": 2.56 if meta else None},
        "google_ads": {**source(google, "2026-10-02T16:10:00Z"), "spend": 3100.0 if google else None,
                       "attributed_revenue": 7400.0 if google else None, "roas_real": None, "attributed_roas": 2.38 if google else None},
        "ga4": {**source(ga4, "2026-10-02T16:07:00Z"), "sessions": 41200 if ga4 else None, "users": 28700 if ga4 else None},
        "instagram": source(instagram, "2026-10-02T15:40:00Z"),
        "total_paid_media": {
            "paid_media_spend": (8200.0 if meta else 0) + (3100.0 if google else 0),
            "included_paid_sources": [p for p, on in (("meta", meta), ("google_ads", google)) if on],
            "blended_roas": None,
        },
        "previous_period": {
            "shopify": {"net_revenue": 0, "orders": 0},
            "meta": {"spend": 7000.0}, "google_ads": {"spend": 2800.0},
            "ga4": {"sessions": 38000}, "instagram": {},
            "total_paid_media": {"blended_roas": None},
        },
        "deltas": {
            "shopify_net_revenue": {"absolute": 0, "percent": None},
            "shopify_orders": {"absolute": 0, "percent": None},
            "meta_spend": {"absolute": 1200.0, "percent": 17.1},
            "blended_roas": {"absolute": None, "percent": None},
        },
        "historical_context": {
            "coverage_start": "2026-01-01", "coverage_end": "2026-09-30",
            "monthly_summary": [], "source_coverage": {},
        },
    }


class SnapshotHarness(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.business_row: List[Dict[str, Any]] = []
        external_research.set_provider(None)
        self.addCleanup(external_research.set_provider, None)

    async def snapshot(self, *, summary=None, context=None, connections=None, business_fails=False):
        from services import fbits_reporting

        summary = fbits_summary() if summary is None else summary
        context = executive_context() if context is None else context
        connections = ALL_CONNECTIONS if connections is None else connections
        build = (
            AsyncMock(side_effect=summary) if isinstance(summary, BaseException)
            else AsyncMock(return_value=summary)
        )
        business_select = (
            AsyncMock(side_effect=httpx.HTTPStatusError("404", request=None, response=None))
            if business_fails else AsyncMock(return_value=self.business_row)
        )
        output = io.StringIO()
        with (
            patch.object(intelligence, "_read_model_executive_context", AsyncMock(return_value=context)),
            patch.object(intelligence, "sb_select", AsyncMock(return_value=[])),
            patch.object(intelligence, "list_generic_connections", AsyncMock(return_value=[])),
            patch.object(commerce_context, "sb_select", AsyncMock(return_value=connections)),
            patch.object(fbits_reporting, "build_fbits_summary", build),
            patch.object(business_context, "sb_select", business_select),
            redirect_stdout(output),
        ):
            snapshot = await intelligence.calculate_intelligence_snapshot(
                client_id=CLIENT, start="2026-09-01", end="2026-09-30",
            )
        self.log = output.getvalue()
        return snapshot

    def metric(self, snapshot: Dict[str, Any], metric_id: str) -> Dict[str, Any]:
        return next(item for item in snapshot["metrics"] if item["id"] == metric_id)

    def source(self, snapshot: Dict[str, Any], source_id: str) -> Dict[str, Any]:
        return next(item for item in snapshot["sources"] if item["id"] == source_id)


class CompleteCompanyTests(SnapshotHarness):
    async def test_commerce_provider_is_fbits_resolved_by_connection(self):
        snapshot = await self.snapshot()
        commerce = snapshot["commerce_context"]
        self.assertEqual(commerce["provider"], "fbits")
        self.assertEqual(commerce["provider_label"], "FBITS/Wake")
        self.assertTrue(commerce["official_kpis"])
        self.assertEqual(self.source(snapshot, "commerce")["provider"], "fbits")

    async def test_official_revenue_orders_and_ticket_reach_the_context(self):
        snapshot = await self.snapshot()
        self.assertEqual(self.metric(snapshot, "revenue")["value"], OFFICIAL_REVENUE)
        self.assertEqual(self.metric(snapshot, "orders")["value"], OFFICIAL_ORDERS)
        self.assertEqual(self.metric(snapshot, "average_ticket")["value"], OFFICIAL_TICKET)
        for metric_id in ("revenue", "orders", "average_ticket"):
            self.assertEqual(self.metric(snapshot, metric_id)["status"], "confirmed")

    async def test_official_kpis_are_not_recalculated(self):
        snapshot = await self.snapshot()
        revenue = self.metric(snapshot, "revenue")["value"]
        orders = self.metric(snapshot, "orders")["value"]
        ticket = self.metric(snapshot, "average_ticket")["value"]
        # revenue/orders daria 469,25342...: o ticket exibido é o da FBITS.
        self.assertNotEqual(ticket, revenue / orders)
        self.assertEqual(ticket, OFFICIAL_TICKET)
        self.assertEqual(self.metric(snapshot, "revenue")["kpi_source"], "fbits_dashboard")

    async def test_every_other_source_reaches_the_context(self):
        snapshot = await self.snapshot()
        self.assertEqual(self.metric(snapshot, "meta_investment")["value"], 8200.0)
        self.assertEqual(self.metric(snapshot, "google_ads_investment")["value"], 3100.0)
        self.assertEqual(self.metric(snapshot, "investment")["value"], 11300.0)
        self.assertEqual(self.metric(snapshot, "sessions")["value"], 41200)
        for source_id in ("commerce", "meta", "google_ads", "ga4", "instagram"):
            self.assertIn(self.source(snapshot, source_id)["status"], {"available", "partial"})

    async def test_fbits_commerce_does_not_borrow_shopify_numbers(self):
        snapshot = await self.snapshot()
        # O read model não tem receita Shopify desta loja; a receita vem da FBITS.
        self.assertEqual(snapshot["executive_context"]["shopify"]["net_revenue"], 0)
        self.assertEqual(self.metric(snapshot, "revenue")["value"], OFFICIAL_REVENUE)
        self.assertEqual(self.metric(snapshot, "revenue")["source"], "fbits")

    async def test_log_names_the_stage_and_the_provider(self):
        await self.snapshot()
        self.assertIn("stage=context status=ok", self.log)
        self.assertIn("commerce_provider=fbits", self.log)
        self.assertIn("elapsed_ms=", self.log)


class DegradationTests(SnapshotHarness):
    async def test_one_missing_source_does_not_break_the_rest(self):
        snapshot = await self.snapshot(context=executive_context(google=False, instagram=False))
        self.assertEqual(self.metric(snapshot, "revenue")["value"], OFFICIAL_REVENUE)
        self.assertEqual(self.metric(snapshot, "meta_investment")["value"], 8200.0)
        self.assertEqual(self.metric(snapshot, "google_ads_investment")["status"], "unavailable")
        self.assertEqual(self.source(snapshot, "google_ads")["status"], "connected_no_data")

    async def test_fbits_unavailable_keeps_the_other_sources(self):
        snapshot = await self.snapshot(summary=RuntimeError("FBITS fora do ar"))
        self.assertEqual(snapshot["commerce_context"]["status"], "unavailable")
        self.assertEqual(self.metric(snapshot, "revenue")["status"], "unavailable")
        # Indisponível nunca é zero.
        self.assertIsNone(self.metric(snapshot, "revenue")["value"])
        self.assertEqual(self.metric(snapshot, "sessions")["value"], 41200)

    async def test_fallback_kpis_are_reported_as_such(self):
        snapshot = await self.snapshot(summary=fbits_summary("fbits_orders_fallback"))
        self.assertFalse(snapshot["commerce_context"]["official_kpis"])
        self.assertEqual(snapshot["commerce_context"]["kpi_source"], "fbits_orders_fallback")

    async def test_missing_business_context_table_does_not_break(self):
        snapshot = await self.snapshot(business_fails=True)
        self.assertFalse(snapshot["business_context"]["available"])
        self.assertEqual(self.metric(snapshot, "revenue")["value"], OFFICIAL_REVENUE)

    async def test_existing_business_context_enters_the_snapshot(self):
        self.business_row = [{
            "client_id": CLIENT, "segment": "Vinhos naturais",
            "audience": "Consumidor final recorrente", "goals": "Dobrar recompra",
            "updated_at": "2026-10-01T10:00:00Z",
        }]
        snapshot = await self.snapshot()
        self.assertTrue(snapshot["business_context"]["available"])
        self.assertEqual(snapshot["business_context"]["context"]["segment"], "Vinhos naturais")

    async def test_no_external_provider_reports_not_configured(self):
        snapshot = await self.snapshot()
        self.assertEqual(snapshot["external_research"]["status"], "not_configured")
        self.assertEqual(snapshot["external_research"]["market_signals"], [])

    async def test_no_credential_reaches_the_snapshot(self):
        self.business_row = [{"client_id": CLIENT, "segment": "Vinhos"}]
        snapshot = await self.snapshot()
        blob = str(snapshot)
        for secret in (FBITS_TOKEN, "_token", "encrypted", "service_role"):
            self.assertNotIn(secret, blob)


class GenerationTests(SnapshotHarness):
    async def generate(self, *, insert_fails_on_fingerprint=False, provider=None):
        snapshot = await self.snapshot()
        self.inserted: List[Dict[str, Any]] = []

        async def sb_insert(table, row, returning="representation"):
            self.inserted.append({"table": table, "row": dict(row)})
            if insert_fails_on_fingerprint and "context_fingerprint" in row:
                # PostgREST sem a migration 039 aplicada.
                response = httpx.Response(
                    400, json={"code": "PGRST204", "message": "Could not find the 'context_fingerprint' column of 'ai_analyses' in the schema cache"},
                    request=httpx.Request("POST", "https://supabase.local/ai_analyses"),
                )
                raise httpx.HTTPStatusError("400", request=response.request, response=response)
            return {"id": "an-1", **row}

        analysis = {
            "executive": {"overall": "Leitura.", "main_change": "m", "opportunity": "o", "attention": "a", "priority_action": "p"},
            "insights": [], "actions": [],
        }
        output = io.StringIO()
        with (
            patch.object(intelligence, "calculate_intelligence_snapshot", AsyncMock(return_value=snapshot)),
            patch.object(intelligence, "provider_configured", lambda: True),
            patch.object(intelligence, "sb_insert", AsyncMock(side_effect=sb_insert)),
            patch.object(intelligence, "sb_select", AsyncMock(return_value=[])),
            patch.object(
                intelligence, "_call_provider",
                AsyncMock(side_effect=provider) if isinstance(provider, BaseException)
                else AsyncMock(return_value=analysis),
            ),
            patch.object(intelligence, "_validate_analysis_grounding", lambda *_args: None),
            patch.object(intelligence, "_sanitize_analysis", lambda value, _snapshot: value),
            redirect_stdout(output),
        ):
            try:
                result, error = await intelligence.generate_analysis(
                    client_id=CLIENT, user_id="user-1", start="2026-09-01", end="2026-09-30",
                ), None
            except Exception as exc:  # noqa: BLE001
                result, error = None, exc
        self.generate_log = output.getvalue()
        return result, error

    async def test_valid_analysis_is_persisted_with_the_real_context(self):
        result, error = await self.generate()
        self.assertIsNone(error)
        self.assertEqual(result["status"], "completed")
        row = self.inserted[-1]["row"]
        self.assertEqual(row["client_id"], CLIENT)
        self.assertEqual(row["status"], "completed")
        self.assertTrue(row["context_fingerprint"])

    async def test_analysis_is_saved_even_before_migration_039_is_applied(self):
        result, error = await self.generate(insert_fails_on_fingerprint=True)
        self.assertIsNone(error)
        self.assertEqual(result["status"], "completed")
        # Primeira tentativa com a coluna, segunda sem ela.
        self.assertIn("context_fingerprint", self.inserted[0]["row"])
        self.assertNotIn("context_fingerprint", self.inserted[-1]["row"])
        self.assertIn("schema_pending", self.generate_log)
        self.assertIn("20261003_000039", self.generate_log)

    async def test_model_failure_is_recorded_with_the_stage(self):
        _result, error = await self.generate(provider=RuntimeError("modelo fora"))
        self.assertIsInstance(error, RuntimeError)
        self.assertIn(intelligence.STAGE_MODEL, self.generate_log)
        self.assertEqual(self.inserted[-1]["row"]["status"], "failed")

    async def test_no_credential_is_sent_to_the_model(self):
        call = AsyncMock(return_value={
            "executive": {"overall": "x", "main_change": "x", "opportunity": "x", "attention": "x", "priority_action": "x"},
            "insights": [], "actions": [],
        })
        snapshot = await self.snapshot()
        with (
            patch.object(intelligence, "calculate_intelligence_snapshot", AsyncMock(return_value=snapshot)),
            patch.object(intelligence, "provider_configured", lambda: True),
            patch.object(intelligence, "sb_insert", AsyncMock(return_value={"id": "an-1"})),
            patch.object(intelligence, "sb_select", AsyncMock(return_value=[])),
            patch.object(intelligence, "_call_provider", call),
            patch.object(intelligence, "_validate_analysis_grounding", lambda *_args: None),
            patch.object(intelligence, "_sanitize_analysis", lambda value, _snapshot: value),
            redirect_stdout(io.StringIO()),
        ):
            await intelligence.generate_analysis(
                client_id=CLIENT, user_id="user-1", start="2026-09-01", end="2026-09-30",
            )
        payload = str(call.await_args.kwargs["payload"])
        for secret in (FBITS_TOKEN, "_token", "encrypted", "service_role", "client_secret"):
            self.assertNotIn(secret, payload)
        self.assertIn("fbits", payload)

    def test_company_name_is_never_the_source_of_the_provider(self):
        import ast

        source = (SERVER_DIR / "services" / "commerce_context.py").read_text(encoding="utf-8")
        # Remove comentários e docstrings: a doc explica justamente que o nome
        # da empresa NÃO é regra, então só o código executável é varrido.
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if (node.body and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and isinstance(node.body[0].value.value, str)):
                    node.body.pop(0)
        code = ast.unparse(tree).lower()
        for name in ("curavino", "roove", "amalie"):
            self.assertNotIn(name, code)
        # E o provider sai mesmo do campo da conexão.
        self.assertIn("chosen.get('provider')", code)


if __name__ == "__main__":
    unittest.main()
