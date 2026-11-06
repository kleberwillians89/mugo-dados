import asyncio
import io
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from services import studio_art_import as ai
from services.studio_calendar import StudioError

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 200
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 200


def _png() -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGBA", (4, 4), (255, 0, 0, 128)).save(out, "PNG")
    return out.getvalue()


def run(coro):
    return asyncio.run(coro)


class Fake:
    """Transporte falso: responde por URL, registra o PUT para o Storage."""
    def __init__(self, pages):
        self.pages = pages
        self.put = None

    def __call__(self, request: httpx.Request):
        url = str(request.url)
        if request.method == "PUT":
            self.put = (url, request.headers.get("content-type"), request.read())
            return httpx.Response(200, json={"Key": "ok"})
        for prefix, resp in self.pages.items():
            if url.startswith(prefix):
                return resp() if callable(resp) else resp
        return httpx.Response(404)


class ArtImportTests(unittest.TestCase):
    def setUp(self):
        self.target = patch.object(ai, "upload_target", AsyncMock(return_value={"upload_url": "https://sb.supabase.co/storage/v1/upload/x",
                                                                               "public_url": "https://sb.supabase.co/storage/v1/object/public/ig-media/a"}))
        self.target.start()

    def tearDown(self):
        self.target.stop()

    def _run(self, fake, url, item=None):
        real = httpx.AsyncClient
        with patch.object(ai.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(fake), **kw)):
            return run(ai.import_art("latinas", url, item))

    def test_sniff(self):
        self.assertEqual(ai.sniff(JPEG), "image/jpeg")
        self.assertEqual(ai.sniff(MP4), "video/mp4")
        self.assertEqual(ai.sniff(b"\x00\x00\x00\x14ftypqt  "), "video/quicktime")
        self.assertIsNone(ai.sniff(b"<!doctype html>"))

    def test_drive_file_video_goes_to_storage(self):
        fake = Fake({"https://drive.usercontent.google.com/download?id=1AbCdEfGhIjK": httpx.Response(200, content=MP4)})
        out = self._run(fake, "https://drive.google.com/file/d/1AbCdEfGhIjK/view?usp=sharing")
        self.assertEqual(out["content_type"], "video/mp4")
        self.assertEqual(fake.put[1], "video/mp4")
        self.assertEqual(fake.put[2], MP4)

    def test_drive_private_returns_html(self):
        fake = Fake({"https://drive.usercontent.google.com/": httpx.Response(200, content=b"<!DOCTYPE html><html>login</html>")})
        with self.assertRaises(StudioError) as ctx:
            self._run(fake, "https://drive.google.com/file/d/1AbCdEfGhIjK/view")
        self.assertEqual(ctx.exception.code, "ART_LINK_PRIVATE")

    def test_folder_and_foreign_hosts_rejected(self):
        for url, code in [("https://drive.google.com/drive/folders/1O-Iz6I-uK8iY", "ART_LINK_FOLDER"),
                          ("https://evil.example.com/a.jpg", "ART_LINK_INVALID"), ("http://drive.google.com/file/d/1AbCdEfGhIjK", "ART_LINK_INVALID")]:
            with self.assertRaises(StudioError) as ctx:
                self._run(Fake({}), url)
            self.assertEqual(ctx.exception.code, code)

    def test_canva_short_link_uses_og_image_and_converts_png(self):
        page = '<html><head><meta property="og:image" content="https://document-export.canva.com/abc/preview.png"></head></html>'
        fake = Fake({"https://canva.link/sym7z8": httpx.Response(302, headers={"location": "https://www.canva.com/design/DAG123/view"}),
                     "https://www.canva.com/design/DAG123/view": httpx.Response(200, text=page),
                     "https://document-export.canva.com/abc/preview.png": httpx.Response(200, content=_png())})
        out = self._run(fake, "https://canva.link/sym7z8")
        self.assertEqual(out["content_type"], "image/jpeg")
        self.assertTrue(fake.put[2].startswith(b"\xff\xd8\xff"))
        self.assertIn("Canva", out["note"])

    def test_redirect_to_foreign_host_is_blocked(self):
        fake = Fake({"https://canva.link/x": httpx.Response(302, headers={"location": "https://169.254.169.254/latest"})})
        with self.assertRaises(StudioError) as ctx:
            self._run(fake, "https://canva.link/xyzxyz")
        self.assertEqual(ctx.exception.code, "ART_LINK_INVALID")


if __name__ == "__main__":
    unittest.main()
