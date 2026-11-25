"""Carrossel com imagem + vídeo: o vídeo vai no padrão que a Meta aceita (4:5–16:9, ≤60 s, H.264, faststart)."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import ig_carousel_video as cv  # noqa: E402
from services import ig_publish  # noqa: E402
from services.studio_calendar import StudioError  # noqa: E402

EXE = cv.ffmpeg_exe()


def make_video(seconds: float, size: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "v.mov")
        subprocess.run([EXE, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=25",
                        "-f", "lavfi", "-i", "sine=frequency=440", "-t", str(seconds), "-shortest",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", out], check=True)
        with open(out, "rb") as handle:
            return handle.read()


def probe(data: bytes) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "o.mp4")
        with open(src, "wb") as handle:
            handle.write(data)
        return subprocess.run([EXE, "-hide_banner", "-i", src], capture_output=True, text=True).stderr


class FrameTests(unittest.TestCase):
    def test_frame_follows_first_slide_within_meta_limits(self):
        self.assertEqual(cv.frame_size(4 / 5), (1080, 1350))
        self.assertEqual(cv.frame_size(1.0), (1080, 1080))
        self.assertEqual(cv.frame_size(9 / 16), (1080, 1350))  # vertical demais: vira 4:5
        self.assertEqual(cv.frame_size(3.0)[1], 608)  # horizontal demais: 16:9

    def test_mixed_carousel_plan_keeps_video_as_video(self):
        plan, problem = ig_publish.media_for({"format": "carrossel", "art_url": "https://x.co/a.jpg https://x.co/b.mp4", "caption_draft": "oi"})
        self.assertIsNone(problem)
        self.assertEqual(plan["children"][1], {"video_url": "https://x.co/b.mp4", "media_type": "VIDEO", "is_carousel_item": "true"})


@unittest.skipUnless(EXE, "ffmpeg indisponível")
class TranscodeTests(unittest.TestCase):
    def test_vertical_phone_video_becomes_4x5_h264_without_cropping(self):
        out = cv._transcode(EXE, make_video(4, "540x960"), 1080, 1350)
        info = probe(out)
        self.assertIn("h264", info)
        self.assertIn("aac", info)
        self.assertRegex(info, r"1080x1350")
        self.assertTrue(out[:64].find(b"ftyp") >= 0)

    def test_too_short_video_is_refused_with_clear_message(self):
        with self.assertRaises(StudioError) as ctx:
            cv._transcode(EXE, make_video(1.5, "320x320"), 1080, 1350)
        self.assertIn("3 segundos", str(ctx.exception))

    def test_long_video_is_trimmed_to_60_seconds(self):
        args = cv.ffmpeg_args("ffmpeg", "in", "out.mp4", 1080, 1350)
        self.assertEqual(args[args.index("-t") + 1], "60")
        self.assertIn("+faststart", args)


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_drive_slide_that_is_a_video_goes_as_video(self):
        plan = {"type": "carousel", "children": [{"image_url": "https://x.co/a.jpg", "is_carousel_item": "true"},
                                                 {"image_url": "https://drive.google.com/uc?export=download&id=abc", "is_carousel_item": "true"}]}

        class Resp:
            headers = {"content-type": "video/quicktime"}

        class Stream:
            async def __aenter__(self): return Resp()
            async def __aexit__(self, *a): return False

        class Client:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            def stream(self, *a, **k): return Stream()

        with patch.object(cv.httpx, "AsyncClient", Client):
            await cv.resolve_drive_children(plan)
        self.assertEqual(plan["children"][1]["media_type"], "VIDEO")
        self.assertNotIn("image_url", plan["children"][1])
        self.assertEqual(plan["children"][0], {"image_url": "https://x.co/a.jpg", "is_carousel_item": "true"})

    async def test_videos_are_converted_and_replaced_by_public_mp4(self):
        plan = {"type": "carousel", "children": [{"image_url": "https://x.co/a.jpg"}, {"video_url": "https://x.co/b.mov", "media_type": "VIDEO"}]}
        upload = AsyncMock(return_value="https://storage/ig-publish/roove/k.mp4")
        with patch.object(cv, "ffmpeg_exe", return_value="ffmpeg"), patch.object(cv, "_download", AsyncMock(return_value=b"v")), \
                patch.object(cv, "_first_slide_ratio", AsyncMock(return_value=0.8)), \
                patch.object(cv, "_transcode", return_value=b"mp4") as transcode, \
                patch("services.ig_supabase.sb_upload_public", upload):
            done = await cv.ensure_carousel_videos(plan, "roove")
        self.assertEqual(done, 1)
        self.assertEqual(transcode.call_args.args[2:], (1080, 1350))
        self.assertEqual(plan["children"][1]["video_url"], "https://storage/ig-publish/roove/k.mp4")
        self.assertEqual(upload.await_args.args[2], "video/mp4")
        self.assertEqual(plan["children"][0], {"image_url": "https://x.co/a.jpg"})

    async def test_storage_failure_becomes_readable_error(self):
        plan = {"type": "carousel", "children": [{"video_url": "https://x.co/b.mov", "media_type": "VIDEO"}]}
        with patch.object(cv, "ffmpeg_exe", return_value="ffmpeg"), patch.object(cv, "_download", AsyncMock(return_value=b"v")), \
                patch.object(cv, "_transcode", return_value=b"mp4"), \
                patch("services.ig_supabase.sb_upload_public", AsyncMock(side_effect=RuntimeError("413"))):
            with self.assertRaises(StudioError):
                await cv.ensure_carousel_videos(plan, "roove")

    async def test_non_carousel_is_untouched(self):
        plan = {"type": "reels", "fields": {"video_url": "https://x.co/b.mp4"}, "children": []}
        self.assertEqual(await cv.ensure_carousel_videos(plan, "roove"), 0)


if __name__ == "__main__":
    unittest.main()
