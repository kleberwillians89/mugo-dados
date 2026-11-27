from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import task_sync_outbox as outbox

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase/migrations/20270131_000168_task_decision_outbox.sql"


class MigrationContractTests(unittest.TestCase):
    def test_decision_and_events_share_one_rpc_transaction(self):
        sql = MIGRATION.read_text().lower()
        self.assertIn("function public.apply_studio_task_decision", sql)
        self.assertIn("insert into public.studio_task_events", sql)
        self.assertIn("for update", sql)
        self.assertIn("unique (client_id, kind, operation_key)", sql)
        self.assertIn("function public.process_calendar_task_sync", sql)
        self.assertIn("revoke all on function", sql)


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_crm_receives_external_notification_with_stable_event_id(self):
        row = {"id": "o1", "client_id": "tenant-a", "kind": "crm_notification", "status": "pending",
               "attempts": 0, "payload": {"task_id": "t1", "action": "client_approve"}}
        post = AsyncMock(return_value={"ok": True})
        with patch.object(outbox, "post_event", post), \
             patch.object(outbox, "sb_update", AsyncMock()) as update:
            self.assertTrue(await outbox.deliver(row))
        payload = post.await_args.args[2]
        self.assertEqual((payload["event_id"], payload["task_id"]), ("o1", "t1"))
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "sent")

    async def test_failure_remains_observable_for_retry(self):
        row = {"id": "o1", "client_id": "tenant-a", "kind": "crm_notification", "status": "pending",
               "attempts": 0, "payload": {}}
        with patch.object(outbox, "post_event", AsyncMock(return_value={"ok": False, "code": "network"})), \
             patch.object(outbox, "sb_update", AsyncMock()) as update:
            self.assertFalse(await outbox.deliver(row))
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "failed")
        self.assertEqual(update.await_args.kwargs["patch"]["attempts"], 1)


if __name__ == "__main__":
    unittest.main()
