"""Engajamento no Instagram: palavras-chave, simulação, uma resposta por comentário e janela do Direct."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
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
        self.assertEqual(check.call_args.kwargs["avoid"], ["barato"])  # antes era posicional e quebrava a sugestão
        self.assertEqual(out["reply"], "Oi!")


if __name__ == "__main__":
    unittest.main()