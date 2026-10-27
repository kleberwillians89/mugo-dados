from __future__ import annotations

from typing import Any, Dict

import time

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query

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


# ---------------------------------------------------------------------------
# Histórico desde uma data (ex.: 01/01/2026): simular (leitura), agendar,
# cancelar e rodar uma rodada agora. Agendar/rodar grava no banco: só
# platform_admin. O cron noturno continua as rodadas sozinho.

_HISTORY_RUN_COOLDOWN_SECONDS = 120
_history_last_run: Dict[str, float] = {}


def _history_http_error(exc: Exception) -> HTTPException:
    from services.history_backfill import HistoryBackfillError

    if isinstance(exc, HistoryBackfillError):
        status = 409 if exc.code in {"HISTORY_ALREADY_REQUESTED", "HISTORY_NOTHING_TO_DO"} else (
            404 if exc.code == "HISTORY_NOT_FOUND" else 422)
        return HTTPException(status_code=status, detail=exc.public_message)
    return HTTPException(status_code=500, detail="Não foi possível concluir a operação de histórico.")


@router.get("/companies/{client_id}/history-backfill")
async def platform_history_plan(
    client_id: str,
    start: str | None = Query(default=None, max_length=10),
    authorization: str | None = Header(default=None),
):
    await require_platform_admin(authorization)
    from services.history_backfill import history_plan

    try:
        return await history_plan(client_id, start)
    except Exception as exc:  # noqa: BLE001
        raise _history_http_error(exc) from None


@router.post("/history-backfill/all")
async def platform_history_request_all(
    payload: Dict[str, Any],
    authorization: str | None = Header(default=None),
):
    user_id = await require_platform_admin(authorization, allow_agency_admin=False)
    from services.history_backfill import request_history_all

    try:
        return await request_history_all(str((payload or {}).get("start") or ""), requested_by=user_id)
    except Exception as exc:  # noqa: BLE001
        raise _history_http_error(exc) from None


@router.post("/companies/{client_id}/history-backfill")
async def platform_history_request(
    client_id: str,
    payload: Dict[str, Any],
    authorization: str | None = Header(default=None),
):
    user_id = await require_platform_admin(authorization, allow_agency_admin=False)
    from services.history_backfill import request_history

    try:
        return await request_history(client_id, str((payload or {}).get("start") or ""), requested_by=user_id)
    except Exception as exc:  # noqa: BLE001
        raise _history_http_error(exc) from None


@router.delete("/companies/{client_id}/history-backfill")
async def platform_history_cancel(client_id: str, authorization: str | None = Header(default=None)):
    await require_platform_admin(authorization, allow_agency_admin=False)
    from services.history_backfill import cancel_history

    try:
        return await cancel_history(client_id)
    except Exception as exc:  # noqa: BLE001
        raise _history_http_error(exc) from None


async def _history_round(client_id: str) -> None:
    from services.history_backfill import run_history_step

    try:
        await run_history_step(client_id, budget_seconds=240)
    except Exception as exc:  # noqa: BLE001 — rodada em segundo plano: só o código
        print(f"[history_backfill] client_id={client_id} background_round=error code={getattr(exc, 'code', 'ERROR')}")


@router.post("/companies/{client_id}/history-backfill/run", status_code=202)
async def platform_history_run(
    client_id: str,
    background: BackgroundTasks,
    authorization: str | None = Header(default=None),
):
    await require_platform_admin(authorization, allow_agency_admin=False)
    from services.history_backfill import active_request

    if not await active_request(client_id):
        raise HTTPException(status_code=404, detail="Agende a busca de histórico antes de rodar.")
    now = time.monotonic()
    last = _history_last_run.get(client_id)
    if last is not None and now - last < _HISTORY_RUN_COOLDOWN_SECONDS:
        wait = int(_HISTORY_RUN_COOLDOWN_SECONDS - (now - last)) + 1
        raise HTTPException(status_code=429, detail=f"Uma rodada acabou de começar. Aguarde {wait}s.")
    _history_last_run[client_id] = now
    background.add_task(_history_round, client_id)
    return {"ok": True, "started": True, "message": "Rodada iniciada em segundo plano (até 4 minutos)."}


# ---------------------------------------------------------------------------
# Pedidos de teste: simular (leitura) e remover do banco (só platform_admin).

@router.get("/companies/{client_id}/origins/reprocess")
async def platform_origins_reprocess_preview(client_id: str, authorization: str | None = Header(default=None)):
    """Prévia: quantos pedidos sem origem passariam a ter origem (nada é gravado)."""
    await require_platform_admin(authorization)
    from services.sales_by_origin import reprocess_unknown_origins

    return await reprocess_unknown_origins(client_id, dry_run=True)


@router.post("/companies/{client_id}/origins/reprocess")
async def platform_origins_reprocess_apply(client_id: str, authorization: str | None = Header(default=None)):
    await require_platform_admin(authorization, allow_agency_admin=False)
    from services.sales_by_origin import reprocess_unknown_origins

    return await reprocess_unknown_origins(client_id, dry_run=False)


@router.get("/companies/{client_id}/test-orders")
async def platform_test_orders_preview(client_id: str, authorization: str | None = Header(default=None)):
    await require_platform_admin(authorization)
    from services.test_orders import cleanup_test_orders

    return await cleanup_test_orders(client_id, dry_run=True)


@router.post("/companies/{client_id}/test-orders/cleanup")
async def platform_test_orders_cleanup(client_id: str, authorization: str | None = Header(default=None)):
    await require_platform_admin(authorization, allow_agency_admin=False)
    from services.test_orders import cleanup_test_orders

    return await cleanup_test_orders(client_id, dry_run=False)
