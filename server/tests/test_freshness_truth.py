"""Regressões de 28/10/2026: Instagram parado e "Ainda não atualizado" falso.

- Um erro passageiro marcava a conexão como status=error e o cron (que só lia
  status=active) nunca mais a sincronizava (Curavino: 6 dias parada).
- Métrica que a Meta não oferece para um post tornava todo sync "parcial", e
  parcial nunca aparecia como "Atualizado em" na tela.
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import data_health, ig_supabase, instagram_sync  # noqa: E402

NOW = datetime(2026, 10, 28, 19, tzinfo=timezone.utc)


class CronSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_errored_connections_stay_in_cron_but_reauth_does_not(self):
        with patch.object(ig_supabase, "sb_select", AsyncMock(return_value=[])) as select:
            await ig_supabase.sb_get_active_meta_connections(platform="instagram", connection_type="organic")
        filters = select.await_args.kwargs["filters"]
        self.assertEqual(filters["status"], "in.(active,error)")
        self.assertEqual(filters["requires_reauth"], "not.is.true")
        self.assertEqual(filters["platform"], "eq.instagram")


class PartialSemanticsTests(unittest.TestCase):
    def test_item_level_gaps_are_not_partial_but_block_failures_are(self):
        routine = [instagram_sync.MEDIA_INSIGHTS_NOTE, instagram_sync.STORY_INSIGHTS_NOTE,
                   instagram_sync.COMMENTS_NOTE, instagram_sync.STORIES_NOTE]
        self.assertEqual(instagram_sync.blocking_warnings(routine), [])
        self.assertEqual(instagram_sync.blocking_warnings(None), [])
        blocking = "Insights do perfil indisponíveis; snapshot anterior preservado."
        self.assertEqual(instagram_sync.blocking_warnings(routine + [blocking]), [blocking])
        self.assertEqual(instagram_sync.blocking_warnings(["Falha parcial na listagem de mídias."]),
                         ["Falha parcial na listagem de mídias."])


class LastUpdatedTests(unittest.TestCase):
    def compose(self, row, jobs=()):
        return data_health.compose_source("instagram", row, list(jobs), [], [], "2026-10-28", "2026-10-28", now=NOW)

    def test_partial_instagram_sync_reports_when_data_was_written(self):
        row = {"id": "ig-1", "client_id": "c", "platform": "instagram", "status": "active",
               "last_sync_status": "partial", "last_sync_at": "2026-10-28T12:47:10+00:00", "last_synced_at": None}
        result = self.compose(row)
        self.assertIsNone(result["last_successful_sync_at"])  # coleta completa continua estrita
        self.assertEqual(result["last_updated_at"], "2026-10-28T12:47:10+00:00")

    def test_partial_job_counts_as_update_and_error_does_not(self):
        row = {"id": "ig-1", "client_id": "c", "platform": "instagram", "status": "error", "last_sync_status": "error",
               "last_sync_at": "2026-10-28T15:00:00+00:00"}
        jobs = [
            {"client_id": "c", "connection_id": "ig-1", "job_name": "instagram_organic_sync", "status": "error",
             "started_at": "2026-10-28T15:00:00+00:00", "finished_at": "2026-10-28T15:01:00+00:00", "payload_json": {}},
            {"client_id": "c", "connection_id": "ig-1", "job_name": "instagram_organic_sync", "status": "partial",
             "started_at": "2026-10-28T09:10:00+00:00", "finished_at": "2026-10-28T09:12:00+00:00", "payload_json": {}},
        ]
        result = self.compose(row, jobs)
        self.assertEqual(result["last_updated_at"], "2026-10-28T09:12:00+00:00")
        self.assertEqual(result["sync_status"], "error")
        self.assertEqual(result["last_attempt_at"], "2026-10-28T15:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
