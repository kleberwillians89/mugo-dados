"""Investigative /ask: real service/tool code, synthetic opaque tenants, no network."""
import copy
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI, HTTPException
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import intelligence as ai
from services import intelligence_tools as tools
from routes import intelligence as routes

PERIOD = {"start": "2026-01-01", "end": "2026-01-01"}


def answer(mid):
    return {"direct_answer": [],
            "metric_ids": [mid], "evidence": ["Indicador consultado."], "attention_points": [],
            "recommendations": [{"text": "Revisar a distribuição observada.", "metric_ids": [mid]}], "next_steps": []}


def connection(cid, provider):
    if provider in {"meta", "instagram"}:
        return {"id": "connection", "client_id": cid, "platform": "meta_ads" if provider == "meta" else provider,
                "connection_type": "paid" if provider == "meta" else "organic", "ad_account_id": "act_fixture",
                "status": "active", "requires_reauth": False}
    return {"id": "connection", "client_id": cid, "provider": provider, "status": "connected", "disconnected_at": None}


class InvestigativeTests(unittest.IsolatedAsyncioTestCase):
    def install(self, cid, providers, plan=None, no_data=False, reply=None, fail_meta=False):
        self.reads, self.payloads = [], []
        async def select(table, **kwargs):
            self.reads.append((table, kwargs))
            self.assertEqual(kwargs["filters"]["client_id"], f"eq.{cid}")
            self.assertNotIn("token", kwargs.get("select", ""))
            if table in {"integration_connections", "meta_connections"}:
                if table == "meta_connections" and fail_meta: raise RuntimeError("fixture read failure")
                return [connection(cid, p) for p in providers if (p in {"meta", "instagram"}) == (table == "meta_connections")]
            if no_data: return []
            if table == "dashboard_daily_metrics":
                return [{"client_id": cid, "metric_date": PERIOD["start"], "meta_spend": 100, "meta_attributed_revenue": 200,
                    "google_ads_spend": 120, "google_ads_conversion_value": 240, "ga4_sessions": 50,
                    "shopify_net_revenue": 300, "shopify_orders": 3, "instagram_followers": 500, "instagram_interactions": 40},
                    {"client_id": "foreign-tenant", "metric_date": PERIOD["start"], "meta_spend": 99999}]
            return []
        async def service_select(table, **kwargs):
            if table == "campaign_daily_stats":
                self.assertEqual(kwargs["filters"]["client_id"], f"eq.{cid}")
                self.assertIn("act_fixture", kwargs["filters"]["ad_account_id"])
                if no_data: return []
                return [{"client_id": cid, "ad_account_id": "act_fixture", "campaign_id": "campaign-id",
                    "campaign_name": "Campanha de exemplo", "stat_date": PERIOD["start"], "spend": 100, "conversions": 2, "revenue": 200},
                    {"client_id": cid, "ad_account_id": "act_other", "campaign_id": "foreign-account", "stat_date": PERIOD["start"], "spend": 88888},
                    {"client_id": "foreign-tenant", "ad_account_id": "act_fixture", "campaign_id": "foreign-campaign", "stat_date": PERIOD["start"], "spend": 99999}]
            self.assertEqual(kwargs["filters"]["client_id"], f"eq.{cid}")
            return []
        async def model(**kwargs):
            self.payloads.append(copy.deepcopy(kwargs))
            self.assertLessEqual(len(json.dumps(kwargs["payload"], ensure_ascii=False)), tools.MAX_INPUT_CHARS)
            if kwargs["schema"]["name"] == tools.PLAN_SCHEMA["name"]:
                return plan if plan is not None else {"name": "read_metrics"}
            valid = next(m for m in kwargs["payload"]["metrics"] if m["value"] is not None)
            result = copy.deepcopy(reply(kwargs) if callable(reply) else reply if reply is not None else answer(valid["id"]))
            if result["direct_answer"] == []:
                result["direct_answer"] = [ref["id"] for ref in kwargs["payload"]["evidence_refs"]
                                           if ref["metric_id"] in result["metric_ids"]]
            return result
        for patcher in [patch.object(tools, "sb_select", AsyncMock(side_effect=select)),
                        patch.object(ai, "sb_select", AsyncMock(side_effect=service_select)),
                        patch.object(ai, "_call_provider", AsyncMock(side_effect=model)),
                        patch.object(tools, "resolve_commerce_context", AsyncMock(return_value={"provider": "fbits",
                            "metrics": {"revenue": {"value": 700}, "orders": {"value": 7}}}))]:
            patcher.start(); self.addCleanup(patcher.stop)

    async def investigate(self, cid):
        with redirect_stdout(io.StringIO()):
            return await ai._investigate_question(client_id=cid, question="Como estão as campanhas?", period=PERIOD)

    async def test_campaign_question_uses_scoped_persisted_evidence_and_bounded_model_calls(self):
        cid = "00000000-0000-0000-0000-000000000001"
        self.install(cid, {"meta"}, plan={"name": "read_campaigns"})
        result, snapshot = await self.investigate(cid)
        self.assertEqual(snapshot["client"]["id"], cid)
        self.assertEqual(len(snapshot["top_campaigns"]), 1)
        self.assertEqual(snapshot["top_campaigns"][0]["spend"], 100)
        self.assertTrue(result["metric_ids"][0].startswith("meta_campaign_"))
        self.assertIn("Campanha de exemplo", result["evidence"][0])
        self.assertIn(PERIOD["start"], result["evidence"][0])
        self.assertIn("fonte", result["evidence"][0])
        self.assertNotIn("99999", json.dumps(result))
        self.assertEqual([p["max_output_tokens"] for p in self.payloads], [100, 900])
        self.assertEqual([p["timeout_seconds"] for p in self.payloads], [10, 15])
        self.assertNotIn(cid, json.dumps(self.payloads))

    async def test_five_tenants_and_sixth_onboarding_without_code_changes(self):
        fixtures = [{"meta"}, {"google_ads", "ga4"}, {"shopify"}, {"instagram"}, {"fbits", "meta"}, {"ga4"}]
        for index, providers in enumerate(fixtures, 1):
            with self.subTest(tenant=index):
                cid = f"00000000-0000-0000-0000-{index:012d}"
                # Each iteration fully restores its module patchers.
                before = len(self._cleanups)
                self.install(cid, providers)
                result, snapshot = await self.investigate(cid)
                self.assertEqual(snapshot["client"]["id"], cid)
                self.assertTrue(result["metric_ids"])
                self.assertTrue(result["evidence"])
                self.assertNotIn("99999", json.dumps(snapshot))
                self.assertTrue({s["id"] for s in snapshot["sources"]} <= providers)
                while len(self._cleanups) > before:
                    function, args, kwargs = self._cleanups.pop(); function(*args, **kwargs)

    async def test_absent_campaign_integration_degrades_without_answer_model(self):
        cid = "00000000-0000-0000-0000-000000000002"
        self.install(cid, {"ga4"}, plan={"name": "read_campaigns"})
        result, _ = await self.investigate(cid)
        self.assertIn("não está disponível", result["direct_answer"])
        self.assertEqual(result["metric_ids"], [])
        self.assertEqual(len(self.payloads), 1)

    async def test_no_sources_skips_model_and_no_data_skips_final_model(self):
        cid = "00000000-0000-0000-0000-000000000003"
        self.install(cid, set())
        result, _ = await self.investigate(cid)
        self.assertFalse(self.payloads)
        self.assertIn("Nenhuma fonte", result["direct_answer"])

    async def test_connected_tenant_without_data_is_explicit(self):
        cid = "00000000-0000-0000-0000-000000000004"
        self.install(cid, {"meta"}, no_data=True)
        result, _ = await self.investigate(cid)
        self.assertIn("Não há métricas", result["direct_answer"])
        self.assertEqual(len(self.payloads), 1)

    async def test_extra_tenant_sql_or_unknown_tool_arguments_are_rejected(self):
        for call in [{"name": "sql"}, {"name": "read_metrics", "client_id": "foreign"}, {"name": "read_metrics", "sql": "select"}]:
            with self.subTest(call=call):
                session = tools.ReadTools("opaque", PERIOD, AsyncMock())
                with self.assertRaisesRegex(RuntimeError, "AI_TOOL_NOT_ALLOWED"):
                    await session.execute(call)
        session = tools.ReadTools("opaque", PERIOD, AsyncMock())
        await session.execute({"name": "read_campaigns"})
        with self.assertRaisesRegex(RuntimeError, "AI_TOOL_NOT_ALLOWED"):
            await session.execute({"name": "read_campaigns"})

    async def test_unconsulted_metric_and_generic_answer_without_evidence_are_rejected(self):
        for ids in [[], ["foreign_metric"]]:
            cid = "00000000-0000-0000-0000-000000000005"
            before = len(self._cleanups)
            self.install(cid, {"meta"}, reply={**answer("meta_investment"), "metric_ids": ids})
            with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_ANSWER"):
                await self.investigate(cid)
            while len(self._cleanups) > before:
                function, args, kwargs = self._cleanups.pop(); function(*args, **kwargs)

    async def test_partial_connection_failure_preserves_other_sources(self):
        cid = "00000000-0000-0000-0000-000000000006"
        self.install(cid, {"meta", "ga4"}, fail_meta=True)
        result, _ = await self.investigate(cid)
        self.assertEqual(result["metric_ids"], ["sessions"])
        self.assertIn("conexões", " ".join(result["attention_points"]))

    async def test_foreign_tenant_denied_by_route_before_tools_or_provider(self):
        with patch.object(routes, "require_user_id", AsyncMock(return_value="opaque-user")), \
             patch.object(routes, "resolve_client_id", AsyncMock(side_effect=HTTPException(status_code=403))) as resolve, \
             patch.object(ai, "_call_provider", AsyncMock()) as provider, \
             patch.object(tools, "sb_select", AsyncMock()) as select:
            with self.assertRaises(HTTPException) as error:
                await routes.intelligence_ask(payload={"question": "Pergunta", "client_id": "foreign"},
                    client_id="foreign", x_client_id=None, authorization="Bearer fixture")
            self.assertEqual(error.exception.status_code, 403)
            resolve.assert_awaited_once_with("foreign", "Bearer fixture")
            select.assert_not_awaited(); provider.assert_not_awaited()

    async def test_existing_ask_endpoint_preserves_response_contract(self):
        cid = "00000000-0000-0000-0000-000000000007"
        self.install(cid, {"meta"}, plan={"name": "read_campaigns"})
        saved = []
        async def insert(table, row):
            self.assertEqual(row["client_id"], cid); saved.append((table, row)); return {"id": f"record-{len(saved)}", **row}
        app = FastAPI(); app.include_router(routes.router)
        with patch.object(routes, "require_user_id", AsyncMock(return_value="opaque-user")), \
             patch.object(routes, "resolve_client_id", AsyncMock(return_value=cid)), \
             patch.object(ai, "provider_configured", return_value=True), \
             patch.object(ai, "sb_insert", insert), patch.object(ai, "sb_update", AsyncMock()):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
                response = await client.post("/api/intelligence/ask", json={"question": "Como estão as campanhas?", **PERIOD})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(set(body), {"ok", "conversation_id", "user_message", "assistant_message", "snapshot"})
        self.assertEqual(body["snapshot"]["period"]["days"], 1)
        self.assertTrue(body["assistant_message"]["content"]["evidence"])
        self.assertEqual(len(saved), 3)

    async def test_foreign_conversation_stops_before_model(self):
        with patch.object(ai, "provider_configured", return_value=True), \
             patch.object(ai, "conversation_messages", AsyncMock(side_effect=RuntimeError("CONVERSATION_NOT_FOUND"))), \
             patch.object(ai, "_investigate_question", AsyncMock()) as investigate:
            with self.assertRaisesRegex(RuntimeError, "CONVERSATION_NOT_FOUND"):
                await ai.ask_intelligence(client_id="opaque", user_id="user", question="Pergunta válida",
                    conversation_id="foreign", **PERIOD)
            investigate.assert_not_awaited()

    async def test_existing_provider_adapter_sends_output_cap(self):
        response = httpx.Response(200, json={"output_text": json.dumps({"name": "read_metrics"})}, request=httpx.Request("POST", "https://fixture"))
        import os
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}), \
             patch.object(httpx.AsyncClient, "post", AsyncMock(return_value=response)) as post, redirect_stdout(io.StringIO()):
            result = await ai._call_provider(payload={"question": "Pergunta"}, schema=tools.PLAN_SCHEMA,
                instructions=tools.PLAN_INSTRUCTIONS, max_output_tokens=100, timeout_seconds=10)
        self.assertEqual(result, {"name": "read_metrics"})
        self.assertEqual(post.await_args.kwargs["json"]["max_output_tokens"], 100)
        self.assertNotIn("tools", post.await_args.kwargs["json"])  # Existing provider contract, no agent loop.


    async def test_incompatible_periods_preserve_independent_grounded_facts(self):
        cid = "00000000-0000-0000-0000-000000000008"
        self.install(cid, {"meta", "ga4"}, reply={**answer("meta_investment"), "metric_ids": ["meta_investment", "sessions"]})
        with redirect_stdout(io.StringIO()):
            result, snapshot = await ai._investigate_question(client_id=cid, question="Compare os indicadores", period={"start": PERIOD["start"], "end": "2026-01-02"})
        self.assertEqual(len(result["evidence"]), 2)
        self.assertEqual(snapshot["quality"]["status"], "partial")
        self.assertTrue(any("Resposta parcial" in line for line in result["attention_points"]))

    async def test_read_timeout_and_input_budget_stop_without_retry(self):
        import asyncio
        cid = "00000000-0000-0000-0000-000000000009"
        async def slow(*args, **kwargs): await asyncio.sleep(1); return []
        with patch.object(tools, "READ_TIMEOUT", 0.001), patch.object(tools, "sb_select", slow), \
             patch.object(ai, "_call_provider", AsyncMock()) as model:
            with self.assertRaisesRegex(RuntimeError, "AI_PROVIDER_TIMEOUT"):
                await ai._investigate_question(client_id=cid, question="Pergunta", period=PERIOD)
            model.assert_not_awaited()
        with self.assertRaisesRegex(RuntimeError, "AI_TOOL_INPUT_LIMIT"):
            tools.bounded({"question": "x" * tools.MAX_INPUT_CHARS})

    async def test_daily_read_failure_keeps_persisted_commerce_evidence(self):
        cid = "00000000-0000-0000-0000-000000000010"
        session = tools.ReadTools(cid, PERIOD, AsyncMock()); session.active = {"ga4", "fbits"}
        with patch.object(tools, "sb_select", AsyncMock(side_effect=RuntimeError("fixture"))), \
             patch.object(tools, "resolve_commerce_context", AsyncMock(return_value={"provider": "fbits", "metrics": {"revenue": {"value": 100}}})):
            result = await session.execute({"name": "read_metrics"})
        self.assertTrue(any(m["value"] == 100 for m in result["metrics"]))
        self.assertTrue(result["limitations"])


    async def test_invented_numbers_are_never_published(self):
        cid = "00000000-0000-0000-0000-000000000011"
        self.install(cid, {"meta"}, reply={**answer("meta_investment"), "recommendations": [{"text": "Cresceu 99999 por cento.", "metric_ids": ["meta_investment"]}]})
        with self.assertRaisesRegex(RuntimeError, "AI_UNTRUSTED_NUMERIC_TEXT"):
            await self.investigate(cid)


    async def test_correct_investment_is_rendered_from_canonical_reference(self):
        self.install("opaque-a", {"meta"}, reply=answer("meta_investment"))
        result, _ = await self.investigate("opaque-a")
        self.assertIsInstance(result["direct_answer"], str)
        self.assertIn("100.0", result["direct_answer"])
        self.assertNotIn("200", result["direct_answer"])
        self.assertIn("currency; fonte meta", result["direct_answer"])
        self.assertIn(PERIOD["start"], result["direct_answer"])

    async def test_swapped_values_in_prose_are_rejected_even_when_present_in_payload(self):
        for metric, claim in [("meta_investment", "Investimento de 200."),
                              ("meta_revenue", "Receita de 100.")]:
            with self.subTest(metric=metric):
                before = len(self._cleanups)
                self.install("opaque-a", {"meta"}, reply={**answer(metric), "recommendations": [{"text": claim, "metric_ids": [metric]}]})
                with self.assertRaisesRegex(RuntimeError, "AI_UNTRUSTED_NUMERIC_TEXT"):
                    await self.investigate("opaque-a")
                # Both amounts really were in the evidence supplied to the model.
                self.assertTrue({100, 200} <= {m["value"] for m in self.payloads[-1]["payload"]["metrics"]})
                while len(self._cleanups) > before:
                    fn, args, kwargs = self._cleanups.pop(); fn(*args, **kwargs)

    async def test_revenue_reference_cannot_be_claimed_as_investment(self):
        def swapped(kwargs):
            ref = next(r["id"] for r in kwargs["payload"]["evidence_refs"] if r["metric_id"] == "meta_revenue")
            return {**answer("meta_investment"), "direct_answer": [ref]}
        self.install("opaque-a", {"meta"}, reply=swapped)
        with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_ANSWER"):
            await self.investigate("opaque-a")

    async def test_free_text_numeric_answer_is_not_a_canonical_reference(self):
        self.install("opaque-a", {"meta"}, reply={**answer("meta_investment"), "direct_answer": "Investimento de 200."})
        with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_ANSWER"):
            await self.investigate("opaque-a")

    async def test_references_cannot_be_reused_across_tenant_period_source_or_scope(self):
        import hashlib
        for dimension in ["tenant", "period", "source", "scope", "format", "value"]:
            with self.subTest(dimension=dimension):
                def stale(kwargs):
                    metric = copy.deepcopy(next(m for m in kwargs["payload"]["metrics"] if m["id"] == "meta_investment"))
                    binding = {"tenant": "opaque-a", "period": PERIOD, "metric": metric}
                    if dimension == "tenant": binding["tenant"] = "opaque-b"
                    elif dimension == "period": binding["period"] = {**PERIOD, "end": "2026-01-02"}
                    elif dimension == "value": metric["value"] = 200
                    else: metric[dimension] = "foreign"
                    ref = "ev_" + hashlib.sha256(json.dumps(binding, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
                    return {**answer("meta_investment"), "direct_answer": [ref]}
                before = len(self._cleanups)
                self.install("opaque-a", {"meta"}, reply=stale)
                with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_ANSWER"):
                    await self.investigate("opaque-a")
                while len(self._cleanups) > before:
                    fn, args, kwargs = self._cleanups.pop(); fn(*args, **kwargs)

    async def test_transport_timeouts_are_normalized_without_retry(self):
        import os
        for error in [httpx.ReadTimeout, httpx.ConnectTimeout, httpx.WriteTimeout, httpx.PoolTimeout]:
            with self.subTest(error=error.__name__), patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}), \
                 patch.object(httpx.AsyncClient, "post", AsyncMock(side_effect=error("fixture"))) as post, redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "^AI_PROVIDER_TIMEOUT$"):
                    await ai._call_provider(payload={}, schema=tools.PLAN_SCHEMA, instructions=tools.PLAN_INSTRUCTIONS)
                post.assert_awaited_once()

    async def test_provider_auth_and_non_timeout_transport_errors_are_unchanged(self):
        import os
        response = httpx.Response(401, request=httpx.Request("POST", "https://fixture"))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}), \
             patch.object(httpx.AsyncClient, "post", AsyncMock(return_value=response)), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "^AI_PROVIDER_ERROR_401$"):
                await ai._call_provider(payload={}, schema=tools.PLAN_SCHEMA, instructions=tools.PLAN_INSTRUCTIONS)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}), \
             patch.object(httpx.AsyncClient, "post", AsyncMock(side_effect=httpx.ConnectError("fixture"))), redirect_stdout(io.StringIO()):
            with self.assertRaises(httpx.ConnectError):
                await ai._call_provider(payload={}, schema=tools.PLAN_SCHEMA, instructions=tools.PLAN_INSTRUCTIONS)

    async def test_read_timeout_uses_existing_http_502_contract_without_persistence(self):
        app = FastAPI(); app.include_router(routes.router)
        with patch.object(routes, "require_user_id", AsyncMock(return_value="opaque-user")), \
             patch.object(routes, "resolve_client_id", AsyncMock(return_value="opaque-a")), \
             patch.object(ai, "provider_configured", return_value=True), \
             patch.object(tools.ReadTools, "discover", AsyncMock(return_value={"sources": ["meta"]})), \
             patch.object(ai, "_call_provider", AsyncMock(side_effect=httpx.ReadTimeout("fixture"))) as model, \
             patch.object(ai, "sb_insert", AsyncMock()) as insert, redirect_stdout(io.StringIO()):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
                response = await client.post("/api/intelligence/ask", json={"question": "Como estão as campanhas?", **PERIOD})
        self.assertEqual(response.status_code, 502, response.text)
        self.assertIn("demorou mais", response.json()["detail"])
        insert.assert_not_awaited(); model.assert_awaited_once()


class AskObservabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_failures_log_safe_code_request_status_and_duration(self):
        import os
        from api_support import _set_request_id, _reset_request_id
        cases = [
            (httpx.ReadTimeout("private-person@example.invalid secret-fixture"), "AI_PROVIDER_TIMEOUT", None),
            (httpx.Response(429, json={"error": "private-person@example.invalid secret-fixture"}), "AI_PROVIDER_ERROR_429", 429),
            (httpx.Response(200, json={"status": "incomplete", "output_text": "secret-fixture"}), "AI_PROVIDER_INCOMPLETE", 200),
            (httpx.Response(200, json={"output": []}), "AI_PROVIDER_EMPTY_RESPONSE", 200),
            (httpx.Response(200, json={"output_text": "private-person@example.invalid secret-fixture"}), "AI_PROVIDER_INVALID_RESPONSE", 200),
        ]
        for outcome, code, status in cases:
            with self.subTest(code=code):
                capture = io.StringIO()
                post = AsyncMock(side_effect=outcome) if isinstance(outcome, Exception) else AsyncMock(return_value=outcome)
                token = _set_request_id("observability-fixture-request")
                try:
                    with patch.dict(os.environ, {"OPENAI_API_KEY": "secret-fixture"}), \
                         patch.object(httpx.AsyncClient, "post", post), redirect_stdout(capture):
                        with self.assertRaises((RuntimeError, json.JSONDecodeError)) as caught:
                            await ai._call_provider(payload={"question": "private-person@example.invalid"},
                                schema=tools.PLAN_SCHEMA, instructions="secret-fixture", max_output_tokens=100)
                finally:
                    _reset_request_id(token)
                logs = capture.getvalue()
                self.assertIn("request_id=observability-fixture-request", logs)
                self.assertIn("error_code=" + code, logs)
                self.assertRegex(logs, r"elapsed_ms=\d+")
                if status is not None: self.assertIn(f"upstream_status={status}", logs)
                self.assertNotIn("secret-fixture", logs)
                self.assertNotIn("private-person", logs)
                if code != "AI_PROVIDER_INVALID_RESPONSE": self.assertEqual(str(caught.exception), code)
                post.assert_awaited_once()

    async def test_investigation_failure_is_correlated_with_exact_stage(self):
        from api_support import _set_request_id, _reset_request_id
        cases = [
            ("discover", "capability_discovery", RuntimeError("secret-fixture"), "AI_UNEXPECTED_ERROR"),
            ("plan", "tool_selection", RuntimeError("AI_PROVIDER_EMPTY_RESPONSE"), "AI_PROVIDER_EMPTY_RESPONSE"),
            ("execute", "tool_read", RuntimeError("AI_TOOL_ROW_LIMIT"), "AI_TOOL_ROW_LIMIT"),
            ("answer", "answer_generation", RuntimeError("AI_PROVIDER_INCOMPLETE"), "AI_PROVIDER_INCOMPLETE"),
            ("validation", "answer_validation", None, "AI_UNGROUNDED_ANSWER"),
        ]
        evidence = {"period": PERIOD, "metrics": [{"id": "metric", "value": 100, "label": "Indicador",
            "format": "currency", "source": "meta", "status": "confirmed"}],
            "sources": [{"id": "meta", "status": "available", "data_max_available": PERIOD["end"]}],
            "quality": {}, "limitations": [], "crossings": [], "top_campaigns": []}
        for where, stage, failure, code in cases:
            with self.subTest(stage=stage):
                model = AsyncMock(side_effect=[{"name": "read_metrics"}, {}])
                discovery = AsyncMock(return_value={"sources": ["meta"]})
                execute = AsyncMock(return_value=evidence)
                if where == "discover": discovery.side_effect = failure
                elif where == "execute": execute.side_effect = failure
                elif where == "plan": model.side_effect = failure
                elif where == "answer": model.side_effect = [{"name": "read_metrics"}, failure]
                capture = io.StringIO(); token = _set_request_id("observability-stage-request")
                try:
                    with patch.object(tools.ReadTools, "discover", discovery), \
                         patch.object(tools.ReadTools, "execute", execute), \
                         patch.object(ai, "_call_provider", model), redirect_stdout(capture):
                        with self.assertRaises(RuntimeError):
                            await ai._investigate_question(client_id="opaque", question="Pergunta", period=PERIOD)
                finally:
                    _reset_request_id(token)
                logs = capture.getvalue()
                self.assertIn("event=ask_failed", logs)
                self.assertIn("stage=" + stage, logs)
                self.assertIn("error_code=" + code, logs)
                self.assertIn("request_id=observability-stage-request", logs)
                self.assertNotIn("secret-fixture", logs)
                for call in model.await_args_list:
                    self.assertEqual(call.kwargs["request_id"], "observability-stage-request")

    async def test_route_logs_fallback_without_changing_http_errors(self):
        from api_support import _set_request_id, _reset_request_id
        app = FastAPI(); app.include_router(routes.router)
        for failure, status in [(RuntimeError("secret-fixture"), 502), (ValueError("secret-fixture"), 500)]:
            with self.subTest(status=status):
                capture = io.StringIO(); token = _set_request_id("observability-route-request")
                try:
                    with patch.object(routes, "_context", AsyncMock(return_value=("opaque", "opaque-user"))), \
                         patch.object(routes, "ask_intelligence", AsyncMock(side_effect=failure)), redirect_stdout(capture):
                        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://fixture") as client:
                            response = await client.post("/api/intelligence/ask", json={"question": "Pergunta"})
                finally:
                    _reset_request_id(token)
                self.assertEqual(response.status_code, status)
                logs = capture.getvalue()
                self.assertEqual(logs.count("event=ask_failed"), 1)
                self.assertIn("stage=ask", logs)
                self.assertIn("error_code=AI_UNEXPECTED_ERROR", logs)
                self.assertIn("request_id=observability-route-request", logs)
                self.assertNotIn("secret-fixture", logs)


class PartialEvidenceTests(unittest.IsolatedAsyncioTestCase):
    def evidence(self):
        from datetime import date, timedelta
        end = (date.fromisoformat(PERIOD["start"]) + timedelta(days=1)).isoformat()
        sources = [{"id": source, "status": "partial" if source == "source-c" else "available", "connected": True,
                    "data_max_available": PERIOD["start"] if source == "source-c" else end}
                   for source in ["source-a", "source-b", "source-c"]]
        metrics = [{"id": mid, "label": mid, "source": source, "value": value, "format": "currency",
                    "status": "partial" if source == "source-c" else "confirmed"}
                   for mid, source, value in [("investment_a", "source-a", 100), ("revenue_a", "source-a", 200),
                                               ("revenue_b", "source-b", 300), ("orders_c", "source-c", 4)]]
        return {"period": {"start": PERIOD["start"], "end": end}, "sources": sources, "metrics": metrics,
                "quality": {"status": "partial", "message": "Dados observados por fonte."},
                "limitations": [], "crossings": [], "top_campaigns": []}

    async def run_case(self, data, claims, cid="opaque-a", retained_refs=None, via_http=False):
        self.calls = []
        async def model(**kwargs):
            self.calls.append(copy.deepcopy(kwargs))
            if len(self.calls) == 1: return {"name": "read_metrics"}
            refs = kwargs["payload"]["evidence_refs"]
            result = {"direct_answer": [r["id"] for r in refs], "metric_ids": [r["metric_id"] for r in refs],
                      "evidence": [], "attention_points": [], "recommendations": claims, "next_steps": []}
            if retained_refs is not None: result["direct_answer"] = retained_refs
            return result
        async def execute(session, plan):
            self.assertEqual(session._client_id, cid)
            self.assertEqual(session.period, data["period"])
            return copy.deepcopy(data)
        with patch.object(tools.ReadTools, "discover", AsyncMock(return_value={"sources": [s["id"] for s in data["sources"]]})), \
             patch.object(tools.ReadTools, "execute", execute), \
             patch.object(ai, "_call_provider", AsyncMock(side_effect=model)), redirect_stdout(io.StringIO()):
            if not via_http:
                return await ai._investigate_question(client_id=cid, question="Compare os indicadores", period=data["period"])
            app = FastAPI(); app.include_router(routes.router)
            async def insert(table, row):
                self.assertEqual(row["client_id"], cid)
                return {"id": "opaque-record", **row}
            with patch.object(routes, "_context", AsyncMock(return_value=(cid, "opaque-user"))), \
                 patch.object(ai, "provider_configured", return_value=True), \
                 patch.object(ai, "sb_select", AsyncMock(return_value=[])), \
                 patch.object(ai, "sb_insert", AsyncMock(side_effect=insert)), \
                 patch.object(ai, "sb_update", AsyncMock()):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
                    response = await client.post("/api/intelligence/ask", json={"question": "Compare os indicadores", **data["period"]})
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(set(body), {"ok", "conversation_id", "user_message", "assistant_message", "snapshot"})
            return body["assistant_message"]["content"], body["snapshot"]

    async def test_partial_source_drops_only_invalid_crossing_and_keeps_independent_claims(self):
        claims = [{"text": "Revisar o indicador isoladamente.", "metric_ids": ["investment_a"]},
                  {"text": "Comparar os canais alinhados.", "metric_ids": ["investment_a", "revenue_b"]},
                  {"text": "Rebalancear todas as fontes em conjunto.", "metric_ids": ["investment_a", "orders_c"]},
                  {"text": "Investigar os pedidos observados isoladamente.", "metric_ids": ["orders_c"]}]
        result, snapshot = await self.run_case(self.evidence(), claims)
        self.assertEqual(len(result["evidence"]), 4)
        self.assertEqual(result["recommendations"], [claims[i]["text"] for i in [0, 1, 3]])
        self.assertNotIn(claims[2]["text"], json.dumps(result))
        self.assertEqual(snapshot["quality"]["status"], "partial")
        self.assertTrue(any("Resposta parcial" in text for text in result["attention_points"]))
        payload = self.calls[1]["payload"]
        self.assertIn(["source-a", "source-b"], payload["analysis_policy"]["comparable_source_groups"])
        self.assertNotIn(["source-a", "source-c"], payload["analysis_policy"]["comparable_source_groups"])
        self.assertEqual(payload["metrics"][0]["source_ids"], ["source-a"])
        self.assertEqual([call["max_output_tokens"] for call in self.calls], [100, 900])
        self.assertEqual([call["timeout_seconds"] for call in self.calls], [10, 15])

    async def test_coverage_mismatch_is_distinct_from_unavailable_source(self):
        data = self.evidence()
        self.assertEqual(ai._cited_sources_comparable(data, ["source-a", "source-c"]), (False, "source_not_available"))
        data["sources"][2]["status"] = "available"
        self.assertEqual(ai._cited_sources_comparable(data, ["source-a", "source-c"]), (False, "coverage_mismatch"))
        claim = {"text": "Combinar os resultados desalinhados.", "metric_ids": ["investment_a", "orders_c"]}
        result, _ = await self.run_case(data, [claim])
        self.assertFalse(result["recommendations"])
        self.assertTrue(any("Não há recomendações sustentadas" in text for text in result["attention_points"]))
        self.assertEqual(len(result["evidence"]), 4)

    async def test_missing_source_is_not_available_evidence_and_does_not_hide_other_sources(self):
        data = self.evidence(); data["sources"] = data["sources"][:2]
        result, _ = await self.run_case(data, [{"text": "Revisar a fonte disponível.", "metric_ids": ["investment_a"]}])
        self.assertNotIn("orders_c", result["metric_ids"])
        self.assertEqual(len(result["evidence"]), 3)
        self.assertEqual(result["recommendations"], ["Revisar a fonte disponível."])
        self.assertTrue(any("sem fonte disponível" in text for text in result["attention_points"]))
        # A model cannot restore an absent source by supplying a metric ID.
        with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_ANSWER"):
            await self.run_case(data, [{"text": "Usar fonte ausente.", "metric_ids": ["orders_c"]}])

    async def test_no_authoritative_origin_returns_explicit_empty_answer_without_answer_call(self):
        data = self.evidence(); data["sources"] = [{"id": "unrelated", "status": "available"}]
        result, _ = await self.run_case(data, [])
        self.assertFalse(result["metric_ids"])
        self.assertFalse(result["evidence"])
        self.assertIn("Não há evidências suficientes", result["direct_answer"])
        self.assertEqual(len(self.calls), 1)

    async def test_foreign_tenant_reference_remains_rejected_during_partial_recovery(self):
        data = self.evidence()
        await self.run_case(data, [], cid="opaque-a")
        stale_refs = [r["id"] for r in self.calls[1]["payload"]["evidence_refs"]]
        with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_ANSWER"):
            await self.run_case(data, [], cid="opaque-b", retained_refs=stale_refs)

    async def test_partial_recovery_does_not_hide_unsupported_numbers_or_causality(self):
        for text, code in [("Investimento de 200.", "AI_UNTRUSTED_NUMERIC_TEXT"),
                           ("Este indicador certamente causou a mudança.", "AI_UNSUPPORTED_CAUSALITY")]:
            with self.subTest(code=code), self.assertRaisesRegex(RuntimeError, code):
                await self.run_case(self.evidence(), [{"text": text, "metric_ids": ["investment_a", "orders_c"]}])


    async def test_partial_answer_is_persisted_through_existing_http_contract(self):
        claim = {"text": "Combinar as fontes sem cobertura alinhada.", "metric_ids": ["investment_a", "orders_c"]}
        result, snapshot = await self.run_case(self.evidence(), [claim], via_http=True)
        self.assertIsInstance(result["direct_answer"], str)
        self.assertEqual(len(result["evidence"]), 4)
        self.assertFalse(result["recommendations"])
        self.assertEqual(snapshot["quality"]["status"], "partial")
        self.assertEqual(set(result), {"direct_answer", "metric_ids", "evidence", "attention_points", "recommendations", "next_steps"})
        self.assertTrue(all(isinstance(text, str) for text in result["attention_points"]))
