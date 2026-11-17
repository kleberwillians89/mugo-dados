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
             patch.object(rc, "sb_select", AsyncMock(return_value=profiles)), \
             patch.object(rc, "sb_upsert", AsyncMock()) as upsert, \
             patch.object(rc, "encrypt_secret", side_effect=lambda val: "encrypted"):
            result = await rc.sync_existing_customers("roove")
        self.assertEqual(result["contacts_synchronized"], 1)
        rows = upsert.await_args.args[1]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["client_id"], "roove")
        self.assertFalse(rows[0]["marketing_email_verified"])
        self.assertFalse(rows[0]["marketing_whatsapp_verified"])
        self.assertEqual(rows[0]["email_ciphertext"], "encrypted")
        self.assertNotIn("ANA@EXAMPLE.COM", str(rows))

    async def test_fbits_existing_contacts(self):
        with patch.object(rc, "resolve_commerce_provider", AsyncMock(return_value={"provider": "fbits"})), \
             patch.object(rc, "sb_select", AsyncMock(return_value=[
                 {"client_id": "curavino", "fbits_customer_id": "ABC", "name": "Maria", "phone": "(11) 99999-1234"}
             ])), patch.object(rc, "sb_upsert", AsyncMock()) as upsert, \
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
        a = rc._row("roove", "shopify", {"shopify_customer_id": "123", "email": "ana@example.com"})
        b = rc._row("roove", "shopify", {"shopify_customer_id": "123", "email": "ana+new@example.com"})
        self.assertEqual(a["identity_hash"], b["identity_hash"])
        self.assertNotEqual(rc._key("ruah", "shopify", "123"), a["identity_hash"])


if __name__ == "__main__":
    unittest.main()
