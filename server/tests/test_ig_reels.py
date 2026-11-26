import asyncio
import json
import unittest
from unittest import mock

from services import ig_publish
from services.ig_publish import media_for
from services.ig_reels import apply_reels_options, clean_reels_options, first_comment
from services.studio_calendar import StudioError
from services.studio_history import changed_fields, describe_patch

VID = "https://x.supabase.co/storage/v1/object/public/ig-media/a.mp4"
COVER = "https://x.supabase.co/storage/v1/object/public/ig-media/capa.jpg"


def reels(**options):
    return {"format": "reels", "art_url": VID, "caption_draft": "x", "reels_options": options}


class CleanTests(unittest.TestCase):
    def test_keeps_known_fields_and_limits(self):
        out = clean_reels_options({"cover_mode": "frame", "thumb_offset_ms": 3500.4, "share_to_feed": False, "trial": "auto",
                                   "audio_name": "  CuraClube  ", "first_comment": "link na bio", "outro": 1})
        self.assertEqual(out, {"cover_mode": "frame", "thumb_offset_ms": 3500, "share_to_feed": False, "trial": "auto",
                               "audio_name": "CuraClube", "first_comment": "link na bio"})

    def test_bad_values_are_dropped_or_refused(self):
        self.assertEqual(clean_reels_options({"cover_mode": "x", "trial": "sim", "thumb_offset_ms": "abc", "share_to_feed": "true"}), {})
        self.assertEqual(clean_reels_options({"thumb_offset_ms": 10**9})["thumb_offset_ms"], 900_000)
        self.assertEqual(clean_reels_options(None), {})
        with self.assertRaises(StudioError):
            clean_reels_options({"cover_url": "http://inseguro.com/a.jpg"})


class ContainerTests(unittest.TestCase):
    def test_old_items_publish_exactly_as_before(self):
        plan, problem = media_for({"format": "reels", "art_url": VID, "caption_draft": "x"})
        self.assertIsNone(problem)
        self.assertEqual(plan["fields"], {"media_type": "REELS", "video_url": VID, "caption": "x"})
        plan, _ = media_for(reels())
        self.assertEqual(plan["fields"], {"media_type": "REELS", "video_url": VID, "caption": "x"})

    def test_frame_cover_sends_thumb_offset(self):
        plan, _ = media_for(reels(cover_mode="frame", thumb_offset_ms=3500, share_to_feed=True))
        self.assertEqual(plan["fields"]["thumb_offset"], "3500")
        self.assertEqual(plan["fields"]["share_to_feed"], "true")
        self.assertNotIn("cover_url", plan["fields"])

    def test_image_cover_wins_over_frame(self):
        plan, _ = media_for(reels(cover_mode="image", cover_url=COVER, thumb_offset_ms=3500))
        self.assertEqual(plan["fields"]["cover_url"], COVER)
        self.assertNotIn("thumb_offset", plan["fields"])
        self.assertNotIn("warning", plan)

    def test_drive_cover_becomes_direct_download(self):
        plan, _ = media_for(reels(cover_mode="image", cover_url="https://drive.google.com/file/d/abcdefghijk123/view"))
        self.assertEqual(plan["fields"]["cover_url"], "https://drive.google.com/uc?export=download&id=abcdefghijk123")

    def test_png_cover_goes_for_jpeg_conversion(self):
        # Antes a capa PNG caía no frame sem avisar direito; agora vai e vira JPG na publicação (ensure_jpeg).
        plan, _ = media_for(reels(cover_mode="image", cover_url="https://x.com/capa.png", thumb_offset_ms=7000))
        self.assertEqual(plan["fields"]["cover_url"], "https://x.com/capa.png")
        self.assertNotIn("thumb_offset", plan["fields"])
        self.assertNotIn("warning", plan)

    def test_cover_that_is_not_an_image_falls_back_to_frame(self):
        plan, _ = media_for(reels(cover_mode="image", cover_url="https://www.canva.com/design/x/view", thumb_offset_ms=7000))
        self.assertNotIn("cover_url", plan["fields"])
        self.assertEqual(plan["fields"]["thumb_offset"], "7000")
        self.assertIn("frame", plan["warning"])

    def test_png_cover_is_converted_before_publishing(self):
        import asyncio
        from io import BytesIO
        from unittest.mock import AsyncMock, MagicMock, patch
        from PIL import Image
        from services import ig_publish
        buf = BytesIO(); Image.new("RGBA", (20, 30), (255, 0, 0, 128)).save(buf, "PNG")
        plan, _ = media_for(reels(cover_mode="image", cover_url="https://x.com/capa.png"))
        client = MagicMock(); client.__aenter__ = AsyncMock(return_value=client); client.__aexit__ = AsyncMock(return_value=False)
        client.get = AsyncMock(return_value=MagicMock(status_code=200, content=buf.getvalue()))
        upload = AsyncMock(return_value="https://x.supabase.co/capa.jpg")
        with patch.object(ig_publish.httpx, "AsyncClient", return_value=client), \
             patch("services.ig_supabase.sb_upload_public", upload):
            changed = asyncio.run(ig_publish.ensure_jpeg(plan, "ruah"))
        self.assertEqual(changed, 1)
        self.assertEqual(plan["fields"]["cover_url"], "https://x.supabase.co/capa.jpg")
        self.assertEqual(plan["fields"]["video_url"], "https://x.supabase.co/storage/v1/object/public/ig-media/a.mp4")

    def test_describe_tells_what_went_with_the_reels(self):
        from services.ig_reels import describe
        music = {"audio_id": "123", "title": "Lofi", "artist": "Ana"}
        raw = {"cover_mode": "image", "cover_url": COVER, "music": music}
        plan, _ = media_for(reels(**raw))
        self.assertEqual(describe(plan, raw), "publicou o Reels com música “Lofi · Ana” e capa por imagem")

    def test_trial_audio_and_feed(self):
        plan, _ = media_for(reels(trial="manual", audio_name="Áudio CuraClube", share_to_feed=False))
        self.assertEqual(json.loads(plan["fields"]["trial_params"]), {"graduation_strategy": "MANUAL"})
        self.assertEqual(plan["fields"]["audio_name"], "Áudio CuraClube")
        self.assertEqual(plan["fields"]["share_to_feed"], "false")
        plan, _ = media_for(reels(trial="auto"))
        self.assertEqual(json.loads(plan["fields"]["trial_params"]), {"graduation_strategy": "SS_PERFORMANCE"})
        plan, _ = media_for(reels(trial="off"))
        self.assertNotIn("trial_params", plan["fields"])

    def test_ignored_outside_reels(self):
        img = "https://x.supabase.co/storage/v1/object/public/ig-media/a.jpg"
        plan, _ = media_for({"format": "imagem", "art_url": img, "reels_options": {"cover_mode": "frame", "thumb_offset_ms": 10}})
        self.assertNotIn("thumb_offset", plan["fields"])
        self.assertIsNone(apply_reels_options({"type": "image", "fields": {}}, {"thumb_offset_ms": 10}))
        self.assertIsNone(first_comment({"format": "imagem", "reels_options": {"first_comment": "oi"}}))
        self.assertEqual(first_comment(reels(first_comment="oi")), "oi")


class FirstCommentTests(unittest.TestCase):
    def test_comment_failure_does_not_break_publication(self):
        calls, events = [], []

        async def graph(method, path, **kw):
            calls.append(path)
            raise StudioError("IG_PUBLISH_FAILED", "sem permissão de comentar")

        async def record(client_id, item_id, action, **kw):
            events.append(action)

        with mock.patch.object(ig_publish, "_graph", graph), mock.patch("services.studio_history.record", record):
            asyncio.run(ig_publish._first_comment({"token": "t"}, {"client_id": "c", "id": "i", **reels(first_comment="link")}, "123"))
        self.assertEqual(calls, ["/123/comments"])
        self.assertIn("não conseguiu publicar o primeiro comentário", events[0])

    def test_no_comment_no_call(self):
        async def graph(*a, **kw):
            raise AssertionError("não devia chamar a Meta")

        with mock.patch.object(ig_publish, "_graph", graph):
            asyncio.run(ig_publish._first_comment({"token": "t"}, {"client_id": "c", "id": "i", **reels()}, "123"))


class HistoryTests(unittest.TestCase):
    def test_only_real_changes_are_recorded(self):
        before = {"reels_options": {"cover_mode": "frame", "thumb_offset_ms": 3500}}
        self.assertEqual(changed_fields(before, {"reels_options": {"thumb_offset_ms": 3500, "cover_mode": "frame"}}), {})
        patch = changed_fields(before, {"reels_options": {"cover_mode": "frame", "thumb_offset_ms": 7000}})
        self.assertIn("ajustou a capa e as opções do Reels", describe_patch(patch))


if __name__ == "__main__":
    unittest.main()
