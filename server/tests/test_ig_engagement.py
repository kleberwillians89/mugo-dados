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


if __name__ == "__main__":
    unittest.main()
