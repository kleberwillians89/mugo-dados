"""
Clipping da marca e Redação de campanha — só a equipe Mugô (agency_admin/platform_admin).
O cliente não vê nada daqui: a única ponte para ele são as pautas que viram rascunho no Calendário.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from services import studio_campaigns as campaigns
from services import studio_clipping as clipping
from services.studio_calendar import StudioError
from services.tenant import is_agency_user, require_client_read, require_client_role, require_user_id

router = APIRouter(prefix="/api/clients/{client_id}/studio", tags=["studio-content-ops"])
AGENCY_ONLY = ("agency_admin",)

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
    "AI_RATE_LIMIT": (429, "Muitas gerações em sequência. Aguarde um minuto."),
    "AI_PROVIDER_NOT_CONFIGURED": (503, "IA não configurada no servidor."),
    "AI_PROVIDER_TIMEOUT": (504, "A IA demorou demais. Tente de novo."),
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
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY_ONLY)
    return {"campaigns": await campaigns.list_campaigns(cid), "channels": campaigns.CHANNEL_LABELS, "limits": campaigns.LIMITS}


@router.post("/campaigns", status_code=201)
async def create_campaign(client_id: str, body: BriefingInput, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY_ONLY)
    uid = await require_user_id(authorization)
    try:
        return {"campaign": await campaigns.generate(cid, body.model_dump(), user_id=uid)}
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/campaigns/{campaign_id}")
async def read_campaign(client_id: str, campaign_id: UUID, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY_ONLY)
    try:
        return {"campaign": await campaigns.get_campaign(cid, str(campaign_id))}
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/campaigns/{campaign_id}/pieces/{channel}/regenerate")
async def regenerate_piece(client_id: str, campaign_id: UUID, channel: Channel, body: RegenerateInput,
                           authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY_ONLY)
    try:
        return {"campaign": await campaigns.regenerate_piece(cid, str(campaign_id), channel, instruction=body.instruction)}
    except StudioError as exc:
        raise _http(exc) from None


@router.put("/campaigns/{campaign_id}/pieces/{channel}")
async def edit_piece(client_id: str, campaign_id: UUID, channel: Channel, body: PieceInput, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY_ONLY)
    try:
        return {"campaign": await campaigns.edit_piece(cid, str(campaign_id), channel, body.content)}
    except StudioError as exc:
        raise _http(exc) from None


@router.patch("/campaigns/{campaign_id}")
async def update_campaign(client_id: str, campaign_id: UUID, body: CampaignStatusInput, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY_ONLY)
    try:
        return {"campaign": await campaigns.set_status(cid, str(campaign_id), body.status)}
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/campaigns/{campaign_id}/calendar")
async def campaign_to_calendar(client_id: str, campaign_id: UUID, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY_ONLY)
    uid = await require_user_id(authorization)
    try:
        return await campaigns.to_calendar(cid, str(campaign_id), user_id=uid)
    except StudioError as exc:
        raise _http(exc) from None
