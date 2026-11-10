"""Consumo de IA por cliente: registro de cada chamada e relatório (Administração → Consumo de IA)."""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import ai_usage
from services import studio_llm
from services.studio_calendar import StudioError


class CostTests(unittest.TestCase):
    def test_estimates_cost_and_accepts_dated_models(self):
        self.assertEqual(ai_usage.estimate_cost("gpt-4.1-mini", 1_000_000, 500_000), 1.2)
        self.assertEqual(ai_usage.estimate_cost("gpt-4.1-mini-2025-04-14", 1_000_000, 0), 0.4)
        self.assertIsNone(ai_usage.estimate_cost("modelo-desconhecido", 10, 10))

    def test_price_override_by_env(self):
        with patch.dict("os.environ", {"AI_PRICES_JSON": '{"gpt-4.1-mini": [1, 2]}'}):
            self.assertEqual(ai_usage.estimate_cost("gpt-4.1-mini", 1_000_000, 1_000_000), 3.0)

    def test_row_has_only_metadata(self):
        row = ai_usage.build_row(feature="studio_content_matrix", model="gpt-4.1-mini", client_id="ruah",
                                 body={"usage": {"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200}, "output": "segredo"})
        self.assertEqual((row["client_id"], row["input_tokens"], row["output_tokens"], row["total_tokens"], row["status"]), ("ruah", 1000, 200, 1200, "ok"))
        self.assertNotIn("segredo", str(row))


class TrackInLLMTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, response):
        recorded = []
        class Client:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, *a, **k): return response
        with patch.dict("os.environ", {"OPENAI_API_KEY": "k", "OPENAI_MODEL": "gpt-4.1-mini"}), \
             patch.object(studio_llm.httpx, "AsyncClient", lambda **k: Client()), \
             patch.object(ai_usage, "_insert", AsyncMock(side_effect=lambda row: recorded.append(row))):
            try:
                out = await studio_llm.llm_json(instructions="i", prompt="p", schema_name="studio_doc_escrever",
                                                schema=studio_llm.obj({"texto": studio_llm.STR}), client_id="ruah", leak_check=False)
            except StudioError as exc:
                out = exc
            await asyncio.sleep(0)
        return out, recorded

    async def test_success_records_tokens_for_the_brand(self):
        body = {"output": [{"type": "message", "content": [{"type": "output_text", "text": '{"texto": "oi"}'}]}],
                "usage": {"input_tokens": 900, "output_tokens": 100, "total_tokens": 1000}}
        out, rows = await self.call(httpx.Response(200, json=body))
        self.assertEqual(out, {"texto": "oi"})
        self.assertEqual((rows[0]["client_id"], rows[0]["feature"], rows[0]["total_tokens"], rows[0]["status"]), ("ruah", "studio_doc_escrever", 1000, "ok"))

    async def test_no_credit_is_recorded_and_explained(self):
        out, rows = await self.call(httpx.Response(429, json={"error": {"code": "insufficient_quota", "type": "insufficient_quota"}}))
        self.assertIsInstance(out, StudioError)
        self.assertEqual(out.code, "AI_PROVIDER_QUOTA")
        self.assertEqual((rows[0]["status"], rows[0]["error_code"]), ("erro", "http_429:insufficient_quota"))

    async def test_record_failure_never_breaks_the_ai(self):
        body = {"output": [{"type": "message", "content": [{"type": "output_text", "text": '{"texto": "oi"}'}]}], "usage": {}}
        with patch("services.ig_supabase.sb_insert", AsyncMock(side_effect=RuntimeError("db fora"))):
            row = ai_usage.build_row(feature="x", model="gpt-4.1-mini", body=body)
            await ai_usage._insert(row)  # só loga


class ReportTests(unittest.TestCase):
    def test_groups_by_client_feature_and_day_and_flags_quota(self):
        rows = [
            {"client_id": "ruah", "feature": "studio_content_matrix", "model": "gpt-4.1-mini", "input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500, "cost_usd": 0.0012, "status": "ok", "error_code": None, "created_at": "2026-11-09T10:00:00Z"},
            {"client_id": "ruah", "feature": "studio_doc_escrever", "model": "gpt-4.1-mini", "input_tokens": 100, "output_tokens": 50, "total_tokens": 150, "cost_usd": 0.0001, "status": "ok", "error_code": None, "created_at": "2026-11-10T09:00:00Z"},
            {"client_id": "roove", "feature": "studio_content_matrix", "model": "gpt-4.1-mini", "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": 0, "status": "erro", "error_code": "http_429:insufficient_quota", "created_at": "2026-11-10T12:00:00Z"},
        ]
        out = ai_usage.aggregate(rows, {"ruah": "Ruah Parfums", "roove": "Roove"})
        self.assertEqual(out["totals"]["total_tokens"], 1650)
        self.assertEqual(out["totals"]["errors"], 1)
        self.assertEqual([c["name"] for c in out["clients"]], ["Ruah Parfums", "Roove"])
        self.assertEqual(out["clients"][0]["features"][0]["feature"], "studio_content_matrix")
        self.assertEqual([d["date"] for d in out["daily"]], ["2026-11-09", "2026-11-10"])
        self.assertTrue(out["quota_exhausted"])
        self.assertEqual(out["clients"][1]["last_error"]["code"], "http_429:insufficient_quota")

    def test_route_is_agency_only(self):
        source = (Path(__file__).resolve().parents[1] / "routes" / "admin_health.py").read_text(encoding="utf-8")
        block = source[source.index('@router.get("/ai-usage")'):]
        self.assertIn("await require_agency_admin(authorization)", block)


if __name__ == "__main__":
    unittest.main()
