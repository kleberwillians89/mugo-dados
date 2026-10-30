"""
O que o CLIENTE vê e pode fazer no calendário (a equipe Mugô continua vendo e fazendo tudo).

Vê: o que está com ele para aprovar, o que pediu ajuste, o aprovado e o publicado. Rascunho e revisão
interna ficam só com a Mugô.
Pode: editar título, gancho, legenda e data/horário; aprovar; pedir ajuste (com comentário).
Toda ação dele avisa o time (tarefa + WhatsApp, via studio_team) e a edição fica marcada no post.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Set

from .ig_supabase import sb_select, sb_update
from .studio_calendar import ITEMS_TABLE, StudioError, update_item
from .studio_team import notify_team

CLIENT_STAGES = ("com_cliente", "ajuste", "aprovado", "publicado")
CLIENT_FIELDS = {"title", "hook", "caption_draft", "scheduled_at", "status", "review_note"}
TEXT_FIELDS = ("title", "hook", "caption_draft", "scheduled_at")
CLIENT_STATUSES = {"aprovado", "rejeitado"}


async def open_request_item_ids(client_id: str) -> Set[str]:
    now = datetime.now(timezone.utc)
    rows = await sb_select("studio_approval_requests", select="item_ids,expires_at",
                           filters={"client_id": f"eq.{client_id}", "status": "eq.aberto"}, limit=50)
    out: Set[str] = set()
    for row in rows:
        if datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00")) >= now:
            out.update(str(i) for i in row.get("item_ids") or [])
    return out


def client_can_see(item: Dict[str, Any], open_ids: Set[str]) -> bool:
    status = item.get("status")
    if status in ("aprovado", "publicado", "rejeitado"):
        return True
    return status == "em_revisao" and str(item.get("id")) in open_ids


async def client_items(client_id: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    open_ids = await open_request_item_ids(client_id)
    return [i for i in items if client_can_see(i, open_ids)]


def _same(field: str, old: Any, new: Any) -> bool:
    if field == "scheduled_at":
        try:
            a = datetime.fromisoformat(str(old).replace("Z", "+00:00"))
            b = datetime.fromisoformat(str(new).replace("Z", "+00:00"))
            return a == b
        except ValueError:
            return False
    return (old or "") == (new or "")


async def client_edit(client_id: str, item_id: str, patch: Dict[str, Any], *, user_id: str, actor_name: str) -> Dict[str, Any]:
    extra = set(patch) - CLIENT_FIELDS
    if extra:
        raise StudioError("CLIENT_FIELD_NOT_ALLOWED")
    rows = await sb_select(ITEMS_TABLE, select="*", filters={"client_id": f"eq.{client_id}", "id": f"eq.{item_id}"}, limit=1)
    if not rows or not client_can_see(rows[0], await open_request_item_ids(client_id)):
        raise StudioError("ITEM_NOT_FOUND")
    current = rows[0]
    status = patch.get("status")
    if status is not None and status not in CLIENT_STATUSES:
        raise StudioError("CLIENT_STATUS_NOT_ALLOWED")
    note = (patch.get("review_note") or "").strip()
    if status == "rejeitado" and not note:
        raise StudioError("COMMENT_REQUIRED")
    changed = [f for f in TEXT_FIELDS if f in patch and not _same(f, current.get(f), patch[f])]
    clean = {k: patch[k] for k in changed}
    if status:
        clean["status"] = status
        clean["review_note"] = f"Cliente ({actor_name}): {note}" if note else None
    if not clean:
        return current
    item = await update_item(client_id, item_id, clean, user_id=user_id)
    if changed:
        fields = sorted(set(current.get("client_edited_fields") or []) | set(changed))
        marked = await sb_update(ITEMS_TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{item_id}"},
                                 patch={"client_edited_at": datetime.now(timezone.utc).isoformat(), "client_edited_by": user_id,
                                        "client_edited_fields": fields})
        item = marked[0] if marked else item
        await notify_team(client_id, item, "editado_pelo_cliente", actor_name=actor_name, comment=note or None, changes=changed)
    if status == "aprovado":
        await notify_team(client_id, item, "aprovado", actor_name=actor_name)
    elif status == "rejeitado":
        await notify_team(client_id, item, "ajuste_solicitado", actor_name=actor_name, comment=note)
    return item
