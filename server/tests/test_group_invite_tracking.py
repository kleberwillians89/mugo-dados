"""Two-path group invite tracking must not expose arbitrary redirects or tenant data."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import group_invite_tracking as tracking


class GroupTrackingTests(unittest.IsolatedAsyncioTestCase):
    def test_only_official_whatsapp_group_invites_accepted(self):
        valid="https://chat.whatsapp.com/I3SBELXVK5qCKRZEcgA7Ev?s=cl"
        self.assertEqual(tracking.validate_invite_url(valid),valid)
        for bad in ("https://evil.example.com/abc", "https://chat.whatsapp.com.evil.example/abc",
                    "http://chat.whatsapp.com/abcdef", "https://chat.whatsapp.com@evil.org/abc",
                    "https://chat.whatsapp.com/abc/extra", "javascript:alert(1)"):
            with self.subTest(bad=bad), self.assertRaises(tracking.GroupLinkError):
                tracking.validate_invite_url(bad)

    async def test_created_links_are_tenant_scoped_and_variants_independent(self):
        stored=[]
        async def insert(table,row):
            stored.append(row)
            return {"id":"uuid", **row, "click_count":0, "created_at":"2026-11-19"}
        with patch.object(tracking,"sb_select",new_callable=AsyncMock,return_value=[]), \
             patch.object(tracking,"sb_insert",new_callable=AsyncMock,side_effect=insert):
            direct=await tracking.create_link("ruah",{"campaign_key":"ruah_vip_2026","label":"Ruah direto",
                "variant":"direct","invite_url":"https://chat.whatsapp.com/AbcDEFG123"})
            signup=await tracking.create_link("ruah",{"campaign_key":"ruah_vip_2026","label":"Ruah cadastro",
                "variant":"post_signup","invite_url":"https://chat.whatsapp.com/AbcDEFG123"})
        self.assertEqual([d["variant"] for d in stored],["direct","post_signup"])
        self.assertEqual({d["client_id"] for d in stored},{"ruah"})
        self.assertNotEqual(direct["slug"],signup["slug"])
        self.assertNotIn("token_hash",str(direct))

    async def test_preview_only_click_does_not_claim_join(self):
        slug="01234567890123456789012345"
        redirect="https://chat.whatsapp.com/AbcDEFG123"
        with patch.object(tracking,"sb_rpc",new_callable=AsyncMock,
                          return_value=[{"destination_url":redirect,"campaign":"ruah_vip_2026",
                                         "link_variant":"direct"}]) as rpc:
            result=await tracking.destination_for_click(slug)
        self.assertEqual(result,redirect)
        self.assertEqual(rpc.await_args.args[0],"register_group_invite_click")
        self.assertEqual(rpc.await_args.args[1],{"p_slug":slug})

    async def test_slug_not_found_is_404(self):
        with patch.object(tracking,"sb_rpc",new_callable=AsyncMock,return_value=[]):
            with self.assertRaises(tracking.GroupLinkError) as cm:
                await tracking.destination_for_click("01234567890123456789012345")
        self.assertEqual(cm.exception.status,404)

    async def test_link_list_filters_tenant(self):
        with patch.object(tracking,"sb_select",new_callable=AsyncMock,return_value=[]) as select:
            await tracking.list_links("ruah")
        self.assertEqual(select.await_args.kwargs["filters"],{"client_id":"eq.ruah"})

    async def test_link_creation_rejects_untrusted_destination_without_write(self):
        with patch.object(tracking,"sb_insert",new_callable=AsyncMock) as insert:
            with self.assertRaises(tracking.GroupLinkError):
                await tracking.create_link("ruah",{"campaign_key":"ruah_vip_2026","label":"Grupo VIP",
                   "variant":"direct","invite_url":"https://other.com/group"})
        insert.assert_not_awaited()


if __name__=="__main__":
    unittest.main()
