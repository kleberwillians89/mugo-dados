"""Tarefas da empresa, guardadas no próprio Mugoverso (antes só lidas do CRM Mugô).

Devolve o mesmo formato que a ponte do CRM devolvia ({available, tasks}), então quadro, Central,
painel do cliente e lista do cliente continuam iguais.

- Equipe Mugô: vê e gerencia todas as tarefas da empresa.
- Cliente: vê só as marcadas como visíveis ao cliente; com "Gerenciar tarefas" cria e altera essas
  (o que o cliente cria nasce visível para ele).
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timezone
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_delete, sb_insert, sb_select, sb_update
from .studio_calendar import StudioError

TABLE = "studio_tasks"
STATUSES = ("pending", "in_progress", "completed", "cancelled")
PRIORITIES = ("low", "medium", "high", "urgent")
COLUMNS = ("id,client_id,title,notes,status,priority,due_date,due_time,category,assignee_name,"
           "visible_to_client,completed_at,created_at,updated_at")
_COLORS = ("#2f6f8f", "#8a5a9e", "#b0693a", "#3f7f5a", "#a3485a", "#5b6bbf", "#7a7a2a", "#3a8a8a")


def _color(name: str) -> str:
    return _COLORS[int(hashlib.sha1(name.encode()).hexdigest(), 16) % len(_COLORS)]


def task_view(row: Dict[str, Any]) -> Dict[str, Any]:
    """Mesmo formato do CRM (CrmTask no frontend) + visible_to_client."""
    who = str(row.get("assignee_name") or "").strip()
    return {
        "id": str(row.get("id")), "title": row.get("title") or "", "status": row.get("status") or "pending",
        "priority": row.get("priority"), "due_date": row.get("due_date"),
        "due_time": str(row["due_time"])[:5] if row.get("due_time") else None,
        "starts_at": None, "category": row.get("category"), "task_type": None, "tags": [],
        "notes": row.get("notes"), "updated_at": row.get("updated_at"),
        "assignee": {"name": who, "color": _color(who)} if who else None,
        "visible_to_client": bool(row.get("visible_to_client")),
    }


async def _rows(client_id: str, *, status: Optional[str], limit: int, client_view: bool) -> List[Dict[str, Any]]:
    filters = {"client_id": f"eq.{client_id}"}
    if status:
        filters["status"] = f"eq.{status}"
    else:
        filters["status"] = "in.(pending,in_progress)"
    if client_view:
        filters["visible_to_client"] = "is.true"
    return await sb_select(TABLE, select=COLUMNS, filters=filters, order="due_date.asc.nullslast,created_at.asc",
                           limit=max(1, min(int(limit), 500)))


async def list_tasks(client_id: str, *, status: Optional[str] = None, limit: int = 200,
                     client_view: bool = False) -> Dict[str, Any]:
    if status and status not in STATUSES:
        raise StudioError("STATUS_INVALID")
    try:
        rows = await _rows(client_id, status=status, limit=limit, client_view=client_view)
    except Exception as exc:  # noqa: BLE001 — tabela ainda não criada (migração 000089)
        print(f"[studio_tasks] list client_id={client_id} unavailable error_type={type(exc).__name__}")
        return {"available": False, "reason": "migration_pending"}
    return {"available": True, "tasks": [task_view(r) for r in rows]}


async def list_client_tasks(client_id: str) -> Dict[str, Any]:
    """Visão do cliente: só visíveis, sem observações nem responsável."""
    out: List[Dict[str, Any]] = []
    for status in (None, "completed"):
        result = await list_tasks(client_id, status=status, limit=50, client_view=True)
        if not result.get("available"):
            return result
        out += [{k: t[k] for k in ("id", "title", "status", "due_date", "updated_at")} for t in result["tasks"]]
    return {"available": True, "tasks": out}


def _clean(data: Dict[str, Any], *, partial: bool) -> Dict[str, Any]:
    row: Dict[str, Any] = {}
    if "title" in data or not partial:
        title = str(data.get("title") or "").strip()[:200]
        if not title:
            raise StudioError("TASK_TITLE_REQUIRED")
        row["title"] = title
    if "notes" in data:
        row["notes"] = (str(data.get("notes") or "").strip()[:4000]) or None
    if "status" in data:
        if data["status"] not in STATUSES:
            raise StudioError("STATUS_INVALID")
        row["status"] = data["status"]
        row["completed_at"] = datetime.now(timezone.utc).isoformat() if data["status"] == "completed" else None
    if "priority" in data:
        if data["priority"] not in (None, "", *PRIORITIES):
            raise StudioError("PRIORITY_INVALID")
        row["priority"] = data["priority"] or None
    if "due_date" in data:
        value = data.get("due_date")
        if value:
            try:
                value = date.fromisoformat(str(value)[:10]).isoformat()
            except ValueError:
                raise StudioError("DUE_DATE_INVALID") from None
        row["due_date"] = value or None
    if "due_time" in data:
        value = data.get("due_time")
        if value:
            try:
                value = time.fromisoformat(str(value)[:5]).strftime("%H:%M")
            except ValueError:
                raise StudioError("DUE_DATE_INVALID") from None
        row["due_time"] = value or None
    for key, size in (("category", 60), ("assignee_name", 80)):
        if key in data:
            row[key] = (str(data.get(key) or "").strip()[:size]) or None
    if "visible_to_client" in data:
        row["visible_to_client"] = bool(data["visible_to_client"])
    return row


async def _owned(client_id: str, task_id: str, *, client_view: bool) -> Dict[str, Any]:
    rows = await sb_select(TABLE, select=COLUMNS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{task_id}"}, limit=1)
    if not rows or (client_view and not rows[0].get("visible_to_client")):
        raise StudioError("TASK_NOT_FOUND")
    return rows[0]


async def create_task(client_id: str, data: Dict[str, Any], *, user_id: str, client_view: bool) -> Dict[str, Any]:
    row = _clean(data, partial=False)
    row.setdefault("status", "pending")
    if client_view:
        row["visible_to_client"] = True  # o que o cliente cria é dele também
    created = await sb_insert(TABLE, {"client_id": client_id, "created_by": user_id, **row})
    if not created:
        raise StudioError("TASK_SAVE_FAILED")
    return task_view(created)


async def update_task(client_id: str, task_id: str, data: Dict[str, Any], *, client_view: bool) -> Dict[str, Any]:
    await _owned(client_id, task_id, client_view=client_view)
    patch = _clean(data, partial=True)
    if client_view:
        patch.pop("visible_to_client", None)  # cliente não esconde tarefa da própria visão
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()
    rows = await sb_update(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{task_id}"}, patch=patch)
    if not rows:
        raise StudioError("TASK_NOT_FOUND")
    return task_view(rows[0])


async def delete_task(client_id: str, task_id: str, *, client_view: bool) -> None:
    await _owned(client_id, task_id, client_view=client_view)
    await sb_delete(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{task_id}"}, returning="minimal")
