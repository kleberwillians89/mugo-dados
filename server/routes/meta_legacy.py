from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from api_support import (
    _log_endpoint_call,
    _log_endpoint_done,
    _log_endpoint_error,
    _pick_client_id,
    _require_cron_secret,
    _request_origin,
    _runtime_error_status,
    _started,
    _structured_error_response,
    _validated_connection_id,
)
from services.clients import list_clients_for_user
from services.connection_resolver import resolve_connection_for_scope
from services.cron_jobs import (
    run_daily_instagram_refresh,
    run_daily_instagram_sync,
    run_hourly_ads_sync,
    run_token_refresh_job,
)
from services.ig_refresh import refresh_all
from services.ads_sync import sync_ads_for_client_period
from services.instagram_sync import discover_instagram_identity_for_connection, sync_instagram_connection
from services.job_runs import finish_job_run, list_job_runs, start_job_run
from services.meta_oauth import (
    build_frontend_callback_redirect,
    build_oauth_url,
    create_discovery_handoff,
    disconnect_connection,
    discover_assets,
    discover_existing_meta_organic_assets,
    exchange_code_for_token,
    get_meta_oauth_settings,
    list_connections,
    read_discovery_handoff,
    read_latest_discovery_handoff,
    resolve_meta_redirect_uri,
    save_pending_meta_authorization,
    save_manual_meta_assets,
    save_connections,
    select_paid_connection,
    validate_manual_meta_assets,
)
from services.oauth_state import consume_oauth_state, create_oauth_state
from services.meta_tokens import get_meta_connection_status, refresh_meta_token_for_connection
from services.runtime_cache import invalidate_namespace
from services.tenant import (
    require_client_role,
    require_user_client_access,
    require_user_id,
    resolve_client_id,
)

router = APIRouter(tags=["meta-legacy"])

META_LEGACY_ENDPOINTS = [
    "GET /api/clients",
    "POST /api/clients",
    "POST /api/clients/{client_id}/connect_meta",
    "GET /api/oauth/meta/start",
    "GET /api/oauth/meta/callback",
    "GET /api/oauth/meta/discover-assets",
    "POST /api/clients/{client_id}/connections/link-assets",
    "GET /api/clients/{client_id}/connections",
    "GET /api/meta/connections/{connection_id}/status",
    "POST /api/meta/connections/{connection_id}/refresh-token",
    "DELETE /api/clients/{client_id}/connections/{connection_id}",
    "POST /api/ig/refresh_all",
    "POST /api/ig/sync",
    "GET /api/ig/debug/identity",
    "POST /api/cron/token_refresh",
    "POST /api/cron/organic_sync",
    "POST /api/cron/paid_sync",
    "POST /api/cron/paid_sync_hourly",
    "POST /api/cron/ig_refresh_all",
    "GET /api/jobs/runs",
]


@router.get("/api/clients")
async def api_clients(
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    user_id = await require_user_id(authorization)
    return await list_clients_for_user(user_id)


@router.post("/api/clients")
async def api_create_client(
    payload: Dict[str, Any],
    authorization: str | None = Header(default=None),
):
    from services.platform_admin import create_platform_company, require_platform_admin
    actor_user_id = await require_platform_admin(authorization)
    try:
        created = await create_platform_company(actor_user_id, payload)
        await invalidate_namespace("clients")
        return created
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/clients/{client_id}/connect_meta")
async def api_connect_meta(
    client_id: str,
    payload: Dict[str, Any],
    authorization: str | None = Header(default=None),
):
    del client_id, payload, authorization
    raise HTTPException(
        status_code=410,
        detail="Conexão manual por token foi desativada. Use o OAuth oficial da Meta.",
    )


@router.get("/api/oauth/meta/start")
async def api_oauth_meta_start(
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    try:
        user_id = await require_user_id(authorization)
        cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
        settings = get_meta_oauth_settings(require_redirect_uri=True, debug=False)
        redirect_uri = str(settings.get("redirect_uri") or "").strip()
        persisted_state = await create_oauth_state(
            provider="meta",
            user_id=user_id,
            client_id=cid,
            redirect_uri=redirect_uri,
        )
        payload = build_oauth_url(
            client_id=cid,
            user_id=user_id,
            redirect_uri=redirect_uri,
            app_id=str(settings.get("app_id") or "").strip(),
            state_override=persisted_state,
        )
        return {
            "ok": True,
            "client_id": cid,
            "authorization_url": payload.get("url"),
        }
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/oauth/meta/callback")
async def api_oauth_meta_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    fallback_client_id = ""

    if error:
        target = build_frontend_callback_redirect(
            success=False,
            client_id=fallback_client_id,
            handoff=None,
            error=(error_description or error),
        )
        return RedirectResponse(url=target, status_code=302)

    try:
        if not code:
            raise RuntimeError("Meta não retornou code")
        if not state:
            raise RuntimeError("Meta não retornou state")

        state_payload = await consume_oauth_state(state, provider="meta")
        client_id_from_state = str(state_payload.get("client_id") or "").strip()
        user_id_from_state = str(state_payload.get("user_id") or "").strip()
        fallback_client_id = client_id_from_state
        if not client_id_from_state or not user_id_from_state:
            raise RuntimeError("State OAuth inválido")
        await require_user_client_access(user_id_from_state, client_id_from_state)

        redirect_uri = resolve_meta_redirect_uri(_request_origin(request))
        token_data = await exchange_code_for_token(code=code, redirect_uri=redirect_uri)
        discovered = await discover_assets(str(token_data.get("access_token") or ""))
        handoff = await create_discovery_handoff(
            user_id=user_id_from_state,
            client_id=client_id_from_state,
            access_token=str(token_data.get("access_token") or ""),
            expires_at=token_data.get("expires_at"),
            discovered=discovered,
        )
        await save_pending_meta_authorization(
            user_id=user_id_from_state,
            client_id=client_id_from_state,
            access_token=str(token_data.get("access_token") or ""),
            expires_at=token_data.get("expires_at"),
            discovered=discovered,
            handoff=handoff,
        )

        target = build_frontend_callback_redirect(
            success=True,
            client_id=client_id_from_state,
            handoff=handoff,
            error=None,
        )
        return RedirectResponse(url=target, status_code=302)
    except Exception as exc:
        target = build_frontend_callback_redirect(
            success=False,
            client_id=fallback_client_id,
            handoff=None,
            error=str(exc),
        )
        return RedirectResponse(url=target, status_code=302)


@router.get("/api/oauth/meta/discover-assets")
async def api_oauth_meta_discover_assets(
    handoff: str,
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    user_id = await require_user_id(authorization)
    cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
    try:
        data = await read_discovery_handoff(handoff=handoff, user_id=user_id, client_id=cid)
        return {"ok": True, **data}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/oauth/meta/pending-assets")
async def api_oauth_meta_pending_assets(
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    user_id = await require_user_id(authorization)
    cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
    try:
        data = await read_latest_discovery_handoff(user_id=user_id, client_id=cid)
        return {"ok": True, **data}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/oauth/meta/{connection_id}/configure-organic")
async def api_configure_existing_meta_organic(
    connection_id: str,
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    user_id = await require_user_id(authorization)
    cid = await require_client_role(_pick_client_id(client_id, x_client_id), authorization)
    return {
        "ok": True,
        **(await discover_existing_meta_organic_assets(
            user_id=user_id, client_id=cid, connection_id=connection_id
        )),
    }


@router.post("/api/oauth/meta/{connection_id}/manual-assets/validate")
async def api_validate_manual_meta_assets(
    connection_id: str,
    payload: Dict[str, Any],
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_role(_pick_client_id(client_id, x_client_id), authorization)
    return await validate_manual_meta_assets(
        client_id=cid, connection_id=connection_id,
        page_id=str(payload.get("page_id") or ""),
        instagram_id=str(payload.get("instagram_id") or ""),
        ad_account_id=str(payload.get("ad_account_id") or ""),
    )


@router.post("/api/oauth/meta/{connection_id}/manual-assets")
async def api_save_manual_meta_assets(
    connection_id: str,
    payload: Dict[str, Any],
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    user_id = await require_user_id(authorization)
    cid = await require_client_role(_pick_client_id(client_id, x_client_id), authorization)
    result = await save_manual_meta_assets(
        user_id=user_id, client_id=cid, connection_id=connection_id,
        page_id=str(payload.get("page_id") or ""),
        instagram_id=str(payload.get("instagram_id") or ""),
        ad_account_id=str(payload.get("ad_account_id") or ""),
    )
    organic_connection_id = str(result.get("organic_connection_id") or "").strip()
    if organic_connection_id:
        try:
            result["initial_sync"] = await sync_instagram_connection(organic_connection_id)
        except Exception as exc:
            result["initial_sync"] = {
                "ok": False,
                "code": "META_GRAPH_UNAVAILABLE",
                "message": "Ativos salvos, mas a primeira sincronização orgânica não foi concluída.",
                "retryable": True,
            }
            result["initial_sync_error_type"] = exc.__class__.__name__
    return result


@router.post("/api/clients/{client_id}/connections/link-assets")
async def api_link_assets(
    client_id: str,
    payload: Dict[str, Any],
    authorization: str | None = Header(default=None),
):
    user_id = await require_user_id(authorization)
    cid = await require_client_role(client_id, authorization)
    try:
        return await save_connections(
            user_id=user_id,
            client_id=cid,
            handoff=str(payload.get("handoff") or ""),
            page_ids=[str(v or "").strip() for v in (payload.get("page_ids") or [])],
            instagram_ig_user_ids=[str(v or "").strip() for v in (payload.get("instagram_ig_user_ids") or [])],
            ad_account_ids=[str(v or "").strip() for v in (payload.get("ad_account_ids") or [])],
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/clients/{client_id}/meta-ads/accounts")
async def api_meta_ads_accounts(
    client_id: str,
    authorization: str | None = Header(default=None),
):
    cid = await require_client_role(client_id, authorization)
    rows = await list_connections(cid)
    accounts = [
        {
            "connection_id": row.get("id"),
            "ad_account_id": row.get("ad_account_id"),
            "ad_account_name": row.get("ad_account_name"),
            "status": row.get("status"),
            "scopes": row.get("scopes_json") or [],
        }
        for row in rows
        if row.get("platform") == "meta_ads" and row.get("connection_type") == "paid" and row.get("ad_account_id")
    ]
    return {"ok": True, "client_id": cid, "accounts": accounts}


@router.post("/api/clients/{client_id}/meta-ads/select")
async def api_select_meta_ads_account(
    client_id: str,
    payload: Dict[str, Any],
    authorization: str | None = Header(default=None),
):
    user_id = await require_user_id(authorization)
    cid = await require_client_role(client_id, authorization)
    try:
        selected = await select_paid_connection(
            client_id=cid,
            ad_account_id=str(payload.get("ad_account_id") or ""),
            user_id=user_id,
        )
        return {"ok": True, **selected}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/clients/{client_id}/meta-ads/sync")
async def api_sync_meta_ads_account(
    client_id: str,
    payload: Dict[str, Any] | None = None,
    authorization: str | None = Header(default=None),
):
    cid = await require_client_role(client_id, authorization)
    body = payload or {}
    return await sync_ads_for_client_period(
        client_id=cid,
        connection_id=str(body.get("connection_id") or "") or None,
        since=str(body.get("since") or "2026-07-02"),
        until=str(body.get("until") or "2026-07-31"),
        job_name="meta_ads_manual_account_sync",
        trigger_source="manual",
        record_job_run=True,
    )


@router.get("/api/clients/{client_id}/connections")
async def api_list_connections(
    client_id: str,
    authorization: str | None = Header(default=None),
):
    started = _started()
    endpoint = "/api/clients/{client_id}/connections"
    user_for_log = await _log_endpoint_call(
        endpoint=endpoint,
        authorization=authorization,
        x_client_id=None,
        client_id=client_id,
    )
    resolved_client_id = (client_id or "").strip() or None
    try:
        resolved_client_id = await resolve_client_id(client_id, authorization)
        rows = await list_connections(resolved_client_id)
        _log_endpoint_done(
            endpoint=endpoint,
            started=started,
            user_id=user_for_log,
            x_client_id=None,
            client_id=resolved_client_id,
        )
        return {"ok": True, "client_id": resolved_client_id, "connections": rows}
    except HTTPException as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=None,
            client_id=resolved_client_id,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=exc.status_code,
            code="meta_connections_http_error",
        )
    except RuntimeError as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=None,
            client_id=resolved_client_id,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=_runtime_error_status(exc),
            code="meta_connections_runtime_error",
        )
    except Exception as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=None,
            client_id=resolved_client_id,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=500,
            code="meta_connections_unexpected_error",
        )


@router.get("/api/meta/connections/{connection_id}/status")
async def api_meta_connection_status(
    connection_id: str,
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
    validated_connection_id = await _validated_connection_id(
        client_id=cid,
        connection_id=connection_id,
        authorization=authorization,
    )
    try:
        return await get_meta_connection_status(validated_connection_id or connection_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/meta/connections/{connection_id}/refresh-token")
async def api_meta_connection_refresh_token(
    connection_id: str,
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
    validated_connection_id = await _validated_connection_id(
        client_id=cid,
        connection_id=connection_id,
        authorization=authorization,
    )
    run = await start_job_run(
        job_name="meta_token_refresh_manual",
        client_id=cid,
        connection_id=validated_connection_id or connection_id,
        trigger_source="manual",
    )
    try:
        result = await refresh_meta_token_for_connection(validated_connection_id or connection_id)
        await finish_job_run(
            run["id"],
            status="success",
            client_id=cid,
            connection_id=validated_connection_id or connection_id,
            payload_json={"connection": result.get("connection")},
        )
        return {**result, "job_run_id": run["id"]}
    except RuntimeError as exc:
        await finish_job_run(
            run["id"],
            status="error",
            error=str(exc),
            client_id=cid,
            connection_id=validated_connection_id or connection_id,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/clients/{client_id}/connections/{connection_id}")
async def api_disconnect_connection(
    client_id: str,
    connection_id: str,
    authorization: str | None = Header(default=None),
):
    cid = await require_client_role(client_id, authorization)
    user_id = await require_user_id(authorization)
    validated_connection_id = await _validated_connection_id(
        client_id=cid,
        connection_id=connection_id,
        authorization=authorization,
    )
    try:
        return await disconnect_connection(cid, validated_connection_id or connection_id, user_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/ig/refresh_all")
async def api_refresh_all(
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    limit: int = Query(40, ge=1, le=200),
    connection_id: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
):
    cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
    validated_connection_id = await _validated_connection_id(
        client_id=cid,
        connection_id=connection_id,
        authorization=authorization,
    )
    try:
        payload = await refresh_all(
            client_id=cid,
            limit=limit,
            connection_id=validated_connection_id,
            start=start,
            end=end,
        )
        await invalidate_namespace("dashboard")
        await invalidate_namespace("media")
        await invalidate_namespace("media_monthly")
        await invalidate_namespace("comments")
        await invalidate_namespace("stories")
        return payload
    except RuntimeError as exc:
        print(
            "[api_refresh_all] runtime_error "
            f"client_id={cid} connection_id={(validated_connection_id or '').strip() or '-'} "
            f"start={start or '-'} end={end or '-'} error={str(exc)[:280]}"
        )
        return {
            "ok": False,
            "client_id": cid,
            "connection_id": (validated_connection_id or "").strip() or None,
            "profile": {"id": "", "username": "", "name": "", "followers_count": 0, "media_count": 0},
            "kpis": {
                "impressions": 0,
                "reach": 0,
                "total_interactions": 0,
                "website_clicks": 0,
                "profile_views": 0,
                "accounts_engaged": 0,
            },
            "media": [],
            "comments_saved": 0,
            "warnings": ["Métricas orgânicas ainda não disponíveis para esta conexão."],
        }
    except Exception as exc:
        return {
            "ok": False,
            "client_id": cid,
            "connection_id": (validated_connection_id or "").strip() or None,
            "profile": {"id": "", "username": "", "name": "", "followers_count": 0, "media_count": 0},
            "kpis": {
                "impressions": 0,
                "reach": 0,
                "total_interactions": 0,
                "website_clicks": 0,
                "profile_views": 0,
                "accounts_engaged": 0,
            },
            "media": [],
            "comments_saved": 0,
            "warnings": ["Métricas orgânicas ainda não disponíveis para esta conexão."],
        }


@router.post("/api/ig/sync")
async def api_instagram_sync(
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    limit: int = Query(40, ge=1, le=200),
    connection_id: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
):
    return await api_refresh_all(
        client_id=client_id,
        x_client_id=x_client_id,
        limit=limit,
        connection_id=connection_id,
        start=start,
        end=end,
        authorization=authorization,
    )


@router.get("/api/ig/debug/identity")
async def api_instagram_debug_identity(
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    connection_id: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
):
    cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
    validated_connection_id = await _validated_connection_id(
        client_id=cid,
        connection_id=connection_id,
        authorization=authorization,
    )
    if not validated_connection_id:
        resolved = await resolve_connection_for_scope(
            client_id=cid,
            platform="instagram",
            connection_type="organic",
        )
        validated_connection_id = str(resolved.get("connection_id") or "").strip() or None
        if not validated_connection_id:
            return {
                "ok": False,
                "client_id": cid,
                "message": "Instagram orgânico ainda não conectado.",
                "instagram_accounts": [],
            }
    try:
        return await discover_instagram_identity_for_connection(validated_connection_id)
    except Exception as exc:
        print(
            "[api_ig_debug_identity] error "
            f"client_id={cid} connection_id={validated_connection_id} error={str(exc)[:280]}"
        )
        return {
            "ok": False,
            "client_id": cid,
            "connection_id": validated_connection_id,
            "message": "Conta Instagram Business ainda não vinculada à página Meta.",
            "instagram_accounts": [],
        }


@router.post("/api/cron/token_refresh")
async def api_cron_token_refresh(
    x_cron_secret: str | None = Header(default=None, alias="X-CRON-SECRET"),
):
    _require_cron_secret(x_cron_secret)
    return await run_token_refresh_job()


@router.post("/api/cron/organic_sync")
async def api_cron_organic_sync(
    x_cron_secret: str | None = Header(default=None, alias="X-CRON-SECRET"),
    limit: int = Query(40, ge=1, le=200),
):
    _require_cron_secret(x_cron_secret)
    return await run_daily_instagram_sync(limit=limit)


@router.post("/api/cron/paid_sync")
async def api_cron_paid_sync(
    x_cron_secret: str | None = Header(default=None, alias="X-CRON-SECRET"),
    days: int = Query(7, ge=1, le=365),
):
    _require_cron_secret(x_cron_secret)
    return await run_hourly_ads_sync(window_days=days)


@router.post("/api/cron/paid_sync_hourly")
async def api_cron_paid_sync_hourly(
    x_cron_secret: str | None = Header(default=None, alias="X-CRON-SECRET"),
    days: int = Query(7, ge=1, le=365),
):
    _require_cron_secret(x_cron_secret)
    return await run_hourly_ads_sync(window_days=days)


@router.post("/api/cron/ig_refresh_all")
async def api_cron_refresh_all(
    x_cron_secret: str | None = Header(default=None, alias="X-CRON-SECRET"),
    limit: int = Query(40, ge=1, le=200),
):
    _require_cron_secret(x_cron_secret)
    return await run_daily_instagram_refresh(limit=limit)


@router.get("/api/jobs/runs")
async def api_job_runs(
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    connection_id: str | None = Query(default=None),
    job_name: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    authorization: str | None = Header(default=None),
):
    cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
    validated_connection_id = await _validated_connection_id(
        client_id=cid,
        connection_id=connection_id,
        authorization=authorization,
    )
    payload = await list_job_runs(
        client_id=cid,
        connection_id=validated_connection_id,
        job_name=job_name,
        status=status,
        limit=limit,
    )
    payload["client_id"] = cid
    return payload
