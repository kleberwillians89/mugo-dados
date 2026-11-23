"""Direcionamento Criativo da peça (Calendário): salvo na pauta, a IA só sugere, vai na tarefa de quem cria."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import studio_briefing_send as bs
from services import studio_calendar as sc
from services import studio_client as scl
from services import studio_engines as se
from services.studio_history import changed_fields, describe_patch

BRIEF_ID = "0b6f2c1e-6a43-4b7e-9d1a-3f0f0c9d2a11"
DIRECTION = {"concept": "Verão sem peso", "texts": "Capa: 3 perfumes leves\nCTA: comenta o seu", "references": "Post de 12/10",
             "instructions": "Frascos no mármore, luz natural"}
ITEM = {"id": "i1", "title": "3 perfumes", "format": "carrossel", "scheduled_at": "2026-11-20T22:00:00+00:00",
        "visual_idea": "Frascos", "creative_direction": DIRECTION, "signals": {}}


class CleanTests(unittest.TestCase):
    def test_keeps_only_known_fields_trimmed(self):
        out = sc.clean_creative_direction({"concept": "  Ideia  ", "texts": "", "outro": "x", "brief_id": BRIEF_ID.upper()})
        self.assertEqual(out, {"concept": "Ideia", "brief_id": BRIEF_ID})

    def test_invalid_brief_and_empty_clear(self):
        self.assertEqual(sc.clean_creative_direction({"brief_id": "nao-e-uuid"}), {})
        self.assertEqual(sc.clean_creative_direction(None), {})
        self.assertEqual(len(sc.clean_creative_direction({"concept": "a" * 900})["concept"]), 300)


class SaveTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_saves_with_the_post_scoped_by_client(self):
        with patch.object(sc, "sb_update", AsyncMock(return_value=[{"id": "i1"}])) as update:
            await sc.update_item("roove", "i1", {"creative_direction": {**DIRECTION, "lixo": "x"}}, user_id="u")
        self.assertEqual(update.await_args.kwargs["filters"], {"client_id": "eq.roove", "id": "eq.i1"})
        self.assertEqual(update.await_args.kwargs["patch"], {"creative_direction": DIRECTION})

    async def test_other_edits_do_not_touch_the_direction(self):
        with patch.object(sc, "sb_update", AsyncMock(return_value=[{"id": "i1"}])) as update:
            await sc.update_item("roove", "i1", {"caption_draft": "nova"}, user_id="u")
        self.assertNotIn("creative_direction", update.await_args.kwargs["patch"])

    async def test_create_only_sends_column_when_written(self):
        with patch.object(sc, "sb_insert_many", AsyncMock(return_value=[{"id": "n"}])) as insert:
            await sc.create_item("roove", {"scheduled_at": "2026-11-20T19:00:00-03:00", "format": "imagem", "title": "x"}, user_id="u")
            self.assertNotIn("creative_direction", insert.await_args.args[1][0])
            await sc.create_item("roove", {"scheduled_at": "2026-11-20T19:00:00-03:00", "format": "imagem", "title": "x",
                                           "creative_direction": {"concept": "Ideia"}}, user_id="u")
            self.assertEqual(insert.await_args.args[1][0]["creative_direction"], {"concept": "Ideia"})

    def test_history_records_only_real_changes(self):
        self.assertEqual(changed_fields({"creative_direction": DIRECTION}, {"creative_direction": dict(DIRECTION)}), {})
        self.assertIn("editou o direcionamento criativo", describe_patch({"creative_direction": DIRECTION}))


class ClientViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_does_not_receive_the_internal_direction(self):
        with patch.object(scl, "open_request_item_ids", AsyncMock(return_value=set())), patch.object(scl, "client_can_see", lambda i, o: True):
            items = await scl.client_items("roove", [{**ITEM, "status": "em_revisao"}])
        self.assertNotIn("creative_direction", items[0])

    def test_client_cannot_patch_it(self):
        self.assertNotIn("creative_direction", scl.CLIENT_FIELDS)


class TaskTests(unittest.IsolatedAsyncioTestCase):
    def test_direction_comes_first_for_every_role_and_brief_goes_as_reference(self):
        ref = {"brief": {"title": "Black Friday", "summary": "Decant em foco", "deliverables": ["Carrossel"]}}
        for role in bs.ROLES:
            text = bs.build_text(ITEM, role, None, ref)
            self.assertIn("DIRECIONAMENTO CRIATIVO", text)
            self.assertIn("Título / conceito: Verão sem peso", text)
            self.assertIn("Capa: 3 perfumes leves", text)
            self.assertIn("BRIEFING DE REFERÊNCIA: Black Friday", text)
            self.assertLess(text.index("DIRECIONAMENTO CRIATIVO"), text.index("BRIEFING DE REFERÊNCIA"))

    def test_reference_survives_long_role_fields(self):
        long_item = {**ITEM, "visual_idea": "x" * 5000}
        text = bs.build_text(long_item, "designer", None, {"brief": {"title": "BF", "summary": "Resumo"}})
        self.assertLessEqual(len(text), 4000)
        self.assertIn("BRIEFING DE REFERÊNCIA: BF", text)

    async def test_selected_brief_is_read_from_the_briefing_scoped_by_client(self):
        select = AsyncMock(return_value=[{"id": BRIEF_ID, "brief": {"title": "BF"}}])
        with patch("services.ig_supabase.sb_select", select):
            ref = await bs.reference_brief("roove", {**ITEM, "creative_direction": {"brief_id": BRIEF_ID}})
        self.assertEqual(ref["brief"]["title"], "BF")
        self.assertEqual(select.await_args.kwargs["filters"], {"client_id": "eq.roove", "id": f"eq.{BRIEF_ID}"})

    async def test_matrix_post_falls_back_to_the_matrix_brief(self):
        select = AsyncMock(side_effect=[[{"matrix_id": "m1"}], [{"brief_snapshot": {"title": "Da Matriz"}}]])
        with patch("services.ig_supabase.sb_select", select):
            ref = await bs.reference_brief("roove", {"id": "i", "matrix_opportunity_id": "op1"})
        self.assertEqual(ref, {"title": "Da Matriz"})
        self.assertTrue(all(c.kwargs["filters"]["client_id"] == "eq.roove" for c in select.await_args_list))

    async def test_reference_failure_never_blocks_the_task(self):
        with patch("services.ig_supabase.sb_select", AsyncMock(side_effect=RuntimeError("down"))):
            self.assertIsNone(await bs.reference_brief("roove", {**ITEM, "creative_direction": {"brief_id": BRIEF_ID}}))


class SuggestTests(unittest.IsolatedAsyncioTestCase):
    async def test_ai_only_suggests_and_never_saves(self):
        llm = AsyncMock(return_value={"concept": "Sugestão", "texts": "Capa nova", "references": "", "instructions": "Luz suave"})
        with patch.object(se, "_load_item", AsyncMock(return_value=ITEM)), patch.object(se, "throttle"), \
             patch.object(se, "build_content_intelligence", AsyncMock(return_value={})), patch.object(se, "coverage", lambda i: {}), \
             patch.object(se, "_post_references", AsyncMock(return_value=[])), patch.object(se, "to_prompt", lambda i: ""), \
             patch.object(se, "language_rule", lambda m: ""), patch.object(se, "llm_json", llm), \
             patch("services.ig_supabase.sb_update", AsyncMock()) as update:
            out = await se.suggest_creative_direction("roove", "i1", {"concept": "Minha ideia"}, "mais curto")
        self.assertEqual(out["suggestion"], {"concept": "Sugestão", "texts": "Capa nova", "instructions": "Luz suave"})
        update.assert_not_awaited()
        prompt = llm.await_args.kwargs["prompt"]
        self.assertIn("Minha ideia", prompt)  # parte do que a pessoa escreveu
        self.assertIn("mais curto", prompt)


if __name__ == "__main__":
    unittest.main()
