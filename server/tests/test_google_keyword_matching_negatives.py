"""Google Ads Search positive matching and campaign negatives remain paused."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import google_ad_drafts as drafts, google_ad_publisher as publisher
from services.studio_calendar import StudioError

BASE = {"platform":"google_ads","name":"Search Roove","objective":"leads",
        "daily_budget":30,"start_date":"2026-11-20","end_date":"2026-12-02",
        "final_url":"https://www.roove.com.br","locations":["São Paulo"],
        "keywords":["skinwear feminino"],"headlines":["Tecnologia têxtil","Moda premium","Roove"],
        "descriptions":["Skinwear com cuidado da pele","Conheça Roove"],
        "contains_eu_political_advertising":False}

class KeywordsTests(unittest.TestCase):
    def test_old_draft_defaults_to_phrase(self):
        clean=drafts.clean_payload(BASE)
        self.assertEqual(clean["keyword_match_type"],"PHRASE")
        self.assertEqual(clean["negative_keywords"],[])
        ops=publisher._operations("123","draft",clean,[])
        positive=[x["adGroupCriterionOperation"]["create"] for x in ops if "adGroupCriterionOperation" in x]
        self.assertEqual(positive[0]["keyword"]["matchType"],"PHRASE")

    def test_exact_and_negatives_are_sent_to_google(self):
        clean=drafts.clean_payload({**BASE,"keyword_match_type":"EXACT",
                 "negative_keywords":["grátis","usado","grátis"]})
        self.assertEqual(clean["negative_keywords"],["grátis","usado"])
        ops=publisher._operations("123","draft",clean,[])
        positive=[x["adGroupCriterionOperation"]["create"] for x in ops if "adGroupCriterionOperation" in x]
        negative=[x["campaignCriterionOperation"]["create"] for x in ops
                  if "campaignCriterionOperation" in x and x["campaignCriterionOperation"]["create"].get("negative")]
        self.assertEqual(positive[0]["keyword"],{"text":"skinwear feminino","matchType":"EXACT"})
        self.assertEqual(len(negative),2)
        self.assertEqual([x["keyword"]["text"] for x in negative],["grátis","usado"])
        self.assertTrue(all(x["negative"] for x in negative))
        self.assertEqual(ops[1]["campaignOperation"]["create"]["status"],"PAUSED")

    def test_invalid_match_type_is_rejected(self):
        with self.assertRaises(StudioError):
            drafts.clean_payload({**BASE,"keyword_match_type":"WILDCARD"})

if __name__=="__main__":
    unittest.main()
