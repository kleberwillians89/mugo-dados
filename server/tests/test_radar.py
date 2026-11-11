"""Tests for evidence-only Radar aggregation, no external network calls."""
import unittest
from unittest.mock import AsyncMock, patch

from server.routes import radar


class RadarTests(unittest.IsolatedAsyncioTestCase):
    def test_creator_digest_preserves_missing_data(self):
        rows = [{
            "id": "1", "network": "youtube", "handle": "canal", "followers": None,
            "engagement_rate": None, "profile_url": "javascript:alert(1)",
            "missing_fields": ["followers", "engagement_rate"],
        }]
        result = radar.creator_digest(rows)
        self.assertIsNone(result[0]["followers"])
        self.assertIsNone(result[0]["engagement_rate"])
        self.assertIsNone(result[0]["profile_url"])
        self.assertEqual(result[0]["missing_fields"], ["followers", "engagement_rate"])

    async def test_requires_client_membership_and_filters_linked_creators(self):
        with (
            patch.object(radar, "require_client_read", new_callable=AsyncMock, return_value="tenant-a") as auth,
            patch.object(radar.creators, "linked_ids", new_callable=AsyncMock, return_value={"creator-a"}) as linked,
            patch.object(radar.creators, "list_creators", new_callable=AsyncMock, return_value=[]) as listings,
            patch.object(radar, "_trends", new_callable=AsyncMock, return_value={"status": "empty", "items": []}),
        ):
            result = await radar.radar_overview("tenant-a", authorization="Bearer token")
        auth.assert_awaited_once_with("tenant-a", "Bearer token")
        linked.assert_awaited_once_with("tenant-a")
        self.assertEqual(listings.await_args.kwargs["only_ids"], {"creator-a"})
        self.assertEqual(result["client_id"], "tenant-a")
        self.assertEqual(result["trends"]["items"], [])

    async def test_empty_links_do_not_trigger_global_creator_listing(self):
        with (
            patch.object(radar, "require_client_read", new_callable=AsyncMock, return_value="tenant-b"),
            patch.object(radar.creators, "linked_ids", new_callable=AsyncMock, return_value=set()),
            patch.object(radar.creators, "list_creators", new_callable=AsyncMock) as listings,
            patch.object(radar, "_trends", new_callable=AsyncMock, return_value={"status": "empty", "items": []}),
        ):
            result = await radar.radar_overview("tenant-b")
        listings.assert_not_awaited()
        self.assertEqual(result["creators"], [])


if __name__ == "__main__":
    unittest.main()
