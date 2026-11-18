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
from services.whatsapp_native import WhatsAppNativeError, disconnect_number, get_roove_registration_status, register_roove_cloud_number, request_roove_verification_code, verify_roove_verification_code, list_numbers, register_number, list_templates, create_template

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
    meta_app_id: Optional[str] = Field(default=None, pattern=r"^[0-9]{5,30}$")


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
        if not crm_connected:
            # Mugô owns its CRM number at the organization level, not as a
            # normal CRM client. Only an explicit org link can authorize it.
            from services.crm_whatsapp_templates import connection_status as crm_templates_connected
            try:
                crm_connected = await crm_templates_connected(cid)
                if crm_connected:
                    crm_unavailable = False
            except StudioError:
                pass
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
                                       access_token=payload.access_token, meta_app_id=payload.meta_app_id)
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


class RooveCloudRegistrationIn(BaseModel):
    pin: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")
    confirmed: bool = Field(default=False)


class RooveVerificationRequestIn(BaseModel):
    method: str = Field(pattern=r"^(SMS|VOICE)$")
    confirmed: bool = Field(default=False)


class RooveVerificationConfirmIn(BaseModel):
    code: str = Field(min_length=4, max_length=8, pattern=r"^[0-9]{4,8}$")
    confirmed: bool = Field(default=False)


def _roove_meta_error(exc: WhatsAppNativeError) -> HTTPException:
    status = (
        404 if exc.code == "NOT_FOUND" else
        409 if exc.code in {"CONFIRMATION_REQUIRED", "STATUS_UNKNOWN", "REGISTRATION_UNSAFE",
                            "NOT_IN_WABA", "ALREADY_VERIFIED", "VERIFICATION_REQUIRED"} else
        422 if exc.code in {"PIN_INVALID", "CODE_INVALID", "METHOD_INVALID"} else 502
    )
    return HTTPException(status, exc.message)


@router.post("/numbers/{number_id}/meta-request-code")
async def whatsapp_roove_request_code(client_id: str, number_id: str, payload: RooveVerificationRequestIn,
                                      authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=NUMBER_ROLES)
    try:
        return {"ok": True, **await request_roove_verification_code(
            cid, number_id, method=payload.method, confirmed=payload.confirmed)}
    except WhatsAppNativeError as exc:
        raise _roove_meta_error(exc) from None


@router.post("/numbers/{number_id}/meta-verify-code")
async def whatsapp_roove_verify_code(client_id: str, number_id: str, payload: RooveVerificationConfirmIn,
                                     authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=NUMBER_ROLES)
    try:
        return {"ok": True, **await verify_roove_verification_code(
            cid, number_id, code=payload.code, confirmed=payload.confirmed)}
    except WhatsAppNativeError as exc:
        raise _roove_meta_error(exc) from None


@router.get("/numbers/{number_id}/meta-registration")
async def whatsapp_meta_registration_status(client_id: str, number_id: str,
                                            authorization: Optional[str] = Header(None)):
    """Consulta registro na Meta, sem alterar a Cloud API."""
    cid = await require_client_role(client_id, authorization, allowed_roles=NUMBER_ROLES)
    try:
        return {"ok": True, **await get_roove_registration_status(cid, number_id)}
    except WhatsAppNativeError as exc:
        status = 404 if exc.code == "NOT_FOUND" else 409 if exc.code in {"STATUS_UNKNOWN", "NOT_IN_WABA"} else 502
        raise HTTPException(status, exc.message) from None


@router.post("/numbers/{number_id}/meta-register")
async def whatsapp_meta_registration(client_id: str, number_id: str, payload: RooveCloudRegistrationIn,
                                     authorization: Optional[str] = Header(None)):
    """Ação explícita de administrador, usa PIN sem persistir e token já salvo; não envia mensagens."""
    cid = await require_client_role(client_id, authorization, allowed_roles=NUMBER_ROLES)
    try:
        return {"ok": True, **await register_roove_cloud_number(
            cid, number_id, pin=payload.pin, confirmed=payload.confirmed)}
    except WhatsAppNativeError as exc:
        status = (
            404 if exc.code == "NOT_FOUND" else
            409 if exc.code in {"CONFIRMATION_REQUIRED", "STATUS_UNKNOWN", "REGISTRATION_UNSAFE", "NOT_IN_WABA"} else
            422 if exc.code == "PIN_INVALID" else 502
        )
        raise HTTPException(status, exc.message) from None


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
    from services.whatsapp_native import active_number_ids
    from services.whatsapp_sources import bridge_for
    from services import crm_whatsapp_templates, brand_whatsapp_templates
    try:
        if number_id or await active_number_ids(cid):
            return {"ok": True, "templates": await list_templates(cid, number_id), "provider": "native"}
        if bridge_for(cid):
            return {"ok": True, "templates": await brand_whatsapp_templates.list_templates(cid),
                    "provider": "crm_bridge"}
        return {"ok": True, "templates": await crm_whatsapp_templates.list_templates(cid),
                "provider": "mugozap_crm"}
    except WhatsAppNativeError as exc:
        raise HTTPException(422 if exc.code in {"NOT_FOUND", "TEMPLATE_INVALID"} else 502, exc.message) from None
    except StudioError as exc:
        raise HTTPException(409 if exc.code in {"CRM_TEMPLATES_NOT_LINKED", "CRM_TEMPLATES_NOT_CONNECTED"}
                            else 503 if exc.code in {"CRM_TEMPLATES_NOT_READY", "CRM_TEMPLATES_NOT_CONFIGURED"}
                            else 502, str(exc)) from None


@router.post("/templates", status_code=201)
async def submit_whatsapp_template(client_id: str, payload: TemplateIn,
                                   authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=TEMPLATE_ROLES)
    from services.whatsapp_native import active_number_ids
    from services.whatsapp_sources import bridge_for
    from services import crm_whatsapp_templates, brand_whatsapp_templates
    try:
        if payload.number_id or await active_number_ids(cid):
            template = await create_template(cid, number_id=payload.number_id, name=payload.name,
                                             category=payload.category, language=payload.language,
                                             body=payload.body, examples=payload.examples, footer=payload.footer)
        else:
            if bridge_for(cid):
                template = await brand_whatsapp_templates.create_template(cid, payload=payload.model_dump())
            else:
                template = await crm_whatsapp_templates.create_template(cid, payload=payload.model_dump())
    except WhatsAppNativeError as exc:
        raise HTTPException(422 if exc.code in {"NOT_FOUND", "TEMPLATE_INVALID"} else 502, exc.message) from None
    except StudioError as exc:
        raise HTTPException(409 if exc.code in {"CRM_TEMPLATES_NOT_LINKED", "CRM_TEMPLATES_NOT_CONNECTED"}
                            else 422 if exc.code == "CRM_TEMPLATE_INVALID"
                            else 503 if exc.code in {"CRM_TEMPLATES_NOT_READY", "CRM_TEMPLATES_NOT_CONFIGURED"}
                            else 502, str(exc)) from None
    return {"ok": True, "template": template}


# ---- Pré-validação segura para futuras campanhas WhatsApp.
# Não reutiliza listas de e-mail como autorização para mensagens WhatsApp.
class WhatsAppTemplatePreflight(BaseModel):
    template_name: str = Field(min_length=3, max_length=81)
    language: str = Field(default="pt_BR", pattern="^(pt_BR|en_US|es_ES)$")
    number_id: Optional[str] = None


@router.post("/campaigns/template-preflight")
async def whatsapp_template_preflight(client_id: str, payload: WhatsAppTemplatePreflight,
                                      authorization: Optional[str] = Header(None)):
    """Somente leitura: valida template aprovado no tenant; nunca envia mensagens."""
    cid = await require_client_role(client_id, authorization, allowed_roles=TEMPLATE_ROLES)
    from services.whatsapp_native import active_number_ids
    from services.whatsapp_sources import bridge_for
    from services import crm_whatsapp_templates, brand_whatsapp_templates
    try:
        if payload.number_id or await active_number_ids(cid):
            templates = await list_templates(cid, payload.number_id)
            provider = "native"
        elif bridge_for(cid):
            templates = await brand_whatsapp_templates.list_templates(cid)
            provider = "crm_bridge"
        else:
            templates = await crm_whatsapp_templates.list_templates(cid)
            provider = "mugozap_crm"
    except WhatsAppNativeError as exc:
        raise HTTPException(422 if exc.code in {"NOT_FOUND", "TEMPLATE_INVALID"} else 502, exc.message) from None
    except StudioError as exc:
        raise HTTPException(503, str(exc)) from None
    matched = next((t for t in templates if t.get("name") == payload.template_name
                    and t.get("language") == payload.language), None)
    approved = bool(matched and str(matched.get("status", "")).upper() == "APPROVED")
    return {"ok": True, "provider": provider, "template_found": bool(matched),
            "template_approved": approved, "template_status": matched.get("status") if matched else None,
            "can_send": False, "reason": "Campanhas WhatsApp ainda exigem listas com opt-in específico, fila e homologação.",
            "messages_sent": 0}



# ---- Campanhas: prévia e rascunhos; nenhum endpoint de envio em massa.
class BulkCampaignDraftIn(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    template_name: str = Field(min_length=3, max_length=81)
    language: str = Field(default="pt_BR", pattern="^(pt_BR|en_US|es_ES)$")
    provider: str = Field(default="all", pattern="^(all|shopify|fbits|whatsapp)$")


@router.get("/campaigns/drafts")
async def whatsapp_campaign_draft_list(client_id: str, authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=TEMPLATE_ROLES)
    from services.whatsapp_campaign_drafts import list_drafts
    return {"ok": True, "drafts": await list_drafts(cid), "sending_enabled": False}


@router.get("/campaigns/audience-preview")
async def whatsapp_campaign_audience_preview(client_id: str, provider: str = "all",
                                              authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=TEMPLATE_ROLES)
    from services.whatsapp_campaign_drafts import audience_preview
    try:
        return {"ok": True, **await audience_preview(cid, provider)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/campaigns/drafts", status_code=201)
async def whatsapp_campaign_create_draft(client_id: str, payload: BulkCampaignDraftIn,
                                          authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=TEMPLATE_ROLES)
    validated = await whatsapp_template_preflight(
        client_id, WhatsAppTemplatePreflight(template_name=payload.template_name, language=payload.language),
        authorization=authorization,
    )
    from services.whatsapp_campaign_drafts import save_draft
    try:
        result = await save_draft(cid, payload.model_dump(), approved=bool(validated["template_approved"]))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, **result, "sending_enabled": False}

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



# ---- Atendente de IA (números ligados direto no MUGOVERSO). Agência e admin da marca configuram e aprovam.
_AI_ERRORS = {"NOT_FOUND": 404, "NO_SUGGESTION": 409, "OUTSIDE_WINDOW": 409, "EMPTY": 422, "INVALID_MODE": 422,
              "INVALID_CATALOG": 422}


def _ai_http(exc: Exception) -> HTTPException:
    from services.whatsapp_ai import WhatsAppAiError
    if isinstance(exc, WhatsAppAiError):
        return HTTPException(_AI_ERRORS.get(exc.code, 400), exc.message)
    if isinstance(exc, WhatsAppNativeError):
        return HTTPException(409 if exc.code == "OUTSIDE_WINDOW" else 502, exc.message)
    if isinstance(exc, StudioError):
        return HTTPException(502, str(exc) if str(exc) != exc.code else "A IA não respondeu agora. Tente de novo.")
    print(f"[whatsapp_ai] route_error error_type={exc.__class__.__name__}")
    return HTTPException(503, "Não foi possível falar com a IA agora. Tente de novo em instantes.")


class AiSettingsIn(BaseModel):
    mode: Optional[str] = Field(default=None, pattern=r"^(off|suggest|auto)$")
    instructions: Optional[str] = Field(default=None, max_length=12000)
    offers: Optional[str] = Field(default=None, max_length=4000)
    welcome_buttons: Optional[list[str]] = Field(default=None, max_length=3)
    featured_products: Optional[list[str]] = Field(default=None, max_length=30)
    catalog_id: Optional[str] = Field(default=None, max_length=30)
    product_cards: Optional[bool] = None
    human_pause_minutes: Optional[int] = Field(default=None, ge=0, le=10080)


class SimTurn(BaseModel):
    role: str = Field(pattern=r"^(cliente|marca)$")
    text: str = Field(min_length=1, max_length=1000)


class SimulateIn(BaseModel):
    conversation: list[SimTurn] = Field(min_length=1, max_length=20)


class SuggestionSendIn(BaseModel):
    text: Optional[str] = Field(default=None, max_length=1000)


@router.get("/ai-settings")
async def read_ai_settings(client_id: str, authorization: Optional[str] = Header(None)):
    from services.whatsapp_ai import get_settings
    cid = await require_client_role(client_id, authorization, allowed_roles=INBOX_ROLES)
    try:
        return {"settings": await get_settings(cid)}
    except Exception as exc:  # noqa: BLE001
        raise _ai_http(exc) from None


@router.put("/ai-settings")
async def update_ai_settings(client_id: str, body: AiSettingsIn, authorization: Optional[str] = Header(None)):
    from services.tenant import require_user_id
    from services.whatsapp_ai import save_settings
    cid = await require_client_role(client_id, authorization, allowed_roles=INBOX_ROLES)
    user_id = await require_user_id(authorization)
    try:
        return {"settings": await save_settings(cid, user_id=user_id, **body.model_dump(exclude_unset=True))}
    except Exception as exc:  # noqa: BLE001
        raise _ai_http(exc) from None


@router.get("/ai-settings/catalog")
async def read_ai_catalog_status(client_id: str, authorization: Optional[str] = Header(None)):
    from services.whatsapp_ai import catalog_status
    cid = await require_client_role(client_id, authorization, allowed_roles=INBOX_ROLES)
    try:
        return await catalog_status(cid)
    except Exception as exc:  # noqa: BLE001
        raise _ai_http(exc) from None


@router.post("/ai-settings/simulate")
async def simulate_ai(client_id: str, body: SimulateIn, authorization: Optional[str] = Header(None)):
    from services.whatsapp_ai import simulate
    cid = await require_client_role(client_id, authorization, allowed_roles=INBOX_ROLES)
    try:
        return await simulate(cid, [turn.model_dump() for turn in body.conversation])
    except Exception as exc:  # noqa: BLE001
        raise _ai_http(exc) from None


@router.post("/conversations/{conversation_id}/ai-suggestion/send")
async def send_ai_suggestion(client_id: str, conversation_id: str, body: SuggestionSendIn,
                             authorization: Optional[str] = Header(None)):
    from services.whatsapp_ai import send_suggestion
    cid = await require_client_role(client_id, authorization, allowed_roles=INBOX_ROLES)
    try:
        return await send_suggestion(cid, conversation_id, text=body.text)
    except Exception as exc:  # noqa: BLE001
        raise _ai_http(exc) from None


@router.delete("/conversations/{conversation_id}/ai-suggestion")
async def discard_ai_suggestion(client_id: str, conversation_id: str, authorization: Optional[str] = Header(None)):
    from services.whatsapp_ai import discard_suggestion
    cid = await require_client_role(client_id, authorization, allowed_roles=INBOX_ROLES)
    try:
        return await discard_suggestion(cid, conversation_id)
    except Exception as exc:  # noqa: BLE001
        raise _ai_http(exc) from None


@router.post("/conversations/{conversation_id}/ai/resume")
async def resume_ai(client_id: str, conversation_id: str, authorization: Optional[str] = Header(None)):
    from services.whatsapp_ai import resume
    cid = await require_client_role(client_id, authorization, allowed_roles=INBOX_ROLES)
    try:
        return await resume(cid, conversation_id)
    except Exception as exc:  # noqa: BLE001
        raise _ai_http(exc) from None
