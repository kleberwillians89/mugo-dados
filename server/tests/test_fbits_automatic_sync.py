"""FBITS atualiza sozinho: os dados analíticos deixam de depender de clique.

Os KPIs executivos (receita, pedidos, ticket) continuam vindo de
GET /dashboard/faturamento — este job só atualiza o que deriva de /pedidos:
situações, aguardando, produtos, clientes, descontos, frete e tendência.
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import cron_jobs
from services import fbits_connections
from services.integration_errors import IntegrationError

REPO_ROOT = SERVER_DIR.parent


def connection(client_id: str, **overrides: Any) -> Dict[str, Any]:
    row = {
        "id": f"fbits-{client_id}", "client_id": client_id, "provider": "fbits",
        "status": "connected", "disconnected_at": None, "metadata": {},
    }
    row.update(overrides)
    return row


def ok(client_id: str, *, orders: int = 5, mode: str = "incremental") -> Dict[str, Any]:
    return {
        "ok": True, "client_id": client_id, "mode": mode, "orders_upserted": orders,
        "items_upserted": orders * 2, "daily_upserted": 1, "requests": 3,
        "last_attempt_at": "2026-10-02T17:00:00+00:00",
        "last_success_at": "2026-10-02T17:00:05+00:00",
        "job_run_id": "job-1",
    }


class CronHarness(unittest.IsolatedAsyncioTestCase):
    async def run_job(self, connections: List[Dict[str, Any]], outcomes: Dict[str, Any], *, window_days: int = 1):
        self.synced: List[Dict[str, Any]] = []

        async def sync(**kwargs):
            self.synced.append(dict(kwargs))
            outcome = outcomes.get(kwargs["client_id"])
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome if outcome is not None else ok(kwargs["client_id"])

        output = io.StringIO()
        with (
            patch.object(cron_jobs, "sb_select", AsyncMock(return_value=[dict(row) for row in connections])),
            # run_fbits_sync_all importa do módulo em tempo de execução.
            patch.object(fbits_connections, "sync_fbits_connection", AsyncMock(side_effect=sync)),
            redirect_stdout(output),
        ):
            summary = await cron_jobs.run_fbits_sync_all(window_days=window_days)
        return summary, output.getvalue()


class ConnectionSelectionTests(CronHarness):
    async def test_syncs_every_active_company_once(self):
        summary, _log = await self.run_job(
            [connection("curavino"), connection("vinhos")],
            {},
        )
        self.assertEqual(summary["job"], "fbits_sync")
        self.assertEqual((summary["connections_total"], summary["connections_ok"], summary["connections_fail"]), (2, 2, 0))
        self.assertEqual([call["client_id"] for call in self.synced], ["curavino", "vinhos"])

    async def test_a_previous_failure_never_excludes_the_company_forever(self):
        # A própria sincronização marca sync_error/reauth_required ao falhar:
        # filtrar status=connected desligaria a empresa em definitivo.
        rows = [
            connection("curavino", status="sync_error"),
            connection("vinhos", status="reauth_required"),
            connection("roove", status="connected"),
        ]
        summary, _log = await self.run_job(rows, {})
        self.assertEqual(summary["connections_total"], 3)
        self.assertEqual([call["client_id"] for call in self.synced], ["curavino", "vinhos", "roove"])

    async def test_disconnected_company_is_skipped(self):
        rows = [
            connection("curavino", status="disconnected"),
            connection("vinhos", disconnected_at="2026-09-01T00:00:00Z"),
            connection("roove", status="not_configured"),
            connection("amalie"),
        ]
        summary, _log = await self.run_job(rows, {})
        self.assertEqual(summary["connections_total"], 1)
        self.assertEqual([call["client_id"] for call in self.synced], ["amalie"])

    async def test_rows_without_identifiers_are_ignored(self):
        summary, _log = await self.run_job([connection(""), {"provider": "fbits", "client_id": "x"}], {})
        self.assertEqual(self.synced, [])
        self.assertEqual(summary["connections_ok"], 0)

    async def test_only_fbits_connections_are_requested(self):
        with (
            patch.object(cron_jobs, "sb_select", AsyncMock(return_value=[])) as select,
            redirect_stdout(io.StringIO()),
        ):
            await cron_jobs.run_fbits_sync_all()
        self.assertEqual(select.await_args.kwargs["filters"], {"provider": "eq.fbits"})


class IsolationAndObservabilityTests(CronHarness):
    async def test_one_company_failing_does_not_stop_the_others(self):
        summary, _log = await self.run_job(
            [connection("curavino"), connection("vinhos"), connection("roove")],
            {"vinhos": IntegrationError(
                "Limite de requisições da FBITS atingido.", status_code=429,
                code="FBITS_RATE_LIMITED", provider="fbits", retryable=True,
            )},
        )
        self.assertEqual((summary["connections_ok"], summary["connections_fail"]), (2, 1))
        self.assertEqual([call["client_id"] for call in self.synced], ["curavino", "vinhos", "roove"])
        failed = next(item for item in summary["results"] if not item["ok"])
        self.assertEqual(failed["client_id"], "vinhos")
        self.assertEqual(failed["error_code"], "FBITS_RATE_LIMITED")

    async def test_unexpected_exception_is_contained_and_classified(self):
        summary, _log = await self.run_job(
            [connection("curavino"), connection("vinhos")],
            {"curavino": RuntimeError("supabase fora")},
        )
        self.assertEqual((summary["connections_ok"], summary["connections_fail"]), (1, 1))
        self.assertEqual(summary["results"][0]["error_code"], "RuntimeError")

    async def test_each_run_is_recorded_as_a_cron_attempt(self):
        await self.run_job([connection("curavino")], {})
        self.assertEqual(self.synced[0]["job_name"], "fbits_sync_cron")
        self.assertEqual(self.synced[0]["trigger_source"], "cron")
        self.assertIs(self.synced[0]["record_job_run"], True)

    async def test_zero_new_orders_is_success_not_failure(self):
        summary, _log = await self.run_job(
            [connection("curavino")], {"curavino": ok("curavino", orders=0)},
        )
        self.assertEqual((summary["connections_ok"], summary["connections_fail"]), (1, 0))
        self.assertEqual(summary["results"][0]["orders_upserted"], 0)

    async def test_summary_carries_mode_and_request_count(self):
        summary, _log = await self.run_job(
            [connection("curavino")], {"curavino": ok("curavino", mode="historical")},
        )
        self.assertEqual(summary["results"][0]["mode"], "historical")
        self.assertEqual(summary["results"][0]["requests"], 3)

    async def test_no_token_reaches_logs_or_summary(self):
        token = "fbits-token-que-nunca-pode-vazar"
        summary, log = await self.run_job(
            [connection("curavino")], {"curavino": RuntimeError(f"Basic {token}")},
        )
        self.assertNotIn(token, log)
        # str(exc) é truncado; o resumo não deve carregar o segredo inteiro.
        self.assertNotIn(token, str(summary["results"][0]["error_code"]))

    async def test_sync_decides_the_window_itself(self):
        # O job não encurta o incremental: quem decide a janela é a conexão.
        await self.run_job([connection("curavino")], {}, window_days=30)
        self.assertNotIn("days", self.synced[0])
        self.assertNotIn("now", self.synced[0])


class SyncObservabilityFieldsTests(unittest.TestCase):
    def test_connection_sync_records_attempt_success_and_counters(self):
        source = (SERVER_DIR / "services" / "fbits_connections.py").read_text(encoding="utf-8")
        for field in ('metadata["last_attempt_at"]', 'metadata["last_success_at"]', 'metadata["last_sync_orders"]'):
            self.assertIn(field, source)
        self.assertIn("_safe_start_job_run", source)
        self.assertIn("_safe_finish_job_run", source)

    def test_error_is_recorded_with_sanitized_code_and_public_message(self):
        source = (SERVER_DIR / "services" / "fbits_connections.py").read_text(encoding="utf-8")
        self.assertIn('error=f"{exc.code}: {exc.public_message[:240]}"', source)

    def test_observability_failure_cannot_break_the_sync(self):
        source = (SERVER_DIR / "services" / "fbits_connections.py").read_text(encoding="utf-8")
        start = source.index("async def _safe_start_job_run")
        end = source.index("async def _persist_state")
        self.assertIn("except Exception", source[start:end])


class DeploymentContractTests(unittest.TestCase):
    def setUp(self):
        self.render = (REPO_ROOT / "render.yaml").read_text(encoding="utf-8")
        self.jobs = (SERVER_DIR / "run_jobs.py").read_text(encoding="utf-8")

    def test_cli_exposes_the_recurring_fbits_command(self):
        self.assertIn('"fbits-sync-all"', self.jobs)
        self.assertIn("run_fbits_sync_all(window_days=args.days)", self.jobs)

    def test_render_declares_the_fbits_cron(self):
        self.assertIn("name: mugo-dados-fbits-incremental", self.render)
        self.assertIn("python run_jobs.py fbits-sync-all", self.render)

    def test_web_service_name_matches_production(self):
        # Nome divergente faz o Blueprint criar outro serviço em vez de
        # atualizar o existente — foi o que manteve os crons inexistentes.
        self.assertIn("name: mugo-dados\n", self.render)
        self.assertNotIn("name: mugo-dados-api", self.render)

    def test_every_provider_has_a_scheduled_job(self):
        for command in (
            "organic-sync", "ads-sync-hourly", "ga4-sync-all",
            "google-ads-sync", "shopify-reconcile", "fbits-sync-all",
        ):
            with self.subTest(command=command):
                self.assertIn(f"python run_jobs.py {command}", self.render)


if __name__ == "__main__":
    unittest.main()
