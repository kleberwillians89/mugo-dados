"""Aprendizado semanal: o job deixa os fatos pendentes; nada entra na memória sem a equipe."""
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import brand_learning as bl  # noqa: E402
from services import ig_supabase  # noqa: E402

FACT = {"fato": "No WhatsApp a marca não usa emoji.", "origem": "equipe", "origem_rotulo": "x", "evidencia": "y", "confianca": "alta"}


class WeeklyTests(unittest.IsolatedAsyncioTestCase):
    def test_week_key(self):
        self.assertEqual(bl.week_key(datetime(2026, 11, 24, tzinfo=timezone.utc)), "2026-W48")

    async def test_creates_pending_only_with_facts_and_skips_done_weeks(self):
        insert, update = AsyncMock(), AsyncMock(return_value=[])

        async def select(table, **kwargs):
            return [{"id": "x"}] if kwargs["filters"]["client_id"] == "eq.feita" else []

        async def suggest(cid):
            return {"facts": [FACT], "signals": 4} if cid == "ruah" else {"facts": [], "signals": 0}
        add_facts = AsyncMock()
        with patch.object(bl, "_weekly_clients", AsyncMock(return_value=["ruah", "vazia", "feita"])), \
             patch.object(bl, "suggest", suggest), \
             patch.object(ig_supabase, "sb_select", select), patch.object(ig_supabase, "sb_insert", insert), \
             patch.object(ig_supabase, "sb_update", update), \
             patch("services.brand_knowledge.add_facts", add_facts):
            out = await bl.run_weekly()
        self.assertEqual((out["created"], out["empty"], out["skipped"]), (1, 1, 1))
        row = insert.await_args.args[1]
        self.assertEqual((row["client_id"], row["status"], row["facts"]), ("ruah", "pendente", [FACT]))
        self.assertEqual(update.await_args.kwargs["patch"], {"status": "substituida"})
        add_facts.assert_not_awaited()  # memória só muda quando alguém confirma

    async def test_one_brand_failing_does_not_stop_the_others(self):
        async def suggest(cid):
            if cid == "quebra":
                raise RuntimeError("x")
            return {"facts": [FACT], "signals": 3}
        with patch.object(bl, "_weekly_clients", AsyncMock(return_value=["quebra", "ruah"])), \
             patch.object(bl, "suggest", suggest), \
             patch.object(ig_supabase, "sb_select", AsyncMock(return_value=[])), \
             patch.object(ig_supabase, "sb_insert", AsyncMock()), patch.object(ig_supabase, "sb_update", AsyncMock()):
            out = await bl.run_weekly()
        self.assertEqual((out["created"], out["failed"]), (1, 1))

    async def test_pending_and_resolve(self):
        row = {"id": "p1", "week": "2026-W48", "facts": [FACT], "signals": 4, "created_at": "2026-11-23"}
        with patch.object(ig_supabase, "sb_select", AsyncMock(return_value=[row])):
            self.assertEqual((await bl.pending("ruah"))["facts"], [FACT])
        async def broken(*a, **k):
            raise RuntimeError("sem migração")
        with patch.object(ig_supabase, "sb_select", broken):
            self.assertIsNone(await bl.pending("ruah"))
        with patch.object(ig_supabase, "sb_update", AsyncMock(return_value=[{"id": "p1"}])) as upd:
            self.assertTrue(await bl.resolve("ruah", "p1", "descartada", user_id="u"))
        self.assertEqual(upd.await_args.kwargs["patch"]["status"], "descartada")
        with self.assertRaises(bl.StudioError):
            await bl.resolve("ruah", "p1", "apagada", user_id="u")


if __name__ == "__main__":
    unittest.main()
