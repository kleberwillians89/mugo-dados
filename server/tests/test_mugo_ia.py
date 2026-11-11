"""Mugoverso IA: responde tudo do mundo do cliente com o contexto inteiro dele, sem vazar o que é só da equipe."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import mugo_ia as mi
from services.studio_calendar import StudioError

PACKAGE = {"marca": {"tone_of_voice": "elegante"}, "kpis": [{"id": "revenue", "valor": 50000}],
           "saude_da_marca": {"indice": 71, "alertas_abertos": [{"tipo": "termo", "termo": "golpe"}]},
           "concorrentes": {"cadastrados": ["Marca X"]}, "lacunas": ["sem_metas_no_mes"]}
ANSWER = {"answer": "O faturamento foi de R$ 50 mil.", "on_topic": True, "sources": ["kpis", "inventada", "documentos"],
          "used_chunks": [1], "new_facts": ["A marca não faz desconto em dezembro"], "follow_ups": ["E os concorrentes?"]}


class ContextTests(unittest.IsolatedAsyncioTestCase):
    async def gather(self, team):
        with patch("services.studio_intelligence.build_content_intelligence", AsyncMock(return_value=PACKAGE)), \
             patch.object(mi, "_clipping", AsyncMock(return_value=[{"manchete": "X lança perfume"}])), \
             patch.object(mi, "_upcoming_posts", AsyncMock(return_value=[{"pauta": "Reels do Oud"}])), \
             patch.object(mi, "_alerts", AsyncMock(return_value=[{"termo": "golpe"}])), \
             patch.object(mi, "_briefs", AsyncMock(return_value=[{"titulo": "Natal"}])), \
             patch.object(mi, "_tasks", AsyncMock(side_effect=RuntimeError("fora"))):
            with redirect_stdout(io.StringIO()):
                return await mi.gather_context("ruah", team=team)

    async def test_team_reads_everything_and_failed_source_is_a_gap(self):
        ctx = await self.gather(team=True)
        self.assertEqual(set(ctx["live"]), {"clipping", "proximos_posts", "alertas", "briefings"})
        self.assertEqual(ctx["gaps"], ["tarefas"])
        self.assertIn("alertas_abertos", ctx["package"]["saude_da_marca"])
        prompt = mi.build_prompt(context=ctx, chunks=[{"content": "Tabela de preços"}], past=[], question="Como estamos?")
        for text in ("Marca X", "X lança perfume", "Reels do Oud", "golpe", "Tabela de preços", "sem_metas_no_mes", "tarefas"):
            self.assertIn(text, prompt)

    async def test_client_never_gets_team_only_data(self):
        ctx = await self.gather(team=False)
        self.assertEqual(set(ctx["live"]), {"clipping", "proximos_posts"})
        self.assertNotIn("alertas_abertos", ctx["package"]["saude_da_marca"])
        self.assertEqual(ctx["package"]["saude_da_marca"]["indice"], 71)
        self.assertNotIn("golpe", mi.build_prompt(context=ctx, chunks=[], past=[], question="Oi"))
        self.assertIn("alertas_abertos", PACKAGE["saude_da_marca"])  # o pacote em cache não é alterado


class AskTests(unittest.IsolatedAsyncioTestCase):
    async def ask(self, answer, team=True):
        context = {"package": PACKAGE, "live": {"clipping": [{"manchete": "x"}]}, "gaps": []}
        inserts = AsyncMock(return_value={"id": "m2"})
        with patch.object(mi, "history", AsyncMock(return_value=[])), \
             patch.object(mi, "gather_context", AsyncMock(return_value=context)) as gather, \
             patch("services.brand_knowledge.search_chunks", AsyncMock(return_value=[{"content": "Preços", "document_id": "d1"}])), \
             patch.object(mi, "_client_name", AsyncMock(return_value="Ruah")), \
             patch.object(mi, "_doc_names", AsyncMock(return_value={"d1": "Tabela 2026.pdf"})), \
             patch("services.studio_engines.throttle"), \
             patch("services.studio_llm.llm_json", AsyncMock(return_value=answer)) as llm, \
             patch.object(mi, "sb_insert", inserts):
            out = await mi.ask("ruah", "u1", "  Quanto  faturamos? ", team=team)
        return out, llm, inserts, gather

    async def test_answer_carries_sources_follow_ups_and_coverage(self):
        out, llm, inserts, gather = await self.ask(ANSWER)
        self.assertEqual(out["sources"], ["Indicadores", "Documentos enviados", "Documento: Tabela 2026.pdf"])
        self.assertEqual(out["follow_ups"], ["E os concorrentes?"])
        self.assertIn("Concorrentes", out["coverage"]["read"])
        self.assertIn("sem_metas_no_mes", out["coverage"]["gaps"])
        self.assertIn("Ruah", llm.await_args.kwargs["instructions"])
        self.assertEqual(gather.await_args.kwargs["team"], True)
        user_row, bot_row = inserts.await_args_list[0].args[1], inserts.await_args_list[1].args[1]
        self.assertEqual(user_row["content"], "Quanto faturamos?")
        self.assertEqual(user_row["meta"], {"channel": "mugo_ia"})
        self.assertEqual(bot_row["meta"]["channel"], "mugo_ia")

    async def test_answer_is_personal_name_tone_and_audience(self):
        context = {"package": {**PACKAGE, "marca": {"tone_of_voice": "leve, com humor sutil"}}, "live": {}, "gaps": []}
        llm = AsyncMock(return_value=ANSWER)
        with patch.object(mi, "history", AsyncMock(return_value=[])), patch.object(mi, "gather_context", AsyncMock(return_value=context)), \
             patch("services.brand_knowledge.search_chunks", AsyncMock(return_value=[])), patch.object(mi, "_client_name", AsyncMock(return_value="Curavino")), \
             patch.object(mi, "_doc_names", AsyncMock(return_value={})), patch("services.studio_engines.throttle"), \
             patch("services.studio_llm.llm_json", llm), patch.object(mi, "sb_insert", AsyncMock(return_value={"id": "m"})):
            await mi.ask("curavino", "u1", "Como estamos?", team=True, person="Kleber Willians")
        text = llm.await_args.kwargs["instructions"]
        for part in ("Mugoverso IA da marca Curavino", "Kleber", "leve, com humor sutil", "colega da equipe Mugô", "O que eu faria agora"):
            self.assertIn(part, text)
        self.assertNotIn("Willians", text)  # só o primeiro nome
        client_voice = mi.voice({}, person="", team=False, name="Curavino")
        self.assertIn("não use nome", client_voice["person"])
        self.assertIn("da própria Curavino", client_voice["who"])

    async def test_off_topic_drops_facts_and_sources(self):
        out, *_ = await self.ask({**ANSWER, "on_topic": False, "answer": "Só falo sobre a Ruah."})
        self.assertEqual((out["sources"], out["new_facts"]), ([], []))

    async def test_empty_question_and_empty_answer(self):
        with self.assertRaises(StudioError):
            await mi.ask("ruah", "u1", " ", team=True)
        with self.assertRaises(StudioError) as raised:
            await self.ask({**ANSWER, "answer": "  "})
        self.assertEqual(raised.exception.code, "AI_INVALID_OUTPUT")

    async def test_history_is_separated_from_the_brand_agent(self):
        with patch.object(mi, "sb_select", AsyncMock(return_value=[{"id": "2"}, {"id": "1"}])) as sel:
            rows = await mi.history("ruah", "u1")
        self.assertEqual([r["id"] for r in rows], ["1", "2"])
        self.assertEqual(sel.await_args.kwargs["filters"]["meta->>channel"], "eq.mugo_ia")
        from services import brand_agent as ba
        with patch.object(ba, "sb_select", AsyncMock(return_value=[])) as sel:
            await ba.history("ruah", "u1")
        self.assertEqual(sel.await_args.kwargs["filters"]["meta->>channel"], "is.null")


if __name__ == "__main__":
    unittest.main()
