"""Social Media → Redação: editor de texto da marca, IA da marca e envio ao Calendário sem duplicar."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import studio_documents as docs
from services import team_access as ta
from services.studio_calendar import StudioError

PROFILE = {"pillars": [], "keywords_avoid": ["barato"], "content_language": "pt-BR"}


class HtmlTests(unittest.TestCase):
    def test_nothing_executable_is_saved(self):
        html = '<p onclick="x()">Oi</p><script>alert(1)</script><a href="javascript:alert(1)">l</a><iframe src="x"></iframe>'
        clean = docs.clean_html(html)
        self.assertNotIn("script", clean)
        self.assertNotIn("onclick", clean)
        self.assertNotIn("javascript:", clean)
        self.assertNotIn("iframe", clean)
        self.assertIn("<p>Oi</p>", clean)

    def test_text_keeps_paragraphs(self):
        self.assertEqual(docs.html_to_text("<h1>Título</h1><p>Um &amp; dois</p><ul><li>a</li><li>b</li></ul>"), "Título\nUm & dois\na\nb")


class CrudTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_saves_html_and_text_for_the_brand(self):
        insert = AsyncMock(return_value={"id": "d1"})
        with patch.object(docs, "sb_insert", insert):
            await docs.create_document("ruah", {"title": " Release Oud ", "kind": "release", "content_html": "<p>Texto</p>"}, user_id="u1")
        row = insert.await_args.args[1]
        self.assertEqual((row["client_id"], row["title"], row["kind"], row["content_text"]), ("ruah", "Release Oud", "release", "Texto"))

    async def test_update_is_scoped_to_the_brand(self):
        update = AsyncMock(return_value=[{"id": "d1"}])
        with patch.object(docs, "sb_update", update):
            await docs.update_document("ruah", "d1", {"content_html": "<p>Novo</p>"}, user_id="u1")
        self.assertEqual(update.await_args.kwargs["filters"], {"client_id": "eq.ruah", "id": "eq.d1"})
        self.assertEqual(update.await_args.kwargs["patch"]["content_text"], "Novo")

    async def test_other_brand_document_is_not_found(self):
        with patch.object(docs, "sb_update", AsyncMock(return_value=[])):
            with self.assertRaises(StudioError) as ctx:
                await docs.update_document("roove", "d1", {"title": "x"}, user_id="u1")
        self.assertEqual(ctx.exception.code, "DOCUMENT_NOT_FOUND")


class AITests(unittest.IsolatedAsyncioTestCase):
    async def call(self, data, llm_out):
        llm = AsyncMock(return_value=llm_out)
        with patch.object(docs, "load_profile", AsyncMock(return_value={"profile": PROFILE})), \
             patch.object(docs, "build_content_intelligence", AsyncMock(return_value={"marca": {}})), \
             patch.object(docs, "llm_json", llm), patch.object(docs, "throttle"):
            return await docs.ai_write("ruah", data), llm

    async def test_rewrite_uses_selection_and_cleans_markdown(self):
        out, llm = await self.call({"action": "reescrever", "kind": "legenda", "selection": "Oud barato", "instruction": "mais elegante"},
                                   {"texto": "## **Oud** — para presentear"})
        self.assertEqual(out["text"], "Oud, para presentear")
        prompt = llm.await_args.kwargs["prompt"]
        self.assertIn("TRECHO:\nOud barato", prompt)
        self.assertIn("PEDIDO DA EQUIPE: mais elegante", prompt)
        self.assertEqual(llm.await_args.kwargs["client_id"], "ruah")  # auditoria anti-vazamento da marca

    async def test_selection_actions_need_a_selection(self):
        with self.assertRaises(StudioError) as ctx:
            await docs.ai_write("ruah", {"action": "encurtar", "selection": " "})
        self.assertEqual(ctx.exception.code, "DOCUMENT_SELECTION_REQUIRED")

    async def test_titles(self):
        out, _ = await self.call({"action": "titulos", "document_text": "Texto"}, {"titulos": ["A", "", "B"]})
        self.assertEqual(out["titles"], ["A", "B"])


class CalendarTests(unittest.IsolatedAsyncioTestCase):
    DOC = {"id": "d1", "client_id": "ruah", "title": "Legenda Oud", "content_text": "Texto do post", "calendar_item_id": None}

    async def test_first_send_creates_draft_post(self):
        create = AsyncMock(return_value={"id": "i1"})
        update = AsyncMock(return_value=[{"id": "d1"}])
        with patch.object(docs, "get_document", AsyncMock(return_value=self.DOC)), patch.object(docs, "create_item", create), \
             patch.object(docs, "sb_update", update):
            out = await docs.to_calendar("ruah", "d1", {"scheduled_at": "2026-11-20T19:00:00-03:00", "channel": "tiktok", "format": "video"}, user_id="u1")
        self.assertEqual((out["created"], out["calendar_item_id"]), (True, "i1"))
        row = create.await_args.args[1]
        self.assertEqual((row["channel"], row["format"], row["caption_draft"]), ("tiktok", "video", "Texto do post"))
        self.assertEqual(update.await_args.kwargs["filters"]["calendar_item_id"], "is.null")

    async def test_resend_updates_the_same_draft_instead_of_duplicating(self):
        create = AsyncMock()
        upd = AsyncMock(return_value={"id": "i1"})
        with patch.object(docs, "get_document", AsyncMock(return_value={**self.DOC, "calendar_item_id": "i1"})), \
             patch.object(docs, "sb_select", AsyncMock(return_value=[{"id": "i1", "status": "rascunho"}])), \
             patch.object(docs, "update_item", upd), patch.object(docs, "create_item", create):
            out = await docs.to_calendar("ruah", "d1", {}, user_id="u1")
        create.assert_not_awaited()
        self.assertEqual((out["created"], out["updated"]), (False, True))
        self.assertEqual(upd.await_args.args[2]["caption_draft"], "Texto do post")

    async def test_approved_post_is_not_touched(self):
        upd = AsyncMock()
        with patch.object(docs, "get_document", AsyncMock(return_value={**self.DOC, "calendar_item_id": "i1"})), \
             patch.object(docs, "sb_select", AsyncMock(return_value=[{"id": "i1", "status": "aprovado"}])), patch.object(docs, "update_item", upd):
            out = await docs.to_calendar("ruah", "d1", {}, user_id="u1")
        upd.assert_not_awaited()
        self.assertEqual((out["created"], out["updated"]), (False, False))

    async def test_double_click_race_removes_the_extra_post(self):
        delete = AsyncMock()
        with patch.object(docs, "get_document", AsyncMock(side_effect=[self.DOC, {**self.DOC, "calendar_item_id": "i0"}])), \
             patch.object(docs, "create_item", AsyncMock(return_value={"id": "i9"})), patch.object(docs, "sb_update", AsyncMock(return_value=[])), \
             patch.object(docs, "delete_item", delete):
            out = await docs.to_calendar("ruah", "d1", {"scheduled_at": "2026-11-20T19:00:00-03:00"}, user_id="u1")
        delete.assert_awaited_once_with("ruah", "i9")
        self.assertEqual((out["created"], out["calendar_item_id"]), (False, "i0"))

    def test_routes_belong_to_social_media(self):
        self.assertEqual(ta.route_module("PATCH", "/api/clients/c1/studio/documents/d1"), ("social_media", "social_media.edit"))
        self.assertEqual(ta.route_module("GET", "/api/clients/c1/studio/documents"), ("social_media", "social_media.view"))


if __name__ == "__main__":
    unittest.main()
