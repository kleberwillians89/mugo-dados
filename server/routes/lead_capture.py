"""Administração de fontes e captura server-to-server de formulários externos."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException, Query

from services import lead_capture
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


@router.get("/api/relationship/captured-leads")
async def captured_leads(client_id: str | None = Query(default=None),
                         x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                         authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id or x_client_id, authorization)
    return {"ok": True, "events": await lead_capture.list_events(cid)}


@router.post("/api/hooks/leads/{source_id}")
async def receive_lead(source_id: str, payload: dict[str, Any] = Body(...),
                       x_lead_capture_key: str | None = Header(default=None, alias="X-Lead-Capture-Key")):
    try:
        return await lead_capture.ingest(source_id, x_lead_capture_key or "", payload)
    except lead_capture.LeadCaptureError as exc:
        raise _error(exc) from exc
