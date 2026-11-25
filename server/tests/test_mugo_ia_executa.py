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
         "botao": "Quero ver", "objetivo": "", "verba_diaria": 0, "dias": 0, "wa_corpo": "", "wa_rodape": ""}
NONE = {**EMAIL, "tipo": "nenhuma"}


class ProposalTests(unittest.TestCase):
    def test_clean_action(self):
        self.assertIsNone(mi.clean_action(NONE))
        self.assertIsNone(mi.clean_action({**EMAIL, "email_texto": ""}))  # e-mail sem corpo não vira proposta
        email = mi.clean_action(EMAIL)
        self.assertEqual((email["status"], email["assunto"]), ("proposta", "A Black Friday chegou"))
        meta = mi.clean_action({**EMAIL, "tipo": "campanha_meta", "objetivo": "Vendas", "verba_diaria": 50, "dias": 500})
        self.assertEqual((meta["objetivo"], meta["verba_diaria"], meta["dias"]), ("vendas", 50, 90))
        self.assertIn("acoes", mi.SCHEMA["required"])
        wa = mi.clean_action({**EMAIL, "tipo": "whatsapp_modelo", "titulo": "Roove Early Access · Convite",
                              "wa_corpo": "{{1}}, o grupo First Access abriu {{2}}. Entra aqui {{1}}", "wa_rodape": "Roove"})
        self.assertEqual(wa["wa_corpo"], "Oi, {{1}}, o grupo First Access abriu . Entra aqui")
        self.assertRegex(wa["wa_nome"], r"^roove_early_access_convite_\d{8}$")
        package = mi.clean_actions([EMAIL, NONE, {**EMAIL, "tipo": "whatsapp_modelo", "wa_corpo": "Oi {{1}}, entra no grupo!"}] * 3)
        self.assertEqual(len(package), 6)  # até 6 peças; "nenhuma" cai fora

    def test_email_becomes_editor_blocks(self):
        body = ma.email_body(mi.clean_action(EMAIL))
        types = [b["type"] for b in body["design"]["blocks"]]
        self.assertEqual(types, ["logo", "titulo", "texto", "texto", "botao"])
        self.assertEqual(body["design"]["blocks"][-1]["href"], "{{link_loja}}")
        self.assertEqual((body["subject"], body["preheader"]), ("A Black Friday chegou", "Só até domingo"))


class ExecuteTests(unittest.IsolatedAsyncioTestCase):
    def message(self, action):
        return [{"id": "m1", "role": "assistant", "meta": {"channel": "mugo_ia", "acao": action}}]

    def package(self, actions):
        return [{"id": "m1", "role": "assistant", "meta": {"channel": "mugo_ia", "acoes": actions}}]

    async def test_package_creates_each_piece_and_whatsapp_goes_to_meta_approval(self):
        wa = mi.clean_action({**EMAIL, "tipo": "whatsapp_modelo", "wa_corpo": "Oi {{1}}, o First Access da Roove abriu. Quer entrar no grupo?"})
        actions = [mi.clean_action(EMAIL), wa]
        update = AsyncMock()
        native = AsyncMock(return_value={"id": "t1", "name": wa["wa_nome"], "status": "PENDING"})
        with patch.object(ma, "sb_select", AsyncMock(return_value=self.package(actions))), patch.object(ma, "sb_update", update), \
                patch("services.whatsapp_native.active_number_ids", AsyncMock(return_value=["n1"])), \
                patch("services.whatsapp_native.create_template", native):
            out = await ma.execute("roove", "m1", user_id="u1", team=True, item=1)
        self.assertEqual(out["acao"]["criado"]["route"], "whatsapp")
        self.assertEqual(out["acao"]["criado"]["status"], "PENDING")
        sent = native.await_args.kwargs
        self.assertEqual((sent["category"], sent["examples"], sent["number_id"]), ("MARKETING", ["Ana"], None))
        saved = update.await_args.kwargs["patch"]["meta"]["acoes"]
        self.assertEqual([a["status"] for a in saved], ["proposta", "criado"])  # o e-mail segue esperando o próprio clique
        with patch.object(ma, "sb_select", AsyncMock(return_value=self.package(actions))):
            with self.assertRaises(StudioError):
                await ma.execute("roove", "m1", user_id="u1", team=True, item=5)

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
                  "new_facts": [], "follow_ups": [], "acoes": [EMAIL, {**EMAIL, "tipo": "whatsapp_modelo", "wa_corpo": "Oi {{1}}, entra no grupo da Roove?"}]}
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
        self.assertEqual([a["tipo"] for a in out["acoes"]], ["email", "whatsapp_modelo"])
        self.assertIn("Pesquisa de mercado", " ".join(out["sources"]))
        self.assertIn("Alo faz 30% off", llm.await_args.kwargs["prompt"])
        self.assertIn("CRIAR (acoes)", llm.await_args.kwargs["instructions"])



class ScreenTests(unittest.TestCase):
    def test_screen_focuses_the_help_and_unknown_screen_is_ignored(self):
        ctx = {"package": {}, "live": {}, "gaps": []}
        text = mi.build_prompt(context=ctx, chunks=[], past=[], question="Melhora este texto", screen="redacao")
        self.assertIn("TELA ATUAL: Redação", text)
        self.assertLess(text.index("TELA ATUAL"), text.index("ÚLTIMA MENSAGEM"))
        self.assertNotIn("TELA ATUAL", mi.build_prompt(context=ctx, chunks=[], past=[], question="x", screen="<script>"))



class LevelUpTests(unittest.IsolatedAsyncioTestCase):
    def test_template_button_goes_to_meta_and_bad_link_is_refused(self):
        from services.whatsapp_native import WhatsAppNativeError, validate_template_input
        out = validate_template_input(name="roove_first_access", category="MARKETING", language="pt_BR",
                                      body="Oi {{1}}, o First Access abriu.", examples=["Ana"],
                                      buttons=[{"text": "Entrar no grupo", "url": "https://chat.whatsapp.com/abc123"}])
        self.assertEqual(out["components"][-1], {"type": "BUTTONS", "buttons": [{"type": "URL", "text": "Entrar no grupo",
                                                                               "url": "https://chat.whatsapp.com/abc123"}]})
        with self.assertRaises(WhatsAppNativeError):
            validate_template_input(name="roove_x", category="MARKETING", language="pt_BR", body="Oi tudo bem", examples=[],
                                    buttons=[{"text": "Entrar", "url": "http://inseguro.com"}])

    def test_card_edits_set_the_group_link(self):
        wa = mi.clean_action({**EMAIL, "tipo": "whatsapp_modelo", "wa_corpo": "Oi {{1}}, entra no grupo da Roove?",
                              "wa_botao_texto": "Entrar no grupo", "wa_botao_url": "não sei"})
        self.assertEqual(wa["wa_botao_url"], "")  # link inválido da IA não passa
        done = ma.apply_edits(wa, {"wa_botao_url": "https://chat.whatsapp.com/xyz"})
        self.assertEqual((done["wa_botao_url"], done["wa_botao_texto"]), ("https://chat.whatsapp.com/xyz", "Entrar no grupo"))
        with self.assertRaises(StudioError):
            ma.apply_edits(wa, {"wa_botao_url": "chat.whatsapp.com/xyz"})

    async def test_button_is_sent_with_the_template(self):
        wa = {**mi.clean_action({**EMAIL, "tipo": "whatsapp_modelo", "wa_corpo": "Oi {{1}}, entra no grupo da Roove?",
                                 "wa_botao_texto": "Entrar no grupo", "wa_botao_url": ""}), "wa_botao_url": "https://chat.whatsapp.com/g"}
        native = AsyncMock(return_value={"id": "t", "name": "x", "status": "PENDING"})
        with patch("services.whatsapp_native.active_number_ids", AsyncMock(return_value=["n"])), \
                patch("services.whatsapp_native.create_template", native):
            await ma._submit_template("roove", wa)
        self.assertEqual(native.await_args.kwargs["buttons"], [{"text": "Entrar no grupo", "url": "https://chat.whatsapp.com/g"}])

    def test_instructions_talk_like_a_senior_and_know_the_channels(self):
        text = mi.INSTRUCTIONS.format(name="Roove", person="Kleber", tone="sensorial", who="um colega")
        for part in ("INTENÇÃO real", "MODELO DE MENSAGEM DO WHATSAPP BUSINESS", "botão de link", "variações"):
            self.assertIn(part, text)
        self.assertNotIn("até 14 linhas", text)
        self.assertGreaterEqual(mi.HISTORY_CHARS, 2000)

    async def test_strong_model_falls_back_when_unavailable(self):
        calls = []

        async def llm(**kw):
            calls.append(kw["model"])
            if kw["model"] != mi.FALLBACK_MODEL:
                raise StudioError("AI_PROVIDER_ERROR")
            return {"answer": "ok", "on_topic": True, "sources": [], "used_chunks": [], "new_facts": [], "follow_ups": [], "acoes": []}
        with patch.object(mi, "history", AsyncMock(return_value=[])), \
                patch.object(mi, "gather_context", AsyncMock(return_value={"package": {}, "live": {}, "gaps": []})), \
                patch("services.brand_knowledge.search_chunks", AsyncMock(return_value=[])), \
                patch.object(mi, "_client_name", AsyncMock(return_value="Roove")), patch.object(mi, "_doc_names", AsyncMock(return_value={})), \
                patch("services.mugo_ia_web.research", AsyncMock(return_value={"status": "not_needed", "sources": []})), \
                patch("services.market_research.get", AsyncMock(return_value={})), patch("services.studio_engines.throttle"), \
                patch("services.studio_llm.llm_json", llm), patch.object(mi, "sb_insert", AsyncMock(return_value={"id": "m"})):
            out = await mi.ask("roove", "u1", "Oi", team=True)
        self.assertEqual(out["answer"], "ok")
        self.assertEqual(calls, [mi.model(), mi.FALLBACK_MODEL])


if __name__ == "__main__":
    unittest.main()
