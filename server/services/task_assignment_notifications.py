"""Private task-assignment inbox and optional, approved WhatsApp notification.

Never posts assignments into the company's shared Studio chat. External delivery
is opt-in, based on a confirmed Supabase Auth phone and a configured, approved
WhatsApp template. Sending failures never undo a successfully created task.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_insert, sb_select, sb_update, sb_upsert

NOTIFICATIONS = "studio_task_notifications"
PREFERENCES = "studio_task_whatsapp_preferences"
FIELDS = "id,task_id,recipient_user_id,title,body,task_url,read_at,whatsapp_status,created_at"


def task_link(task_id: str) -> str:
    from .studio_approvals import frontend_base_url
    return f"{frontend_base_url().rstrip('/')}/tarefas?task={task_id}"


def message_for_task(task: Dict[str, Any]) -> str:
    title = str(task.get("title") or "Nova tarefa").strip()[:200]
    due = str(task.get("due_date") or "")
    hour = str(task.get("due_time") or "")[:5]
    deadline = f"{due[8:10]}/{due[5:7]}/{due[:4]}" if len(due) == 10 else "A definir"
    if hour:
        deadline += f" às {hour}"
    dept = str(task.get("category") or "Equipe").strip()[:60]
    note = str(task.get("notes") or "").strip()[:700]
    return (
        f"Você recebeu uma tarefa no Mugô Dados: {title}\n"
        f"Área: {dept} | Prazo: {deadline}\n"
        + (f"Orientações: {note}\n" if note else "")
        + f"Veja seu cartão: {task_link(str(task['id']))}"
    )[:2000]


async def _verified_auth_phone(user_id: str) -> Optional[str]:
    """Only verified Supabase Auth numbers are valid; never use an arbitrary user input."""
    from .client_access import _admin_request
    response = await _admin_request("GET", f"/users/{user_id}")
    record = response.get("user", response) if isinstance(response, dict) else {}
    if not isinstance(record, dict) or not record.get("phone_confirmed_at"):
        return None
    import re
    digits = re.sub(r"\D", "", str(record.get("phone") or ""))
    return digits if 10 <= len(digits) <= 15 else None


async def _whatsapp_dispatch(client_id: str, user_id: str, body: str, task_id: str = "") -> tuple[str, Optional[str]]:
    if client_id == "pace-sneakers-demo":
        return "skipped_demo", None
    sender_client_id = os.getenv("TASKS_WHATSAPP_SENDER_CLIENT_ID", "").strip()
    template = os.getenv("TASKS_WHATSAPP_TEMPLATE", "").strip()
    if not sender_client_id or not template:
        return "not_configured", None
    prefs = await sb_select(PREFERENCES, select="opted_in",
                            filters={"client_id": f"eq.{client_id}", "user_id": f"eq.{user_id}"}, limit=1)
    if not prefs or prefs[0].get("opted_in") is not True:
        return "not_opted_in", None
    phone = await _verified_auth_phone(user_id)
    if not phone:
        return "not_opted_in", None
    from .whatsapp_native import send_template
    # A template variable must be a single paragraph. The full card stays in the private inbox.
    parameter = " ".join(body.split())[:950]
    try:
        if os.getenv("TASKS_WHATSAPP_TRANSPORT") == "mugozap":
            from .studio_messages import idempotency, mugozap_config, mugozap_send
            cfg = mugozap_config()
            if not cfg:
                return "not_configured", None
            result = await mugozap_send(
                cfg, phone=phone, template_name=template,
                components=[{"type": "body", "parameters": [{"type": "text", "text": parameter}]}],
                idempotency_key=idempotency("task-assignment", client_id, task_id, user_id),
            )
            provider_id = result.get("provider_message_id") if result.get("ok") else None
        else:
            provider_id = await send_template(sender_client_id, number_id=None, to=phone, template=template,
                                              language="pt_BR", params=[parameter])
        return ("sent", provider_id) if provider_id else ("failed", None)
    except Exception as exc:  # noqa: BLE001 — notification is best-effort, task persists
        print(f"[task_notification] whatsapp_failed type={type(exc).__name__}")
        return "failed", None


async def notify_assignment(client_id: str, task: Dict[str, Any], *, send_whatsapp: bool = False) -> int:
    """One notification per assigned person/task, including multi-assignee cards."""
    task_id = str(task.get("id") or "")
    ids = [str(item) for item in (task.get("assignee_user_ids") or []) if item]
    if not ids and task.get("assignee_user_id"):
        ids = [str(task["assignee_user_id"])]
    if not task_id or not ids:
        return 0
    sent = 0
    for user_id in dict.fromkeys(ids):
        try:
            body = message_for_task(task)
            row = await sb_insert(NOTIFICATIONS, {
                "client_id": client_id, "task_id": task_id, "recipient_user_id": user_id,
                "title": str(task.get("title") or "Nova tarefa")[:200],
                "body": body, "task_url": task_link(task_id), "whatsapp_status": "pending",
            })
            if not row:
                continue
            status, provider_id = (await _whatsapp_dispatch(client_id, user_id, body, task_id)
                                   if send_whatsapp else ("not_configured", None))
            await sb_update(NOTIFICATIONS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{row['id']}"},
                            patch={"whatsapp_status": status, "whatsapp_message_id": provider_id},
                            returning="minimal")
            sent += 1
        except Exception as exc:  # noqa: BLE001 — don't fail task creation on delivery
            print(f"[task_notification] record_or_dispatch_failed type={type(exc).__name__}")
    return sent


async def inbox(client_id: str, user_id: str) -> Dict[str, Any]:
    rows = await sb_select(NOTIFICATIONS, select=FIELDS, limit=100,
                           order="created_at.desc",
                           filters={"client_id": f"eq.{client_id}", "recipient_user_id": f"eq.{user_id}"})
    return {"messages": [{key: val for key, val in row.items() if key != "recipient_user_id"}
                         for row in rows],
            "unread": sum(1 for row in rows if not row.get("read_at"))}


async def read_message(client_id: str, user_id: str, notification_id: str) -> bool:
    rows = await sb_update(NOTIFICATIONS,
                           filters={"client_id": f"eq.{client_id}", "recipient_user_id": f"eq.{user_id}",
                                    "id": f"eq.{notification_id}"},
                           patch={"read_at": datetime.now(timezone.utc).isoformat()})
    return bool(rows)


async def preference(client_id: str, user_id: str) -> Dict[str, Any]:
    rows = await sb_select(PREFERENCES, select="opted_in", limit=1,
                           filters={"client_id": f"eq.{client_id}", "user_id": f"eq.{user_id}"})
    configured = bool(os.getenv("TASKS_WHATSAPP_SENDER_CLIENT_ID") and os.getenv("TASKS_WHATSAPP_TEMPLATE"))
    if configured and os.getenv("TASKS_WHATSAPP_TRANSPORT") == "mugozap":
        from .studio_messages import mugozap_config
        configured = bool(mugozap_config())
    return {"whatsapp_opt_in": bool(rows and rows[0].get("opted_in")), "provider_configured": configured}


async def set_preference(client_id: str, user_id: str, opted_in: bool) -> Dict[str, Any]:
    if opted_in and not await _verified_auth_phone(user_id):
        raise ValueError("Adicione e confirme seu telefone na conta antes de habilitar avisos por WhatsApp.")
    await sb_upsert(PREFERENCES, [{"client_id": client_id, "user_id": user_id, "opted_in": opted_in,
                                  "updated_at": datetime.now(timezone.utc).isoformat()}],
                    on_conflict="client_id,user_id")
    return await preference(client_id, user_id)
