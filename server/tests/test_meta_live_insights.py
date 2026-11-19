"""Tela Meta ao vivo: resultados, quebras, rankings, recomendações e permissões por função."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import AsyncMock, patch

from services import meta_live_insights as live


def buy(n, v):
    return {"actions": [{"action_type": "omni_purchase", "value": str(n)}, {"action_type": "purchase", "value": str(n)}],
            "action_values": [{"action_type": "omni_purchase", "value": str(v)}]}


class NumbersTests(unittest.TestCase):
    def test_results_do_not_double_count_purchases(self):
        r = live.results({"spend": "100", "ctr": "1.5", **buy(4, 400)})
        self.assertEqual((r["purchases"], r["revenue"], r["roas"], r["cost_per_purchase"]), (4, 400, 4.0, 25.0))

    def test_breakdown_shares(self):
        rows = [{"age": "25-34", "spend": "80", **buy(1, 100)}, {"age": "18-24", "spend": "20", **buy(3, 300)}]
        out = live.build_breakdown(rows, ("age",))
        self.assertEqual(out[0]["label"], "25-34")
        self.assertEqual((out[0]["spend_share"], out[0]["purchase_share"]), (80.0, 25.0))

    def test_rank_weighted_by_spend(self):
        ads = [{"quality_ranking": "ABOVE_AVERAGE", "spend": "90"}, {"quality_ranking": "BELOW_AVERAGE_10", "spend": "10"}]
        self.assertEqual(live._rank(ads, "quality_ranking")["label"], "acima da média")
        self.assertIsNone(live._rank([{"quality_ranking": "UNKNOWN"}], "quality_ranking"))

    def test_video_retention(self):
        v = live._video({"spend": "50", "video_play_actions": [{"action_type": "video_view", "value": "200"}],
                         "video_thruplay_watched_actions": [{"action_type": "video_view", "value": "50"}],
                         "video_p75_watched_actions": [{"action_type": "video_view", "value": "40"}]})
        self.assertEqual((v["p75"], v["cost_per_thruplay"]), (20.0, 1.0))


class RecommendationTests(unittest.TestCase):
    def test_fatigue_scale_and_audience(self):
        camp = lambda cid, roas, spend: {"id": cid, "name": cid, "status": "ACTIVE", "quality": {},  # noqa: E731
                                         "metrics": {"roas": roas, "spend": spend}}
        ads = [{"ad_name": "A", "campaign_id": "c1", "spend": "50", "impressions": "5000", "ctr": "0.4", "frequency": "4.2"},
               {"ad_name": "B", "spend": "50", "impressions": "5000", "ctr": "1.2", "frequency": "1.1"},
               {"ad_name": "C", "spend": "50", "impressions": "5000", "ctr": "1.0", "frequency": "1.3"}]
        age = [{"label": "45-54", "spend_share": 40.0, "purchase_share": 10.0}]
        out = live.recommendations([camp("c1", 1.0, 100), camp("c2", 4.0, 50)], ads, age, {"roas": 2.0, "spend": 150})
        self.assertEqual([r["kind"] for r in out], ["fatigue", "scale", "audience"])
        self.assertIn("frequência 4.2", out[0]["text"])

    def test_nothing_when_numbers_are_fine(self):
        self.assertEqual(live.recommendations([], [], [], {"roas": 0, "spend": 0}), [])


class PermissionTests(unittest.TestCase):
    def test_feature_states(self):
        paid = {"ads_read", "ads_management", "business_management"}
        organic = {"instagram_basic", "instagram_manage_insights", "pages_read_engagement", "pages_messaging"}
        states = {f["key"]: f for f in live.feature_status(paid, organic)}
        self.assertEqual(states["ads_reports"]["state"], "ok")
        self.assertEqual(states["direct"]["state"], "ok")  # basta uma das duas
        self.assertEqual(states["comments"]["missing"], ["instagram_manage_comments"])
        self.assertEqual(live.feature_status(None, None)[0]["state"], "not_connected")
        self.assertEqual(live.feature_status(set(), set())[0]["state"], "unknown")


class OverviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_overview_survives_missing_breakdowns(self):
        async def fake_paged(path, token, params, pages=4):
            if path.endswith("/campaigns"):
                return [{"id": "c1", "name": "BF", "effective_status": "ACTIVE", "daily_budget": "5000"}]
            if path.endswith("/ads"):
                return [{"id": "a1", "creative": {"thumbnail_url": "https://x/t.jpg", "title": "T"}}]
            if params.get("breakdowns"):
                raise live.StudioError("AD_PERMISSION_MISSING")
            if params.get("level") == "ad":
                return [{"ad_id": "a1", "campaign_id": "c1", "spend": "100", "impressions": "1000", "clicks": "20", **buy(2, 300)}]
            return [{"spend": "100", **buy(2, 300)}]
        live._CACHE.clear()
        with patch("services.meta_ad_publisher._ad_account", AsyncMock(return_value={"act": "act_1", "token": "t"})), \
             patch.object(live, "_paged", side_effect=fake_paged):
            out = await live.overview("roove", since="2026-11-01", until="2026-11-10")
        camp = out["campaigns"][0]
        self.assertEqual((camp["metrics"]["roas"], camp["daily_budget"], camp["creative"]["thumbnail"]), (3.0, 50.0, "https://x/t.jpg"))
        self.assertIn("age", out["unavailable"])
        self.assertEqual(out["breakdowns"]["age"], [])

    async def test_period_is_validated(self):
        with self.assertRaises(live.StudioError):
            await live.overview("roove", since="2026-01-01", until="2026-11-10")


if __name__ == "__main__":
    unittest.main()
