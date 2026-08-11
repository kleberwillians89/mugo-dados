import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from routes import intelligence as routes
from services import intelligence


class IntelligenceAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_route_resolves_user_and_tenant_before_reading_context(self):
        snapshot = {"period": {"start": "2026-07-01", "end": "2026-07-30"}}
        with (
            patch.object(routes, "require_user_id", AsyncMock(return_value="user-1")),
            patch.object(routes, "resolve_client_id", AsyncMock(return_value="client-1")) as tenant,
            patch.object(
                routes,
                "calculate_intelligence_snapshot",
                AsyncMock(return_value=snapshot),
            ),
        ):
            result = await routes.intelligence_context(
                start="2026-07-01",
                end="2026-07-30",
                days=30,
                client_id="client-1",
                x_client_id=None,
                authorization="Bearer valid",
            )
        tenant.assert_awaited_once_with("client-1", "Bearer valid")
        self.assertEqual(result["snapshot"], snapshot)

    async def test_client_admin_generate_uses_only_resolved_membership_tenant(self):
        generated = AsyncMock(return_value={"ok": True, "status": "completed"})
        with (
            patch.object(routes, "require_user_id", AsyncMock(return_value="preview-amalie")),
            patch.object(routes, "resolve_client_id", AsyncMock(return_value="amalie")) as tenant,
            patch.object(routes, "generate_analysis", generated),
        ):
            result = await routes.intelligence_generate(
                payload={"start": "2026-08-01", "end": "2026-08-11"},
                client_id=None,
                x_client_id="amalie",
                authorization="Bearer client-admin",
            )
        tenant.assert_awaited_once_with("amalie", "Bearer client-admin")
        self.assertEqual(generated.await_args.kwargs["client_id"], "amalie")
        self.assertTrue(result["ok"])

    async def test_cross_tenant_denial_stops_generation(self):
        generated = AsyncMock()
        denied = HTTPException(status_code=403, detail="Usuário sem acesso ao client_id solicitado")
        with (
            patch.object(routes, "require_user_id", AsyncMock(return_value="preview-amalie")),
            patch.object(routes, "resolve_client_id", AsyncMock(side_effect=denied)),
            patch.object(routes, "generate_analysis", generated),
        ):
            with self.assertRaises(HTTPException) as raised:
                await routes.intelligence_generate(
                    payload={"start": "2026-08-01", "end": "2026-08-11"},
                    client_id=None,
                    x_client_id="outro-tenant",
                    authorization="Bearer client-admin",
                )
        self.assertEqual(raised.exception.status_code, 403)
        generated.assert_not_awaited()

    async def test_provider_pending_is_honest_and_persisted_as_new_version(self):
        snapshot = {
            "period": {"start": "2026-07-01", "end": "2026-07-30"},
            "sources": [],
            "quality": {"status": "limited"},
            "metrics": [],
        }
        insert = AsyncMock(return_value={"id": "analysis-1", "status": "configuration_pending"})
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False),
            patch.object(
                intelligence,
                "calculate_intelligence_snapshot",
                AsyncMock(return_value=snapshot),
            ),
            patch.object(intelligence, "sb_insert", insert),
        ):
            result = await intelligence.generate_analysis(
                client_id="client-1",
                user_id="user-1",
                start="2026-07-01",
                end="2026-07-30",
            )
        self.assertFalse(result["provider_configured"])
        self.assertEqual(insert.await_args.args[0], "ai_analyses")
        self.assertEqual(insert.await_args.args[1]["status"], "configuration_pending")

    async def test_generation_sends_canonical_policy_and_persists_same_schema(self):
        snapshot = {
            "period": {"start": "2026-08-01", "end": "2026-08-10"},
            "sources": [{"id": "shopify", "status": "available", "connected": True, "last_sync_at": "2026-08-10T12:00:00Z"}],
            "quality": {"score": 100, "status": "good"},
            "metrics": [{"id": "revenue", "value": 100.0, "previous_value": 90.0, "variation_percent": 11.11, "status": "confirmed"}],
            "crossings": [], "top_campaigns": [], "executive_context": {},
        }
        provider_result = {
            "executive": {"overall": "O faturamento avançou.", "main_change": "Faturamento em alta.", "opportunity": "Investigar os itens que sustentaram o avanço.", "attention": "Acompanhar a continuidade do movimento.", "priority_action": "Comparar o mix de produtos."},
            "insights": [{"category": "positive", "title": "Avanço de faturamento", "interpretation": "O faturamento avançou frente à base comparável.", "metric_ids": ["revenue"], "sources": ["shopify"], "impact": "high", "confidence": "high", "action": "Investigar o mix de produtos.", "reason": "A mudança é material e comparável."}],
            "actions": [{"priority": "investigate", "recommendation": "Comparar o mix de produtos.", "justification": "O faturamento mudou frente à base.", "sources": ["shopify"], "impact_expected": "Entender o componente do avanço.", "confidence": "high", "metric_id": "revenue"}],
        }
        call_provider = AsyncMock(return_value=provider_result)
        insert = AsyncMock(return_value={"id": "analysis-1", "status": "completed", "analysis": provider_result})
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "configured"}, clear=False),
            patch.object(intelligence, "calculate_intelligence_snapshot", AsyncMock(return_value=snapshot)),
            patch.object(intelligence, "_call_provider", call_provider),
            patch.object(intelligence, "sb_insert", insert),
        ):
            result = await intelligence.generate_analysis(client_id="amalie", user_id="preview-amalie", start="2026-08-01", end="2026-08-10")
        request = call_provider.await_args.kwargs
        self.assertEqual(request["instructions"], intelligence.ANALYSIS_INSTRUCTIONS)
        self.assertEqual(request["payload"]["analysis_policy"]["material_metric_ids"], ["revenue"])
        self.assertEqual(insert.await_args.args[1]["status"], "completed")
        self.assertEqual(result["analysis"]["analysis"], provider_result)

    async def test_conversation_read_filters_client_and_user(self):
        select = AsyncMock(
            side_effect=[
                [{"id": "conversation-1", "client_id": "client-1", "user_id": "user-1"}],
                [{"id": "message-1", "role": "assistant"}],
            ]
        )
        with patch.object(intelligence, "sb_select", select):
            result = await intelligence.conversation_messages(
                "client-1", "user-1", "conversation-1"
            )
        first_filters = select.await_args_list[0].kwargs["filters"]
        second_filters = select.await_args_list[1].kwargs["filters"]
        self.assertEqual(first_filters["client_id"], "eq.client-1")
        self.assertEqual(first_filters["user_id"], "eq.user-1")
        self.assertEqual(second_filters["client_id"], "eq.client-1")
        self.assertEqual(second_filters["user_id"], "eq.user-1")
        self.assertEqual(result["messages"][0]["id"], "message-1")

    async def test_foreign_conversation_is_not_exposed(self):
        with patch.object(intelligence, "sb_select", AsyncMock(return_value=[])):
            with self.assertRaisesRegex(RuntimeError, "CONVERSATION_NOT_FOUND"):
                await intelligence.conversation_messages(
                    "client-1", "user-1", "conversation-from-client-2"
                )

    def test_provider_error_maps_to_recoverable_http_error(self):
        with self.assertRaises(HTTPException) as raised:
            routes._raise_service_error(RuntimeError("AI_PROVIDER_ERROR_500"))
        self.assertEqual(raised.exception.status_code, 502)

    def test_ai_text_cannot_introduce_untrusted_numbers(self):
        intelligence._assert_no_untrusted_numeric_text(
            {"direct_answer": "A receita melhorou.", "metric_ids": ["revenue"]}
        )
        with self.assertRaisesRegex(RuntimeError, "AI_UNTRUSTED_NUMERIC_TEXT"):
            intelligence._assert_no_untrusted_numeric_text(
                {"direct_answer": "A receita aumentou 42 por cento.", "metric_ids": ["revenue"]}
            )


class IntelligenceInterpretationPolicyTests(unittest.TestCase):
    def snapshot(self, *, metrics=None, sources=None, start="2026-08-01", end="2026-08-10"):
        return {
            "period": {"start": start, "end": end},
            "metrics": metrics or [],
            "sources": sources or [
                {"id": "shopify", "status": "available", "connected": True, "last_sync_at": "2026-08-10T12:00:00Z"}
            ],
        }

    def metric(self, metric_id, value, previous, variation, status="confirmed", fmt="decimal"):
        return {"id": metric_id, "value": value, "previous_value": previous, "variation_percent": variation, "status": status, "format": fmt}

    def test_revenue_orders_ticket_decomposition_remains_comparable_and_material(self):
        policy = intelligence._build_analysis_policy(self.snapshot(metrics=[
            self.metric("revenue", 108, 100, 8),
            self.metric("orders", 94, 100, -6),
            self.metric("average_ticket", 115, 100, 15),
        ]))
        self.assertEqual(policy["comparable_metric_ids"], ["revenue", "orders", "average_ticket"])
        self.assertEqual(policy["material_metric_ids"], ["revenue", "orders", "average_ticket"])

    def test_investment_up_revenue_down_and_roas_down_are_available_as_related_evidence(self):
        policy = intelligence._build_analysis_policy(self.snapshot(metrics=[
            self.metric("investment", 130, 100, 30),
            self.metric("meta_revenue", 90, 100, -10),
            self.metric("roas", 0.69, 1, -31),
        ]))
        self.assertEqual(len(policy["material_metric_ids"]), 3)

    def test_stale_cross_source_data_blocks_cross_source_comparison(self):
        policy = intelligence._build_analysis_policy(self.snapshot(sources=[
            {"id": "shopify", "status": "available", "connected": True, "last_sync_at": "2026-08-10T12:00:00Z"},
            {"id": "meta", "status": "available", "connected": True, "last_sync_at": "2026-08-09T12:00:00Z"},
        ]))
        self.assertFalse(policy["cross_source_comparison_allowed"])
        self.assertEqual(policy["source_sync_spread_hours"], 24)

    def test_connected_without_data_and_null_are_unavailable_not_zero(self):
        policy = intelligence._build_analysis_policy(self.snapshot(
            metrics=[self.metric("google_ads_revenue", None, None, None, "unavailable")],
            sources=[{"id": "google_ads", "status": "connected_no_data", "connected": True, "last_sync_at": None}],
        ))
        self.assertEqual(policy["unavailable_metric_ids"], ["google_ads_revenue"])
        self.assertFalse(policy["cross_source_comparison_allowed"])

    def test_today_is_explicitly_partial(self):
        today = intelligence.datetime.now(intelligence.ZoneInfo("America/Sao_Paulo")).date().isoformat()
        policy = intelligence._build_analysis_policy(self.snapshot(start=today, end=today))
        self.assertTrue(policy["includes_partial_today"])
        self.assertEqual(policy["today_date"], today)

    def test_no_previous_period_does_not_create_comparison(self):
        policy = intelligence._build_analysis_policy(self.snapshot(metrics=[
            self.metric("revenue", 100, None, None),
        ]))
        self.assertEqual(policy["comparable_metric_ids"], [])

    def test_small_variation_is_not_material(self):
        policy = intelligence._build_analysis_policy(self.snapshot(metrics=[
            self.metric("revenue", 101, 100, 1),
        ]))
        self.assertEqual(policy["material_metric_ids"], [])

    def test_small_revenue_percent_can_be_material_by_absolute_impact(self):
        policy = intelligence._build_analysis_policy(self.snapshot(metrics=[
            self.metric("revenue", 1_030_000, 1_000_000, 3, fmt="currency"),
        ]))
        self.assertIn("revenue", policy["material_metric_ids"])
        self.assertIn("revenue", policy["primary_metric_ids"])
        self.assertTrue(policy["metric_changes"][0]["absolute_material"])

    def test_small_low_impact_metric_remains_noise(self):
        policy = intelligence._build_analysis_policy(self.snapshot(metrics=[
            self.metric("ctr", 2.06, 2.0, 3, fmt="percent"),
        ]))
        self.assertNotIn("ctr", policy["material_metric_ids"])
        self.assertNotIn("ctr", policy["primary_metric_ids"])

    def test_percentage_candidate_with_irrelevant_absolute_value_is_not_automatic_primary(self):
        policy = intelligence._build_analysis_policy(self.snapshot(metrics=[
            self.metric("revenue", 1.08, 1.0, 8, fmt="currency"),
        ]))
        self.assertIn("revenue", policy["material_metric_ids"])
        self.assertNotIn("revenue", policy["primary_metric_ids"])

    def test_small_change_can_support_an_important_contradiction(self):
        policy = intelligence._build_analysis_policy(self.snapshot(metrics=[
            self.metric("revenue", 103, 100, 3, fmt="currency"),
            self.metric("orders", 90, 100, -10, fmt="integer"),
            self.metric("average_ticket", 114, 100, 14, fmt="currency"),
        ]))
        self.assertNotIn("revenue", policy["material_metric_ids"])
        self.assertIn("revenue", policy["supporting_metric_ids"])

    def test_rejects_unsupported_causality_and_ungrounded_insights(self):
        snapshot = self.snapshot(metrics=[self.metric("revenue", 108, 100, 8)])
        causal = {"insights": [{
            "metric_ids": ["revenue"], "sources": ["shopify"],
            "interpretation": "O investimento causou o crescimento.", "reason": "Movimentos simultâneos.",
        }], "actions": []}
        with self.assertRaisesRegex(RuntimeError, "AI_UNSUPPORTED_CAUSALITY"):
            intelligence._validate_analysis_grounding(causal, snapshot)
        ungrounded = {"insights": [{
            "metric_ids": ["invented"], "sources": ["shopify"],
            "interpretation": "Leitura sem dado.", "reason": "Sem evidência.",
        }], "actions": []}
        with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_INSIGHT"):
            intelligence._validate_analysis_grounding(ungrounded, snapshot)

    def test_rejects_temporally_incompatible_cross_source_insight(self):
        snapshot = self.snapshot(
            metrics=[self.metric("revenue", 108, 100, 8), self.metric("investment", 90, 100, -10)],
            sources=[
                {"id": "shopify", "status": "available", "connected": True, "last_sync_at": "2026-08-10T12:00:00Z"},
                {"id": "meta", "status": "available", "connected": True, "last_sync_at": "2026-08-09T12:00:00Z"},
            ],
        )
        analysis = {"insights": [{
            "metric_ids": ["revenue", "investment"], "sources": ["shopify", "meta"],
            "interpretation": "Os movimentos ocorreram no mesmo período.", "reason": "Comparação entre fontes.",
        }], "actions": []}
        with self.assertRaisesRegex(RuntimeError, "AI_TEMPORALLY_INCOMPATIBLE_SOURCES"):
            intelligence._validate_analysis_grounding(analysis, snapshot)

    def test_same_closed_coverage_allows_comparison_despite_different_job_times(self):
        policy = intelligence._build_analysis_policy(self.snapshot(sources=[
            {"id": "shopify", "status": "available", "connected": True, "last_sync_at": "2026-08-11T10:00:00Z", "data_max_available": "2026-08-10"},
            {"id": "meta", "status": "available", "connected": True, "last_sync_at": "2026-08-11T02:00:00Z", "data_max_available": "2026-08-10"},
        ]))
        self.assertEqual(policy["temporal_compatibility_mode"], "coverage")
        self.assertTrue(policy["cross_source_comparison_allowed"])
        self.assertEqual(policy["common_coverage_through"], "2026-08-10")

    def test_different_coverage_blocks_cross_source_comparison(self):
        policy = intelligence._build_analysis_policy(self.snapshot(sources=[
            {"id": "shopify", "status": "available", "connected": True, "last_sync_at": "2026-08-11T10:00:00Z", "data_max_available": "2026-08-11"},
            {"id": "meta", "status": "available", "connected": True, "last_sync_at": "2026-08-11T02:00:00Z", "data_max_available": "2026-08-10"},
        ], end="2026-08-11"))
        self.assertFalse(policy["cross_source_comparison_allowed"])
        self.assertFalse(policy["covers_period_end"])

    def test_fresh_job_with_yesterday_coverage_does_not_claim_today_coverage(self):
        policy = intelligence._build_analysis_policy(self.snapshot(sources=[
            {"id": "shopify", "status": "available", "connected": True, "last_sync_at": "2026-08-11T12:00:00Z", "data_max_available": "2026-08-10"},
        ], end="2026-08-11"))
        self.assertFalse(policy["covers_period_end"])
        self.assertEqual(policy["source_coverage"]["shopify"], "2026-08-10")

    def test_missing_coverage_and_timestamp_blocks_comparison(self):
        policy = intelligence._build_analysis_policy(self.snapshot(sources=[
            {"id": "shopify", "status": "available", "connected": True, "last_sync_at": None, "data_max_available": None},
            {"id": "meta", "status": "available", "connected": True, "last_sync_at": None, "data_max_available": None},
        ]))
        self.assertEqual(policy["temporal_compatibility_mode"], "insufficient_temporal_evidence")
        self.assertFalse(policy["cross_source_comparison_allowed"])

    def test_today_requires_explicit_partial_data_limitation(self):
        today = intelligence.datetime.now(intelligence.ZoneInfo("America/Sao_Paulo")).date().isoformat()
        snapshot = self.snapshot(metrics=[self.metric("revenue", 100, 90, 11)], start=today, end=today)
        without_limitation = {"executive": {"overall": "O faturamento avançou."}, "insights": [], "actions": []}
        with self.assertRaisesRegex(RuntimeError, "AI_MISSING_PARTIAL_TODAY_LIMITATION"):
            intelligence._validate_analysis_grounding(without_limitation, snapshot)
        with_limitation = {"executive": {"overall": "Os dados de hoje ainda estão em formação."}, "insights": [], "actions": []}
        intelligence._validate_analysis_grounding(with_limitation, snapshot)

    def test_canonical_prompt_forbids_recalculation_benchmarks_and_generic_actions(self):
        prompt = intelligence.ANALYSIS_INSTRUCTIONS.lower()
        self.assertIn("nunca os recalcule", prompt)
        self.assertIn("benchmark", prompt)
        self.assertIn("recomendações genéricas", prompt)
        self.assertIn("fato, interpretação e hipótese", prompt)


class IntelligenceMigrationTests(unittest.TestCase):
    def test_tables_have_no_authenticated_direct_access(self):
        sql = (
            Path(__file__).parents[2]
            / "supabase/migrations/20260802_000021_intelligence_workspace.sql"
        ).read_text().lower()
        self.assertIn("create table if not exists public.ai_analyses", sql)
        self.assertIn("create table if not exists public.ai_conversations", sql)
        self.assertIn("create table if not exists public.ai_messages", sql)
        self.assertIn("revoke all on public.ai_analyses from anon, authenticated", sql)
        self.assertNotIn("create policy", sql)


if __name__ == "__main__":
    unittest.main()
