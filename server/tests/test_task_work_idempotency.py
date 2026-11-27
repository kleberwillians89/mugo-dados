from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import task_context as tc  # noqa: E402
from services.studio_calendar import StudioError  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase/migrations/20270131_000166_task_work_idempotency.sql"


class TaskWorkIdempotencyTests(unittest.IsolatedAsyncioTestCase):
    def test_migration_validates_every_supported_module_inside_database(self):
        sql = MIGRATION.read_text().lower()
        for table in (
            "email_campaigns", "studio_content_matrices", "studio_ad_drafts",
            "studio_documents", "studio_calendar_items", "whatsapp_campaign_drafts",
        ):
            self.assertIn(f"from public.{table}", sql)
        self.assertIn("unique index task_work_links_operation_idx", sql)
        self.assertIn("for update", sql)
        self.assertIn("interval '15 minutes'", sql)
        self.assertNotIn("on delete cascade", sql)

    async def test_concurrent_claim_does_not_acquire_same_operation_twice(self):
        rpc = AsyncMock(return_value=[{
            "link_id": "link-1", "link_status": "pending", "record_id": None, "acquired": False,
        }])
        with patch.object(tc, "sb_rpc", rpc):
            claim = await tc.claim_work(
                "tenant-a", "11111111-1111-1111-1111-111111111111",
                module="redacao", operation_key="redacao:artigo", deliverable="Artigo",
            )
        self.assertFalse(claim["acquired"])
        self.assertEqual(rpc.await_args.args[0], "claim_task_work_link")

    async def test_retry_of_completed_link_is_idempotent(self):
        rpc = AsyncMock(return_value=[{
            "link_id": "link-1", "link_status": "linked", "record_id": "doc-1", "acquired": False,
        }])
        with patch.object(tc, "sb_rpc", rpc):
            out = await tc.record_link(
                "tenant-a", "11111111-1111-1111-1111-111111111111",
                module="redacao", record_id="doc-1", operation_key="redacao:artigo",
            )
        self.assertEqual(out["record_id"], "doc-1")
        self.assertEqual(rpc.await_count, 1)

    async def test_completed_operation_cannot_be_rebound(self):
        rpc = AsyncMock(return_value=[{
            "link_id": "link-1", "link_status": "linked", "record_id": "doc-1", "acquired": False,
        }])
        with patch.object(tc, "sb_rpc", rpc):
            with self.assertRaises(StudioError) as raised:
                await tc.record_link(
                    "tenant-a", "11111111-1111-1111-1111-111111111111",
                    module="redacao", record_id="doc-2", operation_key="redacao:artigo",
                )
        self.assertEqual(raised.exception.code, "WORK_ALREADY_LINKED")


if __name__ == "__main__":
    unittest.main()
