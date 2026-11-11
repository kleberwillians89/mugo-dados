"""Esteira de agentes (pesquisa → estratégia → redação → briefing visual → revisão → Calendário → revisão interna)
e a sugestão da IA para o ajuste pedido pelo cliente."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import studio_agents as ag
from services import studio_matrix as mx
from services.studio_calendar import StudioError

OPS = [{"id": "o1", "status": "sugerida"}, {"id": "o2", "status": "sugerida"}, {"id": "o3", "status": "descartada"}]
COVERAGE = {"posts_analisados": 40, "campanhas": 2, "aprovados": 5, "ajustes": 1, "lacunas": []}


def content(op_id, guard=None):
    return {"id": op_id, "visual_idea": "Foto em close", "guard": guard or []}


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def run_pipeline(self, *, contents, update=None):
        saved = []

        async def save(table, filters, patch, **kwargs):
            saved.append(patch)
            return [{}]
        exported = {"created": 2, "calendar_item_ids": ["i1", "i2"],
                    "matrix": {"opportunities": [{"id": "o1", "calendar_item_id": "i1"}, {"id": "o2", "calendar_item_id": "i2"}]}}
        update = update or AsyncMock(return_value={})
        with patch.object(ag, "sb_update", AsyncMock(side_effect=save)), \
             patch("services.studio_intelligence.build_content_intelligence", AsyncMock(return_value={})), \
             patch("services.studio_intelligence.coverage", return_value=COVERAGE), \
             patch.object(mx, "generate", AsyncMock(return_value={"id": "m1", "opportunities": OPS, "notes": []})) as gen, \
             patch.object(mx, "create_content", AsyncMock(side_effect=contents)) as write, \
             patch.object(mx, "export_to_calendar", AsyncMock(return_value=exported)) as export, \
             patch("services.studio_calendar.update_item", update), \
             patch("services.studio_engines.generate_briefing", AsyncMock(return_value={})) as brief:
            out = await ag.execute("roove", {"id": "r1", "steps": ag._fresh_steps()}, user_id="u1")
        self.brief = brief
        return out, saved, gen, write, export, update

    async def test_end_to_end_sends_clean_posts_to_internal_review(self):
        out, saved, gen, write, export, update = await self.run_pipeline(
            contents=lambda cid, oid, throttle_calls: content(oid, guard=[{"type": "palavra"}] if oid == "o2" else None))
        self.assertEqual(saved[-1]["status"], "concluida")
        self.assertTrue(all(s["status"] == "feito" for s in out["steps"]))
        self.assertEqual(write.await_count, 2)  # descartada não é escrita
        self.assertFalse(write.await_args.kwargs["throttle_calls"])
        self.assertEqual(sorted(export.await_args.kwargs["ids"]), ["o1", "o2"])
        update.assert_awaited_once_with("roove", "i1", {"status": "em_revisao"}, user_id="u1")  # o2 teve alerta: fica em rascunho
        self.assertIn("1 com alerta", saved[-1]["summary"])
        self.assertIn("direção de arte", saved[-1]["summary"])
        self.assertEqual(sorted(c.args[1] for c in self.brief.await_args_list), ["i1", "i2"])  # briefing técnico de cada post
        self.assertFalse(self.brief.await_args.kwargs["throttle_calls"])

    async def test_a_failed_post_does_not_stop_the_others(self):
        def flaky(cid, oid, throttle_calls):
            if oid == "o1":
                raise StudioError("AI_INVALID_OUTPUT")
            return content(oid)
        out, saved, *_ = await self.run_pipeline(contents=flaky)
        self.assertEqual(saved[-1]["status"], "concluida")
        redacao = next(s for s in out["steps"] if s["key"] == "redacao")
        self.assertIn("1 falharam", redacao["detail"])

    async def test_failure_marks_the_step_and_keeps_the_reason(self):
        out, saved, *_ = await self.run_pipeline(contents=lambda *a, **k: (_ for _ in ()).throw(StudioError("AI_RATE_LIMIT")))
        self.assertEqual(saved[-1]["status"], "falhou")
        self.assertEqual(next(s for s in out["steps"] if s["key"] == "redacao")["status"], "falhou")
        self.assertIn("rode", saved[-1]["error"].lower())


class RunControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_run_at_a_time(self):
        running = {"id": "r1", "status": "rodando", "updated_at": datetime.now(timezone.utc).isoformat(), "steps": []}
        with patch.object(ag, "sb_select", AsyncMock(return_value=[running])):
            with self.assertRaises(StudioError) as raised:
                await ag.start_run("roove", user_id="u1")
        self.assertEqual(raised.exception.code, "AGENTS_RUNNING")

    async def test_stale_run_shows_as_interrupted(self):
        old = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
        stale = {"id": "r1", "status": "rodando", "updated_at": old, "steps": [{"key": "redacao", "status": "rodando"}]}
        with patch.object(ag, "sb_select", AsyncMock(return_value=[stale])), patch.object(ag, "sb_update", AsyncMock()) as upd:
            run = await ag.latest_run("roove")
        self.assertEqual(run["status"], "falhou")
        self.assertIn("interrompida", run["error"])
        self.assertEqual(upd.await_args.kwargs["patch"]["status"], "falhou")

    async def test_needs_pillars_and_platforms(self):
        with patch.object(ag, "sb_select", AsyncMock(return_value=[])), \
             patch.object(ag, "load_profile", AsyncMock(return_value={"profile": {"pillars": [], "editorial_platforms": ["instagram"]}})):
            with self.assertRaises(StudioError) as raised:
                await ag.start_run("roove", user_id="u1")
        self.assertEqual(raised.exception.code, "MATRIX_PILLARS_REQUIRED")


class SuggestionTests(unittest.IsolatedAsyncioTestCase):
    async def test_suggestion_uses_client_note_and_references(self):
        item = {"id": "i1", "format": "reels", "title": "Black Friday", "hook": "Gancho", "caption_draft": "Legenda", "review_note": "Mais curto"}
        llm = AsyncMock(return_value={"gancho": "Novo gancho", "legenda": "Legenda curta", "roteiro": "Cena 1", "ideia_imagem": "Close", "o_que_mudou": "Encurtei"})
        with patch.object(ag, "sb_select", AsyncMock(return_value=[item])), patch.object(ag, "sb_update", AsyncMock()) as upd, \
             patch("services.studio_references.list_references", AsyncMock(return_value=[{"url": "https://pin.it/x", "note": None}])), \
             patch.object(ag, "load_profile", AsyncMock(return_value={"profile": {}})), \
             patch("services.studio_intelligence.build_content_intelligence", AsyncMock(return_value={})), \
             patch("services.studio_llm.llm_json", llm):
            out = await ag.suggest_adjustment("roove", "i1", "Deixa mais curto e com cara de Pinterest")
        prompt = llm.await_args.kwargs["prompt"]
        self.assertIn("Deixa mais curto", prompt)
        self.assertIn("https://pin.it/x", prompt)
        self.assertEqual((out["hook"], out["caption_draft"], out["summary"]), ("Novo gancho", "Legenda curta", "Encurtei"))
        self.assertEqual(upd.await_args.kwargs["patch"]["ai_suggestion"]["note"], "Deixa mais curto e com cara de Pinterest")

    async def test_apply_writes_the_post_and_clears(self):
        suggestion = {"hook": "Novo", "caption_draft": "Nova legenda", "script": "Cena 1", "visual_idea": "Close"}
        with patch.object(ag, "sb_select", AsyncMock(return_value=[{"id": "i1", "ai_suggestion": suggestion}])), \
             patch.object(ag, "sb_update", AsyncMock(return_value=[{"id": "i1"}])) as upd, \
             patch("services.studio_calendar.update_item", AsyncMock()) as update:
            await ag.apply_suggestion("roove", "i1", user_id="u1")
        update.assert_awaited_once_with("roove", "i1", {"hook": "Novo", "caption_draft": "Nova legenda"}, user_id="u1")
        self.assertEqual(upd.await_args.kwargs["patch"], {"script": "Cena 1", "visual_idea": "Close", "ai_suggestion": None})

    async def test_client_adjustment_schedules_a_suggestion(self):
        from services import studio_team as st
        with patch("services.studio_chat.post_decision", AsyncMock()), patch.object(st, "sb_insert", AsyncMock()), \
             patch.object(st, "_send", AsyncMock()), patch("services.studio_history.record", AsyncMock()), \
             patch.object(ag, "schedule_adjustment") as schedule:
            await st.notify_team("roove", {"id": "i1", "title": "Reels"}, "ajuste_solicitado", actor_name="Gabi", comment="Mais curto")
            await st.notify_team("roove", {"id": "i1", "title": "Reels"}, "aprovado", actor_name="Gabi")
        schedule.assert_called_once_with("roove", "i1", "Mais curto")

    def test_client_never_sees_the_suggestion(self):
        import asyncio
        from services import studio_client as sc
        with patch.object(sc, "open_request_item_ids", AsyncMock(return_value=set())), \
             patch.object(sc, "client_can_see", return_value=True):
            out = asyncio.run(sc.client_items("roove", [{"id": "i1", "ai_suggestion": {"hook": "x"}}]))
        self.assertNotIn("ai_suggestion", out[0])


if __name__ == "__main__":
    unittest.main()
