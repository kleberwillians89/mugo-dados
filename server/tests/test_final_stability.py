from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import connection_resolver, sync_locks
from services.audit_supabase import ReadOnlySupabase
from services.data_audit import assert_report_has_no_secrets, audit_existing_connections
from services.integration_errors import IntegrationError
from services.lock_audit import inspect_lock_infrastructure
from services.meta_connection_adapter import MetaConnectionAdapter
from services import provider_health
from services import job_runs


def connection(client_id: str, provider: str, suffix: str = "1", **overrides):
    return {
        "id": f"{client_id}-{provider}-{suffix}", "client_id": client_id,
        "provider": provider, "status": "connected", "disconnected_at": None,
        "encrypted_token": "encrypted", "metadata": {}, **overrides,
    }


class ConnectionResolutionScaleTests(unittest.IsolatedAsyncioTestCase):
    async def test_100_tenants_three_providers_remain_isolated(self):
        rows = [connection(f"tenant-{index}", provider) for index in range(100) for provider in ("meta", "ga4", "shopify")]

        async def select(_table, *, filters=None, **_kwargs):
            client_id = str((filters or {}).get("client_id", "")).removeprefix("eq.")
            provider = str((filters or {}).get("provider", "")).removeprefix("eq.")
            return [row for row in rows if row["client_id"] == client_id and row["provider"] == provider]

        resolved = await asyncio.gather(*[
            connection_resolver.resolve_generic_connection(
                client_id=f"tenant-{index}", provider=provider, require_token=False, select_fn=select,
            )
            for index in range(100) for provider in ("meta", "ga4", "shopify")
        ])
        self.assertEqual(len(resolved), 300)
        self.assertTrue(all(row["id"].startswith(row["client_id"] + "-") for row in resolved))

    async def test_ambiguous_and_disconnected_connections_are_never_selected(self):
        ambiguous = [connection("amalie", "ga4", "1"), connection("amalie", "ga4", "2")]
        with self.assertRaises(IntegrationError) as raised:
            await connection_resolver.resolve_generic_connection(
                client_id="amalie", provider="ga4", require_token=False,
                select_fn=AsyncMock(return_value=ambiguous),
            )
        self.assertEqual(raised.exception.code, "CONNECTION_AMBIGUOUS")
        disconnected = [connection("amalie", "google_ads", status="disconnected", disconnected_at="2026-01-01")]
        with self.assertRaises(IntegrationError) as raised:
            await connection_resolver.resolve_generic_connection(
                client_id="amalie", provider="google_ads", require_token=False,
                select_fn=AsyncMock(return_value=disconnected),
            )
        self.assertEqual(raised.exception.code, "CONNECTION_DISCONNECTED")


class DistributedLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_equal_sync_allows_only_one_worker(self):
        held: set[tuple[str, str]] = set()

        async def rpc(name, payload):
            key = (payload["p_client_id"], payload["p_job_name"])
            if name == "acquire_client_job_lock":
                if key in held:
                    return False
                held.add(key)
                return True
            held.discard(key)
            return True

        entered = asyncio.Event()
        release = asyncio.Event()

        async def worker():
            async with sync_locks.guarded_sync(
                client_id="amalie", provider="ga4", connection_id="ga4-1",
                period_start="2026-08-01", period_end="2026-08-04",
            ):
                entered.set()
                await release.wait()

        with patch.object(sync_locks, "sb_rpc", side_effect=rpc):
            first = asyncio.create_task(worker())
            await entered.wait()
            with self.assertRaises(IntegrationError) as raised:
                await worker()
            self.assertEqual(raised.exception.code, "SYNC_ALREADY_RUNNING")
            release.set()
            await first
            self.assertFalse(held)

    async def test_lock_is_released_when_sync_fails(self):
        calls = []

        async def rpc(name, _payload):
            calls.append(name)
            return True

        with patch.object(sync_locks, "sb_rpc", side_effect=rpc):
            with self.assertRaisesRegex(RuntimeError, "provider failed"):
                async with sync_locks.guarded_sync(
                    client_id="amalie", provider="ga4", connection_id="ga4-1",
                ):
                    raise RuntimeError("provider failed")
        self.assertEqual(calls, ["acquire_client_job_lock", "release_client_job_lock"])


class MetaDriftAndAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_meta_drift_is_reported_without_silent_repair(self):
        async def select(table, **_kwargs):
            if table == "integration_connections":
                return [connection("amalie", "meta", metadata={"selected_instagram_id": "ig-1"})]
            return [{"id": "projection-1", "client_id": "amalie", "platform": "instagram", "connection_type": "organic", "status": "active", "is_active": True, "ig_user_id": "ig-other"}]

        adapter = MetaConnectionAdapter()
        with patch("services.meta_connection_adapter.sb_select", side_effect=select):
            result = await adapter.detect_drift("amalie")
        self.assertTrue(result["drift_detected"])
        self.assertIn("selected_instagram_id_mismatch", {item["reason"] for item in result["issues"]})

    async def test_dry_run_redacts_tokens_and_classifies_duplicates(self):
        async def select(table, **_kwargs):
            if table == "integration_connections":
                return [connection("amalie", "ga4"), connection("amalie", "ga4", "2")]
            return []

        report = await audit_existing_connections(select)
        self.assertGreater(report["summary"]["critical"], 0)
        self.assertNotIn("encrypted_token", str(report))
        self.assertTrue(report["dry_run"])
        self.assertTrue(report["read_only"])
        assert_report_has_no_secrets(report)
        required = {"client_id", "provider", "connection_id", "safe_reason", "suggested_action"}
        self.assertTrue(all(required.issubset(issue) for issue in report["issues"]))

    def test_audit_transport_rejects_non_get_method(self):
        with patch.dict("os.environ", {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_AUDIT_KEY": "x" * 32}):
            client = ReadOnlySupabase()
        client.request_log.append({"method": "POST", "resource": "integration_connections"})
        with self.assertRaises(RuntimeError) as raised:
            client.assert_read_only()
        self.assertIn("AUDIT_WRITE_METHOD_BLOCKED", str(raised.exception))

    def test_audit_client_exposes_no_write_api(self):
        self.assertFalse(hasattr(ReadOnlySupabase, "insert"))
        self.assertFalse(hasattr(ReadOnlySupabase, "update"))
        self.assertFalse(hasattr(ReadOnlySupabase, "delete"))

    async def test_audit_detects_meta_drift_missing_refresh_and_orphan_reference(self):
        async def select(table, **_kwargs):
            if table == "integration_connections":
                return [
                    connection("amalie", "meta", metadata={"selected_instagram_id": "ig-expected"}),
                    connection("amalie", "ga4", encrypted_token="", encrypted_refresh_token=""),
                ]
            if table == "meta_connections":
                return [{
                    "id": "meta-projection", "client_id": "amalie", "platform": "instagram",
                    "connection_type": "organic", "status": "active", "is_active": True,
                    "ig_user_id": "ig-other", "business_id": "page-1",
                }]
            if table == "sync_checkpoints":
                return [{"client_id": "amalie", "connection_id": "missing-connection"}]
            return []

        report = await audit_existing_connections(select)
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("META_SELECTED_INSTAGRAM_ID_DRIFT", codes)
        self.assertIn("GA4_REFRESH_TOKEN_MISSING", codes)
        self.assertIn("CONNECTION_REFERENCE_NOT_FOUND", codes)


class LockInfrastructureAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_lock_audit_uses_only_get_and_confirms_repository_contract(self):
        class Client:
            def __init__(self):
                self.methods = []

            async def openapi(self):
                self.methods.append("GET")
                return {"paths": {path: {} for path in (
                    "/cron_locks", "/cron_job_runs", "/rpc/acquire_client_job_lock", "/rpc/release_client_job_lock",
                )}}

            async def select(self, *_args, **_kwargs):
                self.methods.append("GET")
                return []

            def assert_read_only(self):
                if set(self.methods) - {"GET"}:
                    raise RuntimeError("write")

        client = Client()
        result = await inspect_lock_infrastructure(client, SERVER_DIR.parent / "supabase" / "migrations")
        self.assertTrue(result["ok"])
        self.assertTrue(result["repository_contract"]["cron_locks_unique_constraint"])
        self.assertTrue(result["repository_contract"]["lock_expiration"])
        self.assertTrue(result["rpc_execution_not_invoked"])

    def test_lock_sql_audit_contains_no_write_statement(self):
        source = (SERVER_DIR / "sql" / "audit_locks_readonly.sql").read_text(encoding="utf-8").lower()
        for statement in ("insert into", "update public", "delete from", "alter table", "create table", "drop table"):
            self.assertNotIn(statement, source)


class ProviderHealthContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_contains_every_operational_field(self):
        async def select(table, **kwargs):
            if table == "integration_connections":
                return [{
                    "id": "ga4-1", "client_id": "amalie", "provider": "ga4",
                    "status": "connected", "encrypted_token": "opaque",
                    "token_expires_at": "2099-01-01T00:00:00Z",
                    "metadata": {"ga4_property_id": "123"},
                }]
            if table == "cron_job_runs" and (kwargs.get("filters") or {}).get("status") == "eq.running":
                return []
            if table == "cron_job_runs":
                return [{
                    "connection_id": "ga4-1", "status": "success",
                    "started_at": "2026-08-04T12:00:00Z", "finished_at": "2026-08-04T12:01:00Z",
                    "payload_json": {"request_id": "req-1"},
                }]
            return []

        with patch.object(provider_health, "sb_select", side_effect=select):
            response = await provider_health.client_provider_health("amalie", "ga4")
        item = response["connections"][0]
        required = {
            "client_id", "provider", "connection_id", "status", "last_sync_at",
            "last_success_at", "last_error_code", "request_id", "stale",
            "token_status", "asset_status", "retryable", "drift_detected", "sync_running",
        }
        self.assertTrue(required.issubset(item))

    async def test_sync_run_provider_filter_uses_serialized_provider(self):
        rows = [
            {"id": "1", "job_name": "ga4_sync_manual", "status": "success", "payload_json": {}, "rows_upserted": 1},
            {"id": "2", "job_name": "instagram_organic_sync", "status": "success", "payload_json": {}, "rows_upserted": 1},
        ]
        with patch.object(job_runs, "sb_select", AsyncMock(return_value=rows)):
            response = await job_runs.list_job_runs(provider="ga4", limit=20)
        self.assertEqual(response["total"], 1)
        self.assertEqual(response["runs"][0]["provider"], "ga4")


if __name__ == "__main__":
    unittest.main()
