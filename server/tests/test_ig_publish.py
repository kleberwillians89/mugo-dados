import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os
import unittest
from unittest.mock import AsyncMock, patch

from services import ig_publish as ip
from services.studio_calendar import StudioError

ITEM = {"id": "i1", "client_id": "roove", "format": "imagem", "art_url": "https://cdn.roove.com/arte.jpg", "caption_draft": "Legenda #roove"}
CREDS = {"ig_user_id": "1784", "token": "tok", "scopes": {"instagram_content_publish"}}


class MediaTests(unittest.TestCase):
    def test_links(self):
        self.assertEqual(ip.media_for(ITEM)[0], {"image_url": "https://cdn.roove.com/arte.jpg", "caption": "Legenda #roove"})
        drive = ip.media_for({**ITEM, "art_url": "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view?usp=sharing"})[0]
        self.assertEqual(drive["image_url"], "https://drive.google.com/uc?export=download&id=1AbCdEfGhIjKlMnOp")
        reels = ip.media_for({**ITEM, "format": "reels", "art_url": "https://cdn.x/v.mp4"})[0]
        self.assertEqual((reels["media_type"], reels["video_url"]), ("REELS", "https://cdn.x/v.mp4"))

    def test_manual_cases(self):
        for item in ({**ITEM, "art_url": "https://www.canva.com/design/abc/view"}, {**ITEM, "art_url": ""},
                     {**ITEM, "art_url": "https://cdn.x/arte.png"}, {**ITEM, "format": "carrossel"}):
            container, manual = ip.media_for(item)
            self.assertIsNone(container)
            self.assertTrue(manual)


class PublishItemTests(unittest.IsolatedAsyncioTestCase):
    async def run_item(self, *, enabled, claim=True, publish=None, creds=CREDS, item=ITEM):
        sets = []

        async def update(table, filters, patch, **kwargs):
            sets.append((filters, patch))
            return [{"id": "i1"}] if (claim or "publicando" in str(filters)) else []
        publish = publish or AsyncMock(return_value={"media_id": "m1", "permalink": "https://instagram.com/p/x"})
        with patch.object(ip, "sb_update", AsyncMock(side_effect=update)), patch.object(ip, "publish", publish), \
             patch("services.ig_engagement.credentials", AsyncMock(return_value=creds)), \
             patch.dict(os.environ, {"IG_PUBLISH_ENABLED": "true" if enabled else ""}):
            result = await ip.publish_item(item, creds_cache={})
        return result, sets, publish

    async def test_simulated_never_calls_meta(self):
        result, sets, publish = await self.run_item(enabled=False)
        self.assertEqual(result, "simulado")
        publish.assert_not_awaited()
        self.assertEqual(sets[0][0]["publish_status"], "is.null")  # trava antes de tudo

    async def test_live_publishes_and_marks_item(self):
        result, sets, publish = await self.run_item(enabled=True)
        self.assertEqual(result, "publicado")
        final = sets[-1][1]
        self.assertEqual((final["status"], final["published_permalink"]), ("publicado", "https://instagram.com/p/x"))

    async def test_lock_prevents_double_publish(self):
        result, _, publish = await self.run_item(enabled=True, claim=False)
        self.assertEqual(result, "ocupado")
        publish.assert_not_awaited()

    async def test_missing_permission_and_meta_error_are_recorded(self):
        result, sets, publish = await self.run_item(enabled=True, creds={**CREDS, "scopes": {"instagram_basic"}})
        self.assertEqual(result, "falhou")
        publish.assert_not_awaited()
        self.assertIn("permissão de publicar", sets[-1][1]["publish_error"])
        result, sets, _ = await self.run_item(enabled=True, publish=AsyncMock(side_effect=StudioError("IG_PUBLISH_FAILED", "Only photo or video can be accepted")))
        self.assertEqual(sets[-1][1]["publish_error"], "Only photo or video can be accepted")

    async def test_manual_link_is_not_locked(self):
        result, sets, _ = await self.run_item(enabled=True, item={**ITEM, "art_url": "https://www.canva.com/design/x"})
        self.assertEqual(result, "manual")
        self.assertEqual(sets[0][1]["publish_status"], "manual")


class GraphFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_reels_waits_for_processing(self):
        calls = []

        async def graph(method, path, **kwargs):
            calls.append((method, path))
            if path.endswith("/media"):
                return {"id": "c1"}
            if path == "/c1":
                return {"status_code": "FINISHED" if len([c for c in calls if c[1] == "/c1"]) > 1 else "IN_PROGRESS"}
            if path.endswith("/media_publish"):
                return {"id": "m1"}
            return {"permalink": "https://instagram.com/reel/x"}
        with patch.object(ip, "_graph", AsyncMock(side_effect=graph)):
            out = await ip.publish(CREDS, {"media_type": "REELS", "video_url": "https://x/v.mp4", "caption": ""}, wait_seconds=0)
        self.assertEqual(out, {"media_id": "m1", "permalink": "https://instagram.com/reel/x"})
        self.assertEqual([p for _, p in calls].count("/c1"), 2)

    async def test_due_only_confirmed_approved_and_past(self):
        select = AsyncMock(return_value=[])
        with patch.object(ip, "sb_select", select):
            await ip.publish_due()
        filters = select.await_args.kwargs["filters"]
        self.assertEqual((filters["status"], filters["schedule_confirmed_at"], filters["publish_status"]), ("eq.aprovado", "not.is.null", "is.null"))
        self.assertTrue(filters["scheduled_at"].startswith("lte."))


if __name__ == "__main__":
    unittest.main()
