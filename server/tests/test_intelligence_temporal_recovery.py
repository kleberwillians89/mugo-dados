"""Sanitized Roove-shaped regression: no provider or database IO."""
import copy
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, patch
import httpx
from services import intelligence as service


def snapshot():
    return {"period": {"start": "2026-10-01", "end": "2026-10-20"},
        "metrics": [{"id": "meta_investment", "value": 1000, "status": "confirmed", "format": "currency", "source": "meta"},
                    {"id": "roas", "value": None, "status": "unavailable", "format": "decimal", "source": "commerce+paid_media"}],
        "sources": [{"id": "commerce", "status": "available", "data_max_available": None, "last_sync_at": None},
                    {"id": "google_ads", "status": "available", "data_max_available": "2026-10-20"},
                    {"id": "meta", "status": "available", "data_max_available": "2026-10-20"}],
        "quality": {"status": "partial"}, "crossings": [], "top_campaigns": []}


def insight(sources, metric_ids, title="Acompanhe o investimento"):
    return {"category": "risk", "title": title, "interpretation": "Acompanhar o indicador disponível.",
            "metric_ids": metric_ids, "sources": sources, "impact": "medium", "confidence": "medium",
            "action": "Revisar o período.", "reason": "Leitura observada, sem causalidade."}


def analysis():
    return {"executive": {"overall": "Leitura observada.", "main_change": "Acompanhar.", "opportunity": "Investigar.", "attention": "Revisar.", "priority_action": "Conferir."},
            "insights": [insight(["meta"], ["meta_investment"]), insight(["meta", "commerce", "google_ads"], ["meta_investment", "roas"], "REJECTED COMPARISON")], "actions": []}


class TemporalRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def run_generation(self, outputs, failure=None):
        calls, saved = [], []
        async def post(_client, url, **kwargs):
            calls.append(kwargs["json"])
            if failure: raise failure
            return httpx.Response(200, json={"output_text": json.dumps(outputs[len(calls)-1])}, request=httpx.Request("POST", url))
        async def save(row, **_kwargs):
            saved.append(row)
            return {"id": "fixture-analysis", **row}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}), patch.object(httpx.AsyncClient, "post", post), patch.object(service, "_insert_analysis", save), redirect_stdout(io.StringIO()):
            try:
                result = await service._generate_with_provider(client_id="tenant-fixture", snapshot=snapshot(), period=snapshot()["period"],
                    base_row={"client_id": "tenant-fixture", "user_id": "viewer-fixture", "data_quality": {"status": "partial"}}, request_id="fixture-temporal")
                error = None
            except RuntimeError as exc: result, error = None, exc
        return result, error, calls, saved

    async def test_numeric_50_repair_then_temporal_optional_section_recovers(self):
        first, second = analysis(), analysis()
        first["executive"]["overall"] = "Aumentou 50 por cento."
        result, error, calls, saved = await self.run_generation([first, second])
        self.assertIsNone(error)
        self.assertEqual(len(calls), 2)  # No third paid retry.
        self.assertNotIn("REJECTED COMPARISON", json.dumps(result))
        record = result["analysis"]
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["client_id"], "tenant-fixture")
        self.assertTrue(record["data_quality"]["message"].startswith("Análise parcial:"))
        self.assertEqual(record["analysis"]["executive"]["overall"], second["insights"][0]["interpretation"])
        self.assertEqual(len(saved), 1)
        policy = json.loads(calls[0]["input"])["analysis_policy"]
        self.assertIn("roas", policy["insufficient_coverage_metric_ids"])
        self.assertFalse(policy["cross_source_comparison_allowed"])
        service._validate_analysis_grounding(record["analysis"], snapshot())

    async def test_no_useful_section_still_fails_and_persists_error(self):
        value = analysis(); value["insights"] = value["insights"][1:]
        result, error, calls, saved = await self.run_generation([value])
        self.assertIsNone(result)
        self.assertEqual(str(error), "AI_TEMPORALLY_INCOMPATIBLE_SOURCES")
        self.assertEqual(saved[0]["status"], "failed")
        self.assertEqual(len(calls), 1)

    async def test_recovery_does_not_hide_unknown_source_or_publish_rejected_executive(self):
        value = analysis(); value["insights"].append(insight(["invented"], ["meta_investment"]))
        result, error, _, saved = await self.run_generation([value])
        self.assertIsNone(result)
        self.assertEqual(str(error), "AI_UNGROUNDED_INSIGHT")
        self.assertEqual(saved[0]["status"], "failed")

    async def test_timeout_is_classified_without_inventing_a_partial_result(self):
        result, error, calls, saved = await self.run_generation([], httpx.ReadTimeout("fixture"))
        self.assertIsNone(result)
        self.assertEqual(str(error), "AI_PROVIDER_TIMEOUT")
        self.assertEqual(saved[0]["error_code"], "AI_PROVIDER_TIMEOUT")
        self.assertEqual(len(calls), 1)

    def test_recovery_is_not_mutation_and_keeps_validators_active(self):
        value = analysis(); original = copy.deepcopy(value)
        repaired = service._recover_temporal_sections(value, snapshot())
        self.assertEqual(value, original)
        self.assertNotIn("REJECTED COMPARISON", json.dumps(repaired))
        with self.assertRaisesRegex(RuntimeError, "AI_TEMPORALLY_INCOMPATIBLE_SOURCES"):
            service._validate_analysis_grounding(value, snapshot(), policy={"includes_partial_today": False})

    async def test_no_data_avoids_model_and_persists_explicit_error(self):
        empty = snapshot()
        empty["metrics"] = [{"id": "revenue", "value": None, "status": "unavailable"}]
        with patch.object(service, "_call_analysis_with_numeric_repair", AsyncMock()) as model, patch.object(service, "_insert_analysis", AsyncMock()) as save, redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "AI_INSUFFICIENT_DATA"):
                await service._generate_with_provider(client_id="fixture", snapshot=empty, period=empty["period"], base_row={"client_id":"fixture"}, request_id="fixture-no-data")
            model.assert_not_awaited()
            self.assertEqual(save.await_args.args[0]["error_code"], "AI_INSUFFICIENT_DATA")

    async def test_partial_recovery_does_not_relabel_a_metric_as_another_known_source(self):
        value = analysis()
        value["insights"][0]["sources"] = ["google_ads"]
        result, error, _, saved = await self.run_generation([value])
        self.assertIsNone(result)
        self.assertEqual(str(error), "AI_UNGROUNDED_INSIGHT")
        self.assertEqual(saved[0]["status"], "failed")

    async def test_http_route_serializes_recovered_partial_as_200_after_numeric_repair(self):
        from fastapi import FastAPI
        from routes import intelligence as routes

        first, second = analysis(), analysis()
        first["executive"]["overall"] = "Aumentou 50 por cento."
        observed = {}

        async def generation(**kwargs):
            self.assertEqual(kwargs["client_id"], "tenant-fixture")
            self.assertEqual(kwargs["user_id"], "user-fixture")
            result, error, calls, saved = await self.run_generation([first, second])
            if error:
                raise error
            observed.update(calls=calls, saved=saved)
            return result

        app = FastAPI()
        app.include_router(routes.router)
        with patch.object(routes, "require_user_id", AsyncMock(return_value="user-fixture")), \
             patch.object(routes, "resolve_client_id", AsyncMock(return_value="tenant-fixture")), \
             patch.object(routes, "generate_analysis", generation):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
                response = await client.post("/api/intelligence/analyses?client_id=tenant-fixture",
                    json={"start": "2026-10-01", "end": "2026-10-20"})
        self.assertEqual(response.status_code, 200)
        record = response.json()["analysis"]
        self.assertEqual(record["data_quality"]["status"], "partial")
        self.assertEqual(record["status"], "completed")
        self.assertNotIn("REJECTED COMPARISON", response.text)
        self.assertEqual(len(observed["calls"]), 2)
        self.assertEqual(len(observed["saved"]), 1)


class SelectiveTemporalRecoveryTests(unittest.IsolatedAsyncioTestCase):
    run_generation = TemporalRecoveryTests.run_generation
    async def test_keeps_valid_action_and_insight_but_removes_incompatible_recommendation(self):
        value = analysis()
        good = {"priority": "investigate", "recommendation": "Conferir a campanha persistida.",
            "justification": "Investimento observado na fonte disponível.", "sources": ["meta"],
            "impact_expected": "Hipótese a verificar", "confidence": "medium", "metric_id": "meta_investment"}
        bad = {**good, "recommendation": "REJECTED ACTION", "sources": ["meta", "commerce"]}
        value["actions"] = [bad, good]
        result, error, calls, saved = await self.run_generation([value])
        self.assertIsNone(error)
        recovered = result["analysis"]["analysis"]
        self.assertEqual(recovered["actions"], [good])
        self.assertEqual(recovered["insights"][0], value["insights"][0])
        self.assertEqual(recovered["executive"]["priority_action"], good["recommendation"])
        self.assertNotIn("REJECTED", json.dumps(recovered))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(saved), 1)
        service._validate_analysis_grounding(recovered, snapshot())

    async def test_no_supported_action_explains_insufficiency_without_inventing_recommendations(self):
        result, error, _, _ = await self.run_generation([analysis()])
        self.assertIsNone(error)
        recovered = result["analysis"]["analysis"]
        self.assertEqual(recovered["actions"], [])
        self.assertIn("Não há recomendações com evidência suficiente", recovered["executive"]["priority_action"])

    async def test_unknown_action_cannot_be_hidden_by_temporal_recovery(self):
        value = analysis()
        value["actions"] = [{"priority": "now", "recommendation": "Revisar.", "justification": "Evidência.",
            "sources": ["meta"], "impact_expected": "Hipótese", "confidence": "medium", "metric_id": "other-tenant-metric"}]
        result, error, _, saved = await self.run_generation([value])
        self.assertIsNone(result)
        self.assertEqual(str(error), "AI_UNGROUNDED_ACTION")
        self.assertEqual(saved[0]["status"], "failed")

    async def test_individually_valid_action_survives_without_useful_insight(self):
        value = analysis(); value["insights"] = value["insights"][1:]
        value["actions"] = [{"priority": "investigate", "recommendation": "Revisar o investimento.",
            "justification": "Indicador persistido.", "sources": ["meta"], "impact_expected": "Hipótese",
            "confidence": "medium", "metric_id": "meta_investment"}]
        result, error, _, _ = await self.run_generation([value])
        self.assertIsNone(error)
        self.assertEqual(result["analysis"]["analysis"]["actions"], value["actions"])
