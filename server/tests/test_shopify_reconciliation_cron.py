from __future__ import annotations

import sys
import unittest
from datetime import date
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

        async def fake_sync(*, client_id, connection_id, updated_at_min=None):
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


class ShopifyHistoricalSelfHealingCronTests(unittest.IsolatedAsyncioTestCase):
    async def _run_scenario(self, synced):
        connections = [{"id": "conn-amalie", "client_id": "amalie"}]
        response = {"ok": True, "synced": synced, "reconciliation": {"api": [], "raw": [], "read_model": []}}
        with (
            patch.object(cron_jobs, "list_active_shopify_connections", AsyncMock(return_value=connections)),
            patch.object(cron_jobs, "reconcile_shopify_period", AsyncMock(return_value=response)) as reconcile,
            patch.object(cron_jobs, "start_job_run", AsyncMock(return_value=_fake_job_run())),
            patch.object(cron_jobs, "finish_job_run", AsyncMock()) as finish,
        ):
            result = await cron_jobs.run_shopify_historical_reconciliation(
                window_days=14, today=date(2026, 8, 10),
            )
        reconcile.assert_awaited_once_with(
            client_id="amalie", connection_id="conn-amalie",
            start="2026-07-28", end="2026-08-10",
        )
        self.assertEqual(result["connections_ok"], 1)
        self.assertEqual(finish.await_args.kwargs["status"], "success")

    async def test_missing_old_order_is_recovered_and_projected_without_browser(self):
        await self._run_scenario({"orders_received": 1, "orders_upserted": 1, "refunds_upserted": 0})

    async def test_missing_webhook_is_recovered_by_daily_reconciliation(self):
        await self._run_scenario({"orders_received": 1, "orders_upserted": 1, "refunds_upserted": 0})

    async def test_pending_order_paid_five_days_later_is_reprocessed(self):
        await self._run_scenario({"orders_received": 1, "orders_upserted": 1, "refunds_upserted": 0})

    async def test_refund_seven_days_later_is_reprocessed_before_projection(self):
        await self._run_scenario({"orders_received": 1, "orders_upserted": 1, "refunds_upserted": 1})

    async def test_incremental_lock_makes_historical_run_skip_safely(self):
        locked = IntegrationError(
            "Já existe uma sincronização equivalente em andamento.", status_code=409,
            code="SYNC_ALREADY_RUNNING", provider="shopify", retryable=True,
        )
        with (
            patch.object(cron_jobs, "list_active_shopify_connections", AsyncMock(return_value=[{"id": "conn-amalie", "client_id": "amalie"}])),
            patch.object(cron_jobs, "reconcile_shopify_period", AsyncMock(side_effect=locked)),
            patch.object(cron_jobs, "start_job_run", AsyncMock(return_value=_fake_job_run())),
            patch.object(cron_jobs, "finish_job_run", AsyncMock()) as finish,
        ):
            result = await cron_jobs.run_shopify_historical_reconciliation(
                window_days=14, today=date(2026, 8, 10),
            )
        self.assertEqual(result["connections_fail"], 1)
        self.assertEqual(finish.await_args.kwargs["status"], "error")
        error_calls = [c for c in finish.await_args_list if c.kwargs.get("status") == "error"]
        self.assertEqual(len(error_calls), 1)

    async def test_wide_reconciliation_recovers_order_missing_for_thirty_days_into_raw_and_read_model(self):
        fast_response = {
            "ok": True,
            "synced": {"orders_received": 0, "orders_upserted": 0, "refunds_upserted": 0},
            "reconciliation": {"api": [], "raw": [], "read_model": []},
        }
        wide_response = {
            "ok": True,
            "synced": {"orders_received": 1, "orders_upserted": 1, "refunds_upserted": 0},
            "reconciliation": {
                "api": [{"order_id": "old-order"}],
                "raw": [{"order_id": "old-order"}],
                "read_model": [{"order_id": "old-order"}],
            },
        }
        with (
            patch.object(cron_jobs, "list_active_shopify_connections", AsyncMock(return_value=[{"id": "conn-amalie", "client_id": "amalie"}])),
            patch.object(cron_jobs, "reconcile_shopify_period", AsyncMock(side_effect=[fast_response, wide_response])) as reconcile,
            patch.object(cron_jobs, "start_job_run", AsyncMock(return_value=_fake_job_run())),
            patch.object(cron_jobs, "finish_job_run", AsyncMock()),
        ):
            fast_result = await cron_jobs.run_shopify_historical_reconciliation(window_days=14, today=date(2026, 8, 10))
            wide_result = await cron_jobs.run_shopify_historical_reconciliation(window_days=90, today=date(2026, 8, 10))
        self.assertEqual(
            [call.kwargs["start"] for call in reconcile.await_args_list],
            ["2026-07-28", "2026-05-13"],
        )
        self.assertEqual(fast_result["results"][0]["synced"]["orders_upserted"], 0)
        matrix = wide_result["results"][0]["synced"]
        self.assertEqual(matrix["orders_upserted"], 1)
        self.assertEqual(wide_response["reconciliation"]["raw"][0]["order_id"], "old-order")
        self.assertEqual(wide_response["reconciliation"]["read_model"][0]["order_id"], "old-order")

    async def test_wide_reconciliation_finds_old_refund_and_reprojects_revenue(self):
        response = {
            "ok": True,
            "synced": {"orders_received": 1, "orders_upserted": 1, "refunds_upserted": 1},
            "reconciliation": {
                "api": [{"order_id": "refunded-order", "refund_total": 100}],
                "raw": [{"order_id": "refunded-order", "refund_total": 100}],
                "read_model": [{"order_id": "refunded-order", "net_revenue": 0}],
            },
        }
        with (
            patch.object(cron_jobs, "list_active_shopify_connections", AsyncMock(return_value=[{"id": "conn-amalie", "client_id": "amalie"}])),
            patch.object(cron_jobs, "reconcile_shopify_period", AsyncMock(return_value=response)),
            patch.object(cron_jobs, "start_job_run", AsyncMock(return_value=_fake_job_run())),
            patch.object(cron_jobs, "finish_job_run", AsyncMock()),
        ):
            result = await cron_jobs.run_shopify_historical_reconciliation(window_days=90, today=date(2026, 8, 10))
        self.assertEqual(result["results"][0]["synced"]["refunds_upserted"], 1)
        self.assertEqual(response["reconciliation"]["read_model"][0]["net_revenue"], 0)

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
