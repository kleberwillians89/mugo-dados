"""WhatsApp da marca: números (origem → venda) e caixa de entrada do número da própria marca.

Números: qualquer membro da empresa (são da empresa ativa, revalidada no backend).
Caixa de entrada e mensagens: agência e admin da marca — é conversa com cliente final.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from services.whatsapp_sources import brand_messages
from services.studio_calendar import StudioError
from services.tenant import require_client_read, require_client_role
from services.whatsapp_insights import build_whatsapp_inbox, build_whatsapp_insights
from services.whatsapp_native import WhatsAppNativeError, disconnect_number, list_numbers, register_number

router = APIRouter(prefix="/api/clients/{client_id}/whatsapp", tags=["whatsapp"])

INBOX_ROLES = ("agency_admin", "client_admin")


@router.get("")
async def read_whatsapp_insights(client_id: str, start: date | None = None, end: date | None = None,
                                 authorization: Optional[str] = Header(None)):
    cid = await require_client_read(client_id, authorization)
    if start and end and (end < start or (end - start).days > 366):
        raise HTTPException(422, "Período inválido.")
    try:
        return await build_whatsapp_insights(cid, start=start.isoformat() if start else None, end=end.isoformat() if end else None)
    except StudioError:
        raise HTTPException(502, "O CRM não respondeu agora. Tente de novo em instantes.") from None
    except Exception as exc:
        print(f"[whatsapp_insights] client_id={cid} status=error error_type={exc.__class__.__name__}")
        raise HTTPException(503, "Não foi possível carregar o WhatsApp agora. Tente novamente.") from None


@router.get("/inbox")
async def read_whatsapp_inbox(client_id: str, limit: int = 60, authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=INBOX_ROLES)
    try:
        return await build_whatsapp_inbox(cid, limit=max(1, min(int(limit), 200)))
    except StudioError:
        raise HTTPException(502, "O CRM não respondeu agora. Tente de novo em instantes.") from None
    except Exception as exc:
        print(f"[whatsapp_inbox] client_id={cid} status=error error_type={exc.__class__.__name__}")
        raise HTTPException(503, "Não foi possível carregar as conversas agora.") from None


@router.get("/conversations/{conversation_id}/messages")
async def read_whatsapp_messages(client_id: str, conversation_id: str, limit: int = 100,
                                 authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=INBOX_ROLES)
    try:
        return await brand_messages(cid, conversation_id, limit=limit)
    except StudioError as exc:
        if exc.code == "CONVERSATION_NOT_FOUND":
            raise HTTPException(404, "Conversa não encontrada para esta empresa.") from None
        raise HTTPException(502, "Não foi possível abrir a conversa agora.") from None


# ---- Números ligados direto no MUGOVERSO (app da Mugô na Meta). Só a agência cadastra e vê.
NUMBER_ROLES = ("agency_admin",)


class NumberIn(BaseModel):
    waba_id: str = Field(min_length=5, max_length=30)
    phone_number_id: str = Field(min_length=5, max_length=30)
    access_token: str = Field(min_length=20, max_length=2000)


@router.get("/numbers")
async def read_whatsapp_numbers(client_id: str, authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=NUMBER_ROLES)
    return {"ok": True, "numbers": await list_numbers(cid)}


@router.post("/numbers")
async def create_whatsapp_number(client_id: str, payload: NumberIn, authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=NUMBER_ROLES)
    try:
        number = await register_number(cid, waba_id=payload.waba_id, phone_number_id=payload.phone_number_id,
                                       access_token=payload.access_token)
    except WhatsAppNativeError as exc:
        status = 409 if exc.code == "NUMBER_IN_USE" else 502 if exc.code in {"META_UNREACHABLE", "META_FAILED"} else 422
        raise HTTPException(status, exc.message) from None
    return {"ok": True, "number": number}


@router.delete("/numbers/{number_id}")
async def delete_whatsapp_number(client_id: str, number_id: str, authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=NUMBER_ROLES)
    if not await disconnect_number(cid, number_id):
        raise HTTPException(404, "Número não encontrado para esta empresa.")
    return {"ok": True}


# ---- Instagram Direct da marca na mesma tela (gravado pelo webhook instagram-webhook).
class InstagramReply(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


_IG_ERRORS = {
    "CONVERSATION_NOT_FOUND": (404, "Conversa não encontrada para esta empresa."),
    "DIRECT_WINDOW_CLOSED": (409, "Passou de 24 h desde a última mensagem da pessoa: o Instagram só deixa responder dentro desse prazo."),
    "REPLY_EMPTY": (422, "Escreva a resposta."),
    "IG_NOT_CONNECTED": (409, "Instagram não conectado: conecte em Integrações."),
    "IG_PAGE_NOT_FOUND": (409, "Não achei a página do Facebook ligada a este Instagram: reconecte em Integrações."),
    "IG_PERMISSION_MISSING": (409, "Falta permissão de mensagens no login do Meta: reconecte o Instagram em Integrações."),
}


def _ig_http(exc: StudioError) -> HTTPException:
    status, detail = _IG_ERRORS.get(exc.code, (502, "O Instagram não aceitou agora. Tente de novo em instantes."))
    return HTTPException(status, detail)


@router.get("/instagram")
async def read_instagram_inbox(client_id: str, authorization: Optional[str] = Header(None)):
    from services.ig_direct import inbox
    cid = await require_client_role(client_id, authorization, allowed_roles=INBOX_ROLES)
    return await inbox(cid)


@router.get("/instagram/{sender_id}")
async def read_instagram_thread(client_id: str, sender_id: str, authorization: Optional[str] = Header(None)):
    from services.ig_direct import thread_messages
    cid = await require_client_role(client_id, authorization, allowed_roles=INBOX_ROLES)
    if not sender_id.isdigit() or len(sender_id) > 40:
        raise HTTPException(404, "Conversa não encontrada para esta empresa.")
    try:
        return await thread_messages(cid, sender_id)
    except StudioError as exc:
        raise _ig_http(exc) from None


@router.post("/instagram/{sender_id}/reply")
async def reply_instagram_thread(client_id: str, sender_id: str, body: InstagramReply, authorization: Optional[str] = Header(None)):
    from services.ig_direct import manual_reply
    cid = await require_client_role(client_id, authorization, allowed_roles=INBOX_ROLES)
    if not sender_id.isdigit() or len(sender_id) > 40:
        raise HTTPException(404, "Conversa não encontrada para esta empresa.")
    try:
        return await manual_reply(cid, sender_id, body.text)
    except StudioError as exc:
        raise _ig_http(exc) from None
