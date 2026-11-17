"""Google Ads draft CRUD only — no external publication or spend."""
from __future__ import annotations
from typing import Any, Dict, Optional
from uuid import UUID
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from services import google_ad_drafts as drafts
from services import google_ad_publisher as publisher
from services.integration_errors import IntegrationError
from services.studio_calendar import StudioError
from services.tenant import require_client_role, require_user_id

router = APIRouter(prefix="/api/clients/{client_id}/studio/google-ads", tags=["google-ads-drafts"])
WRITERS = ("agency_admin", "client_admin")

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: Dict[str, Any] = Field(default_factory=dict)

def _http(error: StudioError) -> HTTPException:
    if error.code == "AD_DRAFT_NOT_FOUND":
        return HTTPException(status_code=404, detail="Rascunho não encontrado nesta empresa.")
    if error.code in {"AD_NOT_READY", "AD_OBJECTIVE_INVALID"}:
        return HTTPException(status_code=422, detail=str(error))
    if error.code == "AD_DRAFT_LOCKED":
        return HTTPException(status_code=409, detail="Campanhas em publicação ou já criadas não podem ser alteradas.")
    if error.code == "AD_PUBLICATION_IN_PROGRESS":
        return HTTPException(status_code=409, detail="A publicação desta campanha já está em andamento.")
    if error.code == "AD_PUBLICATION_UNCERTAIN":
        return HTTPException(status_code=409, detail=str(error))
    if error.code in {"GOOGLE_ADS_API_VERSION_INVALID", "GOOGLE_ADS_RESPONSE_INCOMPLETE"}:
        return HTTPException(status_code=502, detail="A publicação Google Ads não pôde ser confirmada com segurança.")
    if error.code == "GOOGLE_ADS_REJECTED":
        return HTTPException(status_code=422, detail=str(error))
    return HTTPException(status_code=502, detail="Não foi possível salvar o rascunho Google Ads.")


def _integration_http(error: IntegrationError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.public_message)

@router.get("")
async def list_campaigns(client_id: str, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    return {"drafts": await drafts.list_drafts(cid), "publication_available": True}


@router.get("/publication-context")
async def read_publication_context(client_id: str, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        return await publisher.publication_context(cid)
    except IntegrationError as error:
        raise _integration_http(error) from None

@router.post("", status_code=201)
async def create_campaign(client_id: str, body: Input, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    try:
        return {"draft": await drafts.create(cid, uid, body.payload)}
    except StudioError as error:
        raise _http(error) from None

@router.put("/{draft_id}")
async def edit_campaign(client_id: str, draft_id: UUID, body: Input, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        return {"draft": await drafts.update(cid, str(draft_id), body.payload)}
    except StudioError as error:
        raise _http(error) from None

@router.delete("/{draft_id}")
async def remove_campaign(client_id: str, draft_id: UUID, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        await drafts.delete(cid, str(draft_id))
    except StudioError as error:
        raise _http(error) from None
    return {"ok": True}


@router.post("/{draft_id}/publish")
async def publish_campaign(client_id: str, draft_id: UUID, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        return {"draft": await publisher.publish(cid, str(draft_id))}
    except StudioError as error:
        raise _http(error) from None
    except IntegrationError as error:
        raise _integration_http(error) from None
