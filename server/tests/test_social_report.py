import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from services import social_report as sr
from services.studio_calendar import StudioError


def row(mid, ts, *, views=0, likes=0, kind="IMAGE", product="FEED"):
    return {"media_id": mid, "media_type": kind, "media_product_type": product, "timestamp": ts, "caption": f"post {mid}",
            "permalink": f"https://www.instagram.com/p/{mid}/", "insights_json": {"views": views, "reach": views, "likes": likes}}


class PureTests(unittest.TestCase):
    def test_month_windows_fit_meta_30_day_limit(self):
        self.assertEqual(sr.parse_month("2026-10"), date(2026, 10, 1))
        with self.assertRaises(StudioError):
            sr.parse_month("10/2026")
        wins = sr.windows(date(2026, 10, 1))
        self.assertEqual(len(wins), 2)
        self.assertTrue(all(b - a <= 30 * 86400 for a, b in wins))
        self.assertEqual(wins[0][1], wins[1][0])
        self.assertEqual(len(sr.windows(date(2026, 2, 1))), 1)
        self.assertEqual(sr.prev_month(date(2026, 1, 1)), date(2025, 12, 1))

    def test_audience_shapes(self):
        self.assertEqual(sr.gender({"F": 75, "M": 25, "U": 10}), {"homens": 25, "mulheres": 75})
        self.assertIsNone(sr.gender({}))
        ages = sr.top_ages({"18-24": 10, "25-34": 50, "35-44": 30, "45-54": 10})
        self.assertEqual([a["label"] for a in ages], ["18-24 anos", "25-34 anos", "35-44 anos"])
        cities = sr.top_cities({"São Paulo, São Paulo (state)": 60, "Rio de Janeiro, Rio de Janeiro (state)": 40})
        self.assertEqual(cities[0], {"label": "São Paulo", "pct": 60})

    def test_highlight_compares_to_typical_post_of_same_format(self):
        posts = [sr.post_view(row(str(i), "2026-10-05T15:00:00+0000", views=v, kind="VIDEO", product="REELS")) for i, v in enumerate([100, 200, 300, 3000])]
        best = sr.highlight(posts)
        self.assertEqual(best["media_id"], "3")
        self.assertEqual(best["typical_views"], 250)
        self.assertEqual(best["times_typical"], 12.0)
        self.assertIsNone(sr.highlight([]))
        self.assertEqual(sr.pct_change(150, 100), 50.0)
        self.assertIsNone(sr.pct_change(150, 0))

    def test_best_formats_need_two_posts(self):
        posts = [{"format": "reels", "views": 900}, {"format": "reels", "views": 1100}, {"format": "posts", "views": 200},
                 {"format": "posts", "views": 300}, {"format": "stories", "views": 5000}]
        self.assertEqual(sr.best_formats(posts), ["reels", "posts"])


class BuildTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_keeps_saved_insights_and_marks_missing_metrics(self):
        media = [row("a", "2026-10-03T15:00:00+0000", views=500, likes=40, kind="VIDEO", product="REELS"),
                 row("b", "2026-10-20T15:00:00+0000", views=100, likes=60),
                 row("late", "2026-11-01T12:00:00+0000", views=9999)]

        async def select(table, **kw):
            if table == "ig_media":
                return media if kw["filters"]["timestamp"].startswith("gte.2026-10") else []
            return [{"data": {}, "insights": ["Manter reels"]}]

        async def account(client, ig, token, metric, first, breakdown=None):
            if metric == "views" and breakdown:
                return {"FOLLOWER": 30, "NON_FOLLOWER": 70}
            if metric == "views":
                return 1000 if first.month == 10 else 800
            if metric == "follows_and_unfollows":
                return {"FOLLOWER": 12, "NON_FOLLOWER": 3}
            return None  # profile_views etc. sem dado

        upsert = AsyncMock()
        creds = {"ig_user_id": "ig1", "token": "t", "username": "origami"}
        with patch("services.ig_engagement.credentials", AsyncMock(return_value=creds)), \
             patch.object(sr, "sb_select", AsyncMock(side_effect=select)), patch.object(sr, "sb_upsert", upsert), \
             patch.object(sr, "_account_total", AsyncMock(side_effect=account)), \
             patch.object(sr, "_demographics", AsyncMock(return_value={"F": 3, "M": 1})), \
             patch.object(sr, "_media_follows", AsyncMock(side_effect=[4, None])), \
             patch.object(sr, "load", AsyncMock(return_value={"built": True})), \
             patch("services.posting_times.build_posting_times", AsyncMock(return_value={"best_slots": [{"weekday": "terça", "hours": "18h-21h"}]})):
            await sr.build("c1", "2026-10")
        saved = upsert.await_args.args[1][0]
        data = saved["data"]
        self.assertEqual(saved["insights"], ["Manter reels"])
        self.assertEqual(data["overview"]["views"], 1000)
        self.assertEqual(data["overview"]["views_change_pct"], 25.0)
        self.assertEqual(data["overview"]["non_follower_pct"], 70.0)
        self.assertEqual(data["overview"]["new_followers"], 12)
        self.assertIsNone(data["overview"]["profile_views"])
        self.assertEqual(data["overview"]["contents"], {"reels": 1, "posts": 1, "stories": 0})
        self.assertEqual(data["highlight"]["media_id"], "a")
        self.assertEqual([p["media_id"] for p in data["top"]["likes"]], ["b", "a"])
        self.assertEqual([p["media_id"] for p in data["top"]["follows"]], ["a"])
        self.assertEqual([p["media_id"] for p in data["top"]["engagement"]], ["b", "a"])
        self.assertEqual(data["audience"]["active"], [{"day": "terça", "hours": "18h-21h"}])
        self.assertEqual(data["month_label"], "outubro")

    async def test_save_insights_requires_built_report(self):
        with patch("services.ig_supabase.sb_update", AsyncMock(return_value=[])):
            with self.assertRaises(StudioError):
                await sr.save_insights("c1", "2026-10", ["x"], user_id="u")
        with patch("services.ig_supabase.sb_update", AsyncMock(return_value=[{}])) as upd:
            out = await sr.save_insights("c1", "2026-10", [" a ", "", "b"], user_id="u")
        self.assertEqual(out["insights"], ["a", "b"])
        self.assertEqual(upd.await_args.kwargs["filters"]["month"], "eq.2026-10")


if __name__ == "__main__":
    unittest.main()
