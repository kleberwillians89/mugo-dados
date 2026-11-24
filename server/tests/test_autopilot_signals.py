"""Aprender com o piloto automático: equipe assumiu, IA pediu ajuda, resultado e 👍👎."""
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import autopilot_signals as ap  # noqa: E402
from services import brand_signals  # noqa: E402

CID = "ruah"


def tables(data):
    async def run(table, **kwargs):
        rows = data.get(table)
        return rows(kwargs) if callable(rows) else list(rows or [])
    return run


class TakeoverTests(unittest.TestCase):
    def test_team_reply_after_ai_is_a_takeover(self):
        rows = [
            {"thread_id": "t1", "direction": "in", "text": "Tem frete grátis?", "created_at": "2026-11-20T10:00:00+00:00"},
            {"thread_id": "t1", "direction": "out", "by_ai": True, "text": "Sim, para todo o Brasil!", "created_at": "2026-11-20T10:01:00+00:00"},
            {"thread_id": "t1", "direction": "in", "text": "Oba", "created_at": "2026-11-20T10:05:00+00:00"},
            {"thread_id": "t1", "direction": "out", "by_ai": False, "text": "Correção: frete grátis só acima de R$ 300.", "created_at": "2026-11-20T10:20:00+00:00"},
            {"thread_id": "t2", "direction": "in", "text": "Oi", "created_at": "2026-11-20T10:00:00+00:00"},
            {"thread_id": "t2", "direction": "out", "by_ai": False, "text": "Oi! Posso ajudar?", "created_at": "2026-11-20T10:02:00+00:00"},
        ]
        out = ap.takeovers_in(rows, key="thread_id", is_ai=lambda m: bool(m.get("by_ai")), is_team=lambda m: m.get("by_ai") is False)
        self.assertEqual(len(out), 1)  # t2: a equipe respondeu sem a IA antes, não é correção
        self.assertEqual(out[0]["cliente"], "Tem frete grátis?")
        self.assertIn("R$ 300", out[0]["equipe_disse_depois"])

    def test_team_reply_days_later_is_not_a_takeover(self):
        rows = [{"k": "a", "direction": "out", "ai": True, "text": "x", "created_at": "2026-11-01T10:00:00+00:00"},
                {"k": "a", "direction": "out", "ai": False, "text": "y", "created_at": "2026-11-05T10:00:00+00:00"}]
        self.assertEqual(ap.takeovers_in(rows, key="k", is_ai=lambda m: m["ai"], is_team=lambda m: not m["ai"]), [])


class SignalTests(unittest.IsolatedAsyncioTestCase):
    async def test_handoffs_grouped_without_team_pauses(self):
        data = {"whatsapp_threads": [{"ai_handoff_reason": "Pergunta sobre troca"}, {"ai_handoff_reason": "Pergunta sobre troca"},
                                     {"ai_handoff_reason": "Pausada pela equipe"}],
                "ig_dm_messages": [{"error": "Reclamação de entrega"}]}
        with patch.object(ap, "sb_select", tables(data)):
            out = await ap.handoffs(CID, "2026-11-17")
        self.assertEqual(out, ["Pergunta sobre troca (2x)", "Reclamação de entrega"])

    async def test_outcomes_count_stages_and_objections(self):
        data = {"whatsapp_threads": [{"ai_stage": "comprou"}, {"ai_stage": "perdida", "ai_objections": ["frete", "preço"]},
                                     {"ai_stage": "perdida", "ai_objections": ["Frete"]}]}
        with patch.object(ap, "sb_select", tables(data)):
            out = await ap.outcomes(CID, "2026-11-17")
        self.assertEqual(out["fases"], {"comprou": 1, "perdida": 2})
        self.assertEqual(out["objecoes_mais_comuns"][0], "frete")

    async def test_count_and_usage_signals(self):
        self.assertEqual(ap.count({"equipe_assumiu": [{}], "ia_pediu_ajuda": ["a", "b"], "avaliacoes_da_equipe": [{}],
                                   "resultado_das_conversas": {"fases": {"comprou": 9}}}), 4)
        self.assertEqual(brand_signals.count_signals({"piloto_automatico": {"ia_pediu_ajuda": ["a"]}}), 1)

    async def test_missing_tables_give_empty(self):
        async def broken(*a, **k):
            raise RuntimeError("sem tabela")
        with patch.object(ap, "sb_select", broken):
            self.assertEqual(await ap.signals(CID, "2026-11-17"), {})
            self.assertEqual(await ap.sample(CID), [])


class SampleTests(unittest.IsolatedAsyncioTestCase):
    async def test_sample_pairs_ai_reply_with_customer_message_and_skips_reviewed(self):
        def wa(kwargs):
            return [{"id": "m1", "thread_id": "t", "direction": "in", "text": "Tem 50ml?"},
                    {"id": "m2", "thread_id": "t", "direction": "out", "by_ai": True, "type": "text", "text": "Temos sim!"},
                    {"id": "m3", "thread_id": "t", "direction": "in", "text": "E 100ml?"},
                    {"id": "m4", "thread_id": "t", "direction": "out", "by_ai": True, "type": "text", "text": "Também!"}]
        data = {"ai_reply_reviews": [{"ref_id": "m4"}], "whatsapp_messages": wa, "ig_dm_messages": [],
                "ig_engagement_actions": [{"id": "a1", "comment_id": "17900000001", "text": "Obrigada 💛"}],
                "ig_comments": [{"comment_id": "17900000001", "text": "Amei o cheiro"}]}
        with patch.object(ap, "sb_select", tables(data)):
            out = await ap.sample(CID, seed=1)
        refs = {r["ref_id"]: r for r in out}
        self.assertEqual(set(refs), {"m2", "a1"})
        self.assertEqual(refs["m2"]["customer_text"], "Tem 50ml?")
        self.assertEqual(refs["a1"]["channel_label"], "Comentário")

    async def test_rate_validates_and_saves(self):
        insert = AsyncMock()
        with patch.object(ap, "sb_insert", insert):
            await ap.rate(CID, channel="whatsapp", ref_id="m2", customer_text="Tem?", ai_text="Temos", rating="down",
                          reason="faltou o preço", user_id="u1")
            with self.assertRaises(ValueError):
                await ap.rate(CID, channel="email", ref_id="x", customer_text="", ai_text="x", rating="up", reason=None, user_id="u1")
        row = insert.await_args.args[1]
        self.assertEqual((row["rating"], row["reason"], row["reviewed_by"]), ("down", "faltou o preço", "u1"))


if __name__ == "__main__":
    unittest.main()
