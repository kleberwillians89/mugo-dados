from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import google_ads


class GoogleAdsPersistedReportTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_is_read_first_and_zero_spend_has_no_roas(self):
        context = google_ads.GoogleAdsContext("amalie", "00000000-0000-0000-0000-000000000001", "123", None)
        rows = [{
            "stat_date": "2026-08-04", "cost": 0, "impressions": 10, "clicks": 0,
            "conversions": 0, "conversion_value": 50,
        }]
        with patch.object(google_ads, "sb_select", AsyncMock(return_value=rows)) as select:
            report = await google_ads.build_google_ads_report(
                client_id="amalie", context=context, start="2026-08-01", end="2026-08-10",
            )
        select.assert_awaited_once()
        self.assertIsNone(report["totals"]["roas"])
        self.assertEqual(report["coverage"], {"covered_days": 1, "expected_days": 10, "is_partial": True})

    def test_gaql_result_maps_daily_campaign_metrics(self):
        context = google_ads.GoogleAdsContext("amalie", "conn", "123", None)
        row = google_ads._parse_result("amalie", context, {
            "segments": {"date": "2026-08-04"},
            "campaign": {"id": "99", "name": "Search"},
            "metrics": {"costMicros": "230000000", "impressions": "100", "clicks": "10", "ctr": 0.1, "conversions": 2, "conversionsValue": 500},
        })
        self.assertEqual(row["cost"], 230.0)
        self.assertEqual(row["cpc"], 23.0)
        self.assertEqual(row["campaign_id"], "99")
