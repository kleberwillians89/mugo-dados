"""Engajamento no Instagram: palavras-chave, simulação, uma resposta por comentário e janela do Direct."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from services import ig_engagement as ie
from services.studio_calendar import StudioError

NOW = datetime.now(timezone.utc)
CREDS = {"connection_id": "c1", "ig_user_id": "1784", "username": "roove", "page_id": "999", "token": "t",
         "scopes": {"instagram_manage_comments", "pages_messaging"}}
RULE = {"id": "r1", "active": True, "keywords": ["quero", "Link"], "media_id": None,
        "public_reply": "Te mandei no Direct, {nome}!", "dm_message": "Oi {nome}, aqui está: https://roove.com.br"}


def comment(cid="111111", text="QUÉRO muito", user="ana", age=timedelta(hours=1), media="555555"):
    return {"comment_id": cid, "media_id": media, "username": user, "text": text, "timestamp": (NOW - age).isoformat()}


class AiGreetingTests(unittest.IsolatedAsyncioTestCase):
    CTX = {"profile": {"keywords_avoid": []}, "context": "{}", "voice": [], "tone": None}
    AI_RULE = {**RULE, "id": "r2", "public_reply": None, "dm_message": "https://roove.com.br", "ai_greeting": True}

    async def test_ai_text_keeps_rule_link(self):
        with patch("services.studio_llm.llm_json", AsyncMock(return_value={"message": "Oi @ana! Que bom que curtiu 💛"})), \
             patch.object(ie, "_post_context", AsyncMock(return_value="post")):
            text = await ie.ai_greeting("roove", comment(), "https://roove.com.br", self.CTX)
        self.assertTrue(text.startswith("Oi @ana!"))
        self.assertIn("https://roove.com.br", text)

    async def test_ai_failure_falls_back_to_rule_text(self):
        with patch("services.studio_llm.llm_json", AsyncMock(side_effect=RuntimeError("fora"))), \
             patch.object(ie, "_post_context", AsyncMock(return_value="")), redirect_stdout(io.StringIO()):
            self.assertEqual(await ie.ai_greeting("roove", comment(), "Oi {nome}!", self.CTX), "Oi @ana!")
            self.assertEqual(await ie.ai_greeting("roove", comment(), "", self.CTX), "Oi @ana! 💛")

    async def test_rule_with_ai_greeting_sends_ai_direct(self):
        reads = AsyncMock(side_effect=[[self.AI_RULE], [comment()], []])
        with patch.object(ie, "get_settings", AsyncMock(return_value={"ai_autoreply": False})), \
             patch.object(ie, "sb_select", reads), patch.object(ie, "credentials", AsyncMock(return_value=CREDS)), \
             patch.object(ie, "refresh_comments", AsyncMock(return_value=0)), patch.object(ie, "sb_insert", AsyncMock()) as insert, \
             patch.object(ie, "_greeting_context", AsyncMock(return_value=self.CTX)) as ctx, \
             patch.object(ie, "ai_greeting", AsyncMock(return_value="Oi @ana! Aqui: https://roove.com.br")), \
             patch.dict("os.environ", {"IG_AUTOREPLY_ENABLED": ""}):
            out = await ie.run_rules("roove")
        self.assertEqual(out["simulated"], 1)
        ctx.assert_awaited_once()
        row = insert.await_args_list[0].args[1]
        self.assertEqual((row["kind"], row["text"]), ("direct", "Oi @ana! Aqui: https://roove.com.br"))


class KeywordTests(unittest.TestCase):
    def test_accents_case_and_whole_word(self):
        self.assertTrue(ie.matches("QUÉRO muito", ["quero"]))
        self.assertTrue(ie.matches("me manda o link pf", ["Link"]))
        self.assertFalse(ie.matches("requerido", ["quero"]))
        self.assertTrue(ie.matches("quero saber o preço", ["preço"]))

    def test_fill_name(self):
        self.assertEqual(ie.fill("Oi {nome}!", "ana"), "Oi @ana!")

    def test_capabilities(self):
        self.assertEqual(ie.capabilities({"instagram_basic"}), {"reply": False, "direct": False})
        self.assertEqual(ie.capabilities(set()), {"reply": True, "direct": True})


class RunRulesTests(unittest.IsolatedAsyncioTestCase):
    def patches(self, comments, done=()):
        reads = AsyncMock(side_effect=[[RULE], comments, list(done)])
        # IA desligada aqui: estes testes cuidam só dos gatilhos (a IA tem os testes de AiAutoreplyTests).
        self._ai_off = patch.object(ie, "get_settings", AsyncMock(return_value={"ai_autoreply": False, "max_per_run": 10}))
        self._ai_off.start()
        self.addCleanup(self._ai_off.stop)
        return (patch.object(ie, "sb_select", reads), patch.object(ie, "credentials", AsyncMock(return_value=CREDS)),
                patch.object(ie, "refresh_comments", AsyncMock(return_value=0)), patch.object(ie, "sb_insert", AsyncMock()))

    async def test_simulates_without_flag_and_never_calls_meta(self):
        p1, p2, p3, p4 = self.patches([comment(), comment(cid="222222", text="adorei", user="bia"), comment(cid="333333", user="roove")])
        with p1, p2, p3, p4 as insert, patch.object(ie, "_graph_post", AsyncMock(side_effect=AssertionError("não deve chamar"))), \
             patch.dict("os.environ", {"IG_AUTOREPLY_ENABLED": ""}):
            out = await ie.run_rules("roove")
        self.assertEqual((out["simulated"], out["sent"], out["live"]), (2, 0, False))
        kinds = sorted(c.args[1]["kind"] for c in insert.await_args_list)
        self.assertEqual(kinds, ["direct", "resposta_publica"])
        self.assertIn("@ana", insert.await_args_list[0].args[1]["text"])

    async def test_already_answered_is_skipped(self):
        done = [{"comment_id": "111111", "kind": "resposta_publica", "rule_id": "r1"}, {"comment_id": "111111", "kind": "direct", "rule_id": "r1"}]
        p1, p2, p3, p4 = self.patches([comment()], done)
        with p1, p2, p3, p4 as insert:
            out = await ie.run_rules("roove")
        self.assertEqual(out["simulated"], 0)
        insert.assert_not_awaited()

    async def test_live_sends_reply_and_private_reply(self):
        p1, p2, p3, p4 = self.patches([comment()])
        graph = AsyncMock(side_effect=[{"id": "r9"}, {"message_id": "m9"}])
        with p1, p2, p3, p4, patch.object(ie, "_graph_post", graph), patch.object(ie, "_page_token", AsyncMock(return_value=("999", "pt"))), \
             patch.dict("os.environ", {"IG_AUTOREPLY_ENABLED": "true"}):
            out = await ie.run_rules("roove")
        self.assertEqual(out["sent"], 2)
        self.assertEqual(graph.await_args_list[0].args[0], "/111111/replies")
        self.assertEqual(graph.await_args_list[1].args[0], "/999/messages")
        self.assertEqual(graph.await_args_list[1].kwargs["json_body"]["recipient"], {"comment_id": "111111"})


class DirectWindowTests(unittest.IsolatedAsyncioTestCase):
    async def test_older_than_7_days_is_blocked(self):
        with self.assertRaises(StudioError) as ctx:
            await ie.send_direct("roove", comment(age=timedelta(days=8)), "oi", creds=CREDS, live=False)
        self.assertEqual(ctx.exception.code, "DIRECT_WINDOW_CLOSED")

    async def test_manual_reply_requires_permission(self):
        creds = {**CREDS, "scopes": {"instagram_basic"}}
        with patch.object(ie, "_comment", AsyncMock(return_value=comment())), patch.object(ie, "credentials", AsyncMock(return_value=creds)):
            with self.assertRaises(StudioError) as ctx:
                await ie.manual_reply("roove", "111111", "Obrigada!", actor="equipe:u")
        self.assertEqual(ctx.exception.code, "IG_PERMISSION_MISSING")



class AiAutoreplyTests(unittest.IsolatedAsyncioTestCase):
    def recent(self, cid="900001", text="Amei esse produto!", user="carla"):
        from datetime import datetime, timezone
        return {**comment(cid=cid, text=text, user=user), "timestamp": datetime.now(timezone.utc).isoformat()}

    async def run_ai(self, comments, *, answer, live=False, claim="act1", handled=None):
        insert = AsyncMock(return_value={"id": claim} if claim else None)
        if claim is None:
            insert.side_effect = Exception("duplicate key")
        update, graph = AsyncMock(), AsyncMock(return_value={"id": "r1"})
        with patch.object(ie, "get_settings", AsyncMock(return_value={"ai_autoreply": True, "max_per_run": 10})), \
             patch.object(ie, "_ai_answer", AsyncMock(return_value=answer)), patch.object(ie, "sb_insert", insert), \
             patch.object(ie, "sb_update", update), patch.object(ie, "_graph_post", graph), \
             patch.dict("os.environ", {"IG_AUTOREPLY_ENABLED": "true" if live else ""}):
            out = await ie.run_ai_replies("roove", creds=CREDS, comments=comments, handled=handled or set())
        return out, insert, update, graph

    async def test_simulated_reply_claims_before_answering(self):
        out, insert, update, graph = await self.run_ai([self.recent()], answer={"reply": "Que bom, Carla! 💛", "needs_human": False, "reason": "", "guard": []})
        self.assertEqual(out["ai_simulated"], 1)
        graph.assert_not_awaited()
        self.assertEqual((insert.await_args.args[1]["kind"], insert.await_args.args[1]["status"]), ("resposta_ia", "pendente"))
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "simulado")

    async def test_live_reply_goes_to_meta(self):
        out, _, update, graph = await self.run_ai([self.recent()], answer={"reply": "Obrigada!", "needs_human": False, "reason": "", "guard": []}, live=True)
        self.assertEqual(out["ai_sent"], 1)
        self.assertEqual(graph.await_args.kwargs["data"], {"message": "Obrigada!"})
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "enviado")

    async def test_sensitive_or_off_brand_goes_to_human_review(self):
        for answer in ({"reply": "Chama no Direct", "needs_human": True, "reason": "reclamação", "guard": []},
                       {"reply": "50% de desconto hoje!", "needs_human": False, "reason": "", "guard": [{"type": "promessa_sem_dado"}]}):
            out, insert, _, graph = await self.run_ai([self.recent()], answer=answer, live=True)
            self.assertEqual(out["ai_review"], 1)
            self.assertEqual(insert.await_args.args[1]["kind"], "revisao")
            graph.assert_not_awaited()

    async def test_already_handled_own_old_or_claimed_elsewhere_is_skipped(self):
        answer = {"reply": "Oi!", "needs_human": False, "reason": "", "guard": []}
        out, insert, _, _ = await self.run_ai([self.recent(cid="1"), self.recent(cid="2", user="roove"), {**self.recent(cid="3"), "timestamp": "2020-01-01T00:00:00+00:00"}],
                                              answer=answer, handled={"1"})
        insert.assert_not_awaited()
        out, _, update, graph = await self.run_ai([self.recent()], answer=answer, live=True, claim=None)
        graph.assert_not_awaited()  # outra execução travou primeiro: não responde duas vezes
        update.assert_not_awaited()

    async def test_brand_guard_is_called_with_keywords(self):
        from services import brand_guard
        with patch.object(brand_guard, "check", return_value=[]) as check, \
             patch("services.studio_calendar.load_profile", AsyncMock(return_value={"profile": {"keywords_avoid": ["barato"]}})), \
             patch.object(ie, "sb_select", AsyncMock(return_value=[])), \
             patch("services.studio_llm.llm_json", AsyncMock(return_value={"reply": "Oi!", "needs_human": False, "reason": ""})):
            out = await ie._ai_answer("roove", self.recent())
        self.assertEqual(check.call_args.kwargs["avoid"][0], "barato")  # antes era posicional e quebrava a sugestão
        self.assertIn("combustível", check.call_args.kwargs["avoid"])  # clichês que soavam forçados
        self.assertEqual(out["reply"], "Oi!")

    async def answer(self, text, llm_reply, *, rows=None):
        llm = AsyncMock(return_value={"reply": llm_reply, "needs_human": False, "reason": ""})

        async def select(table, **kwargs):
            if table == "ig_media":
                return [{"caption": "Bastidores do evento com Rodrigo Mancusi"}] if "media_id" in kwargs.get("filters", {}) else \
                    [{"caption": "A gente não faz post, a gente faz barulho 📣"}]
            if table == ie.ACTIONS:
                return rows or []
            return []
        with patch("services.studio_calendar.load_profile", AsyncMock(return_value={"profile": {"tone_of_voice": "leve"}})), \
             patch.object(ie, "sb_select", AsyncMock(side_effect=select)), patch("services.studio_llm.llm_json", llm):
            out = await ie._ai_answer("mugo", {**self.recent(text=text), "media_id": "m1"})
        return out, llm.await_args.kwargs["prompt"]

    async def test_prompt_has_post_examples_and_comment_type(self):
        rows = [{"kind": "resposta_manual", "text": "Valeu demais, Ana! 🙌", "status": "enviado"}]
        _, prompt = await self.answer("Gente olha sinceramente OS MAIORAIS", "Os maiorais mesmo! Obrigado 🙌", rows=rows)
        self.assertIn("Bastidores do evento com Rodrigo Mancusi", prompt)
        self.assertIn("Valeu demais, Ana!", prompt)
        self.assertIn("TIPO: texto", prompt)
        self.assertIn("a gente faz barulho", prompt)  # voz real da marca

    async def test_emoji_comment_gets_short_reply_or_review(self):
        out, prompt = await self.answer("🔥🔥🔥", "🔥🙌")
        self.assertIn("só emoji", prompt)
        self.assertEqual(out["reply"], "🔥🙌")
        out, _ = await self.answer("❤️❤️❤️", "Que bom que você gostou! Conta pra gente qual parte mais te marcou nesse post")
        self.assertEqual(out["reply"], "")  # longa demais para uma reação: não sai sozinha
        self.assertTrue(out["needs_human"])


if __name__ == "__main__":
    unittest.main()

class DailyAiScheduleTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, *, ai, ai_on):
        ai_mock = AsyncMock(return_value={"ai_sent": 1})
        with patch.object(ie, "list_rules", AsyncMock(return_value=[])), \
             patch.object(ie, "get_settings", AsyncMock(return_value={"ai_autoreply": ai_on, "max_per_run": 10})), \
             patch.object(ie, "credentials", AsyncMock(return_value=CREDS)), \
             patch.object(ie, "refresh_comments", AsyncMock()), \
             patch.object(ie, "sb_select", AsyncMock(return_value=[])), \
             patch.object(ie, "run_ai_replies", ai_mock):
            out = await ie.run_rules("roove", ai=ai)
        return out, ai_mock

    async def test_five_minute_run_never_calls_ai(self):
        out, ai_mock = await self._run(ai=False, ai_on=True)
        ai_mock.assert_not_awaited()
        self.assertEqual(out["sent"], 0)

    async def test_daily_run_answers_only_brands_with_button_on(self):
        _, ai_mock = await self._run(ai=True, ai_on=True)
        self.assertEqual(ai_mock.await_args.kwargs["budget"], ie.AI_DAILY_BUDGET)
        out, ai_mock = await self._run(ai=True, ai_on=False)
        ai_mock.assert_not_awaited()
        self.assertEqual(out["rules"], 0)

    async def test_daily_job_passes_ai_flag(self):
        run = AsyncMock(return_value={})
        with patch.object(ie, "sb_select", AsyncMock(side_effect=[[], [{"client_id": "roove"}]])), \
             patch.object(ie, "run_rules", run):
            await ie.run_all(ai=True)
        self.assertEqual(run.await_args.kwargs, {"ai": True})


class ReplyToneTests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_keep_working_before_tone_migration(self):
        select = AsyncMock(side_effect=[RuntimeError("column reply_tone does not exist"), [{"ai_autoreply": True, "max_per_run": 10}]])
        with patch.object(ie, "sb_select", select):
            out = await ie.get_settings("origami")
        self.assertEqual(out, {"ai_autoreply": True, "max_per_run": 10, "reply_tone": None})

    async def test_saving_tone_keeps_ai_switch_and_toggling_keeps_tone(self):
        upsert = AsyncMock()
        with patch.object(ie, "get_settings", AsyncMock(return_value={"ai_autoreply": True, "max_per_run": 10, "reply_tone": "leve"})), \
             patch.object(ie, "sb_upsert", upsert):
            await ie.save_settings("origami", user_id="u", reply_tone="  próximo   e leve ", set_tone=True)
            row = upsert.await_args.args[1][0]
            self.assertEqual((row["ai_autoreply"], row["reply_tone"]), (True, "próximo e leve"))
            await ie.save_settings("origami", user_id="u", ai_autoreply=False)
            row = upsert.await_args.args[1][0]
            self.assertEqual(row["ai_autoreply"], False)
            self.assertNotIn("reply_tone", row)  # desligar a IA não apaga o tom

    async def test_tone_goes_first_in_the_reply_prompt(self):
        seen = {}

        async def llm(**kw):
            seen["prompt"] = kw["prompt"]
            return {"reply": "Que bom que curtiu! 😊", "needs_human": False, "reason": ""}

        with patch("services.studio_calendar.load_profile", AsyncMock(return_value={"profile": {"tone_of_voice": "sóbrio"}})), \
             patch.object(ie, "get_settings", AsyncMock(return_value={"ai_autoreply": True, "max_per_run": 10, "reply_tone": "próximo e leve"})), \
             patch.object(ie, "sb_select", AsyncMock(return_value=[])), \
             patch.object(ie, "_reply_examples", AsyncMock(return_value={"manual": [], "recent": []})), \
             patch.object(ie, "_brand_voice", AsyncMock(return_value=["Prezados investidores"])), \
             patch("services.studio_llm.llm_json", llm):
            await ie._ai_answer("origami", {"comment_id": "c1", "text": "Adorei a explicação sobre renda fixa", "username": "ana"})
        self.assertTrue(seen["prompt"].startswith("TOM DAS RESPOSTAS DESTA MARCA"))
        self.assertIn("próximo e leve", seen["prompt"])


class RepliesByPostTests(unittest.IsolatedAsyncioTestCase):
    async def test_groups_replies_per_post_with_who_and_status(self):
        actions = [
            {"comment_id": "c1", "media_id": "111", "kind": "resposta_ia", "status": "enviado", "text": "Que bom!", "created_at": "2026-11-04T19:05:00Z"},
            {"comment_id": "c2", "media_id": None, "kind": "revisao", "status": "pendente", "text": "reclamação", "created_at": "2026-11-04T19:04:00Z"},
            {"comment_id": "c3", "media_id": "222", "kind": "resposta_manual", "status": "simulado", "text": "Obrigada", "created_at": "2026-11-03T10:00:00Z"},
        ]
        comments = [{"comment_id": "c1", "media_id": "111", "username": "ana", "text": "amei"},
                    {"comment_id": "c2", "media_id": "111", "username": "bia", "text": "não chegou"},
                    {"comment_id": "c3", "media_id": "222", "username": "caio", "text": "top"}]
        media = [{"media_id": "111", "caption": "Coxinha vegana", "permalink": "https://instagram.com/p/1", "media_type": "IMAGE", "media_url": "https://cdn/1.jpg"}]
        select = AsyncMock(side_effect=[actions, comments, media])
        with patch.object(ie, "sb_select", select):
            out = await ie.replies_by_post("latinas", days=30)
        first, second = out["posts"]
        self.assertEqual(first["media_id"], "111")
        self.assertEqual(first["counts"]["ia"], 1)
        self.assertEqual(first["counts"]["revisao"], 1)  # media_id veio do comentário
        self.assertEqual(first["thumb"], "https://cdn/1.jpg")
        self.assertEqual(second["counts"]["simulado"], 1)
        self.assertEqual(first["replies"][0]["username"], "ana")
        for call in select.await_args_list:
            self.assertEqual(call.kwargs["filters"]["client_id"], "eq.latinas")

    async def test_no_replies_returns_empty_without_extra_reads(self):
        select = AsyncMock(return_value=[])
        with patch.object(ie, "sb_select", select):
            out = await ie.replies_by_post("latinas")
        self.assertEqual(out["posts"], [])
        self.assertEqual(select.await_count, 1)


class InboxAnsweredTests(unittest.IsolatedAsyncioTestCase):
    def test_old_ai_failure_hidden_after_ai_success(self):
        actions = [{"kind": "resposta_ia", "status": "enviado", "text": "Boa!"},
                   {"kind": "resposta_ia", "status": "falhou", "text": "sem crédito"},
                   {"kind": "direct", "status": "falhou", "text": "x"}]
        self.assertEqual([a["status"] for a in ie.visible_actions(actions)], ["enviado", "falhou"])
        self.assertEqual(ie.visible_actions(actions)[1]["kind"], "direct")
        # Falha mais nova que o sucesso continua aparecendo.
        self.assertEqual(len(ie.visible_actions(list(reversed(actions[:2])))), 2)

    def test_credit_balance_exhausted_is_no_credit(self):
        from services.studio_llm import provider_error_code
        self.assertEqual(provider_error_code("http_429:credit_balance_exhausted"), "AI_PROVIDER_QUOTA")
        self.assertIn("sem crédito", ie.failure_reason("AI_PROVIDER_ERROR", "http_429:credit_balance_exhausted"))

    async def test_ai_reply_sent_leaves_open_list(self):
        c = comment()
        sent = {"comment_id": c["comment_id"], "kind": "resposta_ia", "status": "enviado", "text": "Boa!", "created_at": NOW.isoformat()}

        async def select(table, **_):
            return {"ig_comments": [c], "ig_engagement_actions": [sent]}.get(table, [])
        with patch.object(ie, "sb_select", side_effect=select):
            self.assertEqual((await ie.inbox("roove"))["items"], [])
            items = (await ie.inbox("roove", only_open=False))["items"]
        self.assertTrue(items[0]["answered"])
