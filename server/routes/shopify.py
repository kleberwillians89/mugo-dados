from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request

from api_support import (
    _clean,
    _clip,
    _elapsed_ms,
    _log_endpoint_call,
    _log_endpoint_done,
    _log_endpoint_error,
    _runtime_error_status,
    _started,
    _structured_error_response,
)
from services.shopify_webhooks import (
    _log_shopify_event,
    decode_shopify_webhook_payload,
    extract_shopify_order_id,
    get_shopify_client_id,
    list_recent_shopify_orders,
    list_recent_shopify_webhooks,
    mark_shopify_webhook_processing,
    process_shopify_webhook_event,
    register_shopify_webhook_event,
    validate_shopify_hmac,
    validate_shopify_shop_domain,
)
from services.shopify_reporting import (
    build_shopify_customers_report,
    build_shopify_report,
    resolve_shopify_report_period,
)
from services.shopify_oauth import (
    mark_store_uninstalled,
    resolve_shopify_connection_context,
    resolve_store_by_domain,
)
from services.tenant import resolve_client_id

router = APIRouter(tags=["shopify"])

SHOPIFY_ENDPOINTS = [
    "POST /api/webhooks/shopify",
    "GET /api/shopify/report",
    "GET /api/shopify/customers",
    "GET /api/shopify/debug/recent-webhooks",
    "GET /api/shopify/debug/recent-orders",
]


@router.post("/api/webhooks/shopify")
async def shopify_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_shopify_topic: str | None = Header(default=None, alias="X-Shopify-Topic"),
    x_shopify_hmac_sha256: str | None = Header(default=None, alias="X-Shopify-Hmac-Sha256"),
    x_shopify_shop_domain: str | None = Header(default=None, alias="X-Shopify-Shop-Domain"),
    x_shopify_webhook_id: str | None = Header(default=None, alias="X-Shopify-Webhook-Id"),
):
    started = _started()
    topic = _clean(x_shopify_topic) or "-"
    shop_domain = _clean(x_shopify_shop_domain) or "-"
    webhook_id = _clean(x_shopify_webhook_id) or None

    if topic == "-":
        raise HTTPException(status_code=400, detail="Header X-Shopify-Topic é obrigatório.")
    if shop_domain == "-":
        raise HTTPException(status_code=400, detail="Header X-Shopify-Shop-Domain é obrigatório.")

    raw_body = await request.body()
    is_valid_hmac, _computed_hmac, hmac_debug = validate_shopify_hmac(raw_body, x_shopify_hmac_sha256)
    if not is_valid_hmac:
        _log_shopify_event(
            status="rejected_hmac",
            topic=topic,
            webhook_id=webhook_id,
            shop_domain=shop_domain,
            details=hmac_debug,
        )
        raise HTTPException(status_code=401, detail="Webhook Shopify com assinatura inválida.")

    if not validate_shopify_shop_domain(shop_domain):
        _log_shopify_event(
            status="rejected_shop_domain",
            topic=topic,
            webhook_id=webhook_id,
            shop_domain=shop_domain,
            details=hmac_debug,
        )
        raise HTTPException(status_code=401, detail="Webhook Shopify fora do domínio configurado da empresa.")

    store = await resolve_store_by_domain(shop_domain)
    if not store:
        _log_shopify_event(
            status="rejected_unknown_shop",
            topic=topic,
            webhook_id=webhook_id,
            shop_domain=shop_domain,
        )
        raise HTTPException(status_code=401, detail="Webhook recebido de loja Shopify desconhecida.")
    client_id = str(store.get("client_id") or "").strip()

    try:
        payload = decode_shopify_webhook_payload(raw_body)
    except RuntimeError as exc:
        _log_shopify_event(
            status="rejected_payload",
            topic=topic,
            webhook_id=webhook_id,
            shop_domain=shop_domain,
            error_message=str(exc),
            details=hmac_debug,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    order_id = extract_shopify_order_id(topic, payload)

    event, duplicated = await register_shopify_webhook_event(
        client_id=client_id,
        webhook_id=webhook_id,
        topic=topic,
        shop_domain=shop_domain,
        payload_json=payload,
    )

    event_id = _clean(event.get("id"))
    event_status = _clean(event.get("status")).lower() or "received"
    queued = event_status not in {"processing", "processed", "ignored"}

    if topic == "app/uninstalled":
        await mark_store_uninstalled(shop_domain)

    if queued and event_id:
        await mark_shopify_webhook_processing(event_id)
        background_tasks.add_task(
            process_shopify_webhook_event,
            event_id=event_id,
            client_id=client_id,
            topic=topic,
            shop_domain=shop_domain,
            webhook_id=webhook_id,
            payload_json=payload,
        )

    _log_shopify_event(
        status=event_status if duplicated and not queued else "accepted",
        topic=topic,
        webhook_id=webhook_id,
        shop_domain=shop_domain,
        order_id=order_id,
        event_id=event_id,
        client_id=client_id,
        duplicate=duplicated,
        queued=queued,
        duration_ms=_elapsed_ms(started),
    )
    return {
        "ok": True,
        "accepted": True,
        "duplicate": duplicated,
        "queued": queued,
        "event_id": event_id or None,
    }


@router.get("/api/shopify/debug/recent-webhooks")
async def shopify_recent_webhooks(
    limit: int = Query(default=20, ge=1, le=100),
    include_payload: bool = Query(default=False),
    client_id: str | None = Query(default=None),
    connection_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    started = _started()
    endpoint = "/api/shopify/debug/recent-webhooks"
    client_id = await resolve_client_id(client_id or x_client_id, authorization)
    user_for_log = await _log_endpoint_call(
        endpoint=endpoint,
        authorization=authorization,
        x_client_id=None,
        client_id=client_id,
    )
    try:
        context = await resolve_shopify_connection_context(
            client_id, connection_id=connection_id,
        )
        rows = await list_recent_shopify_webhooks(
            client_id=client_id,
            shop_domain=context.shop_domain,
            limit=limit,
            include_payload=include_payload,
        )
        _log_endpoint_done(
            endpoint=endpoint,
            started=started,
            user_id=user_for_log,
            x_client_id=None,
            client_id=client_id,
        )
        return {
            "ok": True,
            "client_id": client_id,
            "count": len(rows),
            "items": rows,
        }
    except HTTPException as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=None,
            client_id=client_id,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=exc.status_code,
            code="shopify_recent_webhooks_http_error",
        )
    except RuntimeError as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=None,
            client_id=client_id,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=400,
            code="shopify_recent_webhooks_runtime_error",
        )
    except Exception as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=None,
            client_id=client_id,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=500,
            code="shopify_recent_webhooks_unexpected_error",
        )


@router.get("/api/shopify/report")
async def shopify_report(
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=366),
    client_id: str | None = Query(default=None),
    connection_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    started = _started()
    endpoint = "/api/shopify/report"
    client_id = await resolve_client_id(client_id or x_client_id, authorization)
    user_for_log = await _log_endpoint_call(
        endpoint=endpoint,
        authorization=authorization,
        x_client_id=None,
        client_id=client_id,
        days=days,
        start=start,
        end=end,
    )
    try:
        context = await resolve_shopify_connection_context(
            client_id, connection_id=connection_id,
            required_scopes=("read_orders", "read_products"),
        )
        period = resolve_shopify_report_period(start=start, end=end, days=days)
        payload = await build_shopify_report(
            client_id=client_id,
            shop_domain=context.shop_domain,
            period=period,
        )
        _log_endpoint_done(
            endpoint=endpoint,
            started=started,
            user_id=user_for_log,
            x_client_id=None,
            client_id=client_id,
        )
        return payload
    except HTTPException as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=None,
            client_id=client_id,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=exc.status_code,
            code="shopify_report_http_error",
        )
    except RuntimeError as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=None,
            client_id=client_id,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=_runtime_error_status(exc),
            code="shopify_report_runtime_error",
        )
    except Exception as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=None,
            client_id=client_id,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=500,
            code="shopify_report_unexpected_error",
        )


@router.get("/api/shopify/customers")
async def shopify_customers(
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=366),
    client_id: str | None = Query(default=None),
    connection_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    started = _started()
    endpoint = "/api/shopify/customers"
    client_id = await resolve_client_id(client_id or x_client_id, authorization)
    user_for_log = await _log_endpoint_call(
        endpoint=endpoint,
        authorization=authorization,
        x_client_id=None,
        client_id=client_id,
        days=days,
        start=start,
        end=end,
    )
    try:
        context = await resolve_shopify_connection_context(
            client_id, connection_id=connection_id,
            required_scopes=("read_orders", "read_customers"),
        )
        period = resolve_shopify_report_period(start=start, end=end, days=days)
        payload = await build_shopify_customers_report(
            client_id=client_id,
            shop_domain=context.shop_domain,
            period=period,
        )
        _log_endpoint_done(
            endpoint=endpoint,
            started=started,
            user_id=user_for_log,
            x_client_id=None,
            client_id=client_id,
        )
        return payload
    except HTTPException as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=None,
            client_id=client_id,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=exc.status_code,
            code="shopify_customers_http_error",
        )
    except RuntimeError as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=None,
            client_id=client_id,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=_runtime_error_status(exc),
            code="shopify_customers_runtime_error",
        )
    except Exception as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=None,
            client_id=client_id,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=500,
            code="shopify_customers_unexpected_error",
        )


@router.get("/api/shopify/debug/recent-orders")
async def shopify_recent_orders(
    limit: int = Query(default=20, ge=1, le=100),
    include_raw: bool = Query(default=False),
    client_id: str | None = Query(default=None),
    connection_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    started = _started()
    endpoint = "/api/shopify/debug/recent-orders"
    client_id = await resolve_client_id(client_id or x_client_id, authorization)
    user_for_log = await _log_endpoint_call(
        endpoint=endpoint,
        authorization=authorization,
        x_client_id=None,
        client_id=client_id,
    )
    try:
        context = await resolve_shopify_connection_context(
            client_id,
            connection_id=connection_id,
            required_scopes=("read_orders",),
        )
        rows = await list_recent_shopify_orders(
            client_id=client_id,
            shop_domain=context.shop_domain,
            limit=limit,
            include_raw=include_raw,
        )
        _log_endpoint_done(
            endpoint=endpoint,
            started=started,
            user_id=user_for_log,
            x_client_id=None,
            client_id=client_id,
        )
        return {
            "ok": True,
            "client_id": client_id,
            "count": len(rows),
            "items": rows,
        }
    except HTTPException as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=None,
            client_id=client_id,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=exc.status_code,
            code="shopify_recent_orders_http_error",
        )
    except RuntimeError as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=None,
            client_id=client_id,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=400,
            code="shopify_recent_orders_runtime_error",
        )
    except Exception as exc:
        _log_endpoint_error(
            endpoint=endpoint,
            exc=exc,
            user_id=user_for_log,
            x_client_id=None,
            client_id=client_id,
        )
        return _structured_error_response(
            endpoint=endpoint,
            exc=exc,
            status_code=500,
            code="shopify_recent_orders_unexpected_error",
        )
