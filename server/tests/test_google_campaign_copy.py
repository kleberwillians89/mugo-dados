"""Google Search copies never recreate provider resources until separately confirmed."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import google_ad_drafts as drafts

BASE={"platform":"google_ads","name":"Roove Search","objective":"leads",
"daily_budget":30,"start_date":"2026-11-20","end_date":"2026-11-30",
"final_url":"https://www.roove.com.br","locations":["Sao Paulo"],
"keywords":["skinwear"],"headlines":["Roove","Moda","Skinwear"],
"descriptions":["Conheça a marca","Compre online"],"contains_eu_political_advertising":False}

class GoogleCampaignCopyTests(unittest.IsolatedAsyncioTestCase):
    async def test_published_google_campaign_duplicates_as_local_draft(self):
        previous={"id":"old","client_id":"roove","payload":BASE,"status":"publicada",
                  "meta_ids":{"campaign_id":"123","customer_id":"444"}}
        inserted={}
        async def fake_insert(table,data):
            inserted.update(data)
            return {"id":"new",**data,"meta_ids":{}}
        with patch.object(drafts,"owned",new_callable=AsyncMock,return_value=previous), \
             patch.object(drafts,"sb_insert",new_callable=AsyncMock,side_effect=fake_insert):
            new=await drafts.duplicate("roove","old","agency-user")
        self.assertEqual(new["id"],"new")
        self.assertEqual(new["status"],"rascunho")
        self.assertEqual(inserted["client_id"],"roove")
        self.assertEqual(inserted["created_by"],"agency-user")
        self.assertIn("cópia",new["payload"]["name"])
        self.assertNotIn("meta_ids",inserted)

if __name__=="__main__":unittest.main()
