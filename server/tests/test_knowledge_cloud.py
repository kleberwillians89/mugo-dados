"""Importar do Google Drive e do Canva para o Conhecimento da marca."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import io
import os
import unittest
from unittest.mock import patch

import httpx

from services import knowledge_cloud as kc
from services.studio_calendar import StudioError


class ParseTests(unittest.TestCase):
    def test_links(self):
        self.assertEqual(kc.parse_link("https://drive.google.com/drive/u/0/folders/1q7psA_PM9Xt-cZhYjgbdGRaWjZoKX7tN"), ("drive_folder", "1q7psA_PM9Xt-cZhYjgbdGRaWjZoKX7tN"))
        self.assertEqual(kc.parse_link("https://drive.google.com/file/d/1AbCdEfGhIjK/view?usp=sharing")[0], "drive_file")
        self.assertEqual(kc.parse_link("https://docs.google.com/presentation/d/1AbCdEfGhIjKlm/edit")[1], "1AbCdEfGhIjKlm")
        self.assertEqual(kc.parse_link("https://www.canva.com/design/DAF123/view")[0], "canva")
        for bad in ("http://drive.google.com/folders/1AbCdEfGhIjK", "https://evil.com/folders/1AbCdEfGhIjK", "https://drive.google.com/drive/my-drive"):
            with self.assertRaises(StudioError):
                kc.parse_link(bad)

    def test_classify(self):
        ok = kc.classify({"id": "1", "name": "Manual.pdf", "mimeType": "application/pdf", "size": "1000"})
        doc = kc.classify({"id": "2", "name": "Briefing", "mimeType": "application/vnd.google-apps.document"})
        big = kc.classify({"id": "3", "name": "x.pdf", "mimeType": "application/pdf", "size": str(20 * 1024 * 1024)})
        ai = kc.classify({"id": "4", "name": "Roove Skinwear.ai", "mimeType": "application/postscript"})
        vid = kc.classify({"id": "5", "name": "ROOVE 1.mp4", "mimeType": "video/mp4"})
        self.assertTrue(ok["supported"] and doc["supported"])
        self.assertFalse(big["supported"] or ai["supported"] or vid["supported"])
        self.assertIn("PDF", ai["reason"])


def transport(routes):
    def handler(request: httpx.Request):
        for match, response in routes:
            if match(request):
                return response(request) if callable(response) else response
        return httpx.Response(404)
    return httpx.MockTransport(handler)


class DriveTests(unittest.IsolatedAsyncioTestCase):
    async def test_lists_folder_with_subfolders(self):
        def files(request):
            q = request.url.params.get("q", "")
            if "'ROOT00000001'" in q:
                return httpx.Response(200, json={"files": [
                    {"id": "SUB000000001", "name": "CONTEUDOS", "mimeType": kc.FOLDER_MIME},
                    {"id": "F1", "name": "ROOVE_MANUAL_ID.pdf", "mimeType": "application/pdf", "size": "2000"},
                    {"id": "F2", "name": "ROOVE 1 .mp4", "mimeType": "video/mp4"}]})
            return httpx.Response(200, json={"files": [{"id": "F3", "name": "Briefing BF", "mimeType": "application/vnd.google-apps.document"}]})
        real = httpx.AsyncClient
        with patch.dict(os.environ, {"GOOGLE_DRIVE_API_KEY": "k"}), \
             patch.object(kc.httpx, "AsyncClient", lambda **kw: real(transport=transport([(lambda r: r.url.path.endswith("/files"), files)]))):
            out = await kc.list_link("https://drive.google.com/drive/folders/ROOT00000001")
        names = [(f["path"], f["name"], f["supported"]) for f in out["files"]]
        self.assertEqual(names, [("", "ROOVE_MANUAL_ID.pdf", True), ("CONTEUDOS/", "Briefing BF", True), ("", "ROOVE 1 .mp4", False)])

    async def test_private_folder_and_missing_key(self):
        real = httpx.AsyncClient
        with patch.dict(os.environ, {"GOOGLE_DRIVE_API_KEY": "k"}), \
             patch.object(kc.httpx, "AsyncClient", lambda **kw: real(transport=transport([(lambda r: True, httpx.Response(404))]))):
            with self.assertRaises(StudioError) as err:
                await kc.list_link("https://drive.google.com/drive/folders/ROOT00000001")
        self.assertEqual(err.exception.code, "DRIVE_PRIVATE")
        with patch.dict(os.environ, {"GOOGLE_DRIVE_API_KEY": "", "YOUTUBE_API_KEY": ""}):
            with self.assertRaises(StudioError) as err:
                await kc.list_link("https://drive.google.com/drive/folders/ROOT00000001")
        self.assertEqual(err.exception.code, "DRIVE_NOT_CONFIGURED")

    async def test_google_doc_is_exported_as_word(self):
        seen = {}
        def export(request):
            seen["mime"] = request.url.params.get("mimeType")
            return httpx.Response(200, content=b"PK-docx")
        real = httpx.AsyncClient
        with patch.dict(os.environ, {"GOOGLE_DRIVE_API_KEY": "k"}), \
             patch.object(kc.httpx, "AsyncClient", lambda **kw: real(transport=transport([(lambda r: r.url.path.endswith("/export"), export)]))):
            out = await kc.fetch_file("drive", "DOC000000001", "Briefing BF", "application/vnd.google-apps.document")
        self.assertEqual(out["file_name"], "Briefing BF.docx")
        self.assertIn("wordprocessingml", seen["mime"])


class CanvaTests(unittest.TestCase):
    def test_image_becomes_one_page_pdf(self):
        from PIL import Image
        buf = io.BytesIO(); Image.new("RGB", (40, 30), (200, 10, 10)).save(buf, format="PNG")
        pdf = kc.image_to_pdf(buf.getvalue())
        self.assertTrue(pdf.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()


class LibraryTests(unittest.IsolatedAsyncioTestCase):
    def test_library_categories(self):
        self.assertEqual(kc.classify({"id": "1", "name": "ROOVE_LOGO.png", "mimeType": "image/png"}, "library")["category"], "logo")
        self.assertEqual(kc.classify({"id": "2", "name": "a.mp4", "mimeType": "video/mp4", "_path": "Vídeos/"}, "library")["category"], "video")
        self.assertEqual(kc.classify({"id": "3", "name": "a.jpg", "mimeType": "image/jpeg", "_path": "roove_produtos/"}, "library")["category"], "produto")
        self.assertFalse(kc.classify({"id": "4", "name": "x.ai", "mimeType": "application/postscript"}, "library")["supported"])
        self.assertTrue(kc.classify({"id": "5", "name": "ROOVE 1.mp4", "mimeType": "video/mp4"}, "library")["supported"])

    async def test_streams_drive_file_into_library(self):
        from unittest.mock import AsyncMock
        put = {}
        def handler(request: httpx.Request):
            if request.method == "GET":
                return httpx.Response(200, content=b"x" * 3000, headers={"content-length": "3000"})
            put["type"] = request.headers.get("content-type"); put["len"] = len(request.read())
            return httpx.Response(200)
        real = httpx.AsyncClient
        with patch.dict(os.environ, {"GOOGLE_DRIVE_API_KEY": "k"}), \
             patch.object(kc.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler))), \
             patch("services.studio_library.upload_target", AsyncMock(return_value={"upload_url": "https://s/up", "public_url": "https://s/pub.mp4"})), \
             patch("services.studio_library.add_item", AsyncMock(side_effect=lambda cid, data, **kw: {"id": "i1", **data})) as add:
            item = await kc.copy_to_library("roove", "drive", "VID000000001", "ROOVE 1.mp4", "video/mp4", "video", user_id="u", author="K", side="mugo")
        self.assertEqual((put["type"], put["len"]), ("video/mp4", 3000))
        self.assertEqual((item["url"], item["category"], item["size_bytes"]), ("https://s/pub.mp4", "video", 3000))
        add.assert_awaited_once()
