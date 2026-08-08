from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import cron_jobs  # noqa: E402
from services.integration_errors import IntegrationError  # noqa: E402


def _fake_job_run(job_id: str = "job-1"):
    return {"id": job_id}


class ShopifyReconciliationCronTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconciles_every_active_shopify_connection(self):
        connections = [
            {"id": "conn-amalie", "client_id": "amalie"},
            {"id": "conn-roove", "client_id": "roove"},
        ]
        with (
            patch.object(cron_jobs, "list_active_shopify_connections", AsyncMock(return_value=connections)),
            patch.object(cron_jobs, "resolve_shopify_reconciliation_since", AsyncMock(return_value="2026-08-01T00:00:00")),
            patch.object(cron_jobs, "sync_shopify_connection", AsyncMock(return_value={"ok": True, "synced": {"orders": 3}})) as sync,
            patch.object(cron_jobs, "start_job_run", AsyncMock(side_effect=lambda **_: _fake_job_run())),
            patch.object(cron_jobs, "finish_job_run", AsyncMock()),
        ):
            result = await cron_jobs.run_shopify_reconciliation()

        self.assertEqual(result["connections_total"], 2)
        self.assertEqual(result["connections_ok"], 2)
        self.assertEqual(sync.await_count, 2)

    async def test_one_connection_locked_by_a_concurrent_sync_never_runs_twice_and_others_still_reconcile(self):
        # Se guarded_sync (usado dentro de sync_shopify_connection) já
        # estiver com o lock preso por outra execução concorrente, a
        # reconciliação deve registrar a falha isolada e seguir para as
        # próximas conexões — nunca travar o job inteiro nem tentar de novo
        # na mesma rodada (sem execução concorrente do mesmo provider/conexão).
        connections = [
            {"id": "conn-locked", "client_id": "amalie"},
            {"id": "conn-free", "client_id": "roove"},
        ]

        async def fake_sync(*, client_id, connection_id, created_at_min=None):
            if connection_id == "conn-locked":
                raise IntegrationError(
                    "Já existe uma sincronização equivalente em andamento.",
                    status_code=409, code="SYNC_ALREADY_RUNNING", provider="shopify", retryable=True,
                )
            return {"ok": True, "synced": {"orders": 1}}

        with (
            patch.object(cron_jobs, "list_active_shopify_connections", AsyncMock(return_value=connections)),
            patch.object(cron_jobs, "resolve_shopify_reconciliation_since", AsyncMock(return_value="2026-08-01T00:00:00")),
            patch.object(cron_jobs, "sync_shopify_connection", AsyncMock(side_effect=fake_sync)) as sync,
            patch.object(cron_jobs, "start_job_run", AsyncMock(side_effect=lambda **_: _fake_job_run())),
            patch.object(cron_jobs, "finish_job_run", AsyncMock()) as finish,
        ):
            result = await cron_jobs.run_shopify_reconciliation()

        self.assertEqual(sync.await_count, 2)
        self.assertEqual(result["connections_ok"], 1)
        self.assertEqual(result["connections_fail"], 1)
        error_calls = [c for c in finish.await_args_list if c.kwargs.get("status") == "error"]
        self.assertEqual(len(error_calls), 1)

    async def test_reconciliation_failure_never_raises_out_of_the_job(self):
        connections = [{"id": "conn-amalie", "client_id": "amalie"}]
        with (
            patch.object(cron_jobs, "list_active_shopify_connections", AsyncMock(return_value=connections)),
            patch.object(cron_jobs, "resolve_shopify_reconciliation_since", AsyncMock(return_value="2026-08-01T00:00:00")),
            patch.object(cron_jobs, "sync_shopify_connection", AsyncMock(side_effect=RuntimeError("timeout"))),
            patch.object(cron_jobs, "start_job_run", AsyncMock(side_effect=lambda **_: _fake_job_run())),
            patch.object(cron_jobs, "finish_job_run", AsyncMock()),
        ):
            result = await cron_jobs.run_shopify_reconciliation()
        self.assertTrue(result["ok"])
        self.assertEqual(result["connections_fail"], 1)


if __name__ == "__main__":
    unittest.main()
