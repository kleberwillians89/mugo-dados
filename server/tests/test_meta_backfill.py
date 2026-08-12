from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from server.services import meta_backfill


class MetaBackfillSlicesTests(unittest.TestCase):
    def test_range_is_split_into_sequential_inclusive_seven_day_slices(self):
        self.assertEqual(meta_backfill.build_slices("2026-01-01", "2026-01-22"), [
            {"since": "2026-01-01", "until": "2026-01-07"},
            {"since": "2026-01-08", "until": "2026-01-14"},
            {"since": "2026-01-15", "until": "2026-01-21"},
            {"since": "2026-01-22", "until": "2026-01-22"},
        ])

    def test_invalid_range_is_rejected(self):
        with self.assertRaises(ValueError):
            meta_backfill.build_slices("2026-02-01", "2026-01-01")

    def test_retry_classifier_covers_gateway_timeout_rate_limit_and_lock(self):
        for value in (RuntimeError("HTTP 502"), RuntimeError("timeout"), RuntimeError("rate limit"), RuntimeError("already running")):
            self.assertTrue(meta_backfill._retryable(value))
        self.assertFalse(meta_backfill._retryable(RuntimeError("invalid token")))


class MetaBackfillReconciliationTests(unittest.IsolatedAsyncioTestCase):
    async def test_account_is_canonical_and_detail_is_only_reconciled(self):
        rows = {
            "ad_account_daily_stats": [{"stat_date": "2026-01-01", "spend": 10, "conversions": 2, "revenue": 30, "clicks": 5, "impressions": 100}],
            "campaign_daily_stats": [{"stat_date": "2026-01-01", "spend": 10, "conversions": 2, "revenue": 30, "clicks": 5, "impressions": 100}],
            "ad_daily_stats": [{"stat_date": "2026-01-01", "spend": 10, "conversions": 2, "revenue": 30, "clicks": 5, "impressions": 100}],
        }
        with patch.object(meta_backfill, "sb_query", AsyncMock(side_effect=lambda table, _query: rows[table])):
            result = await meta_backfill.reconcile_slice(client_id="amalie", connection_id="c1", since="2026-01-01", until="2026-01-07")
        self.assertTrue(result["valid"])
        self.assertEqual(result["totals"]["account"]["spend"], 10)
        self.assertEqual(result["first_date"], "2026-01-01")

    async def test_additive_mismatch_needs_review_but_reach_is_not_compared(self):
        rows = {
            "ad_account_daily_stats": [{"stat_date": "2026-01-01", "spend": 10, "conversions": 2, "revenue": 30, "clicks": 5, "impressions": 100}],
            "campaign_daily_stats": [{"stat_date": "2026-01-01", "spend": 11, "conversions": 2, "revenue": 30, "clicks": 5, "impressions": 100}],
            "ad_daily_stats": [{"stat_date": "2026-01-01", "spend": 10, "conversions": 2, "revenue": 30, "clicks": 5, "impressions": 100}],
        }
        with patch.object(meta_backfill, "sb_query", AsyncMock(side_effect=lambda table, _query: rows[table])):
            result = await meta_backfill.reconcile_slice(client_id="amalie", connection_id="c1", since="2026-01-01", until="2026-01-07")
        self.assertTrue(result["needs_review"])
        self.assertEqual(result["mismatches"], ["spend"])


class MetaBackfillWorkerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.slice = {"id": "s1", "backfill_job_id": "j1", "slice_since": "2026-01-01", "slice_until": "2026-01-07", "attempts": 1}
        self.job = {"id": "j1", "client_id": "amalie", "connection_id": "c1"}

    async def _run(self, *, sync=None, reconciliation=None):
        sync = sync or {"ok": True, "rows_inserted": 21, "sync_outcome": "success"}
        reconciliation = reconciliation or {"valid": True, "needs_review": False, "mismatches": [], "first_date": "2026-01-01", "last_date": "2026-01-07", "rows": {"account": 7, "campaign": 7, "ad": 7}}
        selects = AsyncMock(side_effect=[[self.job], []])
        with patch.object(meta_backfill, "sb_rpc", AsyncMock(return_value=[self.slice])), \
             patch.object(meta_backfill, "sb_select", selects), \
             patch.object(meta_backfill, "sync_ads_for_client_period", AsyncMock(return_value=sync)) as sync_mock, \
             patch.object(meta_backfill, "reconcile_slice", AsyncMock(return_value=reconciliation)), \
             patch.object(meta_backfill, "refresh_dashboard_read_model", AsyncMock()) as refresh, \
             patch.object(meta_backfill, "sb_update", AsyncMock()) as update, \
             patch.object(meta_backfill, "_update_job", AsyncMock()):
            result = await meta_backfill.process_next_slice()
        return result, sync_mock, refresh, update

    async def test_success_projects_only_after_valid_reconciliation(self):
        result, sync, refresh, update = await self._run()
        self.assertTrue(result["processed"])
        sync.assert_awaited_once()
        self.assertFalse(sync.await_args.kwargs["refresh_read_model"])
        refresh.assert_awaited_once()
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "success")

    async def test_duplicate_is_skipped_and_does_not_stop_parent(self):
        _, _, refresh, update = await self._run(sync={"ok": False, "reason": "duplicate", "rows_inserted": 0})
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "skipped")
        refresh.assert_awaited_once()

    async def test_gateway_failure_checks_persistence_before_retrying(self):
        selects = AsyncMock(return_value=[self.job])
        valid = {"valid": True, "needs_review": False, "mismatches": [], "first_date": "2026-01-01", "last_date": "2026-01-07"}
        with patch.object(meta_backfill, "sb_rpc", AsyncMock(return_value=[self.slice])), \
             patch.object(meta_backfill, "sb_select", selects), \
             patch.object(meta_backfill, "sync_ads_for_client_period", AsyncMock(side_effect=RuntimeError("HTTP 502"))), \
             patch.object(meta_backfill, "reconcile_slice", AsyncMock(return_value=valid)), \
             patch.object(meta_backfill, "refresh_dashboard_read_model", AsyncMock()) as refresh, \
             patch.object(meta_backfill, "sb_update", AsyncMock()) as update, \
             patch.object(meta_backfill, "_update_job", AsyncMock()):
            await meta_backfill.process_next_slice()
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "success")
        refresh.assert_awaited_once()

    async def test_transient_failure_waits_with_bounded_retry(self):
        invalid = {"valid": False, "needs_review": False, "mismatches": [], "first_date": None, "last_date": None}
        with patch.object(meta_backfill, "sb_rpc", AsyncMock(return_value=[self.slice])), \
             patch.object(meta_backfill, "sb_select", AsyncMock(return_value=[self.job])), \
             patch.object(meta_backfill, "sync_ads_for_client_period", AsyncMock(side_effect=TimeoutError("timeout"))), \
             patch.object(meta_backfill, "reconcile_slice", AsyncMock(return_value=invalid)), \
             patch.object(meta_backfill, "sb_update", AsyncMock()) as update, \
             patch.object(meta_backfill, "_update_job", AsyncMock()):
            await meta_backfill.process_next_slice()
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "waiting")

    async def test_mismatch_is_terminal_and_read_model_is_not_projected(self):
        reconciliation = {"valid": False, "needs_review": True, "mismatches": ["spend"], "first_date": "2026-01-01", "last_date": "2026-01-07"}
        _, _, refresh, update = await self._run(reconciliation=reconciliation)
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "needs_review")
        refresh.assert_not_awaited()

    async def test_projection_failure_does_not_mark_slice_success(self):
        valid = {"valid": True, "needs_review": False, "mismatches": [], "first_date": "2026-01-01", "last_date": "2026-01-07"}
        with patch.object(meta_backfill, "sb_rpc", AsyncMock(return_value=[self.slice])), \
             patch.object(meta_backfill, "sb_select", AsyncMock(return_value=[self.job])), \
             patch.object(meta_backfill, "sync_ads_for_client_period", AsyncMock(return_value={"ok": True, "rows_inserted": 21})), \
             patch.object(meta_backfill, "reconcile_slice", AsyncMock(return_value=valid)), \
             patch.object(meta_backfill, "refresh_dashboard_read_model", AsyncMock(side_effect=RuntimeError("rpc unavailable"))), \
             patch.object(meta_backfill, "sb_update", AsyncMock()) as update, \
             patch.object(meta_backfill, "_update_job", AsyncMock()):
            await meta_backfill.process_next_slice()
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "waiting")
