import os
import traceback
from typing import Any, Dict, Optional

from services.env_loader import ensure_env_loaded

ensure_env_loaded()

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
    _validated_connection_id,
)
from routes.google import router as google_router
from routes.google_oauth import router as google_oauth_router
from routes.fbits import router as fbits_router
from routes.meta_legacy import router as meta_legacy_router
from routes.invitations import router as invitations_router
from routes.connections import router as connections_router
from routes.platform_admin import router as platform_admin_router
from routes.shopify import router as shopify_router
from routes.shopify_oauth import router as shopify_oauth_router

from services.ai_summary import ai_summary
from services.ads_sync import sync_ads_for_client_period
from services.bootstrap import bootstrap_meta_from_env
from services.comments import get_comments
from services.dashboard_paid import get_paid_dashboard, get_summary_dashboard, list_ads, list_campaigns
from services.ig_dashboard import get_dashboard
from services.ig_months import get_months
from services.ig_supabase import sb_query
from services.media import get_media, get_media_monthly
from services.notes import create_note, list_notes, update_note
from services.stories import get_stories
from services.runtime_cache import get_cached_or_load, invalidate_namespace
from services.tenant import require_user_id, resolve_client_id

app = FastAPI(title="Mugô Dados API")

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
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "ok": False,
            "code": codes.get(exc.status_code, "REQUEST_FAILED"),
            "message": str(exc.detail or "A solicitação não pôde ser concluída."),
            "status": exc.status_code,
            "retryable": exc.status_code == 429 or exc.status_code >= 500,
            "path": request.url.path,
        },
        headers=exc.headers,
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


@app.get("/health")
def health():
    return {"ok": True}

app.include_router(shopify_router)
app.include_router(shopify_oauth_router)
app.include_router(google_router)
app.include_router(google_oauth_router)
app.include_router(fbits_router)
app.include_router(meta_legacy_router)
app.include_router(invitations_router)
app.include_router(connections_router)
app.include_router(platform_admin_router)


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

    stories = await get_stories(
        client_id=cid,
        connection_id=validated_connection_id,
        days=days,
        start=start,
        end=end,
        limit=50,
    )

    # 🔹 (opcional) manter paid
    paid = await get_summary_dashboard(
        client_id=cid,
        connection_id=validated_connection_id,
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
        "stories": stories.get("stories", []),
        "paid": paid,
    }

@app.post("/api/ads/sync")
async def api_ads_sync(
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
        cid = await resolve_client_id(_pick_client_id(payload_client_id, x_client_id), authorization)
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
