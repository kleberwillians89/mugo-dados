"""Calendário e Tarefas no mesmo fluxo: ajuste num post vira tarefa e a tarefa acompanha o post."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import AsyncMock, patch

from services import studio_tasks as st

POST = {"id": "11111111-1111-1111-1111-111111111111", "title": "Black Friday", "scheduled_at": "2026-11-27T12:00:00-03:00"}


class SyncTests(unittest.IsolatedAsyncioTestCase):
    async def run_sync(self, status, existing=None, **kw):
        insert = AsyncMock(return_value={"id": "task-1"})
        update = AsyncMock(return_value=[])
        with patch.object(st, "sb_select", AsyncMock(return_value=existing or [])), patch.object(st, "sb_insert", insert), \
             patch.object(st, "sb_update", update):
            out = await st.sync_calendar_item("ruah", {**POST, "status": status}, **kw)
        return out, insert, update

    async def test_client_adjustment_creates_task_in_changes(self):
        out, insert, _ = await self.run_sync("rejeitado", comment="Trocar a foto", actor_name="Gabi", by_client=True)
        self.assertEqual(out, "created")
        task = insert.await_args_list[0].args[1]
        self.assertEqual((task["status"], task["title"], task["calendar_item_id"], task["visible_to_client"], task["due_date"]),
                         ("changes", "Ajuste: Black Friday (27/11)", POST["id"], False, "2026-11-27"))
        event = insert.await_args_list[1].args[1]
        self.assertEqual((event["kind"], event["comment"], event["actor_side"], event["internal"]), ("ajuste_cliente", "Trocar a foto", "cliente", False))

    async def test_post_without_adjustment_does_not_create_task(self):
        for status in ("em_revisao", "aprovado", "rascunho", "publicado"):
            out, insert, _ = await self.run_sync(status)
            self.assertIsNone(out)
            insert.assert_not_awaited()

    async def test_linked_task_follows_the_post(self):
        existing = [{"id": "task-1", "status": "changes", "approval_round": 1}]
        out, _, update = await self.run_sync("em_revisao", existing, with_client=True)
        self.assertEqual((out, update.await_args.kwargs["patch"]["status"]), ("updated", "client_review"))
        out, _, update = await self.run_sync("aprovado", [{"id": "task-1", "status": "client_review"}], by_client=True)
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "completed")
        out, _, update = await self.run_sync("rejeitado", [{"id": "task-1", "status": "client_review", "approval_round": 1}], comment="De novo")
        self.assertEqual((update.await_args.kwargs["patch"]["status"], update.await_args.kwargs["patch"]["approval_round"]), ("changes", 2))

    async def test_never_raises(self):
        with patch.object(st, "sb_select", AsyncMock(side_effect=RuntimeError("sem coluna"))):
            self.assertIsNone(await st.sync_calendar_item("ruah", {**POST, "status": "rejeitado"}))
