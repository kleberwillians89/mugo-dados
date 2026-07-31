from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException

from services.platform_admin import (
    create_platform_company,
    is_platform_admin,
    list_platform_companies,
    require_platform_admin,
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
    actor_user_id = await require_platform_admin(authorization)
    try:
        return await create_platform_company(actor_user_id, payload)
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
