import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from services import studio_calendar as sc
from services.studio_calendar import StudioError


class ConfirmScheduleTests(unittest.IsolatedAsyncioTestCase):
    async def confirm(self, status, when):
        update = AsyncMock(return_value=[{"id": "i1", "schedule_confirmed_at": "agora"}])
        with patch.object(sc, "sb_select", AsyncMock(return_value=[{"id": "i1", "status": status, "scheduled_at": when.isoformat(), "format": "imagem", "art_url": "https://x.supabase.co/storage/v1/object/public/ig-media/a.jpg"}])), \
             patch.object(sc, "sb_update", update):
            return await sc.confirm_schedule("roove", "i1", user_id="u1"), update

    async def test_only_approved_future_posts(self):
        future = datetime.now(timezone.utc) + timedelta(days=2)
        item, update = await self.confirm("aprovado", future)
        self.assertEqual(update.await_args.kwargs["filters"], {"client_id": "eq.roove", "id": "eq.i1", "status": "eq.aprovado"})
        self.assertEqual(update.await_args.kwargs["patch"]["schedule_confirmed_by"], "u1")
        for status, when, code in (("em_revisao", future, "SCHEDULE_NEEDS_APPROVAL"),
                                   ("aprovado", datetime.now(timezone.utc) - timedelta(hours=1), "SCHEDULE_IN_PAST")):
            with self.assertRaises(StudioError) as err:
                await self.confirm(status, when)
            self.assertEqual(err.exception.code, code)

    async def test_date_change_clears_confirmation(self):
        update = AsyncMock(return_value=[{"id": "i1"}])
        with patch.object(sc, "sb_update", update), patch.object(sc, "sb_select", AsyncMock(return_value=[])):
            await sc.update_item("roove", "i1", {"scheduled_at": "2030-01-10T19:00:00-03:00"}, user_id="u1")
        self.assertIsNone(update.await_args.kwargs["patch"]["schedule_confirmed_at"])


if __name__ == "__main__":
    unittest.main()
