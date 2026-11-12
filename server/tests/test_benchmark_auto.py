import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import benchmark_auto as ba  # noqa: E402


class CleanTests(unittest.TestCase):
    def test_cleans_sites_handles_and_skips_own_brand(self):
        out = ba.clean_list([
            {"name": "Curavino", "website": "curavino.com.br"},
            {"name": "Grand Cru", "website": "http://www.grandcru.com.br/loja", "instagram_handle": "https://instagram.com/grandcrubrasil/"},
            {"name": "grand cru", "website": "x"},
            {"name": "Evino", "website": "nada", "instagram_handle": "@@ inválido"},
        ], own_names=["Curavino"], limit=5)
        self.assertEqual([c["name"] for c in out], ["Grand Cru", "Evino"])
        self.assertEqual(out[0]["website"], "https://www.grandcru.com.br")
        self.assertEqual(out[0]["instagram_handle"], "grandcrubrasil")
        self.assertIsNone(out[1]["website"])
        self.assertIsNone(out[1]["instagram_handle"])


class EnsureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ba._attempts.clear()

    async def test_does_nothing_when_there_are_competitors(self):
        with patch.object(ba, "sb_select", AsyncMock(return_value=[{"id": "1", "name": "X", "active": True}])), \
             patch.object(ba, "suggest", AsyncMock()) as sug:
            out = await ba.ensure_competitors("c1")
        self.assertEqual(out["status"], "ja_tem")
        sug.assert_not_awaited()

    async def test_fills_empty_benchmark_respecting_plan_and_removed(self):
        found = [{"name": "Grand Cru", "website": "https://grandcru.com.br", "instagram_handle": "grandcru", "why": "vinho importado"},
                 {"name": "Evino", "website": None, "instagram_handle": None, "why": ""},
                 {"name": "Wine", "website": None, "instagram_handle": "wine", "why": ""}]
        insert = AsyncMock(side_effect=lambda table, row: {"id": row["name"], **row})
        with patch.object(ba, "sb_select", AsyncMock(return_value=[{"id": "old", "name": "Evino", "active": False}])), \
             patch("services.saas.remaining", AsyncMock(return_value=2)), \
             patch.object(ba, "suggest", AsyncMock(return_value=found)), patch.object(ba, "sb_insert", insert):
            out = await ba.ensure_competitors("c1")
        self.assertEqual(out["status"], "feito")
        self.assertEqual([a["name"] for a in out["added"]], ["Grand Cru", "Wine"])  # Evino foi removido pela equipe
        self.assertEqual(insert.await_args_list[0].args[1]["website"], "https://grandcru.com.br")
        self.assertNotIn("website", insert.await_args_list[1].args[1])

    async def test_ai_failure_waits_before_trying_again(self):
        sug = AsyncMock(side_effect=RuntimeError("sem IA"))
        with patch.object(ba, "sb_select", AsyncMock(return_value=[])), patch("services.saas.remaining", AsyncMock(return_value=None)), \
             patch.object(ba, "suggest", sug):
            self.assertEqual((await ba.ensure_competitors("c1"))["status"], "sem_ia")
            self.assertEqual((await ba.ensure_competitors("c1"))["status"], "aguardando")
        self.assertEqual(sug.await_count, 1)


if __name__ == "__main__":
    unittest.main()
