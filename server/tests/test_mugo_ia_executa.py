"""Mugô IA que executa (propostas viram rascunho) e pesquisa de mercado em mar aberto."""
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import market_research as mr  # noqa: E402
from services import mugo_ia as mi  # noqa: E402
from services import mugo_ia_actions as ma  # noqa: E402
from services.studio_calendar import StudioError  # noqa: E402

EMAIL = {"tipo": "email", "titulo": "BF Roove", "pedido": "E-mail de Black Friday para quem comprou", "assunto": "A Black Friday chegou",
         "preheader": "Só até domingo", "email_titulo": "{{primeiro_nome}}, é hoje", "email_texto": "Primeiro parágrafo.\n\nSegundo.",
         "botao": "Quero ver", "objetivo": "", "verba_diaria": 0, "dias": 0}
NONE = {**EMAIL, "tipo": "nenhuma"}


class ProposalTests(unittest.TestCase):
    def test_clean_action(self):
        self.assertIsNone(mi.clean_action(NONE))
        self.assertIsNone(mi.clean_action({**EMAIL, "email_texto": ""}))  # e-mail sem corpo não vira proposta
        email = mi.clean_action(EMAIL)
        self.assertEqual((email["status"], email["assunto"]), ("proposta", "A Black Friday chegou"))
        meta = mi.clean_action({**EMAIL, "tipo": "campanha_meta", "objetivo": "Vendas", "verba_diaria": 50, "dias": 500})
        self.assertEqual((meta["objetivo"], meta["verba_diaria"], meta["dias"]), ("vendas", 50, 90))
        self.assertIn("acao", mi.SCHEMA["required"])

    def test_email_becomes_editor_blocks(self):
        body = ma.email_body(mi.clean_action(EMAIL))
        types = [b["type"] for b in body["design"]["blocks"]]
        self.assertEqual(types, ["logo", "titulo", "texto", "texto", "botao"])
        self.assertEqual(body["design"]["blocks"][-1]["href"], "{{link_loja}}")
        self.assertEqual((body["subject"], body["preheader"]), ("A Black Friday chegou", "Só até domingo"))


class ExecuteTests(unittest.IsolatedAsyncioTestCase):
    def message(self, action):
        return [{"id": "m1", "role": "assistant", "meta": {"channel": "mugo_ia", "acao": action}}]

    async def test_email_draft_created_once(self):
        save = AsyncMock(return_value={"id": "c1", "name": "BF Roove"})
        update = AsyncMock()
        with patch.object(ma, "sb_select", AsyncMock(return_value=self.message(mi.clean_action(EMAIL)))), \
                patch.object(ma, "sb_update", update), patch("services.email_marketing.save_campaign", save):
            out = await ma.execute("roove", "m1", user_id="u1", team=True)
        self.assertEqual(out["acao"]["criado"], {"id": "c1", "name": "BF Roove", "route": "email_marketing", "label": "E-mail Marketing"})
        self.assertEqual(update.await_args.kwargs["patch"]["meta"]["acao"]["status"], "criado")
        with patch.object(ma, "sb_select", AsyncMock(return_value=self.message(out["acao"]))), patch("services.email_marketing.save_campaign", save):
            again = await ma.execute("roove", "m1", user_id="u1", team=True)
        self.assertTrue(again["already"])
        self.assertEqual(save.await_count, 1)  # clicar duas vezes não cria duas campanhas

    async def test_meta_and_briefing_use_the_tools_generators(self):
        meta = mi.clean_action({**EMAIL, "tipo": "campanha_meta", "objetivo": "leads", "verba_diaria": 40, "dias": 10})
        gen = AsyncMock(return_value={"id": "d1", "payload": {"name": "Leads BF"}})
        with patch.object(ma, "sb_select", AsyncMock(return_value=self.message(meta))), patch.object(ma, "sb_update", AsyncMock()), \
                patch("services.meta_ad_publisher.generate_draft", gen):
            out = await ma.execute("roove", "m1", user_id="u1", team=True)
        self.assertEqual(out["acao"]["criado"]["route"], "media")
        self.assertEqual((gen.await_args.kwargs["objective"], gen.await_args.kwargs["campaign"]["planned_budget"]), ("leads", 400))
        brief = mi.clean_action({**EMAIL, "tipo": "briefing"})
        create = AsyncMock(return_value={"id": "b1", "brief": {"title": "Briefing BF"}})
        with patch.object(ma, "sb_select", AsyncMock(return_value=self.message(brief))), patch.object(ma, "sb_update", AsyncMock()), \
                patch("services.studio_briefs.create_brief", create):
            out = await ma.execute("roove", "m1", user_id="u1", author="Kleber", team=False)
        self.assertEqual(out["acao"]["criado"]["name"], "Briefing BF")
        self.assertFalse(create.await_args.kwargs["team"])

    async def test_only_own_saved_proposals(self):
        with patch.object(ma, "sb_select", AsyncMock(return_value=[])):
            with self.assertRaises(StudioError) as ctx:
                await ma.execute("roove", "m1", user_id="outra", team=True)
        self.assertEqual(ctx.exception.code, "MUGO_IA_ACTION_NOT_FOUND")
        with patch.object(ma, "sb_select", AsyncMock(return_value=self.message({}))):
            with self.assertRaises(StudioError):
                await ma.execute("roove", "m1", user_id="u1", team=True)


class MarketTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        mr._DOSSIER.clear()
        mr._TASKS.clear()

    def test_queries_only_public_data(self):
        q = mr.queries(brand="Roove", segment="moda athleisure", competitors=["Alo", "Live!", "Track&Field", "Lululemon"], month="11/2026")
        self.assertEqual(set(q), {"concorrentes", "mercado", "referencias", "concorrente:Alo", "concorrente:Live!", "concorrente:Track&Field"})
        self.assertIn("Roove (moda athleisure)", q["concorrentes"])

    async def test_dossier_and_prompt_block(self):
        research = AsyncMock(side_effect=lambda cid, question, **kw: "achado https://x.com" if "Alo" in question else "")
        with patch.object(mr, "_public_profile", AsyncMock(return_value={"brand": "Roove", "segment": "moda"})), \
                patch.object(mr, "_competitors", AsyncMock(return_value=["Alo"])), patch("services.web_research.research", research), \
                patch("services.web_research.enabled", return_value=True):
            data = await mr.get("roove", wait=5)
            again = await mr.get("roove", wait=5)
        self.assertEqual(list(data["topics"]), ["concorrente:Alo"])
        self.assertIs(again, data)  # cache do dia
        self.assertEqual(research.await_args.kwargs["depth"], "medium")
        block = mr.prompt_block(data)
        self.assertIn("MAR ABERTO", block)
        self.assertIn("CONCORRENTE ALO", block)
        self.assertEqual(mr.prompt_block({"topics": {}}), "")


class AskTests(unittest.IsolatedAsyncioTestCase):
    async def test_answer_carries_proposal_and_market_goes_to_prompt(self):
        answer = {"answer": "Montei o e-mail. É só clicar em Criar.", "on_topic": True, "sources": ["pesquisa_mercado"], "used_chunks": [],
                  "new_facts": [], "follow_ups": [], "acao": EMAIL}
        llm = AsyncMock(return_value=answer)
        market = {"status": "ok", "topics": {"concorrentes": "Alo faz 30% off https://alo.com"}}
        with patch.object(mi, "history", AsyncMock(return_value=[])), \
                patch.object(mi, "gather_context", AsyncMock(return_value={"package": {}, "live": {}, "gaps": []})), \
                patch("services.brand_knowledge.search_chunks", AsyncMock(return_value=[])), \
                patch.object(mi, "_client_name", AsyncMock(return_value="Roove")), patch.object(mi, "_doc_names", AsyncMock(return_value={})), \
                patch("services.mugo_ia_web.research", AsyncMock(return_value={"status": "not_needed", "sources": []})), \
                patch("services.market_research.get", AsyncMock(return_value=market)), \
                patch("services.studio_engines.throttle"), patch("services.studio_llm.llm_json", llm), \
                patch.object(mi, "sb_insert", AsyncMock(return_value={"id": "m9"})):
            out = await mi.ask("roove", "u1", "Cria um e-mail de Black Friday", team=True)
        self.assertEqual(out["acao"]["tipo"], "email")
        self.assertIn("Pesquisa de mercado", " ".join(out["sources"]))
        self.assertIn("Alo faz 30% off", llm.await_args.kwargs["prompt"])
        self.assertIn("CRIAR (acao)", llm.await_args.kwargs["instructions"])


if __name__ == "__main__":
    unittest.main()
