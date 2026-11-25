"""Administração de fontes e captura server-to-server de formulários externos."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from services import lead_capture, relationship_contacts
from services.tenant import require_client_read, require_client_role

router = APIRouter(tags=["lead-capture"])
WRITERS = ("agency_admin", "client_admin")


def _error(exc: lead_capture.LeadCaptureError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


@router.get("/api/relationship/lead-sources")
async def sources(client_id: str | None = Query(default=None),
                  x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                  authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id or x_client_id, authorization)
    return {"ok": True, "sources": await lead_capture.list_sources(cid)}


@router.post("/api/relationship/lead-sources", status_code=201)
async def create_source(payload: dict[str, Any] = Body(...),
                        client_id: str | None = Query(default=None),
                        x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                        authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    try:
        return {"ok": True, "source": await lead_capture.create_source(
            cid, payload.get("name"), payload.get("kind")
        )}
    except lead_capture.LeadCaptureError as exc:
        raise _error(exc) from exc


@router.post("/api/relationship/lead-sources/{source_id}/disable")
async def disable_source(source_id: str, client_id: str | None = Query(default=None),
                         x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                         authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    try:
        await lead_capture.disable_source(cid, source_id)
        return {"ok": True}
    except lead_capture.LeadCaptureError as exc:
        raise _error(exc) from exc


@router.get("/api/relationship/capture-campaigns")
async def capture_campaigns(client_id: str | None = Query(default=None),
                            x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                            authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id or x_client_id, authorization)
    try:
        return {"ok": True, "campaigns": await lead_capture.list_capture_campaigns(cid)}
    except lead_capture.LeadCaptureError as exc:
        raise _error(exc) from exc


@router.get("/api/relationship/campaigns/{campaign}/summary")
async def campaign_summary(campaign: str, client_id: str | None = Query(default=None),
                           x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                           authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id or x_client_id, authorization)
    try:
        return {"ok": True, **await lead_capture.campaign_summary(cid, campaign)}
    except lead_capture.LeadCaptureError as exc:
        raise _error(exc) from exc


@router.get("/api/relationship/campaigns/{campaign}/recent")
async def campaign_recent(campaign: str, client_id: str | None = Query(default=None),
                          x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                          authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    try:
        return {"ok": True, "contacts": await lead_capture.campaign_recent_contacts(cid, campaign)}
    except lead_capture.LeadCaptureError as exc:
        raise _error(exc) from exc


@router.get("/api/relationship/captured-leads")
async def captured_leads(client_id: str | None = Query(default=None),
                         x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                         authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id or x_client_id, authorization)
    return {"ok": True, "events": await lead_capture.list_events(cid)}


@router.post("/api/hooks/leads/{source_id}")
async def receive_lead(source_id: str, request: Request, payload: dict[str, Any] = Body(...),
                       x_lead_capture_key: str | None = Header(default=None, alias="X-Lead-Capture-Key")):
    # Limita payload de fontes externas; nunca aceitar arquivo ou dados arbitrários.
    raw = await request.body()
    if len(raw) > 16_384:
        raise HTTPException(status_code=413, detail="Evento excede o limite de 16 KB.")
    try:
        return await lead_capture.ingest(source_id, x_lead_capture_key or "", payload)
    except lead_capture.LeadCaptureError as exc:
        raise _error(exc) from exc

# -------------------------------------------------------- base histórica de clientes

@router.get("/api/relationship/contacts/status")
async def relationship_contacts_status(client_id: str | None = Query(default=None),
                                       x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                                       authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id or x_client_id, authorization)
    return {"ok": True, **await relationship_contacts.contacts_status(cid)}


@router.post("/api/relationship/contacts/sync")
async def relationship_contacts_sync(client_id: str | None = Query(default=None),
                                     x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                                     authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    try:
        return {"ok": True, **await relationship_contacts.sync_existing_customers(cid)}
    except relationship_contacts.ContactSyncError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


class SheetImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=3, max_length=200)
    content_base64: str = Field(min_length=4, max_length=15_000_000)
    replace: bool = False
    consent_confirmed: bool


@router.post("/api/relationship/contacts/import-sheet")
async def relationship_contacts_import_sheet(payload: SheetImportInput, client_id: str | None = Query(default=None),
                                             x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                                             authorization: str | None = Header(default=None)):
    """Leads de Excel/CSV para o Disparo em massa (origem "planilha"). Quem importa confirma o aceite dos contatos."""
    import base64
    import binascii
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    if not payload.consent_confirmed:
        raise HTTPException(status_code=422, detail="Confirme que esses contatos aceitaram receber mensagens da marca.")
    try:
        raw = base64.b64decode(payload.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="Arquivo inválido.") from None
    try:
        return {"ok": True, **await relationship_contacts.import_sheet(cid, filename=payload.filename, raw=raw, replace=payload.replace)}
    except relationship_contacts.ContactSyncError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@router.get("/api/relationship/contacts/sheet")
async def relationship_contacts_sheet(q: str = Query(default="", max_length=80), limit: int = Query(default=500, ge=1, le=2000),
                                      client_id: str | None = Query(default=None),
                                      x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                                      authorization: str | None = Header(default=None)):
    """Contatos da planilha importada para escolher à mão quem recebe o disparo (telefone mascarado)."""
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    return {"ok": True, **await relationship_contacts.sheet_contacts_list(cid, q=q, limit=limit)}


@router.post("/api/relationship/contacts/sync-whatsapp")
async def relationship_whatsapp_contacts_sync(
    days: int = Query(default=365, ge=1, le=3650),
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    try:
        return {"ok": True, **await relationship_contacts.sync_whatsapp_conversations(cid, days=days)}
    except relationship_contacts.ContactSyncError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
