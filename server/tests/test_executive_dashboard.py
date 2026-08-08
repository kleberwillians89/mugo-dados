from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import executive_dashboard as ed  # noqa: E402
from services import shopify_reporting  # noqa: E402


def _order(order_id: str, price: str, *, created: str, cancelled: str | None = None) -> dict:
    return {
        "id": order_id,
        "shopify_order_id": order_id,
        "shop_domain": "amalie.myshopify.com",
        "order_number": order_id,
        "name": f"#{order_id}",
        "email": "cliente@amalie.com",
        "customer_id": "cust-1",
        "currency": "BRL",
        "financial_status": "paid",
        "fulfillment_status": "fulfilled",
        "total_price": price,
        "cancelled_at": cancelled,
        "cancel_reason": None,
        "created_at_shopify": created,
        "updated_at_shopify": created,
    }


class ShopifyRevenueTemporalConsistencyTests(unittest.IsolatedAsyncioTestCase):
    """Corresponde ao caso do usuário: pedido de julho reembolsado em agosto
    não pode distorcer silenciosamente a receita líquida de agosto."""

    async def test_refund_of_out_of_period_order_never_distorts_in_period_net_revenue(self):
        period = shopify_reporting.resolve_shopify_report_period(start="2026-08-01", end="2026-08-31")
        august_order = _order("1001", "200.00", created="2026-08-05T00:00:00Z")

        async def fake_sb_select(table, *, select=None, filters=None, order=None, limit=None):
            filters = filters or {}
            if table == "shopify_orders":
                return [august_order]
            if table == "shopify_refunds":
                order_filter = str(filters.get("shopify_order_id") or "")
                if order_filter:
                    # Consulta ligada aos pedidos DO período (agosto) — o
                    # pedido de julho (0500) não está nesse conjunto.
                    self.assertNotIn("0500", order_filter)
                    return []
                if "and" in filters:
                    # Consulta separada: reembolso cuja DATA cai em agosto,
                    # mas cujo pedido original (0500) é de julho.
                    return [{
                        "id": "r-1", "shopify_refund_id": "9001", "shopify_order_id": "0500",
                        "total_refunded": "50.00", "created_at_shopify": "2026-08-10T00:00:00Z",
                    }]
                return []
            if table == "shopify_order_items":
                return []
            if table == "shopify_customers":
                return []
            return []

        with (
            patch.object(shopify_reporting, "sb_select", fake_sb_select),
            patch.object(shopify_reporting, "list_recent_shopify_webhooks", AsyncMock(return_value=[])),
        ):
            report = await shopify_reporting.build_shopify_report(
                client_id="amalie", shop_domain="amalie.myshopify.com", period=period,
            )

        summary = report["summary"]
        self.assertEqual(summary["net_revenue"], 200.0)
        self.assertEqual(summary["refunded_amount"], 0.0)
        # A métrica separada continua visível, só não entra no net_revenue.
        self.assertEqual(summary["refunds_occurred_in_period_amount"], 50.0)

    async def test_cancelled_order_never_enters_report_net_revenue(self):
        period = shopify_reporting.resolve_shopify_report_period(start="2026-08-01", end="2026-08-31")
        orders = [
            _order("1001", "200.00", created="2026-08-05T00:00:00Z"),
            _order("1002", "80.00", created="2026-08-06T00:00:00Z", cancelled="2026-08-06T01:00:00Z"),
        ]

        async def fake_sb_select(table, *, select=None, filters=None, order=None, limit=None):
            if table == "shopify_orders":
                return orders
            return []

        with (
            patch.object(shopify_reporting, "sb_select", fake_sb_select),
            patch.object(shopify_reporting, "list_recent_shopify_webhooks", AsyncMock(return_value=[])),
        ):
            report = await shopify_reporting.build_shopify_report(
                client_id="amalie", shop_domain="amalie.myshopify.com", period=period,
            )

        self.assertEqual(report["summary"]["net_revenue"], 200.0)
        self.assertEqual(report["summary"]["cancelled_orders"], 1)


class BlendedRoasPeriodConsistencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_blended_roas_uses_same_period_for_shopify_and_meta(self):
        seen_windows: list[tuple[str, str, str]] = []

        async def fake_shopify_section(*, client_id, connection_id, since, until):
            seen_windows.append(("shopify", since, until))
            return {"connected": True, "net_revenue": 1000.0, "gross_revenue": 1000.0, "orders": 10,
                    "paid_orders": 10, "cancelled_orders": 0, "refunds": 0, "refunded_amount": 0.0,
                    "refunds_occurred_in_period_count": 0, "refunds_occurred_in_period_amount": 0.0,
                    "average_order_value": 100.0, "new_customers": 5, "returning_customers": 5}

        async def fake_meta_section(*, client_id, connection_id, since, until):
            seen_windows.append(("meta", since, until))
            return {"connected": True, "spend": 500.0, "attributed_revenue": 2000.0, "roas": 4.0}

        with (
            patch.object(ed, "_build_shopify_section", fake_shopify_section),
            patch.object(ed, "_build_meta_section", fake_meta_section),
            patch.object(ed, "_build_ga4_section", AsyncMock(return_value=None)),
        ):
            result = await ed.get_executive_summary(
                "amalie", start="2026-08-01", end="2026-08-31", include_previous_period=False,
            )

        shopify_window = next(w for w in seen_windows if w[0] == "shopify")
        meta_window = next(w for w in seen_windows if w[0] == "meta")
        self.assertEqual(shopify_window[1:], meta_window[1:])
        self.assertAlmostEqual(result["total_paid_media"]["blended_roas"], 2.0)  # 1000 / 500

    async def test_included_paid_sources_present_in_payload(self):
        with (
            patch.object(ed, "_build_shopify_section", AsyncMock(return_value=None)),
            patch.object(ed, "_build_meta_section", AsyncMock(return_value={
                "connected": True, "spend": 300.0, "attributed_revenue": 900.0, "roas": 3.0,
            })),
            patch.object(ed, "_build_ga4_section", AsyncMock(return_value=None)),
        ):
            result = await ed.get_executive_summary("amalie", days=7, include_previous_period=False)

        self.assertEqual(result["total_paid_media"]["included_paid_sources"], ["meta"])

    async def test_google_ads_absence_is_never_treated_as_connected_with_zero_spend(self):
        section = ed._build_google_ads_section()
        self.assertFalse(section["connected"])
        self.assertIsNone(section["spend"])
        self.assertNotIn("google_ads", ed._build_total_paid_media(
            meta={"connected": True, "spend": 100.0},
            google_ads=section,
            shopify=None,
        )["included_paid_sources"])


class IntelligenceConsumesCalculatedMetricsTests(unittest.IsolatedAsyncioTestCase):
    async def test_intelligence_roas_and_revenue_metrics_come_from_backend_executive_summary(self):
        from services import intelligence

        fake_executive = {
            "shopify": {"net_revenue": 1000.0, "gross_revenue": 1000.0, "orders": 10, "connected": True},
            "previous_period": {"shopify": {"net_revenue": 800.0}},
            "deltas": {
                "shopify_net_revenue": {"absolute": 200.0, "percent": 25.0},
                "blended_roas": {"absolute": None, "percent": None},
            },
            "total_paid_media": {"paid_media_spend": 500.0, "included_paid_sources": ["meta"], "blended_roas": 2.0},
        }

        with (
            patch.object(intelligence, "get_executive_summary", AsyncMock(return_value=fake_executive)),
            patch.object(intelligence, "sb_select", AsyncMock(return_value=[])),
            patch.object(intelligence, "list_generic_connections", AsyncMock(return_value=[])),
        ):
            snapshot = await intelligence.calculate_intelligence_snapshot(
                client_id="amalie", start="2026-08-01", end="2026-08-31",
            )

        metrics_by_id = {metric["id"]: metric for metric in snapshot["metrics"]}
        # O valor exibido é exatamente o já calculado no backend (net
        # revenue e blended ROAS via compute_mer) — a IA nunca recebe dados
        # brutos para recalcular isso sozinha.
        self.assertEqual(metrics_by_id["revenue"]["value"], 1000.0)
        self.assertEqual(metrics_by_id["roas"]["value"], 2.0)
        self.assertEqual(metrics_by_id["roas"]["included_paid_sources"], ["meta"])
        self.assertEqual(metrics_by_id["revenue"]["variation_percent"], 25.0)
        self.assertEqual(snapshot["executive_context"], fake_executive)

    async def test_intelligence_degrades_gracefully_without_shopify_connected(self):
        from services import intelligence

        with (
            patch.object(intelligence, "get_executive_summary", AsyncMock(return_value=None)),
            patch.object(intelligence, "sb_select", AsyncMock(return_value=[])),
            patch.object(intelligence, "list_generic_connections", AsyncMock(return_value=[])),
        ):
            snapshot = await intelligence.calculate_intelligence_snapshot(
                client_id="amalie", start="2026-08-01", end="2026-08-31",
            )

        # Sem Shopify conectado, a tela não pode quebrar: metrics continua
        # uma lista válida, com revenue/roas caindo para os campos legados
        # (None quando não há base confiável) em vez de lançar exceção.
        metrics_by_id = {metric["id"]: metric for metric in snapshot["metrics"]}
        self.assertIn("revenue", metrics_by_id)
        self.assertIn("roas", metrics_by_id)
        self.assertIsNone(snapshot["executive_context"])


if __name__ == "__main__":
    unittest.main()
