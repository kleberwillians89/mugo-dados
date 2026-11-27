"""Entrega e reprocessa efeitos externos das tarefas.

O Kanban permanece a fonte operacional. O CRM recebe somente notificacoes com
``event_id`` idempotente; falhas ficam registradas para nova tentativa.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from .crm_bridge import post_event
from .ig_supabase import sb_select, sb_update

TABLE = "studio_task_sync_outbox"
MAX_ATTEMPTS = 8


async def deliver(row: Dict[str, Any]) -> bool:
    if row.get("kind") != "crm_notification" or row.get("status") == "sent":
        return row.get("status") == "sent"
    payload = dict(row.get("payload") or {})
    result = await post_event(str(row["client_id"]), "task_decision", {"event_id": str(row["id"]), **payload})
    attempts = int(row.get("attempts") or 0) + 1
    now = datetime.now(timezone.utc).isoformat()
    if result.get("ok"):
        await sb_update(TABLE, filters={"id": f"eq.{row['id']}", "client_id": f"eq.{row['client_id']}"},
                        patch={"status": "sent", "attempts": attempts, "last_error": None,
                               "sent_at": now, "updated_at": now}, returning="minimal")
        return True
    final = attempts >= MAX_ATTEMPTS or result.get("code") in {"UNKNOWN_EXTERNAL_CLIENT", "not_configured"}
    await sb_update(TABLE, filters={"id": f"eq.{row['id']}", "client_id": f"eq.{row['client_id']}"},
                    patch={"status": "failed", "attempts": attempts,
                           "last_error": str(result.get("code") or "unknown")[:120], "updated_at": now},
                    returning="minimal")
    return False


async def retry_pending(limit: int = 50) -> Dict[str, int]:
    rows = await sb_select(TABLE, select="id,client_id,kind,payload,status,attempts", limit=limit,
                           filters={"status": "in.(pending,failed)", "attempts": f"lt.{MAX_ATTEMPTS}"},
                           order="created_at.asc")
    sent = 0
    for row in rows:
        try:
            sent += 1 if await deliver(row) else 0
        except Exception as exc:  # noqa: BLE001 - permanece pendente/observavel
            print(f"[task_sync] retry_failed id={row.get('id')} error_type={type(exc).__name__}")
    return {"pending": len(rows), "sent": sent}
