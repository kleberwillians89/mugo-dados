"""
Aviso ao time quando o CLIENTE mexe no conteúdo (aprovou, pediu ajuste ou editou).

Cada ação vira uma linha em studio_team_events ANTES de falar com o CRM: se o CRM estiver fora,
nada se perde — a linha fica "pendente" e o job reenvia. No CRM vira tarefa para o responsável
pelo cliente + WhatsApp do time (função dados-ops-events). A ação do cliente nunca falha por causa disso.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .crm_bridge import post_event
from .ig_supabase import sb_insert, sb_select, sb_update

EVENTS = "studio_team_events"
ACTIONS = ("aprovado", "ajuste_solicitado", "editado_pelo_cliente")
MAX_ATTEMPTS = 8
FIELD_LABELS = {"title": "título", "hook": "gancho", "caption_draft": "legenda", "scheduled_at": "data"}


def _event_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    from .studio_approvals import frontend_base_url
    payload = row.get("payload") or {}
    return {"event_id": row["id"], "action": row["action"], "actor_name": row.get("actor_name"),
            "title": payload.get("title"), "comment": payload.get("comment"), "changes": payload.get("changes") or [],
            "scheduled_at": payload.get("scheduled_at"), "link": f"{frontend_base_url()}/aprovacao"}


async def _send(row: Dict[str, Any]) -> bool:
    result = await post_event(row["client_id"], "content_feedback", _event_payload(row))
    attempts = int(row.get("attempts") or 0) + 1
    if result.get("ok"):
        await sb_update(EVENTS, filters={"id": f"eq.{row['id']}"},
                        patch={"status": "enviado", "attempts": attempts, "sent_at": datetime.now(timezone.utc).isoformat(),
                               "crm_task_id": result.get("task_id"), "last_error": None})
        return True
    # Cliente ainda não ligado ao CRM não é falha passageira: não fica tentando para sempre.
    final = result.get("code") == "UNKNOWN_EXTERNAL_CLIENT" or attempts >= MAX_ATTEMPTS
    await sb_update(EVENTS, filters={"id": f"eq.{row['id']}"},
                    patch={"status": "ignorado" if final else "pendente", "attempts": attempts, "last_error": str(result.get("code"))[:80]})
    return False


async def notify_team(client_id: str, item: Dict[str, Any], action: str, *, actor_name: Optional[str],
                      comment: Optional[str] = None, changes: Optional[List[str]] = None) -> Optional[str]:
    """Registra e tenta avisar já. Nunca levanta: a ação do cliente vale mesmo com o CRM fora do ar."""
    if action not in ACTIONS:
        return None
    try:
        row = {"id": str(uuid.uuid4()), "client_id": client_id, "item_id": str(item.get("id")), "action": action,
               "actor_name": (actor_name or "O cliente")[:120],
               "payload": {"title": str(item.get("title") or "")[:200], "comment": (comment or None) and comment[:1000],
                           "changes": [FIELD_LABELS.get(c, c) for c in (changes or [])], "scheduled_at": item.get("scheduled_at")},
               "status": "pendente", "attempts": 0}
        await sb_insert(EVENTS, row)
        await _send(row)
        return row["id"]
    except Exception as exc:  # noqa: BLE001 — aviso é complemento; nunca derruba a ação do cliente
        print(f"[studio_team] client_id={client_id} action={action} notify_failed={type(exc).__name__}")
        return None


async def retry_pending(limit: int = 50) -> Dict[str, int]:
    rows = await sb_select(EVENTS, select="id,client_id,item_id,action,actor_name,payload,attempts",
                           filters={"status": "eq.pendente"}, order="created_at.asc", limit=limit)
    sent = 0
    for row in rows:
        try:
            sent += 1 if await _send(row) else 0
        except Exception as exc:  # noqa: BLE001
            print(f"[studio_team] retry_failed id={row.get('id')} {type(exc).__name__}")
    return {"pending": len(rows), "sent": sent}
