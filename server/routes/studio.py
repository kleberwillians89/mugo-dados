"""Mugô Studio: perfil de marca e calendário editorial.

Leitura: qualquer membro da empresa. Escrita, geração por IA e aprovação:
agency_admin e client_admin (mesma regra das metas). A empresa vem sempre da
membership resolvida no backend; o client_id da URL é só um pedido.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from services.ig_supabase import sb_delete, sb_insert, sb_update

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
    MUGOZAP_ENV, TEMPLATES, build_message, delete_contact, list_contacts, list_messages, mugozap_missing, public_preview,
    whatsapp_channel,
    save_contact, send_message,
)
from services.studio_client import CLIENT_STAGES, client_edit, client_items
from services.studio_comments import add_comment, list_comments
from services.tenant import is_agency_user, require_client_read, require_client_role, require_user_id

router = APIRouter(prefix="/api/clients/{client_id}/studio", tags=["studio"])

Format = Literal["reels", "carrossel", "imagem", "stories", "video"]
Channel = Literal["instagram", "facebook", "tiktok", "linkedin", "youtube", "pinterest"]
Status = Literal["rascunho", "em_revisao", "aprovado", "rejeitado", "publicado"]

ERRORS = {
    "MONTH_INVALID": (422, "Use o mês no formato AAAA-MM."),
    "MONTH_OUT_OF_RANGE": (422, "Gere do mês atual até 3 meses à frente."),
    "MONTH_PAST": (422, "Esse mês já passou; escolha o mês atual ou um próximo."),
    "NO_SLOTS": (409, "Não sobrou dia livre neste mês para novas pautas."),
    "AI_GENERATION_COOLDOWN": (429, "Um calendário acabou de ser gerado. Aguarde um instante."),
    "AI_PROVIDER_NOT_CONFIGURED": (503, "O provedor de IA ainda não está configurado no backend."),
    "AI_PROVIDER_TIMEOUT": (502, "A IA demorou mais que o esperado. Tente novamente."),
    "AI_PROVIDER_QUOTA": (503, "A IA está sem crédito na OpenAI. Recarregue em platform.openai.com → Billing e tente de novo. O consumo por cliente está em Administração → Consumo de IA."),
    "AI_PROVIDER_AUTH": (503, "A chave da OpenAI do Mugoverso foi recusada (inválida ou de outro projeto). Confira a OPENAI_API_KEY no Render."),
    "AI_PROVIDER_RATE": (429, "A OpenAI pediu para esperar: limite de uso por minuto da conta. Tente de novo em 1 minuto."),
    "AI_PROVIDER_REQUEST": (502, "A OpenAI recusou o pedido (modelo ou formato). Avise a equipe técnica: o código do erro está em Administração → Consumo de IA."),
    "AI_PROVIDER_ERROR": (502, "A IA não respondeu agora. Tente novamente."),
    "AI_INVALID_OUTPUT": (502, "A IA não devolveu pautas válidas. Tente novamente."),
    "ITEM_NOT_FOUND": (404, "Pauta não encontrada nesta empresa."),
    "STATUS_INVALID": (422, "Status inválido."),
    "FORMAT_INVALID": (422, "Formato inválido."),
    "CHANNEL_INVALID": (422, "Plataforma inválida."),
    "EMPTY_PATCH": (422, "Nada para alterar."),
    "CREATE_FAILED": (502, "Não foi possível criar a pauta."),
    "SUGGESTION_NOT_FOUND": (404, "Essa sugestão já foi revisada ou não existe."),
    "ART_URL_INVALID": (422, "Link da arte inválido: use um link https (Canva, Google Drive…)."),
    "IMPORT_EMPTY": (422, "Não encontrei texto nos slides. Confira o arquivo ou cole o conteúdo."),
    "IMPORT_TOO_LARGE": (413, "Arquivo grande demais para importar de uma vez (até 150 slides)."),
    "IMPORT_NOTHING": (422, "Nenhum post válido para importar."),
    "INVALID_STATUS": (422, "Status inválido."),
}


def _http(exc: StudioError) -> HTTPException:
    status, detail = ERRORS.get(exc.code, (502, "Não foi possível concluir agora."))
    headers = {"Retry-After": "90"} if status == 429 else None
    return HTTPException(status_code=status, detail=detail, headers=headers)


WRITERS = ("agency_admin", "client_admin")


async def _agency_only(authorization: str | None) -> None:
    """Gerar, criar e excluir pautas é da equipe Mugô; o cliente aprova, pede ajuste e edita o que vê."""
    if not await is_agency_user(authorization):
        raise HTTPException(status_code=403, detail="Só a equipe Mugô pode fazer isso. Você pode editar, aprovar ou pedir ajuste nos posts.")


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
    visual_identity: str = Field(default="", max_length=1500)
    posts_per_week: int = Field(default=3, ge=1, le=14)
    editorial_platforms: List[Channel] = Field(default_factory=list, max_length=6)
    posts_per_week_by_platform: Dict[Channel, Annotated[int, Field(ge=1, le=14)]] = Field(default_factory=dict)
    formats_enabled: List[Format] = Field(default_factory=lambda: ["reels", "carrossel", "imagem"], max_length=5)
    custom_dates: List[CustomDate] = Field(default_factory=list, max_length=30)
    content_language: Literal["pt-BR", "en", "es"] = "pt-BR"


class GenerateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: str = Field(pattern=r"^\d{4}-\d{2}$")


class ItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    scheduled_at: datetime
    channel: Channel = "instagram"
    format: Format
    title: str = Field(min_length=1, max_length=200)
    pillar: Optional[str] = Field(default=None, max_length=120)
    hook: Optional[str] = Field(default=None, max_length=400)
    caption_draft: Optional[str] = Field(default=None, max_length=4000)
    rationale: Optional[str] = Field(default=None, max_length=1200)
    art_url: Optional[str] = Field(default=None, max_length=1000)
    collaborators: Optional[List[str]] = Field(default=None, max_length=3)
    product_tags: Optional[List["ProductTagInput"]] = Field(default=None, max_length=30)


class ItemPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    scheduled_at: Optional[datetime] = None
    channel: Optional[Channel] = None
    format: Optional[Format] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    pillar: Optional[str] = Field(default=None, max_length=120)
    hook: Optional[str] = Field(default=None, max_length=400)
    caption_draft: Optional[str] = Field(default=None, max_length=4000)
    rationale: Optional[str] = Field(default=None, max_length=1200)
    status: Optional[Status] = None
    review_note: Optional[str] = Field(default=None, max_length=1000)
    art_url: Optional[str] = Field(default=None, max_length=1000)
    collaborators: Optional[List[str]] = Field(default=None, max_length=3)
    product_tags: Optional[List["ProductTagInput"]] = Field(default=None, max_length=30)


class ProductTagInput(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    product_id: str = Field(min_length=1, max_length=30, pattern=r"^\d+$")
    name: Optional[str] = Field(default=None, max_length=200)
    image_url: Optional[str] = Field(default=None, max_length=1000)
    slide: int = Field(default=0, ge=0, le=9)
    x: float = Field(default=0.5, ge=0, le=1)
    y: float = Field(default=0.5, ge=0, le=1)


ItemPatch.model_rebuild()
ItemCreate.model_rebuild()


@router.get("/calendar/shop")
async def read_shop(client_id: str, authorization: str | None = Header(default=None)):
    """Equipe: a marca pode marcar produtos da loja do Instagram? Quais catálogos tem?"""
    from services.ig_shop import shop_status
    cid = await require_client_read(client_id, authorization)
    if not await is_agency_user(authorization):
        raise HTTPException(status_code=403, detail="Só a equipe Mugô marca produtos nos posts.")
    return await shop_status(cid)


@router.get("/calendar/shop/products")
async def read_shop_products(client_id: str, q: str = "", catalog_id: Optional[str] = None,
                             authorization: str | None = Header(default=None)):
    """Equipe: busca produtos da loja (nome ou SKU) para marcar no post."""
    from services.ig_shop import search_products
    cid = await require_client_read(client_id, authorization)
    if not await is_agency_user(authorization):
        raise HTTPException(status_code=403, detail="Só a equipe Mugô marca produtos nos posts.")
    if catalog_id is not None and not catalog_id.isdigit():
        raise HTTPException(status_code=400, detail="Catálogo inválido.")
    try:
        return {"products": await search_products(cid, q, catalog_id)}
    except StudioError as exc:
        if exc.code.startswith("SHOP_") or exc.code == "IG_NOT_CONNECTED":
            detail = str(exc) if str(exc) != exc.code else "Conecte o Instagram da marca em Integrações para marcar produtos."
            raise HTTPException(status_code=409, detail=detail) from None
        raise _http(exc) from None


@router.get("/brand-profile")
async def read_profile(client_id: str, authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id, authorization)
    return await load_profile(cid)


@router.put("/brand-profile")
async def write_profile(client_id: str, body: ProfileInput, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    return await save_profile(cid, body.model_dump(mode="json"), user_id=uid)


@router.get("/ai-usage")
async def read_ai_usage(client_id: str, authorization: str | None = Header(default=None)):
    """Consumo de IA desta empresa (tokens e custo estimado). Equipe Mugô e qualquer membro da própria empresa."""
    from services.ai_usage import client_summary
    cid = await require_client_read(client_id, authorization)
    return await client_summary(cid)


@router.get("/central")
async def read_central(client_id: str, month: str, authorization: str | None = Header(default=None)):
    """Central da marca: o mês numa página. Cliente vê a versão filtrada (o que já pode ver em cada módulo)."""
    cid = await require_client_read(client_id, authorization)
    try:
        target = parse_month(month)
    except StudioError as exc:
        raise _http(exc) from None
    from services.studio_central import build_central
    return await build_central(cid, target, agency=await is_agency_user(authorization))


@router.get("/calendar")
async def read_calendar(client_id: str, month: str, authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id, authorization)
    try:
        target = parse_month(month)
    except StudioError as exc:
        raise _http(exc) from None
    items = await list_items(cid, target)
    if not await is_agency_user(authorization):
        # Cliente vê o que está com ele, o ajuste que pediu, o aprovado e o publicado; rascunho fica com a Mugô.
        items = await client_items(cid, items)
    return {"month": target.isoformat(), "items": items}


@router.post("/calendar/generate")
async def generate_calendar(client_id: str, body: GenerateInput, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    await _agency_only(authorization)
    uid = await require_user_id(authorization)
    try:
        return await generate_month(cid, body.month, user_id=uid)
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/calendar/items", status_code=201)
async def add_item(client_id: str, body: ItemCreate, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    await _agency_only(authorization)
    uid = await require_user_id(authorization)
    try:
        item = await create_item(cid, body.model_dump(mode="json"), user_id=uid)
    except StudioError as exc:
        raise _http(exc) from None
    from services.studio_history import record
    await record(cid, (item or {}).get("id"), "criou a pauta", actor_name=_chat_author(authorization, uid), actor_id=uid)
    return {"ok": True, "item": item}


class ImportSlide(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int = Field(ge=1, le=1000)
    text: str = Field(default="", max_length=20000)
    links: List[str] = Field(default_factory=list, max_length=40)


class ImportParseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_name: str = Field(default="", max_length=200)
    slides: List[ImportSlide] = Field(min_length=1, max_length=150)


class ImportRow(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    date: str = Field(max_length=10)
    time: str = Field(default="", max_length=5)
    format: Format
    title: str = Field(min_length=1, max_length=200)
    caption: str = Field(default="", max_length=4000)
    art_url: str = Field(default="", max_length=1000)


class ImportCommitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: List[ImportRow] = Field(min_length=1, max_length=200)
    approved: bool = False


@router.post("/calendar/import/parse")
async def import_parse(client_id: str, body: ImportParseInput, authorization: str | None = Header(default=None)):
    """Lê o texto e os links dos slides (extraídos no navegador) e devolve os posts para revisão. Nada é gravado."""
    from services.studio_import import parse_slides
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    await _agency_only(authorization)
    try:
        from services.studio_engines import throttle
        throttle(cid)
        return await parse_slides([s.model_dump() for s in body.slides], file_name=body.file_name)
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/calendar/import/commit", status_code=201)
async def import_commit(client_id: str, body: ImportCommitInput, authorization: str | None = Header(default=None)):
    """Grava os posts revisados. approved=true: calendário já aprovado pelo cliente fora da plataforma."""
    from services.studio_import import commit_import
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    await _agency_only(authorization)
    uid = await require_user_id(authorization)
    try:
        return await commit_import(cid, [r.model_dump() for r in body.items], approved=body.approved, user_id=uid)
    except StudioError as exc:
        raise _http(exc) from None


@router.patch("/calendar/items/{item_id}")
async def edit_item(client_id: str, item_id: UUID, body: ItemPatch, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    patch = body.model_dump(mode="json", exclude_none=True)
    try:
        if not await is_agency_user(authorization):
            # Cliente: edita texto/data, aprova ou pede ajuste; o time é avisado (tarefa + WhatsApp).
            item = await client_edit(cid, str(item_id), patch, user_id=uid, actor_name="O cliente pelo painel")
            return {"ok": True, "item": item}
        from services.studio_history import changed_fields
        try:
            from services.ig_supabase import sb_select
            found = await sb_select("studio_calendar_items", select="*", limit=1, filters={"client_id": f"eq.{cid}", "id": f"eq.{item_id}"})
            before = found[0] if found else None
        except Exception:  # noqa: BLE001 — sem o estado anterior, o histórico registra o pedido como veio
            before = None
        item = await update_item(cid, str(item_id), patch, user_id=uid)
    except StudioError as exc:
        raise _http(exc) from None
    from services.studio_history import describe_patch, record_many
    await record_many(cid, str(item_id), describe_patch(changed_fields(before, patch)), actor_name=_chat_author(authorization, uid), actor_id=uid)
    return {"ok": True, "item": item}


class ItemDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    status: Literal["aprovado", "rejeitado"]
    review_note: Optional[str] = Field(default=None, max_length=1000)


@router.post("/calendar/items/{item_id}/decision")
async def decide_item(client_id: str, item_id: UUID, body: ItemDecisionInput, authorization: str | None = Header(default=None)):
    """Aprovar ou pedir ajuste num post. Basta poder ver o Calendário (o mesmo que o link de aprovação já permite):
    o cliente com acesso só de leitura também aprova e pede ajuste, sem ganhar a edição das pautas."""
    cid = await require_client_role(client_id, authorization, allowed_roles=MEMBERS)
    uid = await require_user_id(authorization)
    patch = body.model_dump(mode="json", exclude_none=True)
    try:
        if not await is_agency_user(authorization):
            item = await client_edit(cid, str(item_id), patch, user_id=uid, actor_name=_chat_author(authorization, uid) or "O cliente pelo painel")
        else:
            item = await update_item(cid, str(item_id), patch, user_id=uid)
    except StudioError as exc:
        raise _http(exc) from None
    return {"ok": True, "item": item}


class ScheduleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    now: bool = False


@router.post("/calendar/items/{item_id}/schedule")
async def schedule_item(client_id: str, item_id: UUID, body: Optional[ScheduleInput] = None, authorization: str | None = Header(default=None)):
    """Depois da aprovação do cliente, a equipe valida o agendamento na data e horário do post (ou publica agora)."""
    from services.studio_calendar import confirm_schedule
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    await _agency_only(authorization)
    uid = await require_user_id(authorization)
    now = bool(body and body.now)
    try:
        item = await confirm_schedule(cid, str(item_id), user_id=uid, now=now)
    except StudioError as exc:
        if exc.code == "SCHEDULE_ART_INVALID":
            raise HTTPException(status_code=422, detail=f"Não dá para publicar sozinho: {exc}") from None
        raise _http(exc) from None
    from services.studio_history import _when, record
    await record(cid, str(item_id), "pediu para publicar agora" if now else f"agendou a publicação para {_when((item or {}).get('scheduled_at'))}".strip(),
                 actor_name=_chat_author(authorization, uid), actor_id=uid)
    return {"ok": True, "item": item}


@router.post("/calendar/items/{item_id}/publish/retry")
async def publish_retry(client_id: str, item_id: UUID, authorization: str | None = Header(default=None)):
    """Depois de corrigir o link da arte, a pauta volta para a fila de publicação."""
    from services.ig_publish import retry
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    await _agency_only(authorization)
    try:
        item = await retry(cid, str(item_id))
    except StudioError as exc:
        raise _http(exc) from None
    from services.studio_history import record
    uid = await require_user_id(authorization)
    await record(cid, str(item_id), "colocou de novo na fila de publicação", actor_name=_chat_author(authorization, uid), actor_id=uid)
    return {"ok": True, "item": item}


class ArtUploadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_type: Literal["image/jpeg", "video/mp4", "video/quicktime"]


@router.post("/calendar/art/upload")
async def new_art_upload_target(client_id: str, body: ArtUploadInput, authorization: str | None = Header(default=None)):
    """Arte enviada antes de a pauta existir (criação): vai para a pasta "nova" da empresa; o link entra na pauta ao salvar."""
    from services.studio_art import upload_target
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    await _agency_only(authorization)
    try:
        return await upload_target(cid, "", body.content_type)
    except StudioError as exc:
        raise _http(exc) from None


ERRORS.update({
    "ART_LINK_INVALID": (422, "Cole um link de arquivo do Google Drive ou um link de visualização do Canva."),
    "ART_LINK_FOLDER": (422, "Esse é o link de uma pasta do Drive. Use o link do arquivo (botão direito no arquivo → Compartilhar → Copiar link)."),
    "ART_LINK_PRIVATE": (422, "O link não está público. No Drive/Canva, compartilhe como \"qualquer pessoa com o link pode ver\" e tente de novo."),
    "ART_LINK_UNREADABLE": (422, "Não deu para ler a arte desse link. Baixe o arquivo e arraste aqui."),
    "ART_LINK_TOO_LARGE": (413, "Arquivo maior que 200 MB."),
})


class ArtImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=12, max_length=1000)
    item_id: Optional[UUID] = None


@router.post("/calendar/art/import")
async def import_art_from_link(client_id: str, body: ArtImportInput, authorization: str | None = Header(default=None)):
    """Traz a arte de um link do Drive/Canva para o Storage: aparece na prévia, na aprovação e publica sozinho."""
    from services.studio_art_import import import_art
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    await _agency_only(authorization)
    try:
        return await import_art(cid, body.url, str(body.item_id) if body.item_id else None)
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/calendar/items/{item_id}/art/upload")
async def art_upload_target(client_id: str, item_id: UUID, body: ArtUploadInput, authorization: str | None = Header(default=None)):
    """Link assinado para o navegador enviar a arte (JPG/MP4) direto ao Storage; devolve também o link público."""
    from services.studio_art import upload_target
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    await _agency_only(authorization)
    try:
        return await upload_target(cid, str(item_id), body.content_type)
    except StudioError as exc:
        raise _http(exc) from None


MEMBERS = ("agency_admin", "client_admin", "viewer", "owner", "admin")


class CommentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=2000)


@router.get("/calendar/items/{item_id}/comments")
async def read_item_comments(client_id: str, item_id: UUID, authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id, authorization)
    try:
        return {"comments": await list_comments(cid, str(item_id), agency=await is_agency_user(authorization))}
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/calendar/items/{item_id}/comments", status_code=201)
async def write_item_comment(client_id: str, item_id: UUID, body: CommentInput, authorization: str | None = Header(default=None)):
    # Qualquer pessoa da empresa comenta (inclusive leitor); o post precisa estar visível para ela.
    cid = await require_client_role(client_id, authorization, allowed_roles=MEMBERS)
    uid = await require_user_id(authorization)
    try:
        comment = await add_comment(cid, str(item_id), body.body, agency=await is_agency_user(authorization), user_id=uid)
    except StudioError as exc:
        raise _http(exc) from None
    return {"ok": True, "comment": comment}


# ---------------------------------------------------------------- referências da marca

ERRORS.update({
    "REFERENCE_URL_INVALID": (422, "Cole um link completo começando com https:// (Instagram, Pinterest, Drive...)."),
    "REFERENCE_TYPE_INVALID": (422, "Envie uma imagem JPG, PNG ou WEBP."),
    "REFERENCE_NOT_FOUND": (404, "Referência não encontrada."),
})


class ReferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=12, max_length=2000)
    note: Optional[str] = Field(default=None, max_length=500)
    kind: Literal["link", "arte"] = "link"


class ReferenceUploadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_type: Literal["image/jpeg", "image/png", "image/webp"]


@router.get("/references")
async def read_references(client_id: str, authorization: str | None = Header(default=None)):
    from services.studio_references import list_references
    cid = await require_client_read(client_id, authorization)
    uid = await require_user_id(authorization)
    agency = await is_agency_user(authorization)
    rows = await list_references(cid)
    return {"references": [{**{k: v for k, v in r.items() if k != "author_id"},
                            "can_delete": agency or str(r.get("author_id") or "") == uid} for r in rows]}


@router.post("/references", status_code=201)
async def write_reference(client_id: str, body: ReferenceInput, authorization: str | None = Header(default=None)):
    # Qualquer pessoa da empresa (inclusive leitor) pode mandar referência.
    from services.studio_references import add_reference
    cid = await require_client_role(client_id, authorization, allowed_roles=MEMBERS)
    uid = await require_user_id(authorization)
    try:
        row = await add_reference(cid, url=body.url, note=body.note, kind=body.kind,
                                  agency=await is_agency_user(authorization), user_id=uid)
    except StudioError as exc:
        raise _http(exc) from None
    return {"ok": True, "reference": {k: v for k, v in row.items() if k != "author_id"}}


@router.post("/references/upload")
async def reference_upload_target(client_id: str, body: ReferenceUploadInput, authorization: str | None = Header(default=None)):
    from services.studio_references import upload_target
    cid = await require_client_role(client_id, authorization, allowed_roles=MEMBERS)
    try:
        return await upload_target(cid, body.content_type)
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/calendar/items/{item_id}/references")
async def read_item_references(client_id: str, item_id: UUID, authorization: str | None = Header(default=None)):
    from services.studio_comments import _item
    from services.studio_references import list_references
    cid = await require_client_read(client_id, authorization)
    uid = await require_user_id(authorization)
    agency = await is_agency_user(authorization)
    try:
        await _item(cid, str(item_id), agency=agency)  # cliente só vê referência de post que pode ver
    except StudioError as exc:
        raise _http(exc) from None
    rows = await list_references(cid, str(item_id))
    return {"references": [{**{k: v for k, v in r.items() if k != "author_id"},
                            "can_delete": agency or str(r.get("author_id") or "") == uid} for r in rows]}


@router.post("/calendar/items/{item_id}/references", status_code=201)
async def write_item_reference(client_id: str, item_id: UUID, body: ReferenceInput, authorization: str | None = Header(default=None)):
    from services.studio_comments import _item
    from services.studio_references import add_reference
    cid = await require_client_role(client_id, authorization, allowed_roles=MEMBERS)
    uid = await require_user_id(authorization)
    agency = await is_agency_user(authorization)
    try:
        item = await _item(cid, str(item_id), agency=agency)
        row = await add_reference(cid, url=body.url, note=body.note, kind=body.kind, agency=agency, user_id=uid, item=item)
    except StudioError as exc:
        raise _http(exc) from None
    return {"ok": True, "reference": {k: v for k, v in row.items() if k != "author_id"}}


@router.delete("/references/{reference_id}")
async def remove_reference(client_id: str, reference_id: UUID, authorization: str | None = Header(default=None)):
    from services.studio_references import delete_reference
    cid = await require_client_role(client_id, authorization, allowed_roles=MEMBERS)
    uid = await require_user_id(authorization)
    try:
        await delete_reference(cid, str(reference_id), agency=await is_agency_user(authorization), user_id=uid)
    except StudioError as exc:
        raise _http(exc) from None
    return {"ok": True}


@router.delete("/calendar/items/{item_id}")
async def remove_item(client_id: str, item_id: UUID, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    await _agency_only(authorization)
    try:
        await delete_item(cid, str(item_id))
    except StudioError as exc:
        raise _http(exc) from None
    return {"ok": True}


# ---------------------------------------------------------------- motores de conteúdo


ERRORS.update({
    "ITEM_TITLE_REQUIRED": (422, "Dê um título à pauta antes de pedir ajuda à IA."),
    "CHAT_EMPTY": (422, "Escreva uma pergunta."),
    "AI_RATE_LIMIT": (429, "Muitos pedidos à IA em sequência. Aguarde um minuto."),
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
    item_id: Optional[UUID] = None  # post salvo: a IA usa as referências dele


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    messages: List[ChatMessage] = Field(min_length=1, max_length=30)


class SuggestInput(BaseModel):
    # Sem campos desde a remoção da Biblioteca (o guia em PDF saiu junto).
    # "ignore" mantém compatível um navegador com a versão anterior em cache.
    model_config = ConfigDict(extra="ignore")


@router.get("/intelligence")
async def read_intelligence(client_id: str, authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id, authorization)
    return {"based_on": coverage(await build_content_intelligence(cid)), "actions": list(ASSIST_ACTIONS)}


@router.post("/assist")
async def run_assist(client_id: str, body: AssistInput, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        return await assist(cid, body.action, body.item.model_dump(), instruction=body.instruction,
                            item_id=str(body.item_id) if body.item_id else None)
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/strategy/chat")
async def run_strategy_chat(client_id: str, body: ChatInput, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        return await strategy_chat(cid, body.month, [m.model_dump() for m in body.messages])
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/brand-profile/suggestion")
async def read_profile_suggestion(client_id: str, authorization: str | None = Header(default=None)):
    """Sugestão mensal pendente de revisão (gerada pelo job do dia 1)."""
    from services.studio_brand_brain import pending_suggestion
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    await _agency_only(authorization)
    return {"suggestion": await pending_suggestion(cid)}


class SuggestionStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["aplicada", "descartada"]


@router.post("/brand-profile/suggestion/{suggestion_id}")
async def write_profile_suggestion(client_id: str, suggestion_id: UUID, body: SuggestionStatusInput,
                                   authorization: str | None = Header(default=None)):
    from services.studio_brand_brain import resolve_suggestion
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    await _agency_only(authorization)
    uid = await require_user_id(authorization)
    try:
        return await resolve_suggestion(cid, str(suggestion_id), body.status, user_id=uid)
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/brand-profile/suggest")
async def run_profile_suggestion(client_id: str, body: SuggestInput, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        return await suggest_profile(cid)
    except StudioError as exc:
        raise _http(exc) from None


# ---------------------------------------------------------------- aprovação do cliente


ERRORS.update({
    "NO_ITEMS": (422, "Selecione ao menos uma pauta."),
    "ITEMS_INVALID": (422, "Alguma pauta não existe nesta empresa ou está rejeitada."),
    "PHONE_INVALID": (422, "Telefone inválido. Use DDD + número (fora do Brasil, comece com + e o código do país)."),
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
    # Cópia da mesma mensagem (mesmo link) para a equipe Mugô cadastrada na Central de Automações.
    notify_team: bool = True


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
    from services.studio_history import record
    who = _chat_author(authorization, uid)
    for iid in body.item_ids:
        await record(cid, str(iid), f"enviou para aprovação do cliente{f' ({name})' if name else ''}", actor_name=who, actor_id=uid)
    if body.send_whatsapp and body.contact_id:
        # O link já existe; falha no WhatsApp não desfaz o pedido, só volta como aviso.
        try:
            created["whatsapp"] = await send_message(cid, "aprovacao", user_id=uid, contact_id=str(body.contact_id),
                                                     request_id=str(created["request_id"]))
        except StudioError as exc:
            created["whatsapp"] = {"status": "falhou", "detail": ERRORS.get(exc.code, (0, "Não foi possível enviar agora."))[1]}
        if body.notify_team:
            from services.studio_messages import send_approval_to_team
            created["team"] = await send_approval_to_team(cid, str(created["request_id"]), user_id=uid)
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
        result = await pipeline(cid, month)
    except StudioError as exc:
        raise _http(exc) from None
    if not await is_agency_user(authorization):
        result["items"] = [i for i in result["items"] if i.get("stage") in CLIENT_STAGES]
        result["counts"] = {stage: (n if stage in CLIENT_STAGES else 0) for stage, n in result["counts"].items()}
    return result


# ---------------------------------------------------------------- contatos e mensagens (MugôZap)


ERRORS.update({
    "CONTACT_NOT_FOUND": (404, "Contato não encontrado nesta empresa."),
    "CONTACT_REQUIRED": (422, "Cadastre um contato que receba esse tipo de mensagem (aba Contatos)."),
    "LINK_NOT_RESENDABLE": (409, "Este pedido foi criado antes do lembrete existir. Gere um novo link para reenviar."),
    "NOTHING_PENDING": (409, "O cliente já respondeu todas as pautas deste pedido."),
    "NOTHING_SCHEDULED": (409, "Nenhuma pauta aprovada para esta semana."),
    "NO_PAID_DATA": (409, "Sem investimento em mídia nos últimos 7 dias."),
    "NO_RESULTS_DATA": (409, "Sem faturamento do mês anterior para montar o resumo."),
    "MUGOZAP_REQUIRED": (409, "O convite com botões só funciona pelo WhatsApp oficial da Mugô (MugôZap). Configure as variáveis MUGOZAP_* no Render."),
    "CLIENT_FIELD_NOT_ALLOWED": (403, "Você pode editar título, gancho, legenda e data; o resto fica com a equipe Mugô."),
    "CLIENT_STATUS_NOT_ALLOWED": (403, "Você pode aprovar ou pedir ajuste neste post."),
    "NO_STORE_DATA": (409, "Sem faturamento da loja nesse período (nem no indicador oficial, nem na Origem das vendas). A mensagem não sai com número faltando."),
    "DATA_MISSING": (409, "Falta um dado para montar essa mensagem. Confira as integrações antes de enviar."),
    "HEADER_IMAGE_REQUIRED": (422, "O template com arte precisa de uma imagem anexada à pauta."),
    "BUTTON_PARAM_REQUIRED": (422, "O template precisa do link de aprovação."),
    "TEMPLATE_NOT_APPROVED": (409, "O template ainda não está aprovado pela Meta no MugôZap."),
    "RECIPIENT_NOT_IN_CRM": (409, "Esse telefone não está cadastrado no CRM. Cadastre o contato no CRM e tente de novo."),
    "SEND_OUTCOME_UNKNOWN": (409, "Um envio anterior ainda não foi confirmado. Confira o histórico no CRM antes de reenviar."),
    "MUGOZAP_UNAVAILABLE": (502, "O MugôZap não respondeu. Tente novamente."),
    "MUGOZAP_NOT_CONFIGURED": (503, "O envio pelo número oficial da Mugô não está configurado no servidor. Configure no Render: " + ", ".join(MUGOZAP_ENV) + "."),
    "SEND_FAILED": (502, "O MugôZap não conseguiu enviar a mensagem."),
})

MessageKind = Literal["aprovacao", "lembrete", "agenda", "trafego", "resultados", "semanal", "convite"]
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
    return {"contacts": await list_contacts(cid), "whatsapp_channel": whatsapp_channel(), "whatsapp_missing": mugozap_missing()}


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


@router.get("/brand-context")
async def brand_context(client_id: str, authorization: str | None = Header(default=None)):
    """O que a IA de Calendário, Redação, Mídia On e Clipping sabe da marca, num lugar só (só a equipe)."""
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    await _agency_only(authorization)
    from services.studio_intelligence import build_content_intelligence
    intel = await build_content_intelligence(cid)
    return {k: intel.get(k) for k in ("marca", "negocio", "aprendizados", "campanhas_ativas", "plano_de_midia", "calendario_do_mes",
                                      "clipping", "referencias_do_cliente", "metas_do_mes", "lacunas")}


@router.get("/messages")
async def read_messages(client_id: str, request_id: UUID | None = None, authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id, authorization)
    return {"messages": await list_messages(cid, request_id=str(request_id) if request_id else None), "templates": sorted(TEMPLATES),
            "whatsapp_channel": whatsapp_channel(), "whatsapp_missing": mugozap_missing()}


@router.post("/messages/preview")
async def preview_message(client_id: str, body: MessageInput, authorization: str | None = Header(default=None)):
    # Prévia chama a IA para a frase de destaque: mesma permissão de quem envia.
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    await _agency_only(authorization)
    try:
        return public_preview(await build_message(cid, body.kind, **_message_args(body)))
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/messages/send")
async def send_studio_message(client_id: str, body: MessageInput, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    await _agency_only(authorization)
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

Objective = Literal["vendas", "leads", "trafego", "alcance", "retencao", "remarketing"]
Channel = Literal["meta", "google_ads"]


class StrategyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    objective: Objective = "vendas"
    margin: Optional[float] = Field(default=None, gt=0, lt=1)
    budget: Optional[float] = Field(default=None, gt=0, le=100000000)
    distribution: Literal["equilibrado", "hiperfoco"] = "equilibrado"
    briefing: Optional[str] = Field(default=None, max_length=2000)
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
    await _agency_only(authorization)  # cliente vê o plano salvo; gerar e mudar verba é da Mugô
    uid = await require_user_id(authorization)
    try:
        strategy = await build_strategy(cid, month=body.month, objective=body.objective, margin=body.margin, custom_budget=body.budget,
                                        distribution=body.distribution, briefing=body.briefing)
    except StudioError as exc:
        raise _http(exc) from None
    except Exception as exc:  # erro inesperado: registra no log do Render e devolve mensagem clara (nunca a genérica)
        import traceback
        print(f"[media][strategy] erro_inesperado client={cid} tipo={exc.__class__.__name__}\n{traceback.format_exc()[-2000:]}")
        raise HTTPException(status_code=500, detail="Não foi possível calcular a estratégia agora (erro interno, já registrado no log). "
                                                    "Tente de novo em instantes; se repetir, avise com o horário.") from None
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
    await _agency_only(authorization)  # rascunhos de estratégia são da Mugô; o cliente vê só o plano salvo
    try:
        return {"strategies": await list_strategies(cid, month)}
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/media/strategies/{strategy_id}")
async def read_media_strategy(client_id: str, strategy_id: UUID, authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id, authorization)
    await _agency_only(authorization)  # rascunhos de estratégia são da Mugô; o cliente vê só o plano salvo
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
    await _agency_only(authorization)  # cliente vê o plano salvo; gerar e mudar verba é da Mugô
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


# ---------------------------------------------------------------- engajamento no Instagram (tipo ManyChat)


class EngagementReply(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=1000)
    direct: bool = False


class EngagementRule(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    keywords: List[str] = Field(min_length=1, max_length=20)
    media_id: Optional[str] = Field(default=None, pattern=r"^[0-9]{5,40}$")
    public_reply: Optional[str] = Field(default=None, max_length=300)
    dm_message: Optional[str] = Field(default=None, max_length=1000)
    # Oi no Direct escrito pela IA no tom do perfil da marca; dm_message vira o que a mensagem precisa levar (link etc.).
    ai_greeting: bool = False
    active: bool = False


def _rule_row(body: EngagementRule) -> Dict[str, Any]:
    keywords = [k.strip()[:60] for k in body.keywords if k.strip()]
    if not keywords or not (body.public_reply or body.dm_message or body.ai_greeting):
        raise HTTPException(422, "Informe pelo menos uma palavra-chave e uma resposta (pública, no Direct ou o oi feito pela IA).")
    return {"name": body.name, "keywords": keywords, "media_id": body.media_id or None,
            "public_reply": body.public_reply or None, "dm_message": body.dm_message or None,
            "ai_greeting": body.ai_greeting, "active": body.active}


ERRORS.update({
    "IG_NOT_CONNECTED": (409, "Conecte o Instagram desta marca em Integrações."),
    "IG_PERMISSION_MISSING": (409, "Falta permissão no Meta: reconecte o Instagram da marca em Integrações para liberar respostas e Direct."),
    "IG_PAGE_NOT_FOUND": (409, "Não achei a página do Facebook ligada a este Instagram. Reconecte a marca escolhendo a página."),
    "IG_SEND_FAILED": (502, "O Instagram recusou o envio agora. Tente de novo em instantes."),
    "DIRECT_WINDOW_CLOSED": (422, "O Instagram só permite Direct até 7 dias depois do comentário."),
    "COMMENT_NOT_FOUND": (404, "Comentário não encontrado nesta marca."),
    "ART_TYPE_INVALID": (422, "Envie a arte em JPG (imagem) ou MP4/MOV (vídeo)."),
    "STORAGE_NOT_CONFIGURED": (503, "Armazenamento de arquivos não configurado no servidor."),
    "STORAGE_UPLOAD_FAILED": (502, "Não foi possível preparar o envio do arquivo. Tente de novo."),
    "SCHEDULE_NEEDS_APPROVAL": (409, "Só dá para agendar um post aprovado pelo cliente."),
    "SCHEDULE_IN_PAST": (409, "O horário do post já passou. Clique em Publicar agora ou ajuste a data e o horário."),
    "REPLY_EMPTY": (422, "Escreva a resposta."),
})


@router.get("/engagement/replies")
async def engagement_replies(client_id: str, days: int = Query(default=30, ge=1, le=90), authorization: str | None = Header(default=None)):
    from services.ig_engagement import replies_by_post
    # Visível ao cliente também: o que a marca respondeu em cada publicação.
    cid = await require_client_read(client_id, authorization)
    return await replies_by_post(cid, days=days)


@router.get("/engagement/comments")
async def engagement_inbox(client_id: str, open_only: bool = True, authorization: str | None = Header(default=None)):
    from services.ig_engagement import get_settings, inbox, last_ai_run
    # Visível ao cliente: caixa da própria marca (o que a IA respondeu, o que está em revisão).
    cid = await require_client_read(client_id, authorization)
    return {**await inbox(cid, only_open=open_only), "settings": await get_settings(cid), "last_ai_run": await last_ai_run(cid)}


class EngagementSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ai_autoreply: Optional[bool] = None
    reply_tone: Optional[str] = Field(default=None, max_length=500)


@router.put("/engagement/settings")
async def engagement_settings(client_id: str, body: EngagementSettings, authorization: str | None = Header(default=None)):
    from services.ig_engagement import save_settings
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    return await save_settings(cid, user_id=uid, ai_autoreply=body.ai_autoreply, reply_tone=body.reply_tone,
                               set_tone="reply_tone" in body.model_fields_set)


class DirectSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    welcome_enabled: Optional[bool] = None
    welcome_followers_only: Optional[bool] = None
    welcome_content: Optional[str] = Field(default=None, max_length=1000)
    ai_enabled: Optional[bool] = None


@router.get("/engagement/direct")
async def engagement_direct(client_id: str, authorization: str | None = Header(default=None)):
    from services.ig_direct import overview
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    return await overview(cid)


@router.put("/engagement/direct/settings")
async def engagement_direct_settings(client_id: str, body: DirectSettings, authorization: str | None = Header(default=None)):
    from services.ig_direct import save_settings, subscribe_page
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    changes = body.model_dump(exclude_unset=True)
    settings = await save_settings(cid, user_id=uid, **changes)
    subscribed: Optional[str] = None
    if settings["welcome_enabled"] or settings["ai_enabled"]:
        try:  # liga a página ao webhook do app (idempotente)
            await subscribe_page(cid)
            subscribed = "ok"
        except StudioError as exc:
            subscribed = exc.code
    return {"settings": settings, "subscribed": subscribed}


@router.post("/engagement/refresh")
async def engagement_refresh(client_id: str, authorization: str | None = Header(default=None)):
    from services.ig_engagement import capabilities, credentials, refresh_comments
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        creds = await credentials(cid)
        return {"comments": await refresh_comments(cid, creds=creds), "can": capabilities(creds["scopes"])}
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/engagement/comments/{comment_id}/suggest")
async def engagement_suggest(client_id: str, comment_id: str, authorization: str | None = Header(default=None)):
    from services.ig_engagement import suggest_reply
    from services.studio_engines import throttle
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        throttle(cid)
        return await suggest_reply(cid, comment_id)
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/engagement/comments/{comment_id}/reply")
async def engagement_reply(client_id: str, comment_id: str, body: EngagementReply, authorization: str | None = Header(default=None)):
    from services.ig_engagement import manual_reply
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    try:
        return await manual_reply(cid, comment_id, body.text, actor=f"equipe:{uid}", direct=body.direct)
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/engagement/rules")
async def engagement_rules(client_id: str, authorization: str | None = Header(default=None)):
    from services.ig_engagement import autoreply_enabled, list_rules, rule_stats
    # Gatilhos: equipe Mugô e admin da própria empresa (WRITERS); viewer não vê nem mexe.
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        stats = await rule_stats(cid)
    except Exception as exc:  # noqa: BLE001 — a contagem nunca derruba a lista de gatilhos
        print(f"[engagement] rule_stats client_id={cid} error_type={exc.__class__.__name__}")
        stats = {}
    return {"rules": await list_rules(cid), "stats": stats, "autoreply_enabled": autoreply_enabled()}


@router.post("/engagement/rules", status_code=201)
async def engagement_rule_create(client_id: str, body: EngagementRule, authorization: str | None = Header(default=None)):
    from services.ig_engagement import RULES
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    row = await sb_insert(RULES, {"client_id": cid, "created_by": uid, **_rule_row(body)})
    return {"rule": row}


@router.put("/engagement/rules/{rule_id}")
async def engagement_rule_update(client_id: str, rule_id: UUID, body: EngagementRule, authorization: str | None = Header(default=None)):
    from services.ig_engagement import RULES
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    rows = await sb_update(RULES, filters={"client_id": f"eq.{cid}", "id": f"eq.{rule_id}"},
                           patch={**_rule_row(body), "updated_at": datetime.now(timezone.utc).isoformat()})
    if not rows:
        raise HTTPException(404, "Gatilho não encontrado.")
    return {"rule": rows[0]}


@router.delete("/engagement/rules/{rule_id}")
async def engagement_rule_delete(client_id: str, rule_id: UUID, authorization: str | None = Header(default=None)):
    from services.ig_engagement import RULES
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    rows = await sb_delete(RULES, filters={"client_id": f"eq.{cid}", "id": f"eq.{rule_id}"})
    if not rows:
        raise HTTPException(404, "Gatilho não encontrado.")
    return {"ok": True}


@router.post("/engagement/rules/run")
async def engagement_rules_run(client_id: str, authorization: str | None = Header(default=None)):
    """Roda os gatilhos agora (o job faz o mesmo a cada 5 min). Sem IG_AUTOREPLY_ENABLED=true, só simula."""
    from services.ig_engagement import run_rules
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        return await run_rules(cid)
    except StudioError as exc:
        raise _http(exc) from None


# ---------------------------------------------------------------- relatório social do mês

ERRORS.update({
    "REPORT_NOT_BUILT": (404, "O relatório deste mês ainda não foi gerado."),
})


@router.get("/social-report/{month}")
async def social_report_read(client_id: str, month: str, authorization: str | None = Header(default=None)):
    """Relatório do mês já gerado (com os links das imagens renovados). Qualquer membro da marca lê."""
    from services.social_report import load
    cid = await require_client_read(client_id, authorization)
    try:
        return await load(cid, month)
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/social-report/{month}/build")
async def social_report_build(client_id: str, month: str, authorization: str | None = Header(default=None)):
    """Busca os números do mês na Meta e no banco e grava o retrato (os insights salvos são mantidos)."""
    from services.social_report import build
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    await _agency_only(authorization)
    try:
        return await build(cid, month)
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/social-report/{month}/insights/draft")
async def social_report_draft(client_id: str, month: str, authorization: str | None = Header(default=None)):
    """Rascunho dos insights pela IA, a partir dos números (não grava: a equipe revisa e salva)."""
    from services.social_report import draft_insights
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    await _agency_only(authorization)
    try:
        return {"insights": await draft_insights(cid, month)}
    except StudioError as exc:
        raise _http(exc) from None


class ReportInsightsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    insights: List[str] = Field(default_factory=list, max_length=8)


@router.put("/social-report/{month}/insights")
async def social_report_insights(client_id: str, month: str, body: ReportInsightsInput,
                                 authorization: str | None = Header(default=None)):
    from services.social_report import save_insights
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    await _agency_only(authorization)
    uid = await require_user_id(authorization)
    try:
        return await save_insights(cid, month, body.insights, user_id=uid)
    except StudioError as exc:
        raise _http(exc) from None


# ---------------------------------------------------------------- conversa da marca e linha do tempo

ERRORS.update({
    "AI_TENANT_LEAK": (422, "A IA citou outra marca atendida pela Mugô e a resposta foi bloqueada. Confira os materiais desta marca (pode haver conteúdo de outro cliente) e tente de novo."),
    "CHAT_CHANNEL_INVALID": (422, "Canal inválido."),
    "CHAT_FORBIDDEN": (403, "Este canal é só da equipe Mugô."),
    "CHAT_BODY_REQUIRED": (422, "Escreva a mensagem."),
})


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=4000)
    item_id: Optional[UUID] = None


def _chat_author(authorization: str | None, uid: str) -> str:
    from services.auth import _bearer_token, _decode_jwt_claims_no_verify
    from services.studio_chat import author_name_from_claims
    claims = _decode_jwt_claims_no_verify(_bearer_token(authorization) or "") or {}
    # O token já foi validado por require_user_id; o nome só é usado se for do mesmo usuário.
    return author_name_from_claims(claims if str(claims.get("sub") or "") == uid else {})


@router.get("/chat/{channel}")
async def read_chat(client_id: str, channel: str, authorization: str | None = Header(default=None)):
    from services.studio_chat import list_messages, mark_read
    cid = await require_client_read(client_id, authorization)
    uid = await require_user_id(authorization)
    try:
        rows = await list_messages(cid, channel, agency=await is_agency_user(authorization), user_id=uid)
        await mark_read(cid, channel, uid)
    except StudioError as exc:
        raise _http(exc) from None
    return {"messages": rows}


@router.post("/chat/{channel}", status_code=201)
async def write_chat(client_id: str, channel: str, body: ChatInput, authorization: str | None = Header(default=None)):
    from services.studio_chat import post_message
    cid = await require_client_role(client_id, authorization, allowed_roles=MEMBERS)
    uid = await require_user_id(authorization)
    try:
        row = await post_message(cid, channel, body.body, agency=await is_agency_user(authorization), user_id=uid,
                                 author_name=_chat_author(authorization, uid), item_id=str(body.item_id) if body.item_id else None)
    except StudioError as exc:
        raise _http(exc) from None
    return {"ok": True, "message": row}


@router.get("/chat-unread")
async def read_chat_unread(client_id: str, authorization: str | None = Header(default=None)):
    from services.studio_chat import unread
    cid = await require_client_read(client_id, authorization)
    uid = await require_user_id(authorization)
    try:
        return {"unread": await unread(cid, agency=await is_agency_user(authorization), user_id=uid)}
    except Exception:  # noqa: BLE001 — migração 000077 ainda não aplicada: sem contador, sem erro na tela
        return {"unread": {}}


@router.get("/timeline")
async def read_timeline(client_id: str, authorization: str | None = Header(default=None)):
    from services.studio_chat import timeline
    cid = await require_client_read(client_id, authorization)
    return {"events": await timeline(cid)}


# ---------------------------------------------------------------- conhecimento da marca (documentos alimentam a IA)

ERRORS.update({
    "DOC_TYPE_INVALID": (422, "Envie PDF, DOCX, PPTX, XLSX, CSV, TXT ou MD."),
    "DOC_UNREADABLE": (422, "Não deu para ler este arquivo (protegido por senha ou corrompido)."),
    "DOC_EMPTY": (422, "O arquivo não tem texto que dê para ler (ex.: PDF só de imagem)."),
    "DOC_TOO_LARGE": (413, "Arquivo grande demais (até 10 MB). Divida em partes."),
    "DOC_SOURCE_REQUIRED": (422, "Envie um arquivo ou cole um texto."),
    "DOC_SAVE_FAILED": (502, "Não foi possível guardar o material agora. Tente de novo."),
    "DOC_NOT_FOUND": (404, "Material não encontrado nesta empresa."),
    "FACTS_EMPTY": (422, "Nenhum fato para guardar."),
    "AGENT_QUESTION_EMPTY": (422, "Escreva uma pergunta sobre a marca."),
})


class KnowledgeDocInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_name: str = Field(default="Texto colado", max_length=200)
    kind: Literal["institucional", "produto", "campanha", "tom_de_voz", "restricao", "outro"] = "outro"
    content_base64: Optional[str] = Field(default=None, max_length=14_500_000)
    text: Optional[str] = Field(default=None, max_length=60_000)


class KnowledgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    knowledge: str = Field(max_length=6000)


class KnowledgeFactsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facts: List[str] = Field(min_length=1, max_length=5)


class BrandAgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=1000)


@router.get("/knowledge")
async def read_knowledge(client_id: str, authorization: str | None = Header(default=None)):
    from services.brand_knowledge import list_documents, load_knowledge
    cid = await require_client_read(client_id, authorization)
    return {**await load_knowledge(cid), "documents": await list_documents(cid)}


@router.post("/knowledge/documents", status_code=201)
async def add_knowledge_document(client_id: str, body: KnowledgeDocInput, authorization: str | None = Header(default=None)):
    """O texto do material é guardado em trechos ANTES da IA ler; o arquivo binário não fica.
    Se a IA falhar, responde 201 com ``warning`` e o documento em status 'falhou' (reprocessável)."""
    from services.brand_knowledge import decode_upload, extract_text, learn
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    try:
        if body.content_base64:
            text = extract_text(body.file_name, decode_upload(body.content_base64))
        elif body.text and len(body.text.strip()) >= 30:
            text = body.text.strip()
        else:
            raise StudioError("DOC_SOURCE_REQUIRED")
        return {"ok": True, **await learn(cid, file_name=body.file_name, kind=body.kind, text=text, user_id=uid)}
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/knowledge/documents/{document_id}/retry")
async def retry_knowledge_document(client_id: str, document_id: UUID, authorization: str | None = Header(default=None)):
    from services.brand_knowledge import retry
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        return {"ok": True, **await retry(cid, str(document_id), user_id=await require_user_id(authorization))}
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/knowledge/facts", status_code=201)
async def add_knowledge_facts(client_id: str, body: KnowledgeFactsInput, authorization: str | None = Header(default=None)):
    """Fatos confirmados na conversa com o agente entram na memória da marca."""
    from services.brand_knowledge import add_facts
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        return {"ok": True, **await add_facts(cid, body.facts, user_id=await require_user_id(authorization))}
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/brand-agent")
async def read_brand_agent(client_id: str, authorization: str | None = Header(default=None)):
    """Conversa da própria pessoa com o agente da marca (privada)."""
    from services.brand_agent import history
    cid = await require_client_read(client_id, authorization)
    return {"messages": await history(cid, await require_user_id(authorization))}


@router.post("/brand-agent")
async def ask_brand_agent(client_id: str, body: BrandAgentInput, authorization: str | None = Header(default=None)):
    from services.brand_agent import ask
    cid = await require_client_read(client_id, authorization)
    try:
        return {"ok": True, **await ask(cid, await require_user_id(authorization), body.question)}
    except StudioError as exc:
        raise _http(exc) from None


@router.delete("/brand-agent")
async def clear_brand_agent(client_id: str, authorization: str | None = Header(default=None)):
    from services.brand_agent import clear
    cid = await require_client_read(client_id, authorization)
    await clear(cid, await require_user_id(authorization))
    return {"ok": True}


@router.put("/knowledge")
async def write_knowledge(client_id: str, body: KnowledgeInput, authorization: str | None = Header(default=None)):
    from services.brand_knowledge import save_manual
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    return {"ok": True, **await save_manual(cid, body.knowledge, user_id=await require_user_id(authorization))}


# ---------------------------------------------------------------- Meta Business Suite da marca

def publisher_url(page_id: str | None) -> str:
    """Abre o criador de posts do Business Suite já na Página da marca (asset_id); sem página, o genérico."""
    import re as _re
    base = "https://business.facebook.com/latest/composer"
    pid = _re.sub(r"\D", "", str(page_id or ""))
    return f"{base}?asset_id={pid}" if pid else base


@router.get("/publisher")
async def read_publisher(client_id: str, authorization: str | None = Header(default=None)):
    """Link do Business Suite desta empresa (a Página vem da conexão orgânica do Instagram)."""
    from services.ig_supabase import sb_select
    cid = await require_client_read(client_id, authorization)
    try:
        rows = await sb_select("meta_connections", select="business_id,username,status,updated_at", order="updated_at.desc", limit=5,
                               filters={"client_id": f"eq.{cid}", "connection_type": "eq.organic", "platform": "eq.instagram"})
    except Exception:  # noqa: BLE001 — sem leitura: cai no link genérico
        rows = []
    row = next((r for r in rows if r.get("status") == "active" and r.get("business_id")), None) or next((r for r in rows if r.get("business_id")), None)
    page = str((row or {}).get("business_id") or "")
    return {"url": publisher_url(page), "page_id": page or None, "username": (row or {}).get("username")}


# ---------------------------------------------------------------- histórico de cada pauta (kanban interno)

@router.get("/calendar/items/{item_id}/history")
async def read_item_history(client_id: str, item_id: UUID, authorization: str | None = Header(default=None)):
    """Quem fez o quê nesta pauta (só a equipe Mugô)."""
    from services.studio_history import list_item
    cid = await require_client_read(client_id, authorization)
    await _agency_only(authorization)
    return {"events": await list_item(cid, str(item_id))}


@router.get("/calendar/history/latest")
async def read_latest_history(client_id: str, authorization: str | None = Header(default=None)):
    """Último acontecimento de cada pauta, para o cartão do kanban (só a equipe Mugô)."""
    from services.studio_history import latest_by_item
    cid = await require_client_read(client_id, authorization)
    await _agency_only(authorization)
    return {"latest": await latest_by_item(cid)}
