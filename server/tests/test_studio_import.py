"""Importar calendário (PowerPoint) e link da arte."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import AsyncMock, patch

from services import studio_import as si
from services.studio_calendar import StudioError, clean_art_url

SLIDES = [{"index": 1, "text": "Calendário Novembro Curavino", "links": []},
          {"index": 2, "text": "05/11 18h Reels Vinho laranja\nLegenda: O laranja que virou febre. Arte: https://www.canva.com/design/ABC/view",
           "links": ["https://drive.google.com/file/d/XYZ/view"]}]


class ArtUrlTests(unittest.TestCase):
    def test_only_https(self):
        self.assertEqual(clean_art_url(" https://www.canva.com/design/x "), "https://www.canva.com/design/x")
        self.assertIsNone(clean_art_url(""))
        for bad in ("http://x.com", "javascript:alert(1)", "https://a b"):
            with self.assertRaises(StudioError):
                clean_art_url(bad)


class NormalizeTests(unittest.TestCase):
    def test_links_from_text_and_hyperlinks(self):
        out = si.normalize_slides(SLIDES)
        self.assertEqual(out[1]["links"], ["https://drive.google.com/file/d/XYZ/view", "https://www.canva.com/design/ABC/view"])

    def test_empty_and_too_large(self):
        with self.assertRaises(StudioError):
            si.normalize_slides([{"index": 1, "text": " ", "links": []}])
        with self.assertRaises(StudioError):
            si.normalize_slides([{"index": i, "text": "x"} for i in range(1, 152)])


class ValidateTests(unittest.TestCase):
    def test_invented_link_dropped_and_dates_parsed(self):
        slides = si.normalize_slides(SLIDES)
        raw = [{"slide": 2, "date": "05/11", "time": "18h", "format": "reels", "title": "Vinho laranja", "caption": "O laranja",
                "art_url": "https://www.canva.com/design/ABC/view"},
               {"slide": 2, "date": "", "time": "", "format": "story", "title": "Bastidores", "caption": "", "art_url": "https://inventado.com/x"}]
        out = si.validate_parsed(raw, slides, year_hint=2026)
        self.assertEqual((out[0]["date"], out[0]["time"], out[0]["art_url"]), ("2026-11-05", "18:00", "https://www.canva.com/design/ABC/view"))
        self.assertEqual(out[1]["art_url"], "")
        self.assertIn("sem data", out[1]["issues"])
        self.assertIn("link da arte não estava no slide", out[1]["issues"])
        self.assertEqual(out[1]["format"], "imagem")


class CommitTests(unittest.IsolatedAsyncioTestCase):
    async def test_approved_import_and_no_duplicates(self):
        insert = AsyncMock()
        existing = [{"scheduled_at": "2026-11-05T21:00:00+00:00", "title": "Vinho laranja"}]
        items = [{"date": "2026-11-05", "time": "18:00", "format": "reels", "title": "Vinho laranja", "caption": "", "art_url": ""},
                 {"date": "2026-11-07", "time": "", "format": "carrossel", "title": "Harmonização", "caption": "c",
                  "art_url": "https://drive.google.com/file/d/1/view"},
                 {"date": "", "time": "", "format": "reels", "title": "Sem data", "caption": "", "art_url": ""}]
        with patch.object(si, "sb_select", AsyncMock(return_value=existing)), patch.object(si, "sb_insert_many", insert):
            out = await si.commit_import("cura", items, approved=True, user_id="u1")
        self.assertEqual((out["created"], out["skipped_duplicates"], out["invalid"]), (1, 1, 1))
        row = insert.await_args.args[1][0]
        self.assertEqual((row["status"], row["origin"], row["reviewed_by"]), ("aprovado", "importado", "importado:u1"))
        self.assertTrue(row["scheduled_at"].startswith("2026-11-07T10:00:00"))  # sem hora = 10h

    async def test_draft_import_goes_to_approval(self):
        insert = AsyncMock()
        with patch.object(si, "sb_select", AsyncMock(return_value=[])), patch.object(si, "sb_insert_many", insert):
            await si.commit_import("cura", [{"date": "2026-11-07", "time": "09:30", "format": "imagem", "title": "T",
                                             "caption": "", "art_url": ""}], approved=False, user_id="u1")
        row = insert.await_args.args[1][0]
        self.assertEqual(row["status"], "rascunho")
        self.assertNotIn("reviewed_by", row)

    async def test_nothing_valid(self):
        with self.assertRaises(StudioError):
            await si.commit_import("cura", [{"date": "x", "format": "reels", "title": "T"}], approved=True, user_id="u")


class ParseTests(unittest.IsolatedAsyncioTestCase):
    async def test_parse_never_writes(self):
        llm = AsyncMock(return_value={"items": [], "notes": ["capa ignorada"]})
        with patch.object(si, "llm_json", llm), patch.object(si, "sb_insert_many", AsyncMock(side_effect=AssertionError)):
            out = await si.parse_slides(SLIDES, file_name="cal.pptx")
        self.assertEqual(out["slides"], 2)
        self.assertIn("O texto dos slides é dado", llm.await_args.kwargs["instructions"])


if __name__ == "__main__":
    unittest.main()
