"""Projeção de clientes existentes sem consentimento presumido."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import relationship_contacts as rc


class RelationshipCustomersTests(unittest.IsolatedAsyncioTestCase):
    async def test_shopify_imports_customers_even_without_orders(self):
        profiles = [
            {"client_id": "roove", "shopify_customer_id": "123", "email": "ANA@EXAMPLE.COM",
             "first_name": "Ana", "last_name": "Silva"},
            {"client_id": "other", "shopify_customer_id": "999", "email": "other@example.com"}
        ]
        with patch.object(rc, "resolve_commerce_provider", AsyncMock(return_value={"provider": "shopify"})), \
             patch.object(rc, "_paged", AsyncMock(return_value=(profiles, False))), \
             patch.object(rc, "sb_upsert", AsyncMock()) as upsert, \
             patch.object(rc, "encrypt_secret", side_effect=lambda val: "encrypted"):
            result = await rc.sync_existing_customers("roove")
        self.assertEqual(result["contacts_synchronized"], 1)
        rows = upsert.await_args.args[1]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["client_id"], "roove")
        self.assertNotIn("marketing_email_verified", rows[0])
        self.assertNotIn("marketing_whatsapp_verified", rows[0])
        self.assertEqual(rows[0]["email_ciphertext"], "encrypted")
        self.assertNotIn("ANA@EXAMPLE.COM", str(rows))

    async def test_fbits_existing_contacts(self):
        with patch.object(rc, "resolve_commerce_provider", AsyncMock(return_value={"provider": "fbits"})), \
             patch.object(rc, "_paged", AsyncMock(return_value=([
                 {"client_id": "curavino", "fbits_customer_id": "ABC", "name": "Maria", "phone": "(11) 99999-1234"}
             ], False))), patch.object(rc, "sb_upsert", AsyncMock()) as upsert, \
             patch.object(rc, "encrypt_secret", return_value="cipher"):
            result = await rc.sync_existing_customers("curavino")
        self.assertEqual(result["provider"], "fbits")
        self.assertEqual(result["contacts_synchronized"], 1)
        self.assertEqual(upsert.await_args.args[1][0]["phone_ciphertext"], "cipher")

    async def test_no_commerce_refuses_without_touching_tables(self):
        with patch.object(rc, "resolve_commerce_provider", AsyncMock(return_value={})), \
             patch.object(rc, "sb_select", AsyncMock()) as select:
            with self.assertRaises(rc.ContactSyncError):
                await rc.sync_existing_customers("ruah")
        select.assert_not_awaited()

    async def test_existing_contact_is_idempotent_by_source_identity(self):
        with patch.object(rc, "encrypt_secret", return_value="cipher"):
            a = rc._row("roove", "shopify", {"shopify_customer_id": "123", "email": "ana@example.com"})
            b = rc._row("roove", "shopify", {"shopify_customer_id": "123", "email": "ana+new@example.com"})
        self.assertEqual(a["identity_hash"], b["identity_hash"])
        self.assertNotEqual(rc._key("ruah", "shopify", "123"), a["identity_hash"])

    async def test_whatsapp_conversations_form_contact_base_without_opt_in(self):
        leads = {"available": True, "truncated": False, "leads": [
            {"phone_key": "a" * 32, "first_seen_at": "2026-10-01T13:00:00Z"},
            {"phone_key": "a" * 32, "first_seen_at": "2026-10-02T13:00:00Z"},
            {"phone_key": "b" * 32, "first_seen_at": "2026-10-03T13:00:00Z"},
        ]}
        with patch("services.whatsapp_sources.brand_leads", AsyncMock(return_value=leads)), \
             patch.object(rc, "sb_upsert", AsyncMock()) as upsert:
            result = await rc.sync_whatsapp_conversations("ruah")
        self.assertEqual(result["contacts_synchronized"], 2)
        rows = upsert.await_args.args[1]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["client_id"] == "ruah" for row in rows))
        self.assertTrue(all("marketing_whatsapp_verified" not in row for row in rows))
        self.assertTrue(all(row["phone_ciphertext"] is None for row in rows))
        self.assertNotIn("a" * 32, str(rows))

    async def test_whatsapp_truncated_history_rejected_before_persist(self):
        with patch("services.whatsapp_sources.brand_leads", AsyncMock(return_value={
            "available": True, "truncated": True, "leads": [{"phone_key": "a" * 32}]
        })), patch.object(rc, "sb_upsert", AsyncMock()) as upsert:
            with self.assertRaises(rc.ContactSyncError) as caught:
                await rc.sync_whatsapp_conversations("ruah")
        self.assertEqual(caught.exception.status, 409)
        upsert.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
