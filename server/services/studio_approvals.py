"""Aprovação do cliente por link, sem login.

Fluxo: a equipe seleciona pautas e gera um pedido → o backend devolve um token
aleatório (só o hash fica no banco) → a equipe manda o link pelo WhatsApp →
o cliente aprova ou pede ajuste em cada pauta → o calendário reflete na hora.

O link expõe apenas os campos editoriais das pautas do pedido (data, formato,
pauta, gancho, legenda) e a arte anexada, por URL assinada de curta duração. Nada de métricas, outras pautas, outras empresas ou
dados de quem criou. Token inválido, expirado ou cancelado responde igual
("link indisponível"), sem revelar se ele existiu.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from .ig_supabase import _is_column_compat_error, sb_insert, sb_select, sb_update
from .studio_calendar import ITEMS_TABLE, StudioError, parse_month

REQUESTS = "studio_approval_requests"
EVENTS = "studio_approval_events"
LINK_DAYS = 14
PUBLIC_FIELDS = "id,scheduled_at,format,pillar,title,hook,caption_draft,status"


def frontend_base_url() -> str:
    explicit = (os.getenv("FRONTEND_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    origins = [o.strip() for o in (os.getenv("ALLOW_ORIGIN") or "").split(",") if o.strip() and o.strip() != "*"]
    return (origins[0] if origins else "http://localhost:5173").rstrip("/")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_phone(raw: Optional[str]) -> Optional[str]:
    text = (raw or "").strip()
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    # "+" ou "00" na frente = número já com DDI (ex.: +34 632 881 089, Espanha): não mexe.
    international = text.startswith("+") or text.startswith("00")
    if text.startswith("00"):
        digits = digits[2:]
    if not international and len(digits) in (10, 11):  # número brasileiro sem DDI
        digits = "55" + digits
    if not 10 <= len(digits) <= 15:
        raise StudioError("PHONE_INVALID", "Telefone inválido. Use DDD + número (fora do Brasil, comece com + e o código do país).")
    return digits


def whatsapp_text(*, client_name: str, contact_name: Optional[str], month_label: str, count: int, link: str,
                  message: Optional[str]) -> str:
    hello = f"Oi, {contact_name.split()[0]}!" if contact_name else "Oi!"
    body = message or (f"Separamos {count} pauta(s) de {month_label} da {client_name} para sua aprovação. "
                       "É só abrir o link, aprovar ou pedir ajuste em cada uma:")
    return f"{hello} {body}\n{link}"


def whatsapp_url(phone: Optional[str], text: str) -> str:
    return f"https://wa.me/{phone or ''}?text={quote(text)}"


async def _client_name(client_id: str) -> str:
    rows = await sb_select("clients", select="id,name,trade_name", filters={"id": f"eq.{client_id}"}, limit=1)
    row = rows[0] if rows else {}
    return str(row.get("trade_name") or row.get("name") or "sua marca")


async def create_request(
    client_id: str, *, month: str, item_ids: List[str], contact_name: Optional[str], contact_phone: Optional[str],
    message: Optional[str], user_id: str, app_origin: str, contact_id: Optional[str] = None,
) -> Dict[str, Any]:
    target = parse_month(month)
    wanted = sorted({str(i) for i in item_ids})
    if not wanted:
        raise StudioError("NO_ITEMS", "Selecione ao menos uma pauta.")
    rows = await sb_select(ITEMS_TABLE, select="id,status,month",
                           filters={"client_id": f"eq.{client_id}", "id": f"in.({','.join(wanted)})"}, limit=len(wanted))
    found = {str(r["id"]) for r in rows if r.get("status") != "rejeitado"}
    if found != set(wanted):
        raise StudioError("ITEMS_INVALID", "Alguma pauta não existe nesta empresa ou está rejeitada.")
    phone = normalize_phone(contact_phone)
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=LINK_DAYS)
    row = {
        "client_id": client_id, "month": target.isoformat(), "token_hash": hash_token(token), "item_ids": wanted,
        "contact_name": (contact_name or "").strip()[:120] or None, "contact_phone": phone,
        "message": (message or "").strip()[:1000] or None, "expires_at": expires.isoformat(), "created_by": user_id,
    }
    try:
        request = await sb_insert(REQUESTS, {**row, "token_ciphertext": _cipher(token), "contact_id": contact_id})
    except httpx.HTTPStatusError as exc:
        # Migration 053 ainda não aplicada: o link funciona, só o lembrete fica indisponível.
        if not _is_column_compat_error(exc, "token_ciphertext"):
            raise
        request = await sb_insert(REQUESTS, row)
    if not request:
        raise StudioError("CREATE_FAILED")
    # Pautas enviadas ficam "em revisão" até o cliente responder (aprovadas continuam aprovadas).
    pending = [i for i in wanted if any(str(r["id"]) == i and r.get("status") != "aprovado" for r in rows)]
    if pending:
        await sb_update(ITEMS_TABLE, filters={"client_id": f"eq.{client_id}", "id": f"in.({','.join(pending)})"},
                        patch={"status": "em_revisao"})
    link = f"{app_origin.rstrip('/')}/aprovar/{token}"
    months = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
              "outubro", "novembro", "dezembro")
    text = whatsapp_text(client_name=await _client_name(client_id), contact_name=request.get("contact_name"),
                         month_label=months[target.month - 1], count=len(wanted), link=link,
                         message=request.get("message"))
    return {"request_id": request["id"], "link": link, "expires_at": expires.isoformat(),
            "whatsapp_text": text, "whatsapp_url": whatsapp_url(phone, text)}


def _cipher(token: str) -> Optional[str]:
    """Token cifrado para reenviar o MESMO link no lembrete. Sem chave de cifra, o lembrete fica indisponível."""
    from .crypto import encrypt_secret
    try:
        return encrypt_secret(token)
    except Exception:
        return None


async def list_requests(client_id: str) -> List[Dict[str, Any]]:
    rows = await sb_select(REQUESTS, select="id,month,item_ids,contact_name,status,expires_at,created_at,completed_at,last_reminded_at",
                           filters={"client_id": f"eq.{client_id}"}, order="created_at.desc", limit=50)
    now = datetime.now(timezone.utc)
    for row in rows:
        row["items"] = len(row.pop("item_ids") or [])
        if row["status"] == "aberto" and datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00")) < now:
            row["status"] = "expirado"
    return rows


async def cancel_request(client_id: str, request_id: str) -> None:
    rows = await sb_update(REQUESTS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{request_id}", "status": "eq.aberto"},
                           patch={"status": "cancelado"})
    if not rows:
        raise StudioError("REQUEST_NOT_FOUND")


# ------------------------------------------------------------------ público

async def _open_request(token: str) -> Dict[str, Any]:
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{30,64}", token):
        raise StudioError("LINK_UNAVAILABLE")
    rows = await sb_select(REQUESTS, select="id,client_id,month,item_ids,contact_name,status,expires_at",
                           filters={"token_hash": f"eq.{hash_token(token)}"}, limit=1)
    request = rows[0] if rows else None
    if not request or request.get("status") == "cancelado":
        raise StudioError("LINK_UNAVAILABLE")
    if datetime.fromisoformat(str(request["expires_at"]).replace("Z", "+00:00")) < datetime.now(timezone.utc):
        raise StudioError("LINK_UNAVAILABLE")
    return request


async def public_view(token: str) -> Dict[str, Any]:
    request = await _open_request(token)
    ids = [str(i) for i in request.get("item_ids") or []]
    items = await sb_select(ITEMS_TABLE, select=PUBLIC_FIELDS,
                            filters={"client_id": f"eq.{request['client_id']}", "id": f"in.({','.join(ids)})"},
                            order="scheduled_at.asc", limit=len(ids))
    events = await sb_select(EVENTS, select="item_id,action,comment,created_at",
                             filters={"request_id": f"eq.{request['id']}"}, order="created_at.desc", limit=500)
    latest: Dict[str, Dict[str, Any]] = {}
    for event in events:
        latest.setdefault(str(event["item_id"]), event)
    return {
        "client_name": await _client_name(request["client_id"]),
        "month": request["month"],
        "contact_name": request.get("contact_name"),
        "status": request["status"],
        "expires_at": request["expires_at"],
        "items": [{**{k: item.get(k) for k in ("id", "scheduled_at", "format", "pillar", "title", "hook", "caption_draft")},
                   "decision": (latest.get(str(item["id"])) or {}).get("action"),
                   "comment": (latest.get(str(item["id"])) or {}).get("comment")} for item in items],
    }


async def public_decide(token: str, item_id: str, *, action: str, comment: Optional[str],
                        reviewer_name: Optional[str]) -> Dict[str, Any]:
    if action not in {"aprovado", "ajuste_solicitado"}:
        raise StudioError("ACTION_INVALID")
    request = await _open_request(token)
    ids = {str(i) for i in request.get("item_ids") or []}
    if str(item_id) not in ids:
        raise StudioError("LINK_UNAVAILABLE")
    comment = (comment or "").strip()[:1000] or None
    if action == "ajuste_solicitado" and not comment:
        raise StudioError("COMMENT_REQUIRED", "Conte o que precisa mudar.")
    reviewer = (reviewer_name or request.get("contact_name") or "Cliente").strip()[:120]
    await sb_insert(EVENTS, {"request_id": request["id"], "client_id": request["client_id"], "item_id": str(item_id),
                             "action": action, "comment": comment, "reviewer_name": reviewer})
    patch = {"status": "aprovado" if action == "aprovado" else "rejeitado",
             "reviewed_by": f"cliente:{reviewer}", "reviewed_at": datetime.now(timezone.utc).isoformat(),
             "review_note": f"Cliente ({reviewer}): {comment}" if comment else None}
    await sb_update(ITEMS_TABLE, filters={"client_id": f"eq.{request['client_id']}", "id": f"eq.{item_id}"}, patch=patch)
    from .studio_team import notify_team
    item = (await sb_select(ITEMS_TABLE, select="id,title,scheduled_at", limit=1,
                            filters={"client_id": f"eq.{request['client_id']}", "id": f"eq.{item_id}"}) or [{"id": item_id}])[0]
    await notify_team(request["client_id"], item, action, actor_name=reviewer, comment=comment)
    decided = {str(e["item_id"]) for e in await sb_select(EVENTS, select="item_id",
                                                           filters={"request_id": f"eq.{request['id']}"}, limit=500)}
    if ids <= decided and request["status"] == "aberto":
        await sb_update(REQUESTS, filters={"id": f"eq.{request['id']}"},
                        patch={"status": "concluido", "completed_at": datetime.now(timezone.utc).isoformat()})
    return {"ok": True, "item_id": str(item_id), "decision": action}


# ------------------------------------------------------------------ funil

STAGES = ("rascunho", "revisao_interna", "com_cliente", "ajuste", "aprovado", "publicado")


def stage_of(item: Dict[str, Any], open_items: Dict[str, Any]) -> str:
    status = item.get("status")
    if status in ("publicado", "aprovado"):
        return status
    if status == "rejeitado":
        return "ajuste"
    if status == "em_revisao":
        return "com_cliente" if str(item.get("id")) in open_items else "revisao_interna"
    return "rascunho"


async def pipeline(client_id: str, month: str) -> Dict[str, Any]:
    """Pautas do mês por etapa, com o pedido aberto e a última resposta do cliente de cada uma."""
    from .studio_calendar import list_items
    target = parse_month(month)
    items = await list_items(client_id, target)
    now = datetime.now(timezone.utc)
    requests = [r for r in await sb_select(REQUESTS, select="id,item_ids,contact_name,status,expires_at,created_at,last_reminded_at",
                                           filters={"client_id": f"eq.{client_id}", "status": "eq.aberto"}, order="created_at.desc", limit=50)
                if datetime.fromisoformat(str(r["expires_at"]).replace("Z", "+00:00")) >= now]
    open_items: Dict[str, Any] = {}
    for request in requests:
        for item_id in request.get("item_ids") or []:
            open_items.setdefault(str(item_id), {"request_id": request["id"], "sent_at": request["created_at"],
                                                 "contact_name": request.get("contact_name"), "expires_at": request["expires_at"],
                                                 "last_reminded_at": request.get("last_reminded_at")})
    latest: Dict[str, Dict[str, Any]] = {}
    if items:
        ids = ",".join(str(i["id"]) for i in items)
        for event in await sb_select(EVENTS, select="item_id,action,comment,reviewer_name,created_at",
                                     filters={"client_id": f"eq.{client_id}", "item_id": f"in.({ids})"}, order="created_at.desc", limit=1000):
            latest.setdefault(str(event["item_id"]), event)
    out = [{**item, "stage": stage_of(item, open_items), "request": open_items.get(str(item["id"])),
            "client_feedback": latest.get(str(item["id"]))} for item in items]
    counts = {stage: sum(1 for i in out if i["stage"] == stage) for stage in STAGES}
    return {"month": target.isoformat(), "stages": list(STAGES), "counts": counts, "items": out}
