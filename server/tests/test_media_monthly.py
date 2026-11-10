"""Mídia On: estratégias prontas do mês (uma por objetivo), sem duplicar."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, patch

from services import media_monthly as mm
from services.media_strategy import OBJECTIVES


class MonthlyTests(unittest.IsolatedAsyncioTestCase):
    async def test_generates_missing_objectives_only(self):
        build = AsyncMock(side_effect=lambda cid, **kw: {"month": "2026-12-01", "objective": kw["objective"], "scenarios": []})
        record = AsyncMock(return_value={"saved": True, "id": "s"})
        with patch.object(mm, "list_strategies", AsyncMock(return_value=[{"objective": "vendas"}])), \
             patch.object(mm, "build_strategy", build), patch.object(mm, "narrative", AsyncMock(return_value={"headline": "x"})), \
             patch.object(mm, "record_strategy", record):
            out = await mm.generate_for_client("roove", "2026-12")
        self.assertEqual(out["skipped"], ["vendas"])
        self.assertEqual(set(out["created"]), set(OBJECTIVES) - {"vendas"})
        self.assertIn("retencao", out["created"])
        self.assertIn("remarketing", out["created"])
        self.assertIsNone(record.await_args.kwargs["user_id"])
        self.assertTrue(record.await_args.args[1]["auto_generated"])

    async def test_one_objective_failing_does_not_stop_others(self):
        async def build(cid, **kw):
            if kw["objective"] == "leads":
                raise RuntimeError("sem dados")
            return {"month": "2026-12-01", "objective": kw["objective"], "scenarios": []}
        with patch.object(mm, "list_strategies", AsyncMock(return_value=[])), patch.object(mm, "build_strategy", build), \
             patch.object(mm, "narrative", AsyncMock(side_effect=RuntimeError("ia"))), \
             patch.object(mm, "record_strategy", AsyncMock(return_value={"saved": True})), redirect_stdout(io.StringIO()):
            out = await mm.generate_for_client("roove", "2026-12")
        self.assertEqual(out["failed"], ["leads"])
        self.assertEqual(len(out["created"]), len(OBJECTIVES) - 1)


if __name__ == "__main__":
    unittest.main()
