import asyncio
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import auth, ig_supabase, request_performance as performance, tenant
from services import platform_admin
from routes import integrations
from fastapi import HTTPException


class RequestPerformanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_offline_summary_reconstructs_waterfall_and_compares_concurrency_without_raw_payload(self):
        from scripts.summarize_request_performance import summarize
        entries = [
            '[performance][request] ' + json.dumps({"request_id": "later", "started_at": "2026-10-06T12:00:01Z", "endpoint": "/api/media", "duration_ms": 100, "raw_payload": "private@example.test"}),
            '[performance][request] ' + json.dumps({"request_id": "first", "started_at": "2026-10-06T12:00:00Z", "endpoint": "/api/comments", "duration_ms": 200}),
            '[performance][dependency] ' + json.dumps({"dependency": "supabase_rest", "operation": "GET /ig_media", "phase": "data_media", "inflight_at_start": 1, "duration_ms": 10}),
            '[performance][dependency] ' + json.dumps({"dependency": "supabase_rest", "operation": "GET /ig_media", "phase": "data_media", "inflight_at_start": 3, "duration_ms": 20}),
        ]
        result = summarize("\n".join(entries))
        self.assertEqual([row["request_id"] for row in result["waterfall"]], ["first", "later"])
        self.assertNotIn("private@example.test", json.dumps(result))
        comparison = result["latency_by_concurrency"][0]
        self.assertEqual(comparison["low"]["samples"], 1)
        self.assertEqual(comparison["high"]["samples"], 1)

    async def test_same_bearer_is_validated_once_per_request_and_again_next_request(self):
        http = MagicMock()
        http.__aenter__ = AsyncMock(return_value=http)
        http.__aexit__ = AsyncMock(return_value=None)
        http.get = AsyncMock(return_value=MagicMock(status_code=200, json=lambda: {"id": "fixture-user"}))
        env = {"SUPABASE_URL": "https://fixture.invalid", "SUPABASE_ANON_KEY": "x" * 30}
        with patch.object(auth, "_env", side_effect=lambda name: env.get(name, "")), patch.object(auth.httpx, "AsyncClient", return_value=http), redirect_stdout(io.StringIO()):
            for count in (1, 2):
                state, token = performance.begin("fixture-request")
                try:
                    result = await asyncio.gather(auth.get_user_id_from_bearer("Bearer fixture-only"), auth.get_user_id_from_bearer("Bearer fixture-only"))
                    self.assertEqual(result, ["fixture-user", "fixture-user"])
                    self.assertEqual(state.round_trips, 1)
                finally:
                    performance.end(token)
                self.assertEqual(http.get.await_count, count)

    async def test_role_reads_do_not_hydrate_companies_and_are_memoized_only_in_request(self):
        roles = [{"client_id": str(i), "role": "viewer"} for i in range(20)]
        query = AsyncMock(return_value=roles)
        with patch.object(ig_supabase, "sb_select", query), patch.object(ig_supabase, "sb_get_one", AsyncMock(side_effect=AssertionError("no hydration"))):
            for count in (1, 2):
                _, token = performance.begin("fixture-request")
                try:
                    self.assertEqual(await ig_supabase.sb_get_client_membership_roles("user"), roles)
                    self.assertEqual(await ig_supabase.sb_get_client_membership_roles("user"), roles)
                finally:
                    performance.end(token)
                self.assertEqual(query.await_count, count)

    async def test_membership_listing_still_hydrates_company_for_presentation(self):
        with patch.object(ig_supabase, "sb_select", AsyncMock(return_value=[{"client_id": "a", "role": "viewer"}])), patch.object(ig_supabase, "sb_get_one", AsyncMock(return_value={"id": "a", "name": "fixture-company"})):
            rows = await ig_supabase.sb_get_client_memberships("user")
        self.assertEqual(rows[0]["clients"]["name"], "fixture-company")

    async def test_integration_denial_runs_no_business_loader(self):
        loader = AsyncMock()
        with patch.object(tenant, "get_user_id_from_bearer", AsyncMock(return_value="viewer")), patch.object(platform_admin, "is_platform_admin", AsyncMock(return_value=False)), patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=[{"client_id": "a", "role": "viewer"}])), patch.object(tenant, "sb_get_client_id_for_user", AsyncMock(return_value="a")), patch.object(integrations, "get_client_connections", loader):
            with self.assertRaises(HTTPException) as raised:
                await integrations.get_client_integrations("a", None, "Bearer fixture-only")
        self.assertEqual(raised.exception.status_code, 403)
        loader.assert_not_awaited()

    async def test_memo_keys_keep_different_tenants_separate(self):
        calls = []
        @performance.measured("fixture", memo=True)
        async def read(tenant_id):
            calls.append(tenant_id)
            return tenant_id
        _, token = performance.begin("request")
        try:
            self.assertEqual(await read("a"), "a")
            self.assertEqual(await read("b"), "b")
            self.assertEqual(await read("a"), "a")
        finally:
            performance.end(token)
        self.assertEqual(calls, ["a", "b"])

    async def test_failed_auth_is_not_reused_as_success(self):
        calls = 0
        @performance.measured("auth", memo=True)
        async def validate():
            nonlocal calls
            calls += 1
            raise HTTPException(401, "denied")
        _, token = performance.begin("request")
        try:
            for _ in range(2):
                with self.assertRaises(HTTPException):
                    await validate()
        finally:
            performance.end(token)
        self.assertEqual(calls, 2)

    async def test_safe_diagnostic_has_request_phase_round_trips_and_concurrency(self):
        output = io.StringIO()
        @performance.measured("auth", memo=True)
        async def validate(secret):
            first = performance.transport_started()
            second = performance.transport_started()
            performance.transport_done(second, dependency="supabase_auth", operation="user", status="200")
            performance.transport_done(first, dependency="supabase_auth", operation="user", status="200")
            return "fixture-user"
        state, token = performance.begin("fixture-request-id")
        try:
            with redirect_stdout(output):
                await validate("fixture-secret private@example.test")
                performance.summary(state, 200)
        finally:
            performance.end(token)
        log = output.getvalue()
        self.assertNotIn("fixture-secret", log)
        self.assertNotIn("private@example.test", log)
        self.assertNotIn("fixture-user", log)
        entries = [json.loads(line.split(" ", 1)[1]) for line in log.splitlines()]
        self.assertEqual(entries[-1]["supabase_round_trips"], 2)
        self.assertEqual(entries[-1]["phases"]["auth"]["calls"], 1)
        self.assertEqual(entries[0]["inflight_at_start"], 2)
        self.assertEqual(entries[0]["request_id"], "fixture-request-id")
