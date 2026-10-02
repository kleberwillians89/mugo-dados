"""Google Ads: toda sincronização deixa rastro e métricas novas são provadas.

A Curavino ficou dias sem dados novos sem nenhum sinal: `sync_google_ads` não
registrava `cron_job_runs` (o GA4 registra) nem tocava a conexão, então a tela
mostrava o timestamp antigo do OAuth e a falha era invisível.

Aqui se verifica, sem rede e sem banco: tentativa registrada, sucesso com as
linhas gravadas, erro sanitizado com código, nenhum token em log, o `status` da
conexão preservado (uma falha não pode desligar o provider para sempre) e
isolamento entre empresas.
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import asynccontextmanager, redirect_stdout
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import google_ads
from services.integration_errors import IntegrationError

# Valor fictício com prefixo inválido de propósito: nenhum scanner de segredo
# deve confundi-lo com um access token real do Google.
TOKEN = "fake-google-ads-access-token-nao-real"
CONNECTION_ID = "00000000-0000-0000-0000-0000000000ad"


@asynccontextmanager
async def no_lock(**_kwargs):
    yield "lock"


def google_ads_error() -> IntegrationError:
    error = IntegrationError(
        "Google Ads recusou a consulta diária.", status_code=502,
        code="GOOGLE_ADS_QUERY_FAILED", provider="google_ads",
    )
    error.diagnostics = {"upstream_status": 403, "request_id": "req-123", "upstream_reason": "CUSTOMER_NOT_ENABLED"}
    return error


class ObservabilityHarness(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.connection = {
            "id": CONNECTION_ID, "client_id": "curavino", "provider": "google_ads",
            "status": "connected", "metadata": {"google_ads_customer_id": "1234567890"},
        }
        self.updates: List[Dict[str, Any]] = []
        self.started: List[Dict[str, Any]] = []
        self.finished: List[Dict[str, Any]] = []

    async def run_sync(self, *, outcome, client_id="curavino", connection_id=CONNECTION_ID, **kwargs):
        async def select(table, *, select="*", filters=None, order=None, limit=None, offset=None):
            # Imita o PostgREST: a linha só volta se casar com TODOS os filtros.
            filters = filters or {}
            row = dict(self.connection)
            matches = all(
                str(row.get(column) or "") == value.removeprefix("eq.")
                for column, value in filters.items() if value.startswith("eq.")
            )
            return [row] if matches else []

        async def update(table, *, filters, patch, returning="minimal"):
            self.updates.append({"table": table, "filters": dict(filters), "patch": dict(patch)})
            return [{}]

        async def start_job_run(**kwargs):
            self.started.append(dict(kwargs))
            return {"id": "job-1"}

        async def finish_job_run(job_run_id, **kwargs):
            self.finished.append({"id": job_run_id, **kwargs})
            return {}

        inner = AsyncMock(side_effect=outcome) if isinstance(outcome, BaseException) else AsyncMock(return_value=outcome)
        output = io.StringIO()
        with (
            patch.object(google_ads, "guarded_sync", no_lock),
            patch.object(google_ads, "_sync_google_ads", inner),
            patch.object(google_ads, "sb_select", AsyncMock(side_effect=select)),
            patch.object(google_ads, "sb_update", AsyncMock(side_effect=update)),
            patch.object(google_ads, "start_job_run", AsyncMock(side_effect=start_job_run)),
            patch.object(google_ads, "finish_job_run", AsyncMock(side_effect=finish_job_run)),
            redirect_stdout(output),
        ):
            try:
                payload, error = await google_ads.sync_google_ads(
                    client_id=client_id, connection_id=connection_id,
                    start=None, end=None, days=7, **kwargs,
                ), None
            except Exception as exc:  # noqa: BLE001
                payload, error = None, exc
        self.inner = inner
        return payload, error, output.getvalue()

    def success(self, rows=12):
        return {
            "ok": True, "client_id": "curavino", "connection_id": CONNECTION_ID,
            "customer_id": "1234567890",
            "period": {"start": "2026-09-26", "end": "2026-10-02", "days": 7},
            "rows_received": rows, "rows_upserted": rows,
        }

    def metadata_patch(self):
        return self.updates[-1]["patch"]["metadata"]


class SuccessfulSyncTests(ObservabilityHarness):
    async def test_success_records_rows_attempt_and_success_timestamps(self):
        payload, error, _log = await self.run_sync(outcome=self.success(rows=12))
        self.assertIsNone(error)
        self.assertEqual(payload["rows_upserted"], 12)
        self.assertEqual(payload["job_run_id"], "job-1")
        self.assertEqual(payload["last_attempt_at"], payload["last_success_at"])

        self.assertEqual(self.started[0]["job_name"], "google_ads_sync_manual")
        self.assertEqual(self.started[0]["connection_id"], CONNECTION_ID)
        self.assertEqual(self.finished[0]["status"], "success")
        self.assertEqual(self.finished[0]["rows_upserted"], 12)

        patch_sent = self.updates[-1]["patch"]
        self.assertEqual(patch_sent["last_sync_at"], payload["last_success_at"])
        self.assertIsNone(patch_sent["last_error"])
        metadata = self.metadata_patch()
        self.assertEqual(metadata["last_success_at"], payload["last_success_at"])
        self.assertEqual(metadata["last_sync_rows"], 12)
        self.assertIsNone(metadata["last_error_code"])
        # A conta selecionada não é perdida pela escrita de observabilidade.
        self.assertEqual(metadata["google_ads_customer_id"], "1234567890")

    async def test_new_campaign_metrics_are_proven_by_rows_upserted(self):
        _payload, _error, log = await self.run_sync(outcome=self.success(rows=35))
        self.assertIn("status=ok rows_upserted=35", log)
        self.assertEqual(self.finished[0]["payload_json"]["rows_upserted"], 35)

    async def test_zero_rows_is_a_success_without_claiming_new_data(self):
        payload, _error, _log = await self.run_sync(outcome=self.success(rows=0))
        self.assertEqual(payload["rows_upserted"], 0)
        self.assertEqual(self.finished[0]["status"], "success")
        self.assertEqual(self.finished[0]["rows_upserted"], 0)
        self.assertEqual(self.metadata_patch()["last_sync_rows"], 0)

    async def test_cron_trigger_is_identified_apart_from_manual(self):
        await self.run_sync(outcome=self.success(), job_name="google_ads_sync_cron", trigger_source="cron")
        self.assertEqual(self.started[0]["job_name"], "google_ads_sync_cron")
        self.assertEqual(self.started[0]["trigger_source"], "cron")

    async def test_period_is_forwarded_untouched_to_the_api_call(self):
        await self.run_sync(outcome=self.success())
        self.assertEqual(self.inner.await_args.kwargs["days"], 7)
        self.assertIsNone(self.inner.await_args.kwargs["start"])


class FailedSyncTests(ObservabilityHarness):
    async def test_failure_records_sanitized_code_and_keeps_raising(self):
        _payload, error, log = await self.run_sync(outcome=google_ads_error())
        self.assertIsInstance(error, IntegrationError)
        self.assertEqual(error.code, "GOOGLE_ADS_QUERY_FAILED")

        self.assertEqual(self.finished[0]["status"], "error")
        recorded = self.finished[0]["payload_json"]["error"]
        self.assertEqual(recorded["code"], "GOOGLE_ADS_QUERY_FAILED")
        self.assertEqual(recorded["upstream_status"], 403)
        self.assertEqual(recorded["request_id"], "req-123")
        self.assertIn("code=GOOGLE_ADS_QUERY_FAILED", log)

        metadata = self.metadata_patch()
        self.assertEqual(metadata["last_error_code"], "GOOGLE_ADS_QUERY_FAILED")
        self.assertIn("last_attempt_at", metadata)
        self.assertNotIn("last_success_at", metadata)

    async def test_failure_never_changes_the_connection_status(self):
        # O cron seleciona status=connected: marcar erro aqui desligaria o
        # provider em definitivo, que foi o modo de falha silenciosa.
        await self.run_sync(outcome=google_ads_error())
        self.assertNotIn("status", self.updates[-1]["patch"])

    async def test_unexpected_exception_is_recorded_without_leaking_internals(self):
        _payload, error, _log = await self.run_sync(outcome=RuntimeError(f"token {TOKEN} inválido"))
        self.assertIsInstance(error, RuntimeError)
        recorded = self.finished[0]["payload_json"]["error"]
        self.assertEqual(recorded["code"], "GOOGLE_ADS_SYNC_FAILED")
        self.assertEqual(recorded["message"], "RuntimeError")

    async def test_no_token_reaches_logs_or_recorded_payloads(self):
        for outcome in (self.success(), google_ads_error(), RuntimeError(f"Bearer {TOKEN}")):
            with self.subTest(outcome=type(outcome).__name__):
                self.updates.clear(); self.started.clear(); self.finished.clear()
                _payload, _error, log = await self.run_sync(outcome=outcome)
                blob = f"{log}{self.started}{self.finished}{self.updates}"
                self.assertNotIn(TOKEN, blob)

    async def test_observability_write_failure_does_not_break_the_sync(self):
        async def exploding_update(*_args, **_kwargs):
            raise RuntimeError("supabase fora")

        with (
            patch.object(google_ads, "guarded_sync", no_lock),
            patch.object(google_ads, "_sync_google_ads", AsyncMock(return_value=self.success())),
            patch.object(google_ads, "sb_select", AsyncMock(return_value=[dict(self.connection)])),
            patch.object(google_ads, "sb_update", AsyncMock(side_effect=exploding_update)),
            patch.object(google_ads, "start_job_run", AsyncMock(return_value={"id": "job-1"})),
            patch.object(google_ads, "finish_job_run", AsyncMock(return_value={})),
            redirect_stdout(io.StringIO()),
        ):
            payload = await google_ads.sync_google_ads(
                client_id="curavino", connection_id=CONNECTION_ID, start=None, end=None, days=7,
            )
        self.assertEqual(payload["rows_upserted"], 12)


class TenantIsolationTests(ObservabilityHarness):
    async def test_observability_only_touches_the_authorized_tenant(self):
        await self.run_sync(outcome=self.success())
        for update in self.updates:
            self.assertEqual(update["filters"]["client_id"], "eq.curavino")
            self.assertEqual(update["filters"]["provider"], "eq.google_ads")
            self.assertEqual(update["filters"]["id"], f"eq.{CONNECTION_ID}")

    async def test_another_tenant_connection_is_never_patched(self):
        self.connection["client_id"] = "outra-empresa"
        await self.run_sync(outcome=self.success())
        # O select não encontra a conexão do outro tenant: nada é sobrescrito.
        self.assertEqual(self.updates[-1]["filters"]["client_id"], "eq.curavino")
        self.assertEqual(self.metadata_patch().get("google_ads_customer_id"), None)


class IndependenceFromGa4Tests(unittest.TestCase):
    def test_cron_records_google_ads_runs_like_ga4(self):
        source = (SERVER_DIR / "services" / "cron_jobs.py").read_text(encoding="utf-8")
        self.assertIn('job_name="google_ads_sync_cron"', source)
        self.assertIn('trigger_source="cron", record_job_run=True', source)

    def test_connection_sync_route_identifies_the_manual_trigger(self):
        source = (SERVER_DIR / "routes" / "google_oauth.py").read_text(encoding="utf-8")
        self.assertIn('trigger_source="manual_oauth_connection"', source)


if __name__ == "__main__":
    unittest.main()
