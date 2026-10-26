from __future__ import annotations

from typing import Any, Dict

import time

from fastapi import APIRouter, Header, HTTPException, Query

from services.platform_admin import (
    PlatformCompanyConfirmationError,
    PlatformCompanyNotFoundError,
    create_company_activation_link,
    create_platform_company,
    delete_platform_company,
    is_platform_admin,
    list_platform_companies,
    require_platform_admin,
    update_platform_company,
)
from services.ig_supabase import sb_rpc, sb_select
from services.tenant import require_user_id

router = APIRouter(prefix="/api/platform", tags=["platform-admin"])

@router.get("/me")
async def platform_me(authorization: str | None = Header(default=None)):
    user_id = await require_user_id(authorization)
    return {"ok": True, "is_platform_admin": await is_platform_admin(user_id)}


@router.get("/companies")
async def platform_companies(authorization: str | None = Header(default=None)):
    await require_platform_admin(authorization)
    return await list_platform_companies()


@router.post("/companies", status_code=201)
async def platform_create_company(
    payload: Dict[str, Any],
    authorization: str | None = Header(default=None),
):
    # Criar empresa é exclusivo de platform_admin (mesma autoridade da RPC).
    actor_user_id = await require_platform_admin(authorization, allow_agency_admin=False)
    try:
        return await create_platform_company(actor_user_id, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/companies/{client_id}")
async def platform_update_company(
    client_id: str,
    payload: Dict[str, Any],
    authorization: str | None = Header(default=None),
):
    actor_user_id = await require_platform_admin(authorization)
    try:
        return await update_platform_company(actor_user_id, client_id, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/companies/{client_id}")
async def platform_delete_company(
    client_id: str,
    payload: Dict[str, Any],
    authorization: str | None = Header(default=None),
    active_client_id: str | None = Header(default=None, alias="X-Client-Id"),
):
    actor_user_id = await require_platform_admin(
        authorization, allow_agency_admin=False
    )
    if str(active_client_id or "").strip() == str(client_id or "").strip():
        raise HTTPException(
            status_code=409,
            detail="Troque para outra empresa antes de excluir a empresa atualmente aberta.",
        )
    try:
        return await delete_platform_company(
            actor_user_id,
            client_id,
            str(payload.get("confirmation_name") or ""),
        )
    except PlatformCompanyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PlatformCompanyConfirmationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/companies/{client_id}/activation-link")
async def platform_company_activation_link(
    client_id: str,
    authorization: str | None = Header(default=None),
):
    actor_user_id = await require_platform_admin(authorization)
    try:
        return await create_company_activation_link(actor_user_id, client_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/companies/{client_id}/access")
async def platform_open_company(
    client_id: str,
    authorization: str | None = Header(default=None),
):
    actor_user_id = await require_platform_admin(authorization)
    rows = await sb_select(
        "clients",
        select="id,name,trade_name,status,created_at",
        filters={"id": f"eq.{client_id}"},
        limit=1,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Empresa não encontrada.")
    await sb_rpc(
        "audit_platform_company_access",
        {"p_actor_user_id": actor_user_id, "p_client_id": client_id},
    )
    return {"ok": True, "company": rows[0]}


# Diagnóstico de origem FBITS: somente leitura, sem dados pessoais. Um
# intervalo mínimo por empresa evita estourar a cota da API da Wake.
_FBITS_PROBE_COOLDOWN_SECONDS = 60
_fbits_probe_last_run: Dict[str, float] = {}


@router.get("/companies/{client_id}/fbits-origin-probe")
async def platform_fbits_origin_probe(
    client_id: str,
    days: int = Query(default=14, ge=1, le=30),
    limit: int = Query(default=40, ge=1, le=100),
    detail: int = Query(default=10, ge=0, le=20),
    order_id: str | None = Query(default=None, max_length=40),
    authorization: str | None = Header(default=None),
):
    await require_platform_admin(authorization)
    from services.fbits_origin_probe import probe_fbits_order_origin
    from services.integration_errors import IntegrationError

    order = (order_id or "").strip() or None
    if order is not None and not order.isdigit():
        raise HTTPException(status_code=422, detail="Informe apenas o número do pedido.")
    now = time.monotonic()
    last = _fbits_probe_last_run.get(client_id)
    if last is not None and now - last < _FBITS_PROBE_COOLDOWN_SECONDS:
        wait = int(_FBITS_PROBE_COOLDOWN_SECONDS - (now - last)) + 1
        raise HTTPException(status_code=429, detail=f"Aguarde {wait}s para rodar o diagnóstico de novo.")
    _fbits_probe_last_run[client_id] = now
    try:
        result = await probe_fbits_order_origin(
            client_id, order_id=order, days=days, limit=limit, detail_sample=detail,
        )
    except IntegrationError as exc:
        # Conexão ausente/sem token vira resposta legível, não 401 (que
        # derrubaria a sessão do administrador no front).
        return {"ok": False, "code": exc.code, "message": exc.public_message}
    return result
