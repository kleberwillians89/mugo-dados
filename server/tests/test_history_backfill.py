"""Busca de histórico: alvo congelado, blocos retomáveis, falha isolada por fonte."""

import sys
import unittest
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services import history_backfill as hb  # noqa: E402
from routes import platform_admin as routes  # noqa: E402


class FakeRuns:
    """cron_job_runs em memória, com os filtros que o serviço usa."""

    def __init__(self):
        self.rows = []

    async def start(self, *, job_name, client_id=None, trigger_source="cron", payload_json=None, **_):
        row = {"id": f"run-{len(self.rows) + 1}", "job_name": job_name, "client_id": client_id,
               "status": "running", "started_at": f"2026-10-27T00:00:{len(self.rows):02d}Z",
               "payload_json": dict(payload_json or {})}
        self.rows.append(row)
        return row

    async def finish(self, job_id, *, status, payload_json=None, **_):
        for row in self.rows:
            if row["id"] == job_id:
                row["status"] = status
                if payload_json is not None:
                    row["payload_json"] = dict(payload_json)

    async def select(self, table, *, select=None, filters=None, order=None, limit=None):
        assert table == "cron_job_runs", table
        filters = filters or {}
        out = []
        for row in self.rows:
            ok = True
            for key, value in filters.items():
                expected = value.split(".", 1)[1]
                if key.startswith("payload_json->>"):
                    ok &= str(row["payload_json"].get(key.split(">>")[1])) == expected
                else:
                    ok &= str(row.get(key)) == expected
            if ok:
                out.append(row)
        out.sort(key=lambda r: r["started_at"], reverse=bool(order and order.endswith("desc")))
        return out[: limit or len(out)]


@asynccontextmanager
async def _no_lock(**_):
    yield "lock"


TODAY = date(2026, 10, 27)


class HistoryBackfillTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.runs = FakeRuns()
        self.calls = []
        self.fail = set()

        self.patches = [
            patch.object(hb, "sb_select", self.runs.select),
            patch.object(hb, "start_job_run", self.runs.start),
            patch.object(hb, "finish_job_run", self.runs.finish),
            patch.object(hb, "guarded_sync", _no_lock),
            patch.object(hb, "_today", lambda: TODAY),
            patch.object(hb.asyncio, "sleep", AsyncMock()),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in self.patches])

        connections = {"fbits": "conn-f", "shopify": None, "google_ads": "conn-g", "ga4": None, "meta_ads": None}
        earliest = {"fbits": date(2026, 7, 29), "google_ads": None}

        async def connection_or_none(provider, client_id):
            return connections[provider]

        async def earliest_fn(table, column, client_id):
            return {"fbits_orders": earliest["fbits"], "google_ads_daily_stats": earliest["google_ads"]}.get(table)

        patch.object(hb, "_connection_or_none", connection_or_none).start()
        patch.object(hb, "_earliest", earliest_fn).start()
        self.addCleanup(patch.stopall)

        self.runners = {}
        for provider in hb.PROVIDERS:
            async def run(client_id, block, provider=provider):
                self.calls.append((provider, block["start"], block["end"]))
                if provider in self.fail:
                    raise hb.HistoryBackfillError("limite", code="FBITS_RATE_LIMITED")
                return 3
            self.runners[provider] = run
        patch.dict(hb.RUNNERS, self.runners).start()

    def test_start_limits(self):
        with self.assertRaises(hb.HistoryBackfillError):
            hb.validate_start("2026-10-27", today=TODAY)
        with self.assertRaises(hb.HistoryBackfillError):
            hb.validate_start("2024-01-01", today=TODAY)
        with self.assertRaises(hb.HistoryBackfillError):
            hb.validate_start("01/01/2026", today=TODAY)
        self.assertEqual(hb.validate_start("2026-01-01", today=TODAY), date(2026, 1, 1))

    def test_blocks_cover_range_without_gaps(self):
        blocks = hb.build_blocks(date(2026, 1, 1), date(2026, 1, 20), 7)
        self.assertEqual([(b["start"], b["end"]) for b in blocks],
                         [("2026-01-01", "2026-01-07"), ("2026-01-08", "2026-01-14"), ("2026-01-15", "2026-01-20")])
        self.assertEqual(hb.build_blocks(date(2026, 2, 1), date(2026, 1, 1), 7), [])

    async def test_simulation_only_reads_and_targets_missing_past(self):
        plan = await hb.history_plan("c1", "2026-01-01")
        by = {item["provider"]: item for item in plan["providers"]}
        # FBITS já tem desde 29/07: só falta até 28/07.
        self.assertEqual((by["fbits"]["missing_start"], by["fbits"]["missing_end"]), ("2026-01-01", "2026-07-28"))
        self.assertEqual(by["fbits"]["blocks_total"], 30)
        # Google Ads sem nenhum dado: busca até ontem.
        self.assertEqual(by["google_ads"]["missing_end"], "2026-10-26")
        self.assertEqual(by["shopify"]["state"], "not_connected")
        self.assertEqual(self.runs.rows, [])  # simular não grava nada
        self.assertIsNone(plan["request"])

    async def test_request_then_rounds_resume_and_complete(self):
        await hb.request_history("c1", "2026-07-01", requested_by="admin")
        with self.assertRaises(hb.HistoryBackfillError):
            await hb.request_history("c1", "2026-07-01", requested_by="admin")
        # Rodada curta: orçamento acaba depois do primeiro bloco.
        clock = iter([0, 0])  # prazo calculado em 0; 1º bloco em 0; depois o tempo acabou
        with patch.object(hb.time, "monotonic", lambda: next(clock, 1000)):
            first = await hb.run_history_step("c1", budget_seconds=20)
        self.assertEqual(first["processed"], 1)
        self.assertEqual(self.calls[0], ("fbits", "2026-07-22", "2026-07-28"))  # mais recente primeiro
        self.assertEqual(first["state"], "pending")
        second = await hb.run_history_step("c1", budget_seconds=600)
        # Retoma sem repetir o bloco já concluído.
        self.assertEqual(self.calls.count(("fbits", "2026-07-22", "2026-07-28")), 1)
        self.assertEqual(second["state"], "complete")
        self.assertIsNone(await hb.active_request("c1"))
        self.assertTrue(all(row["status"] == "success" for row in self.runs.rows))

    async def test_failure_stops_only_that_source(self):
        await hb.request_history("c1", "2026-07-01", requested_by="admin")
        self.fail.add("fbits")
        result = await hb.run_history_step("c1", budget_seconds=600)
        self.assertEqual(result["blocked"], {"fbits": "FBITS_RATE_LIMITED"})
        self.assertEqual([c for c in self.calls if c[0] == "fbits"], [("fbits", "2026-07-22", "2026-07-28")])
        self.assertTrue(any(c[0] == "google_ads" for c in self.calls))
        self.assertEqual(result["state"], "pending")
        self.assertIsNotNone(await hb.active_request("c1"))

    async def test_cancel(self):
        await hb.request_history("c1", "2026-07-01", requested_by="admin")
        await hb.cancel_history("c1")
        self.assertIsNone(await hb.active_request("c1"))
        result = await hb.run_history_step("c1")
        self.assertEqual(result["state"], "idle")
        self.assertEqual(self.calls, [])


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_fbits_block_reuses_sync_pipeline_and_lock(self):
        from services import fbits_connections, fbits_origin_probe

        locks = []

        @asynccontextmanager
        async def lock(**kwargs):
            locks.append(kwargs)
            yield "lock"

        ingest = AsyncMock(return_value={"orders": 12, "items": 30, "customers": 9})
        daily = AsyncMock(return_value=7)
        row = {"id": "conn-f", "metadata": {"order_statuses": [{"id": 1, "nome": "Pago"}], "revenue_status_ids": [1]}}
        with patch.object(fbits_connections, "load_fbits_connection", AsyncMock(return_value=row)), \
                patch.object(fbits_connections, "ingest_fbits_window", ingest), \
                patch.object(fbits_connections, "_refresh_daily_stats", daily), \
                patch.object(fbits_origin_probe, "_client_for", AsyncMock(return_value="client")), \
                patch.object(hb, "guarded_sync", lock):
            rows = await hb._run_fbits("c1", {"start": "2026-01-01", "end": "2026-01-07"})
        self.assertEqual(rows, 12)
        self.assertEqual(locks, [{"client_id": "c1", "provider": "fbits", "connection_id": "conn-f"}])
        kwargs = ingest.await_args.kwargs
        self.assertEqual(kwargs["date_filter"], "DataPedido")
        self.assertEqual(kwargs["start"].isoformat(), "2026-01-01T00:00:00-03:00")
        self.assertEqual(kwargs["end"].isoformat(), "2026-01-08T00:00:00-03:00")
        daily.assert_awaited_once()

    async def test_shopify_block_enforces_read_all_orders_check(self):
        from services import shopify_oauth

        sync = AsyncMock(return_value={"ok": True, "synced": {"orders_upserted": 40}})
        with patch.object(hb, "_shopify_connection", AsyncMock(return_value="conn-s")), \
                patch.object(shopify_oauth, "sync_shopify_connection", sync):
            rows = await hb._run_shopify("c1", {"start": "2026-01-01", "end": "2026-01-30"})
        self.assertEqual(rows, 40)
        kwargs = sync.await_args.kwargs
        self.assertEqual(kwargs["reconciliation_period"], ("2026-01-01", "2026-01-30"))
        self.assertEqual(kwargs["created_at_min"], "2026-01-01T00:00:00-03:00")
        self.assertEqual(kwargs["created_at_max"], "2026-01-30T23:59:59-03:00")


class HistoryRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduling_requires_platform_admin_only(self):
        guard = AsyncMock(side_effect=HTTPException(status_code=403, detail="no"))
        with patch.object(routes, "require_platform_admin", guard):
            with self.assertRaises(HTTPException):
                await routes.platform_history_request("c1", {"start": "2026-01-01"}, authorization="Bearer t")
        guard.assert_awaited_once_with("Bearer t", allow_agency_admin=False)

    async def test_run_needs_request_and_has_cooldown(self):
        routes._history_last_run.clear()
        tasks = []

        class Background:
            def add_task(self, fn, *args):
                tasks.append((fn, args))

        with patch.object(routes, "require_platform_admin", AsyncMock(return_value="u1")), \
                patch.object(hb, "active_request", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as raised:
                await routes.platform_history_run("c1", Background(), authorization="Bearer t")
        self.assertEqual(raised.exception.status_code, 404)
        with patch.object(routes, "require_platform_admin", AsyncMock(return_value="u1")), \
                patch.object(hb, "active_request", AsyncMock(return_value={"id": "r1"})):
            await routes.platform_history_run("c1", Background(), authorization="Bearer t")
            with self.assertRaises(HTTPException) as raised:
                await routes.platform_history_run("c1", Background(), authorization="Bearer t")
        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(len(tasks), 1)


if __name__ == "__main__":
    unittest.main()


class HistoryAllCompaniesTests(unittest.IsolatedAsyncioTestCase):
    async def test_schedules_every_active_company_and_isolates_failures(self):
        clients = [{"id": "roove", "name": "Roove", "status": "active"},
                   {"id": "curavino", "name": "Curavino", "status": "active"},
                   {"id": "velha", "name": "Velha", "status": "deleted"},
                   {"id": "quebrada", "name": "Quebrada", "status": "active"},
                   {"id": "completa", "name": "Completa", "status": "active"}]

        async def select(table, **kwargs):
            self.assertEqual(table, "clients")
            return clients

        async def request(client_id, start, *, requested_by):
            if client_id == "quebrada":
                raise RuntimeError("boom")
            if client_id == "completa":
                raise hb.HistoryBackfillError("x", code="HISTORY_NOTHING_TO_DO")
            return {"providers": [{"blocks_total": 4}, {"blocks_total": 3}]}

        active = AsyncMock(side_effect=lambda cid: {"id": "r"} if cid == "curavino" else None)
        with patch.object(hb, "sb_select", select), patch.object(hb, "request_history", request), \
                patch.object(hb, "active_request", active), patch.object(hb, "_today", lambda: TODAY):
            result = await hb.request_history_all("2026-01-01", requested_by="admin")
        status = {row["client_id"]: row["status"] for row in result["companies"]}
        self.assertEqual(status, {"roove": "scheduled", "curavino": "already_scheduled",
                                  "quebrada": "error", "completa": "nothing_to_do"})
        self.assertEqual(result["companies"][0]["blocks"], 7)

    async def test_all_requires_platform_admin_only(self):
        guard = AsyncMock(side_effect=HTTPException(status_code=403, detail="no"))
        with patch.object(routes, "require_platform_admin", guard):
            with self.assertRaises(HTTPException):
                await routes.platform_history_request_all({"start": "2026-01-01"}, authorization="Bearer t")
        guard.assert_awaited_once_with("Bearer t", allow_agency_admin=False)
