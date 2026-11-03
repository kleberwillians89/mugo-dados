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
    def test_single_drive_and_reels(self):
        plan = ip.media_for(ITEM)[0]
        self.assertEqual((plan["type"], plan["fields"]), ("image", {"image_url": "https://cdn.roove.com/arte.jpg", "caption": "Legenda #roove"}))
        drive = ip.media_for({**ITEM, "art_url": "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view?usp=sharing"})[0]
        self.assertEqual(drive["fields"]["image_url"], "https://drive.google.com/uc?export=download&id=1AbCdEfGhIjKlMnOp")
        reels = ip.media_for({**ITEM, "format": "reels", "art_url": "https://cdn.x/v.mp4"})[0]
        self.assertEqual((reels["fields"]["media_type"], reels["fields"]["video_url"]), ("REELS", "https://cdn.x/v.mp4"))

    def test_carousel_and_story(self):
        plan = ip.media_for({**ITEM, "format": "carrossel", "art_url": "https://cdn.x/1.jpg\nhttps://cdn.x/2.mp4\nhttps://cdn.x/3.jpg"})[0]
        self.assertEqual(plan["type"], "carousel")
        self.assertEqual([c.get("media_type") for c in plan["children"]], [None, "VIDEO", None])
        self.assertTrue(all(c["is_carousel_item"] == "true" for c in plan["children"]))
        story = ip.media_for({**ITEM, "format": "stories"})[0]
        self.assertEqual(story["fields"], {"media_type": "STORIES", "image_url": "https://cdn.roove.com/arte.jpg"})

    def test_manual_cases(self):
        for item in ({**ITEM, "art_url": "https://www.canva.com/design/abc/view"}, {**ITEM, "art_url": ""},
                     {**ITEM, "art_url": "https://cdn.x/arte.png"}, {**ITEM, "format": "carrossel"},
                     {**ITEM, "format": "reels"}):
            plan, manual = ip.media_for(item)
            self.assertIsNone(plan)
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
    async def flow(self, plan, statuses):
        calls, ids = [], iter(["c1", "c2", "c3", "c4"])

        async def graph(method, path, **kwargs):
            calls.append((method, path, kwargs.get("data")))
            if path.endswith("/media"):
                return {"id": next(ids)}
            if method == "GET" and "fields" in (kwargs.get("params") or {}) and kwargs["params"]["fields"] == "status_code":
                return {"status_code": statuses.pop(0) if statuses else "FINISHED"}
            if path.endswith("/media_publish"):
                return {"id": "m1"}
            return {"permalink": "https://instagram.com/p/x"}
        with patch.object(ip, "_graph", AsyncMock(side_effect=graph)):
            out = await ip.publish(CREDS, plan, wait_seconds=0)
        return out, calls

    async def test_reels_waits_for_processing(self):
        plan = ip.media_for({**ITEM, "format": "reels", "art_url": "https://x/v.mp4"})[0]
        out, calls = await self.flow(plan, ["IN_PROGRESS", "FINISHED"])
        self.assertEqual(out, {"media_id": "m1", "permalink": "https://instagram.com/p/x"})
        self.assertEqual(sum(1 for m, p, _ in calls if m == "GET" and p == "/c1"), 2)

    async def test_carousel_creates_children_then_parent(self):
        plan = ip.media_for({**ITEM, "format": "carrossel", "art_url": "https://x/1.jpg\nhttps://x/2.jpg"})[0]
        out, calls = await self.flow(plan, [])
        posts = [(p, d) for m, p, d in calls if m == "POST"]
        self.assertEqual(posts[2][1]["children"], "c1,c2")
        self.assertEqual(posts[2][1]["media_type"], "CAROUSEL")
        self.assertEqual(posts[-1], ("/1784/media_publish", {"creation_id": "c3"}))

    async def test_due_only_confirmed_approved_and_past(self):
        select = AsyncMock(return_value=[])
        with patch.object(ip, "sb_select", select):
            await ip.publish_due()
        filters = select.await_args.kwargs["filters"]
        self.assertEqual((filters["status"], filters["schedule_confirmed_at"], filters["publish_status"]), ("eq.aprovado", "not.is.null", "is.null"))
        self.assertTrue(filters["scheduled_at"].startswith("lte."))


if __name__ == "__main__":
    unittest.main()
