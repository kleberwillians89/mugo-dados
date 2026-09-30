from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query

from api_support import (
    _log_endpoint_call,
    _log_endpoint_done,
    _log_endpoint_error,
    _runtime_error_status,
    _started,
    _structured_error_response,
)
from services.fbits_connections import (
    connect_fbits,
    disconnect_fbits,
    load_fbits_connection,
    sync_fbits_connection,
)
from services.fbits_reporting import (
    build_fbits_orders_report,
    build_fbits_summary,
    resolve_fbits_period,
)
from services.integration_errors import IntegrationError
from services.tenant import require_client_role, require_user_id, resolve_client_id

router = APIRouter(tags=["fbits"])


async def _fbits_context(
    *,
    client_id: str | None,
    x_client_id: str | None,
    authorization: str | None,
) -> str:
    requested = (client_id or "").strip() or (x_client_id or "").strip() or None
    return await resolve_client_id(requested, authorization)


async def _run_fbits_endpoint(
    *,
    endpoint: str,
    client_id: str | None,
    x_client_id: str | None,
    authorization: str | None,
    start: str | None,
    end: str | None,
    days: int,
    operation: str,
):
    started = _started()
    user_for_log = await _log_endpoint_call(
        endpoint=endpoint,
        authorization=authorization,
        x_client_id=x_client_id,
        client_id=client_id,
        days=days,
        start=start,
        end=end,
    )
    try:
        cid = await _fbits_context(
            client_id=client_id,
            x_client_id=x_client_id,
            authorization=authorization,
        )
        period = resolve_fbits_period(start=start, end=end, days=days)
        if operation == "summary":
            payload = await build_fbits_summary(client_id=cid, period=period)
        else:
            payload = await build_fbits_orders_report(client_id=cid, period=period)
        _log_endpoint_done(
            endpoint=endpoint,
            started=started,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=cid,
            days=days,
            start=period.start,
            end=period.end,
        )
        return payload
    except HTTPException as exc:
        _log_endpoint_error(endpoint=endpoint, exc=exc, user_id=user_for_log, x_client_id=x_client_id, client_id=client_id)
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=exc.status_code,
            code="fbits_http_error",
        )
    except RuntimeError as exc:
        _log_endpoint_error(endpoint=endpoint, exc=exc, user_id=user_for_log, x_client_id=x_client_id, client_id=client_id)
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=_runtime_error_status(exc),
            code="fbits_runtime_error",
        )
    except Exception as exc:
        _log_endpoint_error(endpoint=endpoint, exc=exc, user_id=user_for_log, x_client_id=x_client_id, client_id=client_id)
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=500,
            code="fbits_unexpected_error",
        )


@router.get("/api/fbits/dashboard")
async def fbits_dashboard(
    client_id: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=366),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    return await _run_fbits_endpoint(
        endpoint="/api/fbits/dashboard",
        client_id=client_id,
        x_client_id=x_client_id,
        authorization=authorization,
        start=start,
        end=end,
        days=days,
        operation="summary",
    )


# Compatibilidade com a rota criada durante a primeira leitura FBits.
@router.get("/api/fbits/orders/summary")
async def fbits_orders_summary(
    client_id: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=366),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    return await _run_fbits_endpoint(
        endpoint="/api/fbits/orders/summary",
        client_id=client_id,
        x_client_id=x_client_id,
        authorization=authorization,
        start=start,
        end=end,
        days=days,
        operation="summary",
    )


@router.get("/api/fbits/orders")
async def fbits_orders(
    client_id: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=366),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    return await _run_fbits_endpoint(
        endpoint="/api/fbits/orders",
        client_id=client_id,
        x_client_id=x_client_id,
        authorization=authorization,
        start=start,
        end=end,
        days=days,
        operation="orders",
    )


async def _run_fbits_sync_isolated(client_id: str) -> None:
    """Sincronização em background: falhas nunca desfazem a conexão salva e
    ficam registradas (sanitizadas) em last_error pela própria sincronização."""
    try:
        await sync_fbits_connection(client_id=client_id)
    except IntegrationError as exc:
        print(f"[fbits][sync] client_id={client_id} stage=background status=error code={exc.code}")
    except Exception as exc:
        print(f"[fbits][sync] client_id={client_id} stage=background status=error error_type={exc.__class__.__name__}")


async def _schedule_tenant_sync(client_id: str, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    connection = await load_fbits_connection(client_id)
    if not connection or str(connection.get("status") or "").lower() == "disconnected":
        raise IntegrationError(
            "Nenhuma conexão FBITS ativa para esta empresa.",
            status_code=404, code="FBITS_CONNECTION_NOT_FOUND", provider="fbits",
        )
    background_tasks.add_task(_run_fbits_sync_isolated, client_id)
    return {"ok": True, "client_id": client_id, "scheduled": True}


@router.post("/api/clients/{client_id}/fbits/connect")
async def fbits_connect(
    client_id: str,
    payload: Dict[str, Any],
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
):
    # Só perfis de gestão; viewer é recusado por require_client_role.
    cid = await require_client_role(client_id, authorization)
    user_id = await require_user_id(authorization)
    result = await connect_fbits(client_id=cid, user_id=user_id, token=str(payload.get("token") or ""))
    background_tasks.add_task(_run_fbits_sync_isolated, cid)
    # O token nunca volta na resposta: `connection` já é sanitizada.
    return {"ok": True, **result, "initial_sync": "scheduled"}


@router.post("/api/clients/{client_id}/fbits/sync", status_code=202)
async def fbits_tenant_sync(
    client_id: str,
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
):
    cid = await require_client_role(client_id, authorization)
    return await _schedule_tenant_sync(cid, background_tasks)


@router.delete("/api/clients/{client_id}/fbits/connection")
async def fbits_disconnect(
    client_id: str,
    authorization: str | None = Header(default=None),
):
    cid = await require_client_role(client_id, authorization)
    user_id = await require_user_id(authorization)
    return {"ok": True, "connection": await disconnect_fbits(client_id=cid, user_id=user_id)}


# Compatibilidade: a rota antiga agora exige perfil de gestão e apenas agenda a
# sincronização da conexão da PRÓPRIA empresa. Não existe mais token global.
@router.post("/api/fbits/sync", status_code=202)
async def fbits_sync(
    background_tasks: BackgroundTasks,
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_role(client_id or x_client_id, authorization)
    return await _schedule_tenant_sync(cid, background_tasks)


_LEGACY_DEBUG_DISABLED = (
    "Endpoint de debug FBITS desativado: ele consultava a API com um token global. "
    "Use a conexão FBITS da empresa em Integrações."
)


@router.get("/api/fbits/debug/orders")
async def fbits_debug_orders():
    raise HTTPException(status_code=410, detail=_LEGACY_DEBUG_DISABLED)


@router.get("/api/fbits/debug/reconciliation")
async def fbits_debug_reconciliation():
    raise HTTPException(status_code=410, detail=_LEGACY_DEBUG_DISABLED)
