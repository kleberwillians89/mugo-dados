"""Pedido sem UTM mas com o clique do Google Ads (gclid) conta como Google Ads."""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import sales_by_origin  # noqa: E402
from services.order_attribution import (  # noqa: E402
    fbits_order_attribution,
    fbits_order_from_raw,
    fbits_origin_raw,
    shopify_order_attribution,
)


class GoogleClickTests(unittest.TestCase):
    def test_fbits_gclid_in_metadados_is_google_ads(self):
        out = fbits_order_attribution({"metadados": [{"chave": "gclid", "valor": "Cj0KCQ-abc"}]})
        self.assertEqual(out["origin_channel"], "paid_search")
        self.assertEqual(out["attribution_source"], "click_id")
        self.assertIn("Google Ads", out["origin_detail"])
        self.assertIsNone(out["utm_campaign"])  # nunca inventa campanha
        self.assertNotIn("Cj0KCQ-abc", str(out))  # o identificador não vai para a origem

    def test_gbraid_and_wbraid_count(self):
        for key in ("gbraid", "wbraid", "GCLID"):
            with self.subTest(key=key):
                self.assertEqual(fbits_order_attribution({"metadados": [{"chave": key, "valor": "x1"}]})["origin_channel"], "paid_search")

    def test_utm_wins_over_click_id(self):
        out = fbits_order_attribution({"metadados": [
            {"chave": "gclid", "valor": "abc"},
            {"chave": "utm_source", "valor": "google"}, {"chave": "utm_medium", "valor": "cpc"},
            {"chave": "utm_campaign", "valor": "curavino_shopping_geral"},
        ]})
        self.assertEqual((out["attribution_source"], out["utm_campaign"]), ("utm", "curavino_shopping_geral"))

    def test_fbclid_alone_is_not_paid(self):
        # fbclid aparece em qualquer clique saindo do Facebook/Instagram, pago ou não.
        out = fbits_order_attribution({"metadados": [{"chave": "fbclid", "valor": "x"}]})
        self.assertEqual(out["origin_channel"], "unknown")

    def test_marketplace_order_is_not_reclassified(self):
        out = fbits_order_attribution({"marketPlacePedidoId": "ML-1", "metadados": [{"chave": "gclid", "valor": "x"}]})
        self.assertEqual(out["origin_channel"], "marketplace")

    def test_empty_click_id_is_ignored(self):
        self.assertEqual(fbits_order_attribution({"metadados": [{"chave": "gclid", "valor": " "}]})["origin_channel"], "unknown")

    def test_shopify_gclid_in_landing_site(self):
        out = shopify_order_attribution({"landing_site": "/products/x?gclid=abc&email=a@b.com", "source_name": "web"})
        self.assertEqual((out["origin_channel"], out["attribution_source"]), ("paid_search", "click_id"))

    def test_raw_keeps_click_ids_and_rebuilds_same_origin(self):
        order = {"origemPedido": {"id": 1, "nome": "Loja"}, "metadados": [
            {"chave": "wbraid", "valor": "w1"}, {"chave": "email", "valor": "comprador@example.test"}]}
        raw = fbits_origin_raw(order)
        self.assertNotIn("comprador@example.test", str(raw))
        self.assertEqual(fbits_order_attribution(fbits_order_from_raw(raw)), fbits_order_attribution(order))


class SalesByOriginTests(unittest.TestCase):
    def test_click_orders_show_as_google_ads_without_campaign(self):
        report = sales_by_origin.aggregate_sales_by_origin([
            {"value": 100, "origin_channel": "paid_search", "attribution_source": "click_id"},
            {"value": 50, "origin_channel": "paid_search", "attribution_source": "utm", "utm_source": "google",
             "utm_medium": "cpc", "utm_campaign": "curavino_shopping_geral"},
            {"value": 30, "origin_channel": "unknown", "attribution_source": "none"},
        ])
        self.assertEqual(report["totals"]["orders_with_origin"], 2)
        self.assertEqual(report["totals"]["orders_with_google_click"], 1)
        campaigns = {row["campaign"]: row for row in report["campaigns"]}
        self.assertEqual(campaigns[sales_by_origin.GOOGLE_ADS_NO_CAMPAIGN]["source"], "google")
        self.assertEqual(campaigns["curavino_shopping_geral"]["revenue"], 50)


class ReprocessTests(unittest.TestCase):
    def rows(self):
        return [
            {"id": "a1", "origin_channel": None, "raw": {"metadados_origem": [{"chave": "gclid", "valor": "x"}]}},
            {"id": "a2", "origin_channel": "unknown", "raw": {"origemPedido": {"nome": "Loja"}}},
        ]

    def test_dry_run_counts_and_writes_nothing(self):
        select = AsyncMock(side_effect=[self.rows()])
        update = AsyncMock()
        with patch.object(sales_by_origin, "sb_select", select), patch.object(sales_by_origin, "sb_update", update):
            out = asyncio.run(sales_by_origin.reprocess_unknown_origins("cura", provider="fbits", dry_run=True))
        update.assert_not_awaited()
        fbits = out["providers"]["fbits"]
        self.assertEqual((fbits["scanned_without_origin"], fbits["origin_found"], fbits["updated"]), (2, 1, 0))
        filters = select.await_args.kwargs["filters"]
        self.assertEqual(filters["client_id"], "eq.cura")
        self.assertEqual(filters["or"], "(origin_channel.is.null,origin_channel.eq.unknown)")

    def test_apply_updates_only_rows_with_new_origin_scoped_to_company(self):
        update = AsyncMock()
        with patch.object(sales_by_origin, "sb_select", AsyncMock(side_effect=[self.rows()])), \
             patch.object(sales_by_origin, "sb_update", update):
            out = asyncio.run(sales_by_origin.reprocess_unknown_origins("cura", provider="fbits", dry_run=False))
        self.assertEqual(update.await_count, 1)
        kwargs = update.await_args.kwargs
        self.assertEqual(kwargs["filters"], {"id": "eq.a1", "client_id": "eq.cura"})
        self.assertEqual(kwargs["patch"]["attribution_source"], "click_id")
        self.assertEqual(out["providers"]["fbits"]["updated"], 1)

    def test_keyset_pagination(self):
        page1 = [{"id": f"{i:04d}", "origin_channel": None, "raw": {}} for i in range(200)]
        select = AsyncMock(side_effect=[page1, []])
        with patch.object(sales_by_origin, "sb_select", select), patch.object(sales_by_origin, "sb_update", AsyncMock()):
            asyncio.run(sales_by_origin.reprocess_unknown_origins("cura", provider="fbits", dry_run=True))
        self.assertEqual(select.await_args_list[1].kwargs["filters"]["id"], "gt.0199")


if __name__ == "__main__":
    unittest.main()
