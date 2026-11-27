"""Salvar a pauta (trocar música, capa, legenda) com a mesma data não pode desagendar o post."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from services import studio_calendar as sc

STORED = {"scheduled_at": "2026-11-20T13:00:00+00:00", "channel": "instagram"}


class ScheduleKeepsOnSaveTests(unittest.TestCase):
    def _update(self, patch_body):
        update = AsyncMock(return_value=[{"id": "p1", **STORED}])
        with patch.object(sc, "sb_select", AsyncMock(return_value=[STORED])), patch.object(sc, "sb_update", update):
            asyncio.run(sc.update_item("ruah", "p1", patch_body, user_id="u1"))
        return update.await_args.kwargs["patch"]

    def test_same_time_in_another_format_keeps_confirmation(self):
        sent = self._update({"scheduled_at": "2026-11-20T10:00:00-03:00", "channel": "instagram",
                             "reels_options": {"music": {"audio_id": "123"}}})
        self.assertNotIn("schedule_confirmed_at", sent)
        self.assertEqual(sent["reels_options"]["music"]["audio_id"], "123")

    def test_new_time_drops_confirmation(self):
        sent = self._update({"scheduled_at": "2026-11-20T11:00:00-03:00"})
        self.assertIsNone(sent["schedule_confirmed_at"])

    def test_leaving_approved_drops_confirmation(self):
        sent = self._update({"status": "em_revisao"})
        self.assertIsNone(sent["schedule_confirmed_at"])


if __name__ == "__main__":
    unittest.main()
