"""Novos sinais de aprendizado: CRM de criadores, respostas e correções da equipe, resultados."""
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import brand_signals, whatsapp_ai  # noqa: E402

CID = "ruah"


def fake_select(tables):
    async def run(table, **kwargs):
        rows = tables.get(table)
        if callable(rows):
            return rows(kwargs)
        return list(rows or [])
    return run


class SignalTests(unittest.IsolatedAsyncioTestCase):
    async def test_creator_crm_becomes_signal(self):
        tables = {
            "creator_media_kits": [{"creator_id": "c1", "status": "fechado", "status_at": "2026-11-20", "deals": [{"what": "Reels BF", "amount": 18000}]},
                                   {"creator_id": "c2", "status": "nao_fechou", "status_note": "preço alto", "deals": []}],
            "creators": [{"id": "c1", "handle": "yasmin", "followers": 6100000, "biography": "beleza"},
                         {"id": "c2", "handle": "karine", "followers": 3000000}],
        }
        with patch.object(brand_signals, "sb_select", fake_select(tables)):
            out = await brand_signals.creator_signals(CID, "2026-11-01")
        self.assertEqual(out[0]["resultado"], "fechou")
        self.assertEqual(out[0]["entrega"], "Reels BF")
        self.assertEqual(out[1]["resultado"], "nao_fechou")
        self.assertEqual(out[1]["motivo"], "preço alto")

    async def test_team_replies_and_ai_corrections(self):
        def wa(kwargs):
            if "payload->>ai_original" in kwargs["filters"]:
                return [{"text": "Oi! Temos sim 💛", "payload": {"ai_original": "Olá, prezada cliente. Temos disponibilidade."}}]
            return [{"text": "Separei pra você"}]
        tables = {"ig_engagement_actions": [{"text": "Obrigada, linda!"}], "whatsapp_messages": wa}
        with patch.object(brand_signals, "sb_select", fake_select(tables)):
            out = await brand_signals.team_reply_signals(CID, "2026-11-01")
        self.assertEqual(out["instagram"], ["Obrigada, linda!"])
        self.assertEqual(out["whatsapp"], ["Separei pra você"])
        self.assertEqual(out["correcoes_da_ia"][0]["equipe_enviou"], "Oi! Temos sim 💛")

    def test_new_signals_count_but_results_do_not(self):
        signals = {"criadores": [{}, {}], "respostas_da_equipe": {"instagram": ["a"], "whatsapp": [], "correcoes_da_ia": [{}]},
                   "resultados": {"posts_que_mais_alcancaram": [{}, {}, {}], "metas": [{}]}}
        self.assertEqual(brand_signals.count_signals(signals), 4)

    async def test_usage_signals_include_new_sections_and_survive_missing_tables(self):
        async def broken(*a, **k):
            raise RuntimeError("tabela ausente")
        with patch.object(brand_signals, "sb_select", broken), \
             patch.object(brand_signals, "whatsapp_inbound", AsyncMock(return_value=[])), \
             patch.object(brand_signals, "result_signals", AsyncMock(return_value={})):
            out = await brand_signals.usage_signals(CID)
        self.assertEqual(out["criadores"], [])
        self.assertEqual(out["respostas_da_equipe"]["correcoes_da_ia"], [])


class WhatsAppCorrectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_edited_suggestion_keeps_ai_original_in_payload(self):
        record = AsyncMock()
        thread, number = {"id": "t1", "wa_id": "5511"}, {"id": "n1", "phone_number_id": "p1", "access_token": "x"}
        decision = {"reply": "Oi! Temos sim", "buttons": [], "products": [], "_ai_original": "Olá, prezada cliente."}
        with patch.object(whatsapp_ai, "_graph", AsyncMock(return_value={"messages": [{"id": "wamid.1"}]})), \
             patch.object(whatsapp_ai, "_record", record):
            await whatsapp_ai.send_decision(CID, thread, number, decision, meta=None, match=None)
        self.assertEqual(record.await_args.kwargs["payload"]["ai_original"], "Olá, prezada cliente.")
        record.reset_mock()
        decision.pop("_ai_original")
        with patch.object(whatsapp_ai, "_graph", AsyncMock(return_value={"messages": [{"id": "wamid.2"}]})), \
             patch.object(whatsapp_ai, "_record", record):
            await whatsapp_ai.send_decision(CID, thread, number, decision, meta=None, match=None)
        self.assertNotIn("ai_original", record.await_args.kwargs["payload"] or {})


if __name__ == "__main__":
    unittest.main()
