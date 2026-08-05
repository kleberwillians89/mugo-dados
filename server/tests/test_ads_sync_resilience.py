from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import ads_sync
from services.sync_locks import build_sync_lock_name


def _paid_connection(connection_id: str = "conn-1") -> dict:
    return {
        "id": connection_id,
        "_resolved_source": "explicit",
        "ad_account_id": "act_123",
        "ad_account_name": "Conta de Teste",
    }


def _empty_upsert() -> dict:
    return {"upserted": 0, "skipped": False}


def _empty_readback() -> dict:
    empty = {"count": 0, "mode": "unknown"}
    return {
        "ad_account_daily_stats": dict(empty),
        "campaign_daily_stats": dict(empty),
        "ad_daily_stats": dict(empty),
        "promoted_post_daily_stats": dict(empty),
    }


class _BaseAdsSyncTest(unittest.IsolatedAsyncioTestCase):
    """Isola sync_ads_for_client_period de todas as dependências externas
    (Supabase, Graph API) para exercitar apenas a lógica de finalização,
    lock e timeout adicionada nesta etapa."""

    def setUp(self):
        self.patchers = []
        self.finish_job_run_calls = []
        self.release_lock_calls = []
        self.mark_error_calls = []

        async def fake_start_job_run(**_kwargs):
            return {"id": "job-run-1"}

        async def fake_finish_job_run(job_run_id, **kwargs):
            self.finish_job_run_calls.append({"job_run_id": job_run_id, **kwargs})
            return {"id": job_run_id}

        async def fake_acquire_sync_lock(_client_id, _lock_name, _ttl):
            return True

        async def fake_release_sync_lock(client_id, lock_name):
            self.release_lock_calls.append((client_id, lock_name))

        async def fake_mark_connection_sync_error(connection_id, message, **kwargs):
            self.mark_error_calls.append((connection_id, message, kwargs))

        self._install(ads_sync, "start_job_run", fake_start_job_run)
        self._install(ads_sync, "finish_job_run", fake_finish_job_run)
        self._install(ads_sync, "acquire_sync_lock", fake_acquire_sync_lock)
        self._install(ads_sync, "release_sync_lock", fake_release_sync_lock)
        self._install(ads_sync, "mark_connection_sync_error", fake_mark_connection_sync_error)
        self._install(ads_sync, "mark_connection_sync_no_data", AsyncMock())
        self._install(ads_sync, "mark_connection_sync_partial", AsyncMock())
        self._install(ads_sync, "mark_connection_sync_success", AsyncMock())
        self._install(ads_sync, "_pick_paid_connection", AsyncMock(return_value=_paid_connection()))
        self._install(ads_sync, "ensure_valid_meta_token", AsyncMock(return_value="token-abc"))
        self._install(ads_sync, "_fetch_boosted_insight_rows", AsyncMock(return_value=[]))
        self._install(ads_sync, "_upsert_ad_account_daily_stats", AsyncMock(return_value=_empty_upsert()))
        self._install(ads_sync, "_upsert_campaign_daily_stats", AsyncMock(return_value=_empty_upsert()))
        self._install(ads_sync, "_upsert_ad_daily_stats", AsyncMock(return_value=_empty_upsert()))
        self._install(ads_sync, "_upsert_promoted_post_daily_stats", AsyncMock(return_value=_empty_upsert()))
        self._install(ads_sync, "_readback_persisted_rows", AsyncMock(return_value=_empty_readback()))
        ads_sync._RECENT_SYNC_KEYS.clear()

    def _install(self, target_module, name, replacement):
        patcher = patch.object(target_module, name, replacement)
        patcher.start()
        self.patchers.append(patcher)

    def tearDown(self):
        for patcher in self.patchers:
            patcher.stop()
        ads_sync._RECENT_SYNC_KEYS.clear()


class CancellationTests(_BaseAdsSyncTest):
    async def test_cancelled_during_graph_call_finishes_job_marks_error_and_releases_lock(self):
        async def cancelling_fetch(**_kwargs):
            raise asyncio.CancelledError()

        self._install(ads_sync, "fetch_ad_account_insights", cancelling_fetch)

        with self.assertRaises(asyncio.CancelledError):
            await ads_sync.sync_ads_for_client_period(
                client_id="amalie", since="2026-07-01", until="2026-07-31",
                connection_id="conn-1",
            )

        self.assertEqual(len(self.finish_job_run_calls), 1)
        self.assertEqual(self.finish_job_run_calls[0]["status"], "error")
        self.assertIsNotNone(self.finish_job_run_calls[0].get("error"))
        self.assertEqual(len(self.mark_error_calls), 1)
        self.assertEqual(len(self.release_lock_calls), 1)


class TimeoutTests(_BaseAdsSyncTest):
    async def test_timeout_finishes_job_as_error_and_releases_lock(self):
        async def slow_fetch(**_kwargs):
            await asyncio.sleep(0.2)
            return []

        self._install(ads_sync, "fetch_ad_account_insights", slow_fetch)

        with patch.object(ads_sync, "_ADS_SYNC_TOTAL_TIMEOUT_SECONDS", 0.01):
            with self.assertRaises((asyncio.TimeoutError, TimeoutError)):
                await ads_sync.sync_ads_for_client_period(
                    client_id="amalie", since="2026-07-01", until="2026-07-31",
                    connection_id="conn-1",
                )

        self.assertEqual(len(self.finish_job_run_calls), 1)
        self.assertEqual(self.finish_job_run_calls[0]["status"], "error")
        self.assertTrue(self.finish_job_run_calls[0]["payload_json"].get("timeout"))
        self.assertEqual(len(self.release_lock_calls), 1)


class NoDataPathTests(_BaseAdsSyncTest):
    async def test_no_account_rows_finishes_job_as_skipped_and_releases_lock(self):
        self._install(ads_sync, "fetch_ad_account_insights", AsyncMock(return_value=[]))

        result = await ads_sync.sync_ads_for_client_period(
            client_id="amalie", since="2026-07-01", until="2026-07-31",
            connection_id="conn-1",
        )

        self.assertEqual(result["sync_outcome"], "no_data")
        self.assertEqual(len(self.finish_job_run_calls), 1)
        self.assertEqual(self.finish_job_run_calls[0]["status"], "skipped")
        self.assertEqual(len(self.release_lock_calls), 1)


class LockIdentityTests(unittest.TestCase):
    def test_lock_name_ignores_since_and_until(self):
        with_period = build_sync_lock_name("meta_ads", "conn-1", "2026-07-01", "2026-07-31")
        without_period = build_sync_lock_name("meta_ads", "conn-1")
        self.assertEqual(without_period, "sync:meta_ads:conn-1")
        self.assertNotEqual(with_period, without_period)


class LockAcquisitionUsesConnectionOnlyIdentityTests(_BaseAdsSyncTest):
    async def test_two_different_periods_same_connection_use_identical_lock_name(self):
        captured_lock_names = []

        async def capturing_acquire(_client_id, lock_name, _ttl):
            captured_lock_names.append(lock_name)
            return True

        self._install(ads_sync, "acquire_sync_lock", capturing_acquire)
        self._install(ads_sync, "fetch_ad_account_insights", AsyncMock(return_value=[]))

        await ads_sync.sync_ads_for_client_period(
            client_id="amalie", since="2026-07-01", until="2026-07-31",
            connection_id="conn-1",
        )
        await ads_sync.sync_ads_for_client_period(
            client_id="amalie", since="2026-08-01", until="2026-08-31",
            connection_id="conn-1",
        )

        self.assertEqual(len(captured_lock_names), 2)
        self.assertEqual(captured_lock_names[0], captured_lock_names[1])
        self.assertNotIn("2026-07-01", captured_lock_names[0])
        self.assertNotIn("2026-08-01", captured_lock_names[1])


class PageCapTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_ad_account_insights_stops_at_max_pages(self):
        from services import ads_meta

        call_count = {"n": 0}

        async def infinite_pages(_url, params=None, request_context=None):
            call_count["n"] += 1
            return {
                "data": [{"date_start": "2026-07-01"}],
                "paging": {"next": "https://graph.example/next-page"},
            }

        with patch.object(ads_meta, "_meta_get", infinite_pages):
            rows = await ads_meta.fetch_ad_account_insights(
                ad_account_id="act_123",
                access_token="token",
                since="2026-07-01",
                until="2026-07-31",
                level="ad",
            )

        self.assertEqual(call_count["n"], ads_meta._MAX_INSIGHTS_PAGES)
        self.assertEqual(len(rows), ads_meta._MAX_INSIGHTS_PAGES)


if __name__ == "__main__":
    unittest.main()
