"""Meta placements and video publication use real Graph payloads, but remain PAUSED."""
import sys
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from datetime import date
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import meta_ad_publisher as pub
from services.studio_calendar import StudioError


class ManualMetaPlacementTests(unittest.TestCase):
    def test_instagram_only_does_not_include_facebook(self):
        p = pub.clean_payload({"name": "Black Friday", "objective": "leads", "daily_budget": 30,
            "placements": {"mode":"manual", "platforms":["instagram"],
                "instagram":["stream","story","reels"], "facebook":[]}}, today=date(2026,11,18))
        self.assertEqual(p["placements"]["platforms"], ["instagram"])
        self.assertEqual(p["placements"]["instagram"], ["stream","story","reels"])
        self.assertEqual(p["placements"]["facebook"], [])

    def test_invalid_manual_placements_are_rejected(self):
        for placements in [
            {"mode":"manual", "platforms":[], "instagram":[], "facebook":[]},
            {"mode":"manual", "platforms":["instagram"], "instagram":[], "facebook":[]},
            # Plataforma que não existe na Meta, e Audience Network ligada sem nenhum posicionamento.
            {"mode":"manual", "platforms":["tiktok"], "instagram":["stream"], "facebook":[]},
            {"mode":"manual", "platforms":["audience_network"], "audience_network":[], "instagram":["stream"], "facebook":[]},
            {"mode":"manual", "platforms":["instagram"], "instagram":["feed_inventado"], "facebook":[]},
        ]:
            with self.subTest(placements=placements), self.assertRaises(StudioError):
                pub.clean_placements(placements)

    def test_video_requires_video_url_not_image(self):
        p = pub.clean_payload({"name":"Reel", "objective":"trafego", "daily_budget":30,
          "ad":{"media_type":"video","video_url":"https://cdn.example.com/reel.mp4","primary_text":"Teste",
                "link":"https://roove.com.br"}},today=date(2026,11,18))
        self.assertNotIn("Vídeo", " ".join(pub.readiness(p)))
        p["ad"]["video_url"] = ""
        self.assertIn("vídeo", " ".join(pub.readiness(p)).lower())


class VideoPublishTests(unittest.IsolatedAsyncioTestCase):
    async def test_video_creates_paused_meta_ad_on_instagram_positions_only(self):
        p = {"name":"Roove Reel","objective":"trafego","daily_budget":30,
             "start_date":"2026-11-20","end_date":"2026-11-30",
             "placements":{"mode":"manual","platforms":["instagram"],
                "instagram":["reels","story"],"facebook":[]},
             "ad":{"media_type":"video","video_url":"https://cdn.example.com/video.mp4",
                 "primary_text":"Black Friday","headline":"Cupons",
                 "link":"https://www.roove.com.br/pages/your-first-skinwear-roove-first-access"}}
        row = {"id":"draft","client_id":"roove","status":"rascunho","payload":p,"meta_ids":{}}
        posted=[]
        async def graph(method,path,*,token,data=None,params=None):
            if method == "POST": posted.append((path,data))
            return {"id":str(len(posted))}
        with patch.object(pub,"_draft",new_callable=AsyncMock,return_value=row), \
             patch.object(pub,"_context",new_callable=AsyncMock,return_value={"act":"act_123","token":"token","page_id":"page1","ig_id":"ig1"}), \
             patch.object(pub,"_graph",side_effect=graph), \
             patch.object(pub,"_interest_ids",new_callable=AsyncMock,return_value=[]), \
             patch.object(pub,"_region_keys",new_callable=AsyncMock,return_value=[]), \
             patch.object(pub,"sb_update",new_callable=AsyncMock,return_value=[]):
            await pub.publish("roove","draft")
        self.assertEqual([x[0] for x in posted], ["/act_123/campaigns","/act_123/adsets","/act_123/advideos","/act_123/adcreatives","/act_123/ads"])
        self.assertTrue(all(data.get("status","PAUSED")=="PAUSED" for path,data in posted))
        target=json.loads(posted[1][1]["targeting"])
        self.assertEqual(target["publisher_platforms"],["instagram"])
        self.assertEqual(target["instagram_positions"],["reels","story"])
        self.assertNotIn("facebook_positions",target)
        story=json.loads(posted[3][1]["object_story_spec"])
        self.assertEqual(story["video_data"]["video_id"],"3")


if __name__ == "__main__": unittest.main()
