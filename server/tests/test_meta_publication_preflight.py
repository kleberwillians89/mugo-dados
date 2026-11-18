"""Read-only Meta publication preflight: tenant resolution, pixel and page checks."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import meta_ad_publisher as pub
from services.studio_calendar import StudioError


class MetaPublicationPreflightTests(unittest.IsolatedAsyncioTestCase):
    async def test_ready_lead_campaign_reads_connected_meta_account_and_pixel(self):
        async def graph(method, path, *, token, params=None, data=None):
            if path == "/act_123":
                return {"name": "Roove Ads", "account_status": 1}
            if path == "/act_123/adspixels":
                return {"data": [{"id": "p1", "name": "Roove Pixel"}]}
            raise AssertionError(path)
        with patch.object(pub, "_ad_account", new_callable=AsyncMock,
                          return_value={"act":"act_123", "token":"secret"}), \
             patch.object(pub, "_graph", side_effect=graph) as graph_mock, \
             patch("services.ig_engagement.credentials", new_callable=AsyncMock,
                   return_value={"page_id":"100", "ig_user_id":"200"}):
            data = await pub.publication_preflight("roove", "leads")
        self.assertTrue(data["ready"])
        self.assertEqual({x["key"] for x in data["checks"]}, {"account","page","instagram","pixel"})
        self.assertTrue(all(x["ok"] for x in data["checks"]))
        self.assertNotIn("secret", str(data))
        self.assertNotIn("act_123", str(data))
        self.assertEqual(graph_mock.call_count, 2)

    async def test_missing_pixel_blocks_lead_publication(self):
        async def graph(method, path, *, token, params=None, data=None):
            return {"name": "Roove", "account_status": 1} if path == "/act_123" else {"data": []}
        with patch.object(pub, "_ad_account", new_callable=AsyncMock,
                          return_value={"act":"act_123", "token":"secret"}), \
             patch.object(pub, "_graph", side_effect=graph), \
             patch("services.ig_engagement.credentials", new_callable=AsyncMock,
                   return_value={"page_id":"100", "ig_user_id":""}):
            result = await pub.publication_preflight("roove", "leads")
        self.assertFalse(result["ready"])
        self.assertFalse(next(c for c in result["checks"] if c["key"] == "pixel")["ok"])
        self.assertFalse(next(c for c in result["checks"] if c["key"] == "instagram")["ok"])

    async def test_missing_account_does_not_access_graph(self):
        with patch.object(pub, "_ad_account", new_callable=AsyncMock,
                          side_effect=StudioError("AD_ACCOUNT_MISSING")), \
             patch.object(pub, "_graph", new_callable=AsyncMock) as graph:
            result = await pub.publication_preflight("roove", "leads")
        self.assertFalse(result["ready"])
        graph.assert_not_awaited()

    async def test_pixel_not_required_for_traffic(self):
        with patch.object(pub, "_ad_account", new_callable=AsyncMock,
                          return_value={"act":"act_123", "token":"secret"}), \
             patch.object(pub, "_graph", new_callable=AsyncMock,
                          return_value={"name":"Roove", "account_status":1}) as graph, \
             patch("services.ig_engagement.credentials", new_callable=AsyncMock,
                   return_value={"page_id":"100", "ig_user_id":""}):
            result = await pub.publication_preflight("roove", "trafego")
        self.assertTrue(result["ready"])
        self.assertEqual(graph.await_count, 1)


if __name__ == "__main__":
    unittest.main()
