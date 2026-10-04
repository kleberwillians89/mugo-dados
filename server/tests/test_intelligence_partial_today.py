"""Limitação do dia parcial: garantia determinística, não sorte do modelo.

Reproduz o request real b8086219 (período 2026-10-01 → 2026-10-04, com o dia
corrente dentro do período) e prova que a análise entregue carrega
explicitamente a ressalva de que os dados de hoje estão em formação — sem
depender de o modelo escrever espontaneamente uma frase que satisfaça a regex.
"""

from __future__ import annotations

import datetime as datetime_module
import io
import json
import os
import sys
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from typing import Any, Dict, Iterator, List
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import intelligence

# O caso real de produção.
PERIOD_START = "2026-10-01"
PERIOD_END = "2026-10-04"
TODAY = datetime_module.datetime(2026, 10, 4, 15, 30, tzinfo=ZoneInfo("America/Sao_Paulo"))

REVENUE = 3869.50
ORDERS = 8
AVERAGE_TICKET = 483.69


class FixedDatetime(datetime_module.datetime):
    """`now()` ancorado, para o período incluir hoje em qualquer data real."""

    @classmethod
    def now(cls, tz: Any = None) -> datetime_module.datetime:
        return TODAY.astimezone(tz) if tz else TODAY.replace(tzinfo=None)


@contextmanager
def frozen_today() -> Iterator[None]:
    with patch.object(intelligence, "datetime", FixedDatetime):
        yield


def snapshot(*, period_end: str = PERIOD_END) -> Dict[str, Any]:
    return {
        "period": {"start": PERIOD_START, "end": period_end},
        "metrics": [
            {
                "id": "revenue", "label": "Faturamento", "value": REVENUE,
                "previous_value": 3410.0, "variation_percent": 13.47,
                "status": "confirmed", "format": "currency", "source": "fbits",
            },
            {
                "id": "orders", "label": "Pedidos", "value": ORDERS,
                "previous_value": 7, "variation_percent": 14.29,
                "status": "confirmed", "format": "integer", "source": "fbits",
            },
            {
                "id": "average_ticket", "label": "Ticket médio", "value": AVERAGE_TICKET,
                "previous_value": 487.14, "variation_percent": -0.71,
                "status": "confirmed", "format": "currency", "source": "fbits",
            },
        ],
        "sources": [
            {
                "id": "commerce", "label": "E-commerce", "status": "available",
                "connected": True, "last_sync_at": f"{period_end}T12:00:00Z",
                "data_max_available": period_end,
                "coverage": {"is_partial": True},
            },
        ],
        "quality": {"score": 100, "status": "good"},
        "crossings": [], "top_campaigns": [], "executive_context": {},
    }


def grounded_analysis(*, overall: str | None = None) -> Dict[str, Any]:
    """Resposta válida e aterrada do modelo, SEM a ressalva do dia parcial."""
    return {
        "executive": {
            "overall": overall or "O faturamento do período somou R$ 3.869,50.",
            "main_change": "O faturamento avançou frente à base comparável.",
            "opportunity": "Investigar o mix que sustentou o avanço.",
            "attention": "Acompanhar a continuidade do movimento.",
            "priority_action": "Comparar o mix de produtos.",
        },
        "insights": [
            {
                "category": "positive", "title": "Avanço de faturamento",
                "interpretation": "O faturamento avançou frente à base comparável.",
                "metric_ids": ["revenue"], "sources": ["commerce"],
                "impact": "high", "confidence": "high",
                "action": "Investigar o mix de produtos.",
                "reason": "A mudança é material.",
            },
        ],
        "actions": [
            {
                "priority": "investigate", "recommendation": "Comparar o mix de produtos.",
                "justification": "O faturamento mudou frente à base.",
                "sources": ["commerce"], "impact_expected": "Entender o avanço.",
                "confidence": "high", "metric_id": "revenue",
            },
        ],
    }


class ReproducesTheProductionFailureTests(unittest.TestCase):
    """O caso real: resposta aterrada, mas sem a ressalva do dia parcial."""

    def test_the_period_is_detected_as_including_a_partial_today(self):
        with frozen_today():
            policy = intelligence._build_analysis_policy(snapshot())
        self.assertTrue(policy["includes_partial_today"])
        self.assertEqual(policy["today_date"], PERIOD_END)

    def test_the_raw_model_answer_does_not_satisfy_the_rule(self):
        # É exatamente o que produção devolveu: nada sobre o dia parcial.
        with frozen_today():
            with self.assertRaisesRegex(RuntimeError, "AI_MISSING_PARTIAL_TODAY_LIMITATION"):
                intelligence._validate_analysis_grounding(grounded_analysis(), snapshot())

    def test_the_delivered_analysis_carries_the_limitation(self):
        with frozen_today():
            delivered, applied = intelligence._ensure_partial_today_limitation(
                grounded_analysis(), snapshot(),
            )
            # E continua passando pela validação, que segue sendo o portão.
            intelligence._validate_analysis_grounding(delivered, snapshot())
        self.assertTrue(applied)
        self.assertIn(
            intelligence.PARTIAL_TODAY_INSIGHT_TITLE,
            [item["title"] for item in delivered["insights"]],
        )


class TheInjectedLimitationTests(unittest.TestCase):
    def injected(self) -> Dict[str, Any]:
        with frozen_today():
            delivered, _ = intelligence._ensure_partial_today_limitation(
                grounded_analysis(), snapshot(),
            )
        return next(
            item for item in delivered["insights"]
            if item["title"] == intelligence.PARTIAL_TODAY_INSIGHT_TITLE
        )

    def test_it_uses_the_existing_data_quality_category(self):
        # Sem arquitetura paralela: o schema e o frontend já têm essa categoria.
        self.assertEqual(self.injected()["category"], "data_quality")

    def test_it_says_today_is_partial_and_still_forming(self):
        text = json.dumps(self.injected(), ensure_ascii=False)
        self.assertRegex(text, r"(?i)hoje")
        self.assertRegex(text, r"(?i)(parcia|formação)")

    def test_it_is_grounded_on_a_real_metric_and_source(self):
        item = self.injected()
        self.assertEqual(item["metric_ids"], ["revenue"])
        self.assertEqual(item["sources"], ["commerce"])

    def test_it_cites_a_single_source_to_respect_temporal_compatibility(self):
        self.assertEqual(len(set(self.injected()["sources"])), 1)

    def test_it_invents_no_number(self):
        text = json.dumps(self.injected(), ensure_ascii=False)
        self.assertNotRegex(text, r"\d")

    def test_it_claims_no_causality(self):
        text = json.dumps(self.injected(), ensure_ascii=False)
        for forbidden in ("causou", "provou", "certamente", "sem dúvida", "aconteceu porque"):
            self.assertNotIn(forbidden, text.lower())

    def test_it_does_not_touch_the_model_content(self):
        original = grounded_analysis()
        with frozen_today():
            delivered, _ = intelligence._ensure_partial_today_limitation(original, snapshot())
        self.assertEqual(delivered["executive"], grounded_analysis()["executive"])
        self.assertEqual(delivered["insights"][0], grounded_analysis()["insights"][0])
        self.assertEqual(delivered["actions"], grounded_analysis()["actions"])

    def test_the_original_analysis_is_not_mutated(self):
        original = grounded_analysis()
        with frozen_today():
            intelligence._ensure_partial_today_limitation(original, snapshot())
        self.assertEqual(len(original["insights"]), 1)


class ModelAlreadyWroteTheCaveatTests(unittest.TestCase):
    def analysis_with_caveat(self) -> Dict[str, Any]:
        return grounded_analysis(
            overall=(
                "O faturamento do período somou R$ 3.869,50; os dados de hoje "
                "ainda estão em formação e são parciais."
            ),
        )

    def test_nothing_is_injected_when_the_caveat_is_already_there(self):
        with frozen_today():
            delivered, applied = intelligence._ensure_partial_today_limitation(
                self.analysis_with_caveat(), snapshot(),
            )
        self.assertFalse(applied)
        self.assertEqual(len(delivered["insights"]), 1)

    def test_the_already_caveated_analysis_passes_validation(self):
        with frozen_today():
            intelligence._validate_analysis_grounding(
                self.analysis_with_caveat(), snapshot(),
            )

    def test_the_limitation_is_never_duplicated(self):
        with frozen_today():
            once, _ = intelligence._ensure_partial_today_limitation(
                grounded_analysis(), snapshot(),
            )
            twice, applied = intelligence._ensure_partial_today_limitation(once, snapshot())
        self.assertFalse(applied)
        titles = [item["title"] for item in twice["insights"]]
        self.assertEqual(titles.count(intelligence.PARTIAL_TODAY_INSIGHT_TITLE), 1)


class ClosedPeriodTests(unittest.TestCase):
    """Período que não inclui hoje: comportamento normal, sem aviso."""

    def closed(self) -> Dict[str, Any]:
        return snapshot(period_end="2026-09-30")

    def test_a_closed_period_is_not_flagged_as_partial(self):
        with frozen_today():
            policy = intelligence._build_analysis_policy(self.closed())
        self.assertFalse(policy["includes_partial_today"])
        self.assertIsNone(policy["today_date"])

    def test_no_limitation_is_injected_for_a_closed_period(self):
        with frozen_today():
            delivered, applied = intelligence._ensure_partial_today_limitation(
                grounded_analysis(), self.closed(),
            )
        self.assertFalse(applied)
        self.assertEqual(len(delivered["insights"]), 1)
        self.assertNotIn(
            intelligence.PARTIAL_TODAY_INSIGHT_TITLE,
            [item["title"] for item in delivered["insights"]],
        )

    def test_a_closed_period_does_not_require_the_limitation(self):
        with frozen_today():
            intelligence._validate_analysis_grounding(grounded_analysis(), self.closed())


class TheRuleIsNotMaskedTests(unittest.TestCase):
    """A validação continua sendo o portão: nada é capturado e ignorado."""

    def test_the_rule_still_raises_when_the_limitation_is_absent(self):
        with frozen_today():
            with self.assertRaisesRegex(RuntimeError, "AI_MISSING_PARTIAL_TODAY_LIMITATION"):
                intelligence._validate_analysis_grounding(grounded_analysis(), snapshot())

    def test_the_rule_raises_when_the_limitation_cannot_be_grounded(self):
        # Sem métrica ou fonte não há como entregar a ressalva aterrada: o erro
        # aparece em vez de a limitação ser silenciosamente omitida.
        bare = {**snapshot(), "metrics": [], "sources": []}
        analysis = {**grounded_analysis(), "insights": [], "actions": []}
        with frozen_today():
            delivered, applied = intelligence._ensure_partial_today_limitation(analysis, bare)
            self.assertFalse(applied)
            with self.assertRaisesRegex(RuntimeError, "AI_MISSING_PARTIAL_TODAY_LIMITATION"):
                intelligence._validate_analysis_grounding(delivered, bare)

    def test_generate_analysis_does_not_swallow_the_code(self):
        source = (SERVER_DIR / "services" / "intelligence.py").read_text(encoding="utf-8")
        self.assertNotIn("except RuntimeError:\n        pass", source)
        self.assertNotIn("AI_MISSING_PARTIAL_TODAY_LIMITATION\"", source.split("def _validate_analysis_grounding")[0])


class OtherGroundingRulesStayMandatoryTests(unittest.TestCase):
    def test_unsupported_causality_still_fails(self):
        analysis = grounded_analysis()
        analysis["executive"]["main_change"] = "A campanha causou o avanço."
        with frozen_today():
            delivered, _ = intelligence._ensure_partial_today_limitation(analysis, snapshot())
            with self.assertRaisesRegex(RuntimeError, "AI_UNSUPPORTED_CAUSALITY"):
                intelligence._validate_analysis_grounding(delivered, snapshot())

    def test_ungrounded_insight_still_fails(self):
        analysis = grounded_analysis()
        analysis["insights"][0]["metric_ids"] = ["metrica-inexistente"]
        with frozen_today():
            delivered, _ = intelligence._ensure_partial_today_limitation(analysis, snapshot())
            with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_INSIGHT"):
                intelligence._validate_analysis_grounding(delivered, snapshot())

    def test_ungrounded_action_still_fails(self):
        analysis = grounded_analysis()
        analysis["actions"][0]["metric_id"] = "metrica-inexistente"
        with frozen_today():
            delivered, _ = intelligence._ensure_partial_today_limitation(analysis, snapshot())
            with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_ACTION"):
                intelligence._validate_analysis_grounding(delivered, snapshot())

    def test_temporally_incompatible_sources_still_fail(self):
        incompatible = snapshot()
        incompatible["sources"] = [
            {**incompatible["sources"][0]},
            {
                "id": "meta", "label": "Meta Ads", "status": "available", "connected": True,
                "last_sync_at": f"{PERIOD_END}T12:00:00Z", "data_max_available": "2026-10-02",
                "coverage": {},
            },
        ]
        analysis = grounded_analysis()
        analysis["insights"][0]["sources"] = ["commerce", "meta"]
        with frozen_today():
            policy = intelligence._build_analysis_policy(incompatible)
            self.assertFalse(policy["cross_source_comparison_allowed"])
            delivered, _ = intelligence._ensure_partial_today_limitation(analysis, incompatible)
            with self.assertRaisesRegex(RuntimeError, "AI_TEMPORALLY_INCOMPATIBLE_SOURCES"):
                intelligence._validate_analysis_grounding(delivered, incompatible)


class NumericGroundingStillWorksTests(unittest.TestCase):
    """4ac054e permanece íntegro com os valores reais deste request."""

    def payload(self) -> Dict[str, Any]:
        base = snapshot()
        return {
            "period": base["period"], "metrics": base["metrics"], "sources": base["sources"],
            "quality": base["quality"], "crossings": [], "top_campaigns": [],
        }

    def assert_accepted(self, text: str) -> None:
        intelligence._assert_no_untrusted_numeric_text(
            {"executive": {"overall": text}},
            trusted=intelligence._trusted_numbers(self.payload()),
        )

    def assert_blocked(self, text: str) -> None:
        with self.assertRaises(RuntimeError):
            intelligence._assert_no_untrusted_numeric_text(
                {"executive": {"overall": text}},
                trusted=intelligence._trusted_numbers(self.payload()),
            )

    def test_supported_revenue_is_allowed(self):
        self.assert_accepted("O faturamento somou R$ 3.869,50.")

    def test_supported_orders_are_allowed(self):
        self.assert_accepted("Foram 8 pedidos no período.")

    def test_supported_average_ticket_is_allowed(self):
        self.assert_accepted("O ticket médio ficou em R$ 483,69.")

    def test_invented_numbers_remain_blocked(self):
        for invented in (
            "O faturamento teve crescimento de 97%.",
            "O faturamento alcançou R$ 999.999.",
            "A loja registrou 1.234 pedidos.",
        ):
            with self.subTest(invented=invented):
                self.assert_blocked(invented)

    def test_the_injected_limitation_survives_numeric_grounding(self):
        with frozen_today():
            delivered, _ = intelligence._ensure_partial_today_limitation(
                grounded_analysis(), snapshot(),
            )
        intelligence._assert_no_untrusted_numeric_text(
            delivered, trusted=intelligence._trusted_numbers(self.payload()),
        )


class ObservabilityTests(unittest.IsolatedAsyncioTestCase):
    async def generate(self, *, period_end: str = PERIOD_END) -> tuple[Any, str]:
        output = io.StringIO()
        with (
            redirect_stdout(output),
            frozen_today(),
            patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-key"}, clear=False),
            patch.object(
                intelligence, "calculate_intelligence_snapshot",
                AsyncMock(return_value=snapshot(period_end=period_end)),
            ),
            patch.object(intelligence, "_call_provider", AsyncMock(return_value=grounded_analysis())),
            patch.object(intelligence, "sb_select", AsyncMock(return_value=[])),
            patch.object(
                intelligence, "sb_insert",
                AsyncMock(side_effect=lambda _table, row: {"id": "an-1", **row}),
            ),
        ):
            result = await intelligence.generate_analysis(
                client_id="loja-parcial", user_id="user-1",
                start=PERIOD_START, end=period_end, request_id="req-parcial",
            )
        return result, output.getvalue()

    async def test_the_generation_succeeds_and_persists_the_limitation(self):
        result, _ = await self.generate()
        self.assertEqual(result["status"], "completed")
        titles = [item["title"] for item in result["analysis"]["analysis"]["insights"]]
        self.assertIn(intelligence.PARTIAL_TODAY_INSIGHT_TITLE, titles)

    async def test_the_injection_is_logged_in_a_sanitized_line(self):
        _, output = await self.generate()
        lines = [
            line for line in output.splitlines()
            if "partial_today_limitation_applied" in line
        ]
        self.assertEqual(len(lines), 1, output)
        self.assertTrue(lines[0].startswith(intelligence.LOG_PREFIX))
        self.assertIn("request_id=req-parcial", lines[0])

    async def test_the_model_response_is_never_logged(self):
        _, output = await self.generate()
        self.assertNotIn("Investigar o mix", output)
        self.assertNotIn("priority_action", output)
        self.assertNotIn("3.869,50", output)

    async def test_the_observability_stages_are_preserved(self):
        _, output = await self.generate()
        for stage in ("stage=snapshot", "stage=validation", "stage=persistence"):
            self.assertIn(stage, output)

    async def test_nothing_is_logged_for_a_closed_period(self):
        _, output = await self.generate(period_end="2026-09-30")
        self.assertNotIn("partial_today_limitation_applied", output)


if __name__ == "__main__":
    unittest.main()
