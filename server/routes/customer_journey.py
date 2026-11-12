"""Jornada do cliente (identidade unificada + linha do tempo). Leitura para quem lê clientes; montar é de admin."""
from __future__ import annotations

import time

from fastapi import APIRouter, Header, HTTPException, Query

from routes.customers import _log
from services.tenant import require_client_read, require_client_role

router = APIRouter(prefix="/api/customers", tags=["customers"])


def _journey_unavailable(exc: Exception) -> bool:
    """Tabelas da migração 000107 ainda não aplicadas: a tela diz isso em vez de quebrar."""
    import httpx
    return isinstance(exc, httpx.HTTPStatusError) and exc.response is not None and exc.response.status_code in (400, 404)


@router.get("/journey/status")
async def journey_status(
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    from services.customer_journey import journey_status as status
    cid = await require_client_read(client_id or x_client_id, authorization)
    try:
        return {"ok": True, **(await status(cid))}
    except Exception as exc:  # noqa: BLE001
        if _journey_unavailable(exc):
            return {"ok": True, "built_at": None, "stats": None, "migration_pending": True}
        raise HTTPException(status_code=502, detail="A jornada não pôde ser lida agora.") from exc


@router.post("/journey/rebuild")
async def journey_rebuild(
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    """Monta a jornada da empresa agora (pedidos + WhatsApp). Equipe Mugô ou admin do cliente."""
    from services.customer_journey import rebuild
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=("agency_admin", "client_admin"))
    started = time.perf_counter()
    try:
        result = await rebuild(cid)
    except Exception as exc:  # noqa: BLE001
        _log(endpoint="/api/customers/journey/rebuild", client_id=cid, provider=None, status="error", started=started,
             error_type=exc.__class__.__name__)
        if _journey_unavailable(exc):
            raise HTTPException(status_code=409, detail="Falta aplicar a migração 000107 (jornada) no Supabase.") from exc
        raise HTTPException(status_code=502, detail="A jornada não pôde ser montada agora. Tente de novo.") from exc
    _log(endpoint="/api/customers/journey/rebuild", client_id=cid, provider=result["stats"].get("provider"), status="ok",
         started=started, count=result["stats"].get("persons"))
    return {"ok": True, **result}


@router.get("/{customer_id}/journey")
async def customer_journey(
    customer_id: str,
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    """Linha do tempo do cliente: conversas e pedidos confirmados, do primeiro contato à recompra."""
    from services.customer_journey import journey_for_customer
    cid = await require_client_read(client_id or x_client_id, authorization)
    try:
        return {"ok": True, **(await journey_for_customer(cid, customer_id))}
    except Exception as exc:  # noqa: BLE001
        if _journey_unavailable(exc):
            return {"ok": True, "status": "not_built", "events": [], "summary": None, "built_at": None, "migration_pending": True}
        raise HTTPException(status_code=502, detail="A jornada não pôde ser lida agora.") from exc


@router.get("/value/overview")
async def customer_value(
    margin: float | None = Query(default=None, ge=1, le=100),
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    """CAC, LTV e coortes da empresa (lido da jornada + gasto Meta/Google por mês)."""
    from services.customer_value import overview
    cid = await require_client_read(client_id or x_client_id, authorization)
    try:
        return {"ok": True, **(await overview(cid, margin=margin))}
    except Exception as exc:  # noqa: BLE001
        if _journey_unavailable(exc):
            return {"ok": True, "status": "not_built", "migration_pending": True}
        raise HTTPException(status_code=502, detail="Os indicadores de valor do cliente não puderam ser lidos agora.") from exc
