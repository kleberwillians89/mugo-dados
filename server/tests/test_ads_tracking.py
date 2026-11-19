"""UTM parameters are safe, optional and transmitted in provider payloads."""
import sys
import unittest
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.ads_tracking import clean_tracking, tracking_suffix
from services import meta_ad_publisher as meta, google_ad_drafts as google, google_ad_publisher as google_pub
from services.studio_calendar import StudioError

class TrackingTests(unittest.TestCase):
    def test_order_and_url_encoding(self):
        normalized=clean_tracking({"utm_campaign":"Black Friday Roove",
          "utm_source":"meta","utm_medium":"paid social",
          "secret":"must-not-be-accepted"})
        self.assertEqual(tracking_suffix(normalized),
          "utm_source=meta&utm_medium=paid+social&utm_campaign=Black+Friday+Roove")
        self.assertNotIn("secret",normalized)

    def test_reject_newlines_types_and_macros(self):
        for value in ({"utm_campaign":"test\nInjected"}, {"utm_source":99},
                      {"utm_source":"{dangerous_macro}"}):
            with self.subTest(value=value),self.assertRaises(ValueError):
                clean_tracking(value)

    def test_meta_persists_utm_without_modifying_target_url(self):
        p=meta.clean_payload({"name":"Black Friday","objective":"trafego","daily_budget":20,
          "tracking":{"utm_source":"meta","utm_campaign":"roove_bf"},
          "ad":{"link":"https://roove.com.br/landing"}},today=date(2026,11,18))
        self.assertEqual(p["tracking"]["utm_campaign"],"roove_bf")
        self.assertEqual(p["ad"]["link"],"https://roove.com.br/landing")

    def test_google_campaign_final_url_suffix_is_set(self):
        raw={"platform":"google_ads","name":"Search Roove","objective":"leads",
             "daily_budget":30,"start_date":"2026-11-20","end_date":"2026-11-30",
             "final_url":"https://roove.com.br/landing","locations":["Sao Paulo"],
             "keywords":["skinwear"],"headlines":["Roove","Skinwear","Conheça Roove"],
             "descriptions":["Moda premium","Compre online"],
             "tracking":{"utm_source":"google","utm_medium":"cpc","utm_campaign":"black_friday"},
             "contains_eu_political_advertising":False}
        payload=google.clean_payload(raw)
        ops=google_pub._operations("123","draft",payload,[])
        campaign=ops[1]["campaignOperation"]["create"]
        self.assertEqual(campaign["finalUrlSuffix"],
             "utm_source=google&utm_medium=cpc&utm_campaign=black_friday")
        self.assertEqual(ops[-1]["adGroupAdOperation"]["create"]["ad"]["finalUrls"],
             ["https://roove.com.br/landing"])
        self.assertEqual(campaign["status"],"PAUSED")

    def test_invalid_tracking_is_rejected_by_both_campaigns(self):
        with self.assertRaises(StudioError):
            meta.clean_payload({"name":"x","daily_budget":20,
              "tracking":{"utm_source":"bad\nsource"}},today=date(2026,11,18))
        with self.assertRaises(StudioError):
            google.clean_payload({"name":"x","daily_budget":20,
              "start_date":"2026-11-20","end_date":"2026-11-30",
              "tracking":{"utm_campaign":"bad\nsource"}})

if __name__=="__main__":unittest.main()
