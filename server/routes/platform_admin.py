from __future__ import annotations

from typing import Any, Dict
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException

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
from services.auth import get_user_id_from_bearer
from services.fbits_customer_backfill import CustomerBackfillError, backfill_customer_identities

router = APIRouter(prefix="/api/platform", tags=["platform-admin"])

BACKFILL_COUNT_FIELDS = (
    "orders_processed", "identities_found", "identities_persisted",
    "identities_without_contact", "errors",
)


def _backfill_counts(result: dict) -> dict:
    # Allowlist explícita: nunca repassar payloads ou campos extras do serviço.
    counts = {field: result[field] for field in BACKFILL_COUNT_FIELDS}
    if any(type(value) is not int or value < 0 for value in counts.values()):
        raise ValueError("Contagens operacionais inválidas.")
    return counts


@router.post("/fbits/customer-identities/backfill")
async def platform_backfill_fbits_customers(
    payload: Dict[str, Any],
    authorization: str | None = Header(default=None),
):
    if not authorization or not authorization.lower().startswith("bearer ") or not authorization[7:].strip():
        raise HTTPException(status_code=401, detail="Autenticação obrigatória.")
    # Operação administrativa não aceita os bypasses locais de require_user_id.
    if not await get_user_id_from_bearer(authorization):
        raise HTTPException(status_code=401, detail="Autenticação obrigatória.")
    await require_platform_admin(authorization, allow_agency_admin=False)
    if set(payload) != {"client_id", "confirm_client_id"}:
        raise HTTPException(status_code=400, detail="Informe somente client_id e confirm_client_id.")
    client_id = payload.get("client_id")
    try:
        if not isinstance(client_id, str) or str(UUID(client_id)) != client_id or payload.get("confirm_client_id") != client_id:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=400, detail="Informe e confirme um único client_id UUID válido.") from None
    try:
        rows = await sb_select("clients", select="id", filters={"id": f"eq.{client_id}"}, limit=1)
        if not rows or rows[0].get("id") != client_id:
            raise HTTPException(status_code=404, detail="Empresa não encontrada.")
        result = await backfill_customer_identities(client_id=client_id, confirm_client_id=client_id)
        counts = _backfill_counts(result)
        if counts["errors"]:
            raise HTTPException(status_code=502, detail={"code": "FBITS_CUSTOMER_BACKFILL_FAILED", "counts": counts})
        return counts
    except CustomerBackfillError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "counts": _backfill_counts(exc.counts)}) from None
    except HTTPException:
        raise
    except TimeoutError:
        raise HTTPException(status_code=504, detail={"code": "FBITS_CUSTOMER_BACKFILL_TIMEOUT"}) from None
    except Exception:
        raise HTTPException(status_code=502, detail={"code": "FBITS_CUSTOMER_BACKFILL_FAILED"}) from None


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
