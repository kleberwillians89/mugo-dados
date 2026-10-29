from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import instagram_sync, posting_times
from services.posting_times import online_followers_by_hour, rank_slots, score_posts

START, END = date(2026, 9, 1), date(2026, 10, 31)


def post(ts, reach, *, product="FEED", media_type="IMAGE", interactions=10):
    return {"timestamp": ts, "media_product_type": product, "media_type": media_type,
            "insights_json": {"reach": reach, "total_interactions": interactions}}


class ScorePostsTests(unittest.TestCase):
    def test_converts_utc_to_sao_paulo_weekday_and_hour(self):
        # Sábado 01h UTC = sexta 22h em São Paulo.
        [p] = score_posts([post("2026-10-03T01:00:00+0000", 100)], start=START, end=END)
        self.assertEqual((p["weekday"], p["hour"]), (4, 22))

    def test_reach_index_is_relative_to_same_format(self):
        rows = [post("2026-10-01T15:00:00+0000", 1000, product="REELS"), post("2026-10-02T15:00:00+0000", 3000, product="REELS"),
                post("2026-10-01T15:00:00+0000", 100), post("2026-10-02T15:00:00+0000", 300)]
        scored = score_posts(rows, start=START, end=END)
        # Reels de 3000 e imagem de 300 valem o mesmo: ambos 1,5x a mediana do formato.
        self.assertEqual(sorted(round(p["reach_index"], 2) for p in scored), [0.5, 0.5, 1.5, 1.5])

    def test_ignores_posts_without_reach_and_outside_period(self):
        rows = [post("2026-10-01T15:00:00+0000", 0), post("2025-01-01T15:00:00+0000", 100), {"timestamp": None}]
        self.assertEqual(score_posts(rows, start=START, end=END), [])

    def test_views_used_when_reach_missing(self):
        row = {"timestamp": "2026-10-01T15:00:00Z", "media_product_type": "REELS", "insights_json": {"views": 50}}
        self.assertEqual(score_posts([row], start=START, end=END)[0]["reach"], 50)


class RankSlotsTests(unittest.TestCase):
    def test_single_post_slots_are_not_ranked_and_confidence_reflects_sample(self):
        rows = [post(f"2026-10-{d:02d}T21:00:00+0000", r) for d, r in ((6, 400), (13, 500), (20, 450), (27, 480))]  # terças 18h SP
        rows += [post("2026-10-01T12:00:00+0000", 5000)]  # um post isolado não vira "melhor horário"
        slots = rank_slots(score_posts(rows, start=START, end=END))
        self.assertEqual(len(slots), 1)
        self.assertEqual((slots[0]["weekday"], slots[0]["hours"], slots[0]["posts"], slots[0]["confidence"]),
                         ("terça", "18h-21h", 4, "boa"))


class OnlineFollowersTests(unittest.TestCase):
    def test_hour_key_converted_using_end_time_midnight(self):
        # end_time 07:00 UTC => hora 0 da Meta é meia-noite no Pacífico (UTC-7) = 04h em São Paulo.
        rows = [{"metric_date": "2026-10-27", "end_time": "2026-10-28T07:00:00+0000", "hour_key": 0, "followers_online": 10},
                {"metric_date": "2026-10-27", "end_time": "2026-10-28T07:00:00+0000", "hour_key": 16, "followers_online": 90}]
        out = online_followers_by_hour(rows)
        self.assertEqual(out["days"], 1)
        self.assertEqual({h["hour"]: h["followers_online"] for h in out["by_hour"]}, {"04h": 10, "20h": 90})
        self.assertEqual(out["peak_hours"][0], "20h")


class BuildPostingTimesTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_online_table_still_returns_post_analysis(self):
        reads = AsyncMock(side_effect=[[post("2026-10-07T21:00:00+0000", 100)], RuntimeError("relation does not exist")])
        with patch.object(posting_times, "sb_select", reads):
            result = await posting_times.build_posting_times("tenant-a", start="2026-09-01", end="2026-10-31")
        self.assertEqual(result["posts_analyzed"], 1)
        self.assertEqual(result["online_followers"]["days"], 0)
        self.assertEqual(reads.await_args_list[0].kwargs["filters"]["client_id"], "eq.tenant-a")


class PersistOnlineFollowersTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, followers=500, fetched=None, error=None, upsert_error=None):
        with patch.object(instagram_sync, "fetch_online_followers", AsyncMock(return_value=fetched or [], side_effect=error)) as fetch, \
             patch.object(instagram_sync, "sb_upsert", AsyncMock(side_effect=upsert_error)) as write:
            result = await instagram_sync._persist_online_followers(
                client_id="tenant-a", connection_id="conn-a", ig_user_id="ig-a", access_token="t", followers_count=followers)
        return result, fetch, write

    async def test_skips_accounts_below_meta_minimum(self):
        result, fetch, write = await self.call(followers=99)
        self.assertEqual(result["status"], "below_min_followers")
        fetch.assert_not_awaited(); write.assert_not_awaited()

    async def test_meta_error_never_breaks_sync(self):
        result, _, write = await self.call(error=RuntimeError("boom"))
        self.assertFalse(result["ok"]); write.assert_not_awaited()

    async def test_rows_use_day_before_end_time_and_upsert_key(self):
        result, _, write = await self.call(fetched=[{"end_time": "2026-10-28T07:00:00+0000", "values": {0: 5, 1: 7}}])
        self.assertEqual(result, {"ok": True, "status": "ok", "days": 1})
        table, rows = write.await_args.args
        self.assertEqual(table, "ig_online_followers")
        self.assertEqual(write.await_args.kwargs["on_conflict"], "client_id,metric_date,hour_key")
        self.assertEqual({(r["metric_date"], r["hour_key"], r["followers_online"], r["client_id"]) for r in rows},
                         {("2026-10-27", 0, 5, "tenant-a"), ("2026-10-27", 1, 7, "tenant-a")})

    async def test_table_not_applied_yet_is_reported_not_raised(self):
        response = httpx.Response(404, request=httpx.Request("POST", "http://x"))
        err = httpx.HTTPStatusError("missing", request=response.request, response=response)
        result, _, _ = await self.call(fetched=[{"end_time": "2026-10-28T07:00:00+0000", "values": {0: 5}}], upsert_error=err)
        self.assertEqual(result["status"], "schema_pending")


if __name__ == "__main__":
    unittest.main()
