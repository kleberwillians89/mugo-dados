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
    async def run_pipeline(self, *, contents, update=None, options=None, phase=1, run_extra=None, ops=None):
        saved = []

        async def save(table, filters, patch, **kwargs):
            saved.append(patch)
            return [{}]
        exported = {"created": 2, "calendar_item_ids": ["i1", "i2"],
                    "matrix": {"opportunities": [{"id": "o1", "calendar_item_id": "i1"}, {"id": "o2", "calendar_item_id": "i2"}]}}
        update = update or AsyncMock(return_value={})
        ops = ops if ops is not None else OPS
        run = {"id": "r1", "steps": ag._fresh_steps(), "options": {"auto": True} if options is None else options, **(run_extra or {})}
        with patch.object(ag, "sb_update", AsyncMock(side_effect=save)), patch.object(ag, "sb_select", AsyncMock(return_value=[])), \
             patch("services.studio_intelligence.build_content_intelligence", AsyncMock(return_value={})), \
             patch("services.studio_intelligence.coverage", return_value=COVERAGE), \
             patch.object(mx, "generate", AsyncMock(return_value={"id": "m1", "opportunities": ops, "notes": []})) as gen, \
             patch.object(mx, "get_matrix", AsyncMock(return_value={"id": "m1", "opportunities": ops})), \
             patch.object(mx, "create_content", AsyncMock(side_effect=contents)) as write, \
             patch.object(mx, "export_to_calendar", AsyncMock(return_value=exported)) as export, \
             patch("services.studio_calendar.update_item", update), \
             patch("services.studio_engines.generate_briefing", AsyncMock(return_value={})) as brief:
            out = await ag.execute("roove", run, user_id="u1", phase=phase)
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


class TwoPhaseTests(PipelineTests):
    async def test_phase_one_stops_at_the_matrix(self):
        out, saved, gen, write, *_ = await self.run_pipeline(contents=lambda *a, **k: content("o1"),
                                                             options={"focus": "Black Friday", "weeks": 2})
        self.assertEqual(saved[-1]["status"], "aguardando")
        self.assertIn("Gerar conteúdo", saved[-1]["summary"])
        self.assertEqual(gen.await_args.args[1], {"focus": "Black Friday", "weeks": 2})
        write.assert_not_awaited()
        steps = {s["key"]: s["status"] for s in out["steps"]}
        self.assertEqual((steps["pesquisa"], steps["estrategia"], steps["redacao"]), ("feito", "feito", "pendente"))
        self.assertIn("2 semanas", next(s for s in out["steps"] if s["key"] == "estrategia")["detail"])

    async def test_phase_two_writes_only_what_the_team_kept(self):
        ops = [{"id": "o1", "status": "selecionada"}, {"id": "o2", "status": "sugerida"}, {"id": "o3", "status": "descartada"}]
        out, saved, gen, write, export, _ = await self.run_pipeline(contents=lambda cid, oid, throttle_calls: content(oid),
                                                                    options={}, phase=2, run_extra={"matrix_id": "m1"}, ops=ops)
        gen.assert_not_awaited()
        self.assertEqual([c.args[1] for c in write.await_args_list], ["o1"])
        self.assertEqual(saved[-1]["status"], "concluida")

    async def test_phase_two_without_matrix_fails_clearly(self):
        out, saved, *_ = await self.run_pipeline(contents=lambda *a, **k: content("o1"), options={}, phase=2)
        self.assertEqual(saved[-1]["status"], "falhou")
        self.assertIn("Matriz", saved[-1]["error"])

    def test_targets_skip_discarded_and_exported(self):
        ops = [{"id": "a", "status": "sugerida"}, {"id": "b", "status": "exportada"}, {"id": "c", "status": "descartada"},
               {"id": "d", "status": "sugerida", "calendar_item_id": "x"}]
        self.assertEqual([o["id"] for o in ag.matrix_targets(ops)], ["a"])

    def test_research_summary_mentions_the_new_sources(self):
        text = ag.research_summary(COVERAGE, {"voz_do_publico": "x", "produtos_mais_vendidos": [{}, {}],
                                              "saude_da_marca": {"indice": 74}, "concorrentes": {"cadastrados": ["A"]},
                                              "negocio": {"conhecimento_da_marca": "y"}})
        for part in ("voz do público", "2 produtos", "74/100", "1 concorrentes", "material enviado"):
            self.assertIn(part, text)


PROFILE = {"profile": {"pillars": [{"name": "Produto"}], "editorial_platforms": ["instagram"]}}


class RunControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_busy_pipeline_queues_the_request(self):
        running = {"id": "r1", "status": "aguardando", "updated_at": datetime.now(timezone.utc).isoformat(), "steps": []}
        with patch.object(ag, "sb_select", AsyncMock(return_value=[running])), \
             patch.object(ag, "load_profile", AsyncMock(return_value=PROFILE)), \
             patch.object(ag, "sb_insert", AsyncMock(side_effect=lambda t, row: {"id": "r2", **row})) as ins, \
             patch.object(ag, "_background") as bg:
            run = await ag.start_run("roove", user_id="u1", focus="Natal", weeks=3, brief_id="b1")
        self.assertEqual(run["status"], "na_fila")
        self.assertEqual(ins.await_args.args[1]["options"], {"focus": "Natal", "weeks": 3, "brief_id": "b1"})
        bg.assert_not_called()

    async def test_free_pipeline_starts_now(self):
        with patch.object(ag, "sb_select", AsyncMock(return_value=[])), \
             patch.object(ag, "load_profile", AsyncMock(return_value=PROFILE)), \
             patch.object(ag, "sb_insert", AsyncMock(side_effect=lambda t, row: {"id": "r2", **row})), \
             patch.object(ag, "_background") as bg:
            run = await ag.start_run("roove", user_id="u1")
        self.assertEqual(run["status"], "rodando")
        bg.assert_called_once()
        bg.call_args.args[0].close()

    async def test_invalid_period_fails_before_queueing(self):
        with patch.object(ag, "sb_select", AsyncMock(return_value=[])), \
             patch.object(ag, "load_profile", AsyncMock(return_value=PROFILE)), patch.object(ag, "sb_insert", AsyncMock()) as ins:
            with self.assertRaises(StudioError) as raised:
                await ag.start_run("roove", user_id="u1", weeks=12)
        self.assertEqual(raised.exception.code, "MATRIX_PERIOD_INVALID")
        ins.assert_not_awaited()

    async def test_continue_only_from_waiting(self):
        with patch.object(ag, "sb_update", AsyncMock(return_value=[])):
            with self.assertRaises(StudioError) as raised:
                await ag.continue_run("roove", "r1", user_id="u1")
        self.assertEqual(raised.exception.code, "AGENTS_NOT_WAITING")
        with patch.object(ag, "sb_update", AsyncMock(return_value=[{"id": "r1", "status": "rodando"}])) as upd, \
             patch.object(ag, "_background") as bg:
            await ag.continue_run("roove", "r1", user_id="u1")
        self.assertEqual(upd.await_args.kwargs["filters"]["status"], "eq.aguardando")
        bg.call_args.args[0].close()

    async def test_next_in_queue_starts_when_free(self):
        queued = [{"id": "r2", "status": "na_fila", "created_by": "u1"}, {"id": "r3", "status": "na_fila"}]
        with patch.object(ag, "sb_select", AsyncMock(return_value=queued)), \
             patch.object(ag, "sb_update", AsyncMock(return_value=[{"id": "r2", "status": "rodando"}])) as upd, \
             patch.object(ag, "_background") as bg:
            nxt = await ag.start_next("roove")
        self.assertEqual(nxt["id"], "r2")
        self.assertEqual(upd.await_args.kwargs["filters"]["id"], "eq.r2")
        bg.call_args.args[0].close()
        with patch.object(ag, "sb_select", AsyncMock(return_value=[{"id": "r1", "status": "aguardando"}, *queued])), \
             patch.object(ag, "sb_update", AsyncMock()) as upd:
            self.assertIsNone(await ag.start_next("roove"))
        upd.assert_not_awaited()

    async def test_latest_prefers_active_and_counts_queue(self):
        now = datetime.now(timezone.utc).isoformat()
        rows = [{"id": "r3", "status": "na_fila", "updated_at": now}, {"id": "r2", "status": "aguardando", "updated_at": now},
                {"id": "r1", "status": "concluida", "updated_at": now}]
        with patch.object(ag, "sb_select", AsyncMock(return_value=rows)):
            run = await ag.latest_run("roove")
        self.assertEqual((run["id"], run["queued"]), ("r2", 1))

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
