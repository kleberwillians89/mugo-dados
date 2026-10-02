from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

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
from services.meta_backfill import enqueue_backfill, get_backfill
from services.periods import resolve_period
from services.instagram_sync import discover_instagram_identity_for_connection, sync_instagram_connection
from services.integration_errors import IntegrationError
from services.job_runs import finish_job_run, list_job_runs, start_job_run
from services.meta_oauth import (
    build_frontend_callback_redirect,
    build_oauth_url,
    create_discovery_handoff,
    disconnect_connection,
    discover_assets,
    discover_existing_meta_organic_assets,
    activate_meta_organic_assets,
    exchange_code_for_token,
    get_meta_oauth_settings,
    list_connections,
    read_discovery_handoff,
    resolve_meta_redirect_uri,
    save_pending_meta_authorization,
    save_manual_meta_assets,
    finalize_meta_organic_activation,
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
from services.platform_admin import require_platform_admin

router = APIRouter(tags=["meta-legacy"])


def _meta_oauth_log(
    request: Request,
    *,
    stage: str,
    client_id: str = "",
    user_id: str = "",
    connection_id: str = "",
    page_count: int | None = None,
    instagram_count: int | None = None,
    ad_account_count: int | None = None,
    error_code: str = "",
    state_present: bool | None = None,
    provider_error_code: str = "",
    provider_error_subcode: str = "",
    provider_error_reason: str = "",
) -> None:
    request_id = str(getattr(getattr(request, "state", None), "request_id", "") or "-")
    counts = ""
    if page_count is not None:
        counts += f" page_count={max(0, page_count)}"
    if instagram_count is not None:
        counts += f" instagram_count={max(0, instagram_count)}"
    if ad_account_count is not None:
        counts += f" ad_account_count={max(0, ad_account_count)}"
    callback = ""
    if state_present is not None:
        callback += f" state_present={1 if state_present else 0}"
    if provider_error_code:
        callback += f" provider_error_code={str(provider_error_code).strip()[:80]}"
    if provider_error_subcode:
        callback += f" provider_error_subcode={str(provider_error_subcode).strip()[:80]}"
    if provider_error_reason:
        callback += f" provider_error_reason={str(provider_error_reason).strip()[:80]}"
    print(
        "[meta_oauth][flow] "
        f"request_id={request_id} client_id={client_id or '-'} user_id={user_id or '-'} "
        f"connection_id={connection_id or '-'} stage={stage} error_code={error_code or '-'}{counts}{callback}"
    )


def _meta_oauth_config_log(request: Request, *, client_id: str, settings: Dict[str, str]) -> None:
    """Diagnostico seguro do inicio OAuth; nunca registra state ou secrets."""
    request_id = str(getattr(getattr(request, "state", None), "request_id", "") or "-")
    app_id = str(settings.get("app_id") or "").strip()[:80]
    login_config_id = str(settings.get("login_config_id") or "").strip()[:80]
    redirect_uri = str(settings.get("redirect_uri") or "").strip().replace("\n", "")[:300]
    print(
        "[meta_oauth][config] "
        f"request_id={request_id} client_id={client_id or '-'} app_id={app_id or '-'} "
        f"login_config_id={login_config_id or '-'} redirect_uri={redirect_uri or '-'} "
        "response_type=code state_present=1"
    )

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
    actor_user_id = await require_platform_admin(authorization, allow_agency_admin=False)
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
    request: Request,
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    try:
        user_id = await require_user_id(authorization)
        cid = await require_client_role(
            _pick_client_id(client_id, x_client_id),
            authorization,
            allowed_roles=("agency_admin", "client_admin"),
        )
        settings = get_meta_oauth_settings(
            require_redirect_uri=True, require_login_config_id=True, debug=False,
        )
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
        _meta_oauth_log(
            request, stage="authorization_url_created", client_id=cid, user_id=user_id,
        )
        _meta_oauth_config_log(request, client_id=cid, settings=settings)
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
    callback_user_id = ""
    callback_connection_id = ""

    if error:
        query_params = getattr(request, "query_params", {})
        # Cancelamento/recusa (ex.: /dialog/oauth/business/cancel/) também
        # devolve o state: recuperar empresa e usuário só quando o state é
        # válido (assinatura, registro e acesso) permite diagnosticar qual
        # tenant tentou conectar e manter o retorno na mesma empresa.
        # O valor do state nunca é registrado.
        if str(state or "").strip():
            try:
                denied_state = await consume_oauth_state(str(state), provider="meta")
                denied_client_id = str(denied_state.get("client_id") or "").strip()
                denied_user_id = str(denied_state.get("user_id") or "").strip()
                if denied_client_id and denied_user_id:
                    await require_user_client_access(denied_user_id, denied_client_id)
                    fallback_client_id = denied_client_id
                    callback_user_id = denied_user_id
            except Exception as exc:  # noqa: BLE001 - diagnóstico não altera o retorno de erro
                _meta_oauth_log(request, stage="provider_denied_state_unresolved", error_code=exc.__class__.__name__)
        _meta_oauth_log(
            request,
            stage="provider_denied",
            client_id=fallback_client_id,
            user_id=callback_user_id,
            error_code=str(error)[:80],
            state_present=bool(str(state or "").strip()),
            provider_error_code=str(query_params.get("error_code") or "")[:80],
            provider_error_subcode=str(query_params.get("error_subcode") or "")[:80],
            provider_error_reason=str(query_params.get("error_reason") or "")[:80],
        )
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
        callback_user_id = user_id_from_state
        if not client_id_from_state or not user_id_from_state:
            raise RuntimeError("State OAuth inválido")
        await require_user_client_access(user_id_from_state, client_id_from_state)
        _meta_oauth_log(
            request, stage="state_validated", client_id=client_id_from_state,
            user_id=user_id_from_state,
        )

        configured_redirect_uri = resolve_meta_redirect_uri(_request_origin(request))
        persisted_redirect_uri = str(state_payload.get("redirect_uri") or "").strip()
        if persisted_redirect_uri and persisted_redirect_uri != configured_redirect_uri:
            raise RuntimeError("Redirect URI da sessão OAuth não corresponde à configuração atual.")
        redirect_uri = persisted_redirect_uri or configured_redirect_uri
        token_data = await exchange_code_for_token(code=code, redirect_uri=redirect_uri)
        _meta_oauth_log(
            request, stage="code_exchanged", client_id=client_id_from_state,
            user_id=user_id_from_state,
        )
        discovered = await discover_assets(str(token_data.get("access_token") or ""))
        _meta_oauth_log(
            request, stage="assets_discovered", client_id=client_id_from_state,
            user_id=user_id_from_state,
            page_count=len(discovered.get("pages") or []),
            instagram_count=len(discovered.get("instagram_accounts") or []),
            ad_account_count=len(discovered.get("ad_accounts") or []),
        )
        handoff = await create_discovery_handoff(
            user_id=user_id_from_state,
            client_id=client_id_from_state,
            access_token=str(token_data.get("access_token") or ""),
            expires_at=token_data.get("expires_at"),
            discovered=discovered,
        )
        saved_authorization = await save_pending_meta_authorization(
            user_id=user_id_from_state,
            client_id=client_id_from_state,
            access_token=str(token_data.get("access_token") or ""),
            expires_at=token_data.get("expires_at"),
            discovered=discovered,
            handoff=handoff,
        )
        callback_connection_id = str(saved_authorization.get("id") or "").strip()
        _meta_oauth_log(
            request, stage="authorization_saved", client_id=client_id_from_state,
            user_id=user_id_from_state, connection_id=callback_connection_id,
        )

        target = build_frontend_callback_redirect(
            success=True,
            client_id=client_id_from_state,
            handoff=handoff,
            error=None,
            connection_id=callback_connection_id,
        )
        return RedirectResponse(url=target, status_code=302)
    except Exception as exc:
        _meta_oauth_log(
            request, stage="callback_failed", client_id=fallback_client_id,
            user_id=callback_user_id, connection_id=callback_connection_id,
            error_code=exc.__class__.__name__,
        )
        target = build_frontend_callback_redirect(
            success=False,
            client_id=fallback_client_id,
            handoff=None,
            error=str(exc),
        )
        return RedirectResponse(url=target, status_code=302)


@router.get("/api/oauth/meta/discover-assets")
async def api_oauth_meta_discover_assets(
    request: Request,
    handoff: str,
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    user_id = await require_user_id(authorization)
    cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
    try:
        data = await read_discovery_handoff(handoff=handoff, user_id=user_id, client_id=cid)
        request_id = str(getattr(getattr(request, "state", None), "request_id", "") or "-")
        return {"ok": True, **data, "request_id": request_id}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/oauth/meta/pending-assets")
async def api_oauth_meta_pending_assets(
    handoff: str,
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    user_id = await require_user_id(authorization)
    cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
    try:
        data = await read_discovery_handoff(
            handoff=handoff, user_id=user_id, client_id=cid,
        )
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
    request: Request = None,
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
    elif str(payload.get("page_id") or "").strip() or str(payload.get("instagram_id") or "").strip():
        request_id = str(getattr(getattr(request, "state", None), "request_id", "") or "-") if request else "-"
        result.update({
            "ok": False,
            "initial_sync": {
                "ok": False, "code": "META_ORGANIC_ASSETS_REQUIRED",
                "message": "Selecione uma Página e o Instagram profissional vinculado.",
                "retryable": False,
            },
            "code": "META_ORGANIC_ASSETS_REQUIRED",
            "request_id": request_id,
        })
    return result


@router.post("/api/oauth/meta/{authorization_connection_id}/organic/activate")
async def api_activate_meta_organic(
    authorization_connection_id: str,
    payload: Dict[str, Any],
    request: Request,
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    user_id = await require_user_id(authorization)
    cid = await require_client_role(
        _pick_client_id(client_id, x_client_id),
        authorization,
    )
    request_id = str(
        getattr(getattr(request, "state", None), "request_id", "") or "-"
    )

    prepared: Dict[str, Any] = {}
    organic_connection_id = ""
    stage = "assets_prepare"

    try:
        print(
            "[meta-organic-real] "
            f"stage={stage} request_id={request_id} client_id={cid} "
            f"authorization_connection_id={authorization_connection_id}"
        )
        prepared = await activate_meta_organic_assets(
            user_id=user_id,
            client_id=cid,
            connection_id=authorization_connection_id,
            page_id=str(payload.get("page_id") or ""),
            instagram_id=str(payload.get("instagram_id") or ""),
        )
        if not isinstance(prepared, dict):
            raise RuntimeError(
                "A preparação da conexão orgânica retornou um resultado inválido."
            )

        organic_connection_id = str(
            prepared.get("organic_connection_id") or ""
        ).strip()
        if not organic_connection_id:
            raise RuntimeError(
                "A conexão orgânica operacional não foi retornada."
            )

        stage = "sync_start"
        print(
            "[meta-organic-real] "
            f"stage={stage} request_id={request_id} client_id={cid} "
            f"organic_connection_id={organic_connection_id}"
        )
        sync_result = await sync_instagram_connection(organic_connection_id)
        if not isinstance(sync_result, dict):
            raise RuntimeError(
                "A sincronização do Instagram retornou "
                f"{type(sync_result).__name__} em vez de dict."
            )

        metrics_written = (
            int(sync_result.get("media_saved") or 0)
            + int(sync_result.get("comments_saved") or 0)
            + (1 if sync_result.get("snapshot_saved") else 0)
        )
        last_sync_at = datetime.now(timezone.utc).isoformat()
        stage = "authorization_finalize"

        await finalize_meta_organic_activation(
            client_id=cid,
            connection_id=authorization_connection_id,
            organic_connection_id=organic_connection_id,
            succeeded=True,
            code="OK",
            request_id=request_id,
            last_sync_at=last_sync_at,
        )
        print(
            "[meta-organic-real] "
            f"stage=complete request_id={request_id} client_id={cid} "
            f"organic_connection_id={organic_connection_id} "
            f"metrics_written={metrics_written}"
        )
        return {
            "ok": True,
            **prepared,
            "status": "active",
            "initial_sync": {
                **sync_result,
                "ok": True,
                "metrics_written": metrics_written,
            },
            "metrics_written": metrics_written,
            "last_sync_at": last_sync_at,
            "code": "OK",
            "request_id": request_id,
        }

    except Exception as exc:
        import traceback

        # Preserve explicit integration codes. Generic failures during the real
        # Instagram sync keep the established META_GRAPH_UNAVAILABLE contract.
        if getattr(exc, "code", None):
            code = str(exc.code)
        elif stage in {"sync_start", "authorization_finalize"}:
            code = "META_GRAPH_UNAVAILABLE"
        else:
            code = "META_ORGANIC_ACTIVATION_FAILED"

        message = str(
            getattr(exc, "public_message", "")
            or str(exc)
            or "A ativação orgânica não foi concluída."
        )
        print(
            "[meta-organic-real] "
            f"stage=error failed_stage={stage} request_id={request_id} "
            f"client_id={cid} "
            f"organic_connection_id={organic_connection_id or '-'} "
            f"error_type={type(exc).__name__} error={message[:400]}"
        )
        traceback.print_exc()

        if organic_connection_id:
            try:
                await finalize_meta_organic_activation(
                    client_id=cid,
                    connection_id=authorization_connection_id,
                    organic_connection_id=organic_connection_id,
                    succeeded=False,
                    code=code,
                    request_id=request_id,
                )
            except Exception as finalize_exc:
                print(
                    "[meta-organic-real] "
                    f"stage=error_finalize_failed request_id={request_id} "
                    f"error_type={type(finalize_exc).__name__} "
                    f"error={str(finalize_exc)[:400]}"
                )
                traceback.print_exc()

        return {
            "ok": False,
            **prepared,
            "organic_connection_id": organic_connection_id or None,
            "status": "error",
            "initial_sync": {
                "ok": False,
                "code": code,
                "message": message[:500],
                "retryable": True,
            },
            "metrics_written": 0,
            "last_sync_at": None,
            "code": code,
            "failed_stage": stage,
            "request_id": request_id,
        }


@router.post("/api/clients/{client_id}/connections/link-assets")
async def api_link_assets(
    client_id: str,
    payload: Dict[str, Any],
    authorization: str | None = Header(default=None),
):
    user_id = await require_user_id(authorization)
    cid = await require_client_role(client_id, authorization)
    try:
        result = await save_connections(
            user_id=user_id,
            client_id=cid,
            handoff=str(payload.get("handoff") or ""),
            page_ids=[str(v or "").strip() for v in (payload.get("page_ids") or [])],
            instagram_ig_user_ids=[str(v or "").strip() for v in (payload.get("instagram_ig_user_ids") or [])],
            ad_account_ids=[str(v or "").strip() for v in (payload.get("ad_account_ids") or [])],
        )
        paid_connection = next(
            (
                row for row in (result.get("connections") or [])
                if row.get("platform") == "meta_ads" and str(row.get("id") or "").strip()
            ),
            None,
        )
        if not paid_connection:
            return result

        period = resolve_period(days=30, max_days=365)
        connection_id = str(paid_connection.get("id") or "").strip()
        try:
            sync_result = await sync_ads_for_client_period(
                client_id=cid,
                connection_id=connection_id,
                since=period.start.isoformat(),
                until=period.end.isoformat(),
                job_name="meta_ads_initial_sync",
                trigger_source="oauth_asset_selection",
                record_job_run=True,
            )
            result["meta_ads_initial_sync"] = {
                **sync_result,
                "ok": bool(sync_result.get("ok")),
                "client_id": cid,
                "connection_id": connection_id,
            }
        except Exception as exc:
            result["meta_ads_initial_sync"] = {
                "ok": False,
                "client_id": cid,
                "connection_id": connection_id,
                "code": str(getattr(exc, "code", "META_ADS_INITIAL_SYNC_FAILED")),
                "retryable": bool(getattr(exc, "retryable", True)),
            }
        return result
    except IntegrationError:
        raise
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
    request: Request,
    payload: Dict[str, Any] | None = None,
    authorization: str | None = Header(default=None),
):
    cid = await require_client_role(client_id, authorization)
    body = payload or {}
    requested_days = max(1, min(int(body.get("days") or 30), 365))
    default_period = resolve_period(days=requested_days, max_days=365)
    return await sync_ads_for_client_period(
        client_id=cid,
        connection_id=str(body.get("connection_id") or "") or None,
        since=str(body.get("since") or default_period.start.isoformat()),
        until=str(body.get("until") or default_period.end.isoformat()),
        job_name="meta_ads_manual_account_sync",
        trigger_source="manual",
        record_job_run=True,
        request_id=str(getattr(request.state, "request_id", "") or "-"),
    )


@router.post("/api/ads/backfill", status_code=202)
async def api_enqueue_meta_ads_backfill(
    payload: Dict[str, Any],
    authorization: str | None = Header(default=None),
):
    actor = await require_platform_admin(authorization)
    client_id = str(payload.get("client_id") or "").strip()
    connection_id = str(payload.get("connection_id") or "").strip()
    since, until = str(payload.get("since") or "").strip(), str(payload.get("until") or "").strip()
    if not client_id or not connection_id or not since or not until:
        raise HTTPException(status_code=422, detail="client_id, connection_id, since e until são obrigatórios.")
    cid = await require_client_role(client_id, authorization, allowed_roles=("agency_admin",))
    resolved = await _validated_connection_id(client_id=cid, connection_id=connection_id, authorization=authorization)
    try:
        datetime.fromisoformat(since)
        datetime.fromisoformat(until)
        result = await enqueue_backfill(client_id=cid, connection_id=resolved or connection_id,
                                        since=since, until=until, created_by=actor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(status_code=202, content=result)


@router.get("/api/ads/backfill/{job_id}")
async def api_get_meta_ads_backfill(
    job_id: str,
    authorization: str | None = Header(default=None),
):
    await require_platform_admin(authorization)
    try:
        result = await get_backfill(job_id)
        await require_client_role(str(result.get("client_id") or ""), authorization, allowed_roles=("agency_admin",))
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
    # Mutação (renova e persiste o token Meta): exige papel de gestão do tenant,
    # não apenas leitura. resolve_client_id continua garantindo o isolamento
    # cross-tenant dentro de require_client_role.
    cid = await require_client_role(_pick_client_id(client_id, x_client_id), authorization)
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
