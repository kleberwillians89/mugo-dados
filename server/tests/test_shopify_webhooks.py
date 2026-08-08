from __future__ import annotations

import base64
import hashlib
import hmac
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import os  # noqa: E402

os.environ.setdefault("SHOPIFY_APP_SECRET", "test-shopify-secret-01234567")

from services import shopify_webhooks  # noqa: E402
from services.shopify_reporting import compute_shopify_revenue  # noqa: E402
from services.dashboard_paid import compute_mer  # noqa: E402


def _sign(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


class ShopifyHmacTests(unittest.TestCase):
    def test_valid_hmac_is_accepted(self):
        body = b'{"id": 1}'
        secret = os.environ["SHOPIFY_APP_SECRET"]
        provided = _sign(secret, body)
        is_valid, _computed, _debug = shopify_webhooks.validate_shopify_hmac(body, provided)
        self.assertTrue(is_valid)

    def test_invalid_hmac_is_rejected(self):
        body = b'{"id": 1}'
        is_valid, _computed, _debug = shopify_webhooks.validate_shopify_hmac(body, "not-the-real-signature")
        self.assertFalse(is_valid)

    def test_missing_hmac_header_is_rejected(self):
        is_valid, _computed, _debug = shopify_webhooks.validate_shopify_hmac(b"{}", None)
        self.assertFalse(is_valid)


class ShopifyWebhookDedupTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_webhook_id_delivered_twice_is_registered_once(self):
        stored: dict | None = None

        async def fake_get_one_by(table, *, filters, select="*", order=None):
            if stored and filters.get("webhook_id") == f"eq.{stored['webhook_id']}":
                return stored
            return None

        async def fake_insert(table, row, returning="representation"):
            nonlocal stored
            stored = row
            return row

        with (
            patch.object(shopify_webhooks, "sb_get_one_by", fake_get_one_by),
            patch.object(shopify_webhooks, "sb_insert", fake_insert),
        ):
            first, first_dup = await shopify_webhooks.register_shopify_webhook_event(
                client_id="amalie", webhook_id="wh-1", topic="orders/create",
                shop_domain="amalie.myshopify.com", payload_json={"id": 1},
            )
            second, second_dup = await shopify_webhooks.register_shopify_webhook_event(
                client_id="amalie", webhook_id="wh-1", topic="orders/create",
                shop_domain="amalie.myshopify.com", payload_json={"id": 1},
            )

        self.assertFalse(first_dup)
        self.assertTrue(second_dup)
        self.assertEqual(first["id"], second["id"])


class ShopifyOrderOrderingGuardTests(unittest.IsolatedAsyncioTestCase):
    """Um webhook mais antigo entregue depois de um mais novo (reentrega,
    fora de ordem) nunca pode sobrescrever o estado já persistido."""

    async def test_stale_webhook_does_not_overwrite_newer_persisted_order(self):
        persisted = {"updated_at_shopify": "2026-08-08T12:00:00Z"}
        upsert_calls = []

        async def fake_get_one_by(table, *, filters, select="*", order=None):
            return persisted

        async def fake_upsert(table, rows, on_conflict=None):
            upsert_calls.append(rows)

        stale_payload = {
            "id": 555,
            "updated_at": "2026-08-08T10:00:00Z",  # antes do já persistido
            "financial_status": "pending",
        }

        with (
            patch.object(shopify_webhooks, "sb_get_one_by", fake_get_one_by),
            patch.object(shopify_webhooks, "sb_upsert", fake_upsert),
        ):
            order_id = await shopify_webhooks._upsert_order(
                client_id="amalie", shop_domain="amalie.myshopify.com", payload=stale_payload,
            )

        self.assertEqual(order_id, "555")
        self.assertEqual(upsert_calls, [])  # nunca chegou a escrever

    async def test_newer_webhook_does_overwrite_persisted_order(self):
        persisted = {"updated_at_shopify": "2026-08-08T10:00:00Z"}
        upsert_calls = []

        async def fake_get_one_by(table, *, filters, select="*", order=None):
            return persisted

        async def fake_upsert(table, rows, on_conflict=None):
            upsert_calls.append(rows)

        newer_payload = {
            "id": 555,
            "updated_at": "2026-08-08T12:00:00Z",  # depois do já persistido
            "financial_status": "paid",
        }

        with (
            patch.object(shopify_webhooks, "sb_get_one_by", fake_get_one_by),
            patch.object(shopify_webhooks, "sb_upsert", fake_upsert),
        ):
            await shopify_webhooks._upsert_order(
                client_id="amalie", shop_domain="amalie.myshopify.com", payload=newer_payload,
            )

        self.assertEqual(len(upsert_calls), 1)
        self.assertEqual(upsert_calls[0][0]["financial_status"], "paid")


class ShopifyRevenueRuleTests(unittest.TestCase):
    def test_cancelled_order_never_counts_as_revenue(self):
        orders = [
            {"total_price": "100.00", "cancelled_at": None},
            {"total_price": "50.00", "cancelled_at": "2026-08-08T00:00:00Z"},
        ]
        result = compute_shopify_revenue(orders, [])
        self.assertEqual(result["revenue_total"], 100.0)
        self.assertEqual(result["net_revenue"], 100.0)

    def test_refund_reduces_net_revenue_but_not_gross(self):
        orders = [{"total_price": "100.00", "cancelled_at": None}]
        refunds = [{"total_refunded": "40.00"}]
        result = compute_shopify_revenue(orders, refunds)
        self.assertEqual(result["revenue_total"], 100.0)
        self.assertEqual(result["net_revenue"], 60.0)

    def test_fully_refunded_order_never_goes_negative(self):
        orders = [{"total_price": "100.00", "cancelled_at": None}]
        refunds = [{"total_refunded": "100.00"}, {"total_refunded": "50.00"}]
        result = compute_shopify_revenue(orders, refunds)
        self.assertEqual(result["net_revenue"], 0.0)

    def test_same_order_is_never_counted_twice(self):
        # shopify_orders é upsert por (client_id, shopify_order_id) — a
        # camada de relatório já recebe uma linha por pedido.
        orders = [{"total_price": "100.00", "cancelled_at": None}]
        result = compute_shopify_revenue(orders, [])
        self.assertEqual(result["revenue_total"], 100.0)


class BlendedRoasTests(unittest.TestCase):
    def test_blended_roas_uses_shopify_net_revenue_over_total_media_spend(self):
        # meta_spend=300, google_spend=200 -> total 500; shopify net=1000
        self.assertAlmostEqual(compute_mer(1000, 500), 2.0)

    def test_blended_roas_is_none_when_no_media_spend(self):
        self.assertIsNone(compute_mer(1000, 0))


class CustomerBatchUpsertTests(unittest.IsolatedAsyncioTestCase):
    """Antes, o backfill fazia um POST individual por cliente (o gargalo
    real observado em produção: dezenas/centenas de writes sequenciais).
    upsert_customers_batch faz poucas chamadas em chunks."""

    async def test_persists_many_customers_in_a_single_chunk_call(self):
        payloads = [{"id": i, "email": f"c{i}@example.com"} for i in range(1, 6)]
        calls = []

        async def fake_upsert(table, rows, on_conflict=None):
            calls.append((table, len(rows)))

        with patch.object(shopify_webhooks, "sb_upsert", fake_upsert):
            result = await shopify_webhooks.upsert_customers_batch(
                client_id="amalie", shop_domain="amalie-6421.myshopify.com", payloads=payloads, chunk_size=100,
            )

        self.assertEqual(result, {"upserted": 5, "failed": 0})
        self.assertEqual(calls, [("shopify_customers", 5)])  # uma única chamada, não 5

    async def test_respects_chunk_size_splitting_into_multiple_batched_calls(self):
        payloads = [{"id": i} for i in range(1, 251)]  # 250 clientes
        calls = []

        async def fake_upsert(table, rows, on_conflict=None):
            calls.append(len(rows))

        with patch.object(shopify_webhooks, "sb_upsert", fake_upsert):
            result = await shopify_webhooks.upsert_customers_batch(
                client_id="amalie", shop_domain="amalie-6421.myshopify.com", payloads=payloads, chunk_size=100,
            )

        self.assertEqual(result["upserted"], 250)
        # 3 chamadas (100 + 100 + 50), nunca 250 chamadas individuais.
        self.assertEqual(calls, [100, 100, 50])

    async def test_chunk_failure_falls_back_to_individual_upserts_to_isolate_bad_records(self):
        payloads = [{"id": 1}, {"id": 2}, {"id": 3}]
        attempts = []

        async def flaky_upsert(table, rows, on_conflict=None):
            attempts.append(len(rows))
            if len(rows) > 1:
                raise RuntimeError("chunk rejeitado pelo Supabase")
            if rows[0]["shopify_customer_id"] == "2":
                raise RuntimeError("registro 2 é inválido")

        with patch.object(shopify_webhooks, "sb_upsert", flaky_upsert):
            result = await shopify_webhooks.upsert_customers_batch(
                client_id="amalie", shop_domain="amalie-6421.myshopify.com", payloads=payloads, chunk_size=100,
            )

        # Chunk inteiro falhou -> fallback individual: 1 e 3 persistem, 2 falha isolado.
        self.assertEqual(result, {"upserted": 2, "failed": 1})

    async def test_customer_without_id_is_silently_skipped_not_counted_as_failed(self):
        payloads = [{"id": 1}, {"no_id": True}]
        calls = []

        async def fake_upsert(table, rows, on_conflict=None):
            calls.append(len(rows))

        with patch.object(shopify_webhooks, "sb_upsert", fake_upsert):
            result = await shopify_webhooks.upsert_customers_batch(
                client_id="amalie", shop_domain="amalie-6421.myshopify.com", payloads=payloads, chunk_size=100,
            )

        self.assertEqual(result["upserted"], 1)
        self.assertEqual(calls, [1])


if __name__ == "__main__":
    unittest.main()
