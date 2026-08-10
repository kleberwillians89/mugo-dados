from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
ROOT = SERVER_DIR.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import cron_jobs  # noqa: E402


class RenderCronScheduleTests(unittest.TestCase):
    def test_provider_jobs_are_wired_to_real_render_schedules(self):
        blueprint = (ROOT / "render.yaml").read_text()
        contracts = (
            ("mugo-dados-shopify-incremental", 'schedule: "*/30 * * * *"', "shopify-reconcile --fallback-days 30"),
            ("mugo-dados-shopify-historical-reconciliation", 'schedule: "25 7 * * *"', "shopify-historical-reconcile --days 14"),
            ("mugo-dados-meta-ads-sync-hourly", 'schedule: "5 * * * *"', "ads-sync-hourly --days 7"),
            ("mugo-dados-instagram-organic-sync", 'schedule: "10 6,12,18,23 * * *"', "organic-sync --limit 60"),
            ("mugo-dados-ga4-sync", 'schedule: "20 */3 * * *"', "ga4-sync-all --days 3"),
            ("mugo-dados-google-ads-sync", 'schedule: "35 */3 * * *"', "google-ads-sync --days 7"),
            ("mugo-dados-shopify-wide-reconciliation", 'schedule: "40 8 * * 0"', "shopify-historical-reconcile --days 90"),
            ("mugo-dados-meta-ads-wide-reconciliation", 'schedule: "45 2 * * *"', "ads-sync-hourly --days 30"),
            ("mugo-dados-ga4-wide-reconciliation", 'schedule: "15 3 * * *"', "ga4-sync-all --days 30"),
            ("mugo-dados-google-ads-wide-reconciliation", 'schedule: "45 3 * * *"', "google-ads-sync --days 30"),
            ("mugo-dados-instagram-wide-reconciliation", 'schedule: "20 9 * * 0"', "organic-sync --limit 250 --skip-thumbnails"),
        )
        for name, schedule, command in contracts:
            with self.subTest(name=name):
                block = blueprint.split(f"name: {name}", 1)[1].split("\n  - type:", 1)[0]
                self.assertIn(schedule, block)
                self.assertIn(command, block)


class MultiTenantGoogleCronTests(unittest.IsolatedAsyncioTestCase):
    async def test_ga4_discovers_and_syncs_every_active_configured_connection(self):
        conns = [
            {"id": "ga-a", "client_id": "amalie", "metadata": {"ga4_property_id": "1"}},
            {"id": "ga-b", "client_id": "roove", "metadata": {"ga4_property_id": "2"}},
        ]
        with (
            patch.object(cron_jobs, "sb_select", AsyncMock(return_value=conns)),
            patch("services.google_oauth.get_google_access_token", AsyncMock(return_value="token")),
            patch("services.ga4_sync.sync_ga4_for_period", AsyncMock(return_value={"rows_upserted": {"total": 1}})) as sync,
        ):
            result = await cron_jobs.run_ga4_sync_all(window_days=3)
        self.assertEqual(sync.await_count, 2)
        self.assertEqual(result["connections_ok"], 2)

    async def test_google_ads_setup_failure_is_isolated_per_connection(self):
        conns = [
            {"id": "ads-a", "client_id": "amalie"},
            {"id": "ads-b", "client_id": "roove"},
        ]
        sync = AsyncMock(side_effect=[RuntimeError("setup required"), {"rows_upserted": 2}])
        with (
            patch.object(cron_jobs, "sb_select", AsyncMock(return_value=conns)),
            patch("services.google_ads.sync_google_ads", sync),
        ):
            result = await cron_jobs.run_google_ads_sync_all(window_days=7)
        self.assertEqual(sync.await_count, 2)
        self.assertEqual(result["connections_ok"], 1)
        self.assertEqual(result["connections_fail"], 1)


class WideReconciliationTests(unittest.IsolatedAsyncioTestCase):
    async def test_instagram_wide_sweep_reuses_ingestion_without_thumbnail_downloads(self):
        conns = [{"id": "ig-a", "client_id": "amalie", "platform": "instagram", "connection_type": "organic"}]
        with (
            patch.object(cron_jobs, "sb_get_active_meta_connections", AsyncMock(return_value=conns)),
            patch.object(cron_jobs, "_acquire_lock", AsyncMock(return_value=True)),
            patch.object(cron_jobs, "_release_lock", AsyncMock()),
            patch.object(cron_jobs, "_safe_start_job_run", AsyncMock(return_value={"id": "job-ig"})),
            patch.object(cron_jobs, "_safe_finish_job_run", AsyncMock()),
            patch.object(cron_jobs, "sync_instagram_connection", AsyncMock(return_value={"media": [{}], "comments_saved": 0})) as sync,
        ):
            result = await cron_jobs.run_daily_instagram_sync(limit=250, process_thumbnails=False)
        sync.assert_awaited_once_with(
            connection_id="ig-a", limit=250, process_thumbnails=False,
        )
        self.assertEqual(result["job"], "organic_wide_reconciliation")

    async def test_instagram_sync_survives_cron_job_run_fk_failure(self):
        connection_id = "00bb094c-337a-49b3-b2bc-5aec75d79da5"
        conns = [{"id": connection_id, "client_id": "amalie", "platform": "instagram", "connection_type": "organic"}]
        with (
            patch.object(cron_jobs, "sb_get_active_meta_connections", AsyncMock(return_value=conns)),
            patch.object(cron_jobs, "_acquire_lock", AsyncMock(return_value=True)),
            patch.object(cron_jobs, "_release_lock", AsyncMock()),
            patch.object(cron_jobs, "start_job_run", AsyncMock(side_effect=RuntimeError("23503 cron_job_runs_connection_id_fkey"))),
            patch.object(cron_jobs, "sync_instagram_connection", AsyncMock(return_value={"media": [{}], "comments_saved": 2})) as sync,
        ):
            result = await cron_jobs.run_daily_instagram_sync(limit=60)
        sync.assert_awaited_once_with(connection_id=connection_id, limit=60, process_thumbnails=True)
        self.assertEqual(result["connections_ok"], 1)
        self.assertIsNone(result["results"][0]["job_run_id"])


if __name__ == "__main__":
    unittest.main()
