import os
import logging
import sys
import time
import traceback
import uuid
from types import SimpleNamespace
from typing import Any, Dict, Optional

from services.env_loader import ensure_env_loaded

ensure_env_loaded()

# Defesa em profundidade: o painel do Render pode sobrescrever o comando do
# blueprint. Desabilitar o logger aqui impede query strings sensíveis mesmo
# quando o processo é iniciado com `uvicorn app:app`.
logging.getLogger("uvicorn.access").disabled = True
logging.getLogger("uvicorn.access").propagate = False

# Os logs operacionais usam print(). Em produção o stdout é um pipe, e o Python
# acumula a saída em blocos de ~8 KB: as linhas só apareciam no Render muito
# depois (ou nunca). Line buffering publica cada linha imediatamente,
# independentemente do comando de start ou de PYTHONUNBUFFERED.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from api_support import (
    _cache_key,
    _clean,
    _clip,
    _log_endpoint_call,
    _log_endpoint_done,
    _log_endpoint_error,
    _pick_client_id,
    _started,
    _structured_error_response,
    _set_request_id,
    _reset_request_id,
    _validated_connection_id,
)
from routes.google import router as google_router
from routes.google_oauth import router as google_oauth_router
from routes.fbits import router as fbits_router
from routes.meta_legacy import router as meta_legacy_router
from routes.invitations import router as invitations_router
from routes.client_access import router as client_access_router
from routes.intelligence import router as intelligence_router
from routes.connections import router as connections_router
from routes.integrations import router as integrations_router
from routes.platform_admin import router as platform_admin_router
from routes.admin_health import router as admin_health_router
from routes.shopify import router as shopify_router
from routes.shopify_oauth import router as shopify_oauth_router

from services.ai_summary import ai_summary
from services.ads_sync import sync_ads_for_client_period
from services.bootstrap import bootstrap_meta_from_env
from services.comments import get_comments
from services.dashboard_paid import get_paid_dashboard, get_summary_dashboard, list_ads, list_campaigns
from services.executive_dashboard import get_executive_summary
from services.ig_dashboard import get_dashboard
from services.ig_months import get_months
from services.ig_supabase import sb_query
from services.media import get_media, get_media_monthly
from services.notes import create_note, list_notes, update_note
from services.stories import get_stories
from services.runtime_cache import get_cached_or_load, invalidate_namespace
from services.tenant import require_client_role, require_user_id, resolve_client_id
from services.integration_errors import IntegrationError

app = FastAPI(title="Mugô Dados API")


def _version_payload() -> Dict[str, str]:
    commit_sha = (
        os.getenv("RENDER_GIT_COMMIT")
        or os.getenv("GIT_COMMIT_SHA")
        or os.getenv("SOURCE_VERSION")
        or "unknown"
    ).strip()
    return {
        "commit_sha": commit_sha,
        "build_time": (os.getenv("BUILD_TIME") or "unknown").strip(),
        "environment": (os.getenv("APP_ENV") or "development").strip(),
    }


@app.get("/api/version", tags=["system"])
async def api_version():
    return _version_payload()


@app.middleware("http")
async def safe_request_log(request: Request, call_next):
    started = time.perf_counter()
    request_id = str(request.headers.get("X-Request-ID") or uuid.uuid4().hex)[:64]
    request_id_token = _set_request_id(request_id)
    if not hasattr(request, "state"):
        request.state = SimpleNamespace()
    request.state.request_id = request_id

    def emit(status: int) -> None:
        duration_ms = int((time.perf_counter() - started) * 1000)
        path = request.url.path
        integration_product = str(getattr(request.state, "integration_product", "") or "").strip()
        if not integration_product:
            integration_product = next(
                (name for name in ("meta", "shopify") if path.startswith(f"/api/oauth/{name}/")),
                "ga4" if "/ga4/" in path else "google_ads" if "/ads/" in path else "-",
            )
        print(
            "[http] "
            f"method={request.method} path={path} integration_product={integration_product} "
            f"status={status} duration_ms={duration_ms} request_id={request_id}",
            flush=True,
        )

    try:
        response = await call_next(request)
    except BaseException:
        # O handler de Exception vive no ServerErrorMiddleware, que é externo a
        # este middleware: quando call_next levanta, a resposta 500 é montada
        # fora daqui e a linha [http] nunca saía. Emitimos antes de repassar,
        # para a requisição aparecer no Render mesmo quando quebra.
        emit(500)
        raise
    finally:
        _reset_request_id(request_id_token)
    emit(response.status_code)
    response.headers["X-Request-ID"] = request_id
    return response

TTL_DASHBOARD_SECONDS = 120
TTL_MEDIA_SECONDS = 120
TTL_COMMENTS_SECONDS = 90
TTL_STORIES_SECONDS = 90
TTL_NOTES_SECONDS = 90
TTL_MEDIA_MONTHLY_SECONDS = 180

default_allow_origin = ",".join(
    [
        "http://localhost:5173",
        "http://localhost:5174",
    ]
)
raw = (os.getenv("ALLOW_ORIGIN") or default_allow_origin).strip()
allow_origins = [o.strip() for o in raw.split(",") if o.strip()]
allow_all_origins = "*" in allow_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=not allow_all_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    codes = {
        401: "AUTHENTICATION_REQUIRED",
        403: "TENANT_ACCESS_DENIED",
        404: "RESOURCE_NOT_FOUND",
        429: "RATE_LIMITED",
    }
    raw_detail = exc.detail
    detail_payload = raw_detail if isinstance(raw_detail, dict) else {}
    code = str(detail_payload.get("code") or codes.get(exc.status_code, "REQUEST_FAILED"))
    message = str(detail_payload.get("message") or (raw_detail if isinstance(raw_detail, str) else "A solicitação não pôde ser concluída."))
    request_id = str(getattr(request.state, "request_id", "") or "")
    retryable = bool(detail_payload.get("retryable")) if "retryable" in detail_payload else exc.status_code == 429 or exc.status_code >= 500
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "ok": False,
            "code": code,
            "message": message,
            "status": exc.status_code,
            "retryable": retryable,
            "path": request.url.path,
            "request_id": request_id,
            "detail": {"code": code, "message": message, "request_id": request_id, "reason": str(detail_payload.get("reason") or "http_error")},
        },
        headers=exc.headers,
    )


@app.exception_handler(IntegrationError)
async def integration_exception_handler(request: Request, exc: IntegrationError):
    print(
        "[api][integration_error] "
        f"method={request.method} path={request.url.path} "
        f"provider={exc.provider} code={exc.code} status={exc.status_code}"
    )
    reauth_required = exc.code in {
        "GOOGLE_TOKEN_EXPIRED", "GOOGLE_REAUTH_REQUIRED",
        "GOOGLE_REAUTH_REQUIRED_REFRESH_MISSING", "GOOGLE_REAUTH_REQUIRED_INVALID_GRANT",
        "GOOGLE_SCOPE_INSUFFICIENT", "META_TOKEN_EXPIRED", "META_REAUTH_REQUIRED",
        "META_PERMISSION_MISSING",
    }
    setup_required = exc.code == "GOOGLE_ADS_SETUP_REQUIRED"
    safe_reasons = {
        "GOOGLE_CONNECTION_DISCONNECTED": "connection_disconnected",
        "GOOGLE_REAUTH_REQUIRED_REFRESH_MISSING": "refresh_token_missing",
        "GOOGLE_REAUTH_REQUIRED_INVALID_GRANT": "refresh_token_rejected",
        "GOOGLE_ADMIN_API_DISABLED": "admin_api_disabled",
    }
    detail = {
        "code": exc.code,
        "message": exc.public_message,
        "request_id": str(getattr(request.state, "request_id", "") or ""),
        "reason": safe_reasons.get(exc.code, "integration_error"),
        "reauth_required": reauth_required,
        "setup_required": setup_required,
        **exc.diagnostics,
    }
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "ok": False,
            "code": exc.code,
            "message": exc.public_message,
            "provider": exc.provider,
            "status": exc.status_code,
            "retryable": exc.retryable,
            "path": request.url.path,
            "request_id": str(getattr(request.state, "request_id", "") or ""),
            "reauth_required": reauth_required,
            "setup_required": setup_required,
            "detail": detail,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    print(f"[api][unhandled] method={request.method} path={request.url.path} error={repr(exc)}")
    print(tb)
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "code": "INTERNAL_ERROR",
            "message": "Erro interno da API.",
            "status": 500,
            "retryable": True,
            "path": request.url.path,
            "request_id": str(getattr(request.state, "request_id", "") or ""),
        },
    )


@app.on_event("startup")
async def startup_bootstrap():
    try:
        applied = await bootstrap_meta_from_env()
        if applied:
            print(f"[startup] bootstrap meta aplicado: {', '.join(applied)}")
    except Exception as exc:
        print(f"[startup] bootstrap meta falhou: {exc}")


@app.get("/")
def root():
    return {"ok": True, "service": "mugo-dados-api"}


@app.head("/")
def root_head():
    return JSONResponse(content=None, status_code=200)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


@app.get("/health")
def health():
    revision = (os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT") or "").strip()
    return {"ok": True, "revision": revision[:12] or None}

app.include_router(shopify_router)
app.include_router(shopify_oauth_router)
app.include_router(google_router)
app.include_router(google_oauth_router)
app.include_router(fbits_router)
app.include_router(meta_legacy_router)
app.include_router(invitations_router)
app.include_router(intelligence_router)
app.include_router(client_access_router)
app.include_router(connections_router)
app.include_router(integrations_router)
app.include_router(platform_admin_router)
app.include_router(admin_health_router)


@app.get("/api/ig/stories")
async def api_stories(
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    connection_id: str | None = Query(default=None),
    limit: int = Query(25, ge=1, le=100),
    days: int = Query(30, ge=1, le=3650),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
):
    started = _started()
    endpoint = "/api/ig/stories"
    user_for_log = await _log_endpoint_call(
        endpoint=endpoint,
        authorization=authorization,
        x_client_id=x_client_id,
        client_id=client_id,
        connection_id=connection_id,
        days=days,
        start=start,
        end=end,
    )
    try:
        cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
        validated_connection_id = await _validated_connection_id(
            client_id=cid,
            connection_id=connection_id,
            authorization=authorization,
        )
        key = _cache_key(
            {
                "client_id": cid,
                "connection_id": _clean(validated_connection_id) or "-",
                "days": days,
                "start": _clean(start) or "-",
                "end": _clean(end) or "-",
                "limit": limit,
            }
        )
        payload, cache_hit = await get_cached_or_load(
            namespace="stories",
            key=key,
            ttl_seconds=TTL_STORIES_SECONDS,
            loader=lambda: get_stories(
                client_id=cid,
                connection_id=validated_connection_id,
                limit=limit,
                days=days,
                start=start,
                end=end,
            ),
        )
        _log_endpoint_done(
            endpoint=endpoint,
            started=started,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=cid,
            connection_id=validated_connection_id,
            days=days,
            start=start,
            end=end,
            cache_hit=cache_hit,
        )
        return payload
    except IntegrationError:
        raise
    except HTTPException as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
            connection_id=connection_id,
            days=days,
            start=start,
            end=end,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=exc.status_code,
            code="api_stories_http_error",
        )
    except RuntimeError as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
            connection_id=connection_id,
            days=days,
            start=start,
            end=end,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=400,
            code="api_stories_runtime_error",
        )
    except Exception as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
            connection_id=connection_id,
            days=days,
            start=start,
            end=end,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=500,
            code="api_stories_unexpected_error",
        )


@app.get("/api/months")
async def api_months(
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
    return await get_months(client_id=cid, connection_id=validated_connection_id)


# Compat com frontend atual
@app.get("/api/dashboard")
async def api_dashboard(
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    connection_id: str | None = Query(default=None),
    days: int = Query(30, ge=1, le=3650),
    month: str | None = None,
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
):
    started = _started()
    endpoint = "/api/dashboard"
    user_for_log = await _log_endpoint_call(
        endpoint=endpoint,
        authorization=authorization,
        x_client_id=x_client_id,
        client_id=client_id,
        connection_id=connection_id,
        days=days,
        start=start,
        end=end,
    )
    try:
        cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
        validated_connection_id = await _validated_connection_id(
            client_id=cid,
            connection_id=connection_id,
            authorization=authorization,
        )
        key = _cache_key(
            {
                "client_id": cid,
                "connection_id": _clean(validated_connection_id) or "-",
                "days": days,
                "month": _clean(month) or "-",
                "start": _clean(start) or "-",
                "end": _clean(end) or "-",
            }
        )
        payload, cache_hit = await get_cached_or_load(
            namespace="dashboard",
            key=key,
            ttl_seconds=TTL_DASHBOARD_SECONDS,
            loader=lambda: get_dashboard(
                client_id=cid,
                connection_id=validated_connection_id,
                days=days,
                month=month,
                start=start,
                end=end,
            ),
        )
        _log_endpoint_done(
            endpoint=endpoint,
            started=started,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=cid,
            connection_id=validated_connection_id,
            days=days,
            start=start,
            end=end,
            cache_hit=cache_hit,
        )
        return payload
    except HTTPException as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
            connection_id=connection_id,
            days=days,
            start=start,
            end=end,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=exc.status_code,
            code="api_dashboard_http_error",
        )
    except Exception as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
            connection_id=connection_id,
            days=days,
            start=start,
            end=end,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=500,
            code="api_dashboard_unexpected_error",
        )


@app.get("/api/dashboard/organic")
async def api_dashboard_organic(
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    connection_id: str | None = Query(default=None),
    days: int = Query(30, ge=1, le=3650),
    month: str | None = None,
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
    return await get_dashboard(
        client_id=cid,
        connection_id=validated_connection_id,
        days=days,
        month=month,
        start=start,
        end=end,
    )


@app.get("/api/dashboard/paid")
async def api_dashboard_paid(
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    connection_id: str | None = Query(default=None),
    days: int = Query(30, ge=1, le=365),
    month: str | None = None,
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    campaign: str | None = Query(default=None),
    adset: str | None = Query(default=None),
    ad: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
):
    started = _started()
    endpoint = "/api/dashboard/paid"
    user_for_log = await _log_endpoint_call(
        endpoint=endpoint,
        authorization=authorization,
        x_client_id=x_client_id,
        client_id=client_id,
        connection_id=connection_id,
        days=days,
        start=start,
        end=end,
    )
    try:
        cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
        validated_connection_id = await _validated_connection_id(
            client_id=cid,
            connection_id=connection_id,
            authorization=authorization,
        )
        payload = await get_paid_dashboard(
            client_id=cid,
            connection_id=validated_connection_id,
            days=days,
            month=month,
            start=start,
            end=end,
            campaign=campaign,
            adset=adset,
            ad=ad,
            platform=platform,
        )
        paid_sources = payload.get("sources") or {}
        paid_rows = paid_sources.get("rows") or {}
        print(
            "[api][dashboard_paid][audit] "
            f"client_id={cid} connection_id={_clean(str(payload.get('connection_id') or validated_connection_id)) or '-'} "
            f"since={_clean(str((payload.get('date_range') or {}).get('since') or start)) or '-'} "
            f"until={_clean(str((payload.get('date_range') or {}).get('until') or end)) or '-'} "
            f"has_data={1 if bool(payload.get('has_data')) else 0} row_count={int(payload.get('row_count') or 0)} "
            f"rows_ad_account_daily_stats={int(paid_rows.get('ad_account_daily_stats') or 0)} "
            f"rows_ad_daily_stats={int(paid_rows.get('ad_daily_stats') or 0)} "
            f"rows_promoted_post_daily_stats={int(paid_rows.get('promoted_post_daily_stats') or 0)} "
            f"rows_promoted_unique={int(paid_rows.get('promoted_post_unique') or 0)} "
            f"rows_aggregated={int(paid_rows.get('aggregated_rows') or 0)} "
            f"mode_account={_clean(str(paid_sources.get('mode_account') or '-')) or '-'} "
            f"mode_ad={_clean(str(paid_sources.get('mode_ad') or '-')) or '-'} "
            f"mode_promoted={_clean(str(paid_sources.get('mode_promoted') or '-')) or '-'} "
            f"message={_clip(str(payload.get('message') or '-'), 180) or '-'}"
        )
        _log_endpoint_done(
            endpoint=endpoint,
            started=started,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=cid,
            connection_id=validated_connection_id,
            days=days,
            start=start,
            end=end,
        )
        return payload
    except HTTPException as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
            connection_id=connection_id,
            days=days,
            start=start,
            end=end,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=exc.status_code,
            code="api_dashboard_paid_http_error",
        )
    except RuntimeError as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
            connection_id=connection_id,
            days=days,
            start=start,
            end=end,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=400,
            code="api_dashboard_paid_runtime_error",
        )
    except Exception as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
            connection_id=connection_id,
            days=days,
            start=start,
            end=end,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=500,
            code="api_dashboard_paid_unexpected_error",
        )


@app.get("/api/dashboard/summary")
async def api_dashboard_summary(
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    connection_id: str | None = Query(default=None),
    days: int = Query(30, ge=1, le=365),
    month: str | None = None,
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
    # 🔹 dados orgânicos (Instagram)
    dash = await get_dashboard(
        client_id=cid,
        connection_id=validated_connection_id,
        days=days,
        month=month,
        start=start,
        end=end,
    )

    media = await get_media(
        client_id=cid,
        connection_id=validated_connection_id,
        days=days,
        start=start,
        end=end,
        limit=120,
        offset=0,
    )

    comments = await get_comments(
        client_id=cid,
        connection_id=validated_connection_id,
        days=days,
        start=start,
        end=end,
        limit=120,
        offset=0,
    )

    # 🔹 (opcional) manter paid
    paid = await get_summary_dashboard(
        client_id=cid,
        # `connection_id` desta rota pertence ao escopo orgânico legado. Meta
        # Ads resolve sua própria conexão paid e nunca herda um id Instagram.
        connection_id=None,
        days=days,
        month=month,
        start=start,
        end=end,
    )

    return {
        "dash": dash,
        "media": media.get("media", []),
        "comments": comments.get("comments", []),
        "top_words": comments.get("top_words", []),
        "paid": paid,
    }

@app.get("/api/dashboard/executive")
async def api_dashboard_executive(
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    days: int = Query(30, ge=1, le=365),
    month: str | None = None,
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    include_previous_period: bool = Query(default=True),
    authorization: str | None = Header(default=None),
):
    """Payload executivo (Shopify + Meta + Google Ads + GA4 + blended ROAS)
    já com todos os números calculados no backend — Dashboard ("Operação
    real") e Intelligence consomem este mesmo endpoint, nunca recalculam."""
    cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
    return await get_executive_summary(
        cid,
        days=days,
        month=month,
        start=start,
        end=end,
        include_previous_period=include_previous_period,
    )


@app.post("/api/ads/sync")
async def api_ads_sync(
    request: Request,
    payload: Dict[str, Any],
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    started = _started()
    endpoint = "/api/ads/sync"
    payload_client_id = _clean(str(payload.get("client_id") or ""))
    payload_connection_id = _clean(str(payload.get("connection_id") or "")) or None
    payload_since = _clean(str(payload.get("since") or ""))
    payload_until = _clean(str(payload.get("until") or ""))
    user_for_log = await _log_endpoint_call(
        endpoint=endpoint,
        authorization=authorization,
        x_client_id=x_client_id,
        client_id=payload_client_id,
        connection_id=payload_connection_id,
        start=payload_since,
        end=payload_until,
    )
    try:
        # Sync manual é mutação: viewer não dispara (mesma regra de /meta-ads/sync).
        cid = await require_client_role(_pick_client_id(payload_client_id, x_client_id), authorization)
        validated_connection_id = await _validated_connection_id(
            client_id=cid,
            connection_id=payload_connection_id,
            authorization=authorization,
        )
        result = await sync_ads_for_client_period(
            client_id=cid,
            since=payload_since,
            until=payload_until,
            connection_id=validated_connection_id,
            request_id=str(getattr(request.state, "request_id", "") or "-"),
        )
        rows_returned = result.get("rows_returned") or {}
        saved = result.get("saved") or {}
        persisted_rows = result.get("persisted_rows") or {}
        print(
            "[api][ads_sync][audit] "
            f"client_id={cid} connection_id={_clean(str(result.get('connection_id') or validated_connection_id)) or '-'} "
            f"ad_account_id={_clean(str(result.get('ad_account_id') or '-')) or '-'} "
            f"since={_clean(str((result.get('date_range') or {}).get('since') or payload_since)) or '-'} "
            f"until={_clean(str((result.get('date_range') or {}).get('until') or payload_until)) or '-'} "
            f"rows_classic_ads={int(rows_returned.get('ad') or 0)} "
            f"rows_boosted_posts={int(rows_returned.get('boosted_posts') or 0)} "
            f"rows_boosted_fallback={int(rows_returned.get('boosted_fallback_in_classic') or 0)} "
            f"saved_ad_account_daily_stats={int(saved.get('ad_account_daily_stats') or 0)} "
            f"saved_campaign_daily_stats={int(saved.get('campaign_daily_stats') or 0)} "
            f"saved_ad_daily_stats={int(saved.get('ad_daily_stats') or 0)} "
            f"saved_promoted_post_daily_stats={int(saved.get('promoted_post_daily_stats') or 0)} "
            f"persisted_ad_account_daily_stats={int(persisted_rows.get('ad_account_daily_stats') or 0)} "
            f"persisted_campaign_daily_stats={int(persisted_rows.get('campaign_daily_stats') or 0)} "
            f"persisted_ad_daily_stats={int(persisted_rows.get('ad_daily_stats') or 0)} "
            f"persisted_promoted_post_daily_stats={int(persisted_rows.get('promoted_post_daily_stats') or 0)}"
        )
        _log_endpoint_done(
            endpoint=endpoint,
            started=started,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=cid,
            connection_id=str(result.get("connection_id") or validated_connection_id or ""),
            start=payload_since,
            end=payload_until,
        )
        return result
    except IntegrationError:
        raise
    except HTTPException as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=payload_client_id,
            connection_id=payload_connection_id,
            start=payload_since,
            end=payload_until,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=exc.status_code,
            code="api_ads_sync_http_error",
        )
    except RuntimeError as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=payload_client_id,
            connection_id=payload_connection_id,
            start=payload_since,
            end=payload_until,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=400,
            code="api_ads_sync_runtime_error",
        )
    except Exception as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=payload_client_id,
            connection_id=payload_connection_id,
            start=payload_since,
            end=payload_until,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=500,
            code="api_ads_sync_unexpected_error",
        )


@app.get("/api/campaigns")
async def api_campaigns(
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    connection_id: str | None = Query(default=None),
    days: int = Query(30, ge=1, le=365),
    month: str | None = None,
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    limit: int = Query(100, ge=1, le=1000),
    authorization: str | None = Header(default=None),
):
    cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
    validated_connection_id = await _validated_connection_id(
        client_id=cid,
        connection_id=connection_id,
        authorization=authorization,
    )
    return await list_campaigns(
        client_id=cid,
        connection_id=validated_connection_id,
        days=days,
        month=month,
        limit=limit,
        start=start,
        end=end,
    )


@app.get("/api/ads")
async def api_ads(
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    connection_id: str | None = Query(default=None),
    days: int = Query(30, ge=1, le=365),
    month: str | None = None,
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    limit: int = Query(200, ge=1, le=2000),
    authorization: str | None = Header(default=None),
):
    cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
    validated_connection_id = await _validated_connection_id(
        client_id=cid,
        connection_id=connection_id,
        authorization=authorization,
    )
    return await list_ads(
        client_id=cid,
        connection_id=validated_connection_id,
        days=days,
        month=month,
        limit=limit,
        start=start,
        end=end,
    )


@app.get("/api/debug/paid-sync-check")
async def api_debug_paid_sync_check(
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    started = _started()
    endpoint = "/api/debug/paid-sync-check"
    user_for_log = await _log_endpoint_call(
        endpoint=endpoint,
        authorization=authorization,
        x_client_id=x_client_id,
        client_id=client_id,
    )
    try:
        cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
        month_windows = [
            ("2026-01", "2026-01-01", "2026-01-31"),
            ("2026-03", "2026-03-01", "2026-03-31"),
        ]
        tables = [
            "ad_account_daily_stats",
            "campaign_daily_stats",
            "ad_daily_stats",
            "promoted_post_daily_stats",
        ]

        checks: Dict[str, Any] = {}
        for table in tables:
            table_rows = []
            for month_key, since, until in month_windows:
                rows = await sb_query(
                    table,
                    (
                        f"client_id=eq.{cid}"
                        f"&and=(stat_date.gte.{since},stat_date.lte.{until})"
                        "&select=stat_date&order=stat_date.asc&limit=10000"
                    ),
                )
                stat_dates = sorted(
                    [
                        str(row.get("stat_date") or "").strip()
                        for row in rows
                        if str(row.get("stat_date") or "").strip()
                    ]
                )
                first_stat_date = stat_dates[0] if stat_dates else None
                last_stat_date = stat_dates[-1] if stat_dates else None
                print(
                    "[paid][sync-check] "
                    f"client_id={cid} table={table} month={month_key} "
                    f"rows={len(rows)} first_stat_date={first_stat_date or '-'} "
                    f"last_stat_date={last_stat_date or '-'}"
                )
                table_rows.append(
                    {
                        "month": month_key,
                        "row_count": len(rows),
                        "first_stat_date": first_stat_date,
                        "last_stat_date": last_stat_date,
                    }
                )
            checks[table] = table_rows

        _log_endpoint_done(
            endpoint=endpoint,
            started=started,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=cid,
        )
        return {
            "ok": True,
            "client_id": cid,
            "checks": checks,
        }
    except HTTPException as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=exc.status_code,
            code="api_debug_paid_sync_http_error",
        )
    except Exception as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=500,
            code="api_debug_paid_sync_unexpected_error",
        )


@app.get("/api/comments")
async def api_comments(
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    connection_id: str | None = Query(default=None),
    days: int = Query(0, ge=0, le=3650),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    limit: int = Query(120, ge=1, le=500),
    offset: int = Query(0, ge=0, le=20000),
    include_media_linked: bool = Query(False),
    authorization: str | None = Header(default=None),
):
    started = _started()
    endpoint = "/api/comments"
    user_for_log = await _log_endpoint_call(
        endpoint=endpoint,
        authorization=authorization,
        x_client_id=x_client_id,
        client_id=client_id,
        connection_id=connection_id,
        days=days,
        start=start,
        end=end,
    )
    try:
        cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
        validated_connection_id = await _validated_connection_id(
            client_id=cid,
            connection_id=connection_id,
            authorization=authorization,
        )
        key = _cache_key(
            {
                "client_id": cid,
                "connection_id": _clean(validated_connection_id) or "-",
                "days": days,
                "start": _clean(start) or "-",
                "end": _clean(end) or "-",
                "limit": limit,
                "offset": offset,
                "include_media_linked": 1 if include_media_linked else 0,
            }
        )
        payload, cache_hit = await get_cached_or_load(
            namespace="comments",
            key=key,
            ttl_seconds=TTL_COMMENTS_SECONDS,
            loader=lambda: get_comments(
                client_id=cid,
                connection_id=validated_connection_id,
                days=days,
                start=start,
                end=end,
                limit=limit,
                offset=offset,
                include_media_linked=include_media_linked,
            ),
        )
        _log_endpoint_done(
            endpoint=endpoint,
            started=started,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=cid,
            connection_id=validated_connection_id,
            days=days,
            start=start,
            end=end,
            cache_hit=cache_hit,
        )
        return payload
    except HTTPException as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
            connection_id=connection_id,
            days=days,
            start=start,
            end=end,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=exc.status_code,
            code="api_comments_http_error",
        )
    except Exception as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
            connection_id=connection_id,
            days=days,
            start=start,
            end=end,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=500,
            code="api_comments_unexpected_error",
        )


@app.get("/api/media")
async def api_media(
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    connection_id: str | None = Query(default=None),
    days: int = Query(365, ge=1, le=3650),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    limit: int = Query(120, ge=1, le=1000),
    offset: int = Query(0, ge=0, le=20000),
    authorization: str | None = Header(default=None),
):
    started = _started()
    endpoint = "/api/media"
    user_for_log = await _log_endpoint_call(
        endpoint=endpoint,
        authorization=authorization,
        x_client_id=x_client_id,
        client_id=client_id,
        connection_id=connection_id,
        days=days,
        start=start,
        end=end,
    )
    try:
        cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
        validated_connection_id = await _validated_connection_id(
            client_id=cid,
            connection_id=connection_id,
            authorization=authorization,
        )
        key = _cache_key(
            {
                "client_id": cid,
                "connection_id": _clean(validated_connection_id) or "-",
                "days": days,
                "start": _clean(start) or "-",
                "end": _clean(end) or "-",
                "limit": limit,
                "offset": offset,
            }
        )
        payload, cache_hit = await get_cached_or_load(
            namespace="media",
            key=key,
            ttl_seconds=TTL_MEDIA_SECONDS,
            loader=lambda: get_media(
                client_id=cid,
                connection_id=validated_connection_id,
                days=days,
                start=start,
                end=end,
                limit=limit,
                offset=offset,
            ),
        )
        _log_endpoint_done(
            endpoint=endpoint,
            started=started,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=cid,
            connection_id=validated_connection_id,
            days=days,
            start=start,
            end=end,
            cache_hit=cache_hit,
        )
        return payload
    except HTTPException as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
            connection_id=connection_id,
            days=days,
            start=start,
            end=end,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=exc.status_code,
            code="api_media_http_error",
        )
    except Exception as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
            connection_id=connection_id,
            days=days,
            start=start,
            end=end,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=500,
            code="api_media_unexpected_error",
        )


@app.get("/api/media/monthly")
async def api_media_monthly(
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    connection_id: str | None = Query(default=None),
    days: int = Query(3650, ge=1, le=3650),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
):
    started = _started()
    endpoint = "/api/media/monthly"
    user_for_log = await _log_endpoint_call(
        endpoint=endpoint,
        authorization=authorization,
        x_client_id=x_client_id,
        client_id=client_id,
        connection_id=connection_id,
        days=days,
        start=start,
        end=end,
    )
    try:
        cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
        validated_connection_id = await _validated_connection_id(
            client_id=cid,
            connection_id=connection_id,
            authorization=authorization,
        )
        key = _cache_key(
            {
                "client_id": cid,
                "connection_id": _clean(validated_connection_id) or "-",
                "days": days,
                "start": _clean(start) or "-",
                "end": _clean(end) or "-",
            }
        )
        payload, cache_hit = await get_cached_or_load(
            namespace="media_monthly",
            key=key,
            ttl_seconds=TTL_MEDIA_MONTHLY_SECONDS,
            loader=lambda: get_media_monthly(
                client_id=cid,
                connection_id=validated_connection_id,
                days=days,
                start=start,
                end=end,
            ),
        )
        _log_endpoint_done(
            endpoint=endpoint,
            started=started,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=cid,
            connection_id=validated_connection_id,
            days=days,
            start=start,
            end=end,
            cache_hit=cache_hit,
        )
        return payload
    except HTTPException as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
            connection_id=connection_id,
            days=days,
            start=start,
            end=end,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=exc.status_code,
            code="api_media_monthly_http_error",
        )
    except Exception as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
            connection_id=connection_id,
            days=days,
            start=start,
            end=end,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=500,
            code="api_media_monthly_unexpected_error",
        )


@app.get("/api/notes")
async def api_notes(
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    connection_id: str | None = Query(default=None),
    limit: int = Query(80, ge=1, le=300),
    authorization: str | None = Header(default=None),
):
    started = _started()
    endpoint = "/api/notes"
    user_for_log = await _log_endpoint_call(
        endpoint=endpoint,
        authorization=authorization,
        x_client_id=x_client_id,
        client_id=client_id,
        connection_id=connection_id,
    )
    try:
        cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
        validated_connection_id = await _validated_connection_id(
            client_id=cid,
            connection_id=connection_id,
            authorization=authorization,
        )
        key = _cache_key(
            {
                "client_id": cid,
                "connection_id": _clean(validated_connection_id) or "-",
                "limit": limit,
            }
        )
        payload, cache_hit = await get_cached_or_load(
            namespace="notes",
            key=key,
            ttl_seconds=TTL_NOTES_SECONDS,
            loader=lambda: list_notes(
                client_id=cid,
                connection_id=validated_connection_id,
                limit=limit,
            ),
        )
        _log_endpoint_done(
            endpoint=endpoint,
            started=started,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=cid,
            connection_id=validated_connection_id,
            cache_hit=cache_hit,
        )
        return payload
    except HTTPException as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
            connection_id=connection_id,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=exc.status_code,
            code="api_notes_http_error",
        )
    except Exception as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
            connection_id=connection_id,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=500,
            code="api_notes_unexpected_error",
        )


@app.post("/api/notes")
async def api_notes_create(
    payload: Dict[str, Any],
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
    note = await create_note(client_id=cid, title=str(payload.get("title") or ""), body=str(payload.get("body") or ""))
    await invalidate_namespace("notes")
    return note


@app.put("/api/notes/{note_id}")
async def api_notes_update(
    note_id: str,
    payload: Dict[str, Any],
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
    note = await update_note(client_id=cid, note_id=note_id, title=payload.get("title"), body=payload.get("body"))
    await invalidate_namespace("notes")
    return note


@app.post("/api/ai/summary")
@app.get("/api/ai/summary")
async def api_ai_summary(
    client_id: str | None = None,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    days: int = Query(30, ge=1, le=3650),
    month: str | None = None,
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
):
    cid = await resolve_client_id(_pick_client_id(client_id, x_client_id), authorization)
    return await ai_summary(client_id=cid, days=days, month=month, start=start, end=end)
