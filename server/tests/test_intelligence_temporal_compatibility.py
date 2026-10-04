"""AI_TEMPORALLY_INCOMPATIBLE_SOURCES: compatibilidade por par, não global.

`cross_source_comparison_allowed` é um veredito único sobre TODAS as fontes
ativas, mas era aplicado por insight contra as duas fontes que aquele insight
cita. Com uma fonte cobrindo um dia a mais que as outras, todo cruzamento era
recusado — inclusive entre duas fontes de cobertura idêntica, perfeitamente
comparáveis.

Reproduz o request 45c06ecc3ea6464985a1bfa87d31eef6 (Curavino, FBITS, período
2026-09-05 → 2026-10-04, 10 metrics / 5 sources) com o
`calculate_intelligence_snapshot` real.
"""

from __future__ import annotations

import io
import itertools
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import business_context, commerce_context, external_research, intelligence
from test_intelligence_partial_today import frozen_today
from test_intelligence_real_generation import (
    ALL_CONNECTIONS,
    CLIENT,
    executive_context,
    fbits_summary,
)

PERIOD_START = "2026-09-05"
PERIOD_END = "2026-10-04"

# KPIs oficiais da FBITS no request real.
REVENUE = 32452.42
ORDERS = 70
AVERAGE_TICKET = 463.61

# Coberturas do caso real: o comércio tem um dia a mais que as plataformas.
COMMERCE_COVERAGE = "2026-10-04"
PLATFORM_COVERAGE = "2026-09-30"

PARTIAL_TODAY_CAVEAT = "Os dados de hoje ainda estão em formação."


def curavino_summary() -> Dict[str, Any]:
    summary = fbits_summary()
    summary["period"] = {"start": PERIOD_START, "end": PERIOD_END}
    summary["summary"] = {
        **summary["summary"],
        "receita_oficial": REVENUE, "pedidos": ORDERS, "ticket_medio": AVERAGE_TICKET,
    }
    summary["comparison"] = {
        "receita_oficial": {"current": REVENUE, "previous": 29000.0, "change_percent": 11.9},
        "pedidos": {"current": ORDERS, "previous": 64, "change_percent": 9.4},
        "ticket_medio": {"current": AVERAGE_TICKET, "previous": 453.12, "change_percent": 2.3},
    }
    summary["status_distribution"] = [{"status": "Pago", "pedidos": ORDERS, "valor": REVENUE}]
    return summary


def analysis_with(
    *,
    metric_ids: List[str],
    sources: List[str],
    category: str = "opportunity",
    caveat: bool = True,
) -> Dict[str, Any]:
    """Análise do modelo com um segundo insight no index=1, como no request."""
    return {
        "executive": {
            "overall": "O faturamento do período avançou.",
            "main_change": "Faturamento em alta.",
            "opportunity": "Investigar o mix de produtos.",
            "attention": (
                f"Acompanhar a continuidade. {PARTIAL_TODAY_CAVEAT}" if caveat
                else "Acompanhar a continuidade."
            ),
            "priority_action": "Comparar o mix.",
        },
        "insights": [
            {
                "category": "positive", "title": "Avanço de faturamento",
                "interpretation": "O faturamento avançou frente à base comparável.",
                "metric_ids": ["revenue"], "sources": ["commerce"],
                "impact": "high", "confidence": "high",
                "action": "Investigar o mix.", "reason": "A mudança é material.",
            },
            {
                # index=1, o insight que falhava em produção.
                "category": category, "title": "Leitura combinada",
                "interpretation": "Os indicadores se movem no mesmo período.",
                "metric_ids": metric_ids, "sources": sources,
                "impact": "medium", "confidence": "medium",
                "action": "Investigar a relação.", "reason": "Movimento simultâneo.",
            },
        ],
        "actions": [
            {
                "priority": "investigate", "recommendation": "Comparar o mix.",
                "justification": "O faturamento mudou.", "sources": ["commerce"],
                "impact_expected": "Entender o avanço.", "confidence": "high",
                "metric_id": "revenue",
            },
        ],
    }


class RealSnapshotHarness(unittest.IsolatedAsyncioTestCase):
    snapshot: Dict[str, Any]

    def setUp(self) -> None:
        external_research.set_provider(None)
        self.addCleanup(external_research.set_provider, None)

    async def asyncSetUp(self) -> None:
        from services import fbits_reporting

        with (
            redirect_stdout(io.StringIO()),
            patch.object(
                intelligence, "_read_model_executive_context",
                AsyncMock(return_value=executive_context()),
            ),
            patch.object(intelligence, "sb_select", AsyncMock(return_value=[])),
            patch.object(intelligence, "list_generic_connections", AsyncMock(return_value=[])),
            patch.object(commerce_context, "sb_select", AsyncMock(return_value=ALL_CONNECTIONS)),
            patch.object(
                fbits_reporting, "build_fbits_summary",
                AsyncMock(return_value=curavino_summary()),
            ),
            patch.object(business_context, "sb_select", AsyncMock(return_value=[])),
        ):
            self.snapshot = await intelligence.calculate_intelligence_snapshot(
                client_id=CLIENT, start=PERIOD_START, end=PERIOD_END,
            )

    def policy(self) -> Dict[str, Any]:
        with frozen_today():
            return intelligence._build_analysis_policy(self.snapshot)

    def validate(self, analysis: Dict[str, Any]) -> None:
        with frozen_today():
            intelligence._validate_analysis_grounding(
                analysis, self.snapshot, policy=self.policy(),
            )


class TheCoverageEvidenceTests(RealSnapshotHarness):
    """Cobertura temporal real de cada fonte, do snapshot de produção."""

    async def test_the_fixture_matches_the_production_shape(self):
        self.assertEqual(len(self.snapshot["metrics"]), 10)
        self.assertEqual(len(self.snapshot["sources"]), 5)
        self.assertEqual(self.snapshot["period"]["start"], PERIOD_START)
        self.assertEqual(self.snapshot["period"]["end"], PERIOD_END)
        self.assertEqual(self.snapshot["commerce_context"]["provider"], "fbits")

    async def test_commerce_covers_one_day_more_than_the_platforms(self):
        coverage = {item["id"]: item["data_max_available"] for item in self.snapshot["sources"]}
        self.assertEqual(coverage["commerce"], COMMERCE_COVERAGE)
        for source_id in ("meta", "google_ads", "ga4", "instagram"):
            self.assertEqual(coverage[source_id], PLATFORM_COVERAGE)

    async def test_every_source_is_connected_and_available(self):
        # complete_sources é verdadeiro: a recusa não vem do status.
        for source in self.snapshot["sources"]:
            self.assertTrue(source["connected"], source["id"])
            self.assertEqual(source["status"], "available", source["id"])

    async def test_coverage_is_the_deciding_mode_not_freshness(self):
        policy = self.policy()
        self.assertEqual(policy["temporal_compatibility_mode"], "coverage")
        # O spread de sincronização caberia no limite, mas cobertura decide.
        self.assertIsNotNone(policy["source_sync_spread_hours"])
        self.assertLessEqual(
            policy["source_sync_spread_hours"],
            intelligence.INTELLIGENCE_CROSS_SOURCE_MAX_LAG_HOURS,
        )

    async def test_the_global_verdict_is_false_because_two_coverages_exist(self):
        policy = self.policy()
        self.assertFalse(policy["cross_source_comparison_allowed"])
        self.assertEqual(
            sorted(set(policy["source_coverage"].values())),
            [PLATFORM_COVERAGE, COMMERCE_COVERAGE],
        )
        self.assertIsNone(policy["common_coverage_through"])


class TheBugIsProvedTests(RealSnapshotHarness):
    """O veredito global contradiz a verdade do par citado."""

    async def test_the_global_verdict_blocks_pairs_that_are_actually_aligned(self):
        policy = self.policy()
        self.assertFalse(policy["cross_source_comparison_allowed"])
        # meta e google_ads têm cobertura idêntica: comparar é sólido.
        compatible, mode = intelligence._cited_sources_comparable(
            self.snapshot, ["meta", "google_ads"],
        )
        self.assertTrue(compatible)
        self.assertEqual(mode, "coverage")

    async def test_six_of_ten_pairs_were_false_positives(self):
        source_ids = [item["id"] for item in self.snapshot["sources"]]
        aligned, misaligned = [], []
        for pair in itertools.combinations(source_ids, 2):
            compatible, _ = intelligence._cited_sources_comparable(self.snapshot, list(pair))
            (aligned if compatible else misaligned).append(pair)
        self.assertEqual(len(aligned), 6)
        self.assertEqual(len(misaligned), 4)
        # Os 4 corretos são exatamente os que envolvem o comércio.
        self.assertTrue(all("commerce" in pair for pair in misaligned))


class CompatiblePairsAreAllowedTests(RealSnapshotHarness):
    async def test_two_platforms_with_identical_coverage_pass(self):
        self.validate(
            analysis_with(
                metric_ids=["meta_investment", "google_ads_investment"],
                sources=["meta", "google_ads"],
            ),
        )

    async def test_sessions_and_platform_spend_pass(self):
        self.validate(
            analysis_with(metric_ids=["sessions", "meta_investment"], sources=["ga4", "meta"]),
        )

    async def test_every_aligned_pair_passes(self):
        for pair in itertools.combinations(["meta", "google_ads", "ga4", "instagram"], 2):
            with self.subTest(pair=pair):
                self.validate(
                    analysis_with(
                        metric_ids=["meta_investment", "sessions"], sources=list(pair),
                    ),
                )


class IncompatiblePairsStayBlockedTests(RealSnapshotHarness):
    async def test_commerce_against_a_platform_is_still_refused(self):
        with self.assertRaisesRegex(RuntimeError, "AI_TEMPORALLY_INCOMPATIBLE_SOURCES"):
            self.validate(
                analysis_with(metric_ids=["revenue", "meta_investment"], sources=["commerce", "meta"]),
            )

    async def test_every_misaligned_pair_is_refused(self):
        for platform in ("meta", "google_ads", "ga4", "instagram"):
            with self.subTest(platform=platform):
                with self.assertRaisesRegex(RuntimeError, "AI_TEMPORALLY_INCOMPATIBLE_SOURCES"):
                    self.validate(
                        analysis_with(
                            metric_ids=["revenue", "sessions"], sources=["commerce", platform],
                        ),
                    )

    async def test_the_refusal_reports_coverage_mismatch(self):
        compatible, mode = intelligence._cited_sources_comparable(
            self.snapshot, ["commerce", "meta"],
        )
        self.assertFalse(compatible)
        self.assertEqual(mode, "coverage_mismatch")

    async def test_freshness_never_overrides_available_coverage(self):
        # Cobertura e freshness são conceitos distintos: com cobertura para
        # todas as fontes citadas, o spread de sincronização é irrelevante.
        self.assertLessEqual(
            self.policy()["source_sync_spread_hours"],
            intelligence.INTELLIGENCE_CROSS_SOURCE_MAX_LAG_HOURS,
        )
        compatible, mode = intelligence._cited_sources_comparable(
            self.snapshot, ["commerce", "meta"],
        )
        self.assertFalse(compatible)
        self.assertNotEqual(mode, "freshness_fallback")

    async def test_a_source_without_data_is_refused(self):
        degraded = {
            **self.snapshot,
            "sources": [
                {**item, "status": "connected_no_data"} if item["id"] == "meta" else item
                for item in self.snapshot["sources"]
            ],
        }
        compatible, mode = intelligence._cited_sources_comparable(degraded, ["ga4", "meta"])
        self.assertFalse(compatible)
        self.assertEqual(mode, "source_not_available")


class FreshnessFallbackTests(RealSnapshotHarness):
    """Sem cobertura para todas as fontes citadas, freshness é o último recurso."""

    def without_coverage(self, spread_hours: int) -> Dict[str, Any]:
        return {
            **self.snapshot,
            "sources": [
                {
                    **item,
                    "data_max_available": None,
                    "last_sync_at": (
                        "2026-10-04T12:00:00Z" if item["id"] == "ga4"
                        else f"2026-10-04T{12 + spread_hours:02d}:00:00Z"
                    ),
                }
                for item in self.snapshot["sources"]
            ],
        }

    async def test_a_small_spread_is_accepted(self):
        compatible, mode = intelligence._cited_sources_comparable(
            self.without_coverage(2), ["ga4", "meta"],
        )
        self.assertTrue(compatible)
        self.assertEqual(mode, "freshness_fallback")

    async def test_a_large_spread_is_refused(self):
        compatible, mode = intelligence._cited_sources_comparable(
            self.without_coverage(11), ["ga4", "meta"],
        )
        self.assertFalse(compatible)
        self.assertEqual(mode, "freshness_spread_exceeded")

    async def test_missing_temporal_evidence_is_refused(self):
        blind = {
            **self.snapshot,
            "sources": [
                {**item, "data_max_available": None, "last_sync_at": None}
                for item in self.snapshot["sources"]
            ],
        }
        compatible, mode = intelligence._cited_sources_comparable(blind, ["ga4", "meta"])
        self.assertFalse(compatible)
        self.assertEqual(mode, "insufficient_temporal_evidence")


class AggregationIsNotComparisonTests(RealSnapshotHarness):
    """Indicador que o backend compôs não é o modelo cruzando fontes."""

    async def test_roas_names_its_component_sources_without_being_a_comparison(self):
        self.assertTrue(
            intelligence._aggregate_only_sources(
                self.snapshot, ["roas"], ["commerce", "meta", "google_ads"],
            ),
        )

    async def test_investment_names_both_platforms_without_being_a_comparison(self):
        self.assertTrue(
            intelligence._aggregate_only_sources(
                self.snapshot, ["investment"], ["meta", "google_ads"],
            ),
        )

    async def test_an_insight_citing_only_roas_passes(self):
        # Mesmo misturando grupos de cobertura: o número já foi calculado.
        self.validate(
            analysis_with(metric_ids=["roas"], sources=["commerce", "meta", "google_ads"]),
        )

    async def test_an_insight_citing_only_investment_passes(self):
        self.validate(analysis_with(metric_ids=["investment"], sources=["meta", "google_ads"]))

    async def test_a_single_metric_cannot_justify_an_unrelated_source(self):
        # revenue vem só do comércio: citar meta junto é comparação de fato.
        self.assertFalse(
            intelligence._aggregate_only_sources(self.snapshot, ["revenue"], ["commerce", "meta"]),
        )
        with self.assertRaisesRegex(RuntimeError, "AI_TEMPORALLY_INCOMPATIBLE_SOURCES"):
            self.validate(analysis_with(metric_ids=["revenue"], sources=["commerce", "meta"]))

    async def test_two_metrics_are_always_a_comparison(self):
        self.assertFalse(
            intelligence._aggregate_only_sources(
                self.snapshot, ["roas", "revenue"], ["commerce", "meta"],
            ),
        )

    async def test_aggregation_does_not_bypass_causality(self):
        analysis = analysis_with(metric_ids=["roas"], sources=["commerce", "meta", "google_ads"])
        analysis["insights"][1]["interpretation"] = "A mídia paga causou o avanço."
        with self.assertRaisesRegex(RuntimeError, "AI_UNSUPPORTED_CAUSALITY"):
            self.validate(analysis)

    async def test_aggregation_does_not_bypass_grounding(self):
        with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_INSIGHT"):
            self.validate(analysis_with(metric_ids=["roas"], sources=["tiktok"]))


class TheModelContractTests(RealSnapshotHarness):
    async def test_the_policy_names_the_comparable_groups(self):
        groups = self.policy()["comparable_source_groups"]
        self.assertEqual(
            groups, [["ga4", "google_ads", "instagram", "meta"], ["commerce"]],
        )

    async def test_every_group_is_internally_comparable(self):
        for group in self.policy()["comparable_source_groups"]:
            for pair in itertools.combinations(group, 2):
                with self.subTest(pair=pair):
                    compatible, _ = intelligence._cited_sources_comparable(
                        self.snapshot, list(pair),
                    )
                    self.assertTrue(compatible)

    async def test_sources_in_different_groups_are_never_comparable(self):
        groups = self.policy()["comparable_source_groups"]
        for first, second in itertools.combinations(groups, 2):
            for left in first:
                for right in second:
                    with self.subTest(pair=(left, right)):
                        compatible, _ = intelligence._cited_sources_comparable(
                            self.snapshot, [left, right],
                        )
                        self.assertFalse(compatible)

    async def test_the_instructions_tell_the_model_about_the_groups(self):
        instructions = intelligence.ANALYSIS_INSTRUCTIONS
        self.assertIn("comparable_source_groups", instructions)
        self.assertIn("cross_source_comparison_allowed", instructions)
        # E que citar um agregado do backend não é cruzar fontes.
        self.assertIn("não é cruzar fontes", instructions)

    async def test_a_source_without_coverage_is_in_no_group(self):
        blind = {
            **self.snapshot,
            "sources": [
                {**item, "data_max_available": None} if item["id"] == "instagram" else item
                for item in self.snapshot["sources"]
            ],
        }
        groups = intelligence._comparable_source_groups(blind)
        self.assertNotIn("instagram", [item for group in groups for item in group])


class SurgicalObservabilityTests(RealSnapshotHarness):
    def failure_fields(self, analysis: Dict[str, Any], expected: str) -> Dict[str, str]:
        output = io.StringIO()
        with redirect_stdout(output), frozen_today():
            with self.assertRaisesRegex(RuntimeError, expected):
                intelligence._validate_analysis_grounding(
                    analysis, self.snapshot, policy=self.policy(),
                    request_id="req-45c06ec",
                )
        lines = [
            line for line in output.getvalue().splitlines()
            if "event=grounding_validation_failed" in line
        ]
        self.assertEqual(len(lines), 1, output.getvalue())
        fields: Dict[str, str] = {}
        for token in lines[0].split(" "):
            if "=" in token:
                key, _, value = token.partition("=")
                fields.setdefault(key, value)
        return fields

    async def test_the_cross_source_refusal_names_metrics_sources_and_coverage(self):
        fields = self.failure_fields(
            analysis_with(metric_ids=["revenue", "meta_investment"], sources=["commerce", "meta"]),
            "AI_TEMPORALLY_INCOMPATIBLE_SOURCES",
        )
        self.assertEqual(fields["kind"], "insight")
        self.assertEqual(fields["index"], "1")
        self.assertEqual(fields["category"], "opportunity")
        self.assertEqual(fields["reason"], "cross_source_not_allowed")
        self.assertEqual(fields["metric_ids"], "revenue,meta_investment")
        self.assertEqual(fields["source_ids"], "commerce,meta")
        self.assertEqual(fields["detail"], "coverage_mismatch")
        self.assertEqual(
            fields["coverage"], f"commerce:{COMMERCE_COVERAGE},meta:{PLATFORM_COVERAGE}",
        )
        self.assertEqual(fields["request_id"], "req-45c06ec")

    async def test_no_model_prose_is_logged(self):
        output = io.StringIO()
        with redirect_stdout(output), frozen_today():
            with self.assertRaises(RuntimeError):
                intelligence._validate_analysis_grounding(
                    analysis_with(
                        metric_ids=["revenue", "meta_investment"], sources=["commerce", "meta"],
                    ),
                    self.snapshot, policy=self.policy(), request_id="req-45c06ec",
                )
        logged = output.getvalue()
        for prose in (
            "Leitura combinada",
            "Os indicadores se movem no mesmo período.",
            "Investigar a relação.",
            "Movimento simultâneo.",
        ):
            self.assertNotIn(prose, logged)

    async def test_nothing_is_logged_for_a_compatible_pair(self):
        output = io.StringIO()
        with redirect_stdout(output), frozen_today():
            intelligence._validate_analysis_grounding(
                analysis_with(
                    metric_ids=["meta_investment", "sessions"], sources=["meta", "ga4"],
                ),
                self.snapshot, policy=self.policy(), request_id="req-45c06ec",
            )
        self.assertNotIn("grounding_validation_failed", output.getvalue())


class EndToEndTests(RealSnapshotHarness):
    async def generate(self, analysis: Dict[str, Any]) -> tuple[Any, BaseException | None, str]:
        output = io.StringIO()
        with (
            redirect_stdout(output),
            frozen_today(),
            patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-key"}, clear=False),
            patch.object(
                intelligence, "calculate_intelligence_snapshot",
                AsyncMock(return_value=self.snapshot),
            ),
            patch.object(intelligence, "_call_provider", AsyncMock(return_value=analysis)),
            patch.object(intelligence, "sb_select", AsyncMock(return_value=[])),
            patch.object(
                intelligence, "sb_insert",
                AsyncMock(side_effect=lambda _table, row: {"id": "an-1", **row}),
            ),
        ):
            try:
                result, error = await intelligence.generate_analysis(
                    client_id=CLIENT, user_id="user-1",
                    start=PERIOD_START, end=PERIOD_END, request_id="req-45c06ec",
                ), None
            except BaseException as exc:  # noqa: BLE001 - o erro é o objeto do teste
                result, error = None, exc
        return result, error, output.getvalue()

    async def test_the_production_case_now_completes(self):
        result, error, output = await self.generate(
            analysis_with(
                metric_ids=["meta_investment", "google_ads_investment"],
                sources=["meta", "google_ads"],
            ),
        )
        self.assertIsNone(error, output)
        self.assertEqual(result["status"], "completed")

    async def test_the_limitation_is_injected_when_the_model_omits_it(self):
        result, error, output = await self.generate(
            analysis_with(
                metric_ids=["meta_investment", "google_ads_investment"],
                sources=["meta", "google_ads"], caveat=False,
            ),
        )
        self.assertIsNone(error, output)
        titles = [item["title"] for item in result["analysis"]["analysis"]["insights"]]
        self.assertIn(intelligence.PARTIAL_TODAY_INSIGHT_TITLE, titles)
        self.assertIn("event=partial_today_limitation_applied", output)

    async def test_the_model_own_caveat_is_kept_without_duplication(self):
        result, error, output = await self.generate(
            analysis_with(
                metric_ids=["meta_investment", "google_ads_investment"],
                sources=["meta", "google_ads"],
            ),
        )
        self.assertIsNone(error, output)
        analysis = result["analysis"]["analysis"]
        self.assertIn(PARTIAL_TODAY_CAVEAT, analysis["executive"]["attention"])
        self.assertNotIn("event=partial_today_limitation_applied", output)
        self.assertNotIn(
            intelligence.PARTIAL_TODAY_INSIGHT_TITLE,
            [item["title"] for item in analysis["insights"]],
        )

    async def test_a_genuinely_incompatible_comparison_still_returns_the_error(self):
        _, error, output = await self.generate(
            analysis_with(metric_ids=["revenue", "meta_investment"], sources=["commerce", "meta"]),
        )
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(str(error), "AI_TEMPORALLY_INCOMPATIBLE_SOURCES")
        self.assertIn("detail=coverage_mismatch", output)
        self.assertIn("source_ids=commerce,meta", output)

    async def test_the_payload_carries_the_comparable_groups(self):
        captured: Dict[str, Any] = {}

        async def call_provider(**kwargs: Any) -> Dict[str, Any]:
            captured.update(kwargs)
            return analysis_with(
                metric_ids=["meta_investment", "google_ads_investment"],
                sources=["meta", "google_ads"],
            )

        with (
            redirect_stdout(io.StringIO()),
            frozen_today(),
            patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-key"}, clear=False),
            patch.object(
                intelligence, "calculate_intelligence_snapshot",
                AsyncMock(return_value=self.snapshot),
            ),
            patch.object(intelligence, "_call_provider", call_provider),
            patch.object(intelligence, "sb_select", AsyncMock(return_value=[])),
            patch.object(
                intelligence, "sb_insert",
                AsyncMock(side_effect=lambda _table, row: {"id": "an-1", **row}),
            ),
        ):
            await intelligence.generate_analysis(
                client_id=CLIENT, user_id="user-1",
                start=PERIOD_START, end=PERIOD_END, request_id="req-45c06ec",
            )
        policy = captured["payload"]["analysis_policy"]
        self.assertEqual(
            policy["comparable_source_groups"],
            [["ga4", "google_ads", "instagram", "meta"], ["commerce"]],
        )


class ProtectionsPreservedTests(RealSnapshotHarness):
    async def test_an_invented_source_is_still_blocked(self):
        with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_INSIGHT"):
            self.validate(analysis_with(metric_ids=["meta_investment"], sources=["tiktok"]))

    async def test_an_invented_metric_is_still_blocked(self):
        with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_INSIGHT"):
            self.validate(analysis_with(metric_ids=["inventada"], sources=["meta"]))

    async def test_an_ungrounded_action_is_still_blocked(self):
        analysis = analysis_with(metric_ids=["meta_investment"], sources=["meta"])
        analysis["actions"][0]["sources"] = []
        with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_ACTION"):
            self.validate(analysis)

    async def test_causality_is_still_blocked(self):
        analysis = analysis_with(metric_ids=["meta_investment"], sources=["meta"])
        analysis["executive"]["main_change"] = "O investimento causou o avanço."
        with self.assertRaisesRegex(RuntimeError, "AI_UNSUPPORTED_CAUSALITY"):
            self.validate(analysis)

    async def test_the_partial_today_limitation_is_still_required(self):
        analysis = analysis_with(metric_ids=["meta_investment"], sources=["meta"])
        analysis["executive"]["attention"] = "Acompanhar a continuidade."
        with self.assertRaisesRegex(RuntimeError, "AI_MISSING_PARTIAL_TODAY_LIMITATION"):
            self.validate(analysis)

    async def test_the_source_vocabulary_normalization_still_works(self):
        normalized = intelligence._normalize_grounding_ids(
            analysis_with(metric_ids=["revenue"], sources=["fbits"]), self.snapshot,
        )
        self.assertEqual(normalized["insights"][1]["sources"], ["commerce"])

    async def test_numeric_grounding_accepts_the_official_values(self):
        payload = {
            "period": self.snapshot["period"],
            "metrics": intelligence._metrics_with_source_ids(self.snapshot),
            "sources": self.snapshot["sources"],
            "quality": self.snapshot["quality"],
            "crossings": self.snapshot["crossings"],
            "top_campaigns": self.snapshot["top_campaigns"],
            "commerce_context": self.snapshot.get("commerce_context"),
            "real_operation": self.snapshot.get("executive_context"),
        }
        trusted = intelligence._trusted_numbers(payload)
        for allowed in (
            "O faturamento somou R$ 32.452,42.",
            "Foram 70 pedidos no período.",
            "O ticket médio ficou em R$ 463,61.",
        ):
            with self.subTest(allowed=allowed):
                intelligence._assert_no_untrusted_numeric_text(
                    {"executive": {"overall": allowed}}, trusted=trusted,
                )
        for blocked in (
            "O faturamento teve crescimento de 97%.",
            "O faturamento alcançou R$ 999.999.",
            "A loja registrou 1.234 pedidos.",
        ):
            with self.subTest(blocked=blocked):
                with self.assertRaises(RuntimeError):
                    intelligence._assert_no_untrusted_numeric_text(
                        {"executive": {"overall": blocked}}, trusted=trusted,
                    )

    async def test_the_comparable_groups_do_not_widen_the_trusted_numbers(self):
        with frozen_today():
            policy = intelligence._build_analysis_policy(self.snapshot)
        # Os grupos são listas de strings: nenhum número novo entra.
        self.assertEqual(
            intelligence._trusted_numbers({"groups": policy["comparable_source_groups"]}),
            set(),
        )


if __name__ == "__main__":
    unittest.main()
