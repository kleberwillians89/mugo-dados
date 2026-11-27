"""A IA lê a Biblioteca: documentos enviados viram Conhecimento da marca, sem repetir e só da pasta da empresa."""
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import library_knowledge as lk  # noqa: E402
from services.brand_context_health import evaluate  # noqa: E402
from services.studio_calendar import StudioError  # noqa: E402

PDF = "application/pdf"
URL = "https://sb.supabase.co/storage/v1/object/public/ig-media/studio-library/roove/a.pdf"


def item(title, mime=PDF, note="", kind="arquivo", **extra):
    return {"id": title, "kind": kind, "title": title, "mime_type": mime, "note": note, "url": URL, "category": "documento", **extra}


class PendingTests(unittest.TestCase):
    def test_only_unread_documents(self):
        library = [item("Roove_plan.pdf"), item("Logo", mime="image/png"), item("Site", kind="link"),
                   item("Brand book", note="Conhecimento da marca · doc:123"), item("Já lido.pdf"), item("Apresentação", mime=
                   "application/vnd.openxmlformats-officedocument.presentationml.presentation")]
        out = lk.pending_items(library, {"Já lido.pdf"})
        self.assertEqual([i["title"] for i in out], ["Roove_plan.pdf", "Apresentação"])
        self.assertEqual(lk.file_name(out[1]), "Apresentação.pptx")  # a extensão decide como extrair

    def test_health_points_to_unread_library(self):
        base = dict(profile={}, profile_saved=False, business={}, knowledge="", knowledge_max=6000, documents=[], competitors=0, new_signals=0)
        with_lib = evaluate(**base, library_pending=2)
        self.assertIn("2 documento(s) da Biblioteca", " ".join(i["title"] for i in with_lib["items"]))
        self.assertNotIn("biblioteca", [i["id"] for i in evaluate(**base)["items"]])


class SyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        lk._FAILED.clear()
        lk._RUNNING.clear()

    async def test_reads_teaches_and_skips_large(self):
        todo = [item("Roove_plan.pdf"), item("Catalogo.pdf", size_bytes=50 * 1024 * 1024)]
        learn = AsyncMock(return_value={"document": {"id": "d1", "status": "aprendido"}})
        with patch.object(lk, "pending", AsyncMock(return_value=todo)), patch.object(lk, "_download", AsyncMock(return_value=b"%PDF")), \
                patch("services.brand_knowledge.extract_text", return_value="Plano de campanha Black Friday da Roove " * 3), \
                patch("services.brand_knowledge.learn", learn):
            out = await lk.sync("roove", user_id="u1")
        self.assertEqual([r["name"] for r in out["read"]], ["Roove_plan.pdf"])
        self.assertEqual(out["skipped"][0]["reason"], "maior que 10 MB")
        self.assertEqual(learn.await_args.kwargs["kind"], "institucional")

    async def test_scanned_pdf_goes_to_ocr_and_failures_are_not_retried(self):
        empty = StudioError("DOC_EMPTY")
        with patch("services.brand_knowledge.extract_text", side_effect=empty), \
                patch("services.brand_ocr.ocr_pdf", AsyncMock(return_value={"text": "[Página 1] plano"})) as ocr:
            self.assertIn("plano", await lk._text("roove", "plano.pdf", b"%PDF"))
        ocr.assert_awaited_once()
        todo = [item("Quebrado.pdf")]
        with patch.object(lk, "pending", AsyncMock(return_value=todo)), \
                patch.object(lk, "_download", AsyncMock(side_effect=StudioError("DOC_UNREADABLE"))) as download:
            first = await lk.sync("roove")
            second = await lk.sync("roove")
        self.assertEqual(first["skipped"][0]["reason"], "arquivo protegido ou corrompido")
        self.assertEqual((second["skipped"], download.await_count), ([], 1))

    async def test_never_downloads_outside_the_company_folder(self):
        with self.assertRaises(StudioError) as ctx:
            await lk._download("roove", "https://evil.example.com/x.pdf", 1000)
        self.assertEqual(ctx.exception.code, "LIBRARY_URL_INVALID")


if __name__ == "__main__":
    unittest.main()
