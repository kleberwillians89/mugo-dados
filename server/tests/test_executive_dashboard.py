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

    async def test_today_coverage_uses_persisted_coverage_not_last_sync_timestamp(self):
        context = type("Context", (), {"shop_domain": "amalie.myshopify.com", "connection_id": "conn-1"})()
        report = {
            "summary": {"orders": 0, "average_ticket": 0, "customers": 0},
            "coverage": {"data_max_available": "2026-08-10"},
            "daily_commercial": [],
        }
        with patch.object(ed, "build_shopify_report", AsyncMock(return_value=report)):
            section = await ed._build_shopify_section(
                client_id="amalie",
                connection_id="conn-1",
                since="2026-08-10",
                until="2026-08-10",
                context=context,
                connection_row={"last_sync_at": "2026-08-09T12:00:00Z", "status": "connected"},
            )

        self.assertEqual(section["data_max_available"], "2026-08-10")
        self.assertEqual(section["orders"], 0)
        self.assertEqual(section["average_order_value"], 0.0)

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

    async def test_shopify_summary_daily_invariants_and_global_freshness(self):
        period = shopify_reporting.resolve_shopify_report_period(start="2026-08-01", end="2026-08-10")
        orders = [
            _order("1001", "200.00", created="2026-08-05T12:00:00Z"),
            {**_order("1002", "400.00", created="2026-08-06T12:00:00Z"), "customer_id": "cust-2", "email": "b@amalie.com"},
        ]

        async def fake_select(table, *, select=None, filters=None, order=None, limit=None):
            if table == "dashboard_source_snapshots":
                return [{"data_max_available": "2026-08-20"}]
            if table == "shopify_orders":
                return orders
            if table == "shopify_customers":
                return [{"shopify_customer_id": "cust-1", "orders_count": 2}, {"shopify_customer_id": "cust-2", "orders_count": 1}]
            return []

        with (
            patch.object(shopify_reporting, "sb_select", fake_select),
            patch.object(shopify_reporting, "list_recent_shopify_webhooks", AsyncMock(return_value=[])),
        ):
            report = await shopify_reporting.build_shopify_report(
                client_id="amalie", shop_domain="amalie.myshopify.com", period=period,
            )

        summary = report["summary"]
        self.assertEqual(sum(day["revenue"] for day in report["trends"]["daily"]), summary["net_revenue"])
        self.assertEqual(sum(day["orders"] for day in report["trends"]["daily"]), summary["orders"])
        self.assertEqual(summary["average_ticket"], summary["revenue_total"] / summary["orders"])
        self.assertEqual(summary["customers"], 2)
        self.assertEqual(summary["returning_customers"], 1)
        self.assertEqual(report["coverage"]["data_max_in_period"], "2026-08-06")
        self.assertEqual(report["coverage"]["data_max_available"], "2026-08-20")

    async def test_pending_order_is_visible_but_excluded_from_commercial_totals(self):
        period = shopify_reporting.resolve_shopify_report_period(start="2026-08-01", end="2026-08-10")
        paid = _order("1001", "200.00", created="2026-08-05T12:00:00Z")
        pending = {**_order("1002", "900.00", created="2026-08-06T12:00:00Z"), "financial_status": "pending"}

        async def fake_select(table, *, select=None, filters=None, order=None, limit=None):
            if table == "shopify_orders" and select == "created_at_shopify":
                return [{"created_at_shopify": pending["created_at_shopify"]}]
            if table == "shopify_orders":
                return [paid, pending]
            return []

        with (
            patch.object(shopify_reporting, "sb_select", fake_select),
            patch.object(shopify_reporting, "list_recent_shopify_webhooks", AsyncMock(return_value=[])),
        ):
            report = await shopify_reporting.build_shopify_report(
                client_id="amalie", shop_domain="amalie.myshopify.com", period=period,
            )

        self.assertEqual(report["summary"]["orders"], 1)
        self.assertEqual(report["summary"]["net_revenue"], 200.0)
        self.assertEqual(len(report["recent_orders"]), 2)
        self.assertIn("pending", [order["financial_status"] for order in report["recent_orders"]])


class ShopifyCustomerKpiConsistencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_fifteen_orders_keep_report_and_customer_section_at_fourteen_customers(self):
        period = shopify_reporting.resolve_shopify_report_period(start="2026-08-01", end="2026-08-10")
        period_orders = [
            {
                **_order(str(index), "100.00", created=f"2026-08-{(index % 10) + 1:02d}T12:00:00Z"),
                "customer_id": str(min(index, 14)),
                "email": "",
            }
            for index in range(1, 16)
        ]

        async def fake_select(table, *, select=None, filters=None, order=None, limit=None):
            filters = filters or {}
            if table == "shopify_orders" and select == "created_at_shopify":
                return [{"created_at_shopify": "2026-08-10T12:00:00Z"}]
            if table == "shopify_orders":
                return period_orders
            if table == "shopify_customers":
                return [{"shopify_customer_id": str(index), "orders_count": 1} for index in range(1, 15)]
            return []

        with (
            patch.object(shopify_reporting, "sb_select", fake_select),
            patch.object(shopify_reporting, "list_recent_shopify_webhooks", AsyncMock(return_value=[])),
        ):
            report = await shopify_reporting.build_shopify_report(
                client_id="amalie", shop_domain="amalie.myshopify.com", period=period,
            )
            customers = await shopify_reporting.build_shopify_customers_report(
                client_id="amalie", shop_domain="amalie.myshopify.com", period=period,
            )

        self.assertEqual(report["summary"]["orders"], 15)
        self.assertEqual(report["summary"]["customers"], 14)
        self.assertEqual(customers["summary"]["total_customers"], 14)

    async def test_customer_kpis_only_use_recognized_orders(self):
        period = shopify_reporting.resolve_shopify_report_period(start="2026-08-01", end="2026-08-10")
        previous_a = {**_order("a-previous", "50.00", created="2026-07-20T12:00:00Z"), "customer_id": "A", "email": ""}
        period_orders = [
            {**_order("a-current", "100.00", created="2026-08-02T12:00:00Z"), "customer_id": "A", "email": ""},
            {**_order("b-1", "140.00", created="2026-08-03T12:00:00Z"), "customer_id": "B", "email": ""},
            {**_order("b-2", "160.00", created="2026-08-04T12:00:00Z"), "customer_id": "B", "email": ""},
            {**_order("c-pending", "999.00", created="2026-08-05T12:00:00Z"), "customer_id": "C", "email": "", "financial_status": "pending"},
        ]

        async def fake_select(table, *, select=None, filters=None, order=None, limit=None):
            filters = filters or {}
            if table == "shopify_customers":
                return [
                    {"shopify_customer_id": "A", "first_name": "Cliente", "last_name": "A"},
                    {"shopify_customer_id": "B", "first_name": "Cliente", "last_name": "B"},
                ]
            if table == "shopify_refunds":
                return []
            if table == "shopify_orders" and "and" in filters:
                return period_orders
            if table == "shopify_orders" and "customer_id" in filters:
                return [previous_a, *period_orders]
            return []

        with patch.object(shopify_reporting, "sb_select", fake_select):
            report = await shopify_reporting.build_shopify_customers_report(
                client_id="amalie", shop_domain="amalie.myshopify.com", period=period,
            )

        self.assertEqual(report["summary"]["total_customers"], 2)
        self.assertEqual(report["summary"]["recurring_customers"], 1)
        self.assertEqual(report["summary"]["multi_order_customers"], 1)
        self.assertEqual(report["summary"]["top_customer"]["name"], "Cliente B")
        self.assertEqual(report["summary"]["top_customer"]["total_spent"], 300.0)
        self.assertNotIn("C", [row["shopify_customer_id"] for row in report["items"]])


class BlendedRoasPeriodConsistencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_blended_roas_uses_same_period_for_shopify_and_meta(self):
        seen_windows: list[tuple[str, str, str]] = []

        async def fake_shopify_section(*, client_id, connection_id, since, until, **_kwargs):
            seen_windows.append(("shopify", since, until))
            return {"connected": True, "net_revenue": 1000.0, "gross_revenue": 1000.0, "orders": 10,
                    "paid_orders": 10, "cancelled_orders": 0, "refunds": 0, "refunded_amount": 0.0,
                    "refunds_occurred_in_period_count": 0, "refunds_occurred_in_period_amount": 0.0,
                    "average_order_value": 100.0, "new_customers": 5, "returning_customers": 5}

        async def fake_meta_section(*, client_id, connection_id, since, until, **_kwargs):
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
        section = await ed._build_google_ads_section(
            client_id="amalie", since="2026-08-01", until="2026-08-10", context=ed._UNAVAILABLE,
        )
        self.assertFalse(section["connected"])
        self.assertIsNone(section["spend"])
        self.assertNotIn("google_ads", ed._build_total_paid_media(
            meta={"connected": True, "spend": 100.0},
            google_ads=section,
            shopify=None,
        )["included_paid_sources"])

    async def test_connected_meta_without_period_coverage_is_missing_not_zero(self):
        with patch.object(ed, "get_paid_dashboard", AsyncMock(return_value={
            "connection_id": "paid-1", "has_data": False, "totals": {"spend": 0, "revenue": 0},
            "daily": [], "connection_status": {"connection_state": "connected", "sync_state": "stale"},
        })):
            section = await ed._build_meta_section(
                client_id="amalie", connection_id=None, since="2026-08-10", until="2026-08-10",
            )

        self.assertTrue(section["connected"])
        self.assertFalse(section["data_available"])
        self.assertIsNone(section["spend"])
        total = ed._build_total_paid_media(
            meta=section, google_ads=await ed._build_google_ads_section(
                client_id="amalie", since="2026-08-01", until="2026-08-10", context=ed._UNAVAILABLE,
            ), shopify={"net_revenue": 100.0},
        )
        self.assertIsNone(total["paid_media_spend"])
        self.assertEqual(total["included_paid_sources"], [])


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
            patch.object(intelligence, "_read_model_executive_context", AsyncMock(return_value=fake_executive)),
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
            patch.object(intelligence, "_read_model_executive_context", AsyncMock(return_value=None)),
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

    async def test_intelligence_keeps_four_provider_freshness_and_null_values(self):
        from services import intelligence

        fake_executive = {
            "period": {"start": "2026-08-10", "end": "2026-08-10", "days": 1},
            "shopify": {"connected": True, "net_revenue": None, "data_max_available": "2026-08-09"},
            "meta": {"connected": True, "spend": None, "data_max_available": "2026-08-09", "stale": True},
            "ga4": {"connected": True, "sessions": None, "data_max_available": "2026-08-09"},
            "instagram": {"connected": True, "data_max_available": "2026-08-09"},
            "total_paid_media": {"paid_media_spend": None, "included_paid_sources": [], "blended_roas": None},
            "previous_period": None,
            "deltas": None,
        }
        with (
            patch.object(intelligence, "_read_model_executive_context", AsyncMock(return_value=fake_executive)),
            patch.object(intelligence, "sb_select", AsyncMock(return_value=[])),
            patch.object(intelligence, "list_generic_connections", AsyncMock(return_value=[])),
        ):
            snapshot = await intelligence.calculate_intelligence_snapshot(
                client_id="amalie", start="2026-08-10", end="2026-08-10",
            )

        self.assertEqual(snapshot["executive_context"], fake_executive)
        self.assertIsNone(next(metric for metric in snapshot["metrics"] if metric["id"] == "revenue")["value"])
        self.assertIsNone(next(metric for metric in snapshot["metrics"] if metric["id"] == "roas")["value"])


if __name__ == "__main__":
    unittest.main()
