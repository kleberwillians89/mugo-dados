"""Private assignment notifications: one inbox per person, no cross-tenant leaks."""
import asyncio
from unittest.mock import AsyncMock

from services import task_assignment_notifications as notices


def test_task_message_includes_details_and_link(monkeypatch):
    monkeypatch.setattr("services.studio_approvals.frontend_base_url", lambda: "https://dados.example.com")
    body = notices.message_for_task({
        "id": "task-1", "title": "Enviar apresentação",
        "category": "Criação", "due_date": "2026-11-18",
        "due_time": "15:00", "notes": "Compartilhar arquivo do Drive",
    })
    assert "Enviar apresentação" in body
    assert "18/11/2026 às 15:00" in body
    assert "Compartilhar arquivo" in body
    assert "https://dados.example.com/tarefas?task=task-1" in body


def test_each_assignee_gets_one_private_message_and_demo_never_sends_whatsapp(monkeypatch):
    monkeypatch.setattr("services.studio_approvals.frontend_base_url", lambda: "https://dados.example.com")
    writes = []
    updates = []
    async def insert(table, row, **kwargs):
        writes.append(row)
        return {**row, "id": f"notice-{len(writes)}"}
    async def update(table, *, filters, patch, **kwargs):
        updates.append(patch)
        return [patch]
    monkeypatch.setattr(notices, "sb_insert", insert)
    monkeypatch.setattr(notices, "sb_update", update)
    task = {"id": "task-1", "title": "Entregar layout", "assignee_user_ids": ["u1", "u2", "u2"]}
    result = asyncio.run(notices.notify_assignment("pace-sneakers-demo", task))
    assert result == 2
    assert {m["recipient_user_id"] for m in writes} == {"u1", "u2"}
    assert all(m["client_id"] == "pace-sneakers-demo" for m in writes)
    assert all(row["whatsapp_status"] == "skipped_demo" for row in updates)


def test_inbox_is_private_to_signed_in_user(monkeypatch):
    async def select(table, *, select, filters, **kwargs):
        assert filters == {"client_id": "eq.tenant-a", "recipient_user_id": "eq.user-1"}
        return [{"id": "m1", "recipient_user_id": "user-1", "read_at": None,
                 "title": "Task", "body": "Task body"}]
    monkeypatch.setattr(notices, "sb_select", select)
    out = asyncio.run(notices.inbox("tenant-a", "user-1"))
    assert out["unread"] == 1
    assert out["messages"][0].get("recipient_user_id") is None


def test_whatsapp_requires_opt_in_verified_number_and_sender_configuration(monkeypatch):
    monkeypatch.setenv("TASKS_WHATSAPP_SENDER_CLIENT_ID", "mugo")
    monkeypatch.setenv("TASKS_WHATSAPP_TEMPLATE", "nova_tarefa")
    async def select(table, *, select, filters, **kwargs):
        return [{"opted_in": False}]
    monkeypatch.setattr(notices, "sb_select", select)
    called = AsyncMock()
    monkeypatch.setattr(notices, "_verified_auth_phone", called)
    result = asyncio.run(notices._whatsapp_dispatch("tenant-a", "u1", "A tarefa"))
    assert result == ("not_opted_in", None)
    called.assert_not_awaited()
