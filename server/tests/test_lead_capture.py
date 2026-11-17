"""Regressão da captura universal: isolamento, credenciais, idempotência e LGPD."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import lead_capture as lc

SOURCE = "11111111-1111-4111-8111-111111111111"
KEY = "x" * 50


class CaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_random_key_without_persisting_plaintext(self):
        with patch.object(lc, "sb_insert", AsyncMock()) as insert:
            result = await lc.create_source("roove", "Newsletter", "custom_form")
        row = insert.await_args.args[1]
        self.assertEqual(row["client_id"], "roove")
        self.assertNotEqual(row["token_hash"], result["ingest_key"])
        self.assertEqual(row["token_hash"], lc._digest(result["ingest_key"]))
        self.assertEqual(len(row["token_hash"]), 64)

    async def test_any_future_provider_can_be_registered_without_schema_change(self):
        for provider in ("shopify", "wake_fbits", "woocommerce", "vtex", "hubspot", "custom_form"):
            with self.subTest(provider=provider), patch.object(lc, "sb_insert", AsyncMock()) as insert:
                source = await lc.create_source("roove", "Origem " + provider, provider)
                self.assertEqual(source["kind"], provider)
                self.assertEqual(insert.await_args.args[1]["kind"], provider)

    async def test_invalid_provider_slug_cannot_be_registered(self):
        with patch.object(lc, "sb_insert", AsyncMock()) as insert:
            with self.assertRaises(lc.LeadCaptureError):
                await lc.create_source("roove", "Form", "https://evil.example/?x=1")
        insert.assert_not_awaited()

    async def test_bad_key_rejected_before_write(self):
        with patch.object(lc, "sb_select", AsyncMock(return_value=[{
            "id": SOURCE, "client_id": "roove", "active": True, "token_hash": lc._digest(KEY)
        }])), patch.object(lc, "sb_insert", AsyncMock()) as insert:
            with self.assertRaises(lc.LeadCaptureError) as caught:
                await lc.ingest(SOURCE, "z" * 50, {"event_id": "1", "email": "ana@exemplo.com"})
            self.assertEqual(caught.exception.status, 401)
        insert.assert_not_awaited()

    async def test_ingest_keeps_tenant_and_claim_not_verified(self):
        async def select(table, **kwargs):
            if table == lc.SOURCE_TABLE:
                return [{"id": SOURCE, "client_id": "roove", "active": True, "token_hash": lc._digest(KEY)}]
            return []
        with patch.object(lc, "sb_select", side_effect=select), \
             patch.object(lc, "sb_insert", AsyncMock()) as insert, \
             patch.object(lc, "sb_update", AsyncMock()), \
             patch.object(lc, "encrypt_secret", side_effect=lambda value: "encrypted:" + value):
            result = await lc.ingest(SOURCE, KEY, {
                "event_id": "shopify-form-123", "email": "ANA@EXEMPLO.COM",
                "consent": {"email": True, "whatsapp": False}, "origin": "footer"
            })
        row = insert.await_args.args[1]
        self.assertFalse(result["duplicate"])
        self.assertEqual(row["client_id"], "roove")
        self.assertTrue(row["consent_email_claimed"])
        self.assertFalse(row["consent_verified"])
        self.assertNotIn("ANA@EXEMPLO.COM", str(row))
        self.assertEqual(row["email_ciphertext"], "encrypted:ana@exemplo.com")

    async def test_duplicate_event_not_inserted(self):
        with patch.object(lc, "sb_select", AsyncMock(side_effect=[
            [{"id": SOURCE, "client_id": "roove", "active": True, "token_hash": lc._digest(KEY)}],
            [{"id": "already"}],
        ])), patch.object(lc, "sb_insert", AsyncMock()) as insert:
            result = await lc.ingest(SOURCE, KEY, {"event_id": "same", "email": "ana@exemplo.com"})
        self.assertTrue(result["duplicate"])
        insert.assert_not_awaited()

    async def test_invalid_consent_rejected(self):
        with patch.object(lc, "sb_select", AsyncMock(return_value=[
            {"id": SOURCE, "client_id": "roove", "active": True, "token_hash": lc._digest(KEY)}
        ])), patch.object(lc, "sb_insert", AsyncMock()) as insert:
            with self.assertRaises(lc.LeadCaptureError):
                await lc.ingest(SOURCE, KEY, {
                    "event_id": "x", "email": "ana@exemplo.com", "consent": {"whatsapp": "yes"}
                })
        insert.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
