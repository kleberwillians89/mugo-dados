"""Convite "quer ver o resumo?": só pelo WhatsApp oficial, relatório validado antes, clique idempotente."""
from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routes import hooks
from services import studio_messages as sm
from services.studio_calendar import StudioError

CONTACT = {"id": "k1", "name": "Nasser Alves", "phone": "5511971201557", "role": None, "receives": ["trafego"], "is_primary": True}
CFG = {"MUGOZAP_FUNCTION_URL": "https://crm.supabase.co/functions/v1/mugozap-api", "MUGOZAP_ANON_KEY": "anon",
       "MUGOZAP_WORKER_KEY": "wk", "MUGOZAP_TEAM_MEMBER_ID": "tm1"}
NOW = datetime.now(timezone.utc).isoformat()
INVITE = {"id": "inv1", "client_id": "cura", "contact_id": "k1", "report_kind": "trafego", "provider_message_id": "wamid.CONVITE",
          "status": "aguardando", "answer_message_id": None, "created_at": NOW, "sent_by": "u1"}
REPLY = {"provider_message_id": "wamid.RESPOSTA", "context_message_id": "wamid.CONVITE", "wa_id": "551171201557", "answer": "Sim, quero ver"}


class AnswerTests(unittest.TestCase):
    def test_answers(self):
        self.assertEqual(sm.invite_answer("Sim, quero ver"), "sim")
        self.assertEqual(sm.invite_answer("Agora não"), "nao")
        self.assertIsNone(sm.invite_answer("👍"))


class SendInviteTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_official_whatsapp(self):
        with patch.dict(os.environ, {k: "" for k in CFG}):
            with self.assertRaises(StudioError) as err:
                await sm.send_invite("cura", contact_id="k1", user_id="u1")
        self.assertEqual(err.exception.code, "MUGOZAP_REQUIRED")

    async def test_report_is_validated_before_asking(self):
        with patch.dict(os.environ, CFG), patch.object(sm, "build_message", AsyncMock(side_effect=StudioError("NO_STORE_DATA"))), \
             patch.object(sm, "deliver", AsyncMock()) as deliver:
            with self.assertRaises(StudioError) as err:
                await sm.send_invite("cura", contact_id="k1", user_id="u1")
        self.assertEqual(err.exception.code, "NO_STORE_DATA")
        deliver.assert_not_awaited()

    async def test_invite_is_recorded_with_the_whatsapp_message_id(self):
        built = {"_contact": CONTACT, "params": {"nome": "Nasser", "marca": "Curavino", "periodo": "23/10 a 29/10"}}
        with patch.dict(os.environ, CFG), patch.object(sm, "build_message", AsyncMock(side_effect=[{}, built])), \
             patch.object(sm, "deliver", AsyncMock(return_value={"status": "enviado", "provider_message_id": "wamid.CONVITE"})), \
             patch.object(sm, "sb_insert", AsyncMock()) as insert:
            await sm.send_invite("cura", contact_id="k1", user_id="u1")
        self.assertEqual(insert.await_args.args[1]["provider_message_id"], "wamid.CONVITE")
        self.assertEqual(insert.await_args.args[1]["report_kind"], "trafego")
        self.assertEqual(insert.await_args.args[1]["sent_by"], None)  # "u1" não é uuid: não quebra o registro do convite


class ReplyTests(unittest.IsolatedAsyncioTestCase):
    async def run_reply(self, reply=REPLY, invite=INVITE, claimed=True, text_ok=True):
        update = AsyncMock(side_effect=lambda *a, **k: [{"id": "inv1"}] if claimed or "answer_message_id" not in k["filters"] else [])
        text = AsyncMock(return_value={"ok": text_ok} if text_ok else {"ok": False, "code": "HTTP_400"})
        with patch.dict(os.environ, CFG), patch.object(sm, "sb_select", AsyncMock(return_value=[invite] if invite else [])), \
             patch.object(sm, "list_contacts", AsyncMock(return_value=[CONTACT])), patch.object(sm, "sb_update", update), \
             patch("services.automation_reports.report_text", self.report), patch.object(sm, "_record_response", AsyncMock()), \
             patch.object(sm, "mugozap_text", text), patch.object(sm, "_log", AsyncMock()), redirect_stdout(io.StringIO()):
            result = await sm.handle_invite_reply(reply)
        return result, update, text

    def setUp(self):
        self.report = AsyncMock(return_value="Olá, Nasser! Resumo da Curavino...")

    async def test_yes_sends_the_report_as_free_text_to_the_same_number(self):
        result, update, text = await self.run_reply()
        self.assertEqual(result, {"ok": True, "answer": "sim"})
        self.assertEqual(text.await_args.kwargs["wa_id"], "551171201557")  # sem o 9º dígito: mesmo contato
        self.assertTrue(text.await_args.kwargs["text"].startswith("Olá, Nasser! Resumo"))
        self.assertEqual(update.await_args_list[0].kwargs["filters"]["answer_message_id"], "is.null")  # trava antes de enviar

    async def test_weekly_and_full_period_buttons(self):
        result, _, _ = await self.run_reply(reply={**REPLY, "answer": "Resumo semanal"})
        self.assertEqual(result["answer"], "sim")
        self.assertFalse(self.report.await_args.kwargs["full"])
        self.assertEqual(self.report.await_args.args[0], INVITE["client_id"])  # dados só da empresa do convite
        result, update, _ = await self.run_reply(reply={**REPLY, "answer": "Período completo"})
        self.assertEqual(result["answer"], "completo")
        self.assertTrue(self.report.await_args.kwargs["full"])
        self.assertEqual(update.await_args_list[0].kwargs["patch"]["status"], "sim")  # constraint do convite continua válida

    async def test_same_click_twice_never_sends_twice(self):
        result, _, text = await self.run_reply(invite={**INVITE, "answer_message_id": "wamid.RESPOSTA", "status": "enviado"})
        self.assertEqual(result["ignored"], "already_answered")
        text.assert_not_awaited()
        result, _, text = await self.run_reply(claimed=False)
        self.assertEqual(result["ignored"], "already_answered")
        text.assert_not_awaited()

    async def test_no_gets_only_an_ack(self):
        result, _, text = await self.run_reply(reply={**REPLY, "answer": "Agora não"})
        self.assertEqual(result["answer"], "nao")
        self.assertIn("Combinado, Nasser", text.await_args.kwargs["text"])

    async def test_other_number_or_unknown_invite_is_ignored(self):
        result, _, text = await self.run_reply(reply={**REPLY, "wa_id": "5511900000000"})
        self.assertEqual(result["ignored"], "phone_mismatch")
        text.assert_not_awaited()
        result, _, _ = await self.run_reply(invite=None)
        self.assertEqual(result["ignored"], "unknown_invite")

    async def test_expired_invite_does_not_send_old_numbers(self):
        old = {**INVITE, "created_at": (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()}
        result, _, text = await self.run_reply(invite=old)
        self.assertEqual(result["answer"], "expirado")
        self.assertIn("passou do prazo", text.await_args.kwargs["text"])


class HookAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_hook_requires_the_bridge_key(self):
        body = hooks.CrmHook(type="invite_reply", reply=hooks.InviteReply(**REPLY))
        with patch.dict(os.environ, {"CRM_OPS_API_KEY": "chave"}), patch.object(hooks, "handle_invite_reply", AsyncMock()) as handle:
            with self.assertRaises(HTTPException) as raised:
                await hooks.crm_hook(body, x_dados_ops_key="errada")
            self.assertEqual(raised.exception.status_code, 401)
            handle.assert_not_awaited()
            await hooks.crm_hook(body, x_dados_ops_key="chave")
            handle.assert_awaited_once()
        with patch.dict(os.environ, {"CRM_OPS_API_KEY": ""}):
            with self.assertRaises(HTTPException):
                await hooks.crm_hook(body, x_dados_ops_key="")


if __name__ == "__main__":
    unittest.main()
