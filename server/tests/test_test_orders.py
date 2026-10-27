"""Pedidos de teste não entram em venda: regra, ingestão e limpeza."""

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services import test_orders  # noqa: E402
from routes import platform_admin as routes  # noqa: E402

COUPON_100 = {"id": 1, "total_price": "0.00", "total_line_items_price": "249.90", "total_discounts": "249.90",
              "discount_codes": [{"code": "TESTE100", "amount": "249.90"}], "tags": ""}


class RuleTests(unittest.TestCase):
    def test_shopify_rule(self):
        self.assertTrue(test_orders.is_test_shopify_order(COUPON_100))
        self.assertTrue(test_orders.is_test_shopify_order({"test": True, "total_price": "100"}))
        self.assertTrue(test_orders.is_test_shopify_order({"tags": "vip, Teste", "total_price": "100"}))
        # Venda real com cupom parcial, ou pedido pago normal: continua.
        self.assertFalse(test_orders.is_test_shopify_order({**COUPON_100, "total_price": "199.90", "total_discounts": "50"}))
        self.assertFalse(test_orders.is_test_shopify_order({"total_price": "249.90", "tags": "testemunho"}))
        # R$ 0 sem cupom (ex.: troca) não é tratado como teste.
        self.assertFalse(test_orders.is_test_shopify_order({**COUPON_100, "discount_codes": []}))

    def test_fbits_rule(self):
        self.assertTrue(test_orders.is_test_fbits_order({"total_value": 0, "subtotal_value": 120, "coupon_code": "TESTE"}))
        self.assertFalse(test_orders.is_test_fbits_order({"total_value": 90, "subtotal_value": 120, "coupon_code": "X"}))
        self.assertFalse(test_orders.is_test_fbits_order({"total_value": 0, "subtotal_value": 120, "coupon_code": None}))


class IngestionTests(unittest.IsolatedAsyncioTestCase):
    async def test_shopify_webhook_skips_test_order_without_writing(self):
        from services import shopify_webhooks
        with patch.object(shopify_webhooks, "_upsert_order", AsyncMock()) as order, \
             patch.object(shopify_webhooks, "_upsert_customer", AsyncMock()) as customer:
            result = await shopify_webhooks._handle_order_topic(client_id="roove", shop_domain="x.myshopify.com", payload=COUPON_100)
        self.assertTrue(result["skipped_test"])
        order.assert_not_awaited()
        customer.assert_not_awaited()

    async def test_fbits_window_skips_test_order(self):
        from services import fbits_connections as fc

        class Client:
            async def iter_order_pages(self, **kwargs):
                yield [{"pedidoId": 1, "valorTotalPedido": 0, "valorSubTotalSemDescontos": 100, "cupomDesconto": "T", "itens": []},
                       {"pedidoId": 2, "valorTotalPedido": 100, "valorSubTotalSemDescontos": 100, "itens": []}]

        written = []
        with patch.object(fc, "upsert_orders_with_attribution", AsyncMock(side_effect=lambda t, rows, **k: written.extend(rows))), \
             patch.object(fc, "_persist_customer_identities", AsyncMock(return_value=0)), \
             patch.object(fc, "sb_upsert", AsyncMock()):
            from datetime import datetime, timezone
            counts = await fc.ingest_fbits_window(Client(), client_id="c", start=datetime.now(timezone.utc), end=datetime.now(timezone.utc),
                                                  date_filter="DataPedido", status_names={}, affected_days=set())
        self.assertEqual([row["order_id"] for row in written], ["2"])
        self.assertEqual(counts["orders"], 1)


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_dry_run_counts_and_cleanup_deletes_only_tests(self):
        shop_rows = [{"client_id": "roove", "shopify_order_id": "1", "created_at_shopify": "2026-10-20T15:00:00Z", "raw_payload": COUPON_100},
                     {"client_id": "roove", "shopify_order_id": "2", "created_at_shopify": "2026-10-21T15:00:00Z",
                      "raw_payload": {"total_price": "249.90"}}]

        async def select(table, **kwargs):
            return shop_rows if table == "shopify_orders" else []

        deletes = []
        with patch.object(test_orders, "sb_select", select), \
             patch.object(test_orders, "sb_delete", AsyncMock(side_effect=lambda t, **k: deletes.append((t, k["filters"])))), \
             patch("services.dashboard_read_model.refresh_dashboard_read_model", AsyncMock()) as refresh:
            preview = await test_orders.cleanup_test_orders("roove", dry_run=True)
            self.assertEqual(preview["shopify_test_orders"], 1)
            self.assertEqual(deletes, [])
            await test_orders.cleanup_test_orders("roove", dry_run=False)
        self.assertEqual([t for t, _ in deletes], ["shopify_order_items", "shopify_refunds", "shopify_orders"])
        self.assertTrue(all(f["shopify_order_id"] == 'in.("1")' and f["client_id"] == "eq.roove" for _, f in deletes))
        refresh.assert_awaited_once_with(client_id="roove", start="2026-10-20", end="2026-10-20", provider="shopify")

    async def test_cleanup_route_is_platform_admin_only(self):
        guard = AsyncMock(side_effect=HTTPException(status_code=403, detail="no"))
        with patch.object(routes, "require_platform_admin", guard):
            with self.assertRaises(HTTPException):
                await routes.platform_test_orders_cleanup("roove", authorization="Bearer t")
        guard.assert_awaited_once_with("Bearer t", allow_agency_admin=False)


if __name__ == "__main__":
    unittest.main()
