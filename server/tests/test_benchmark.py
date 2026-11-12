"""Benchmarking: Instagram público da marca x concorrentes (ritmo, interações, engajamento, share de atenção)."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import benchmark as bm
from services.studio_calendar import StudioError

NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)


def post(days_ago, likes, comments, url="u"):
    return {"timestamp": (NOW - timedelta(days=days_ago)).isoformat(), "likes": likes, "comments": comments, "url": url, "type": "REELS"}


class MetricsTests(unittest.TestCase):
    def test_numbers_of_one_profile(self):
        snap = {"handle": "roove", "is_brand": True, "followers": 10000,
                "posts": [post(2, 300, 20, "a"), post(10, 100, 0), post(40, 50, 10), post(50, None, 4)]}
        m = bm.ig_metrics(snap, days=30, now=NOW)
        self.assertEqual(m["posts_in_period"], 2)
        self.assertEqual(m["posts_per_week"], 0.5)  # 2 posts em 30 dias
        self.assertEqual(m["avg_interactions"], 121.0)  # (320 + 100 + 60 + 4) / 4
        self.assertEqual(m["engagement_rate"], 1.21)
        self.assertEqual(m["interactions_in_period"], 420)
        self.assertEqual(m["hidden_likes"], 1)
        self.assertEqual(m["top_post"], {"url": "a", "interactions": 320, "type": "REELS"})
        self.assertFalse(m["sampled"])

    def test_sample_that_does_not_cover_the_period_is_flagged(self):
        snap = {"handle": "x", "followers": 100, "posts": [post(i * 0.5, 10, 1) for i in range(bm.POSTS_PER_PROFILE)]}
        self.assertTrue(bm.ig_metrics(snap, days=30, now=NOW)["sampled"])

    def test_no_followers_or_posts_never_becomes_a_number(self):
        m = bm.ig_metrics({"handle": "x", "followers": None, "posts": []}, days=30, now=NOW)
        self.assertEqual((m["avg_interactions"], m["engagement_rate"], m["posts_per_week"]), (None, None, 0.0))

    def test_share_of_attention_and_brand_first(self):
        rows = bm.with_share([{"is_brand": False, "interactions_in_period": 300}, {"is_brand": True, "interactions_in_period": 100},
                              {"is_brand": False, "interactions_in_period": 600}])
        self.assertEqual([r["share"] for r in rows], [10.0, 60.0, 30.0])
        self.assertTrue(rows[0]["is_brand"])
        self.assertIsNone(bm.with_share([{"is_brand": True, "interactions_in_period": 0}])[0]["share"])


class RefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_collects_brand_and_competitors_and_isolates_failures(self):
        async def discovery(ig_user_id, token, handle, posts):
            if handle == "quebrado":
                raise RuntimeError("Perfil não é profissional")
            return {"followers": 5000, "media_count": 80, "posts": [{"url": "p", "timestamp": NOW.isoformat(), "likes": 10, "comments": 2, "type": "IMAGE", "views": None}]}
        upsert = AsyncMock()
        competitors = [{"id": "c1", "instagram_handle": "@Rival", "active": True}, {"id": "c2", "instagram_handle": "quebrado", "active": True},
                       {"id": "c3", "instagram_handle": None, "active": True}]
        with patch.object(bm, "latest_snapshots", AsyncMock(return_value=[])), \
             patch("services.creators._meta_credentials", AsyncMock(return_value=("ig1", "tok"))), \
             patch("services.creators.record_usage", AsyncMock()), \
             patch.object(bm, "_brand_handle", AsyncMock(return_value="roove")), \
             patch("services.creators_providers.meta_business_discovery", side_effect=discovery), \
             patch.object(bm, "sb_upsert", upsert):
            out = await bm.refresh_instagram("roove", competitors)
        self.assertEqual(out["updated"], 2)
        self.assertEqual(out["errors"][0]["handle"], "quebrado")
        rows = upsert.await_args.args[1]
        self.assertEqual(sorted(r["handle"] for r in rows), ["rival", "roove"])
        self.assertTrue(next(r for r in rows if r["handle"] == "roove")["is_brand"])
        self.assertNotIn("views", rows[0]["posts"][0])
        self.assertEqual(upsert.await_args.kwargs["on_conflict"], "client_id,handle,day")

    async def test_cooldown_and_no_handles(self):
        recent = [{"handle": "roove", "collected_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}]
        with patch.object(bm, "latest_snapshots", AsyncMock(return_value=recent)):
            with self.assertRaises(StudioError) as raised:
                await bm.refresh_instagram("roove", [])
        self.assertEqual(raised.exception.code, "BENCHMARK_COOLDOWN")
        with patch.object(bm, "latest_snapshots", AsyncMock(return_value=[])), \
             patch("services.creators._meta_credentials", AsyncMock(return_value=("ig1", "tok"))), \
             patch.object(bm, "_brand_handle", AsyncMock(return_value="roove")):
            with self.assertRaises(StudioError) as raised:
                await bm.refresh_instagram("roove", [{"id": "c1", "instagram_handle": None}])
        self.assertEqual(raised.exception.code, "BENCHMARK_NO_HANDLES")

    async def test_block_keeps_only_brand_and_active_competitors(self):
        snaps = [{"handle": "roove", "is_brand": True, "collected_at": None, "followers": 100, "posts": [post(1, 10, 0)]},
                 {"handle": "rival", "is_brand": False, "followers": 100, "posts": [post(1, 30, 0)]},
                 {"handle": "antigo", "is_brand": False, "followers": 100, "posts": [post(1, 99, 0)]}]
        with patch.object(bm, "latest_snapshots", AsyncMock(return_value=snaps)):
            out = await bm.instagram_block("roove", [{"name": "Rival", "instagram_handle": "@Rival", "active": True}], days=30)
        self.assertEqual([r["name"] for r in out["rows"]], ["Sua marca", "Rival"])
        self.assertEqual([r["share"] for r in out["rows"]], [25.0, 75.0])


if __name__ == "__main__":
    unittest.main()
