"""Kanban na criação: Redação a partir da tarefa, Redação → E-mail Marketing e vínculos com a tarefa."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import AsyncMock, patch

from services import redacao_from_task as rft
from services import studio_documents, email_marketing
from services.studio_calendar import StudioError

CTX = {"task": {"id": "t1", "title": "Black Ruah"}, "brief_id": "b1", "suggested_deliverable": "Legenda do Reels",
       "context": {"summary": "Black com frete grátis", "offer": "Frete grátis", "avoid": ["prometer mais de 50%"]}}


class PureTests(unittest.TestCase):
    def test_kind_and_instruction_from_brief(self):
        self.assertEqual(rft.kind_for("Roteiro do Reels"), "roteiro")
        self.assertEqual(rft.kind_for("E-mail de lançamento"), "email")
        self.assertEqual(rft.kind_for("Peça"), "livre")
        text = rft.brief_instruction(CTX, "Legenda do Reels")
        for piece in ("Entregável: Legenda do Reels", "Resumo: Black com frete grátis", "Evitar: prometer mais de 50%"):
            self.assertIn(piece, text)


class DocumentTests(unittest.IsolatedAsyncioTestCase):
    async def test_ai_writes_from_brief_and_links_to_task(self):
        create = AsyncMock(return_value={"id": "d1", "title": "Black Ruah · Legenda do Reels", "kind": "legenda"})
        update = AsyncMock(return_value={"id": "d1", "title": "Black Ruah · Legenda do Reels", "kind": "legenda"})
        ai = AsyncMock(return_value={"text": "Primeiro parágrafo.\n\nSegundo <b>."})
        claim = {"acquired": True, "link_status": "pending"}
        reserve = AsyncMock(return_value=claim)
        complete = AsyncMock()
        with patch.object(rft, "task_context", AsyncMock(return_value=CTX)), patch.object(rft, "_safe_linked", AsyncMock(return_value=[])), \
             patch.object(studio_documents, "create_document", create), patch.object(studio_documents, "update_document", update), \
             patch.object(studio_documents, "ai_write", ai), patch.object(rft, "claim_work", reserve), \
             patch.object(rft, "complete_work", complete):
            out = await rft.document_from_task("ruah", "t1", {}, user_id="u1")
        self.assertEqual(out["created"]["id"], "d1")
        self.assertEqual(create.await_args.args[1], {"title": "Black Ruah · Legenda do Reels", "kind": "legenda"})
        self.assertIn("Resumo: Black com frete grátis", ai.await_args.args[1]["instruction"])
        self.assertEqual(update.await_args.args[2]["content_html"], "<p>Primeiro parágrafo.</p><p>Segundo &lt;b&gt;.</p>")
        reserve.assert_awaited_once()
        self.assertEqual(reserve.await_args.args, ("ruah", "t1"))
        self.assertEqual(reserve.await_args.kwargs["module"], "redacao")
        self.assertEqual(reserve.await_args.kwargs["deliverable"], "Legenda do Reels")
        complete.assert_awaited_once_with(claim, "d1")

    async def test_existing_document_is_resumed_not_duplicated(self):
        with patch.object(rft, "task_context", AsyncMock(return_value=CTX)), \
             patch.object(rft, "_safe_linked", AsyncMock(return_value=[{"record_id": "d9", "deliverable": "Legenda do Reels"}])), \
             patch.object(studio_documents, "get_document", AsyncMock(return_value={"id": "d9", "title": "Antigo", "status": "rascunho"})), \
             patch.object(studio_documents, "create_document", AsyncMock()) as create:
            out = await rft.document_from_task("ruah", "t1", {}, user_id="u1")
        self.assertIsNone(out["created"])
        self.assertEqual(out["existing"][0]["id"], "d9")
        create.assert_not_awaited()


class EmailTests(unittest.IsolatedAsyncioTestCase):
    async def test_document_becomes_email_draft_linked_to_the_task(self):
        save = AsyncMock(return_value={"id": "e1", "name": "Black", "status": "rascunho"})
        link = AsyncMock()
        with patch.object(studio_documents, "get_document", AsyncMock(return_value={"id": "d1", "title": "Black", "content_text": "Um.\n\nDois."})), \
             patch.object(email_marketing, "save_campaign", save), patch.object(rft, "tasks_of_document", AsyncMock(return_value=["t1"])), \
             patch.object(rft, "record_link", link):
            out = await rft.document_to_email("ruah", "d1", user_id="u1")
        self.assertEqual(out["campaign"]["id"], "e1")
        blocks = save.await_args.args[1]["design"]["blocks"]
        self.assertEqual([b["type"] for b in blocks], ["logo", "titulo", "texto", "texto", "botao"])
        self.assertEqual((link.await_args.args[1], link.await_args.kwargs["module"]), ("t1", "email_marketing"))

    async def test_empty_document_is_refused(self):
        with patch.object(studio_documents, "get_document", AsyncMock(return_value={"id": "d1", "title": "x", "content_text": " "})):
            with self.assertRaises(StudioError):
                await rft.document_to_email("ruah", "d1", user_id="u1")

    async def test_link_validates_module_and_record(self):
        with self.assertRaises(StudioError):
            await rft.link_to_task("ruah", "t1", {}, module="financeiro", record_id="x")
        with self.assertRaises(StudioError):
            await rft.link_to_task("ruah", "t1", {}, module="social_media", record_id="a;drop")
        link = AsyncMock()
        with patch.object(rft, "task_context", AsyncMock(return_value=CTX)), patch.object(rft, "record_link", link):
            await rft.link_to_task("ruah", "t1", {}, module="social_media", record_id="m-1", deliverable="Matriz")
        self.assertEqual(link.await_args.kwargs["record_id"], "m-1")


if __name__ == "__main__":
    unittest.main()
