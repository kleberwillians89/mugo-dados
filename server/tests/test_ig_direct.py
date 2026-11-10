"""Direct do Instagram: quem recebe o oi, quando a IA responde, quando para (equipe) e modo teste."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from services import ig_direct as dm

NOW = datetime.now(timezone.utc)
ON = {"welcome_enabled": True, "welcome_followers_only": True, "welcome_content": "https://ruah.com.br", "ai_enabled": False}


class DecideTests(unittest.TestCase):
    def test_follower_first_message_gets_welcome(self):
        self.assertEqual(dm.decide(first=True, follows=True, settings=ON, human_active=False), "oi")

    def test_non_follower_skipped_when_followers_only(self):
        self.assertEqual(dm.decide(first=True, follows=False, settings=ON, human_active=False), "nao_segue")
        self.assertEqual(dm.decide(first=True, follows=False, settings={**ON, "welcome_followers_only": False}, human_active=False), "oi")

    def test_ai_answers_the_rest_and_team_pauses_everything(self):
        settings = {**ON, "ai_enabled": True}
        self.assertEqual(dm.decide(first=False, follows=True, settings=settings, human_active=False), "ia")
        self.assertEqual(dm.decide(first=True, follows=False, settings=settings, human_active=False), "ia")
        self.assertEqual(dm.decide(first=True, follows=True, settings=settings, human_active=True), "equipe_respondendo")

    def test_clean_content_unwraps_links(self):
        self.assertEqual(dm.clean_content("Grupo: {https://chat.whatsapp.com/abc}  "), "Grupo: https://chat.whatsapp.com/abc")
        self.assertIsNone(dm.clean_content("   "))


class ProcessTests(unittest.IsolatedAsyncioTestCase):
    def pending(self, mid="m1", sender="555", text="oi, quanto custa?"):
        return {"id": f"id-{mid}", "client_id": "ruah", "sender_id": sender, "mid": mid, "direction": "in", "text": text,
                "status": "processando", "created_at": (NOW - timedelta(minutes=1)).isoformat()}

    async def run_process(self, *, settings, thread, follows=True, live=False, history=False):
        claimed = [self.pending()]
        updates = []

        async def update(table, *, filters, patch, returning="representation"):
            updates.append((filters, patch))
            return claimed if patch.get("status") == "processando" else []
        upsert = AsyncMock()
        with patch.object(dm, "sb_update", side_effect=update), patch.object(dm, "sb_upsert", upsert), \
             patch.object(dm, "sb_select", AsyncMock(return_value=thread)), \
             patch.object(dm, "get_settings", AsyncMock(return_value=settings)), \
             patch.object(dm, "person", AsyncMock(return_value={"username": "ana", "name": "Ana", "follows": follows})), \
             patch.object(dm, "earlier_history", AsyncMock(return_value=history)), \
             patch.object(dm, "_brand_context", AsyncMock(return_value={"profile": {}, "context": "{}", "knowledge": "", "voice": [], "tone": None})), \
             patch.object(dm, "welcome_text", AsyncMock(return_value="Oi @ana! Obrigada por seguir 💛 https://ruah.com.br")), \
             patch.object(dm, "_send", AsyncMock(return_value="mid-out")) as send, \
             patch("services.ig_engagement.credentials", AsyncMock(return_value={"ig_user_id": "1784"})), \
             patch("services.ig_engagement._page_token", AsyncMock(return_value=("999", "pt"))), \
             patch("services.ig_engagement.autoreply_enabled", return_value=live):
            out = await dm.process_client("ruah")
        final = [p for f, p in updates if "processed_at" in p and p.get("status") not in ("processando", "pendente", "ignorado") or p.get("error")]
        return out, send, upsert, final

    async def test_welcome_simulated_without_flag(self):
        out, send, upsert, final = await self.run_process(settings=ON, thread=[self.pending()])
        self.assertEqual((out["oi"], out["simulated"]), (1, 1))
        send.assert_not_awaited()
        row = upsert.await_args.args[1][0]
        self.assertTrue(row["by_app"] and row["mid"].startswith("sim:") and row["reply_kind"] == "oi")

    async def test_welcome_sent_live(self):
        out, send, upsert, _ = await self.run_process(settings=ON, thread=[self.pending()], live=True)
        send.assert_awaited_once()
        self.assertEqual(upsert.await_args.args[1][0]["mid"], "mid-out")

    async def test_old_conversation_does_not_get_first_welcome(self):
        out, send, _, final = await self.run_process(settings=ON, thread=[self.pending()], history=True)
        self.assertEqual(out["oi"], 0)
        self.assertTrue(any(p.get("error") == "desligado" for p in final))

    async def test_team_reply_pauses(self):
        echo = {"id": "x", "direction": "out", "by_app": False, "text": "oi", "created_at": (NOW - timedelta(hours=1)).isoformat()}
        out, send, _, final = await self.run_process(settings={**ON, "ai_enabled": True}, thread=[echo, self.pending()])
        self.assertEqual(out["skipped"], 1)
        self.assertTrue(any(p.get("error") == "equipe_respondendo" for p in final))

    async def test_ai_review_does_not_send(self):
        with patch.object(dm, "ai_reply", AsyncMock(return_value={"reply": "", "needs_human": True, "reason": "reclamação"})):
            old = {"id": "y", "direction": "in", "by_app": False, "text": "oi", "created_at": (NOW - timedelta(days=2)).isoformat()}
            out, send, upsert, final = await self.run_process(settings={**ON, "ai_enabled": True}, thread=[old, self.pending()])
        self.assertEqual(out["review"], 1)
        upsert.assert_not_awaited()


class InboxTests(unittest.IsolatedAsyncioTestCase):
    async def test_groups_threads_and_flags_waiting_review_window(self):
        rows = [
            {"sender_id": "1", "direction": "in", "text": "tem frete?", "by_app": False, "status": "revisao", "follows": True,
             "username": "ana", "created_at": (NOW - timedelta(hours=1)).isoformat()},
            {"sender_id": "1", "direction": "out", "text": "Oi!", "by_app": True, "status": "respondido", "follows": None,
             "username": None, "created_at": (NOW - timedelta(hours=2)).isoformat()},
            {"sender_id": "2", "direction": "out", "text": "valeu", "by_app": False, "status": "respondido", "follows": None,
             "username": "bia", "created_at": (NOW - timedelta(days=3)).isoformat()},
        ]
        with patch.object(dm, "sb_select", AsyncMock(return_value=rows)):
            out = await dm.inbox("ruah")
        first, second = out["threads"]
        self.assertEqual((first["username"], first["waiting"], first["review"], first["window_open"], first["messages"]),
                         ("ana", True, True, True, 2))
        self.assertEqual((second["waiting"], second["window_open"]), (False, False))
        self.assertEqual(out["counts"], {"conversations": 2, "waiting": 1, "review": 1})

    async def test_manual_reply_blocked_after_24h(self):
        old = [{"created_at": (NOW - timedelta(hours=30)).isoformat()}]
        with patch.object(dm, "sb_select", AsyncMock(return_value=old)):
            with self.assertRaises(dm.StudioError) as ctx:
                await dm.manual_reply("ruah", "1", "oi")
        self.assertEqual(ctx.exception.code, "DIRECT_WINDOW_CLOSED")

    async def test_manual_reply_counts_as_team(self):
        recent = [{"created_at": (NOW - timedelta(hours=1)).isoformat()}]
        upsert, update = AsyncMock(), AsyncMock(return_value=[])
        with patch.object(dm, "sb_select", AsyncMock(return_value=recent)), patch.object(dm, "sb_upsert", upsert), \
             patch.object(dm, "sb_update", update), patch.object(dm, "_send", AsyncMock(return_value="mid-9")), \
             patch("services.ig_engagement.credentials", AsyncMock(return_value={"ig_user_id": "1784"})), \
             patch("services.ig_engagement._page_token", AsyncMock(return_value=("999", "pt"))):
            out = await dm.manual_reply("ruah", "1", " Temos sim! ")
        row = upsert.await_args.args[1][0]
        self.assertEqual((out["status"], row["by_app"], row["text"], row["mid"]), ("enviado", False, "Temos sim!", "mid-9"))
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "respondido")
