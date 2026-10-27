"""GA4: compras e receita por canal e campanha, com investimento só quando seguro."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services import ga4_attribution as attr  # noqa: E402
from services import ga4_reporting, ga4_sync  # noqa: E402
from services.ga4_reporting import GA4ReportPeriod  # noqa: E402
from datetime import date  # noqa: E402

PERIOD = GA4ReportPeriod(start=date(2026, 7, 29), end=date(2026, 10, 26), days=90)


def ga4_row(date_key, campaign, source_medium, purchases, revenue, channel=None, sessions=10):
    values = {"date": date_key, "sessionCampaignName": campaign, "sessionSourceMedium": source_medium,
              "sessions": str(sessions), "activeUsers": "5", "totalUsers": "5", "eventCount": "50",
              "ecommercePurchases": str(purchases), "purchaseRevenue": str(revenue), "totalRevenue": str(revenue)}
    if channel:
        values["sessionDefaultChannelGroup"] = channel
    return {"values": values}


class ChannelGroupTests(unittest.TestCase):
    def test_derived_channel_follows_ga4_rules(self):
        cases = [
            (("google", "cpc", "[CURAVINO] [Shopping] [Geral]"), "Paid Shopping"),
            (("google", "cpc", "[CURAVINO] [Search] [Marca]"), "Paid Search"),
            (("google", "organic", "(organic)"), "Organic Search"),
            (("(direct)", "(none)", "(direct)"), "Direct"),
            (("facebook", "paid", "ROOVE | PURCHASE"), "Paid Social"),
            (("ig", "social", "(not set)"), "Organic Social"),
            (("newsletter", "email", "BF"), "Email"),
            (("site.com", "referral", "(referral)"), "Referral"),
            (("google", "cpc", "PMax cross-network"), "Cross-network"),
        ]
        for (source, medium, campaign), expected in cases:
            with self.subTest(source=source, medium=medium, campaign=campaign):
                self.assertEqual(attr.derive_channel_group(source, medium, campaign), expected)


class SyncTests(unittest.IsolatedAsyncioTestCase):
    def test_campaign_rows_keep_ga4_channel_and_merge_duplicate_keys(self):
        rows = ga4_sync._campaign_upsert_rows(client_id="c", property_id="p", rows=[
            ga4_row("20261020", "[CURAVINO] [Shopping] [Geral]", "google / cpc", 2, 300.5, "Paid Shopping"),
            ga4_row("20261020", "[CURAVINO] [Shopping] [Geral]", "google / cpc", 1, 100, "Cross-network"),
            ga4_row("20261020", "(organic)", "google / organic", 1, 80, "Organic Search"),
        ])
        self.assertEqual(len(rows), 2)
        shopping = next(r for r in rows if r["campaign_name"].startswith("[CURAVINO]"))
        self.assertEqual((shopping["ecommerce_purchases"], shopping["purchase_revenue"]), (3, 400.5))
        self.assertEqual(shopping["channel_group"], "Paid Shopping")

    async def test_channel_dimension_only_after_compatibility_check(self):
        for check, expected in (({"dimensions": [], "metrics": []}, True),
                                ({"dimensions": ["sessionDefaultChannelGroup"], "metrics": []}, False),
                                (None, False)):
            with self.subTest(check=check), patch.object(ga4_sync, "check_ga4_compatibility", AsyncMock(return_value=check)) as compat:
                dims = await ga4_sync._campaign_dimensions("123", "token")
                self.assertEqual("sessionDefaultChannelGroup" in dims, expected)
                self.assertEqual(dims[:3], ("date", "sessionCampaignName", "sessionSourceMedium"))
                kwargs = compat.await_args.kwargs
                self.assertIn("ecommercePurchases", kwargs["metrics"])
                self.assertIn("purchaseRevenue", kwargs["metrics"])


class CompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_credentials_or_http_error_returns_none(self):
        from services import ga4_client
        with patch.object(ga4_client, "_get_access_token", side_effect=RuntimeError("sem credenciais")):
            self.assertIsNone(await ga4_client.check_ga4_compatibility(
                property_id="123", access_token=None, dimensions=["date"], metrics=["sessions"]))

    async def test_parses_incompatible_names(self):
        from services import ga4_client
        response = SimpleNamespace(status_code=200, json=lambda: {
            "dimensionCompatibilities": [{"dimensionMetadata": {"apiName": "sessionDefaultChannelGroup"}, "compatibility": "INCOMPATIBLE"}],
            "metricCompatibilities": [],
        })
        client = SimpleNamespace(post=AsyncMock(return_value=response))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        class Factory:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return client

            async def __aexit__(self, *a):
                return None

        with patch.object(ga4_client.httpx, "AsyncClient", Factory):
            out = await ga4_client.check_ga4_compatibility(
                property_id="properties/123", access_token="tok", dimensions=["date", "sessionDefaultChannelGroup"], metrics=["sessions"])
        self.assertEqual(out, {"dimensions": ["sessionDefaultChannelGroup"], "metrics": []})
        url = client.post.await_args.args[0]
        self.assertTrue(url.endswith("/properties/123:checkCompatibility"))
        self.assertEqual(client.post.await_args.kwargs["json"]["compatibilityFilter"], "INCOMPATIBLE")


class InvestmentTests(unittest.TestCase):
    def items(self):
        base = {"sessions": 10, "ecommerce_purchases": 0, "purchase_revenue": 0.0}
        return [
            {**base, "campaign_name": "[CURAVINO] [Shopping] [Geral]", "source": "google", "medium": "cpc",
             "channel_group": "Paid Shopping", "ecommerce_purchases": 4, "purchase_revenue": 800.0},
            {**base, "campaign_name": "[CURAVINO] [Shopping] [Curva A]", "source": "google", "medium": "cpc", "channel_group": None,
             "ecommerce_purchases": 1, "purchase_revenue": 150.0},
            {**base, "campaign_name": "(organic)", "source": "google", "medium": "organic", "channel_group": "Organic Search",
             "ecommerce_purchases": 2, "purchase_revenue": 300.0},
            {**base, "campaign_name": "BF", "source": "facebook", "medium": "paid", "channel_group": "Paid Social"},
            {**base, "campaign_name": "BF", "source": "instagram", "medium": "paid", "channel_group": "Paid Social"},
        ]

    def test_roas_only_with_safe_link(self):
        investments = {"google_ads": {"[CURAVINO] [Shopping] [Geral]": 200.0, "[CURAVINO] [Shopping] [Curva A]": 0.0},
                       "meta_ads": {"BF": 90.0}}
        out = {(i["campaign_name"], i["source"]): i for i in attr.enrich_campaign_items(self.items(), investments)}
        geral = out[("[CURAVINO] [Shopping] [Geral]", "google")]
        self.assertEqual((geral["investment"], geral["roas"], geral["investment_source"]), (200.0, 4.0, "google_ads"))
        curva = out[("[CURAVINO] [Shopping] [Curva A]", "google")]
        self.assertEqual(curva["channel_group"], "Paid Shopping")
        self.assertEqual(curva["channel_group_source"], "derivado")
        self.assertIsNone(curva["roas"])  # investimento zero: sem ROAS
        organic = out[("(organic)", "google")]
        self.assertIsNone(organic["investment"])
        self.assertIsNone(organic["roas"])
        # Duas linhas do GA4 disputam a mesma campanha Meta: nenhuma recebe investimento.
        self.assertIsNone(out[("BF", "facebook")]["investment"])
        self.assertIsNone(out[("BF", "instagram")]["investment"])

    def test_spend_only_for_names_of_a_single_campaign(self):
        spend = attr._spend_by_unique_name([
            {"campaign_id": "1", "campaign_name": "A", "cost": 10}, {"campaign_id": "1", "campaign_name": "A", "cost": 5},
            {"campaign_id": "2", "campaign_name": "B", "cost": 10}, {"campaign_id": "3", "campaign_name": "B", "cost": 7},
        ], spend_key="cost")
        self.assertEqual(spend, {"A": 15.0})

    def test_channel_group_totals(self):
        groups = attr.build_channel_group_items(attr.enrich_campaign_items(self.items(), {}))
        top = groups[0]
        self.assertEqual((top["channel_group"], top["ecommerce_purchases"], top["purchase_revenue"]), ("Paid Shopping", 5, 950.0))
        self.assertEqual(top["channel_group_source"], "derivado")


class ReportTests(unittest.IsolatedAsyncioTestCase):
    async def test_google_spend_is_scoped_to_client_connection_and_account(self):
        context = SimpleNamespace(client_id="cura", connection_id="conn", customer_id="acc")
        rows = [{"client_id": "cura", "connection_id": "conn", "customer_id": "acc", "campaign_id": "1",
                 "campaign_name": "[CURAVINO] [Shopping] [Geral]", "stat_date": "2026-10-10", "cost": 50},
                {"client_id": "outra", "connection_id": "conn", "customer_id": "acc", "campaign_id": "1",
                 "campaign_name": "[CURAVINO] [Shopping] [Geral]", "stat_date": "2026-10-10", "cost": 999}]
        with patch("services.google_ads.resolve_google_ads_context", AsyncMock(return_value=context)), \
             patch.object(attr, "sb_select", AsyncMock(return_value=rows)) as read:
            spend = await attr._google_ads_spend("cura", "2026-07-29", "2026-10-26")
        self.assertEqual(spend, {"[CURAVINO] [Shopping] [Geral]": 50.0})
        filters = read.await_args.kwargs["filters"]
        self.assertEqual((filters["client_id"], filters["connection_id"], filters["customer_id"]), ("eq.cura", "eq.conn", "eq.acc"))

    async def test_campaign_rows_fall_back_without_channel_column_and_drop_other_tenants(self):
        calls = []

        async def pages(table, *, select, filters, order, limit):
            calls.append(select)
            if "channel_group" in select:
                raise RuntimeError("column ga4_campaign_stats.channel_group does not exist")
            return [{"client_id": "cura", "property_id": "p", "campaign_name": "x"},
                    {"client_id": "outra", "property_id": "p", "campaign_name": "y"}]

        with patch.object(ga4_reporting, "_select_persisted_pages", pages):
            rows = await ga4_reporting._select_ga4_campaign_rows(client_id="cura", property_id="p", period=PERIOD)
        self.assertEqual([r["campaign_name"] for r in rows], ["x"])
        self.assertEqual(len(calls), 2)

    async def test_report_exposes_acquisition_and_empty_state_without_purchases(self):
        empty = AsyncMock(return_value=[])
        campaign_rows = [{"client_id": "c", "property_id": "p", "stat_date": "2026-10-10", "campaign_name": "(direct)",
                          "source_medium": "(direct) / (none)", "source": "(direct)", "medium": "(none)", "sessions": 12,
                          "ecommerce_purchases": 0, "purchase_revenue": 0}]
        with patch.object(ga4_reporting, "_select_ga4_daily_rows", empty), \
             patch.object(ga4_reporting, "_select_ga4_channel_rows", empty), \
             patch.object(ga4_reporting, "_select_ga4_event_rows", empty), \
             patch.object(ga4_reporting, "_select_ga4_campaign_rows", AsyncMock(return_value=campaign_rows)), \
             patch.object(ga4_reporting, "campaign_investments", AsyncMock(return_value={})):
            report = await ga4_reporting.build_ga4_report(client_id="c", property_id="p", period=PERIOD)
        self.assertFalse(report["acquisition"]["has_purchases"])
        self.assertEqual(report["acquisition"]["channel_groups"][0]["channel_group"], "Direct")
        self.assertEqual(report["campaigns"][0]["channel_group_label"], "Direto")
        self.assertIn("não é o faturamento confirmado", report["acquisition"]["notes"][0])


if __name__ == "__main__":
    unittest.main()
