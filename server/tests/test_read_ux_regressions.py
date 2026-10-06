import asyncio
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import meta_live_trace, request_performance, fbits_official_kpis as official

class ReadUXRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_meta_sources_are_scoped_and_logs_have_no_sensitive_arguments(self):
        output = io.StringIO()
        async def call(source):
            with meta_live_trace.live_scope(source, "fixture-job"):
                await asyncio.sleep(0)
                meta_live_trace.trace_live_call("media_insights")
        sources = ["navigation", "manual_refresh", "scheduled_sync", "reconciliation", "backfill"]
        with redirect_stdout(output):
            await asyncio.gather(*(call(source) for source in sources))
        entries = [json.loads(line.split(" ", 1)[1]) for line in output.getvalue().splitlines()]
        self.assertEqual({entry["trigger_source"] for entry in entries}, set(sources))
        for entry in entries:
            self.assertEqual(set(entry), {"trigger_source", "job_run_id", "request_id", "operation"})

    async def test_manual_request_origin_has_request_id_and_unknown_is_not_assigned_to_cron(self):
        state, token = request_performance.begin("fixture-request")
        state.scope.update(method="POST", endpoint="/api/clients/fixture/data-refresh/meta")
        output = io.StringIO()
        try:
            with redirect_stdout(output): meta_live_trace.trace_live_call("media_comments")
        finally: request_performance.end(token)
        entry = json.loads(output.getvalue().split(" ", 1)[1])
        self.assertEqual(entry["trigger_source"], "manual_refresh")
        self.assertEqual(entry["request_id"], "fixture-request")
        state, token = request_performance.begin("fixture-alias")
        output = io.StringIO()
        try:
            state.scope.update(method="POST", endpoint="/api/ig/sync")
            with redirect_stdout(output): meta_live_trace.trace_live_call("media_comments")
        finally: request_performance.end(token)
        self.assertEqual(json.loads(output.getvalue().split(" ", 1)[1])["trigger_source"], "manual_refresh")
        output = io.StringIO()
        with redirect_stdout(output): meta_live_trace.trace_live_call("media_comments")
        self.assertEqual(json.loads(output.getvalue().split(" ", 1)[1])["trigger_source"], "unknown")

    async def test_fbits_read_uses_persisted_official_numbers_without_provider(self):
        key = "2026-10-01:2026-10-05:2026-09-26:2026-09-30"
        value = {"current": {"receita_oficial": 100, "pedidos": 2, "ticket_medio": 50}, "previous": None}
        row = {"id": "conn", "metadata": {"official_kpi_snapshots": {key: {"connection_id": "conn", "value": value}}}}
        with patch.object(official, "load_fbits_connection", AsyncMock(return_value=row)), patch.object(official, "client_factory", side_effect=AssertionError("no provider on read")), patch.object(official, "get_connection", AsyncMock(side_effect=AssertionError("no secret on read"))):
            result = await official.read_persisted_official_kpis(client_id="tenant", start="2026-10-01", end="2026-10-05", previous_start="2026-09-26", previous_end="2026-09-30")
        self.assertEqual(result, value)

    async def test_fbits_missing_snapshot_does_not_call_provider_or_invent_official_kpis(self):
        with patch.object(official, "load_fbits_connection", AsyncMock(return_value={"id": "conn", "metadata": {}})), patch.object(official, "client_factory", side_effect=AssertionError("no live fallback")):
            with self.assertRaises(official.OfficialKpisUnavailable) as error:
                await official.read_persisted_official_kpis(client_id="tenant", start="a", end="b", previous_start="c", previous_end="d")
        self.assertEqual(error.exception.code, "FBITS_OFFICIAL_SNAPSHOT_MISSING")

    async def test_explicit_fbits_refresh_persists_only_normalized_kpis_and_preserves_metadata(self):
        row = {"id": "conn", "metadata": {"revenue_status_ids": [1]}}
        value = {"current": {"receita_oficial": 100, "pedidos": 2, "ticket_medio": 50}, "previous": None}
        write = AsyncMock(return_value=[row])
        with patch.object(official, "load_fbits_connection", AsyncMock(return_value=row)), patch.object(official, "fetch_official_kpis", AsyncMock(return_value=value)), patch.object(official, "sb_update", write):
            await official.refresh_persisted_official_kpis("tenant", "2026-10-01", "2026-10-05")
        kwargs = write.await_args.kwargs
        self.assertEqual(kwargs["filters"], {"client_id": "eq.tenant", "id": "eq.conn"})
        self.assertEqual(kwargs["patch"]["metadata"]["revenue_status_ids"], [1])
        self.assertEqual(next(iter(kwargs["patch"]["metadata"]["official_kpi_snapshots"].values()))["value"], value)
