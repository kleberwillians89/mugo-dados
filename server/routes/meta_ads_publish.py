"""Mídia On → Meta Ads: rascunhos de campanha e publicação PAUSADA. Só a equipe Mugô (mexe com verba)."""
from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from services import meta_ad_publisher as pub
from services.studio_calendar import StudioError
from services.tenant import require_client_role, require_user_id

router = APIRouter(prefix="/api/clients/{client_id}/studio/ads", tags=["meta-ads-publish"])
AGENCY = ("agency_admin",)

ERRORS = {
    "AD_MIGRATION_PENDING": (503, "Falta aplicar a migração 000091 (campanhas do Mídia On) no banco."),
    "AD_DRAFT_NOT_FOUND": (404, "Campanha não encontrada."),
    "AD_OBJECTIVE_INVALID": (422, "Objetivo inválido."),
    "AD_SAVE_FAILED": (502, "Não foi possível salvar a campanha. Tente de novo."),
    "AD_ALREADY_PUBLISHED": (409, "Esta campanha já foi criada no Meta Ads."),
    "AD_ACCOUNT_MISSING": (409, "Escolha a conta de anúncios do Meta desta empresa em Integrações."),
    "AD_PERMISSION_MISSING": (409, "A conexão do Meta não tem permissão para criar anúncios. Reconecte o Meta em Integrações para liberar."),
    "AD_PAGE_MISSING": (409, "Não achei a página do Facebook ligada a esta empresa. Reconecte o Instagram/Facebook em Integrações."),
    "AD_PIXEL_MISSING": (409, "A conta de anúncios não tem pixel. Use o objetivo Tráfego ou configure o pixel no Meta."),
    "AD_IMAGE_UNREACHABLE": (422, "Não consegui baixar a imagem do anúncio. Use um post do Calendário com arte ou um link direto da imagem."),
    "AI_INVALID_OUTPUT": (502, "A IA não devolveu a campanha. Tente de novo."),
    "AI_RATE_LIMIT": (429, "Muitas gerações seguidas. Espere um pouco e tente de novo."),
}
PASS_MESSAGE = {"AD_META_REJECTED", "AD_NOT_READY"}


def _http(exc: StudioError) -> HTTPException:
    if exc.code in PASS_MESSAGE or (exc.code == "AD_PERMISSION_MISSING" and str(exc) != exc.code):
        prefix = "O Meta recusou: " if exc.code != "AD_NOT_READY" else ""
        return HTTPException(status_code=422, detail=f"{prefix}{exc}")
    status, detail = ERRORS.get(exc.code, (502, "Não foi possível concluir agora."))
    return HTTPException(status_code=status, detail=detail)


class GenerateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    objective: str = Field(default="trafego", max_length=20)
    days_left: int = Field(default=14, ge=1, le=62)
    campaign: Dict[str, Any] = Field(default_factory=dict)


class DraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: Dict[str, Any]


@router.get("")
async def read_drafts(client_id: str, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    try:
        return {"drafts": await pub.list_drafts(cid), "objectives": {k: v["label"] for k, v in pub.OBJECTIVES.items()}, "ctas": pub.CTAS}
    except StudioError as exc:
        raise _http(exc) from None


@router.post("", status_code=201)
async def create_draft(client_id: str, body: GenerateInput, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    uid = await require_user_id(authorization)
    try:
        return {"draft": await pub.generate_draft(cid, user_id=uid, month=body.month, campaign=body.campaign,
                                                  objective=body.objective, days_left=body.days_left)}
    except StudioError as exc:
        raise _http(exc) from None


@router.put("/{draft_id}")
async def update_draft(client_id: str, draft_id: UUID, body: DraftInput, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    try:
        return {"draft": await pub.save_draft(cid, str(draft_id), body.payload)}
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/{draft_id}/publish")
async def publish_draft(client_id: str, draft_id: UUID, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    try:
        return {"draft": await pub.publish(cid, str(draft_id))}
    except StudioError as exc:
        raise _http(exc) from None


@router.delete("/{draft_id}")
async def remove_draft(client_id: str, draft_id: UUID, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    try:
        await pub.delete_draft(cid, str(draft_id))
        return {"ok": True}
    except StudioError as exc:
        raise _http(exc) from None
