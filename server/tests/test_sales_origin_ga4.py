"""Pedido sem UTM herda a origem que o GA4 registrou para a mesma transação."""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import ga4_sync, sales_by_origin  # noqa: E402


def ga4_row(date, tid, sm, campaign, revenue, purchases=1):
    return {"values": {"date": date, "transactionId": tid, "sessionSourceMedium": sm, "sessionCampaignName": campaign,
                       "ecommercePurchases": str(purchases), "purchaseRevenue": str(revenue)}}


class TransactionSyncTests(unittest.TestCase):
    def test_one_row_per_transaction_without_placeholders(self):
        rows = ga4_sync._transaction_upsert_rows(client_id="cura", property_id="p", rows=[
            ga4_row("20261020", "150900", "google / cpc", "[CURAVINO] [Shopping] [Geral]", 400),
            ga4_row("20261020", "150900", "google / cpc", "[CURAVINO] [Shopping] [Geral]", 400),  # purchase repetido
            ga4_row("20261019", "150901", "(direct) / (none)", "(direct)", 100),
            ga4_row("20261021", "150901", "google / cpc", "[CURAVINO] [Shopping] [Curva A]", 250),
            ga4_row("20261021", "(not set)", "google / cpc", "x", 999),
            ga4_row("20261021", "", "google / cpc", "x", 999),
        ])
        by_id = {row["transaction_id"]: row for row in rows}
        self.assertEqual(set(by_id), {"150900", "150901"})
        self.assertEqual(by_id["150900"]["stat_date"], "2026-10-20")
        self.assertEqual(by_id["150901"]["campaign_name"], "[CURAVINO] [Shopping] [Curva A]")  # maior receita
        self.assertEqual((by_id["150901"]["source"], by_id["150901"]["medium"]), ("google", "cpc"))
        self.assertTrue(all(row["client_id"] == "cura" and row["property_id"] == "p" for row in rows))

    def test_transaction_sync_never_breaks_ga4_sync(self):
        with patch.object(ga4_sync, "_run_named_report", AsyncMock(side_effect=RuntimeError("table missing"))):
            count = asyncio.run(ga4_sync._sync_ga4_transactions(
                client_id="cura", property_id="p", access_token=None, start="2026-10-01", end="2026-10-27"))
        self.assertEqual(count, 0)

    def test_transaction_sync_upserts_by_transaction(self):
        report = {"rows": [ga4_row("20261020", "150900", "google / cpc", "Geral", 400)], "row_count": 1}
        with patch.object(ga4_sync, "_run_named_report", AsyncMock(return_value=report)) as run, \
             patch.object(ga4_sync, "sb_upsert", AsyncMock()) as upsert:
            count = asyncio.run(ga4_sync._sync_ga4_transactions(
                client_id="cura", property_id="p", access_token="t", start="2026-10-01", end="2026-10-27"))
        self.assertEqual(count, 1)
        self.assertIn("transactionId", run.await_args.kwargs["dimensions"])
        self.assertEqual(upsert.await_args.kwargs["on_conflict"], "client_id,property_id,transaction_id")


class MergeTests(unittest.TestCase):
    def transactions(self):
        return {
            "150900": {"client_id": "cura", "transaction_id": "150900", "source": "google", "medium": "cpc",
                       "campaign_name": "[CURAVINO] [Shopping] [Curva A]"},
            "150901": {"client_id": "cura", "transaction_id": "150901", "source": "google", "medium": "organic",
                       "campaign_name": "(organic)"},
            "150902": {"client_id": "cura", "transaction_id": "150902", "source": "(direct)", "medium": "(none)",
                       "campaign_name": "(direct)"},
            "150903": {"client_id": "cura", "transaction_id": "150903", "source": "(not set)", "medium": "",
                       "campaign_name": "(not set)"},
            "1001": {"client_id": "cura", "transaction_id": "1001", "source": "facebook", "medium": "paid",
                     "campaign_name": "BF"},
        }

    def test_only_orders_without_origin_receive_ga4_origin(self):
        orders = [
            {"order_id": "150900", "value": 400, "origin_channel": "unknown", "attribution_source": "none"},
            {"order_id": "150901", "value": 90, "origin_channel": None},
            {"order_id": "150902", "value": 50, "origin_channel": "unknown"},
            {"order_id": "150903", "value": 10, "origin_channel": "unknown"},
            {"order_id": "150900x", "value": 10, "origin_channel": "unknown"},
            {"order_id": "150900", "value": 70, "origin_channel": "paid_search", "attribution_source": "utm",
             "utm_source": "google", "utm_medium": "cpc", "utm_campaign": "curavino_shopping_geral"},
        ]
        matched = sales_by_origin.merge_ga4_origins(orders, self.transactions())
        self.assertEqual(matched, 3)
        self.assertEqual((orders[0]["origin_channel"], orders[0]["utm_campaign"], orders[0]["attribution_source"]),
                         ("paid_search", "[CURAVINO] [Shopping] [Curva A]", "ga4"))
        self.assertEqual((orders[1]["origin_channel"], orders[1]["utm_campaign"]), ("organic_search", None))
        self.assertEqual(orders[2]["origin_channel"], "direct")
        self.assertEqual(orders[3]["origin_channel"], "unknown")  # GA4 sem origem
        self.assertEqual(orders[4]["origin_channel"], "unknown")  # ID diferente
        self.assertEqual(orders[5]["utm_campaign"], "curavino_shopping_geral")  # UTM da loja não muda
        report = sales_by_origin.aggregate_sales_by_origin(orders)
        campaigns = {row["campaign"] for row in report["campaigns"]}
        self.assertIn("[CURAVINO] [Shopping] [Curva A]", campaigns)
        self.assertEqual(report["totals"]["orders_with_origin"], 4)
        # Curva A (GA4) + campanha da UTM: 2 de 6 pedidos com campanha.
        self.assertEqual(report["totals"]["orders_with_campaign"], 2)
        self.assertEqual(report["totals"]["campaign_coverage_percent"], 33.33)

    def test_shopify_names_match_with_or_without_hash(self):
        orders = [{"shopify_order_id": "5550001", "name": "#1001", "order_number": "1001", "origin_channel": "unknown", "value": 1}]
        self.assertEqual(sales_by_origin.merge_ga4_origins(orders, self.transactions()), 1)
        self.assertEqual(orders[0]["origin_channel"], "paid_social")

    def test_lookup_is_scoped_and_tolerates_missing_table(self):
        rows = [{"client_id": "cura", "transaction_id": "1"}, {"client_id": "outra", "transaction_id": "2"}]
        with patch.object(sales_by_origin, "_paged", AsyncMock(return_value=(rows, False))) as paged:
            out = asyncio.run(sales_by_origin._ga4_transactions("cura", "2026-09-26", "2026-10-29"))
        self.assertEqual(set(out), {"1"})
        self.assertEqual(paged.await_args.kwargs["filters"]["client_id"], "eq.cura")
        with patch.object(sales_by_origin, "_paged", AsyncMock(side_effect=RuntimeError("relation does not exist"))):
            self.assertEqual(asyncio.run(sales_by_origin._ga4_transactions("cura", "a", "b")), {})


if __name__ == "__main__":
    unittest.main()
