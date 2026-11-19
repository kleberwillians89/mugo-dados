"""Tenant-authenticated group invite management and public redirect."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import RedirectResponse

from services import group_invite_tracking as tracking
from services.tenant import require_client_read, require_client_role

router = APIRouter(tags=["group-invite-tracking"])
WRITERS = ("agency_admin", "client_admin")


def _error(exc: tracking.GroupLinkError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


@router.get("/api/relationship/group-links")
async def list_group_links(client_id: str | None = Query(default=None),
                           x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                           authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id or x_client_id, authorization)
    return {"ok": True, "links": await tracking.list_links(cid)}


@router.post("/api/relationship/group-links", status_code=201)
async def create_group_link(payload: dict[str, Any] = Body(...),
                            client_id: str | None = Query(default=None),
                            x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                            authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    try:
        return {"ok": True, "link": await tracking.create_link(cid, payload)}
    except tracking.GroupLinkError as exc:
        raise _error(exc) from exc


@router.post("/api/relationship/group-links/{link_id}/status")
async def set_group_link_status(link_id: UUID, payload: dict[str, Any] = Body(...),
                                client_id: str | None = Query(default=None),
                                x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                                authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    if type(payload.get("active")) is not bool:
        raise HTTPException(status_code=422, detail="Informe active como verdadeiro ou falso.")
    try:
        await tracking.change_status(cid, str(link_id), payload["active"])
        return {"ok": True}
    except tracking.GroupLinkError as exc:
        raise _error(exc) from exc


@router.get("/r/{slug}", include_in_schema=False)
async def public_group_redirect(slug: str):
    try:
        destination = await tracking.destination_for_click(slug)
    except tracking.GroupLinkError as exc:
        raise _error(exc) from exc
    response = RedirectResponse(destination, status_code=302)
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
