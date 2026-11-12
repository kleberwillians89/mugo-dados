"""Auditoria cruzada: loja × GA4 × Meta × Google, cada conferência com causa provável e o que fazer."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import data_reconciliation as dr


def daily(**sums):
    base = {f: 0.0 for f in dr.DAILY_FIELDS}
    base.update(sums)
    days = {k: 30 for k, v in sums.items() if v}
    days.update({"ga4_sessions": 30, "meta_spend": 28})
    return {"sums": base, "days": days, "period_days": 30}


STORE = {"orders": 200, "revenue": 40000.0, "orders_with_origin": 120, "origin_coverage_percent": 60.0,
         "channels": [{"channel": "paid_social", "orders": 50}, {"channel": "paid_search", "orders": 0}]}


class ChecksTests(unittest.TestCase):
    def setUp(self):
        out = dr.build_checks(STORE, daily(ga4_purchases=120, ga4_revenue=25000, meta_attributed_revenue=38000,
                                           google_ads_conversion_value=20000, meta_purchases=90, google_ads_conversions=12, meta_spend=1),
                              {"transactions": 130, "matched": 110}, {"store": 2})
        self.c = {c["key"]: c for c in out}

    def test_ga4_undercounting_is_flagged_with_cause(self):
        c = self.c["ga4_orders"]
        self.assertEqual((c["status"], c["value"]), ("warn", 60.0))
        self.assertIn("checkout externo", c["cause"])
        self.assertEqual(self.c["ga4_revenue"]["status"], "warn")  # 62,5%
        self.assertEqual(self.c["ga4_match"]["value"], 55.0)

    def test_platforms_claiming_the_same_sale(self):
        c = self.c["overlap"]
        self.assertEqual((c["status"], c["value"]), ("warn", 145.0))
        self.assertIn("mesma venda", c["cause"])

    def test_platform_vs_store_by_channel(self):
        self.assertEqual(self.c["meta_vs_store"]["value"], 180.0)
        self.assertEqual(self.c["meta_vs_store"]["status"], "warn")
        g = self.c["google_vs_store"]
        self.assertEqual((g["status"], g["value"]), ("warn", None))  # Google diz 12, loja 0 pedidos de busca paga

    def test_origin_coverage_days_and_duplicates(self):
        self.assertEqual(self.c["origin"]["status"], "warn")
        self.assertEqual(self.c["coverage_meta_spend"]["status"], "warn")  # 28 de 30
        self.assertEqual(self.c["coverage_ga4_sessions"]["status"], "ok")
        self.assertEqual((self.c["duplicates"]["status"], self.c["duplicates"]["value"]), ("bad", 2.0))

    def test_without_store_or_ga4_nothing_is_invented(self):
        out = {c["key"]: c for c in dr.build_checks({"orders": 0, "revenue": 0}, daily(), {"transactions": 0, "matched": 0}, {"store": 0})}
        self.assertEqual(out["ga4_orders"]["status"], "na")
        self.assertNotIn("overlap", out)
        self.assertNotIn("duplicates", out)
        ok = {c["key"]: c for c in dr.build_checks(STORE, daily(ga4_purchases=196, ga4_revenue=39000), {"transactions": 0, "matched": 0}, {"store": 0})}
        self.assertEqual((ok["ga4_orders"]["status"], ok["ga4_orders"]["cause"]), ("ok", ""))
        self.assertEqual(ok["ga4_match"]["status"], "na")

    def test_duplicates_helper(self):
        self.assertEqual(dr.duplicates(["a", "b", "a", "", "", "a"]), 2)


if __name__ == "__main__":
    unittest.main()


class ReconcileWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconcile_reads_store_daily_and_ga4_transactions(self):
        from unittest.mock import AsyncMock, patch
        from services import sales_by_origin as sbo
        store = {"provider": sbo.SHOPIFY, "status": "available", "channels": [],
                 "totals": {"orders": 3, "revenue": 300.0, "orders_with_origin": 3, "origin_coverage_percent": 100.0}}
        orders = [{"shopify_order_id": "1", "name": "#1001"}, {"shopify_order_id": "2", "name": "#1002"}, {"shopify_order_id": "2", "name": "#1002"}]
        tx = [{"client_id": "roove", "transaction_id": "#1001", "stat_date": "2026-11-02"}, {"client_id": "outra", "transaction_id": "1002"}]
        rows = [{"metric_date": "2026-11-02", "ga4_purchases": 3, "ga4_revenue": 300, "ga4_sessions": 50}]
        with patch.object(sbo, "build_sales_by_origin", AsyncMock(return_value=store)), \
             patch.object(sbo, "_shopify_orders", AsyncMock(return_value=(orders, False))), \
             patch.object(sbo, "_paged", AsyncMock(return_value=(tx, False))), \
             patch.object(dr, "sb_select", AsyncMock(return_value=rows)):
            out = await dr.reconcile("roove", start="2026-11-01", end="2026-11-10")
        c = {x["key"]: x for x in out["checks"]}
        self.assertEqual(c["ga4_match"]["value"], 33.3)  # 1 de 3: só o #1001 casa (a outra transação é de outro cliente)
        self.assertEqual(c["duplicates"]["value"], 1.0)
        self.assertEqual(out["period"], {"start": "2026-11-01", "end": "2026-11-10"})
