"""Origem dos pedidos: Shopify, FBITS, classificação de canal e agregação."""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import fbits_connections, order_attribution, sales_by_origin  # noqa: E402
from services.order_attribution import (  # noqa: E402
    classify_channel,
    fbits_order_attribution,
    fbits_origin_raw,
    shopify_order_attribution,
    utms_from_url,
)


class ShopifyAttributionTests(unittest.TestCase):
    def test_utm_from_landing_site(self):
        payload = {
            "landing_site": "/products/legging?utm_source=facebook&utm_medium=paid_social&utm_campaign=bf_2026&email=x@y.com",
            "referring_site": "https://l.facebook.com/",
            "source_name": "web",
        }
        out = shopify_order_attribution(payload, shop_domain="roove.myshopify.com")
        self.assertEqual(out["utm_source"], "facebook")
        self.assertEqual(out["utm_campaign"], "bf_2026")
        self.assertEqual(out["origin_channel"], "paid_social")
        self.assertEqual(out["attribution_source"], "utm")
        self.assertEqual(out["referrer_domain"], "l.facebook.com")
        # Nada da query além de utm_* é guardado.
        self.assertNotIn("x@y.com", str(out))

    def test_note_attributes_fill_missing_utms(self):
        payload = {"landing_site": "/", "note_attributes": [{"name": "utm_source", "value": "google"}, {"name": "utm_medium", "value": "cpc"}]}
        out = shopify_order_attribution(payload)
        self.assertEqual(out["origin_channel"], "paid_search")

    def test_referrer_without_utm(self):
        out = shopify_order_attribution({"referring_site": "https://www.google.com/"})
        self.assertEqual(out["origin_channel"], "organic_search")
        self.assertEqual(out["attribution_source"], "referrer")

    def test_no_origin_is_unknown(self):
        out = shopify_order_attribution({"source_name": "web"})
        self.assertEqual(out["origin_channel"], "unknown")
        self.assertEqual(out["attribution_source"], "none")
        self.assertIsNone(out["utm_campaign"])

    def test_bad_payload_does_not_raise(self):
        self.assertEqual(shopify_order_attribution(None)["origin_channel"], "unknown")  # type: ignore[arg-type]
        self.assertEqual(utms_from_url("http://[bad"), {})


class FbitsAttributionTests(unittest.TestCase):
    def order(self, **extra):
        return {
            "pedidoId": 10, "situacaoPedidoId": 1, "valorTotalPedido": 100,
            "usuario": {"usuarioId": 5, "nome": "Fulano", "email": "f@x.com", "cpf": "123", "origemContato": "Google"},
            "itens": [],
            **extra,
        }

    def test_utm_from_metadados(self):
        order = self.order(metadados=[{"chave": "utm_source", "valor": "instagram"}, {"chave": "utm_medium", "valor": "cpc"},
                                      {"chave": "utm_campaign", "valor": "dia_dos_pais"}, {"chave": "cpf", "valor": "999"}])
        out = fbits_order_attribution(order)
        self.assertEqual(out["origin_channel"], "paid_social")
        self.assertEqual(out["utm_campaign"], "dia_dos_pais")
        raw = fbits_origin_raw(order)
        self.assertEqual([m["chave"] for m in raw["metadados_origem"]], ["utm_source", "utm_medium", "utm_campaign"])
        self.assertNotIn("999", str(raw))

    def test_origem_pedido_without_utm(self):
        order = self.order(origemPedido={"id": 1, "nome": "Mercado Livre", "subOrigem": {"id": 2, "nome": "Full"}})
        out = fbits_order_attribution(order)
        self.assertEqual(out["origin_channel"], "marketplace")
        self.assertEqual(out["origin_detail"], "Mercado Livre · Full")
        self.assertEqual(out["attribution_source"], "platform")

    def test_normalize_order_keeps_pii_out_and_adds_origin(self):
        order = self.order(metadados=[{"chave": "utm_source", "valor": "google"}, {"chave": "utm_medium", "valor": "cpc"}])
        row = fbits_connections.normalize_order("c1", order, {})
        self.assertEqual(row["origin_channel"], "paid_search")
        self.assertEqual(set(row["raw"]["usuario"]), {"usuarioId"})
        for secret in ("Fulano", "f@x.com", "123"):
            self.assertNotIn(secret, str(row))


class ChannelTests(unittest.TestCase):
    def test_matrix(self):
        cases = [
            ({"utm_source": "facebook", "utm_medium": "cpc"}, "paid_social"),
            ({"utm_source": "ig", "utm_medium": "social"}, "organic_social"),
            ({"utm_source": "google", "utm_medium": "organic"}, "organic_search"),
            ({"utm_source": "klaviyo", "utm_medium": "email"}, "email"),
            ({"utm_source": "whatsapp", "utm_medium": "broadcast"}, "sms_whatsapp"),
            ({"utm_source": "criteo", "utm_medium": "display"}, "paid_other"),
            ({"utm_source": "blog_parceiro", "utm_medium": "afiliado"}, "affiliate"),
            ({"referrer_domain": "bing.com"}, "organic_search"),
            ({"referrer_domain": "roove.myshopify.com", "store_domain": "roove.myshopify.com"}, "unknown"),
            ({}, "unknown"),
        ]
        for kwargs, expected in cases:
            with self.subTest(kwargs=kwargs):
                self.assertEqual(classify_channel(**kwargs), expected)


class AggregateTests(unittest.TestCase):
    def test_totals_channels_campaigns(self):
        orders = [
            {"value": 100, "origin_channel": "paid_social", "utm_source": "facebook", "utm_campaign": "bf", "attribution_source": "utm"},
            {"value": 50, "origin_channel": "paid_social", "utm_source": "facebook", "utm_campaign": "bf", "attribution_source": "utm"},
            {"value": 50, "origin_channel": None, "attribution_source": None},
        ]
        out = sales_by_origin.aggregate_sales_by_origin(orders)
        self.assertEqual(out["totals"]["orders"], 3)
        self.assertEqual(out["totals"]["revenue"], 200)
        self.assertEqual(out["totals"]["utm_coverage_percent"], 66.67)
        self.assertEqual(out["channels"][0]["channel"], "paid_social")
        self.assertEqual(out["channels"][0]["share_of_revenue"], 75.0)
        # "Origem não identificada" sempre por último.
        self.assertEqual(out["channels"][-1]["channel"], "unknown")
        self.assertEqual(out["campaigns"][0]["campaign"], "bf")
        self.assertEqual(out["campaigns"][0]["average_ticket"], 75.0)

    def test_empty(self):
        out = sales_by_origin.aggregate_sales_by_origin([])
        self.assertIsNone(out["totals"]["average_ticket"])
        self.assertEqual(out["channels"], [])


def _column_error():
    request = httpx.Request("POST", "https://x/rest/v1/shopify_orders")
    response = httpx.Response(400, request=request, text='{"message":"column shopify_orders.utm_source does not exist"}')
    return httpx.HTTPStatusError("400", request=request, response=response)


class MigrationCompatibilityTests(unittest.TestCase):
    def test_upsert_retries_without_origin_columns(self):
        calls = []

        async def fake_upsert(table, rows, on_conflict=None):
            calls.append(rows)
            if len(calls) == 1:
                raise _column_error()
            return {}

        rows = [{"client_id": "c", "shopify_order_id": "1", "utm_source": "facebook", "origin_channel": "paid_social"}]
        asyncio.run(order_attribution.upsert_orders_with_attribution(
            "shopify_orders", rows, on_conflict="client_id,shopify_order_id", upsert=fake_upsert))
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1], [{"client_id": "c", "shopify_order_id": "1"}])

    def test_report_says_migration_pending(self):
        with patch.object(sales_by_origin, "resolve_commerce_provider", AsyncMock(return_value={"provider": "shopify"})), \
             patch.object(sales_by_origin, "sb_select", AsyncMock(side_effect=_column_error())):
            out = asyncio.run(sales_by_origin.build_sales_by_origin("c", start="2026-10-01", end="2026-10-07"))
        self.assertEqual(out["status"], "migration_pending")

    def test_report_shopify_ignores_cancelled(self):
        rows = [
            {"shopify_order_id": "1", "total_price": "120.00", "cancelled_at": None, "origin_channel": "paid_social",
             "utm_campaign": "bf", "attribution_source": "utm"},
            {"shopify_order_id": "2", "total_price": "80.00", "cancelled_at": "2026-10-02T00:00:00Z", "origin_channel": "email"},
        ]
        with patch.object(sales_by_origin, "resolve_commerce_provider", AsyncMock(return_value={"provider": "shopify"})), \
             patch.object(sales_by_origin, "sb_select", AsyncMock(return_value=rows)):
            out = asyncio.run(sales_by_origin.build_sales_by_origin("c", start="2026-10-01", end="2026-10-07"))
        self.assertEqual(out["status"], "available")
        self.assertEqual(out["totals"]["orders"], 1)
        self.assertEqual(out["totals"]["revenue"], 120.0)
        self.assertEqual(out["attribution_model"], "last_click_utm")

    def test_not_connected(self):
        with patch.object(sales_by_origin, "resolve_commerce_provider", AsyncMock(return_value={"provider": None})):
            out = asyncio.run(sales_by_origin.build_sales_by_origin("c"))
        self.assertEqual(out["status"], "not_connected")

    def test_backfill_updates_from_raw_payload(self):
        page = [{"id": "r1", "shop_domain": "roove.myshopify.com",
                 "raw_payload": {"landing_site": "/?utm_source=facebook&utm_medium=cpc&utm_campaign=x"}}]
        update = AsyncMock(return_value=[])
        with patch.object(sales_by_origin, "sb_select", AsyncMock(side_effect=[page, []])), \
             patch.object(sales_by_origin, "sb_update", update):
            out = asyncio.run(sales_by_origin.backfill_shopify_attribution("c"))
        self.assertEqual(out["updated"], 1)
        patch_arg = update.call_args.kwargs["patch"]
        self.assertEqual(patch_arg["origin_channel"], "paid_social")
        self.assertEqual(update.call_args.kwargs["filters"]["client_id"], "eq.c")


if __name__ == "__main__":
    unittest.main()
