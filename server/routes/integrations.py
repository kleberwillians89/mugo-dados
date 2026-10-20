from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Request, Query
from pydantic import BaseModel, ConfigDict, model_validator

from services.integration_errors import IntegrationError
from services.provider_refresh import RefreshProvider, refresh_provider_data

from services.connections_service import get_client_connections
from services.tenant import require_client_role, require_client_read
from services.runtime_cache import get_cached_or_load

router = APIRouter(prefix="/api/clients", tags=["integrations"])


@router.get("/{client_id}/integrations")
async def get_client_integrations(
    client_id: str,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    """
    Contrato canônico consolidado de conexões (Fase 3). client_id do path é
    apenas contexto — require_client_read confere contra memberships/
    platform_admin/agency_admin e nunca confia cegamente no X-Client-Id.
    """
    cid = await require_client_role(
        client_id or x_client_id,
        authorization,
        allowed_roles=("agency_admin", "client_admin"),
    )
    result, _ = await get_cached_or_load(
        namespace="client_integrations",
        key=cid,
        ttl_seconds=15,
        loader=lambda: get_client_connections(cid),
    )
    return {"ok": True, **result}


class DataRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: date
    end: date

    @model_validator(mode="after")
    def bounded_period(self):
        if self.end < self.start or (self.end - self.start).days > 365:
            raise ValueError("Período inválido: use até 366 dias.")
        return self


@router.post("/{client_id}/data-refresh/{provider}")
async def refresh_client_provider(
    client_id: str,
    provider: RefreshProvider,
    body: DataRefreshRequest,
    request: Request,
    authorization: str | None = Header(default=None),
):
    cid = await require_client_role(client_id, authorization)
    if request.query_params:
        raise HTTPException(400, "Parâmetros extras não são permitidos.")
    try:
        return await refresh_provider_data(cid, provider, body.start.isoformat(), body.end.isoformat())
    except IntegrationError as exc:
        if provider in {"fbits", "meta"}:
            print(f"[{provider}][manual_refresh_error] client_id={cid} code={exc.code} status={exc.status_code}")
        if exc.status_code == 429:
            seconds = max(60, int(exc.diagnostics.get("retry_after") or 60))
            raise HTTPException(429, exc.public_message, headers={"Retry-After": str(seconds)}) from None
        raise


@router.get("/{client_id}/data-health")
async def get_data_health(client_id: str, start: date = Query(...), end: date = Query(...),
                          authorization: str | None = Header(default=None)):
    from services.data_health import client_data_health
    cid = await require_client_read(client_id, authorization)
    if end < start or (end - start).days > 365:
        raise HTTPException(400, "Período inválido: use até 366 dias.")
    return await client_data_health(cid, start.isoformat(), end.isoformat())


@router.get("/{client_id}/data-refresh/{provider}/status")
async def get_refresh_status(client_id: str, provider: Literal["meta", "google", "shopify", "fbits"],
                             start: date = Query(...), end: date = Query(...),
                             authorization: str | None = Header(default=None)):
    from services.provider_refresh_status import refresh_status
    cid = await require_client_role(client_id, authorization)
    if end < start or (end - start).days > 365:
        raise HTTPException(400, "Período inválido: use até 366 dias.")
    return await refresh_status(cid, provider, start.isoformat(), end.isoformat())
