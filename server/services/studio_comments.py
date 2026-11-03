"""
Comentários nos posts do Calendário (cliente e equipe Mugô no mesmo fio).

Cliente (inclusive leitor) comenta só nos posts que pode ver. Comentário do cliente avisa o time
(tarefa no CRM + WhatsApp) pelo mesmo caminho de aprovação/ajuste (studio_team.notify_team).
Nada de nome ou e-mail exposto: aparece "Cliente" ou "Equipe Mugô".
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_insert, sb_select
from .studio_calendar import ITEMS_TABLE, StudioError
from .studio_client import client_can_see, open_request_item_ids
from .studio_team import notify_team

COMMENTS = "studio_item_comments"
MAX_BODY = 2000


async def _item(client_id: str, item_id: str, *, agency: bool) -> Dict[str, Any]:
    rows = await sb_select(ITEMS_TABLE, select="id,title,status,scheduled_at", limit=1,
                           filters={"client_id": f"eq.{client_id}", "id": f"eq.{item_id}"})
    if not rows or (not agency and not client_can_see(rows[0], await open_request_item_ids(client_id))):
        raise StudioError("ITEM_NOT_FOUND")
    return rows[0]


async def list_comments(client_id: str, item_id: str, *, agency: bool) -> List[Dict[str, Any]]:
    await _item(client_id, item_id, agency=agency)
    return await sb_select(COMMENTS, select="id,author_side,author_name,body,created_at", order="created_at.asc", limit=200,
                           filters={"client_id": f"eq.{client_id}", "item_id": f"eq.{item_id}"})


async def add_comment(client_id: str, item_id: str, body: str, *, agency: bool, user_id: Optional[str]) -> Dict[str, Any]:
    text = re.sub(r"[ \t]+", " ", str(body or "")).strip()[:MAX_BODY]
    if not text:
        raise StudioError("COMMENT_REQUIRED")
    item = await _item(client_id, item_id, agency=agency)
    side = "mugo" if agency else "cliente"
    row = await sb_insert(COMMENTS, {"client_id": client_id, "item_id": item_id, "author_id": user_id, "author_side": side,
                                     "author_name": "Equipe Mugô" if agency else "Cliente", "body": text})
    if not agency:
        await notify_team(client_id, item, "comentario", actor_name="O cliente pelo painel", comment=text)
    return row or {"author_side": side, "body": text}
