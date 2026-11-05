"""Conversa da marca (Calendário → painel do cliente) e linha do tempo.

Dois canais por marca:
- "cliente": cliente e equipe Mugô no mesmo fio. Mensagem do cliente avisa o time pelo mesmo caminho
  dos comentários (studio_team.notify_team → tarefa no CRM + WhatsApp do time).
- "equipe": só a equipe Mugô; o cliente nunca lê nem escreve aqui.

A linha do tempo não grava nada novo: junta o que já existe (ações do cliente, pedidos de aprovação,
comentários e referências da equipe) em ordem de data.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .ig_supabase import _request, sb_insert, sb_select
from .studio_calendar import ITEMS_TABLE, StudioError

MESSAGES = "studio_chat_messages"
READS = "studio_chat_reads"
CHANNELS = ("cliente", "equipe")
MAX_BODY = 4000
SELECT = "id,channel,author_id,author_side,author_name,body,item_id,created_at"


def check_channel(channel: str, *, agency: bool) -> str:
    if channel not in CHANNELS:
        raise StudioError("CHAT_CHANNEL_INVALID")
    if channel == "equipe" and not agency:
        raise StudioError("CHAT_FORBIDDEN")
    return channel


def author_name_from_claims(claims: Dict[str, Any]) -> str:
    meta = claims.get("user_metadata") or {}
    name = str(meta.get("full_name") or meta.get("name") or "").strip()
    if not name:
        name = str(claims.get("email") or "").split("@")[0]
    return re.sub(r"\s+", " ", name)[:80] or "Equipe"


async def _titles(client_id: str, ids: List[str]) -> Dict[str, str]:
    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    rows = await sb_select(ITEMS_TABLE, select="id,title", limit=len(ids),
                           filters={"client_id": f"eq.{client_id}", "id": f"in.({','.join(ids)})"})
    return {str(r["id"]): str(r.get("title") or "Post") for r in rows}


async def list_messages(client_id: str, channel: str, *, agency: bool, user_id: Optional[str]) -> List[Dict[str, Any]]:
    check_channel(channel, agency=agency)
    rows = await sb_select(MESSAGES, select=SELECT, order="created_at.desc", limit=200,
                           filters={"client_id": f"eq.{client_id}", "channel": f"eq.{channel}"})
    rows.reverse()
    titles = await _titles(client_id, [str(r.get("item_id") or "") for r in rows])
    return [{**{k: v for k, v in r.items() if k != "author_id"}, "mine": bool(user_id) and str(r.get("author_id") or "") == user_id,
             "item_title": titles.get(str(r.get("item_id") or "")) if r.get("item_id") else None} for r in rows]


async def post_message(client_id: str, channel: str, body: str, *, agency: bool, user_id: Optional[str],
                       author_name: str, item_id: Optional[str] = None) -> Dict[str, Any]:
    check_channel(channel, agency=agency)
    text = re.sub(r"[ \t]+", " ", str(body or "")).strip()[:MAX_BODY]
    if not text:
        raise StudioError("CHAT_BODY_REQUIRED")
    item: Optional[Dict[str, Any]] = None
    if item_id:
        from .studio_comments import _item
        item = await _item(client_id, item_id, agency=agency)  # cliente só cita post que pode ver
    side = "mugo" if agency else "cliente"
    row = await sb_insert(MESSAGES, {"client_id": client_id, "channel": channel, "author_id": user_id, "author_side": side,
                                     "author_name": author_name[:80], "body": text, "item_id": item["id"] if item else None})
    if not agency:
        from .studio_team import notify_team
        await notify_team(client_id, item or {"id": None, "title": "Conversa da marca", "status": "conversa", "scheduled_at": None},
                          "comentario", actor_name=f"{author_name} (cliente) pela conversa", comment=text)
    if user_id:
        await mark_read(client_id, channel, user_id)
    out = row or {"channel": channel, "author_side": side, "author_name": author_name, "body": text}
    return {**{k: v for k, v in out.items() if k != "author_id"}, "mine": True, "item_title": (item or {}).get("title")}


async def mark_read(client_id: str, channel: str, user_id: str) -> None:
    await _request("POST", f"/{READS}", params={"on_conflict": "user_id,client_id,channel"},
                   json={"user_id": user_id, "client_id": client_id, "channel": channel,
                         "last_read_at": datetime.now(timezone.utc).isoformat()},
                   headers={"Prefer": "resolution=merge-duplicates,return=minimal"})


async def unread(client_id: str, *, agency: bool, user_id: str) -> Dict[str, int]:
    channels = CHANNELS if agency else ("cliente",)
    reads = await sb_select(READS, select="channel,last_read_at", limit=5,
                            filters={"client_id": f"eq.{client_id}", "user_id": f"eq.{user_id}"})
    seen = {r["channel"]: r["last_read_at"] for r in reads}
    out: Dict[str, int] = {}
    for ch in channels:
        filters = {"client_id": f"eq.{client_id}", "channel": f"eq.{ch}", "author_id": f"neq.{user_id}"}
        if seen.get(ch):
            filters["created_at"] = f"gt.{seen[ch]}"
        rows = await sb_select(MESSAGES, select="id", limit=99, filters=filters)
        out[ch] = len(rows)
    return out


TEAM_ACTION = {"aprovado": "aprovou", "ajuste_solicitado": "pediu ajuste em", "editado_pelo_cliente": "editou", "comentario": "comentou em"}


async def _safe(coro) -> List[Dict[str, Any]]:
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001 — uma fonte fora não derruba a linha do tempo
        print(f"[studio_chat] timeline_source_failed error_type={exc.__class__.__name__}")
        return []


async def timeline(client_id: str, limit: int = 60) -> List[Dict[str, Any]]:
    """Eventos recentes da marca, mais novos primeiro. Nada interno do time (canal equipe) entra aqui."""
    cid = {"client_id": f"eq.{client_id}"}
    team = await _safe(sb_select("studio_team_events", select="id,item_id,action,actor_name,payload,created_at",
                                 order="created_at.desc", limit=limit, filters=cid))
    requests = await _safe(sb_select("studio_approval_requests", select="id,item_ids,contact_name,status,created_at,completed_at",
                                     order="created_at.desc", limit=20, filters=cid))
    comments = await _safe(sb_select("studio_item_comments", select="id,item_id,body,created_at", order="created_at.desc",
                                     limit=30, filters={**cid, "author_side": "eq.mugo"}))
    refs = await _safe(sb_select("studio_references", select="id,url,note,created_at", order="created_at.desc",
                                 limit=20, filters={**cid, "author_side": "eq.mugo"}))
    titles = await _safe(_titles(client_id, [str(c.get("item_id") or "") for c in comments])) or {}
    events: List[Dict[str, Any]] = []
    for e in team:
        payload = e.get("payload") or {}
        title = payload.get("title") or "um post"
        verb = TEAM_ACTION.get(e.get("action"), e.get("action"))
        events.append({"id": f"t-{e['id']}", "at": e["created_at"], "side": "cliente", "kind": e.get("action"),
                       "text": f"{e.get('actor_name') or 'O cliente'} {verb} “{title}”", "detail": payload.get("comment"),
                       "item_id": e.get("item_id"), "actor": e.get("actor_name") or "O cliente", "title": payload.get("title"),
                       "changes": payload.get("changes") or []})
    for r in requests:
        n = len(r.get("item_ids") or [])
        events.append({"id": f"r-{r['id']}", "at": r["created_at"], "side": "mugo", "kind": "pedido",
                       "text": f"Mugô enviou {n} post{'s' if n != 1 else ''} para aprovação" + (f" a {r['contact_name']}" if r.get("contact_name") else ""),
                       "detail": None, "item_id": None})
        if r.get("status") == "concluido" and r.get("completed_at"):
            events.append({"id": f"rc-{r['id']}", "at": r["completed_at"], "side": "cliente", "kind": "pedido_concluido",
                           "text": "Pedido de aprovação concluído", "detail": None, "item_id": None})
    for c in comments:
        events.append({"id": f"c-{c['id']}", "at": c["created_at"], "side": "mugo", "kind": "comentario_mugo",
                       "text": f"Mugô comentou em “{titles.get(str(c.get('item_id')), 'um post') if isinstance(titles, dict) else 'um post'}”",
                       "detail": c.get("body"), "item_id": c.get("item_id")})
    for f in refs:
        events.append({"id": f"f-{f['id']}", "at": f["created_at"], "side": "mugo", "kind": "referencia",
                       "text": "Mugô adicionou uma referência", "detail": f.get("note") or f.get("url"), "item_id": None})
    events.sort(key=lambda x: str(x["at"]), reverse=True)
    return events[:limit]
