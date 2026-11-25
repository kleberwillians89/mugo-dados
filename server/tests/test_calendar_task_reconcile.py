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
        update, event = AsyncMock(), AsyncMock()
        with patch.object(st, "sb_select", select), patch.object(st, "sb_update", update), patch.object(st, "_event", event):
            out = await st.list_tasks("roove")
        self.assertEqual([t["id"] for t in out["tasks"]], ["t3", "t5"])
        patched = {c.kwargs["filters"]["id"]: c.kwargs["patch"]["status"] for c in update.await_args_list}
        self.assertEqual(patched, {"eq.t1": "completed", "eq.t2": "completed", "eq.t4": "cancelled"})
        self.assertEqual(event.await_count, 3)  # fica no histórico por que saiu de Ajustes

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
