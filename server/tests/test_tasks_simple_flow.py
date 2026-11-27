"""Spec do Danilo (PR 1): áreas de cada pessoa e o motivo do ajuste no card."""
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import member_departments as md  # noqa: E402
from services import studio_tasks as st  # noqa: E402

U1, U2 = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"


class DepartmentTests(unittest.IsolatedAsyncioTestCase):
    def test_only_catalog_areas_without_repeating(self):
        self.assertEqual(md.clean_departments(["design", "Design", "Social Media", "Marketing de guerrilha", None]), ["Design", "Social Media"])
        self.assertEqual(md.clean_departments("Design"), [])

    async def test_set_replaces_all_areas_of_the_person(self):
        delete, insert = AsyncMock(), AsyncMock()
        with patch.object(md, "sb_delete", delete), patch.object(md, "sb_insert", insert):
            out = await md.set_departments(U1, ["Design", "Redação"], actor_id=U2)
        self.assertEqual(out, ["Design", "Redação"])
        delete.assert_awaited_once_with(md.TABLE, filters={"user_id": f"eq.{U1}"})
        self.assertEqual([c.args[1]["department"] for c in insert.await_args_list], ["Design", "Redação"])
        with self.assertRaises(ValueError):
            await md.set_departments("nao-e-uuid", ["Design"], actor_id=U2)

    async def test_read_groups_by_person_and_survives_missing_table(self):
        with patch.object(md, "sb_select", AsyncMock(return_value=[{"user_id": U1, "department": "Social Media"}, {"user_id": U1, "department": "Design"}])):
            self.assertEqual(await md.departments_of([U1, U2, "lixo"]), {U1: ["Design", "Social Media"], U2: []})
        with patch.object(md, "sb_select", AsyncMock(side_effect=RuntimeError("relation does not exist"))):
            self.assertEqual(await md.departments_of([U1]), {U1: []})


class ChangeNoteTests(unittest.IsolatedAsyncioTestCase):
    async def test_latest_adjustment_per_task_and_client_sees_only_public(self):
        rows = [{"task_id": "t1", "comment": "Trocar a capa", "created_at": "2026-11-25T10:00:00Z"},
                {"task_id": "t1", "comment": "Pedido antigo", "created_at": "2026-11-20T10:00:00Z"},
                {"task_id": "t2", "comment": "  ", "created_at": "2026-11-25T09:00:00Z"}]
        select = AsyncMock(return_value=rows)
        with patch.object(st, "sb_select", select):
            out = await st.change_notes("roove", ["t1", "t2"], client_view=True)
        self.assertEqual(out, {"t1": "Trocar a capa"})
        self.assertEqual(select.await_args.kwargs["filters"]["internal"], "is.false")
        self.assertEqual(await st.change_notes("roove", [], client_view=False), {})


if __name__ == "__main__":
    unittest.main()
