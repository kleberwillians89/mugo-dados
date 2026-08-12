import unittest
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services.ads_reconciliation import reconcile_ads_levels


class AdsReconciliationTests(unittest.TestCase):
    def test_may_account_campaign_and_ad_close_without_inflating_canonical_total(self):
        row = {"spend": 1452.50, "conversions": 8, "revenue": 5806.01, "clicks": 200, "impressions": 10000, "reach": 7000}
        result = reconcile_ads_levels([row], [row], [row])
        self.assertEqual(result["canonical_level"], "account")
        self.assertEqual(result["account"]["spend"], 1452.50)
        self.assertEqual(result["account"]["conversions"], 8)
        self.assertEqual(result["account"]["revenue"], 5806.01)
        self.assertEqual(result["delta_campaign"]["spend"], 0)
        self.assertEqual(result["delta_ad"]["revenue"], 0)
        self.assertNotIn("reach", result["compared_metrics"])

    def test_june_fixture_uses_account_once(self):
        row = {"spend": 7530.69, "conversions": 40, "revenue": 21413.26}
        result = reconcile_ads_levels([row], [row], [row])
        self.assertEqual(result["account"], {"spend": 7530.69, "clicks": 0, "impressions": 0, "conversions": 40, "revenue": 21413.26})

    def test_missing_account_is_unavailable_not_detail_fallback_or_zero(self):
        result = reconcile_ads_levels([], [{"spend": 10}], [{"spend": 10}])
        self.assertIsNone(result["canonical_level"])
        self.assertIsNone(result["account"])
        self.assertIsNone(result["delta_campaign"])
