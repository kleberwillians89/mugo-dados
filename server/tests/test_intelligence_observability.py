"""Observabilidade do POST /api/intelligence/analyses.

Prova que a sequência completa da requisição sai em stdout com o prefixo
`[intelligence]` — o mecanismo que já aparece no Render — e que nenhuma
credencial entra na linha. O log é diagnóstico: não pode alterar o resultado
da análise nem relaxar nenhuma regra de grounding.
"""

from __future__ import annotations

import io
import os
import re
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import AsyncMock, patch

import httpx

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import api_support
from routes import intelligence as routes
from services import intelligence

CLIENT = "loja-observada"
REQUEST_ID = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
API_KEY = "sk-proj-chave-que-nunca-pode-sair-no-log-00000000"
SERVICE_ROLE = "eyJhbGciOiJIUzI1NiJ9.service-role-que-nao-pode-vazar.assinatura"

SNAPSHOT: Dict[str, Any] = {
    "period": {"start": "2026-09-01", "end": "2026-09-30"},
    "sources": [
        {
            "id": "commerce", "status": "available", "connected": True,
            "last_sync_at": "2026-09-30T12:00:00Z",
        },
    ],
    "quality": {"score": 100, "status": "good"},
    "metrics": [
        {
            "id": "revenue", "value": 100.0, "previous_value": 90.0,
            "variation_percent": 11.11, "status": "confirmed", "format": "currency",
        },
    ],
    "crossings": [],
    "top_campaigns": [],
    "executive_context": {},
}

ANALYSIS: Dict[str, Any] = {
    "executive": {
        "overall": "O faturamento avançou.",
        "main_change": "Faturamento em alta.",
        "opportunity": "Investigar os itens que sustentaram o avanço.",
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
            "reason": "A mudança é material e comparável.",
        },
    ],
    "actions": [
        {
            "priority": "investigate", "recommendation": "Comparar o mix de produtos.",
            "justification": "O faturamento mudou frente à base.",
            "sources": ["commerce"], "impact_expected": "Entender o componente do avanço.",
            "confidence": "high", "metric_id": "revenue",
        },
    ],
}

UNGROUNDED_ANALYSIS: Dict[str, Any] = {
    **ANALYSIS,
    "insights": [{**ANALYSIS["insights"][0], "metric_ids": ["metrica-inexistente"]}],
}


def parse_lines(output: str) -> List[Dict[str, str]]:
    """Linhas `[intelligence]` do stdout viradas em dicionários de campos."""
    parsed: List[Dict[str, str]] = []
    for line in output.splitlines():
        if not line.startswith(f"{intelligence.LOG_PREFIX} "):
            continue
        fields: Dict[str, str] = {}
        for token in line[len(intelligence.LOG_PREFIX) + 1:].split(" "):
            if "=" in token:
                key, _, value = token.partition("=")
                fields.setdefault(key, value)
        parsed.append(fields)
    return parsed


def stages(lines: List[Dict[str, str]], event: str) -> List[str]:
    return [item.get("stage", "") for item in lines if item.get("event") == event]


async def run_route(
    *,
    provider: Any = None,
    insert: Any = None,
    snapshot: Any = None,
    analysis: Dict[str, Any] | None = None,
    validate_for_real: bool = False,
) -> Tuple[Any, BaseException | None, str]:
    """Executa a rota com o request_id do middleware e captura o stdout."""
    output = io.StringIO()
    token = api_support._set_request_id(REQUEST_ID)
    patches = [
        patch.dict(
            os.environ,
            {"OPENAI_API_KEY": API_KEY, "SUPABASE_SERVICE_ROLE_KEY": SERVICE_ROLE},
            clear=False,
        ),
        patch.object(routes, "require_user_id", AsyncMock(return_value="user-1")),
        patch.object(routes, "resolve_client_id", AsyncMock(return_value=CLIENT)),
        patch.object(
            intelligence, "calculate_intelligence_snapshot",
            AsyncMock(side_effect=snapshot) if isinstance(snapshot, BaseException)
            else AsyncMock(return_value=snapshot or SNAPSHOT),
        ),
        patch.object(
            intelligence, "_call_provider",
            AsyncMock(side_effect=provider) if isinstance(provider, BaseException)
            else AsyncMock(return_value=analysis or ANALYSIS),
        ),
        patch.object(
            intelligence, "sb_insert",
            AsyncMock(side_effect=insert) if insert is not None
            else AsyncMock(return_value={"id": "analysis-1", "status": "completed"}),
        ),
        patch.object(intelligence, "sb_select", AsyncMock(return_value=[])),
    ]
    if not validate_for_real:
        patches.append(patch.object(intelligence, "_validate_analysis_grounding", lambda *_a, **_kw: None))
    try:
        with redirect_stdout(output):
            for item in patches:
                item.start()
            try:
                result, error = await routes.intelligence_generate(
                    payload={"start": "2026-09-01", "end": "2026-09-30"},
                    client_id=None,
                    x_client_id=CLIENT,
                    authorization=f"Bearer {API_KEY}",
                ), None
            except BaseException as exc:  # noqa: BLE001 - o erro é o objeto do teste
                result, error = None, exc
            finally:
                for item in reversed(patches):
                    item.stop()
    finally:
        api_support._reset_request_id(token)
    return result, error, output.getvalue()


class HappyPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_started_opens_the_sequence_with_period_and_client(self):
        _, error, output = await run_route()
        self.assertIsNone(error)
        lines = parse_lines(output)
        self.assertTrue(lines, output)
        first = lines[0]
        self.assertEqual(first["event"], "request_started")
        self.assertEqual(first["request_id"], REQUEST_ID)
        self.assertEqual(first["client_id"], CLIENT)
        self.assertEqual(first["period_start"], "2026-09-01")
        self.assertEqual(first["period_end"], "2026-09-30")

    async def test_every_instrumented_stage_reports_completion_in_order(self):
        _, error, output = await run_route()
        self.assertIsNone(error)
        completed = stages(parse_lines(output), "stage_completed")
        expected = [
            intelligence.LOG_STAGE_AUTHORIZATION,
            intelligence.LOG_STAGE_SNAPSHOT,
            intelligence.LOG_STAGE_MODEL_REQUEST,
            intelligence.LOG_STAGE_MODEL_RESPONSE,
            intelligence.LOG_STAGE_VALIDATION,
            intelligence.LOG_STAGE_PERSISTENCE,
        ]
        # model_request/model_response saem de dentro de _call_provider, que
        # aqui está mockado; as outras provam a ordem real da rota.
        route_stages = [item for item in completed if item in expected]
        self.assertEqual(
            route_stages,
            [
                intelligence.LOG_STAGE_AUTHORIZATION,
                intelligence.LOG_STAGE_SNAPSHOT,
                intelligence.LOG_STAGE_VALIDATION,
                intelligence.LOG_STAGE_PERSISTENCE,
            ],
        )

    async def test_every_line_carries_elapsed_ms_and_the_same_request_id(self):
        _, error, output = await run_route()
        self.assertIsNone(error)
        lines = parse_lines(output)
        self.assertEqual({item["request_id"] for item in lines}, {REQUEST_ID})
        for item in lines:
            if item["event"] == "request_started":
                continue
            self.assertIn("elapsed_ms", item)
            self.assertTrue(item["elapsed_ms"].isdigit(), item)

    async def test_logging_does_not_change_the_analysis_result(self):
        result, error, _ = await run_route()
        self.assertIsNone(error)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["snapshot"], SNAPSHOT)
        self.assertEqual(result["analysis"], {"id": "analysis-1", "status": "completed"})


class StageFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_authorization_failure_is_identified(self):
        from fastapi import HTTPException

        output = io.StringIO()
        token = api_support._set_request_id(REQUEST_ID)
        denied = HTTPException(status_code=403, detail="sem acesso")
        try:
            with (
                redirect_stdout(output),
                patch.object(routes, "require_user_id", AsyncMock(side_effect=denied)),
                patch.object(routes, "generate_analysis", AsyncMock()) as generated,
            ):
                with self.assertRaises(HTTPException):
                    await routes.intelligence_generate(
                        payload={"start": "2026-09-01", "end": "2026-09-30"},
                        client_id=None, x_client_id=CLIENT,
                        authorization=f"Bearer {API_KEY}",
                    )
        finally:
            api_support._reset_request_id(token)
        generated.assert_not_awaited()
        failed = [item for item in parse_lines(output.getvalue()) if item["event"] == "stage_failed"]
        self.assertEqual([item["stage"] for item in failed], [intelligence.LOG_STAGE_AUTHORIZATION])
        self.assertEqual(failed[0]["request_id"], REQUEST_ID)
        self.assertEqual(failed[0]["error_type"], "HTTPException")

    async def test_snapshot_failure_is_identified(self):
        _, error, output = await run_route(snapshot=RuntimeError("INTELLIGENCE_CONTEXT_ERROR"))
        self.assertIsNotNone(error)
        failed = [item for item in parse_lines(output) if item["event"] == "stage_failed"]
        self.assertIn(intelligence.LOG_STAGE_SNAPSHOT, [item["stage"] for item in failed])
        snapshot_failure = next(
            item for item in failed if item["stage"] == intelligence.LOG_STAGE_SNAPSHOT
        )
        self.assertEqual(snapshot_failure["error_code"], "INTELLIGENCE_CONTEXT_ERROR")

    async def test_model_error_carries_upstream_status(self):
        response = httpx.Response(
            500, json={"error": {"message": "upstream"}},
            request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
        )
        started = {"calls": 0}

        async def post(*_args: Any, **_kwargs: Any) -> httpx.Response:
            started["calls"] += 1
            return response

        output = io.StringIO()
        with (
            redirect_stdout(output),
            patch.dict(os.environ, {"OPENAI_API_KEY": API_KEY}, clear=False),
            patch.object(httpx.AsyncClient, "post", post),
        ):
            with self.assertRaises(RuntimeError) as raised:
                await intelligence._call_provider(
                    payload={}, schema=intelligence.ANALYSIS_SCHEMA,
                    instructions="x", request_id=REQUEST_ID,
                )
        self.assertEqual(str(raised.exception), "AI_PROVIDER_ERROR_500")
        failed = [item for item in parse_lines(output.getvalue()) if item["event"] == "stage_failed"]
        self.assertEqual([item["stage"] for item in failed], [intelligence.LOG_STAGE_MODEL_RESPONSE])
        self.assertEqual(failed[0]["upstream_status"], "500")
        self.assertEqual(failed[0]["error_code"], "AI_PROVIDER_ERROR_500")
        self.assertEqual(failed[0]["success"], "false")
        self.assertEqual(failed[0]["request_id"], REQUEST_ID)

    async def test_missing_model_variable_is_reported_as_configuration(self):
        output = io.StringIO()
        with (
            redirect_stdout(output),
            patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False),
        ):
            with self.assertRaises(RuntimeError):
                await intelligence._call_provider(
                    payload={}, schema=intelligence.ANALYSIS_SCHEMA,
                    instructions="x", request_id=REQUEST_ID,
                )
        failed = [item for item in parse_lines(output.getvalue()) if item["event"] == "stage_failed"]
        self.assertEqual([item["error_code"] for item in failed], ["MODEL_CONFIGURATION_MISSING"])
        self.assertEqual(failed[0]["stage"], intelligence.LOG_STAGE_MODEL_REQUEST)

    async def test_validation_error_reports_the_existing_grounding_code(self):
        _, error, output = await run_route(
            analysis=UNGROUNDED_ANALYSIS, validate_for_real=True,
        )
        self.assertIsNotNone(error)
        failed = [item for item in parse_lines(output) if item["event"] == "stage_failed"]
        validation = next(
            item for item in failed if item["stage"] == intelligence.LOG_STAGE_VALIDATION
        )
        # A regra não foi relaxada: o código específico do grounding aparece.
        self.assertEqual(validation["error_code"], "AI_UNGROUNDED_INSIGHT")
        self.assertEqual(validation["request_id"], REQUEST_ID)

    async def test_persistence_error_reports_the_postgrest_code(self):
        request = httpx.Request("POST", "https://supabase.local/ai_analyses")
        response = httpx.Response(
            409,
            json={
                "code": "23505",
                "message": "duplicate key",
                "details": f"token={API_KEY}",
            },
            request=request,
        )

        async def insert(*_args: Any, **_kwargs: Any) -> Dict[str, Any]:
            raise httpx.HTTPStatusError("409", request=request, response=response)

        _, error, output = await run_route(insert=insert)
        self.assertIsNotNone(error)
        failed = [item for item in parse_lines(output) if item["event"] == "stage_failed"]
        persistence = next(
            item for item in failed if item["stage"] == intelligence.LOG_STAGE_PERSISTENCE
        )
        self.assertEqual(persistence["upstream_status"], "409")
        self.assertEqual(persistence["postgrest_code"], "23505")
        # O body traz credencial: nada dele pode entrar na linha.
        self.assertNotIn(API_KEY, output)
        self.assertNotIn("duplicate key", output)


    async def test_no_exception_reaches_the_502_without_a_structured_line(self):
        # AI_PROVIDER_EMPTY_RESPONSE não passa por nenhuma etapa instrumentada:
        # o catch-all tem de registrar a linha mesmo assim.
        _, error, output = await run_route(provider=RuntimeError("AI_PROVIDER_EMPTY_RESPONSE"))
        self.assertIsNotNone(error)
        failed = [item for item in parse_lines(output) if item["event"] == "stage_failed"]
        self.assertEqual(len(failed), 1, output)
        self.assertEqual(failed[0]["error_code"], "AI_PROVIDER_EMPTY_RESPONSE")
        self.assertEqual(failed[0]["request_id"], REQUEST_ID)

    async def test_an_already_logged_stage_is_not_logged_twice(self):
        _, error, output = await run_route(
            analysis=UNGROUNDED_ANALYSIS, validate_for_real=True,
        )
        self.assertIsNotNone(error)
        failed = [item for item in parse_lines(output) if item["event"] == "stage_failed"]
        self.assertEqual([item["stage"] for item in failed], [intelligence.LOG_STAGE_VALIDATION])

    async def test_the_legacy_generate_line_carries_the_request_id(self):
        _, error, output = await run_route(provider=RuntimeError("AI_PROVIDER_ERROR_503"))
        self.assertIsNotNone(error)
        legacy = [line for line in output.splitlines() if line.startswith("[intelligence][generate]")]
        self.assertEqual(len(legacy), 1, output)
        self.assertIn(f"request_id={REQUEST_ID}", legacy[0])


class SecretRedactionTests(unittest.IsolatedAsyncioTestCase):
    FORBIDDEN = (API_KEY, SERVICE_ROLE, "sk-proj-", "Bearer ", "service-role-que-nao-pode-vazar")

    def assert_clean(self, output: str) -> None:
        intelligence_output = "\n".join(
            line for line in output.splitlines() if line.startswith(intelligence.LOG_PREFIX)
        )
        for forbidden in self.FORBIDDEN:
            self.assertNotIn(forbidden, intelligence_output)
        for pattern in (r"(?i)password", r"(?i)\bsenha\b", r"(?i)service_role"):
            self.assertIsNone(re.search(pattern, intelligence_output), pattern)

    async def test_happy_path_logs_no_credential(self):
        _, _, output = await run_route()
        self.assert_clean(output)

    async def test_failure_logs_no_credential(self):
        _, _, output = await run_route(
            provider=RuntimeError(f"falhou com Authorization: Bearer {API_KEY}"),
        )
        self.assert_clean(output)

    def test_free_text_with_credentials_is_redacted(self):
        for raw in (
            f"Authorization: Bearer {API_KEY}",
            f"api_key={API_KEY}",
            f"access_token={SERVICE_ROLE}",
            "password=hunter2",
            SERVICE_ROLE,
            API_KEY,
        ):
            safe = intelligence._log_safe(raw)
            self.assertIn("[redacted]", safe, raw)
            self.assertNotIn(API_KEY, safe)
            self.assertNotIn(SERVICE_ROLE, safe)

    def test_structural_identifiers_survive_redaction(self):
        # O padrão de cadeia longa não pode apagar justamente os campos que
        # tornam o log pesquisável no Render.
        self.assertEqual(intelligence._log_safe(REQUEST_ID, key="request_id"), REQUEST_ID)
        client_uuid = "3f2b9c10-5d4e-4a7b-9c88-0ab1c2d3e4f5"
        self.assertEqual(intelligence._log_safe(client_uuid, key="client_id"), client_uuid)

    def test_log_line_is_single_line_and_prefixed(self):
        output = io.StringIO()
        with redirect_stdout(output):
            intelligence._log_line("stage_completed", stage="snapshot", note="quebra\nde linha")
        printed = output.getvalue().strip()
        self.assertEqual(len(printed.splitlines()), 1)
        self.assertTrue(printed.startswith(f"{intelligence.LOG_PREFIX} event=stage_completed"))
        self.assertIn("note=quebra de linha", printed)


class HttpAccessLineTests(unittest.TestCase):
    def test_http_line_is_emitted_even_when_the_handler_raises(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import app as app_module

        probe = FastAPI()
        probe.middleware("http")(app_module.safe_request_log)

        @probe.get("/boom")
        async def boom():  # noqa: ANN202
            raise RuntimeError("explodiu")

        output = io.StringIO()
        with redirect_stdout(output):
            client = TestClient(probe, raise_server_exceptions=False)
            client.get("/boom", headers={"X-Request-ID": REQUEST_ID})
        lines = [line for line in output.getvalue().splitlines() if line.startswith("[http] ")]
        self.assertEqual(len(lines), 1, output.getvalue())
        self.assertIn("method=GET", lines[0])
        self.assertIn("path=/boom", lines[0])
        self.assertIn("status=500", lines[0])
        self.assertIn(f"request_id={REQUEST_ID}", lines[0])
        self.assertRegex(lines[0], r"duration_ms=\d+")

    def test_http_line_reports_the_analysis_endpoint_and_status(self):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient

        import app as app_module

        probe = FastAPI()
        probe.middleware("http")(app_module.safe_request_log)

        @probe.post("/api/intelligence/analyses")
        async def analyses():  # noqa: ANN202
            raise HTTPException(status_code=502, detail="A análise não pôde ser concluída agora.")

        output = io.StringIO()
        with redirect_stdout(output):
            client = TestClient(probe, raise_server_exceptions=False)
            client.post(
                "/api/intelligence/analyses", json={},
                headers={"X-Request-ID": REQUEST_ID},
            )
        lines = [line for line in output.getvalue().splitlines() if line.startswith("[http] ")]
        self.assertEqual(len(lines), 1, output.getvalue())
        self.assertIn("method=POST path=/api/intelligence/analyses", lines[0])
        self.assertIn("status=502", lines[0])
        self.assertIn(f"request_id={REQUEST_ID}", lines[0])


class LogMechanismTests(unittest.TestCase):
    def test_stdout_is_line_buffered_by_the_app(self):
        source = (SERVER_DIR / "app.py").read_text(encoding="utf-8")
        self.assertIn("reconfigure(line_buffering=True)", source)

    def test_intelligence_log_flushes_explicitly(self):
        source = (SERVER_DIR / "services" / "intelligence.py").read_text(encoding="utf-8")
        block = source[source.index("def _log_line("):]
        self.assertIn("flush=True", block[:600])

    def test_no_silent_logger_is_introduced(self):
        # O mecanismo precisa ser o mesmo que já aparece no Render: print em
        # stdout. Um logging.getLogger novo poderia ficar mudo por config.
        source = (SERVER_DIR / "services" / "intelligence.py").read_text(encoding="utf-8")
        self.assertNotIn("getLogger", source)
        self.assertNotIn("import logging", source)


if __name__ == "__main__":
    unittest.main()
