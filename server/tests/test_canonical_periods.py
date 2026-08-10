from __future__ import annotations

import unittest

from server.services import dashboard_paid, executive_dashboard, ga4_reporting, shopify_reporting
from server.services.periods import resolve_period


class CanonicalPeriodTests(unittest.TestCase):
    def test_single_local_day_has_exact_sao_paulo_utc_bounds(self):
        period = resolve_period(start="2026-08-10", end="2026-08-10", days=30)

        self.assertEqual(period.days, 1)
        self.assertEqual(period.dates(), ["2026-08-10"])
        start_utc, end_utc = period.utc_bounds()
        self.assertEqual(start_utc.isoformat(), "2026-08-10T03:00:00+00:00")
        self.assertEqual(end_utc.isoformat(), "2026-08-11T02:59:59.999999+00:00")

    def test_explicit_range_is_authoritative_over_days(self):
        period = resolve_period(start="2026-08-04", end="2026-08-10", days=1)

        self.assertEqual(period.days, 7)
        self.assertEqual(period.dates()[0], "2026-08-04")
        self.assertEqual(period.dates()[-1], "2026-08-10")
        self.assertEqual(dashboard_paid._date_window(1, None, "2026-08-04", "2026-08-10"), ("2026-08-04", "2026-08-10"))
        self.assertEqual(ga4_reporting.resolve_ga4_report_period(start="2026-08-04", end="2026-08-10", days=1).days, 7)
        self.assertEqual(shopify_reporting.resolve_shopify_report_period(start="2026-08-04", end="2026-08-10", days=1).days, 7)

    def test_shopify_order_uses_local_commercial_date(self):
        self.assertEqual(
            shopify_reporting._order_date_key({"created_at_shopify": "2026-08-11T02:30:00Z"}),
            "2026-08-10",
        )
        self.assertEqual(
            shopify_reporting._order_date_key({"created_at_shopify": "2026-08-10T23:30:00-03:00"}),
            "2026-08-10",
        )

    def test_shopify_filters_use_whole_local_day(self):
        day = shopify_reporting.resolve_shopify_report_period(start="2026-08-10", end="2026-08-10")

        self.assertEqual(shopify_reporting._iso_start_of_day(day.start), "2026-08-10T03:00:00+00:00")
        self.assertEqual(shopify_reporting._iso_end_of_day(day.end), "2026-08-11T02:59:59.999999+00:00")

    def test_consolidated_series_keeps_every_requested_date(self):
        series = executive_dashboard._build_daily_series(
            since="2026-08-04",
            until="2026-08-10",
            shopify={"daily": [{"date": "2026-08-10", "net_revenue": 4000}]},
            meta={"daily": []},
            ga4=None,
            instagram=None,
            included_paid_sources=["meta"],
        )

        self.assertEqual(len(series), 7)
        self.assertEqual(series[0]["date"], "2026-08-04")
        self.assertEqual(series[-1]["date"], "2026-08-10")
        self.assertIsNone(series[-1]["meta"])
        self.assertEqual(series[-1]["shopify"]["net_revenue"], 4000)
        self.assertIsNone(series[-1]["blended_return"])

    def test_zero_spend_never_generates_invalid_division(self):
        self.assertIsNone(dashboard_paid.compute_roas(500, 0))
        self.assertIsNone(dashboard_paid.compute_mer(4000, 0))


if __name__ == "__main__":
    unittest.main()
