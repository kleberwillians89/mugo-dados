"""Consumo de IA de uma empresa (Central da marca): hoje, mês, 30 dias e recursos."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from services import ai_usage

ROWS = [
    {"feature": "studio_content_matrix", "input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500, "cost_usd": 0.0012, "status": "ok", "created_at": "2026-11-10T13:00:00Z"},
    {"feature": "ig_comment_reply", "input_tokens": 200, "output_tokens": 50, "total_tokens": 250, "cost_usd": 0.0002, "status": "ok", "created_at": "2026-11-03T10:00:00Z"},
    {"feature": "studio_content_matrix", "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": None, "status": "erro", "error_code": "http_429:insufficient_quota", "created_at": "2026-10-25T10:00:00Z"},
]


class ClientSummaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_today_month_days_features(self):
        select = AsyncMock(return_value=ROWS)
        with patch("services.ig_supabase.sb_select", select):
            out = await ai_usage.client_summary("roove", today=date(2026, 11, 10))
        self.assertEqual(select.await_args.kwargs["filters"]["client_id"], "eq.roove")
        self.assertEqual((out["today"]["calls"], out["today"]["total_tokens"]), (1, 1500))
        self.assertEqual((out["month"]["calls"], out["month"]["cost_usd"]), (2, 0.0014))
        self.assertEqual([d["day"] for d in out["days"]], ["2026-11-10", "2026-11-03", "2026-10-25"])
        self.assertEqual(out["features"][0]["feature"], "studio_content_matrix")
        self.assertEqual(out["last_error"]["code"], "http_429:insufficient_quota")
        self.assertAlmostEqual(out["per_call"]["cost_usd"], 0.0007)


class RouteAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_any_member_reads_own_company_usage(self):
        from routes import studio as studio_routes
        read = AsyncMock(return_value="roove")
        with patch.object(studio_routes, "require_client_read", read), \
             patch("services.ai_usage.client_summary", AsyncMock(return_value={"client_id": "roove"})):
            out = await studio_routes.read_ai_usage("roove", authorization="Bearer viewer")
        read.assert_awaited_once()
        self.assertEqual(out["client_id"], "roove")


if __name__ == "__main__":
    unittest.main()
