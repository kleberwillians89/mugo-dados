from __future__ import annotations

from fastapi import APIRouter, Header

from services.connections_service import get_client_connections
from services.tenant import require_client_role
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
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=("agency_admin",))
    result, _ = await get_cached_or_load(
        namespace="client_integrations",
        key=cid,
        ttl_seconds=15,
        loader=lambda: get_client_connections(cid),
    )
    return {"ok": True, **result}
