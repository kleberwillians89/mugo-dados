import io
import json
import os
import re
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import intelligence


def analysis(text):
    return {"executive": {"overall": text, "main_change": "Sem alteração confirmada.",
                          "opportunity": "Investigar.", "attention": "Acompanhar.", "priority_action": "Revisar."},
            "insights": [], "actions": []}


class NumericRepairTests(unittest.IsolatedAsyncioTestCase):
    async def generate(self, texts, status=200, field="overall", period=None):
        requests, saved = [], []
        async def post(_client, url, **kwargs):
            requests.append(kwargs["json"])
            text = texts[len(requests)-1]
            output = analysis(text)
            if field != "overall":
                output["executive"]["overall"] = "Leitura qualitativa do período."
                output["executive"][field] = text
            return httpx.Response(status, json={"output_text": json.dumps(output)}, request=httpx.Request("POST", url))
        async def insert(row, **kwargs):
            saved.append(row)
            return {"id": "analysis-a", **row}
        snapshot = {"period": period or {"start": "2026-10-01", "end": "2026-10-05"},
                    "metrics": [{"id": "revenue", "value": 4429.1, "source": "commerce"}],
                    "sources": [{"id": "commerce"}], "quality": {}, "crossings": [], "top_campaigns": []}
        output = io.StringIO()
        with (
            redirect_stdout(output), patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}),
            patch.object(httpx.AsyncClient, "post", post),
            patch.object(intelligence, "_insert_analysis", insert),
            patch.object(intelligence, "_build_analysis_policy", return_value={}),
            patch.object(intelligence, "_normalize_grounding_ids", side_effect=lambda value, *args, **kwargs: value),
            patch.object(intelligence, "_validate_analysis_grounding", return_value=None),
            patch.object(intelligence, "_sanitize_analysis", side_effect=lambda value, *args: value),
            patch.object(intelligence, "_ensure_partial_today_limitation", side_effect=lambda value, *args, **kwargs: (value, False)),
        ):
            try:
                result = await intelligence._generate_with_provider(client_id="tenant-a", snapshot=snapshot,
                    period=snapshot["period"], base_row={"client_id": "tenant-a", "user_id": "viewer-a"}, request_id="req-repair")
                error = None
            except RuntimeError as exc:
                result, error = None, exc
        return result, error, requests, saved, output.getvalue()

    async def test_initial_25_rejected_then_one_grounded_repair_succeeds(self):
        invalid = "Receita cresceu 25 por cento."
        result, error, requests, saved, logs = await self.generate([invalid, "Receita registrada R$ 4.429,10."])
        self.assertIsNone(error)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]["input"], requests[1]["input"])
        self.assertEqual(requests[0]["text"], requests[1]["text"])
        payload = json.loads(requests[0]["input"])
        self.assertNotIn(25, intelligence._trusted_numbers(payload))
        self.assertNotIn(invalid, json.dumps(requests[1]))
        self.assertNotIn(invalid, json.dumps(result))
        self.assertEqual([row["status"] for row in saved], ["completed"])
        self.assertTrue(all(row["client_id"] == "tenant-a" for row in saved))
        self.assertIn("field=response.executive.overall numeric_token=25", logs)
        self.assertIn("numeric_grounding_repair_succeeded", logs)
        self.assertNotIn(invalid, logs)

    async def test_second_25_stays_rejected_and_failed_is_persisted_without_third_request(self):
        result, error, requests, saved, logs = await self.generate(["Cresceu 25%.", "Mantém 25%."])
        self.assertIsNone(result)
        self.assertEqual(str(error), "AI_UNTRUSTED_NUMERIC_TEXT:response.executive.overall")
        self.assertEqual(len(requests), 2)
        self.assertEqual([row["status"] for row in saved], ["failed"])
        self.assertEqual(saved[0]["error_code"], str(error))
        self.assertIn("numeric_grounding_repair_failed", logs)
        self.assertEqual(logs.count("[intelligence][numeric_validation_failed]"), 2)

    async def test_valid_initial_response_does_not_retry(self):
        result, error, requests, _, logs = await self.generate(["Receita registrada R$ 4.429,10."])
        self.assertIsNone(error)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(requests), 1)
        self.assertNotIn("numeric_grounding_repair_started", logs)

    async def test_qualitative_repair_is_valid(self):
        result, error, requests, _, _ = await self.generate(["Cresceu 25%.", "Sem variação confirmada."])
        self.assertIsNone(error)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(requests), 2)

    async def test_upstream_error_does_not_retry(self):
        result, error, requests, saved, _ = await self.generate(["Sem números."], status=502)
        self.assertIsNone(result)
        self.assertEqual(str(error), "AI_PROVIDER_ERROR_502")
        self.assertEqual(len(requests), 1)
        self.assertEqual(saved[0]["status"], "failed")

    async def test_main_change_30_gets_one_strict_qualitative_repair_without_changing_context(self):
        invalid = "A receita cresceu 30 por cento."
        result, error, requests, saved, logs = await self.generate([invalid, "A variação confirmada orienta a leitura."], field="main_change",
            period={"start": "2026-10-01", "end": "2026-10-20"})
        self.assertIsNone(error)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]["input"], requests[1]["input"])
        self.assertNotIn(30, intelligence._trusted_numbers(json.loads(requests[0]["input"])))
        self.assertTrue(requests[1]["text"]["format"]["strict"])
        schema = requests[1]["text"]["format"]["schema"]
        field = schema["properties"]["executive"]["properties"]["main_change"]
        self.assertIsNone(re.fullmatch(field["pattern"], invalid))
        self.assertIsNotNone(re.fullmatch(field["pattern"], "Os sinais do GA4 merecem acompanhamento."))
        self.assertEqual(schema["properties"]["insights"], requests[0]["text"]["format"]["schema"]["properties"]["insights"])
        self.assertNotIn("pattern", intelligence.ANALYSIS_SCHEMA["schema"]["properties"]["executive"]["properties"]["main_change"])
        self.assertNotIn(invalid, json.dumps(requests[1]))
        self.assertEqual(saved[0]["status"], "completed")
        self.assertEqual(saved[0]["client_id"], "tenant-a")
        self.assertIn("field=response.executive.main_change numeric_token=30", logs)
        self.assertNotIn(invalid, logs)

    async def test_repeated_30_in_main_change_stays_rejected_even_with_strict_repair(self):
        result, error, requests, saved, logs = await self.generate(["Cresceu 30%.", "Mantém 30%."], field="main_change",
            period={"start": "2026-10-01", "end": "2026-10-20"})
        self.assertIsNone(result)
        self.assertEqual(str(error), "AI_UNTRUSTED_NUMERIC_TEXT:response.executive.main_change")
        self.assertEqual(len(requests), 2)
        self.assertEqual(saved[0]["status"], "failed")
        self.assertIn("numeric_grounding_repair_failed", logs)

    async def test_supported_initial_number_in_main_change_keeps_existing_contract(self):
        result, error, requests, _, _ = await self.generate(["Receita registrada R$ 4.429,10."], field="main_change")
        self.assertIsNone(error)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(requests), 1)

    async def test_legitimate_30_day_context_is_accepted_only_when_period_proves_it(self):
        result, error, requests, _, _ = await self.generate(["Nos 30 dias analisados, acompanhe os indicadores."], field="main_change",
            period={"start": "2026-09-01", "end": "2026-09-30"})
        self.assertIsNone(error)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(requests), 1)
        self.assertNotIn("strict", requests[0]["text"]["format"])

    async def test_20_day_period_does_not_authorize_invented_30_day_context(self):
        result, error, requests, _, _ = await self.generate(["Nos 30 dias analisados, houve mudança.", "Acompanhe a mudança no período selecionado."], field="main_change",
            period={"start": "2026-10-01", "end": "2026-10-20"})
        self.assertIsNone(error)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(requests), 2)
        trusted = intelligence._trusted_numbers(json.loads(requests[0]["input"]))
        self.assertIn(20, trusted)
        self.assertNotIn(30, trusted)
