"""Grounding numérico dos textos da IA.

O número que o backend calculou e enviou ao modelo é verificável: citá-lo no
texto é legítimo. Qualquer outro número é invenção e continua barrado. Este
arquivo prova as duas metades, incluindo as formatações equivalentes do mesmo
valor (``3506.79``, ``3.506,79``, ``R$ 3.506,79``).
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
import unittest
from datetime import datetime, timezone
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import httpx

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import intelligence

REVENUE = 3506.79
ORDERS = 73
AVERAGE_TICKET = 48.04
REVENUE_VARIATION = 11.11
INVESTMENT = 1200.5

# Espelha o payload real enviado ao modelo em generate_analysis: period,
# metrics, sources, quality, crossings, top_campaigns e analysis_policy.
PAYLOAD: Dict[str, Any] = {
    "period": {"start": "2026-09-01", "end": "2026-09-30"},
    "metrics": [
        {
            "id": "revenue", "label": "Faturamento", "value": REVENUE,
            "previous_value": 3156.40, "variation_percent": REVENUE_VARIATION,
            "status": "confirmed", "format": "currency", "source": "fbits",
        },
        {
            "id": "orders", "label": "Pedidos", "value": ORDERS,
            "previous_value": 66, "variation_percent": 10.61,
            "status": "confirmed", "format": "integer", "source": "fbits",
        },
        {
            "id": "average_ticket", "label": "Ticket médio", "value": AVERAGE_TICKET,
            "previous_value": 47.82, "variation_percent": 0.46,
            "status": "confirmed", "format": "currency", "source": "fbits",
        },
        {
            "id": "investment", "label": "Investimento", "value": INVESTMENT,
            "previous_value": 1100.0, "variation_percent": 9.14,
            "status": "confirmed", "format": "currency", "source": "meta",
        },
    ],
    "sources": [
        {"id": "commerce", "status": "available", "connected": True,
         "last_sync_at": "2026-09-30T12:00:00Z"},
        {"id": "meta", "status": "available", "connected": True,
         "last_sync_at": "2026-09-30T12:00:00Z"},
    ],
    "quality": {"score": 100, "status": "good"},
    "crossings": [],
    "top_campaigns": [],
}


def _fingerprint_filter(filters: Dict[str, Any]) -> Any:
    """Impressão digital pedida na consulta, quando houver."""
    raw = str(filters.get("context_fingerprint") or "")
    return raw.removeprefix("eq.") if raw else None


def trusted() -> Any:
    return intelligence._trusted_numbers(PAYLOAD)


def executive(overall: str) -> Dict[str, Any]:
    return {
        "executive": {
            "overall": overall,
            "main_change": "Faturamento em alta.",
            "opportunity": "Investigar o mix de produtos.",
            "attention": "Acompanhar a continuidade.",
            "priority_action": "Comparar o mix.",
        },
        "insights": [],
        "actions": [],
    }


class ReproducesTheFalsePositiveTests(unittest.TestCase):
    """O cenário exato do request b9644a5a em produção."""

    def assert_accepted(self, overall: str) -> None:
        try:
            intelligence._assert_no_untrusted_numeric_text(
                executive(overall), trusted=trusted(),
            )
        except RuntimeError as exc:
            self.fail(f"número verificável rejeitado em {overall!r}: {exc}")

    def test_revenue_from_the_snapshot_is_accepted_in_executive_overall(self):
        self.assert_accepted("O faturamento do período alcançou R$ 3.506,79.")

    def test_orders_from_the_snapshot_are_accepted(self):
        self.assert_accepted("A loja registrou 73 pedidos no período.")

    def test_average_ticket_from_the_snapshot_is_accepted(self):
        self.assert_accepted("O ticket médio ficou em R$ 48,04.")

    def test_percentage_variation_from_the_snapshot_is_accepted(self):
        self.assert_accepted("O faturamento avançou 11,11% frente à base comparável.")

    def test_rounded_percentage_variation_is_accepted(self):
        # O modelo arredonda 11.11 para 11%: continua sendo o mesmo número.
        self.assert_accepted("O faturamento avançou 11% frente à base comparável.")

    def test_rounded_currency_is_accepted(self):
        self.assert_accepted("O faturamento alcançou R$ 3.507.")

    def test_several_verifiable_numbers_in_one_sentence_are_accepted(self):
        self.assert_accepted(
            "Com 73 pedidos e ticket médio de R$ 48,04, o faturamento somou R$ 3.506,79."
        )

    def test_the_analysed_period_can_be_named(self):
        self.assert_accepted("Nos 30 dias de 2026-09-01 a 2026-09-30 o faturamento avançou.")


class EquivalentFormattingTests(unittest.TestCase):
    def test_the_same_value_is_accepted_in_every_legitimate_formatting(self):
        for written in ("3506.79", "3506,79", "3.506,79", "R$ 3.506,79", "R$3.506,79", "3,506.79"):
            with self.subTest(written=written):
                try:
                    intelligence._assert_no_untrusted_numeric_text(
                        executive(f"O faturamento somou {written}."), trusted=trusted(),
                    )
                except RuntimeError as exc:
                    self.fail(f"formatação legítima rejeitada: {written!r} ({exc})")

    def test_integer_metric_accepts_thousand_separator_formatting(self):
        payload = {**PAYLOAD, "metrics": [{"id": "sessions", "value": 12345.0, "format": "integer"}]}
        for written in ("12345", "12.345", "12,345"):
            with self.subTest(written=written):
                intelligence._assert_no_untrusted_numeric_text(
                    executive(f"Foram {written} sessões."),
                    trusted=intelligence._trusted_numbers(payload),
                )


class InventedNumbersStayBlockedTests(unittest.TestCase):
    def assert_blocked(self, overall: str) -> str:
        with self.assertRaises(RuntimeError) as raised:
            intelligence._assert_no_untrusted_numeric_text(
                executive(overall), trusted=trusted(),
            )
        message = str(raised.exception)
        self.assertTrue(message.startswith("AI_UNTRUSTED_NUMERIC_TEXT:"), message)
        return message

    def test_invented_growth_percentage_is_blocked(self):
        self.assert_blocked("O faturamento teve crescimento de 97%.")

    def test_invented_currency_is_blocked(self):
        self.assert_blocked("O faturamento alcançou R$ 999.999.")

    def test_invented_order_count_is_blocked(self):
        self.assert_blocked("A loja registrou 1.234 pedidos.")

    def test_invented_benchmark_is_blocked(self):
        self.assert_blocked("O setor cresce 25% ao ano.")

    def test_the_path_of_the_offending_field_is_reported(self):
        message = self.assert_blocked("O faturamento teve crescimento de 97%.")
        self.assertEqual(message, "AI_UNTRUSTED_NUMERIC_TEXT:response.executive.overall")

    def test_invented_number_inside_an_insight_is_blocked(self):
        analysis = {
            **executive("O faturamento avançou."),
            "insights": [
                {
                    "category": "positive", "title": "Avanço",
                    "interpretation": "O faturamento subiu 88% no período.",
                    "metric_ids": ["revenue"], "sources": ["commerce"],
                    "impact": "high", "confidence": "high",
                    "action": "Investigar.", "reason": "Material.",
                },
            ],
            "actions": [],
        }
        with self.assertRaises(RuntimeError) as raised:
            intelligence._assert_no_untrusted_numeric_text(analysis, trusted=trusted())
        self.assertEqual(
            str(raised.exception),
            "AI_UNTRUSTED_NUMERIC_TEXT:response.insights[0].interpretation",
        )

    def test_without_a_trusted_set_every_number_is_still_rejected(self):
        # Comportamento anterior preservado para quem chama sem contexto.
        with self.assertRaises(RuntimeError):
            intelligence._assert_no_untrusted_numeric_text(
                {"direct_answer": "A receita aumentou 42 por cento."}
            )

    def test_metric_identifier_fields_remain_exempt(self):
        intelligence._assert_no_untrusted_numeric_text(
            {"direct_answer": "A receita melhorou.", "metric_ids": ["revenue"]},
        )


class TrustedNumberSetTests(unittest.TestCase):
    def test_the_trusted_set_comes_from_the_payload_sent_to_the_model(self):
        numbers = trusted()
        for value in (REVENUE, float(ORDERS), AVERAGE_TICKET, REVENUE_VARIATION, INVESTMENT):
            self.assertIn(value, numbers)

    def test_a_value_absent_from_the_payload_is_not_trusted(self):
        self.assertNotIn(999999.0, trusted())
        self.assertNotIn(97.0, trusted())

    def test_identifiers_glued_to_letters_are_not_read_as_numbers(self):
        # "GA4" e "Meta Ads" não podem ser lidos como o número 4.
        intelligence._assert_no_untrusted_numeric_text(
            executive("GA4 e Meta Ads seguem conectados."), trusted=set(),
        )


class PermissivenessEnvelopeTests(unittest.TestCase):
    """Mede o quanto o conjunto verificado abre, em vez de supor que é pouco."""

    def payload_with_policy(self) -> Dict[str, Any]:
        snapshot = {
            "period": PAYLOAD["period"],
            "metrics": [
                *PAYLOAD["metrics"],
                {"id": "roas", "value": 2.92, "previous_value": 2.87,
                 "variation_percent": 1.74, "status": "confirmed", "format": "ratio"},
                {"id": "sessions", "value": 14820, "previous_value": 13990,
                 "variation_percent": 5.93, "status": "confirmed", "format": "integer"},
            ],
            "sources": PAYLOAD["sources"],
            "quality": PAYLOAD["quality"],
            "crossings": [], "top_campaigns": [], "executive_context": {},
        }
        return {
            **{key: snapshot[key] for key in ("period", "metrics", "sources", "quality")},
            "crossings": [], "top_campaigns": [],
            "analysis_policy": intelligence._build_analysis_policy(snapshot),
        }

    def test_the_trusted_set_stays_small_with_a_full_payload(self):
        numbers = intelligence._trusted_numbers(self.payload_with_policy())
        # Um conjunto que crescesse para centenas de valores tornaria o
        # arredondamento para inteiro permissivo demais.
        self.assertLess(len(numbers), 60, len(numbers))
        small_integers = {int(round(item)) for item in numbers if 0 <= round(item) <= 200}
        self.assertLess(len(small_integers), 25, sorted(small_integers))

    def test_realistic_invented_numbers_are_blocked_with_a_full_payload(self):
        numbers = intelligence._trusted_numbers(self.payload_with_policy())
        for invented in (
            "O faturamento teve crescimento de 97%.",
            "O faturamento alcançou R$ 999.999.",
            "A loja registrou 1.234 pedidos.",
            "O setor cresce 25% ao ano.",
            "A meta era R$ 5.000,00.",
            "O ROAS chegou a 7,4.",
            "Foram 88 pedidos.",
            "A conversão foi de 3,2%.",
        ):
            with self.subTest(invented=invented):
                with self.assertRaises(RuntimeError):
                    intelligence._assert_no_untrusted_numeric_text(
                        executive(invented), trusted=numbers,
                    )

    def test_realistic_verifiable_numbers_pass_with_a_full_payload(self):
        numbers = intelligence._trusted_numbers(self.payload_with_policy())
        for legitimate in (
            "O faturamento somou R$ 3.506,79 em 73 pedidos.",
            "O faturamento avançou 11% com ticket médio de R$ 48,04.",
            "Foram 14.820 sessões no período.",
        ):
            with self.subTest(legitimate=legitimate):
                intelligence._assert_no_untrusted_numeric_text(
                    executive(legitimate), trusted=numbers,
                )


class OtherGroundingRulesUntouchedTests(unittest.TestCase):
    """As demais regras de grounding não podem ter sido relaxadas."""

    def snapshot(self) -> Dict[str, Any]:
        return {
            "period": PAYLOAD["period"],
            "metrics": PAYLOAD["metrics"],
            "sources": PAYLOAD["sources"],
        }

    def analysis(self, **overrides: Any) -> Dict[str, Any]:
        base = {
            "executive": {
                "overall": "O faturamento avançou.", "main_change": "Alta.",
                "opportunity": "Investigar.", "attention": "Acompanhar.",
                "priority_action": "Comparar.",
            },
            "insights": [
                {
                    "category": "positive", "title": "Avanço",
                    "interpretation": "O faturamento avançou frente à base.",
                    "metric_ids": ["revenue"], "sources": ["commerce"],
                    "impact": "high", "confidence": "high",
                    "action": "Investigar.", "reason": "Material.",
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
        base.update(overrides)
        return base

    def test_unsupported_causality_still_fails(self):
        analysis = self.analysis()
        analysis["executive"]["overall"] = "A campanha causou o avanço do faturamento."
        with self.assertRaisesRegex(RuntimeError, "AI_UNSUPPORTED_CAUSALITY"):
            intelligence._validate_analysis_grounding(analysis, self.snapshot())

    def test_ungrounded_insight_still_fails(self):
        analysis = self.analysis()
        analysis["insights"][0]["metric_ids"] = ["metrica-inexistente"]
        with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_INSIGHT"):
            intelligence._validate_analysis_grounding(analysis, self.snapshot())

    def test_ungrounded_action_still_fails(self):
        analysis = self.analysis()
        analysis["actions"][0]["metric_id"] = "metrica-inexistente"
        with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_ACTION"):
            intelligence._validate_analysis_grounding(analysis, self.snapshot())


class CallProviderWiringTests(unittest.IsolatedAsyncioTestCase):
    """A rejeição continua vindo de _call_provider, com o log preservado."""

    async def _call(self, overall: str) -> tuple[Any, BaseException | None, str]:
        body = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": __import__("json").dumps(executive(overall))}],
                },
            ],
        }
        response = httpx.Response(
            200, json=body, request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
        )

        async def post(*_args: Any, **_kwargs: Any) -> httpx.Response:
            return response

        output = io.StringIO()
        with (
            redirect_stdout(output),
            patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-key-para-o-teste"}, clear=False),
            patch.object(httpx.AsyncClient, "post", post),
        ):
            try:
                result, error = await intelligence._call_provider(
                    payload=PAYLOAD, schema=intelligence.ANALYSIS_SCHEMA,
                    instructions="x", request_id="req-grounding",
                ), None
            except BaseException as exc:  # noqa: BLE001 - o erro é o objeto do teste
                result, error = None, exc
        return result, error, output.getvalue()

    async def test_verifiable_number_passes_through_call_provider(self):
        result, error, _ = await self._call("O faturamento alcançou R$ 3.506,79.")
        self.assertIsNone(error)
        self.assertEqual(result["executive"]["overall"], "O faturamento alcançou R$ 3.506,79.")

    async def test_invented_number_is_rejected_by_call_provider(self):
        _, error, _ = await self._call("O faturamento cresceu 97%.")
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(
            str(error), "AI_UNTRUSTED_NUMERIC_TEXT:response.executive.overall",
        )

    async def test_the_rejection_keeps_the_observability_fields(self):
        _, error, output = await self._call("O faturamento cresceu 97%.")
        self.assertIsNotNone(error)
        lines = [
            line for line in output.splitlines()
            if line.startswith(intelligence.LOG_PREFIX)
        ]
        self.assertTrue(lines, output)
        model_response = [line for line in lines if "stage=model_response" in line]
        self.assertTrue(model_response, output)
        # O upstream foi 200: o stage_completed do model_response continua saindo.
        self.assertIn("upstream_status=200", model_response[0])
        self.assertIn("request_id=req-grounding", model_response[0])
        self.assertIn("elapsed_ms=", model_response[0])
        self.assertIn("[intelligence][numeric_validation_failed] request_id=req-grounding", output)

    async def test_the_model_response_is_never_logged(self):
        _, _, output = await self._call("O faturamento cresceu 97%.")
        self.assertNotIn("O faturamento cresceu", output)
        self.assertNotIn("priority_action", output)


if __name__ == "__main__":
    unittest.main()


class GenerationCostGuardsTests(unittest.IsolatedAsyncioTestCase):
    """Gerar análise chama a OpenAI: a contenção é no servidor.

    Qualquer membro pode pedir desde esta release, então papel deixou de ser
    a proteção. Sobram três: reuso por fingerprint, lock de concorrência no
    worker e cooldown por tenant/período lido do banco.
    """

    CLIENT = "curavino-test"
    PERIOD = {"start": "2026-10-01", "end": "2026-10-04"}

    def setUp(self) -> None:
        self.rows: list[Dict[str, Any]] = []
        self.provider_calls = 0
        intelligence._GENERATION_LOCKS.clear()

    def snapshot(self) -> Dict[str, Any]:
        return {
            "period": dict(self.PERIOD),
            "metrics": PAYLOAD["metrics"],
            "sources": PAYLOAD["sources"],
            "quality": PAYLOAD["quality"],
            "crossings": [], "top_campaigns": [], "executive_context": {},
        }

    def analysis(self) -> Dict[str, Any]:
        return {
            "executive": {
                "overall": "Leitura.", "main_change": "m", "opportunity": "o",
                "attention": "a", "priority_action": "p",
            },
            "insights": [], "actions": [],
        }

    async def generate(self, **overrides: Any) -> tuple[Any, BaseException | None]:
        async def select(table: str, **kwargs: Any) -> list[Dict[str, Any]]:
            if table != "ai_analyses":
                return []
            filters = kwargs.get("filters") or {}
            wanted = _fingerprint_filter(filters)
            rows = [row for row in self.rows if row.get("status") == "completed"]
            if wanted is not None:
                rows = [row for row in rows if row.get("context_fingerprint") == wanted]
            return rows

        async def insert(_table: str, row: Dict[str, Any], **_kwargs: Any) -> Dict[str, Any]:
            saved = {"id": f"an-{len(self.rows) + 1}", **row}
            self.rows.append(saved)
            return saved

        async def provider(**_kwargs: Any) -> Dict[str, Any]:
            self.provider_calls += 1
            return self.analysis()

        with (
            redirect_stdout(io.StringIO()),
            patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False),
            patch.object(
                intelligence, "calculate_intelligence_snapshot",
                AsyncMock(return_value=self.snapshot()),
            ),
            patch.object(intelligence, "sb_select", AsyncMock(side_effect=select)),
            patch.object(intelligence, "sb_insert", AsyncMock(side_effect=insert)),
            patch.object(intelligence, "_call_provider", provider),
            patch.object(intelligence, "_validate_analysis_grounding", lambda *_a, **_k: None),
            patch.object(intelligence, "_sanitize_analysis", lambda value, _s: value),
            patch.object(intelligence, "_ensure_partial_today_limitation", lambda a, _s, **_k: (a, False)),
        ):
            try:
                return await intelligence.generate_analysis(
                    client_id=self.CLIENT, user_id="nasser",
                    start=self.PERIOD["start"], end=self.PERIOD["end"], **overrides,
                ), None
            except BaseException as exc:  # noqa: BLE001
                return None, exc

    async def test_the_first_generation_calls_the_provider(self):
        result, error = await self.generate()
        self.assertIsNone(error)
        self.assertEqual(self.provider_calls, 1)
        self.assertEqual(result["status"], "completed")

    async def test_the_same_context_is_reused_without_calling_the_provider(self):
        await self.generate()
        with patch.object(intelligence, "INTELLIGENCE_GENERATION_COOLDOWN_SECONDS", 0):
            result, error = await self.generate()
        self.assertIsNone(error)
        # Fingerprint igual: devolve a análise existente, sem gastar token.
        self.assertEqual(self.provider_calls, 1)
        self.assertTrue(result["reused"])

    async def test_concurrent_requests_collapse_into_one_provider_call(self):
        results = await asyncio.gather(
            self.generate(), self.generate(), self.generate(),
        )
        for _result, error in results:
            self.assertIsNone(error)
        # O lock serializa; quem espera encontra a análise pronta.
        self.assertEqual(self.provider_calls, 1)

    async def test_a_changed_context_inside_the_cooldown_is_refused(self):
        await self.generate()
        # Contexto novo: o reuso não se aplica e o cooldown entra em ação.
        self.rows[0]["context_fingerprint"] = "impressao-antiga"
        _result, error = await self.generate()
        self.assertIsInstance(error, RuntimeError)
        self.assertTrue(str(error).startswith("AI_GENERATION_COOLDOWN:"), str(error))
        self.assertEqual(self.provider_calls, 1)

    async def test_the_cooldown_reports_the_remaining_seconds(self):
        await self.generate()
        self.rows[0]["context_fingerprint"] = "impressao-antiga"
        _result, error = await self.generate()
        remaining = int(str(error).split(":")[1])
        self.assertGreater(remaining, 0)
        self.assertLessEqual(remaining, int(intelligence.INTELLIGENCE_GENERATION_COOLDOWN_SECONDS) + 1)

    async def test_an_expired_cooldown_allows_a_new_generation(self):
        await self.generate()
        self.rows[0]["context_fingerprint"] = "impressao-antiga"
        with patch.object(intelligence, "INTELLIGENCE_GENERATION_COOLDOWN_SECONDS", 0):
            _result, error = await self.generate()
        self.assertIsNone(error)
        self.assertEqual(self.provider_calls, 2)

    async def test_a_failed_attempt_does_not_block_the_next_one(self):
        # Só análise concluída conta para o cooldown: quem está tentando
        # resolver uma falha não fica travado.
        self.rows.append({
            "id": "an-falha", "client_id": self.CLIENT, "status": "failed",
            "period_start": self.PERIOD["start"], "period_end": self.PERIOD["end"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        remaining = await intelligence._generation_cooldown_remaining(
            client_id=self.CLIENT, period=self.PERIOD,
        )
        self.assertEqual(remaining, 0.0)

    async def test_the_cooldown_is_scoped_to_the_tenant(self):
        await self.generate()
        self.rows[0]["client_id"] = "roove-test"
        remaining = await intelligence._generation_cooldown_remaining(
            client_id=self.CLIENT, period=self.PERIOD,
        )
        self.assertEqual(remaining, 0.0)

    async def test_an_unreadable_cooldown_lookup_never_blocks(self):
        with (
            redirect_stdout(io.StringIO()),
            patch.object(intelligence, "sb_select", AsyncMock(side_effect=RuntimeError("sem banco"))),
        ):
            remaining = await intelligence._generation_cooldown_remaining(
                client_id=self.CLIENT, period=self.PERIOD,
            )
        self.assertEqual(remaining, 0.0)


class NumericFailureDiagnosticTests(unittest.TestCase):
    def rejection(self, text, path="response.executive.main_change"):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(RuntimeError) as error:
            intelligence._assert_no_untrusted_numeric_text(
                text, path, trusted={4429.1, 9.0, 492.12}, request_id="req-numeric",
            )
        self.assertEqual(str(error.exception), f"AI_UNTRUSTED_NUMERIC_TEXT:{path}")
        return output.getvalue()

    def test_rejected_currency_logs_only_numeric_diagnostic(self):
        output = self.rejection("Texto reservado da análise: receita R$ 8.900.")
        self.assertEqual(output, "[intelligence][numeric_validation_failed] request_id=req-numeric "
                         "field=response.executive.main_change numeric_token=8.900 "
                         "normalized_value=8900.0|8.9 reason=unsupported_numeric_value "
                         "trusted_numeric_count=3\n")
        self.assertNotIn("Texto reservado", output)
        self.assertNotIn("receita", output)

    def test_contact_numbers_are_redacted_including_split_phones_and_cpf(self):
        for text in ("Telefone +55 (11) 98765-4321", "CPF 123.456.789-00", "Contato ana.8900@example.com", "Telefone 987654321", "senha=8900", "access_token=8900"):
            with self.subTest(text=text):
                output = self.rejection(text)
                self.assertIn("numeric_token=[redacted]", output)
                self.assertIn("normalized_value=[redacted]", output)
                self.assertNotIn(text, output)
                self.assertNotIn("98765", output)
                self.assertNotIn("8900", output)

    def test_unexpected_json_key_is_not_logged(self):
        output = self.rejection("8900", "response.ana@example.com")
        self.assertIn("field=response.unknown_field", output)
        self.assertNotIn("ana@example.com", output)

    def test_recursive_validation_keeps_request_id_and_field(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(RuntimeError):
            intelligence._assert_no_untrusted_numeric_text(
                {"executive": {"main_change": "R$ 8.900"}},
                trusted={4429.1}, request_id="req-recursive",
            )
        self.assertIn("request_id=req-recursive", output.getvalue())
        self.assertIn("field=response.executive.main_change", output.getvalue())
