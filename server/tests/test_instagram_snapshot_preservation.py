from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import instagram_sync


class InstagramSnapshotPreservationTests(unittest.IsolatedAsyncioTestCase):
    async def run_sync(self, *, kpis=None, media_insights=None, comments_error=False, profile_error=False, media_error=False, story_error=False):
        self.previous = {"client_id": "tenant-a", "reach_day": 120, "profile_views_day": 30,
                         "insights_json": {"reach": 90, "shares": 12}}
        with (
            patch.object(instagram_sync, "fetch_profile", AsyncMock(return_value={})),
            patch.object(instagram_sync, "fetch_media_list", AsyncMock(return_value=[{"id": "m1", "comments_count": 1}])),
            patch.object(instagram_sync, "fetch_kpis_total_value", AsyncMock(side_effect=RuntimeError("profile insights failed") if profile_error else None, return_value=kpis or {"reach": 4, "available_metrics": ["reach"]})),
            patch.object(instagram_sync, "fetch_media_insights", AsyncMock(side_effect=RuntimeError("media insights failed") if media_error else None, return_value=media_insights or {"reach": 5})),
            patch.object(instagram_sync, "fetch_media_comments", AsyncMock(side_effect=RuntimeError("comments failed") if comments_error else None, return_value=[])),
            patch.object(instagram_sync, "fetch_stories", AsyncMock(return_value=[{"id": "story-1"}] if story_error else [])),
            patch.object(instagram_sync, "fetch_story_insights", AsyncMock(side_effect=RuntimeError("story insights failed"))),
            patch.object(instagram_sync, "sb_get_one", AsyncMock(return_value=self.previous)) as read,
            patch.object(instagram_sync, "sb_upsert", AsyncMock()) as write,
        ):
            result = await instagram_sync._run_sync_for_client_and_ig(client_id="tenant-a", connection_id="conn-a", ig_user_id="ig-a", access_token="test", limit=40)
        return result, read, write

    async def test_total_profile_insights_failure_does_not_overwrite_snapshot(self):
        result, _, write = await self.run_sync(kpis={"available_metrics": [], "unavailable_metrics": ["reach", "views"]})
        self.assertFalse(result["snapshot_saved"])
        self.assertFalse(result["block_status"]["insights"]["ok"])
        self.assertNotIn("ig_profile_snapshots", [call.args[0] for call in write.await_args_list])

    async def test_partial_profile_failure_preserves_previous_metric_in_same_tenant(self):
        _, read, write = await self.run_sync(kpis={"reach": 4, "available_metrics": ["reach"], "unavailable_metrics": ["profile_views"]})
        snapshot = next(call.args[1][0] for call in write.await_args_list if call.args[0] == "ig_profile_snapshots")
        self.assertEqual(snapshot["reach_day"], 4)
        self.assertEqual(snapshot["profile_views_day"], 30)
        self.assertEqual(snapshot["client_id"], "tenant-a")
        self.assertIn("client_id=eq.tenant-a", read.await_args.args[1])

    async def test_partial_media_failure_preserves_unavailable_metrics(self):
        _, read, write = await self.run_sync(media_insights={"reach": 5, "available_metrics": ["reach"], "unavailable_metrics": ["shares"]})
        media = next(call.args[1][0] for call in write.await_args_list if call.args[0] == "ig_media")
        self.assertEqual(media["insights_json"]["shares"], 12)
        self.assertEqual(media["insights_json"]["reach"], 5)
        self.assertIn("client_id=eq.tenant-a", read.await_args.args[1])
        self.assertIn("media_id=eq.m1", read.await_args.args[1])

    async def test_comments_failure_does_not_discard_insights(self):
        result, _, write = await self.run_sync(comments_error=True)
        media = next(call.args[1][0] for call in write.await_args_list if call.args[0] == "ig_media")
        self.assertEqual(media["insights_json"]["reach"], 5)
        self.assertTrue(result["snapshot_saved"])

    async def test_profile_exception_preserves_snapshot(self):
        result, _, write = await self.run_sync(profile_error=True)
        self.assertFalse(result["snapshot_saved"])
        self.assertNotIn("ig_profile_snapshots", [call.args[0] for call in write.await_args_list])

    async def test_media_exception_preserves_existing_row(self):
        result, _, write = await self.run_sync(media_error=True)
        self.assertEqual(result["media_saved"], 0)
        self.assertNotIn("ig_media", [call.args[0] for call in write.await_args_list])

    async def test_all_media_metrics_unavailable_preserves_existing_row(self):
        result, _, write = await self.run_sync(media_insights={"available_metrics": [], "unavailable_metrics": ["reach"]})
        self.assertEqual(result["media_saved"], 0)
        self.assertNotIn("ig_media", [call.args[0] for call in write.await_args_list])

    async def test_story_exception_preserves_existing_story(self):
        result, _, write = await self.run_sync(story_error=True)
        rows = next(call.args[1] for call in write.await_args_list if call.args[0] == "ig_media")
        self.assertEqual([row["media_id"] for row in rows], ["m1"])
        self.assertTrue(result["warnings"])
