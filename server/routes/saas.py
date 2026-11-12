"""Planos e cobrança. Empresa vê o próprio plano, uso, faturas e implantação; a equipe Mugô administra tudo."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, Header, HTTPException, Query

from services import saas, tenant_commercial_config as commercial_config
from services.platform_admin import is_platform_admin
from services.tenant import require_user_id
from services.ig_supabase import sb_get_client_membership_roles
from services.tenant import require_agency_admin, require_client_read

router = APIRouter(tags=["saas"])


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, saas.QuotaError):
        return HTTPException(status_code=exc.status, detail=exc.message)
    import httpx
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None and exc.response.status_code in (400, 404):
        return HTTPException(status_code=409, detail="Falta aplicar a migração 000112 (planos) no Supabase.")
    print(f"[saas_routes] unexpected {type(exc).__name__}")
    return HTTPException(status_code=502, detail="Não foi possível concluir agora.")


@router.get("/api/plan")
async def my_plan(client_id: str | None = Query(default=None), x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                  authorization: str | None = Header(default=None)):
    """Plano e implantação da empresa ativa: só equipe Mugô (admin)."""
    await require_agency_admin(authorization)
    cid = await require_client_read(client_id or x_client_id, authorization)
    try:
        return {"ok": True, **(await saas.overview(cid))}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.get("/api/admin/plans/overview")
async def plans_admin(authorization: str | None = Header(default=None)):
    await require_agency_admin(authorization)
    try:
        return {"ok": True, **(await saas.admin_overview())}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.put("/api/admin/plans/{plan_id}")
async def plans_save(plan_id: str, payload: Dict[str, Any] = Body(...), authorization: str | None = Header(default=None)):
    await require_agency_admin(authorization)
    try:
        return {"ok": True, "plan": await saas.save_plan(plan_id, payload)}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.put("/api/admin/subscriptions/{client_id}")
async def subscription_save(client_id: str, payload: Dict[str, Any] = Body(...), authorization: str | None = Header(default=None)):
    user_id = await require_agency_admin(authorization)
    try:
        return {"ok": True, "subscription": await saas.set_subscription(client_id, payload, user_id=user_id)}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.delete("/api/admin/subscriptions/{client_id}")
async def subscription_remove(client_id: str, authorization: str | None = Header(default=None)):
    """Tira a empresa dos planos (volta a ficar sem limite). Faturas antigas ficam."""
    await require_agency_admin(authorization)
    try:
        await saas.remove_subscription(client_id)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.post("/api/admin/invoices/{client_id}/{invoice_id}/paid")
async def invoice_paid(client_id: str, invoice_id: str, authorization: str | None = Header(default=None)):
    await require_agency_admin(authorization)
    try:
        return {"ok": True, "invoice": await saas.mark_paid(client_id, invoice_id)}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


# Etapa 2B.1: somente administração declarativa (sem enforcement).
async def _commercial_admin(authorization: str | None) -> str:
    from fastapi import HTTPException
    uid = await require_user_id(authorization)
    if await is_platform_admin(uid):
        return uid
    memberships = await sb_get_client_membership_roles(uid)
    if any(row.get("role") == "agency_admin" for row in memberships):
        return uid
    raise HTTPException(status_code=403, detail="Apenas administradores Mugô podem configurar módulos.")


@router.get("/api/admin/commercial-modules/catalog")
async def commercial_catalog(authorization: str | None = Header(default=None)):
    await _commercial_admin(authorization)
    return {"ok": True, "modules": commercial_config.catalog(),
            "basic_capabilities": ["briefing", "tasks"], "enforcement_enabled": False}


@router.get("/api/admin/commercial-modules/{client_id}")
async def commercial_get(client_id: str, authorization: str | None = Header(default=None)):
    await _commercial_admin(authorization)
    try:
        return {"ok": True, "configuration": await commercial_config.get_configuration(client_id)}
    except Exception as exc:
        print(f"[commercial_config] read unavailable type={type(exc).__name__}")
        raise HTTPException(status_code=503, detail="Configuração comercial indisponível.") from exc


@router.put("/api/admin/commercial-modules/{client_id}")
async def commercial_save(client_id: str, payload: Dict[str, Any] = Body(...),
                          authorization: str | None = Header(default=None)):
    uid = await _commercial_admin(authorization)
    if set(payload) != {"module_keys", "expected_version"}:
        raise HTTPException(status_code=400, detail="Informe module_keys e expected_version.")
    try:
        result = await commercial_config.save_configuration(
            client_id, payload["module_keys"], expected_version=payload["expected_version"],
            actor_user_id=uid,
        )
        return {"ok": True, "configuration": result}
    except commercial_config.CommercialConfigError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.code) from exc
    except Exception as exc:
        print(f"[commercial_config] write failed type={type(exc).__name__}")
        raise HTTPException(status_code=503, detail="Não foi possível salvar a configuração.") from exc
