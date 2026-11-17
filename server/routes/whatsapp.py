"""WhatsApp da marca: números (origem → venda) e caixa de entrada do número da própria marca.

Números: qualquer membro da empresa (são da empresa ativa, revalidada no backend).
Caixa de entrada e mensagens: agência e admin da marca — é conversa com cliente final.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from services.whatsapp_sources import brand_messages, brand_reply
from services.studio_calendar import StudioError
from services.tenant import require_client_read, require_client_role
from services.whatsapp_insights import build_whatsapp_inbox, build_whatsapp_insights
from services.whatsapp_native import WhatsAppNativeError, disconnect_number, list_numbers, register_number, list_templates, create_template

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


class WhatsAppReply(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


_REPLY_ERRORS = {
    "CONVERSATION_NOT_FOUND": 404, "EMPTY_MESSAGE": 422, "OUTSIDE_WINDOW": 409, "REPLY_UNSUPPORTED": 409,
    "CRM_UNREACHABLE": 502, "SEND_FAILED": 502,
}


@router.post("/conversations/{conversation_id}/reply")
async def reply_whatsapp_conversation(client_id: str, conversation_id: str, body: WhatsAppReply,
                                      authorization: Optional[str] = Header(None)):
    """Equipe (agência ou admin da marca) responde a conversa pelo número da marca."""
    from services.tenant import is_agency_user
    cid = await require_client_role(client_id, authorization, allowed_roles=INBOX_ROLES)
    author = "equipe Mugô" if await is_agency_user(authorization) else "equipe da marca"
    try:
        return await brand_reply(cid, conversation_id, body.text, author=author)
    except StudioError as exc:
        status = _REPLY_ERRORS.get(exc.code, 502)
        detail = str(exc) if str(exc) and str(exc) != exc.code else "Não foi possível enviar agora."
        if exc.code == "CONVERSATION_NOT_FOUND":
            detail = "Conversa não encontrada para esta empresa."
        raise HTTPException(status, detail) from None


# ---- Números ligados direto no MUGOVERSO (app da Mugô na Meta). Só a agência cadastra e vê.
NUMBER_ROLES = ("agency_admin",)


class NumberIn(BaseModel):
    waba_id: str = Field(min_length=5, max_length=30)
    phone_number_id: str = Field(min_length=5, max_length=30)
    access_token: str = Field(min_length=20, max_length=2000)


@router.get("/connection-status")
async def whatsapp_connection_status(client_id: str, authorization: Optional[str] = Header(None)):
    """Connection overview for any tenant, never returning credentials.

    A CRM bridge key does NOT constitute a Meta WhatsApp Cloud API token.
    The UI should distinguish these providers instead of suggesting token reuse.
    """
    cid = await require_client_role(client_id, authorization, allowed_roles=NUMBER_ROLES)
    from services.whatsapp_sources import bridge_for
    from services.crm_bridge import brand_conversations as crm_brand_conversations, _config as crm_config
    from services.studio_calendar import StudioError

    numbers = await list_numbers(cid)
    active = [number for number in numbers if number.get("status") == "active"]
    brand_bridge = bool(bridge_for(cid))
    crm_connected = False
    crm_unavailable = False
    if not active and not brand_bridge and crm_config():
        # CRM Mugô is a per-company bridge. The global server credentials alone
        # do NOT prove this particular tenant owns a connected WhatsApp number.
        try:
            state = await crm_brand_conversations(cid, limit=1)
            crm_connected = bool(state.get("available") and state.get("connected"))
            crm_unavailable = not bool(state.get("available"))
        except StudioError:
            crm_unavailable = True
    provider = ("native" if active else "crm_bridge" if brand_bridge
                else "mugozap_crm" if crm_connected else "not_connected")
    is_connected = bool(active or brand_bridge or crm_connected)
    notice = (
        "Número Cloud API cadastrado e credencial protegida no Mugô Dados."
        if active else
        "WhatsApp conectado pelo CRM próprio. As conversas são mantidas nessa integração."
        if brand_bridge else
        "WhatsApp conectado pelo CRM Mugô (MugôZap), com as conversas acessíveis pela ponte."
        if crm_connected else
        "Não foi possível confirmar a conexão do CRM neste momento. Confira as conversas antes de cadastrar outro número."
        if crm_unavailable else
        "Nenhuma conexão WhatsApp ativa identificada para esta empresa."
    )
    return {
        "ok": True,
        "client_id": cid,
        "provider": provider,
        "connected": is_connected,
        "native_connected": bool(active),
        "crm_bridge_configured": brand_bridge or crm_connected,
        "meta_credentials_saved": bool(active),
        "number_count": len(active),
        "numbers": active,
        "requires_meta_credentials": not bool(active),
        "notice": notice,
        "crm_status_unavailable": crm_unavailable,
    }


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


# ---- Biblioteca por WABA: criar modelos e acompanhar aprovação na Meta.
# Nenhum endpoint daqui dispara mensagens aos contatos.
TEMPLATE_ROLES = ("agency_admin", "client_admin")


class TemplateIn(BaseModel):
    number_id: Optional[str] = Field(default=None, max_length=50)
    name: str = Field(min_length=3, max_length=81)
    category: str = Field(pattern="^(MARKETING|UTILITY)$")
    language: str = Field(default="pt_BR", pattern="^(pt_BR|en_US|es_ES)$")
    body: str = Field(min_length=1, max_length=1024)
    footer: str = Field(default="", max_length=60)
    examples: list[str] = Field(default_factory=list, max_length=5)


@router.get("/templates")
async def read_whatsapp_templates(client_id: str, number_id: Optional[str] = None,
                                  authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=TEMPLATE_ROLES)
    try:
        return {"ok": True, "templates": await list_templates(cid, number_id)}
    except WhatsAppNativeError as exc:
        raise HTTPException(422 if exc.code in {"NOT_FOUND", "TEMPLATE_INVALID"} else 502, exc.message) from None


@router.post("/templates", status_code=201)
async def submit_whatsapp_template(client_id: str, payload: TemplateIn,
                                   authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=TEMPLATE_ROLES)
    try:
        template = await create_template(cid, number_id=payload.number_id, name=payload.name,
                                         category=payload.category, language=payload.language,
                                         body=payload.body, examples=payload.examples, footer=payload.footer)
    except WhatsAppNativeError as exc:
        raise HTTPException(422 if exc.code in {"NOT_FOUND", "TEMPLATE_INVALID"} else 502, exc.message) from None
    return {"ok": True, "template": template}


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
