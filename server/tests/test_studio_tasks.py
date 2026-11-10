"""Tarefas no Mugoverso: formato do quadro, visão do cliente, validação e escopo por empresa."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import AsyncMock, patch

from services import studio_tasks as st
from services.studio_calendar import StudioError

ROW = {"id": "t1", "client_id": "roove", "title": "Fotos do lançamento", "notes": "interno", "status": "pending", "priority": "high",
       "due_date": "2026-11-20", "due_time": "14:30:00", "category": "Conteúdo", "assignee_name": "Julia",
       "visible_to_client": True, "updated_at": "x"}


class ViewTests(unittest.TestCase):
    def test_same_shape_as_crm_board(self):
        v = st.task_view(ROW)
        self.assertEqual((v["due_time"], v["assignee"]["name"], v["tags"]), ("14:30", "Julia", []))
        self.assertIsNone(st.task_view({**ROW, "assignee_name": None})["assignee"])

    def test_validation(self):
        with self.assertRaises(StudioError):
            st._clean({"title": "  "}, partial=False)
        with self.assertRaises(StudioError):
            st._clean({"title": "x", "status": "feito"}, partial=False)
        self.assertIsNotNone(st._clean({"status": "completed"}, partial=True)["completed_at"])
        self.assertEqual(st._clean({"due_date": "2026-11-20T10:00"}, partial=True)["due_date"], "2026-11-20")


class ScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_list_filters_visible_and_hides_internal_fields(self):
        select = AsyncMock(return_value=[ROW])
        with patch.object(st, "sb_select", select):
            out = await st.list_client_tasks("roove")
        self.assertEqual(select.await_args_list[0].kwargs["filters"]["visible_to_client"], "is.true")
        self.assertNotIn("notes", out["tasks"][0])
        self.assertNotIn("assignee", out["tasks"][0])

    async def test_missing_table_is_reported_not_crashed(self):
        with patch.object(st, "sb_select", AsyncMock(side_effect=RuntimeError("relation does not exist"))):
            self.assertEqual(await st.list_tasks("roove"), {"available": False, "reason": "migration_pending"})

    async def test_client_creates_visible_and_cannot_touch_internal(self):
        insert = AsyncMock(return_value={**ROW, "visible_to_client": True})
        with patch.object(st, "sb_insert", insert):
            await st.create_task("roove", {"title": "Aprovar arte", "visible_to_client": False}, user_id="u1", client_view=True)
        self.assertTrue(insert.await_args.args[1]["visible_to_client"])
        with patch.object(st, "sb_select", AsyncMock(return_value=[{**ROW, "visible_to_client": False}])):
            with self.assertRaises(StudioError) as raised:
                await st.update_task("roove", "t1", {"status": "completed"}, client_view=True)
        self.assertEqual(raised.exception.code, "TASK_NOT_FOUND")

    async def test_update_is_scoped_to_company(self):
        update = AsyncMock(return_value=[ROW])
        with patch.object(st, "sb_select", AsyncMock(return_value=[ROW])), patch.object(st, "sb_update", update):
            await st.update_task("roove", "t1", {"status": "in_progress"}, client_view=False)
        self.assertEqual(update.await_args.kwargs["filters"], {"client_id": "eq.roove", "id": "eq.t1"})


if __name__ == "__main__":
    unittest.main()
