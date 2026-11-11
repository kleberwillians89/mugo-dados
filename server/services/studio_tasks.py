"""Tarefas da empresa, guardadas no próprio Mugoverso (antes só lidas do CRM Mugô).

Devolve o mesmo formato que a ponte do CRM devolvia ({available, tasks}), então quadro, Central,
painel do cliente e lista do cliente continuam iguais.

- Equipe Mugô: vê e gerencia todas as tarefas da empresa.
- Cliente: vê só as marcadas como visíveis ao cliente; com "Gerenciar tarefas" cria e altera essas
  (o que o cliente cria nasce visível para ele).

Aprovação (como no iAgência): Em produção → Aprovação interna (equipe Mugô aprova ou pede ajuste) →
Aprovação do cliente (qualquer pessoa da empresa aprova ou pede ajuste) → Aprovada. Ajuste volta para
"Ajustes" com o comentário; reenviar recomeça a rodada. Tarefa só interna (não visível ao cliente ou sem
aprovação do cliente) termina na aprovação interna. O cliente não vê a etapa interna (aparece "Em produção")
nem os comentários internos. Histórico em ``studio_task_events``.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timezone
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_delete, sb_insert, sb_select, sb_update
from .studio_calendar import StudioError

TABLE = "studio_tasks"
STATUSES = ("pending", "in_progress", "internal_review", "client_review", "changes", "completed", "cancelled")
OPEN_STATUSES = ("pending", "in_progress", "internal_review", "client_review", "changes")
EVENTS = "studio_task_events"
PRIORITIES = ("low", "medium", "high", "urgent")
COLUMNS = ("id,client_id,title,notes,status,priority,due_date,due_time,category,assignee_name,"
           "visible_to_client,completed_at,created_at,updated_at,deliverable_url,needs_client_approval,approval_round,approved_at")
# Com a ligação ao Calendário (migração 000097); sem ela, cai para COLUMNS e depois LEGACY_COLUMNS.
LINKED_COLUMNS = COLUMNS + ",calendar_item_id"
LEGACY_COLUMNS = ("id,client_id,title,notes,status,priority,due_date,due_time,category,assignee_name,"
                  "visible_to_client,completed_at,created_at,updated_at")
_COLORS = ("#2f6f8f", "#8a5a9e", "#b0693a", "#3f7f5a", "#a3485a", "#5b6bbf", "#7a7a2a", "#3a8a8a")


def _color(name: str) -> str:
    return _COLORS[int(hashlib.sha1(name.encode()).hexdigest(), 16) % len(_COLORS)]


def task_view(row: Dict[str, Any], *, client_view: bool = False) -> Dict[str, Any]:
    """Mesmo formato do CRM (CrmTask no frontend) + visible_to_client e aprovação."""
    who = str(row.get("assignee_name") or "").strip()
    status = row.get("status") or "pending"
    if client_view and status == "internal_review":
        status = "in_progress"  # a etapa interna não aparece para o cliente
    return {
        "id": str(row.get("id")), "title": row.get("title") or "", "status": status,
        "deliverable_url": row.get("deliverable_url"), "needs_client_approval": row.get("needs_client_approval", True) is not False,
        "approval_round": int(row.get("approval_round") or 0), "approved_at": row.get("approved_at"),
        "priority": row.get("priority"), "due_date": row.get("due_date"),
        "due_time": str(row["due_time"])[:5] if row.get("due_time") else None,
        "starts_at": None, "category": row.get("category"), "task_type": None, "tags": [],
        "notes": row.get("notes"), "updated_at": row.get("updated_at"),
        "assignee": {"name": who, "color": _color(who)} if who else None,
        "visible_to_client": bool(row.get("visible_to_client")),
        "calendar_item_id": str(row["calendar_item_id"]) if row.get("calendar_item_id") else None,
    }


async def _rows(client_id: str, *, status: Optional[str], limit: int, client_view: bool) -> List[Dict[str, Any]]:
    filters = {"client_id": f"eq.{client_id}"}
    if status:
        filters["status"] = f"eq.{status}"
    else:
        filters["status"] = f"in.({','.join(OPEN_STATUSES)})"
    if client_view:
        filters["visible_to_client"] = "is.true"
    kwargs = dict(filters=filters, order="due_date.asc.nullslast,created_at.asc", limit=max(1, min(int(limit), 500)))
    try:
        return await sb_select(TABLE, select=LINKED_COLUMNS, **kwargs)
    except Exception:  # noqa: BLE001 — sem a migração 000097
        pass
    try:
        return await sb_select(TABLE, select=COLUMNS, **kwargs)
    except Exception:  # noqa: BLE001 — sem a migração 000096: colunas e etapas antigas
        if status in (None, "pending", "in_progress", "completed", "cancelled"):
            if not status:
                kwargs["filters"] = {**filters, "status": "in.(pending,in_progress)"}
            return await sb_select(TABLE, select=LEGACY_COLUMNS, **kwargs)
        raise


async def list_tasks(client_id: str, *, status: Optional[str] = None, limit: int = 200,
                     client_view: bool = False) -> Dict[str, Any]:
    if status and status not in STATUSES:
        raise StudioError("STATUS_INVALID")
    try:
        rows = await _rows(client_id, status=status, limit=limit, client_view=client_view)
    except Exception as exc:  # noqa: BLE001 — tabela ainda não criada (migração 000089)
        print(f"[studio_tasks] list client_id={client_id} unavailable error_type={type(exc).__name__}")
        return {"available": False, "reason": "migration_pending"}
    return {"available": True, "tasks": [task_view(r, client_view=client_view) for r in rows]}


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
    if "needs_client_approval" in data:
        row["needs_client_approval"] = bool(data["needs_client_approval"])
    if "deliverable_url" in data:
        url = str(data.get("deliverable_url") or "").strip()[:1000]
        if url and not url.startswith("https://"):
            raise StudioError("DELIVERABLE_URL_INVALID", "O link da entrega precisa começar com https://")
        row["deliverable_url"] = url or None
    return row


async def _owned(client_id: str, task_id: str, *, client_view: bool) -> Dict[str, Any]:
    filters = {"client_id": f"eq.{client_id}", "id": f"eq.{task_id}"}
    try:
        rows = await sb_select(TABLE, select=LINKED_COLUMNS, filters=filters, limit=1)
    except Exception:  # noqa: BLE001 — sem a migração 000097
        rows = None
    if rows is None:
        try:
            rows = await sb_select(TABLE, select=COLUMNS, filters=filters, limit=1)
        except Exception:  # noqa: BLE001 — sem a migração 000096
            rows = await sb_select(TABLE, select=LEGACY_COLUMNS, filters=filters, limit=1)
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
    return task_view(rows[0], client_view=client_view)


async def delete_task(client_id: str, task_id: str, *, client_view: bool) -> None:
    await _owned(client_id, task_id, client_view=client_view)
    await sb_delete(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{task_id}"}, returning="minimal")


# ------------------------------------------------------------------ aprovação

ACTIONS = {
    # ação: (quem pode, etapas de origem, etapa de destino, evento, interno, comentário obrigatório)
    "submit": ("mugo", ("pending", "in_progress", "changes"), "internal_review", "enviado_interno", True, False),
    "internal_approve": ("mugo", ("internal_review",), None, "aprovado_interno", True, False),
    "internal_changes": ("mugo", ("internal_review",), "changes", "ajuste_interno", True, True),
    "client_approve": ("any", ("client_review",), "completed", "aprovado_cliente", False, False),
    "client_changes": ("any", ("client_review",), "changes", "ajuste_cliente", False, True),
    "comment": ("any", STATUSES, None, "comentario", None, True),
}


def next_status(action: str, task: Dict[str, Any]) -> Optional[str]:
    """Destino da ação; aprovação interna vai ao cliente só se a tarefa é visível e pede aprovação dele."""
    if action == "internal_approve":
        to_client = bool(task.get("visible_to_client")) and task.get("needs_client_approval", True) is not False
        return "client_review" if to_client else "completed"
    return ACTIONS[action][2]


async def approval_action(client_id: str, task_id: str, action: str, *, comment: Optional[str], user_id: str,
                          actor_name: str, is_agency: bool, internal_comment: bool = False) -> Dict[str, Any]:
    if action not in ACTIONS:
        raise StudioError("ACTION_INVALID", "Ação inválida.")
    who, sources, _, kind, internal, needs_comment = ACTIONS[action]
    if who == "mugo" and not is_agency:
        raise StudioError("FORBIDDEN", "Só a equipe Mugô faz a aprovação interna.")
    task = await _owned(client_id, task_id, client_view=not is_agency)
    if task.get("status") not in sources:
        raise StudioError("STAGE_INVALID", "A tarefa não está nesta etapa (atualize a tela).")
    text = str(comment or "").strip()[:2000]
    if needs_comment and not text:
        raise StudioError("COMMENT_REQUIRED", "Escreva o que precisa mudar." if action != "comment" else "Escreva o comentário.")
    if internal is None:  # comentário: interno só quando a equipe marca; cliente sempre público
        internal = bool(internal_comment) and is_agency
    now = datetime.now(timezone.utc).isoformat()
    destination = next_status(action, task)
    events = [{"client_id": client_id, "task_id": task_id, "kind": kind, "internal": internal, "comment": text or None,
               "actor_id": user_id, "actor_name": actor_name[:120], "actor_side": "mugo" if is_agency else "cliente", "created_at": now}]
    if destination == "client_review":
        events.append({**events[0], "kind": "enviado_cliente", "internal": False, "comment": None})
    patch: Dict[str, Any] = {"updated_at": now}
    if destination:
        patch["status"] = destination
        if destination == "completed":
            patch.update({"completed_at": now, "approved_at": now})
        if action == "submit":
            patch["approval_round"] = int(task.get("approval_round") or 0) + 1
    rows = await sb_update(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{task_id}",
                                           "status": f"eq.{task['status']}"}, patch=patch) if destination else [task]
    if not rows:
        raise StudioError("STAGE_INVALID", "Alguém mexeu nesta tarefa agora (atualize a tela).")
    for event in events:
        await sb_insert(EVENTS, event)
    return {"task": task_view(rows[0], client_view=not is_agency), "events": await list_events(client_id, task_id, client_view=not is_agency)}


async def list_events(client_id: str, task_id: str, *, client_view: bool) -> List[Dict[str, Any]]:
    filters = {"client_id": f"eq.{client_id}", "task_id": f"eq.{task_id}"}
    if client_view:
        filters["internal"] = "is.false"
    try:
        rows = await sb_select(EVENTS, select="id,kind,internal,comment,actor_name,actor_side,created_at", filters=filters,
                               order="created_at.asc", limit=200)
    except Exception:  # noqa: BLE001 — sem a migração 000096
        return []
    return rows


async def task_history(client_id: str, task_id: str, *, client_view: bool) -> List[Dict[str, Any]]:
    await _owned(client_id, task_id, client_view=client_view)
    return await list_events(client_id, task_id, client_view=client_view)


# ------------------------------------------------------------------ Calendário → Tarefas
# Ajuste pedido num post (cliente ou revisão interna) vira tarefa em "Ajustes" ligada ao post; daí em diante a
# tarefa acompanha o post. A aprovação continua sendo feita no Calendário (link do cliente, Fluxo de aprovação):
# a tarefa é o "a fazer" da equipe e fecha sozinha quando o post é aprovado ou publicado.

CALENDAR_STAGE_TO_TASK = {"rejeitado": "changes", "em_revisao": "internal_review", "aprovado": "completed",
                          "publicado": "completed", "rascunho": "in_progress"}


def _post_title(item: Dict[str, Any]) -> str:
    when = str(item.get("scheduled_at") or "")[:10]
    day = f"{when[8:10]}/{when[5:7]}" if len(when) == 10 else ""
    title = str(item.get("title") or "post sem título").strip()[:150]
    return f"Ajuste: {title}" + (f" ({day})" if day else "")


async def sync_calendar_item(client_id: str, item: Dict[str, Any], *, comment: Optional[str] = None,
                             actor_name: Optional[str] = None, by_client: bool = False, with_client: bool = False) -> Optional[str]:
    """Leva a etapa do post para a tarefa ligada (cria a tarefa quando o post entra em ajuste). Nunca levanta."""
    try:
        status = str(item.get("status") or "")
        target = CALENDAR_STAGE_TO_TASK.get(status)
        if status == "em_revisao" and with_client:
            target = "client_review"  # link de aprovação enviado ao cliente
        if not target or not item.get("id"):
            return None
        item_id = str(item["id"])
        found = await sb_select(TABLE, select="id,status,approval_round", limit=1,
                                filters={"client_id": f"eq.{client_id}", "calendar_item_id": f"eq.{item_id}"})
        now = datetime.now(timezone.utc).isoformat()
        note = str(comment or "").strip()[:2000] or None
        if not found:
            if target != "changes":
                return None  # só ajuste cria tarefa; post sem ajuste segue só no Calendário
            created = await sb_insert(TABLE, {
                "client_id": client_id, "title": _post_title(item), "status": "changes", "category": "Calendário",
                "notes": note, "visible_to_client": False, "needs_client_approval": True, "calendar_item_id": item_id,
                "due_date": str(item.get("scheduled_at") or "")[:10] or None, "approval_round": 1})
            task_id = str((created or {}).get("id") or "")
            if task_id:
                await _event(client_id, task_id, "ajuste_cliente" if by_client else "ajuste_interno", note, actor_name, by_client, now)
            return "created" if task_id else None
        task = found[0]
        if task["status"] == target or task["status"] == "cancelled":
            return "unchanged"
        patch: Dict[str, Any] = {"status": target, "updated_at": now}
        if target == "completed":
            patch.update({"completed_at": now, "approved_at": now})
        if target == "changes":
            patch["approval_round"] = int(task.get("approval_round") or 0) + 1
        await sb_update(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{task['id']}"}, patch=patch, returning="minimal")
        kind = {"changes": "ajuste_cliente" if by_client else "ajuste_interno", "internal_review": "enviado_interno",
                "client_review": "enviado_cliente",
                "completed": "aprovado_cliente" if by_client else "aprovado_interno"}.get(target)
        if kind:
            await _event(client_id, str(task["id"]), kind, note, actor_name, by_client, now)
        return "updated"
    except Exception as exc:  # noqa: BLE001 — sem a migração 000097 ou banco fora: o Calendário segue normal
        print(f"[studio_tasks] calendar_sync_failed client_id={client_id} {type(exc).__name__}")
        return None


async def _event(client_id: str, task_id: str, kind: str, comment: Optional[str], actor_name: Optional[str], by_client: bool, at: str) -> None:
    try:
        await sb_insert(EVENTS, {"client_id": client_id, "task_id": task_id, "kind": kind, "internal": not by_client,
                                 "comment": comment, "actor_id": None, "actor_name": (actor_name or ("Cliente" if by_client else "Equipe Mugô"))[:120],
                                 "actor_side": "cliente" if by_client else "mugo", "created_at": at})
    except Exception as exc:  # noqa: BLE001
        print(f"[studio_tasks] calendar_event_failed {type(exc).__name__}")
