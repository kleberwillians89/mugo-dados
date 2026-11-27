"""Post aprovado no Calendário não pode continuar em Ajustes no Kanban."""
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import studio_tasks as st  # noqa: E402

ROWS = [{"id": "t1", "status": "changes", "calendar_item_id": "p1"},       # post aprovado → conclui
        {"id": "t2", "status": "client_review", "calendar_item_id": "p2"},  # post publicado → conclui
        {"id": "t3", "status": "changes", "calendar_item_id": "p3"},       # post ainda em ajuste → fica
        {"id": "t4", "status": "changes", "calendar_item_id": "p4"},       # post apagado → cancela
        {"id": "t5", "status": "in_progress", "calendar_item_id": None}]   # tarefa comum → fica
POSTS = {"p1": {"id": "p1", "status": "aprovado"}, "p2": {"id": "p2", "status": "publicado"},
         "p3": {"id": "p3", "status": "rejeitado"}, "p4": {"id": "p4", "status": "rejeitado", "deleted_at": "2026-11-20"}}


class ReconcileTests(unittest.IsolatedAsyncioTestCase):
    def test_post_is_the_source_of_truth(self):
        self.assertEqual(st.stale_calendar_tasks(ROWS, POSTS), {"t1": "completed", "t2": "completed", "t4": "cancelled"})

    async def test_list_fixes_and_hides_resolved_posts(self):
        select = AsyncMock(side_effect=[ROWS, list(POSTS.values())])
        sync = AsyncMock(return_value="updated")
        with patch.object(st, "sb_select", select), patch.object(st, "sync_calendar_item", sync):
            out = await st.list_tasks("roove")
        self.assertEqual([t["id"] for t in out["tasks"]], ["t3", "t5"])
        self.assertEqual(sync.await_count, 3)
        self.assertEqual(
            {call.args[1]["id"] for call in sync.await_args_list},
            {"p1", "p2", "p4"},
        )

    async def test_failed_sync_keeps_unresolved_task_visible(self):
        select = AsyncMock(side_effect=[ROWS, list(POSTS.values())])
        async def sync(_client_id, post, **_kwargs):
            return None if post["id"] == "p2" else "updated"
        with patch.object(st, "sb_select", select), patch.object(st, "sync_calendar_item", side_effect=sync):
            out = await st.list_tasks("roove")
        self.assertEqual([t["id"] for t in out["tasks"]], ["t2", "t3", "t5"])

    async def test_failure_keeps_the_board_working(self):
        select = AsyncMock(side_effect=[ROWS, RuntimeError("banco fora")])
        with patch.object(st, "sb_select", select):
            out = await st.list_tasks("roove")
        self.assertEqual(len(out["tasks"]), 5)

    async def test_completed_list_is_not_touched(self):
        select = AsyncMock(return_value=[{"id": "t9", "status": "completed", "calendar_item_id": "p1"}])
        with patch.object(st, "sb_select", select):
            await st.list_tasks("roove", status="completed")
        self.assertEqual(select.await_count, 1)


if __name__ == "__main__":
    unittest.main()
