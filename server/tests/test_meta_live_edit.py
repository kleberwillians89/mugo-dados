"""Mídia On live edits: no Meta actions without confirmation and tenant scoping."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unittest
from unittest.mock import AsyncMock, patch

from services import meta_ad_publisher as pub


class LiveBudgetEditTests(unittest.IsolatedAsyncioTestCase):
    async def test_budget_confirmed_by_meta_before_persist(self):
        row = {"id": "draft1", "client_id": "ruah", "status": "publicada",
               "payload": {"name": "Campanha", "daily_budget": 30, "ad": {}},
               "meta_ids": {"campaign_id": "100", "ad_account_id": "act_200"}}
        calls = []

        async def graph(method, path, *, token, data=None, params=None):
            calls.append((method, path, data))
            if method == "POST":
                return {"success": True}
            return {"id": "100", "account_id": "200", "daily_budget": "4500" if any(c[0] == "POST" for c in calls) else "3000"}

        with patch.object(pub, "_draft", AsyncMock(return_value=row)), \
             patch.object(pub, "_ad_account", AsyncMock(return_value={"act": "act_200", "token": "private"})), \
             patch.object(pub, "_graph", graph), \
             patch.object(pub, "sb_update", AsyncMock(return_value=[{**row, "payload": {**row["payload"], "daily_budget": 45}}])) as saved:
            result = await pub.edit_live_budget("ruah", "draft1", 45)
        self.assertTrue(result["meta_confirmed"])
        self.assertEqual(result["budget_level"], "campaign")
        self.assertIn(("POST", "/100", {"daily_budget": "4500"}), calls)
        self.assertEqual(saved.await_args.kwargs["filters"]["client_id"], "eq.ruah")

    async def test_meta_mismatch_prevents_local_persist(self):
        row = {"id": "draft1", "status": "publicada", "payload": {"daily_budget": 30},
               "meta_ids": {"campaign_id": "100", "ad_account_id": "act_200"}}

        async def graph(method, path, *, token, data=None, params=None):
            return {"account_id": "200", "daily_budget": "3000"} if method == "GET" else {"success": True}

        persist = AsyncMock()
        with patch.object(pub, "_draft", AsyncMock(return_value=row)), \
             patch.object(pub, "_ad_account", AsyncMock(return_value={"act": "act_200", "token": "private"})), \
             patch.object(pub, "_graph", graph), patch.object(pub, "sb_update", persist):
            with self.assertRaises(pub.StudioError):
                await pub.edit_live_budget("ruah", "draft1", 45)
        persist.assert_not_awaited()

    async def test_other_account_rejected_before_write(self):
        row = {"id": "draft1", "status": "publicada", "payload": {"daily_budget": 30},
               "meta_ids": {"campaign_id": "100", "ad_account_id": "act_other"}}
        graph = AsyncMock()
        with patch.object(pub, "_draft", AsyncMock(return_value=row)), \
             patch.object(pub, "_ad_account", AsyncMock(return_value={"act": "act_200", "token": "private"})), \
             patch.object(pub, "_graph", graph):
            with self.assertRaises(pub.StudioError):
                await pub.edit_live_budget("ruah", "draft1", 45)
        graph.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
