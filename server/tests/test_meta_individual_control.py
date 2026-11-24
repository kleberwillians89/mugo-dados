"""Mídia On: per-object control must never cross campaign or tenant."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import AsyncMock, patch
from services import meta_ad_publisher as pub

ROW = {"id": "draft", "status": "publicada", "payload": {},
       "meta_ids": {"campaign_id": "123456789", "ad_account_id": "act_987654321"}}
ACCOUNT = {"act": "act_987654321", "token": "test-token"}


class MetaIndividualControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_structure_reads_current_meta_objects(self):
        async def graph(method, path, *, token, params=None, data=None):
            if path.endswith("/adsets"):
                return {"data": [{"id": "111111111", "name": "Conjunto A",
                                  "campaign_id": "123456789", "status": "PAUSED",
                                  "effective_status": "PAUSED"}]}
            if path.endswith("/ads"):
                return {"data": [{"id": "222222222", "name": "Anúncio A",
                                  "campaign_id": "123456789", "adset_id": "111111111",
                                  "status": "PAUSED", "effective_status": "PAUSED"}]}
            return {"id": "123456789", "account_id": "987654321", "effective_status": "ACTIVE"}
        with patch.object(pub, "_draft", AsyncMock(return_value=ROW)), \
             patch.object(pub, "_ad_account", AsyncMock(return_value=ACCOUNT)), \
             patch.object(pub, "_graph", graph):
            data = await pub.live_campaign_structure("ruah", "draft")
        self.assertEqual([r["id"] for r in data["adsets"]], ["111111111"])
        self.assertEqual([r["id"] for r in data["ads"]], ["222222222"])
        self.assertTrue(data["read_only"])

    async def test_wrong_ad_cannot_be_activated(self):
        async def graph(method, path, *, token, params=None, data=None):
            if path.endswith("/ads"):
                return {"data": [{"id": "222222222", "campaign_id": "123456789"}]}
            return {"id": "123456789", "account_id": "987654321"}
        g = AsyncMock(side_effect=graph)
        with patch.object(pub, "_draft", AsyncMock(return_value=ROW)), \
             patch.object(pub, "_ad_account", AsyncMock(return_value=ACCOUNT)), \
             patch.object(pub, "_graph", g):
            with self.assertRaises(pub.StudioError):
                await pub.change_live_object_status(
                    "ruah", "draft", level="ad", object_id="333333333", active=True)
        self.assertFalse(any(c.args[0] == "POST" for c in g.await_args_list))

    async def test_ad_status_write_is_verified(self):
        calls = []
        async def graph(method, path, *, token, params=None, data=None):
            calls.append((method, path, data))
            if path.endswith("/ads"):
                return {"data": [{"id": "222222222", "campaign_id": "123456789",
                                  "status": "PAUSED"}]}
            if method == "POST":
                return {"success": True}
            if path == "/222222222":
                return {"id": "222222222", "status": "ACTIVE",
                        "effective_status": "CAMPAIGN_PAUSED"}
            return {"id": "123456789", "account_id": "987654321"}
        with patch.object(pub, "_draft", AsyncMock(return_value=ROW)), \
             patch.object(pub, "_ad_account", AsyncMock(return_value=ACCOUNT)), \
             patch.object(pub, "_graph", graph):
            result = await pub.change_live_object_status(
                "ruah", "draft", level="ad", object_id="222222222", active=True)
        self.assertTrue(result["meta_confirmed"])
        self.assertEqual(result["effective_status"], "CAMPAIGN_PAUSED")
        self.assertIn(("POST", "/222222222", {"status": "ACTIVE"}), calls)

    async def test_adset_budget_changes_only_owned_set_and_reads_back(self):
        calls = []
        async def graph(method, path, *, token, params=None, data=None):
            calls.append((method, path, data))
            if path.endswith("/adsets"):
                return {"data": [{"id": "111111111", "campaign_id": "123456789", "daily_budget": "2000"},
                                 {"id": "222222222", "campaign_id": "123456789", "daily_budget": "3500"}]}
            if method == "POST":
                return {"success": True}
            if path == "/111111111":
                return {"id": "111111111", "campaign_id": "123456789", "daily_budget": "2500"}
            return {"id": "123456789", "account_id": "987654321"}
        with patch.object(pub, "_draft", AsyncMock(return_value=ROW)), \
             patch.object(pub, "_ad_account", AsyncMock(return_value=ACCOUNT)), \
             patch.object(pub, "_graph", graph):
            result = await pub.edit_live_adset_budget("ruah", "draft", adset_id="111111111", daily_budget=25.0)
        self.assertTrue(result["meta_confirmed"])
        self.assertEqual(result["daily_budget"], 2500)
        self.assertEqual([call for call in calls if call[0] == "POST"],
                         [("POST", "/111111111", {"daily_budget": "2500"})])

    async def test_adset_budget_rejects_foreign_set_and_cbo(self):
        for items, object_id in [
            ([{"id": "111111111", "campaign_id": "123456789", "daily_budget": "2000"}], "222222222"),
            ([{"id": "111111111", "campaign_id": "123456789", "daily_budget": None}], "111111111"),
        ]:
            async def graph(method, path, *, token, params=None, data=None):
                if path.endswith("/adsets"):
                    return {"data": items}
                return {"id": "123456789", "account_id": "987654321"}
            g = AsyncMock(side_effect=graph)
            with patch.object(pub, "_draft", AsyncMock(return_value=ROW)), \
                 patch.object(pub, "_ad_account", AsyncMock(return_value=ACCOUNT)), \
                 patch.object(pub, "_graph", g):
                with self.assertRaises(pub.StudioError):
                    await pub.edit_live_adset_budget("ruah", "draft", adset_id=object_id, daily_budget=25)
            self.assertFalse(any(call.args[0] == "POST" for call in g.await_args_list))

    async def test_adset_budget_readback_mismatch_is_failure(self):
        async def graph(method, path, *, token, params=None, data=None):
            if path.endswith("/adsets"):
                return {"data": [{"id": "111111111", "campaign_id": "123456789", "daily_budget": "2000"}]}
            if method == "POST":
                return {"success": True}
            if path == "/111111111":
                return {"id": "111111111", "campaign_id": "123456789", "daily_budget": "2000"}
            return {"id": "123456789", "account_id": "987654321"}
        with patch.object(pub, "_draft", AsyncMock(return_value=ROW)), \
             patch.object(pub, "_ad_account", AsyncMock(return_value=ACCOUNT)), \
             patch.object(pub, "_graph", graph):
            with self.assertRaises(pub.StudioError):
                await pub.edit_live_adset_budget("ruah", "draft", adset_id="111111111", daily_budget=25)

    async def test_insights_read_only_for_owned_ad(self):
        calls = []
        async def graph(method, path, *, token, params=None, data=None):
            calls.append((method, path, params))
            if path.endswith("/ads"):
                return {"data": [{"id": "222222222", "campaign_id": "123456789", "adset_id": "111111111"}]}
            if path.endswith("/insights"):
                return {"data": [{"spend": "25.40", "impressions": "1000", "reach": "900",
                                  "clicks": "50", "inline_link_clicks": "40", "ctr": "5.0",
                                  "cpc": "0.51", "cpm": "25.4", "frequency": "1.1",
                                  "actions": [{"action_type": "purchase", "value": "3"}]}]}
            return {"id": "123456789", "account_id": "987654321"}
        with patch.object(pub, "_draft", AsyncMock(return_value=ROW)), \
             patch.object(pub, "_ad_account", AsyncMock(return_value=ACCOUNT)), \
             patch.object(pub, "_graph", graph):
            result = await pub.live_object_insights("ruah", "draft", level="ad", object_id="222222222")
        self.assertEqual(result["link_clicks"], 40)
        self.assertEqual(result["spend"], 25.4)
        self.assertEqual(result["actions"][0]["value"], 3)
        self.assertEqual(result["date_preset"], "last_7d")
        self.assertTrue(result["read_only"])
        self.assertTrue(all(method == "GET" for method, _, _ in calls))
        self.assertEqual(calls[-1][2]["date_preset"], "last_7d")

    async def test_insights_foreign_ad_rejected_without_reading_metrics(self):
        calls = []
        async def graph(method, path, *, token, params=None, data=None):
            calls.append(path)
            if path.endswith("/ads"):
                return {"data": [{"id": "222222222", "campaign_id": "123456789"}]}
            return {"id": "123456789", "account_id": "987654321"}
        with patch.object(pub, "_draft", AsyncMock(return_value=ROW)), \
             patch.object(pub, "_ad_account", AsyncMock(return_value=ACCOUNT)), \
             patch.object(pub, "_graph", graph):
            with self.assertRaises(pub.StudioError):
                await pub.live_object_insights("ruah", "draft", level="ad", object_id="333333333")
        self.assertFalse(any(path.endswith("/insights") for path in calls))

    async def test_insights_empty_period_has_explicit_no_data(self):
        async def graph(method, path, *, token, params=None, data=None):
            if path.endswith("/adsets"):
                return {"data": [{"id": "111111111", "campaign_id": "123456789"}]}
            if path.endswith("/insights"):
                return {"data": []}
            return {"id": "123456789", "account_id": "987654321"}
        with patch.object(pub, "_draft", AsyncMock(return_value=ROW)), \
             patch.object(pub, "_ad_account", AsyncMock(return_value=ACCOUNT)), \
             patch.object(pub, "_graph", graph):
            result = await pub.live_object_insights("ruah", "draft", level="adset", object_id="111111111")
        self.assertFalse(result["has_data"])
        self.assertEqual(result["spend"], 0)

    async def test_foreign_account_fails_before_writes(self):
        account = {**ROW, "meta_ids": {"campaign_id": "123456789", "ad_account_id": "act_foreign"}}
        graph = AsyncMock()
        with patch.object(pub, "_draft", AsyncMock(return_value=account)), \
             patch.object(pub, "_ad_account", AsyncMock(return_value=ACCOUNT)), \
             patch.object(pub, "_graph", graph):
            with self.assertRaises(pub.StudioError):
                await pub.change_live_object_status(
                    "ruah", "draft", level="adset", object_id="111111111", active=False)
        graph.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
