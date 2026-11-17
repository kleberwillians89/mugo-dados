"""Listas do Relacionamento: LGPD, tenant, consentimento e minimização."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import relationship_lists as rl
from services import email_marketing as em

LIST_ID = "5d9368b5-f6b5-443e-9eac-ce3651454f20"


class ListTests(unittest.IsolatedAsyncioTestCase):
    async def test_import_saves_only_valid_opted_in_members_as_hashes(self):
        ana = em.email_hash("ana@exemplo.com")
        bia = em.email_hash("bia@exemplo.com")
        contacts = [
            {"hash": ana, "consent": True},
            {"hash": bia, "consent": False},
        ]
        upsert = AsyncMock()
        with patch.object(rl, "get_list", AsyncMock(return_value={"id": LIST_ID})), \
             patch.object(em, "load_contacts", AsyncMock(return_value=("shopify", contacts))), \
             patch.object(em, "suppressed", AsyncMock(return_value=set())), \
             patch.object(rl, "sb_upsert", upsert):
            result = await rl.add_members("roove", LIST_ID,
                                          ["ana@exemplo.com", "ana@exemplo.com", "bia@exemplo.com"])
        self.assertEqual(result, {"accepted": 1, "duplicates_in_input": 1, "not_eligible": 1})
        rows = upsert.await_args.args[1]
        self.assertEqual(rows, [{"client_id": "roove", "list_id": LIST_ID, "email_hash": ana}])
        self.assertNotIn("email", rows[0])

    async def test_import_respects_existing_suppression(self):
        ana = em.email_hash("ana@exemplo.com")
        with patch.object(rl, "get_list", AsyncMock(return_value={"id": LIST_ID})), \
             patch.object(em, "load_contacts", AsyncMock(return_value=("shopify", [{"hash": ana, "consent": True}]))), \
             patch.object(em, "suppressed", AsyncMock(return_value={ana})), \
             patch.object(rl, "sb_upsert", AsyncMock()) as upsert:
            result = await rl.add_members("roove", LIST_ID, ["ana@exemplo.com"])
        self.assertEqual(result["not_eligible"], 1)
        upsert.assert_not_awaited()

    async def test_cross_tenant_list_cannot_be_used(self):
        with patch.object(rl, "sb_select", AsyncMock(return_value=[])):
            with self.assertRaises(rl.ListError) as caught:
                await rl.member_hashes("ruah", LIST_ID)
        self.assertEqual(caught.exception.status, 404)

    async def test_history_never_queries_without_tenant(self):
        with patch.object(rl, "sb_select", AsyncMock(return_value=[])) as select:
            self.assertEqual(await rl.contact_email_history("roove", "ana@exemplo.com"), [])
        filters = select.await_args.kwargs["filters"]
        self.assertEqual(filters["client_id"], "eq.roove")
        self.assertEqual(filters["email_hash"], f"eq.{em.email_hash('ana@exemplo.com')}")
        self.assertNotIn("ana@exemplo.com", str(select.await_args))

    async def test_invalid_member_import_fails_without_write(self):
        with patch.object(rl, "get_list", AsyncMock(return_value={"id": LIST_ID})), \
             patch.object(rl, "sb_upsert", AsyncMock()) as upsert:
            with self.assertRaises(rl.ListError):
                await rl.add_members("roove", LIST_ID, ["nao-e-email"])
            upsert.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
