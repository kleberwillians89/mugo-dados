from __future__ import annotations

from fastapi import APIRouter, Header, Query

from services.generic_connections import list_generic_connections
from services.integration_catalog import public_integration_catalog
from services.tenant import require_client_read

router = APIRouter(prefix="/api/connections", tags=["connections"])


@router.get("")
async def list_connections(
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_read(client_id or x_client_id, authorization)
    return {
        "ok": True,
        "client_id": cid,
        "connections": await list_generic_connections(cid),
        "providers": public_integration_catalog(),
    }
