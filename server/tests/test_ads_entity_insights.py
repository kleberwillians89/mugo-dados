from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import ads_sync  # noqa: E402


class EntityInsightsRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_zero_daily_delivery_does_not_repeat_all_days_request(self):
        catalog = [{"id": "ad-1", "creative": {"object_story_id": "page_post"}}]
        insights = AsyncMock(return_value=[])
        with (
            patch.object(ads_sync, "fetch_ad_catalog", AsyncMock(side_effect=[catalog, catalog])),
            patch.object(ads_sync, "fetch_entity_insights", insights),
        ):
            rows = await ads_sync._fetch_boosted_insight_rows(
                ad_account_id="act_1", access_token="token",
                since="2026-08-01", until="2026-08-10",
            )
        self.assertEqual(rows, [])
        self.assertEqual(insights.await_count, 1)
        self.assertEqual(insights.await_args.kwargs["time_increment"], 1)


if __name__ == "__main__":
    unittest.main()
