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
from cron_fixtures import active_companies
from jobs_schedule import scheduled_commands  # noqa: E402


class ScheduledJobsTests(unittest.TestCase):
    """Render free não tem Cron Job: os jobs rodam no GitHub Actions."""

    def test_provider_jobs_are_wired_to_real_schedules(self):
        jobs = scheduled_commands()
        contracts = (
            ("15,45 * * * *", "shopify-reconcile --fallback-days 30"),
            ("25 7 * * *", "shopify-historical-reconcile --days 14"),
            ("5 * * * *", "ads-sync-hourly --days 7"),
            ("10 6,12,18,23 * * *", "organic-sync --limit 60"),
            ("20 */3 * * *", "ga4-sync-all --days 3"),
            ("35 */3 * * *", "google-ads-sync --days 7"),
            ("40 8 * * 0", "shopify-historical-reconcile --days 90"),
            ("45 2 * * *", "ads-sync-hourly --days 30"),
            ("15 3 * * *", "ga4-sync-all --days 30"),
            ("45 3 * * *", "google-ads-sync --days 30"),
            ("20 9 * * 0", "organic-sync --limit 250 --skip-thumbnails"),
            ("10 5 * * *", "history-backfill-worker --budget-minutes 150"),
            ("*/10 * * * *", "ads-backfill-worker"),
            ("15 */6 * * *", "token-refresh"),
        )
        for schedule, command in contracts:
            with self.subTest(schedule=schedule):
                self.assertEqual(jobs[schedule], command)

    def test_render_stays_free_without_paid_cron_services(self):
        blueprint = (ROOT / "render.yaml").read_text()
        self.assertNotIn("type: cron", blueprint)
        self.assertIn("plan: free", blueprint)
        self.assertNotIn("plan: starter", blueprint)

    def test_public_logs_never_carry_job_output(self):
        runner = (ROOT / ".github" / "scripts" / "run_job.py").read_text()
        self.assertIn("stdout=subprocess.DEVNULL", runner)
        self.assertIn("stderr=subprocess.DEVNULL", runner)
        workflow = (ROOT / ".github" / "workflows" / "sync-jobs.yml").read_text()
        self.assertIn("secrets.MUGO_JOBS_ENV", workflow)
        self.assertIn("contents: read", workflow)


class MultiTenantGoogleCronTests(unittest.IsolatedAsyncioTestCase):
    async def test_ga4_discovers_and_syncs_every_active_configured_connection(self):
        conns = [
            {"id": "ga-a", "client_id": "amalie", "metadata": {"ga4_property_id": "1"}},
            {"id": "ga-b", "client_id": "roove", "metadata": {"ga4_property_id": "2"}},
        ]
        with (
            patch("services.client_lifecycle.sb_select", side_effect=active_companies),
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
            patch("services.client_lifecycle.sb_select", side_effect=active_companies),
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
            patch("services.client_lifecycle.sb_select", side_effect=active_companies),
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
            patch("services.client_lifecycle.sb_select", side_effect=active_companies),
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
