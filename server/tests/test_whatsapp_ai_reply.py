"""Atendimento IA em WhatsApp: somente rascunho, autorização e isolamento por empresa."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from services import whatsapp_ai_reply as wa
from services.studio_calendar import StudioError

THREAD = "11111111-2222-4333-8444-555555555555"
RECENT = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

async def fake_select(table, **kwargs):
    if table == "whatsapp_threads":
        if kwargs.get("filters", {}).get("client_id") != "eq.roove":
            return []
        return [{"id": THREAD, "client_id": "roove", "number_id": "n1", "last_inbound_at": RECENT}]
    if table == "whatsapp_numbers":
        return [{"id": "n1", "status": "active"}]
    if table == "whatsapp_messages":
        return [{"direction": "in", "text": "Quanto custa o frete?", "type": "text"}]
    raise AssertionError(table)


class WhatsAppAiDraftTests(unittest.IsolatedAsyncioTestCase):
    async def test_draft_only_uses_tenant_context_and_never_sends(self):
        with patch.object(wa, "sb_select", side_effect=fake_select), \
             patch("services.brand_knowledge.knowledge_for_prompt", AsyncMock(return_value="Marca Roove")), \
             patch("services.brand_knowledge.search_chunks", AsyncMock(return_value=[])), \
             patch("services.studio_calendar.load_profile", AsyncMock(return_value={"profile": {}})), \
             patch("services.studio_llm.llm_json", AsyncMock(return_value={"draft": "Você pode informar o CEP para verificarmos?", "needs_human": True, "reason": "O frete não foi informado"})) as llm:
            out = await wa.suggest_reply("roove", THREAD)
        self.assertEqual(out["draft"], "Você pode informar o CEP para verificarmos?")
        self.assertTrue(out["approval_required"])
        self.assertFalse(out["sent"])
        self.assertEqual(llm.await_args.kwargs["client_id"], "roove")
        self.assertNotIn("wa_id", llm.await_args.kwargs["prompt"])
        self.assertNotIn("access_token", llm.await_args.kwargs["prompt"])

    async def test_cross_tenant_conversation_rejected(self):
        with patch.object(wa, "sb_select", side_effect=fake_select):
            with self.assertRaises(StudioError) as ctx:
                await wa.suggest_reply("ruah", THREAD)
        self.assertEqual(ctx.exception.code, "CONVERSATION_NOT_FOUND")

    async def test_expired_window_rejected_before_ai(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        with patch.object(wa, "sb_select", AsyncMock(return_value=[{"id": THREAD, "number_id": "n1", "last_inbound_at": old}])):
            with self.assertRaises(StudioError) as ctx:
                await wa.suggest_reply("roove", THREAD)
        self.assertEqual(ctx.exception.code, "OUTSIDE_WINDOW")

    async def test_invalid_conversation_rejected(self):
        with self.assertRaises(StudioError):
            await wa.suggest_reply("roove", "invalid")


if __name__ == "__main__":
    unittest.main()
