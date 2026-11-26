"""Meta campaign management: duplicate drafts safely and read current delivery only."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import meta_ad_publisher as pub
from services.studio_calendar import StudioError

class CampaignManagementTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_creates_only_local_draft_without_provider_ids(self):
        old = {"id": "old", "client_id": "roove", "status": "publicada",
               "month": "2026-11-01", "source_campaign": "Black Friday",
               "meta_ids": {"campaign_id": "123", "ad_id": "789"},
               "payload": {"name":"Black Friday Roove","objective":"leads",
                           "daily_budget":30,"ad":{"primary_text":"Teste"}}}
        captured = {}
        async def insert(table, row):
            captured.update(row)
            return {**row,"id":"new","meta_ids":{}}
        with patch.object(pub,"_draft",new_callable=AsyncMock,return_value=old), \
             patch.object(pub,"sb_insert",new_callable=AsyncMock,side_effect=insert):
            new = await pub.duplicate_draft("roove","old","agency-user")
        self.assertEqual(new["status"],"rascunho")
        self.assertEqual(captured["client_id"],"roove")
        self.assertEqual(captured["created_by"],"agency-user")
        self.assertNotIn("meta_ids",captured)
        self.assertIn("cópia",new["payload"]["name"])
        self.assertNotEqual(new["id"],old["id"])

    async def test_delivery_reads_owned_objects_and_does_not_mutate(self):
        draft={"id":"own","client_id":"roove","status":"publicada",
               "meta_ids":{"ad_account_id":"act_444",
                           "campaign_id":"111","adset_id":"222","ad_id":"333"}}
        reads=[]
        async def graph(method, path, *, token, params=None, data=None):
            reads.append((method,path))
            return {"id":path.removeprefix("/"),"name":"Roove",
                    "account_id":"444","status":"PAUSED","effective_status":"PAUSED"}
        with patch.object(pub,"_draft",new_callable=AsyncMock,return_value=draft), \
             patch.object(pub,"_ad_account",new_callable=AsyncMock,
                          return_value={"act":"act_444","token":"private"}), \
             patch.object(pub,"_graph",new_callable=AsyncMock,side_effect=graph), \
             patch.object(pub,"sb_update",new_callable=AsyncMock) as update:
            result=await pub.live_delivery_status("roove","own")
        self.assertTrue(result["read_only"])
        self.assertEqual(set(result["objects"]),{"campaign_id","adset_id","ad_id"})
        self.assertEqual(reads,[("GET","/111"),("GET","/222"),("GET","/333")])
        self.assertNotIn("private",str(result))
        update.assert_not_awaited()

    async def test_refuses_provider_account_mismatch(self):
        draft={"id":"own","client_id":"roove","meta_ids":{"campaign_id":"111","ad_account_id":"act_999"}}
        with patch.object(pub,"_draft",new_callable=AsyncMock,return_value=draft), \
             patch.object(pub,"_ad_account",new_callable=AsyncMock,
                          return_value={"act":"act_444","token":"private"}), \
             patch.object(pub,"_graph",new_callable=AsyncMock) as graph:
            with self.assertRaises(StudioError):
                await pub.live_delivery_status("roove","own")
        graph.assert_not_awaited()

    async def test_unpublished_draft_does_not_call_meta(self):
        with patch.object(pub,"_draft",new_callable=AsyncMock,
                          return_value={"meta_ids":{}}), \
             patch.object(pub,"_graph",new_callable=AsyncMock) as graph:
            with self.assertRaises(StudioError):
                await pub.live_delivery_status("roove","own")
        graph.assert_not_awaited()

if __name__=="__main__":
    unittest.main()
