"""
Clipping da marca (só a equipe Mugô) e Social Media: Redação de campanha + Matriz de Conteúdo.

Social Media é um módulo com permissão própria (team_access: social_media.view / social_media.edit):
a equipe Mugô sempre tem; um usuário do cliente só quando a Mugô libera na tela de Usuários.
A ponte para o Calendário são pautas em rascunho, que seguem a aprovação de sempre.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from services import studio_campaigns as campaigns
from services import studio_clipping as clipping
from services import studio_documents as documents
from services import studio_matrix as matrix
from services.studio_calendar import StudioError
from services.tenant import is_agency_user, require_client_read, require_client_role, require_user_id

router = APIRouter(prefix="/api/clients/{client_id}/studio", tags=["studio-content-ops"])
AGENCY_ONLY = ("agency_admin",)
# Social Media: papel de escrita + permissão do módulo (social_media.*), checada em tenant._module_check.
SOCIAL_MEDIA = ("agency_admin", "client_admin")

ERRORS = {
    "CLIPPING_TERMS_REQUIRED": (422, "Informe pelo menos um termo da marca."),
    "CLIPPING_NOT_CONFIGURED": (409, "Configure os termos da marca antes de buscar notícias."),
    "CLIPPING_COOLDOWN": (429, "Acabamos de buscar. Tente de novo em alguns minutos."),
    "CLIPPING_NOT_FOUND": (404, "Notícia não encontrada."),
    "STATUS_INVALID": (400, "Status inválido."),
    "BRIEFING_REQUIRED": (422, "Dê um nome e um objetivo para a campanha."),
    "BRIEFING_DATE_INVALID": (422, "Data do briefing inválida."),
    "CAMPAIGN_NOT_FOUND": (404, "Campanha não encontrada."),
    "CHANNEL_INVALID": (400, "Peça inválida."),
    "NOTHING_FOR_CALENDAR": (409, "Esta campanha não tem post, Reels ou Stories para o Calendário."),
    "DOCUMENT_NOT_FOUND": (404, "Documento não encontrado."),
    "DOCUMENT_KIND_INVALID": (422, "Tipo de texto inválido."),
    "DOCUMENT_SAVE_FAILED": (502, "Não foi possível salvar o documento. Tente de novo."),
    "DOCUMENT_SELECTION_REQUIRED": (422, "Selecione o trecho do texto antes de pedir para a IA."),
    "DOCUMENT_INSTRUCTION_REQUIRED": (422, "Diga o que a IA deve escrever."),
    "DOCUMENT_EMPTY": (422, "O documento está vazio."),
    "DOCUMENT_DATE_REQUIRED": (422, "Escolha a data do post."),
    "ACTION_INVALID": (400, "Ação inválida."),
    "CHANNEL_INVALID": (422, "Plataforma inválida."),
    "MATRIX_PILLARS_REQUIRED": (422, "Cadastre os pilares editoriais no Perfil da marca (IA da marca) antes de gerar a matriz."),
    "MATRIX_PLATFORMS_REQUIRED": (422, "Defina as plataformas do planejamento no Perfil da marca antes de gerar a matriz."),
    "MATRIX_FREQUENCY_TOO_HIGH": (422, "A frequência semanal configurada ultrapassa o limite de 80 oportunidades por matriz."),
    "MATRIX_DATE_INVALID": (422, "Escolha uma semana a partir desta, até 4 meses à frente."),
    "MATRIX_NOT_FOUND": (404, "Matriz não encontrada."),
    "MATRIX_SAVE_FAILED": (502, "Não foi possível salvar a matriz. Tente de novo."),
    "MATRIX_NOTHING_SELECTED": (409, "Selecione pelo menos uma oportunidade para enviar ao Calendário."),
    "OPPORTUNITY_NOT_FOUND": (404, "Oportunidade não encontrada."),
    "OPPORTUNITY_EXPORTED": (409, "Esta oportunidade já está no Calendário. Edite o post por lá."),
    "OPPORTUNITY_INVALID": (422, "Confira os campos da oportunidade."),
    "FORMAT_INVALID": (422, "Formato inválido para esta plataforma."),
    "EMPTY_PATCH": (400, "Nada para alterar."),
    "CREATE_FAILED": (502, "Não foi possível criar a pauta no Calendário."),
    "AI_RATE_LIMIT": (429, "Muitas gerações em sequência. Aguarde um minuto."),
    "AI_PROVIDER_NOT_CONFIGURED": (503, "IA não configurada no servidor."),
    "AI_PROVIDER_TIMEOUT": (504, "A IA demorou demais. Tente de novo."),
    "AI_PROVIDER_QUOTA": (503, "A IA está sem crédito na OpenAI. Recarregue em platform.openai.com → Billing e tente de novo. O consumo por cliente está em Administração → Consumo de IA."),
    "AI_PROVIDER_ERROR": (502, "A IA não respondeu agora. Tente de novo."),
    "AI_INVALID_OUTPUT": (502, "A IA devolveu algo fora do formato. Tente de novo."),
}


def _http(exc: StudioError) -> HTTPException:
    status, detail = ERRORS.get(exc.code, (502, "Não foi possível concluir agora."))
    return HTTPException(status_code=status, detail=detail, headers={"Retry-After": "60"} if status == 429 else None)


class ClippingSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand_terms: List[str] = Field(default_factory=list, max_length=6)
    competitor_terms: List[str] = Field(default_factory=list, max_length=6)
    exclude_terms: List[str] = Field(default_factory=list, max_length=6)
    people: Optional[List[str]] = Field(default=None, max_length=6)
    keywords: Optional[List[str]] = Field(default=None, max_length=6)
    themes: Optional[List[str]] = Field(default=None, max_length=6)
    feeds: Optional[List[str]] = Field(default=None, max_length=10)
    region: Optional[str] = Field(default=None, max_length=120)
    relevance_criteria: Optional[str] = Field(default=None, max_length=1000)
    min_relevance: Optional[int] = Field(default=None, ge=0, le=100)
    active: bool = True


class ClippingReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: Literal["diario", "semanal", "mensal"] = "semanal"
    focus: Literal["cobertura", "concorrentes", "setor", "riscos"] = "cobertura"


class ClippingStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["novo", "lido", "arquivado"]


class ClippingCalendarInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: Optional[str] = Field(default=None, max_length=10)


Channel = Literal["meta_ads", "google_ads", "post", "reels", "stories", "whatsapp", "email"]


class BriefingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=160)
    objective: str = Field(min_length=1, max_length=400)
    offer: str = Field(default="", max_length=600)
    audience: str = Field(default="", max_length=400)
    start: str = Field(default="", max_length=10)
    end: str = Field(default="", max_length=10)
    notes: str = Field(default="", max_length=1000)
    channels: List[Channel] = Field(default_factory=lambda: ["post", "reels", "meta_ads"], min_length=1, max_length=7)


class RegenerateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: Optional[str] = Field(default=None, max_length=600)


class PieceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: Any


class CampaignStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["rascunho", "pronta", "arquivada"]


# ---------------------------------------------------------------- clipping

def _client_visible(item: Dict[str, Any]) -> bool:
    """Cliente vê só o relevante; crise/negativa crítica só depois que a equipe revisou (status ≠ novo)."""
    return item.get("relevant") is not False and not (clipping.needs_alert(item) and item.get("status") == "novo")


CLIENT_HIDDEN = {"justification", "evidence", "alert_status", "url_hash"}


@router.get("/clipping")
async def read_clipping(client_id: str, kind: Optional[str] = None, sentiment: Optional[str] = None,
                        q: Optional[str] = Query(default=None, max_length=60), theme: Optional[str] = Query(default=None, max_length=60),
                        min_relevance: Optional[int] = Query(default=None, ge=0, le=100), criticality: Optional[str] = None,
                        authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    # Cliente lê o clipping da própria empresa; configurar, buscar e tratar notícias é da agência.
    cid = await require_client_read(client_id, authorization)
    view = await clipping.list_clippings(cid, kind=kind, sentiment=sentiment, q=q, theme=theme,
                                         min_relevance=min_relevance, criticality=criticality)
    if await is_agency_user(authorization):
        return view
    settings = view.get("settings") or {}
    return {
        "items": [{k: v for k, v in item.items() if k not in CLIENT_HIDDEN} for item in view.get("items") or [] if _client_visible(item)],
        "week": view.get("week"),
        "settings": {"saved": settings.get("saved"), "last_run_at": settings.get("last_run_at")},
    }


@router.get("/clipping/insights")
async def clipping_insights(client_id: str, days: int = Query(default=30, ge=1, le=90), authorization: Optional[str] = Header(default=None)):
    cid = await require_client_read(client_id, authorization)
    agency = await is_agency_user(authorization)
    rows = await clipping.period_rows(cid, days, relevant_only=not agency)
    if not agency:
        rows = [r for r in rows if _client_visible(r)]
    return clipping.insights_from(rows, days)


@router.post("/clipping/report")
async def clipping_report(client_id: str, body: ClippingReportInput, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY_ONLY)
    try:
        return await clipping.build_report(cid, body.period, body.focus)
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/clipping/export")
async def clipping_export(client_id: str, days: int = Query(default=30, ge=1, le=90), authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY_ONLY)
    rows = await clipping.period_rows(cid, days)
    return Response(clipping.export_csv(rows), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="clipping-{cid}-{days}d.csv"'})


@router.post("/clipping/settings/suggest")
async def suggest_clipping_settings(client_id: str, authorization: Optional[str] = Header(default=None)):
    """Rascunho do radar pela IA (nome, contexto de negócio, perfil e posts). Não grava: a equipe revisa e salva."""
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY_ONLY)
    from services.business_brain import suggest_radar
    from services.studio_engines import throttle
    try:
        throttle(cid)
        return await suggest_radar(cid)
    except StudioError as exc:
        raise _http(exc) from None


@router.put("/clipping/settings")
async def write_clipping_settings(client_id: str, body: ClippingSettingsInput, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY_ONLY)
    uid = await require_user_id(authorization)
    try:
        return await clipping.save_settings(cid, body.model_dump(exclude_none=True), user_id=uid)
    except StudioError as exc:
        raise _http(exc) from None
    except httpx.HTTPStatusError as exc:
        # Coluna do radar ausente no banco (migração 000073 não aplicada): erro claro em vez de 500 sem CORS.
        print(f"[clipping] save_settings client_id={cid} status={exc.response.status_code if exc.response is not None else '?'}")
        raise HTTPException(status_code=503, detail="Não foi possível salvar o radar: o banco ainda não tem os campos novos "
                                                    "do clipping (migração 000073). Fale com a equipe técnica.") from None


@router.post("/clipping/refresh")
async def refresh_clipping(client_id: str, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY_ONLY)
    try:
        return await clipping.refresh(cid, manual=True)
    except StudioError as exc:
        raise _http(exc) from None


@router.patch("/clipping/{clipping_id}")
async def update_clipping(client_id: str, clipping_id: UUID, body: ClippingStatusInput, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY_ONLY)
    try:
        return await clipping.set_status(cid, str(clipping_id), body.status)
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/clipping/{clipping_id}/calendar")
async def clipping_to_calendar(client_id: str, clipping_id: UUID, body: ClippingCalendarInput, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY_ONLY)
    uid = await require_user_id(authorization)
    try:
        return await clipping.to_calendar(cid, str(clipping_id), user_id=uid, date_iso=body.date)
    except StudioError as exc:
        raise _http(exc) from None


# ---------------------------------------------------------------- campanhas

@router.get("/campaigns")
async def read_campaigns(client_id: str, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    return {"campaigns": await campaigns.list_campaigns(cid), "channels": campaigns.CHANNEL_LABELS, "limits": campaigns.LIMITS}


@router.post("/campaigns", status_code=201)
async def create_campaign(client_id: str, body: BriefingInput, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    uid = await require_user_id(authorization)
    try:
        return {"campaign": await campaigns.generate(cid, body.model_dump(), user_id=uid)}
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/campaigns/{campaign_id}")
async def read_campaign(client_id: str, campaign_id: UUID, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    try:
        return {"campaign": await campaigns.get_campaign(cid, str(campaign_id))}
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/campaigns/{campaign_id}/pieces/{channel}/regenerate")
async def regenerate_piece(client_id: str, campaign_id: UUID, channel: Channel, body: RegenerateInput,
                           authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    try:
        return {"campaign": await campaigns.regenerate_piece(cid, str(campaign_id), channel, instruction=body.instruction)}
    except StudioError as exc:
        raise _http(exc) from None


@router.put("/campaigns/{campaign_id}/pieces/{channel}")
async def edit_piece(client_id: str, campaign_id: UUID, channel: Channel, body: PieceInput, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    try:
        return {"campaign": await campaigns.edit_piece(cid, str(campaign_id), channel, body.content)}
    except StudioError as exc:
        raise _http(exc) from None


@router.patch("/campaigns/{campaign_id}")
async def update_campaign(client_id: str, campaign_id: UUID, body: CampaignStatusInput, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    try:
        return {"campaign": await campaigns.set_status(cid, str(campaign_id), body.status)}
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/campaigns/{campaign_id}/calendar")
async def campaign_to_calendar(client_id: str, campaign_id: UUID, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    uid = await require_user_id(authorization)
    try:
        return await campaigns.to_calendar(cid, str(campaign_id), user_id=uid)
    except StudioError as exc:
        raise _http(exc) from None


# ---------------------------------------------------------------- matriz de conteúdo

Platform = Literal["instagram", "facebook", "tiktok", "linkedin", "youtube", "pinterest"]
MatrixFormat = Literal["reels", "carrossel", "imagem", "stories", "video"]


class MatrixInput(BaseModel):
    """Campos legados são aceitos durante o rollout, mas a geração usa somente o Perfil da marca."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    week_start: str = Field(default="", max_length=10)
    platforms: List[Platform] = Field(default_factory=list, max_length=6)
    pillars: List[str] = Field(default_factory=list, max_length=8)
    per_week: int = Field(default=3, ge=1, le=5)
    focus: str = Field(default="", max_length=1000)


class OpportunityPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    platform: Optional[Platform] = None
    pillar: Optional[str] = Field(default=None, min_length=1, max_length=120)
    week: Optional[int] = Field(default=None, ge=1, le=4)
    weekday: Optional[int] = Field(default=None, ge=0, le=6)
    format: Optional[MatrixFormat] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    hook: Optional[str] = Field(default=None, max_length=400)
    angle: Optional[str] = Field(default=None, max_length=600)
    caption_draft: Optional[str] = Field(default=None, max_length=4000)
    rationale: Optional[str] = Field(default=None, max_length=1200)
    status: Optional[Literal["sugerida", "selecionada", "descartada"]] = None


class OpportunityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    platform: Platform
    pillar: str = Field(min_length=1, max_length=120)
    week: int = Field(ge=1, le=4)
    weekday: int = Field(ge=0, le=6)
    format: MatrixFormat
    title: str = Field(min_length=1, max_length=200)
    hook: Optional[str] = Field(default=None, max_length=400)
    angle: Optional[str] = Field(default=None, max_length=600)
    caption_draft: Optional[str] = Field(default=None, max_length=4000)
    rationale: Optional[str] = Field(default=None, max_length=1200)


class BulkStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: List[UUID] = Field(min_length=1, max_length=80)
    status: Literal["sugerida", "selecionada", "descartada"]


class ExportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: Optional[List[UUID]] = Field(default=None, max_length=80)


@router.get("/matrix")
async def read_matrices(client_id: str, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    from services.studio_calendar import CHANNEL_LABELS
    return {"matrices": await matrix.list_matrices(cid), "platforms": CHANNEL_LABELS,
            "platform_formats": {k: list(v) for k, v in matrix.PLATFORM_FORMATS.items()}}


@router.post("/matrix", status_code=201)
async def create_matrix(client_id: str, body: Optional[MatrixInput] = None, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    uid = await require_user_id(authorization)
    try:
        return {"matrix": await matrix.generate(cid, body.model_dump() if body else {}, user_id=uid)}
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/matrix/{matrix_id}")
async def read_matrix(client_id: str, matrix_id: UUID, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    try:
        return {"matrix": await matrix.get_matrix(cid, str(matrix_id))}
    except StudioError as exc:
        raise _http(exc) from None


@router.delete("/matrix/{matrix_id}")
async def archive_matrix(client_id: str, matrix_id: UUID, authorization: Optional[str] = Header(default=None)):
    """Arquiva (some da lista); as pautas que já foram para o Calendário ficam lá."""
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    try:
        return {"matrix": await matrix.archive(cid, str(matrix_id))}
    except StudioError as exc:
        raise _http(exc) from None


@router.patch("/matrix/{matrix_id}/opportunities/{opportunity_id}")
async def update_opportunity(client_id: str, matrix_id: UUID, opportunity_id: UUID, body: OpportunityPatch,
                             authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    try:
        return {"opportunity": await matrix.update_opportunity(cid, str(opportunity_id), body.model_dump(exclude_none=True))}
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/matrix/{matrix_id}/opportunities", status_code=201)
async def add_opportunity(client_id: str, matrix_id: UUID, body: OpportunityCreate,
                          authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    try:
        return {"opportunity": await matrix.create_opportunity(cid, str(matrix_id), body.model_dump())}
    except StudioError as exc:
        raise _http(exc) from None


@router.delete("/matrix/{matrix_id}/opportunities/{opportunity_id}")
async def remove_opportunity(client_id: str, matrix_id: UUID, opportunity_id: UUID,
                             authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    try:
        return {"opportunity": await matrix.delete_opportunity(cid, str(matrix_id), str(opportunity_id))}
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/matrix/{matrix_id}/opportunities/{opportunity_id}/refine")
async def refine_opportunity(client_id: str, matrix_id: UUID, opportunity_id: UUID, body: RegenerateInput,
                             authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    try:
        return {"opportunity": await matrix.refine_opportunity(cid, str(opportunity_id), instruction=body.instruction)}
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/matrix/{matrix_id}/status")
async def bulk_status(client_id: str, matrix_id: UUID, body: BulkStatusInput, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    try:
        return await matrix.set_many_status(cid, str(matrix_id), [str(i) for i in body.ids], body.status)
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/matrix/{matrix_id}/calendar")
async def matrix_to_calendar(client_id: str, matrix_id: UUID, body: Optional[ExportInput] = None,
                             authorization: Optional[str] = Header(default=None)):
    """Selecionadas viram rascunho no Calendário (origem "matriz"). Repetir não duplica."""
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    uid = await require_user_id(authorization)
    ids = [str(i) for i in (body.ids or [])] if body else []
    try:
        result = await matrix.export_to_calendar(cid, str(matrix_id), user_id=uid, ids=ids or None)
    except StudioError as exc:
        raise _http(exc) from None
    if result["created_ids"]:
        from routes.studio import _chat_author
        from services.studio_history import record
        author = _chat_author(authorization, uid)
        for item_id in result["created_ids"]:
            await record(cid, item_id, "criou a pauta pela Matriz de conteúdo", actor_name=author, actor_id=uid)
    return result


# ---------------------------------------------------------------- redação (editor de texto)

DocKind = Literal["livre", "post", "legenda", "roteiro", "artigo", "email", "release", "campanha"]


class DocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="Sem título", max_length=200)
    kind: DocKind = "livre"
    content_html: str = Field(default="", max_length=300_000)


class DocumentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = Field(default=None, max_length=200)
    kind: Optional[DocKind] = None
    content_html: Optional[str] = Field(default=None, max_length=300_000)
    status: Optional[Literal["rascunho", "arquivado"]] = None


class DocumentAIInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["escrever", "continuar", "reescrever", "encurtar", "expandir", "corrigir", "titulos"]
    kind: DocKind = "livre"
    title: str = Field(default="", max_length=200)
    instruction: str = Field(default="", max_length=1500)
    selection: str = Field(default="", max_length=12000)
    document_text: str = Field(default="", max_length=100_000)


class DocumentCalendarInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheduled_at: Optional[str] = Field(default=None, max_length=40)
    channel: Platform = "instagram"
    format: MatrixFormat = "imagem"


@router.get("/documents")
async def read_documents(client_id: str, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    return {"documents": await documents.list_documents(cid), "kinds": documents.KINDS}


@router.post("/documents", status_code=201)
async def create_document(client_id: str, body: DocumentCreate, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    uid = await require_user_id(authorization)
    try:
        return {"document": await documents.create_document(cid, body.model_dump(), user_id=uid)}
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/documents/ai")
async def document_ai(client_id: str, body: DocumentAIInput, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    try:
        return await documents.ai_write(cid, body.model_dump())
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/documents/{document_id}")
async def read_document(client_id: str, document_id: UUID, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    try:
        return {"document": await documents.get_document(cid, str(document_id))}
    except StudioError as exc:
        raise _http(exc) from None


@router.patch("/documents/{document_id}")
async def update_document(client_id: str, document_id: UUID, body: DocumentPatch, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    uid = await require_user_id(authorization)
    try:
        return {"document": await documents.update_document(cid, str(document_id), body.model_dump(exclude_none=True), user_id=uid)}
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/documents/{document_id}/calendar")
async def document_to_calendar(client_id: str, document_id: UUID, body: DocumentCalendarInput,
                               authorization: Optional[str] = Header(default=None)):
    """O texto vira post em rascunho no Calendário. Repetir atualiza a mesma pauta (não duplica)."""
    cid = await require_client_role(client_id, authorization, allowed_roles=SOCIAL_MEDIA)
    uid = await require_user_id(authorization)
    try:
        result = await documents.to_calendar(cid, str(document_id), body.model_dump(), user_id=uid)
    except StudioError as exc:
        raise _http(exc) from None
    if result.get("created"):
        from routes.studio import _chat_author
        from services.studio_history import record
        await record(cid, result["calendar_item_id"], "criou a pauta pela Redação", actor_name=_chat_author(authorization, uid), actor_id=uid)
    return result
