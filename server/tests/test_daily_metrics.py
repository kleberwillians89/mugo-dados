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
from services.dashboard_paid import _aggregate_paid_rows, _filter_paid_detail_rows  # noqa: E402


class MetaDailyRoasTests(unittest.TestCase):
    def test_august_revenue_never_includes_july_rows(self):
        rows = [
            {"stat_date": "2026-07-31", "spend": 1000, "revenue": 100000},
            {"stat_date": "2026-08-01", "spend": 5000, "revenue": 20000},
        ]
        august_rows = [row for row in rows if "2026-08-01" <= row["stat_date"] <= "2026-08-31"]
        aggregated = _aggregate_paid_rows(august_rows, since="2026-08-01", until="2026-08-31")
        self.assertEqual(aggregated["totals"]["revenue"], 20000)
        self.assertEqual(aggregated["totals"]["spend"], 5000)
        self.assertEqual(aggregated["totals"]["roas"], 4)

    def test_missing_days_are_null_and_coverage_is_explicit(self):
        aggregated = _aggregate_paid_rows(
            [{"stat_date": "2026-08-02", "spend": 10, "revenue": 20}],
            since="2026-08-01", until="2026-08-03",
        )
        by_date = {row["date"]: row for row in aggregated["daily"]}
        self.assertIsNone(by_date["2026-08-01"]["spend"])
        self.assertTrue(by_date["2026-08-01"]["missing"])
        self.assertEqual(aggregated["coverage"], {"covered_days": 1, "expected_days": 3, "is_partial": True})

    def test_composed_paid_filters_use_the_intersection(self):
        rows = [
            {"campaign_name": "Agosto", "adset_name": "Mulheres", "ad_name": "Video A", "source_platform": "instagram"},
            {"campaign_name": "Agosto", "adset_name": "Homens", "ad_name": "Video A", "source_platform": "instagram"},
            {"campaign_name": "Agosto", "adset_name": "Mulheres", "ad_name": "Video B", "source_platform": "facebook"},
        ]
        filtered = _filter_paid_detail_rows(
            rows, campaign="agosto", adset="mulheres", ad="video a", platform="instagram",
        )
        self.assertEqual(filtered, [rows[0]])

    def test_daily_meta_roas_uses_same_day_revenue_over_same_day_spend(self):
        rows = [
            {"stat_date": "2026-08-01", "spend": "100.00", "revenue_micros": None, "revenue": "500.00", "conversions": "5", "impressions": "1000", "clicks": "50"},
            {"stat_date": "2026-08-02", "spend": "200.00", "revenue": "100.00", "conversions": "2", "impressions": "1000", "clicks": "50"},
        ]
        aggregated = _aggregate_paid_rows(rows, since="2026-08-01", until="2026-08-02")
        by_date = {row["date"]: row for row in aggregated["daily"]}
        # dia 1: 500/100 = 5.0 — nunca usa receita acumulada nem spend de outro dia
        self.assertAlmostEqual(by_date["2026-08-01"]["roas"], 5.0)
        # dia 2: 100/200 = 0.5
        self.assertAlmostEqual(by_date["2026-08-02"]["roas"], 0.5)

    def test_daily_meta_roas_is_none_when_spend_is_zero(self):
        rows = [{"stat_date": "2026-08-01", "spend": "0", "revenue": "500.00", "conversions": "1", "impressions": "0", "clicks": "0"}]
        aggregated = _aggregate_paid_rows(rows, since="2026-08-01", until="2026-08-01")
        self.assertIsNone(aggregated["daily"][0]["roas"])


class ShopifyDailyNetRevenueTests(unittest.TestCase):
    def test_daily_net_revenue_uses_refunds_of_that_days_orders_regardless_of_refund_date(self):
        period = shopify_reporting.resolve_shopify_report_period(start="2026-08-01", end="2026-08-02")
        orders = [
            {"shopify_order_id": "1", "total_price": "300.00", "cancelled_at": None,
             "financial_status": "paid", "created_at_shopify": "2026-08-01T10:00:00Z"},
            {"shopify_order_id": "2", "total_price": "150.00", "cancelled_at": None,
             "financial_status": "paid", "created_at_shopify": "2026-08-02T10:00:00Z"},
        ]
        # refund do pedido 1 (dia 01) só chega/é registrado no dia 05 — mas
        # ainda precisa reduzir o net_revenue do dia 01 (dia do PEDIDO).
        refunds = [{"shopify_order_id": "1", "total_refunded": "50.00", "created_at_shopify": "2026-08-05T00:00:00Z"}]

        series = shopify_reporting.build_daily_commercial_series(period, orders, refunds)
        by_date = {row["date"]: row for row in series}
        self.assertEqual(by_date["2026-08-01"]["gross_revenue"], 300.0)
        self.assertEqual(by_date["2026-08-01"]["net_revenue"], 250.0)
        self.assertEqual(by_date["2026-08-02"]["net_revenue"], 150.0)

    def test_cancelled_order_never_enters_daily_net_revenue(self):
        period = shopify_reporting.resolve_shopify_report_period(start="2026-08-01", end="2026-08-01")
        orders = [
            {"shopify_order_id": "1", "total_price": "100.00", "cancelled_at": None,
             "financial_status": "paid", "created_at_shopify": "2026-08-01T10:00:00Z"},
            {"shopify_order_id": "2", "total_price": "80.00", "cancelled_at": "2026-08-01T12:00:00Z",
             "financial_status": "voided", "created_at_shopify": "2026-08-01T11:00:00Z"},
        ]
        series = shopify_reporting.build_daily_commercial_series(period, orders, [])
        self.assertEqual(series[0]["net_revenue"], 100.0)
        self.assertEqual(series[0]["cancelled_orders"], 1)


class RealMediaReturnDailyTests(unittest.TestCase):
    def test_blended_daily_uses_same_day_shopify_net_revenue_and_same_day_meta_spend(self):
        shopify = {"daily": [
            {"date": "2026-08-01", "net_revenue": 1000.0},
            {"date": "2026-08-02", "net_revenue": 500.0},
        ]}
        meta = {"daily": [
            {"date": "2026-08-01", "spend": 200.0, "attributed_revenue": 900.0, "roas": 4.5},
            {"date": "2026-08-02", "spend": 100.0, "attributed_revenue": 300.0, "roas": 3.0},
        ]}
        series = ed._build_daily_series(shopify=shopify, meta=meta, included_paid_sources=["meta"])
        by_date = {row["date"]: row for row in series}
        self.assertAlmostEqual(by_date["2026-08-01"]["blended_roas"], 5.0)  # 1000/200
        self.assertAlmostEqual(by_date["2026-08-02"]["blended_roas"], 5.0)  # 500/100

    def test_blended_daily_is_none_without_included_paid_sources(self):
        shopify = {"daily": [{"date": "2026-08-01", "net_revenue": 1000.0}]}
        meta = {"daily": []}
        series = ed._build_daily_series(shopify=shopify, meta=meta, included_paid_sources=[])
        self.assertIsNone(series[0]["blended_roas"])


class SourceIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_meta_failure_never_prevents_shopify_data_from_appearing(self):
        with (
            patch.object(ed, "_build_shopify_section", AsyncMock(return_value={
                "connected": True, "net_revenue": 500.0, "daily": [{"date": "2026-08-01", "net_revenue": 500.0}],
            })),
            patch.object(ed, "get_paid_dashboard", AsyncMock(side_effect=RuntimeError("meta down"))),
            patch.object(ed, "_build_ga4_section", AsyncMock(return_value=None)),
        ):
            result = await ed.get_executive_summary("amalie", days=1, include_previous_period=False)

        self.assertEqual(result["shopify"]["net_revenue"], 500.0)
        self.assertFalse(result["meta"]["connected"])
        self.assertIsNone(result["meta"]["spend"])


if __name__ == "__main__":
    unittest.main()
