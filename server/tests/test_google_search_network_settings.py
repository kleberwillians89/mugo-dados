"""Google Search network selection is saved and sent to the Ads API, PAUSED."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import google_ad_drafts, google_ad_publisher
from services.studio_calendar import StudioError

BASE = {"platform":"google_ads","name":"Roove Search","objective":"leads","daily_budget":30,
        "start_date":"2026-11-20","end_date":"2026-11-30",
        "final_url":"https://roove.com.br","locations":["Sao Paulo"],
        "keywords":["skinwear"],"headlines":["Roupas com cuidado","Nova coleção","Conheça Roove"],
        "descriptions":["Conforto para sua rotina","Conheça o site"],
        "contains_eu_political_advertising":False}

class GoogleNetworkSelectionTests(unittest.TestCase):
    def test_search_only_is_default(self):
        p=google_ad_drafts.clean_payload(BASE)
        self.assertEqual(p["networks"],{"google_search":True,"search_partners":False,"display_network":False})
        campaign=google_ad_publisher._operations("123","draft",p,["geo/1"])[1]["campaignOperation"]["create"]
        self.assertEqual(campaign["networkSettings"],{"targetGoogleSearch":True,"targetSearchNetwork":False,"targetContentNetwork":False})
        self.assertEqual(campaign["status"],"PAUSED")

    def test_optional_networks_reach_google_payload(self):
        p=google_ad_drafts.clean_payload({**BASE,"networks":{
            "google_search":True,"search_partners":True,"display_network":True}})
        campaign=google_ad_publisher._operations("123","draft",p,[])[1]["campaignOperation"]["create"]
        self.assertTrue(campaign["networkSettings"]["targetSearchNetwork"])
        self.assertTrue(campaign["networkSettings"]["targetContentNetwork"])

    def test_reject_unsupported_network_values(self):
        with self.assertRaises(StudioError):
            google_ad_drafts.clean_payload({**BASE,"networks":{"google_search":False}})
        with self.assertRaises(StudioError):
            google_ad_drafts.clean_payload({**BASE,"networks":{"search_partners":"yes"}})

if __name__ == "__main__": unittest.main()
