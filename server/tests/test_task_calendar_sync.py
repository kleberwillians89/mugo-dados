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
        calls = []
        async def rpc(fn, payload):
            calls.append((fn, payload))
            if fn == "enqueue_studio_task_sync":
                return {"id": "outbox-1", "status": "pending", "attempts": 0}
            result = "created" if status == "rejeitado" and not existing else "updated"
            task_id = "task-1" if existing or status == "rejeitado" else None
            return {"id": "outbox-1", "task_id": task_id, "result": result}
        with patch.object(st, "sb_rpc", side_effect=rpc), patch.object(st, "sb_update", AsyncMock()):
            out = await st.sync_calendar_item("ruah", {**POST, "status": status}, **kw)
        return out, calls

    async def test_client_adjustment_creates_task_in_changes(self):
        out, calls = await self.run_sync("rejeitado", comment="Trocar a foto", actor_name="Gabi", by_client=True)
        self.assertEqual(out, "created")
        payload = calls[0][1]["p_payload"]
        self.assertEqual((payload["target"], payload["title"], payload["item_id"], payload["due_date"]),
                         ("changes", "Ajuste: Black Friday (27/11)", POST["id"], "2026-11-27"))
        self.assertEqual((payload["comment"], payload["actor_name"], payload["by_client"]), ("Trocar a foto", "Gabi", True))

    async def test_post_without_adjustment_does_not_create_task(self):
        for status in ("em_revisao", "aprovado", "rascunho", "publicado"):
            out, calls = await self.run_sync(status)
            self.assertIsNone(out)
            self.assertEqual([call[0] for call in calls], ["enqueue_studio_task_sync", "process_calendar_task_sync"])

    async def test_linked_task_follows_the_post(self):
        existing = [{"id": "task-1", "status": "changes", "approval_round": 1}]
        out, calls = await self.run_sync("em_revisao", existing, with_client=True)
        self.assertEqual((out, calls[0][1]["p_payload"]["target"]), ("updated", "client_review"))
        out, calls = await self.run_sync("aprovado", [{"id": "task-1", "status": "client_review"}], by_client=True)
        self.assertEqual(calls[0][1]["p_payload"]["target"], "completed")
        out, calls = await self.run_sync("rejeitado", [{"id": "task-1", "status": "client_review", "approval_round": 1}], comment="De novo")
        self.assertEqual(calls[0][1]["p_payload"]["target"], "changes")

    async def test_never_raises(self):
        with patch.object(st, "sb_rpc", AsyncMock(side_effect=RuntimeError("sem funcao"))), \
             patch.object(st, "sb_update", AsyncMock()):
            self.assertIsNone(await st.sync_calendar_item("ruah", {**POST, "status": "rejeitado"}))

    async def test_same_source_version_has_same_operation_key(self):
        item = {**POST, "status": "rejeitado", "updated_at": "2026-11-27T10:00:00Z"}
        seen = []
        async def rpc(fn, payload):
            if fn == "enqueue_studio_task_sync":
                seen.append(payload["p_operation_key"])
                return {"id": "o1", "status": "pending", "attempts": 0}
            return {"id": "o1", "task_id": "t1", "result": "unchanged"}
        with patch.object(st, "sb_rpc", side_effect=rpc):
            await st.sync_calendar_item("ruah", item, comment="x")
            await st.sync_calendar_item("ruah", item, comment="x")
        self.assertEqual(seen[0], seen[1])
