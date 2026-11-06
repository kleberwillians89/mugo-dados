import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from services import studio_calendar as sc
from services.studio_calendar import StudioError

VID = "https://x.supabase.co/storage/v1/object/public/ig-media/a.mp4"


def run(coro):
    return asyncio.run(coro)


def item(**kw):
    base = {"id": "i1", "status": "aprovado", "format": "reels", "art_url": VID, "caption_draft": "x",
            "scheduled_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()}
    return {**base, **kw}


class PublishNowTests(unittest.TestCase):
    def _run(self, row, **kw):
        upd = AsyncMock(side_effect=lambda table, filters, patch: [{**row, **patch}])
        with patch.object(sc, "sb_select", AsyncMock(return_value=[row])), patch.object(sc, "sb_update", upd):
            out = run(sc.confirm_schedule("latinas", "i1", user_id="u", **kw))
        return out, upd.call_args.kwargs["patch"]

    def test_schedule_future(self):
        out, patch_ = self._run(item())
        self.assertIn("schedule_confirmed_at", patch_)
        self.assertNotIn("scheduled_at", patch_)

    def test_publish_now_even_when_time_passed(self):
        out, patch_ = self._run(item(scheduled_at="2026-11-06T19:06:00+00:00"), now=True)
        self.assertIn("scheduled_at", patch_)
        self.assertLessEqual(datetime.fromisoformat(patch_["scheduled_at"]), datetime.now(timezone.utc))

    def test_past_without_now_is_refused(self):
        with self.assertRaises(StudioError) as ctx:
            self._run(item(scheduled_at="2020-01-01T00:00:00+00:00"))
        self.assertEqual(ctx.exception.code, "SCHEDULE_IN_PAST")

    def test_art_that_does_not_publish_is_refused_before_scheduling(self):
        for row in (item(format="imagem", art_url="https://canva.link/sym7z8mpql3cf9l"), item(art_url=None),
                    item(format="reels", art_url="https://x.supabase.co/storage/v1/object/public/ig-media/a.jpg")):
            with self.assertRaises(StudioError) as ctx:
                self._run(row)
            self.assertEqual(ctx.exception.code, "SCHEDULE_ART_INVALID")


if __name__ == "__main__":
    unittest.main()
