"""AI_UNGROUNDED_INSIGHT: vocabulário de fonte no payload da Inteligência.

`metrics[].source` é rótulo de procedência exibido no painel ("fbits",
"paid media"); os identificadores que a validação aceita vivem em
`sources[].id` ("commerce", "meta"). O modelo recebe os dois e o schema não
restringe `sources` por enum — citar o rótulo que aparece ao lado da métrica
derrubava a análise com AI_UNGROUNDED_INSIGHT.

Reproduz o request e32229140ae748ccacc801db5a0f7515 (Curavino, FBITS, período
2026-10-01 → 2026-10-04, 10 metrics / 5 sources) usando o
`calculate_intelligence_snapshot` real.
"""

from __future__ import annotations

import io
import json
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

PERIOD_START = "2026-10-01"
PERIOD_END = "2026-10-04"

# KPIs oficiais da FBITS no request real.
REVENUE = 3869.50
ORDERS = 8
AVERAGE_TICKET = 483.69


def curavino_summary() -> Dict[str, Any]:
    """O retorno oficial da FBITS com os números do request real."""
    summary = fbits_summary()
    summary["period"] = {"start": PERIOD_START, "end": PERIOD_END}
    summary["summary"] = {
        **summary["summary"],
        "receita_oficial": REVENUE, "pedidos": ORDERS, "ticket_medio": AVERAGE_TICKET,
    }
    summary["comparison"] = {
        "receita_oficial": {"current": REVENUE, "previous": 3410.0, "change_percent": 13.47},
        "pedidos": {"current": ORDERS, "previous": 7, "change_percent": 14.29},
        "ticket_medio": {"current": AVERAGE_TICKET, "previous": 487.14, "change_percent": -0.71},
    }
    summary["status_distribution"] = [{"status": "Pago", "pedidos": ORDERS, "valor": REVENUE}]
    return summary


# A regra do dia parcial exige "hoje" seguido de "formação" ou "parcial". Note
# que "parciais" (plural) NÃO satisfaz a regex: só "formação" ou o singular.
PARTIAL_TODAY_CAVEAT = "Os dados de hoje ainda estão em formação."


def model_analysis(
    *,
    insight_sources: List[str],
    metric_ids: List[str] | None = None,
    caveat: bool = True,
) -> Dict[str, Any]:
    """Análise válida do modelo, variando só o vocabulário de fonte citado.

    `caveat` controla a ressalva do dia parcial, para a regra do dia corrente
    não interferir no que cada teste está medindo.
    """
    attention = "Acompanhar a continuidade."
    return {
        "executive": {
            "overall": "O faturamento do período avançou.",
            "main_change": "Faturamento em alta.",
            "opportunity": "Investigar o mix de produtos.",
            "attention": f"{attention} {PARTIAL_TODAY_CAVEAT}" if caveat else attention,
            "priority_action": "Comparar o mix.",
        },
        "insights": [
            {
                "category": "positive", "title": "Avanço de faturamento",
                "interpretation": "O faturamento avançou frente à base comparável.",
                "metric_ids": ["revenue"] if metric_ids is None else metric_ids,
                "sources": insight_sources,
                "impact": "high", "confidence": "high",
                "action": "Investigar o mix.", "reason": "A mudança é material.",
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
    """Snapshot do caso real, montado pelo código de produção."""

    snapshot: Dict[str, Any]

    def setUp(self) -> None:
        external_research.set_provider(None)
        self.addCleanup(external_research.set_provider, None)

    async def asyncSetUp(self) -> None:
        from services import fbits_reporting

        output = io.StringIO()
        with (
            redirect_stdout(output),
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

    def source_ids(self) -> List[str]:
        return [item["id"] for item in self.snapshot["sources"]]

    def metric_ids(self) -> List[str]:
        return [item["id"] for item in self.snapshot["metrics"]]


class TheContractDefectTests(RealSnapshotHarness):
    """A prova: o payload mostra dois vocabulários incompatíveis."""

    async def test_the_fixture_matches_the_production_shape(self):
        self.assertEqual(len(self.snapshot["metrics"]), 10)
        self.assertEqual(len(self.snapshot["sources"]), 5)
        self.assertEqual(
            self.source_ids(), ["commerce", "meta", "google_ads", "ga4", "instagram"],
        )
        self.assertEqual(self.snapshot["commerce_context"]["provider"], "fbits")

    async def test_most_metrics_expose_a_source_that_is_not_a_source_id(self):
        valid = set(self.source_ids())
        mismatched = {
            metric["source"] for metric in self.snapshot["metrics"]
            if metric["source"] not in valid
        }
        # Esta é a causa raiz, medida no snapshot real.
        self.assertEqual(mismatched, {"fbits", "paid_media", "shopify+paid_media"})
        offenders = [
            metric["id"] for metric in self.snapshot["metrics"]
            if metric["source"] not in valid
        ]
        self.assertEqual(len(offenders), 7)
        self.assertIn("revenue", offenders)

    async def test_the_schema_does_not_restrict_sources_by_enum(self):
        insight = ANALYSIS_ITEM = intelligence.ANALYSIS_SCHEMA["schema"]["properties"]["insights"]["items"]
        self.assertNotIn("enum", insight["properties"]["sources"].get("items", {}))
        self.assertNotIn("enum", insight["properties"]["metric_ids"].get("items", {}))


class TheInjectedInsightIsNotTheCauseTests(RealSnapshotHarness):
    """Elimina o suspeito principal do briefing, com o snapshot real."""

    async def test_the_anchor_is_derived_from_the_snapshot(self):
        with frozen_today():
            anchor = intelligence._partial_today_anchor(self.snapshot)
        self.assertIsNotNone(anchor)
        metric_id, source_id = anchor
        self.assertIn(metric_id, self.metric_ids())
        self.assertIn(source_id, self.source_ids())
        self.assertEqual(anchor, ("revenue", "commerce"))

    async def test_no_conceptual_id_is_hardcoded_in_the_injected_insight(self):
        self.assertNotIn("metric_ids", intelligence._PARTIAL_TODAY_INSIGHT)
        self.assertNotIn("sources", intelligence._PARTIAL_TODAY_INSIGHT)

    async def test_the_injected_insight_passes_grounding(self):
        with frozen_today():
            delivered, applied = intelligence._ensure_partial_today_limitation(
                model_analysis(insight_sources=["commerce"], caveat=False), self.snapshot,
            )
            self.assertTrue(applied)
            intelligence._validate_analysis_grounding(delivered, self.snapshot)
        injected = next(
            item for item in delivered["insights"]
            if item["title"] == intelligence.PARTIAL_TODAY_INSIGHT_TITLE
        )
        self.assertEqual(injected["metric_ids"], ["revenue"])
        self.assertEqual(injected["sources"], ["commerce"])


class ReproducesTheProductionFailureTests(RealSnapshotHarness):
    async def test_citing_the_displayed_provenance_label_is_rejected(self):
        # Exatamente o que o payload convida o modelo a escrever.
        analysis = model_analysis(insight_sources=["fbits"])
        with frozen_today():
            delivered, _ = intelligence._ensure_partial_today_limitation(analysis, self.snapshot)
            with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_INSIGHT"):
                intelligence._validate_analysis_grounding(delivered, self.snapshot)

    async def test_normalization_resolves_it_and_grounding_then_passes(self):
        analysis = model_analysis(insight_sources=["fbits"])
        with frozen_today():
            normalized = intelligence._normalize_grounding_ids(analysis, self.snapshot)
            delivered, _ = intelligence._ensure_partial_today_limitation(normalized, self.snapshot)
            intelligence._validate_analysis_grounding(delivered, self.snapshot)
        self.assertEqual(normalized["insights"][0]["sources"], ["commerce"])

    async def test_the_composite_paid_media_label_is_rejected_raw(self):
        analysis = model_analysis(insight_sources=["paid_media"], metric_ids=["investment"])
        with frozen_today():
            with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_INSIGHT"):
                intelligence._validate_analysis_grounding(
                    intelligence._ensure_partial_today_limitation(analysis, self.snapshot)[0],
                    self.snapshot,
                )


class SourceAliasIndexTests(RealSnapshotHarness):
    async def test_the_provider_resolves_to_the_commerce_source(self):
        index = intelligence._source_alias_index(self.snapshot)
        self.assertEqual(index["fbits"], ("commerce",))

    async def test_the_provider_label_also_resolves(self):
        index = intelligence._source_alias_index(self.snapshot)
        self.assertEqual(index["fbits/wake"], ("commerce",))

    async def test_each_source_id_resolves_to_itself(self):
        index = intelligence._source_alias_index(self.snapshot)
        for source_id in self.source_ids():
            self.assertEqual(index[source_id], (source_id,))

    async def test_the_composite_paid_media_label_resolves_to_both_platforms(self):
        index = intelligence._source_alias_index(self.snapshot)
        self.assertEqual(index["paid_media"], ("meta", "google_ads"))

    async def test_an_invented_source_resolves_to_nothing(self):
        index = intelligence._source_alias_index(self.snapshot)
        self.assertNotIn("tiktok", index)

    async def test_every_metric_resolves_to_real_source_ids(self):
        # O defeito de contrato deixa de existir no payload.
        valid = set(self.source_ids())
        for metric in intelligence._metrics_with_source_ids(self.snapshot):
            with self.subTest(metric=metric["id"]):
                self.assertTrue(metric["source_ids"], metric["id"])
                self.assertTrue(set(metric["source_ids"]) <= valid, metric["source_ids"])

    async def test_the_roas_metric_names_commerce_and_both_platforms(self):
        metrics = {item["id"]: item for item in intelligence._metrics_with_source_ids(self.snapshot)}
        self.assertEqual(metrics["roas"]["source_ids"], ["commerce", "google_ads", "meta"])
        self.assertEqual(metrics["revenue"]["source_ids"], ["commerce"])
        self.assertEqual(metrics["investment"]["source_ids"], ["google_ads", "meta"])

    async def test_the_displayed_provenance_label_is_preserved(self):
        # O painel mostra metric.source; renomear degradaria a interface.
        metrics = {item["id"]: item for item in intelligence._metrics_with_source_ids(self.snapshot)}
        self.assertEqual(metrics["revenue"]["source"], "fbits")

    async def test_the_persisted_snapshot_is_not_annotated(self):
        intelligence._metrics_with_source_ids(self.snapshot)
        for metric in self.snapshot["metrics"]:
            self.assertNotIn("source_ids", metric)


class NormalizationIsFailClosedTests(RealSnapshotHarness):
    async def test_an_invented_source_is_not_invented_into_a_valid_one(self):
        analysis = model_analysis(insight_sources=["tiktok"])
        normalized = intelligence._normalize_grounding_ids(analysis, self.snapshot)
        self.assertEqual(normalized["insights"][0]["sources"], ["tiktok"])
        with frozen_today():
            with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_INSIGHT"):
                intelligence._validate_analysis_grounding(normalized, self.snapshot)

    async def test_an_invented_metric_id_is_still_rejected(self):
        analysis = model_analysis(insight_sources=["commerce"], metric_ids=["faturamento_inventado"])
        normalized = intelligence._normalize_grounding_ids(analysis, self.snapshot)
        with frozen_today():
            with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_INSIGHT"):
                intelligence._validate_analysis_grounding(normalized, self.snapshot)

    async def test_normalization_does_not_mutate_the_model_answer(self):
        analysis = model_analysis(insight_sources=["fbits"])
        intelligence._normalize_grounding_ids(analysis, self.snapshot)
        self.assertEqual(analysis["insights"][0]["sources"], ["fbits"])

    async def test_normalization_keeps_everything_else_untouched(self):
        analysis = model_analysis(insight_sources=["fbits"])
        normalized = intelligence._normalize_grounding_ids(analysis, self.snapshot)
        self.assertEqual(normalized["executive"], analysis["executive"])
        self.assertEqual(
            normalized["insights"][0]["interpretation"],
            analysis["insights"][0]["interpretation"],
        )

    async def test_duplicates_collapse_after_normalization(self):
        analysis = model_analysis(insight_sources=["fbits", "commerce"])
        normalized = intelligence._normalize_grounding_ids(analysis, self.snapshot)
        self.assertEqual(normalized["insights"][0]["sources"], ["commerce"])


class SurgicalObservabilityTests(RealSnapshotHarness):
    def failure_line(self, output: str) -> Dict[str, str]:
        lines = [
            line for line in output.splitlines()
            if "event=grounding_validation_failed" in line
        ]
        self.assertEqual(len(lines), 1, output)
        fields: Dict[str, str] = {}
        for token in lines[0].split(" "):
            if "=" in token:
                key, _, value = token.partition("=")
                fields.setdefault(key, value)
        return fields

    def capture(self, analysis: Dict[str, Any], expected: str) -> Dict[str, str]:
        output = io.StringIO()
        with redirect_stdout(output), frozen_today():
            with self.assertRaisesRegex(RuntimeError, expected):
                intelligence._validate_analysis_grounding(
                    analysis, self.snapshot, request_id="req-e322291",
                )
        return self.failure_line(output.getvalue())

    async def test_an_unknown_source_names_the_reason_and_the_id(self):
        fields = self.capture(
            model_analysis(insight_sources=["fbits"]), "AI_UNGROUNDED_INSIGHT",
        )
        self.assertEqual(fields["kind"], "insight")
        self.assertEqual(fields["index"], "0")
        self.assertEqual(fields["category"], "positive")
        self.assertEqual(fields["reason"], "unknown_source")
        self.assertEqual(fields["metric_ids_count"], "1")
        self.assertEqual(fields["sources_count"], "1")
        self.assertEqual(fields["unknown_ids"], "fbits")
        self.assertEqual(fields["request_id"], "req-e322291")

    async def test_an_absent_source_list_is_distinguished(self):
        fields = self.capture(
            model_analysis(insight_sources=[]), "AI_UNGROUNDED_INSIGHT",
        )
        self.assertEqual(fields["reason"], "no_source")
        self.assertEqual(fields["sources_count"], "0")

    async def test_an_unknown_metric_id_is_distinguished(self):
        fields = self.capture(
            model_analysis(insight_sources=["commerce"], metric_ids=["inventada"]),
            "AI_UNGROUNDED_INSIGHT",
        )
        self.assertEqual(fields["reason"], "unknown_metric_id")
        self.assertEqual(fields["unknown_ids"], "inventada")

    async def test_an_absent_metric_id_list_is_distinguished(self):
        fields = self.capture(
            model_analysis(insight_sources=["commerce"], metric_ids=[]),
            "AI_UNGROUNDED_INSIGHT",
        )
        self.assertEqual(fields["reason"], "no_metric_id")

    async def test_an_ungrounded_action_is_reported_as_an_action(self):
        analysis = model_analysis(insight_sources=["commerce"])
        analysis["actions"][0]["metric_id"] = "inventada"
        fields = self.capture(analysis, "AI_UNGROUNDED_ACTION")
        self.assertEqual(fields["kind"], "action")
        self.assertEqual(fields["category"], "investigate")
        self.assertEqual(fields["reason"], "unknown_metric_id")

    async def test_the_cross_source_rejection_is_reported(self):
        analysis = model_analysis(insight_sources=["commerce", "meta"])
        output = io.StringIO()
        with redirect_stdout(output), frozen_today():
            policy = intelligence._build_analysis_policy(self.snapshot)
            if policy["cross_source_comparison_allowed"]:
                self.skipTest("snapshot permite cruzamento neste cenário")
            with self.assertRaisesRegex(RuntimeError, "AI_TEMPORALLY_INCOMPATIBLE_SOURCES"):
                intelligence._validate_analysis_grounding(
                    analysis, self.snapshot, policy=policy, request_id="req-e322291",
                )
        self.assertEqual(self.failure_line(output.getvalue())["reason"], "cross_source_not_allowed")

    async def test_no_model_prose_is_ever_logged(self):
        output = io.StringIO()
        with redirect_stdout(output), frozen_today():
            with self.assertRaises(RuntimeError):
                intelligence._validate_analysis_grounding(
                    model_analysis(insight_sources=["fbits"]),
                    self.snapshot, request_id="req-e322291",
                )
        logged = output.getvalue()
        for prose in (
            "Avanço de faturamento",
            "O faturamento avançou frente à base comparável.",
            "Investigar o mix.",
            "A mudança é material.",
            "Comparar o mix.",
        ):
            self.assertNotIn(prose, logged)

    async def test_nothing_is_logged_when_grounding_passes(self):
        output = io.StringIO()
        with redirect_stdout(output), frozen_today():
            delivered, _ = intelligence._ensure_partial_today_limitation(
                model_analysis(insight_sources=["commerce"]), self.snapshot,
            )
            intelligence._validate_analysis_grounding(delivered, self.snapshot)
        self.assertNotIn("grounding_validation_failed", output.getvalue())


class EndToEndTests(RealSnapshotHarness):
    async def generate(
        self, *, insight_sources: List[str], caveat: bool = True,
    ) -> tuple[Any, BaseException | None, str]:
        import os

        output = io.StringIO()
        with (
            redirect_stdout(output),
            frozen_today(),
            patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-key"}, clear=False),
            patch.object(
                intelligence, "calculate_intelligence_snapshot",
                AsyncMock(return_value=self.snapshot),
            ),
            patch.object(
                intelligence, "_call_provider",
                AsyncMock(
                    return_value=model_analysis(
                        insight_sources=insight_sources, caveat=caveat,
                    ),
                ),
            ),
            patch.object(intelligence, "sb_select", AsyncMock(return_value=[])),
            patch.object(
                intelligence, "sb_insert",
                AsyncMock(side_effect=lambda _table, row: {"id": "an-1", **row}),
            ),
        ):
            try:
                result, error = await intelligence.generate_analysis(
                    client_id=CLIENT, user_id="user-1",
                    start=PERIOD_START, end=PERIOD_END, request_id="req-e322291",
                ), None
            except BaseException as exc:  # noqa: BLE001 - o erro é o objeto do teste
                result, error = None, exc
        return result, error, output.getvalue()

    async def test_the_production_case_now_completes(self):
        result, error, output = await self.generate(insight_sources=["fbits"])
        self.assertIsNone(error, output)
        self.assertEqual(result["status"], "completed")

    async def test_the_delivered_analysis_carries_canonical_source_ids(self):
        result, _, _ = await self.generate(insight_sources=["fbits"])
        insights = result["analysis"]["analysis"]["insights"]
        self.assertEqual(insights[0]["sources"], ["commerce"])

    async def test_the_delivered_analysis_still_carries_the_partial_today_limitation(self):
        result, _, output = await self.generate(insight_sources=["fbits"], caveat=False)
        titles = [item["title"] for item in result["analysis"]["analysis"]["insights"]]
        self.assertIn(intelligence.PARTIAL_TODAY_INSIGHT_TITLE, titles)
        self.assertIn("event=partial_today_limitation_applied", output)

    async def test_the_normalization_is_logged(self):
        _, _, output = await self.generate(insight_sources=["fbits"])
        lines = [line for line in output.splitlines() if "event=source_alias_normalized" in line]
        self.assertEqual(len(lines), 1, output)
        self.assertIn("request_id=req-e322291", lines[0])
        self.assertIn("rewritten=1", lines[0])

    async def test_nothing_is_normalized_when_the_model_uses_real_ids(self):
        _, _, output = await self.generate(insight_sources=["commerce"])
        self.assertNotIn("event=source_alias_normalized", output)

    async def test_the_observability_stages_are_preserved(self):
        _, _, output = await self.generate(insight_sources=["fbits"])
        for stage in ("stage=snapshot", "stage=validation", "stage=persistence"):
            self.assertIn(stage, output)

    async def test_an_invented_source_still_fails_end_to_end(self):
        _, error, output = await self.generate(insight_sources=["tiktok"])
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(str(error), "AI_UNGROUNDED_INSIGHT")
        self.assertIn("reason=unknown_source", output)
        self.assertIn("unknown_ids=tiktok", output)


class ProtectionsPreservedTests(RealSnapshotHarness):
    async def test_unsupported_causality_still_fails(self):
        analysis = model_analysis(insight_sources=["commerce"])
        analysis["executive"]["main_change"] = "A campanha causou o avanço."
        with frozen_today():
            with self.assertRaisesRegex(RuntimeError, "AI_UNSUPPORTED_CAUSALITY"):
                intelligence._validate_analysis_grounding(analysis, self.snapshot)

    async def test_missing_partial_today_limitation_still_fails(self):
        analysis = model_analysis(insight_sources=["commerce"], caveat=False)
        with frozen_today():
            with self.assertRaisesRegex(RuntimeError, "AI_MISSING_PARTIAL_TODAY_LIMITATION"):
                intelligence._validate_analysis_grounding(analysis, self.snapshot)

    async def test_ungrounded_action_still_fails(self):
        analysis = model_analysis(insight_sources=["commerce"])
        analysis["actions"][0]["sources"] = []
        with frozen_today():
            with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_ACTION"):
                intelligence._validate_analysis_grounding(analysis, self.snapshot)

    async def test_numeric_grounding_accepts_the_official_fbits_values(self):
        payload = {
            "period": self.snapshot["period"],
            "metrics": intelligence._metrics_with_source_ids(self.snapshot),
            "sources": self.snapshot["sources"],
            "quality": self.snapshot["quality"],
            "crossings": self.snapshot["crossings"],
            "top_campaigns": self.snapshot["top_campaigns"],
            "real_operation": self.snapshot.get("executive_context"),
            "commerce_context": self.snapshot.get("commerce_context"),
        }
        trusted = intelligence._trusted_numbers(payload)
        for allowed in (
            "O faturamento somou R$ 3.869,50.",
            "Foram 8 pedidos no período.",
            "O ticket médio ficou em R$ 483,69.",
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

    async def test_the_annotated_payload_does_not_widen_the_trusted_numbers(self):
        # source_ids são strings: não podem virar números verificáveis.
        annotated = intelligence._trusted_numbers(
            {"metrics": intelligence._metrics_with_source_ids(self.snapshot)}
        )
        plain = intelligence._trusted_numbers({"metrics": self.snapshot["metrics"]})
        self.assertEqual(annotated, plain)


class ClosedPeriodTests(RealSnapshotHarness):
    async def test_a_closed_period_gets_no_artificial_limitation(self):
        closed = {**self.snapshot, "period": {"start": "2026-09-01", "end": "2026-09-30"}}
        analysis = model_analysis(insight_sources=["commerce"])
        with frozen_today():
            policy = intelligence._build_analysis_policy(closed)
            self.assertFalse(policy["includes_partial_today"])
            delivered, applied = intelligence._ensure_partial_today_limitation(
                analysis, closed, policy=policy,
            )
            intelligence._validate_analysis_grounding(delivered, closed, policy=policy)
        self.assertFalse(applied)
        self.assertNotIn(
            intelligence.PARTIAL_TODAY_INSIGHT_TITLE,
            [item["title"] for item in delivered["insights"]],
        )


if __name__ == "__main__":
    unittest.main()
