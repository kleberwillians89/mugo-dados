from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query

from api_support import (
    _elapsed_ms,
    _log_endpoint_call,
    _log_endpoint_done,
    _log_endpoint_error,
    _runtime_error_status,
    _started,
    _structured_error_response,
)
from services.ga4_reporting import (
    build_ga4_campaigns_report,
    build_ga4_channels_report,
    build_ga4_events_report,
    build_ga4_report,
    resolve_ga4_report_period,
)
from services.ga4_sync import sync_ga4_for_period
from services.ga4_connections import resolve_ga4_connection_context
from services.google_oauth import get_google_access_token
from services.google_ads import build_google_ads_report, resolve_google_ads_context, sync_google_ads
from services.tenant import require_user_id, resolve_client_id

router = APIRouter(tags=["google"])

GOOGLE_ENDPOINTS = [
    "POST /api/google/ga4/sync",
    "GET /api/google/ga4/report",
    "GET /api/google/ga4/channels",
    "GET /api/google/ga4/campaigns",
    "GET /api/google/ga4/events",
    "POST /api/google/ads/sync",
    "GET /api/google/ads/report",
]


@router.post("/api/google/ads/sync")
async def google_ads_sync(
    start: str | None = Query(default=None), end: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=366), client_id: str | None = Query(default=None),
    connection_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await resolve_client_id(_pick_ga4_client_id(client_id, x_client_id), authorization)
    await require_user_id(authorization)
    return await sync_google_ads(
        client_id=cid, connection_id=connection_id, start=start, end=end, days=days,
    )


@router.get("/api/google/ads/report")
async def google_ads_report(
    start: str | None = Query(default=None), end: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=366), client_id: str | None = Query(default=None),
    connection_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await resolve_client_id(_pick_ga4_client_id(client_id, x_client_id), authorization)
    await require_user_id(authorization)
    context = await resolve_google_ads_context(cid, connection_id)
    period = resolve_ga4_report_period(start=start, end=end, days=days)
    return await build_google_ads_report(
        client_id=cid, context=context,
        start=period.start.isoformat(), end=period.end.isoformat(),
    )


def _pick_ga4_client_id(client_id: str | None, x_client_id: str | None) -> str | None:
    return (client_id or "").strip() or (x_client_id or "").strip() or None


async def _ga4_request_context(
    client_id: str | None,
    x_client_id: str | None,
    authorization: str | None,
    selected_connection_id: str | None,
) -> tuple[str, str, str | None]:
    requested = _pick_ga4_client_id(client_id, x_client_id)
    authorized_client_id = await resolve_client_id(requested, authorization)
    context = await resolve_ga4_connection_context(authorized_client_id, selected_connection_id)
    print(
        "[google][ga4_context] "
        f"requested_client_id={requested or '-'} x_client_id={(x_client_id or '').strip() or '-'} "
        f"resolved_client_id={context.client_id} property_id={context.property_id} "
        f"auth_mode={context.auth_mode} connection_id={context.connection_id or '-'}"
    )
    return context.client_id, context.property_id, context.connection_id


@router.post("/api/google/ga4/sync")
async def ga4_sync(
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=366),
    client_id: str | None = Query(default=None),
    connection_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    started = _started()
    endpoint = "/api/google/ga4/sync"
    requested_client_id = client_id
    client_id, property_id, connection_id = await _ga4_request_context(client_id, x_client_id, authorization, connection_id)
    user_for_log = await _log_endpoint_call(
        endpoint=endpoint,
        authorization=authorization,
        x_client_id=x_client_id,
        client_id=requested_client_id or client_id,
        days=days,
        start=start,
        end=end,
    )
    try:
        await require_user_id(authorization)
        access_token = (
            await get_google_access_token(client_id, connection_id)
            if connection_id
            else None
        )
        payload = await sync_ga4_for_period(
            client_id=client_id,
            property_id=property_id,
            access_token=access_token,
            since=start,
            until=end,
            days=days,
            job_name="ga4_sync_manual",
            trigger_source="manual_api",
            record_job_run=True,
        )
        _log_endpoint_done(
            endpoint=endpoint,
            started=started,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
        )
        return payload
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
            code="ga4_sync_http_error",
        )
    except RuntimeError as exc:
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
            status_code=_runtime_error_status(exc),
            code="ga4_sync_runtime_error",
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
            code="ga4_sync_unexpected_error",
        )


@router.get("/api/google/ga4/report")
async def ga4_report(
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=366),
    client_id: str | None = Query(default=None),
    connection_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    started = _started()
    endpoint = "/api/google/ga4/report"
    requested_client_id = client_id
    client_id, property_id, _ = await _ga4_request_context(client_id, x_client_id, authorization, connection_id)
    user_for_log = await _log_endpoint_call(
        endpoint=endpoint,
        authorization=authorization,
        x_client_id=x_client_id,
        client_id=requested_client_id or client_id,
        days=days,
        start=start,
        end=end,
    )
    try:
        await require_user_id(authorization)
        period = resolve_ga4_report_period(start=start, end=end, days=days)
        payload = await build_ga4_report(
            client_id=client_id,
            property_id=property_id,
            period=period,
        )
        _log_endpoint_done(
            endpoint=endpoint,
            started=started,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
        )
        return payload
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
            code="ga4_report_http_error",
        )
    except RuntimeError as exc:
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
            status_code=_runtime_error_status(exc),
            code="ga4_report_runtime_error",
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
            code="ga4_report_unexpected_error",
        )


@router.get("/api/google/ga4/channels")
async def ga4_channels(
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=366),
    client_id: str | None = Query(default=None),
    connection_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    started = _started()
    endpoint = "/api/google/ga4/channels"
    requested_client_id = client_id
    client_id, property_id, _ = await _ga4_request_context(client_id, x_client_id, authorization, connection_id)
    user_for_log = await _log_endpoint_call(
        endpoint=endpoint,
        authorization=authorization,
        x_client_id=x_client_id,
        client_id=requested_client_id or client_id,
        days=days,
        start=start,
        end=end,
    )
    try:
        await require_user_id(authorization)
        period = resolve_ga4_report_period(start=start, end=end, days=days)
        payload = await build_ga4_channels_report(
            client_id=client_id,
            property_id=property_id,
            period=period,
        )
        _log_endpoint_done(
            endpoint=endpoint,
            started=started,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
        )
        return payload
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
            code="ga4_channels_http_error",
        )
    except RuntimeError as exc:
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
            status_code=_runtime_error_status(exc),
            code="ga4_channels_runtime_error",
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
            code="ga4_channels_unexpected_error",
        )


@router.get("/api/google/ga4/campaigns")
async def ga4_campaigns(
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=366),
    client_id: str | None = Query(default=None),
    connection_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    started = _started()
    endpoint = "/api/google/ga4/campaigns"
    requested_client_id = client_id
    client_id, property_id, _ = await _ga4_request_context(client_id, x_client_id, authorization, connection_id)
    user_for_log = await _log_endpoint_call(
        endpoint=endpoint,
        authorization=authorization,
        x_client_id=x_client_id,
        client_id=requested_client_id or client_id,
        days=days,
        start=start,
        end=end,
    )
    try:
        await require_user_id(authorization)
        period = resolve_ga4_report_period(start=start, end=end, days=days)
        payload = await build_ga4_campaigns_report(
            client_id=client_id,
            property_id=property_id,
            period=period,
        )
        _log_endpoint_done(
            endpoint=endpoint,
            started=started,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
        )
        return payload
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
            code="ga4_campaigns_http_error",
        )
    except RuntimeError as exc:
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
            status_code=_runtime_error_status(exc),
            code="ga4_campaigns_runtime_error",
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
            code="ga4_campaigns_unexpected_error",
        )


@router.get("/api/google/ga4/events")
async def ga4_events(
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=366),
    client_id: str | None = Query(default=None),
    connection_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    started = _started()
    endpoint = "/api/google/ga4/events"
    requested_client_id = client_id
    client_id, property_id, _ = await _ga4_request_context(client_id, x_client_id, authorization, connection_id)
    user_for_log = await _log_endpoint_call(
        endpoint=endpoint,
        authorization=authorization,
        x_client_id=x_client_id,
        client_id=requested_client_id or client_id,
        days=days,
        start=start,
        end=end,
    )
    try:
        await require_user_id(authorization)
        period = resolve_ga4_report_period(start=start, end=end, days=days)
        payload = await build_ga4_events_report(
            client_id=client_id,
            property_id=property_id,
            period=period,
        )
        _log_endpoint_done(
            endpoint=endpoint,
            started=started,
            user_id=user_for_log,
            x_client_id=x_client_id,
            client_id=client_id,
        )
        return payload
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
            code="ga4_events_http_error",
        )
    except RuntimeError as exc:
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
            status_code=_runtime_error_status(exc),
            code="ga4_events_runtime_error",
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
            code="ga4_events_unexpected_error",
        )
