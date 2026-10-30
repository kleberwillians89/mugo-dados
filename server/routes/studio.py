"""Mugô Studio: perfil de marca e calendário editorial.

Leitura: qualquer membro da empresa. Escrita, geração por IA e aprovação:
agency_admin e client_admin (mesma regra das metas). A empresa vem sempre da
membership resolvida no backend; o client_id da URL é só um pedido.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from services.studio_calendar import (
    StudioError, create_item, delete_item, generate_month, list_items, load_profile,
    parse_month, save_profile, update_item,
)
from services.studio_approvals import (
    cancel_request, create_request, frontend_base_url, list_requests, pipeline, public_decide, public_view,
)
from services.studio_engines import ASSIST_ACTIONS, assist, strategy_chat, suggest_profile
from services.studio_intelligence import build_content_intelligence, coverage
from services.media_plan import get_strategy, list_strategies, plan_vs_actual, record_strategy, save_plan
from services.media_strategy import build_strategy, narrative as media_narrative
from services.studio_messages import (
    TEMPLATES, build_message, delete_contact, list_contacts, list_messages, mugozap_config, public_preview,
    save_contact, send_message,
)
from services.studio_assets import (
    attach_assets, confirm_upload, delete_asset, list_assets, request_upload, set_item_assets, update_asset,
)
from services.tenant import require_client_read, require_client_role, require_user_id

router = APIRouter(prefix="/api/clients/{client_id}/studio", tags=["studio"])

Format = Literal["reels", "carrossel", "imagem", "stories", "video"]
Status = Literal["rascunho", "em_revisao", "aprovado", "rejeitado", "publicado"]

ERRORS = {
    "MONTH_INVALID": (422, "Use o mês no formato AAAA-MM."),
    "MONTH_OUT_OF_RANGE": (422, "Gere do mês atual até 3 meses à frente."),
    "MONTH_PAST": (422, "Esse mês já passou; escolha o mês atual ou um próximo."),
    "NO_SLOTS": (409, "Não sobrou dia livre neste mês para novas pautas."),
    "AI_GENERATION_COOLDOWN": (429, "Um calendário acabou de ser gerado. Aguarde um instante."),
    "AI_PROVIDER_NOT_CONFIGURED": (503, "O provedor de IA ainda não está configurado no backend."),
    "AI_PROVIDER_TIMEOUT": (502, "A IA demorou mais que o esperado. Tente novamente."),
    "AI_PROVIDER_ERROR": (502, "A IA não respondeu agora. Tente novamente."),
    "AI_INVALID_OUTPUT": (502, "A IA não devolveu pautas válidas. Tente novamente."),
    "ITEM_NOT_FOUND": (404, "Pauta não encontrada nesta empresa."),
    "STATUS_INVALID": (422, "Status inválido."),
    "FORMAT_INVALID": (422, "Formato inválido."),
    "EMPTY_PATCH": (422, "Nada para alterar."),
    "CREATE_FAILED": (502, "Não foi possível criar a pauta."),
}


def _http(exc: StudioError) -> HTTPException:
    status, detail = ERRORS.get(exc.code, (502, "Não foi possível concluir agora."))
    headers = {"Retry-After": "90"} if status == 429 else None
    return HTTPException(status_code=status, detail=detail, headers=headers)


WRITERS = ("agency_admin", "client_admin")


class Pillar(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    weight: int = Field(default=0, ge=0, le=100)
    description: str = Field(default="", max_length=400)


class CustomDate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    date: str = Field(pattern=r"^(\d{4}-)?\d{2}-\d{2}$")
    label: str = Field(min_length=1, max_length=80)


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    tone_of_voice: str = Field(default="", max_length=1000)
    personality: str = Field(default="", max_length=500)
    audience: str = Field(default="", max_length=1000)
    pillars: List[Pillar] = Field(default_factory=list, max_length=8)
    keywords_use: List[str] = Field(default_factory=list, max_length=30)
    keywords_avoid: List[str] = Field(default_factory=list, max_length=30)
    hashtags: List[str] = Field(default_factory=list, max_length=30)
    restrictions: str = Field(default="", max_length=1500)
    posts_per_week: int = Field(default=3, ge=1, le=14)
    formats_enabled: List[Format] = Field(default_factory=lambda: ["reels", "carrossel", "imagem"], max_length=5)
    custom_dates: List[CustomDate] = Field(default_factory=list, max_length=30)


class GenerateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: str = Field(pattern=r"^\d{4}-\d{2}$")


class ItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    scheduled_at: datetime
    format: Format
    title: str = Field(min_length=1, max_length=200)
    pillar: Optional[str] = Field(default=None, max_length=120)
    hook: Optional[str] = Field(default=None, max_length=400)
    caption_draft: Optional[str] = Field(default=None, max_length=4000)
    rationale: Optional[str] = Field(default=None, max_length=1200)


class ItemPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    scheduled_at: Optional[datetime] = None
    format: Optional[Format] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    pillar: Optional[str] = Field(default=None, max_length=120)
    hook: Optional[str] = Field(default=None, max_length=400)
    caption_draft: Optional[str] = Field(default=None, max_length=4000)
    rationale: Optional[str] = Field(default=None, max_length=1200)
    status: Optional[Status] = None
    review_note: Optional[str] = Field(default=None, max_length=1000)


@router.get("/brand-profile")
async def read_profile(client_id: str, authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id, authorization)
    return await load_profile(cid)


@router.put("/brand-profile")
async def write_profile(client_id: str, body: ProfileInput, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    return await save_profile(cid, body.model_dump(mode="json"), user_id=uid)


@router.get("/calendar")
async def read_calendar(client_id: str, month: str, authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id, authorization)
    try:
        target = parse_month(month)
    except StudioError as exc:
        raise _http(exc) from None
    return {"month": target.isoformat(), "items": await attach_assets(cid, await list_items(cid, target))}


@router.post("/calendar/generate")
async def generate_calendar(client_id: str, body: GenerateInput, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    try:
        result = await generate_month(cid, body.month, user_id=uid)
    except StudioError as exc:
        raise _http(exc) from None
    return {**result, "items": await attach_assets(cid, result.get("items") or [])}


@router.post("/calendar/items", status_code=201)
async def add_item(client_id: str, body: ItemCreate, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    try:
        return {"ok": True, "item": await create_item(cid, body.model_dump(mode="json"), user_id=uid)}
    except StudioError as exc:
        raise _http(exc) from None


@router.patch("/calendar/items/{item_id}")
async def edit_item(client_id: str, item_id: UUID, body: ItemPatch, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    try:
        item = await update_item(cid, str(item_id), body.model_dump(mode="json", exclude_none=True), user_id=uid)
    except StudioError as exc:
        raise _http(exc) from None
    return {"ok": True, "item": (await attach_assets(cid, [item]))[0]}


@router.delete("/calendar/items/{item_id}")
async def remove_item(client_id: str, item_id: UUID, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        await delete_item(cid, str(item_id))
    except StudioError as exc:
        raise _http(exc) from None
    return {"ok": True}


# ---------------------------------------------------------------- biblioteca e arte na pauta


ERRORS.update({
    "STORAGE_NOT_CONFIGURED": (503, "O armazenamento de arquivos ainda não está configurado no backend."),
    "STORAGE_ERROR": (502, "O armazenamento de arquivos não respondeu. Tente novamente."),
    "TYPE_NOT_ALLOWED": (422, "Tipo de arquivo não aceito. Use JPG, PNG, WEBP, MP4, MOV ou PDF."),
    "SIZE_INVALID": (422, "Tamanho de arquivo inválido."),
    "FILE_TOO_LARGE": (413, "Arquivo grande demais. Limites: imagem 15 MB, vídeo 200 MB, PDF 30 MB."),
    "NAME_INVALID": (422, "Dê um nome ao arquivo."),
    "KIND_INVALID": (422, "Tipo inválido."),
    "TOO_MANY_PENDING": (429, "Muitos envios em andamento. Aguarde alguns minutos."),
    "ASSET_NOT_FOUND": (404, "Arquivo não encontrado nesta empresa."),
    "ASSET_NOT_UPLOADED": (409, "O arquivo ainda não chegou ao armazenamento. Envie de novo."),
    "TYPE_MISMATCH": (422, "O conteúdo do arquivo não corresponde ao tipo informado. Ele foi descartado."),
    "ASSETS_DUPLICATED": (422, "A mesma mídia aparece duas vezes."),
    "TOO_MANY_ASSETS": (422, "Uma pauta aceita no máximo 20 mídias."),
    "ASSETS_INVALID": (422, "Alguma mídia não existe nesta empresa ou ainda não terminou de subir."),
    "ASSET_KIND_INVALID": (422, "Na pauta entram só imagens e vídeos. PDFs ficam na Biblioteca."),
})

AssetKind = Literal["imagem", "video", "pdf"]


class UploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    file_name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=3, max_length=100)
    size_bytes: int = Field(gt=0)
    folder: Optional[str] = Field(default=None, max_length=80)
    tags: List[str] = Field(default_factory=list, max_length=20)
    with_thumb: bool = False


class UploadConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: Optional[int] = Field(default=None, ge=1, le=20000)
    height: Optional[int] = Field(default=None, ge=1, le=20000)
    duration_seconds: Optional[float] = Field(default=None, ge=0, le=86400)


class AssetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    folder: Optional[str] = Field(default=None, max_length=80)
    tags: Optional[List[str]] = Field(default=None, max_length=20)


class ItemAssetsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_ids: List[UUID] = Field(default_factory=list, max_length=20)


@router.get("/assets")
async def read_assets(client_id: str, folder: Optional[str] = None, tag: Optional[str] = None,
                      kind: Optional[AssetKind] = None, q: Optional[str] = None,
                      authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id, authorization)
    try:
        return await list_assets(cid, folder=folder, tag=tag, kind=kind, q=q)
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/assets/upload-url", status_code=201)
async def new_asset_upload(client_id: str, body: UploadRequest, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    try:
        return await request_upload(cid, file_name=body.file_name, mime_type=body.mime_type, size_bytes=body.size_bytes,
                                    folder=body.folder, tags=body.tags, with_thumb=body.with_thumb, user_id=uid)
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/assets/{asset_id}/confirm")
async def confirm_asset_upload(client_id: str, asset_id: UUID, body: UploadConfirm,
                               authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        asset = await confirm_upload(cid, str(asset_id), width=body.width, height=body.height,
                                     duration_seconds=body.duration_seconds)
    except StudioError as exc:
        raise _http(exc) from None
    return {"ok": True, "asset": asset}


@router.patch("/assets/{asset_id}")
async def edit_asset(client_id: str, asset_id: UUID, body: AssetPatch, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        asset = await update_asset(cid, str(asset_id), body.model_dump(mode="json", exclude_unset=True))
    except StudioError as exc:
        raise _http(exc) from None
    return {"ok": True, "asset": asset}


@router.delete("/assets/{asset_id}")
async def remove_asset(client_id: str, asset_id: UUID, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        await delete_asset(cid, str(asset_id))
    except StudioError as exc:
        raise _http(exc) from None
    return {"ok": True}


@router.put("/calendar/items/{item_id}/assets")
async def write_item_assets(client_id: str, item_id: UUID, body: ItemAssetsInput,
                            authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        assets = await set_item_assets(cid, str(item_id), [str(a) for a in body.asset_ids])
    except StudioError as exc:
        raise _http(exc) from None
    return {"ok": True, "item_id": str(item_id), "assets": assets}


# ---------------------------------------------------------------- motores de conteúdo


ERRORS.update({
    "ITEM_TITLE_REQUIRED": (422, "Dê um título à pauta antes de pedir ajuda à IA."),
    "CHAT_EMPTY": (422, "Escreva uma pergunta."),
    "AI_RATE_LIMIT": (429, "Muitos pedidos à IA em sequência. Aguarde um minuto."),
    "GUIDE_NOT_FOUND": (404, "Guia da marca não encontrado na Biblioteca (precisa ser um PDF)."),
    "GUIDE_TOO_LARGE": (413, "Guia grande demais para leitura (máx. 12 MB)."),
    "GUIDE_UNREADABLE": (422, "Não consegui ler o texto desse PDF (pode ser só imagem)."),
})

AssistAction = Literal["legenda", "variacoes", "ganchos", "hashtags", "roteiro_reels", "revisar"]


class AssistItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    format: Format = "imagem"
    title: str = Field(min_length=1, max_length=200)
    pillar: Optional[str] = Field(default=None, max_length=120)
    hook: Optional[str] = Field(default=None, max_length=400)
    caption_draft: Optional[str] = Field(default=None, max_length=4000)
    scheduled_at: Optional[str] = Field(default=None, max_length=40)


class AssistInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: AssistAction
    item: AssistItem
    instruction: Optional[str] = Field(default=None, max_length=600)


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    messages: List[ChatMessage] = Field(min_length=1, max_length=30)


class SuggestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    guide_asset_id: Optional[UUID] = None


@router.get("/intelligence")
async def read_intelligence(client_id: str, authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id, authorization)
    return {"based_on": coverage(await build_content_intelligence(cid)), "actions": list(ASSIST_ACTIONS)}


@router.post("/assist")
async def run_assist(client_id: str, body: AssistInput, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        return await assist(cid, body.action, body.item.model_dump(), instruction=body.instruction)
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/strategy/chat")
async def run_strategy_chat(client_id: str, body: ChatInput, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        return await strategy_chat(cid, body.month, [m.model_dump() for m in body.messages])
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/brand-profile/suggest")
async def run_profile_suggestion(client_id: str, body: SuggestInput, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        return await suggest_profile(cid, guide_asset_id=str(body.guide_asset_id) if body.guide_asset_id else None)
    except StudioError as exc:
        raise _http(exc) from None


# ---------------------------------------------------------------- aprovação do cliente


ERRORS.update({
    "NO_ITEMS": (422, "Selecione ao menos uma pauta."),
    "ITEMS_INVALID": (422, "Alguma pauta não existe nesta empresa ou está rejeitada."),
    "PHONE_INVALID": (422, "Telefone inválido. Use DDD + número."),
    "REQUEST_NOT_FOUND": (404, "Pedido de aprovação não encontrado ou já encerrado."),
    "LINK_UNAVAILABLE": (404, "Este link de aprovação expirou ou não está mais disponível. Peça um novo à equipe Mugô."),
    "ACTION_INVALID": (422, "Ação inválida."),
    "COMMENT_REQUIRED": (422, "Conte o que precisa mudar."),
})


def _frontend_base_url() -> str:
    return frontend_base_url()


class ApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    item_ids: List[UUID] = Field(min_length=1, max_length=200)
    contact_name: Optional[str] = Field(default=None, max_length=120)
    contact_phone: Optional[str] = Field(default=None, max_length=30)
    message: Optional[str] = Field(default=None, max_length=1000)
    contact_id: Optional[UUID] = None
    send_whatsapp: bool = False


@router.get("/approvals")
async def read_approvals(client_id: str, authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id, authorization)
    return {"requests": await list_requests(cid)}


@router.post("/approvals", status_code=201)
async def send_for_approval(client_id: str, body: ApprovalInput, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    name, phone = body.contact_name, body.contact_phone
    try:
        if body.contact_id:
            contact = next((c for c in await list_contacts(cid) if str(c["id"]) == str(body.contact_id)), None)
            if not contact:
                raise StudioError("CONTACT_NOT_FOUND")
            name, phone = contact["name"], contact["phone"]
        created = await create_request(cid, month=body.month, item_ids=[str(i) for i in body.item_ids],
                                       contact_name=name, contact_phone=phone, message=body.message, user_id=uid,
                                       app_origin=_frontend_base_url(), contact_id=str(body.contact_id) if body.contact_id else None)
    except StudioError as exc:
        raise _http(exc) from None
    if body.send_whatsapp and body.contact_id:
        # O link já existe; falha no WhatsApp não desfaz o pedido, só volta como aviso.
        try:
            created["whatsapp"] = await send_message(cid, "aprovacao", user_id=uid, contact_id=str(body.contact_id),
                                                     request_id=str(created["request_id"]))
        except StudioError as exc:
            created["whatsapp"] = {"status": "falhou", "detail": ERRORS.get(exc.code, (0, "Não foi possível enviar agora."))[1]}
    return created


@router.delete("/approvals/{request_id}")
async def cancel_approval(client_id: str, request_id: UUID, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        await cancel_request(cid, str(request_id))
    except StudioError as exc:
        raise _http(exc) from None
    return {"ok": True}


@router.get("/approvals/pipeline")
async def read_pipeline(client_id: str, month: str, authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id, authorization)
    try:
        data = await pipeline(cid, month)
    except StudioError as exc:
        raise _http(exc) from None
    return {**data, "items": await attach_assets(cid, data["items"])}


# ---------------------------------------------------------------- contatos e mensagens (MugôZap)


ERRORS.update({
    "CONTACT_NOT_FOUND": (404, "Contato não encontrado nesta empresa."),
    "CONTACT_REQUIRED": (422, "Cadastre um contato que receba esse tipo de mensagem (aba Contatos)."),
    "LINK_NOT_RESENDABLE": (409, "Este pedido foi criado antes do lembrete existir. Gere um novo link para reenviar."),
    "NOTHING_PENDING": (409, "O cliente já respondeu todas as pautas deste pedido."),
    "NOTHING_SCHEDULED": (409, "Nenhuma pauta aprovada para esta semana."),
    "NO_PAID_DATA": (409, "Sem investimento em mídia nos últimos 7 dias."),
    "NO_RESULTS_DATA": (409, "Sem faturamento do mês anterior para montar o resumo."),
    "HEADER_IMAGE_REQUIRED": (422, "O template com arte precisa de uma imagem anexada à pauta."),
    "BUTTON_PARAM_REQUIRED": (422, "O template precisa do link de aprovação."),
    "TEMPLATE_NOT_APPROVED": (409, "O template ainda não está aprovado pela Meta no MugôZap."),
    "RECIPIENT_NOT_IN_CRM": (409, "Esse telefone não está cadastrado no CRM. Cadastre o contato no CRM e tente de novo."),
    "SEND_OUTCOME_UNKNOWN": (409, "Um envio anterior ainda não foi confirmado. Confira o histórico no CRM antes de reenviar."),
    "MUGOZAP_UNAVAILABLE": (502, "O MugôZap não respondeu. Tente novamente."),
    "SEND_FAILED": (502, "O MugôZap não conseguiu enviar a mensagem."),
})

MessageKind = Literal["aprovacao", "lembrete", "agenda", "trafego", "resultados"]
Receives = Literal["conteudo", "trafego", "resultados"]


class ContactInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=8, max_length=30)
    role: Optional[str] = Field(default=None, max_length=80)
    receives: List[Receives] = Field(default_factory=lambda: ["conteudo"], min_length=1, max_length=3)
    is_primary: bool = False


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: MessageKind
    contact_id: Optional[UUID] = None
    request_id: Optional[UUID] = None
    overrides: Dict[str, str] = Field(default_factory=dict, max_length=4)


def _message_args(body: MessageInput) -> Dict[str, Any]:
    return {"contact_id": str(body.contact_id) if body.contact_id else None,
            "request_id": str(body.request_id) if body.request_id else None,
            "overrides": {k: v[:300] for k, v in body.overrides.items()}}


@router.get("/contacts")
async def read_contacts(client_id: str, authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id, authorization)
    return {"contacts": await list_contacts(cid), "whatsapp_channel": "mugozap" if mugozap_config() else "wa_link"}


@router.post("/contacts", status_code=201)
async def add_contact(client_id: str, body: ContactInput, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    try:
        return {"ok": True, "contact": await save_contact(cid, body.model_dump(), user_id=uid)}
    except StudioError as exc:
        raise _http(exc) from None


@router.put("/contacts/{contact_id}")
async def edit_contact(client_id: str, contact_id: UUID, body: ContactInput, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    try:
        return {"ok": True, "contact": await save_contact(cid, body.model_dump(), user_id=uid, contact_id=str(contact_id))}
    except StudioError as exc:
        raise _http(exc) from None


@router.delete("/contacts/{contact_id}")
async def remove_contact(client_id: str, contact_id: UUID, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        await delete_contact(cid, str(contact_id))
    except StudioError as exc:
        raise _http(exc) from None
    return {"ok": True}


@router.get("/messages")
async def read_messages(client_id: str, authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id, authorization)
    return {"messages": await list_messages(cid), "templates": sorted(TEMPLATES),
            "whatsapp_channel": "mugozap" if mugozap_config() else "wa_link"}


@router.post("/messages/preview")
async def preview_message(client_id: str, body: MessageInput, authorization: str | None = Header(default=None)):
    # Prévia chama a IA para a frase de destaque: mesma permissão de quem envia.
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        return public_preview(await build_message(cid, body.kind, **_message_args(body)))
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/messages/send")
async def send_studio_message(client_id: str, body: MessageInput, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    try:
        return {"ok": True, **await send_message(cid, body.kind, user_id=uid, **_message_args(body))}
    except StudioError as exc:
        raise _http(exc) from None


# ---------------------------------------------------------------- Mídia On


ERRORS.update({
    "BUDGET_INVALID": (422, "Informe uma verba maior que zero."),
    "ALLOCATION_INVALID": (422, "A divisão por canal precisa somar a verba do mês."),
    "OBJECTIVE_INVALID": (422, "Objetivo inválido."),
    "SCENARIO_INVALID": (422, "Cenário inválido."),
    "MARGIN_INVALID": (422, "A margem precisa estar entre 2% e 95%."),
    "STRATEGY_TOO_LARGE": (413, "Estratégia grande demais para salvar."),
    "STRATEGY_NOT_FOUND": (404, "Estratégia não encontrada nesta empresa."),
    "NO_PAID_HISTORY": (409, "Sem histórico de Meta Ads e Google Ads nos últimos 90 dias. Informe a verba do mês para montar o plano "
                             "com os dados da loja e referências de mercado."),
    "DISTRIBUTION_INVALID": (422, "Modo de distribuição inválido."),
    "MIGRATION_054_PENDING": (503, "Falta aplicar a migration 000054 (planos do Mídia On) no Supabase."),
    "MIGRATION_055_PENDING": (503, "Falta aplicar a migration 000055 (estratégia no plano) no Supabase."),
    "MIGRATION_056_PENDING": (503, "Falta aplicar a migration 000056 (histórico de estratégias) no Supabase."),
    "HISTORY_SAVE_FAILED": (502, "Não foi possível gravar a estratégia no histórico."),
})

Objective = Literal["vendas", "leads", "trafego", "alcance"]
Channel = Literal["meta", "google_ads"]


class StrategyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    objective: Objective = "vendas"
    margin: Optional[float] = Field(default=None, gt=0, lt=1)
    budget: Optional[float] = Field(default=None, gt=0, le=100000000)
    distribution: Literal["equilibrado", "hiperfoco"] = "equilibrado"
    with_narrative: bool = True


class PlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    objective: Objective
    scenario: Literal["ritmo_atual", "meta", "eficiencia", "personalizado"]
    budget: float = Field(gt=0, le=100000000)
    allocation: Dict[Channel, float]
    margin: Optional[float] = Field(default=None, gt=0, lt=1)
    strategy: Dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = Field(default=None, max_length=2000)
    status: Literal["rascunho", "aprovado"] = "rascunho"


@router.post("/media/strategy")
async def run_media_strategy(client_id: str, body: StrategyInput, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    try:
        strategy = await build_strategy(cid, month=body.month, objective=body.objective, margin=body.margin, custom_budget=body.budget,
                                        distribution=body.distribution)
    except StudioError as exc:
        raise _http(exc) from None
    strategy["narrative"] = None
    if body.with_narrative:
        try:
            strategy["narrative"] = await media_narrative(cid, strategy)
        except StudioError as exc:
            # Os números valem sem a leitura da IA; a tela avisa e oferece tentar de novo.
            strategy["narrative_error"] = ERRORS.get(exc.code, (0, "A leitura da IA não veio agora."))[1]
    # Toda estratégia gerada fica gravada: sair da página não perde a última.
    record = await record_strategy(cid, strategy, objective=body.objective, margin=body.margin, custom_budget=body.budget, user_id=uid)
    strategy["strategy_id"], strategy["generated_at"] = record.get("id"), record.get("created_at")
    if not record["saved"]:
        strategy["history_warning"] = ERRORS.get(record["reason"], (0, "Não foi possível gravar a estratégia no histórico."))[1]
    return strategy


@router.get("/media/strategies")
async def read_media_strategies(client_id: str, month: str, authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id, authorization)
    try:
        return {"strategies": await list_strategies(cid, month)}
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/media/strategies/{strategy_id}")
async def read_media_strategy(client_id: str, strategy_id: UUID, authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id, authorization)
    try:
        return await get_strategy(cid, str(strategy_id))
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/media/plan")
async def read_media_plan(client_id: str, month: str, authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id, authorization)
    try:
        return await plan_vs_actual(cid, month)
    except StudioError as exc:
        raise _http(exc) from None


@router.put("/media/plan")
async def write_media_plan(client_id: str, body: PlanInput, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    try:
        return {"ok": True, "plan": await save_plan(cid, body.month, body.model_dump(mode="json"), user_id=uid)}
    except StudioError as exc:
        raise _http(exc) from None


# Rotas públicas: o token do link é a credencial. Sem sessão, sem client_id na URL.
public_router = APIRouter(prefix="/api/public/approvals", tags=["studio-public"])


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["aprovado", "ajuste_solicitado"]
    comment: Optional[str] = Field(default=None, max_length=1000)
    reviewer_name: Optional[str] = Field(default=None, max_length=120)


@public_router.get("/{token}")
async def public_approval(token: str):
    try:
        return await public_view(token)
    except StudioError as exc:
        raise _http(exc) from None


@public_router.post("/{token}/items/{item_id}")
async def public_approval_decide(token: str, item_id: UUID, body: DecisionInput):
    try:
        return await public_decide(token, str(item_id), action=body.action, comment=body.comment,
                                   reviewer_name=body.reviewer_name)
    except StudioError as exc:
        raise _http(exc) from None
