from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .env_loader import ensure_env_loaded
from .ig_supabase import sb_get_one_by, sb_insert, sb_select, sb_update, sb_upsert
from .single_tenant import get_default_client_id, get_default_shopify_domain

SUPPORTED_SHOPIFY_TOPICS = {
    "orders/create",
    "orders/updated",
    "orders/paid",
    "orders/cancelled",
    "refunds/create",
    "customers/create",
    "customers/update",
    "app/uninstalled",
    "customers/data_request",
    "customers/redact",
    "shop/redact",
}


def _env(name: str) -> str:
    import os

    return (os.getenv(name) or "").strip()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _normalize_shop_domain(value: Any) -> str:
    return _safe_str(value).lower()


def _safe_json(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clip(value: Any, size: int = 2000) -> Optional[str]:
    text = _safe_str(value)
    if not text:
        return None
    if len(text) <= size:
        return text
    return f"{text[:size]}..."


def _safe_id(value: Any) -> Optional[str]:
    text = _safe_str(value)
    return text or None


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return fallback


def _safe_money(value: Any) -> Optional[float]:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return None

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except Exception:
            return None

    if isinstance(value, dict):
        if "amount" in value:
            return _safe_money(value.get("amount"))
        for nested_key in ("shop_money", "presentment_money", "money", "amount_set"):
            if nested_key in value:
                nested = _safe_money(value.get(nested_key))
                if nested is not None:
                    return nested

    return None


def _pick_money(payload: Dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = _safe_money(payload.get(key))
        if value is not None:
            return value
    return None


def _parse_shopify_timestamp(value: Any) -> Optional[datetime]:
    raw = _safe_str(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_limit(limit: int, *, default: int = 20, maximum: int = 100) -> int:
    try:
        resolved = int(limit)
    except Exception:
        resolved = default
    return max(1, min(resolved, maximum))


def _postgrest_in_filter(values: List[str]) -> Optional[str]:
    cleaned = [_safe_str(value) for value in values if _safe_str(value)]
    if not cleaned:
        return None

    escaped = ",".join([json.dumps(value) for value in cleaned])
    return f"in.({escaped})"


def extract_shopify_order_id(topic: str, payload: Dict[str, Any]) -> Optional[str]:
    resolved_topic = _safe_str(topic).lower()
    data = _safe_json(payload)

    if resolved_topic.startswith("orders/"):
        return _safe_id(data.get("id"))

    if resolved_topic == "refunds/create":
        return _safe_id(data.get("order_id")) or _safe_id(_safe_json(data.get("order")).get("id"))

    return _safe_id(data.get("order_id"))


def _log_shopify_event(
    *,
    status: str,
    topic: Optional[str] = None,
    webhook_id: Optional[str] = None,
    shop_domain: Optional[str] = None,
    order_id: Optional[str] = None,
    event_id: Optional[str] = None,
    client_id: Optional[str] = None,
    duplicate: Optional[bool] = None,
    queued: Optional[bool] = None,
    duration_ms: Optional[int] = None,
    error_type: Optional[str] = None,
    error_message: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    parts = [
        f"status={_safe_str(status) or '-'}",
        f"topic={_safe_str(topic) or '-'}",
        f"webhook_id={_safe_str(webhook_id) or '-'}",
        f"shop_domain={_safe_str(shop_domain) or '-'}",
        f"order_id={_safe_str(order_id) or '-'}",
        f"event_id={_safe_str(event_id) or '-'}",
        f"client_id={_safe_str(client_id) or '-'}",
    ]

    if duplicate is not None:
        parts.append(f"duplicate={'1' if duplicate else '0'}")
    if queued is not None:
        parts.append(f"queued={'1' if queued else '0'}")
    if duration_ms is not None:
        parts.append(f"duration_ms={duration_ms}")
    if error_type:
        parts.append(f"error_type={_safe_str(error_type)}")
    if error_message:
        parts.append(f"error={_clip(error_message, 500) or '-'}")
    if details:
        compact_details: Dict[str, Any] = {}
        for key, value in details.items():
            if value is None or value == "" or value is False:
                continue
            if isinstance(value, (list, dict)) and not value:
                continue
            compact_details[key] = value
        if compact_details:
            parts.append(f"details={json.dumps(compact_details, ensure_ascii=False, sort_keys=True)}")

    print("[shopify][event] " + " ".join(parts))


def _shopify_secret() -> str:
    ensure_env_loaded()
    secret = _env("SHOPIFY_APP_SECRET")
    if len(secret) < 8:
        raise RuntimeError("SHOPIFY_APP_SECRET não configurado.")
    return secret


def get_shopify_client_id() -> str:
    return get_default_client_id()


def _shopify_secret_debug(secret: str) -> Dict[str, Any]:
    return {
        "secret_configured": bool(secret),
        "secret_len": len(secret),
    }


def validate_shopify_hmac(raw_body: bytes, provided_hmac: Optional[str]) -> Tuple[bool, str, Dict[str, Any]]:
    header_hmac = _safe_str(provided_hmac)
    secret = _shopify_secret()
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    computed_hmac = base64.b64encode(digest).decode("utf-8")
    is_valid = bool(header_hmac) and hmac.compare_digest(computed_hmac, header_hmac)
    return is_valid, computed_hmac, _shopify_secret_debug(secret)


def validate_shopify_shop_domain(shop_domain: Optional[str]) -> bool:
    domain = _normalize_shop_domain(shop_domain)
    if not domain.endswith(".myshopify.com"):
        return False
    label = domain.removesuffix(".myshopify.com")
    return bool(label) and all(char.isalnum() or char == "-" for char in label)


def decode_shopify_webhook_payload(raw_body: bytes) -> Dict[str, Any]:
    try:
        text = raw_body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("Payload Shopify inválido: UTF-8 não pôde ser lido.") from exc

    if not text.strip():
        return {}

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Payload Shopify inválido: JSON malformado.") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("Payload Shopify inválido: esperado um objeto JSON.")

    return payload


async def _find_webhook_event(client_id: str, webhook_id: Optional[str]) -> Optional[Dict[str, Any]]:
    resolved_webhook_id = _safe_str(webhook_id)
    if not resolved_webhook_id:
        return None

    return await sb_get_one_by(
        "shopify_webhook_events",
        filters={
            "client_id": f"eq.{client_id}",
            "webhook_id": f"eq.{resolved_webhook_id}",
        },
    )


async def register_shopify_webhook_event(
    *,
    client_id: str,
    webhook_id: Optional[str],
    topic: str,
    shop_domain: str,
    payload_json: Dict[str, Any],
) -> Tuple[Dict[str, Any], bool]:
    existing = await _find_webhook_event(client_id, webhook_id)
    if existing:
        return existing, True

    row = {
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "webhook_id": _safe_str(webhook_id) or None,
        "topic": _safe_str(topic),
        "shop_domain": _normalize_shop_domain(shop_domain),
        "payload_json": payload_json,
        "received_at": _iso_now(),
        "processed_at": None,
        "status": "received",
        "error_message": None,
    }

    try:
        inserted = await sb_insert(
            "shopify_webhook_events",
            row,
            returning="representation",
        )
        return inserted or row, False
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 409 and _safe_str(webhook_id):
            existing = await _find_webhook_event(client_id, webhook_id)
            if existing:
                return existing, True
        raise


async def mark_shopify_webhook_processing(event_id: str) -> None:
    await sb_update(
        "shopify_webhook_events",
        filters={"id": f"eq.{_safe_str(event_id)}"},
        patch={
            "status": "processing",
            "processed_at": None,
            "error_message": None,
        },
        returning="minimal",
    )


async def _mark_shopify_webhook_status(
    event_id: str,
    *,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    patch: Dict[str, Any] = {
        "status": status,
        "error_message": _clip(error_message),
    }
    if status in {"processed", "ignored", "error"}:
        patch["processed_at"] = _iso_now()

    await sb_update(
        "shopify_webhook_events",
        filters={"id": f"eq.{_safe_str(event_id)}"},
        patch=patch,
        returning="minimal",
    )


def _build_customer_row(*, client_id: str, shop_domain: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    customer_id = _safe_id(payload.get("id"))
    if not customer_id:
        return None
    return {
        "client_id": client_id,
        "shop_domain": _normalize_shop_domain(shop_domain),
        "shopify_customer_id": customer_id,
        "email": _safe_str(payload.get("email")) or None,
        "first_name": _safe_str(payload.get("first_name")) or None,
        "last_name": _safe_str(payload.get("last_name")) or None,
        "phone": _safe_str(payload.get("phone")) or None,
        "orders_count": _safe_int(payload.get("orders_count"), 0),
        "total_spent": _safe_money(payload.get("total_spent")),
        "state": _safe_str(payload.get("state")) or None,
        "created_at_shopify": payload.get("created_at"),
        "updated_at_shopify": payload.get("updated_at"),
        "raw_payload": payload,
    }


async def _upsert_customer(
    *,
    client_id: str,
    shop_domain: str,
    payload: Dict[str, Any],
) -> Optional[str]:
    row = _build_customer_row(client_id=client_id, shop_domain=shop_domain, payload=payload)
    if not row:
        return None
    await sb_upsert(
        "shopify_customers",
        [row],
        on_conflict="client_id,shopify_customer_id",
    )
    return row["shopify_customer_id"]


def _chunked(items: List[Any], size: int) -> List[List[Any]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _customer_row_recency(row: Dict[str, Any]) -> tuple[datetime, datetime]:
    minimum = datetime.min.replace(tzinfo=timezone.utc)
    updated = _parse_shopify_timestamp(row.get("updated_at_shopify")) or minimum
    created = _parse_shopify_timestamp(row.get("created_at_shopify")) or minimum
    return updated, created


def _deduplicate_customer_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplica pela constraint real UNIQUE(client_id, shopify_customer_id).

    Mantém a versão Shopify mais recente; em empate, a última ocorrência do
    payload vence de forma determinística.
    """
    unique: Dict[tuple[str, str], Dict[str, Any]] = {}
    for row in rows:
        key = (_safe_str(row.get("client_id")), _safe_str(row.get("shopify_customer_id")))
        current = unique.get(key)
        if current is None or _customer_row_recency(row) >= _customer_row_recency(current):
            unique[key] = row
    return list(unique.values())


async def upsert_customers_batch(
    *,
    client_id: str,
    shop_domain: str,
    payloads: List[Dict[str, Any]],
    chunk_size: int = 100,
) -> Dict[str, int]:
    """Upsert em lote — uma chamada por chunk em vez de uma por cliente.
    Reduz dezenas/centenas de round-trips individuais (o gargalo real
    observado em produção) para poucas chamadas. Se um chunk inteiro
    falhar (registro com formato inesperado no meio do lote), cai para
    upsert individual DENTRO do chunk só para isolar o(s) registro(s)
    problemático(s) — nunca perde os demais do mesmo chunk."""
    rows = [
        row for row in (
            _build_customer_row(client_id=client_id, shop_domain=shop_domain, payload=payload)
            for payload in payloads
        )
        if row is not None
    ]
    unique_rows = _deduplicate_customer_rows(rows)
    duplicates_removed = len(rows) - len(unique_rows)
    chunks = _chunked(unique_rows, max(1, int(chunk_size or 100)))
    upserted = 0
    failed = 0
    for chunk_index, chunk in enumerate(chunks, start=1):
        try:
            await sb_upsert("shopify_customers", chunk, on_conflict="client_id,shopify_customer_id")
            upserted += len(chunk)
        except Exception as chunk_exc:
            print(
                "[shopify_sync] stage=customers_chunk_fallback "
                f"chunk={chunk_index}/{len(chunks)} rows={len(chunk)} "
                f"error_type={chunk_exc.__class__.__name__}"
            )
            for row in chunk:
                try:
                    await sb_upsert("shopify_customers", [row], on_conflict="client_id,shopify_customer_id")
                    upserted += 1
                except Exception as row_exc:
                    failed += 1
                    print(
                        "[shopify_sync] stage=customer_persistence_error "
                        f"chunk={chunk_index}/{len(chunks)} customer_id={row.get('shopify_customer_id')} "
                        f"error_type={row_exc.__class__.__name__}"
                    )
    return {
        "received": len(payloads),
        "unique": len(unique_rows),
        "duplicates_removed": duplicates_removed,
        "chunks": len(chunks),
        "upserted": upserted,
        "failed": failed,
    }


async def _upsert_order(
    *,
    client_id: str,
    shop_domain: str,
    payload: Dict[str, Any],
) -> str:
    order_id = _safe_id(payload.get("id"))
    if not order_id:
        raise RuntimeError("Webhook de pedido sem id da Shopify.")

    # Guarda de ordenação: um webhook mais antigo entregue depois de um mais
    # novo (reentrega, fora de ordem) nunca pode sobrescrever o estado mais
    # recente já persistido para o mesmo pedido.
    incoming_updated_at = _parse_shopify_timestamp(payload.get("updated_at"))
    if incoming_updated_at is not None:
        existing = await sb_get_one_by(
            "shopify_orders",
            filters={"client_id": f"eq.{client_id}", "shopify_order_id": f"eq.{order_id}"},
            select="updated_at_shopify",
        )
        existing_updated_at = _parse_shopify_timestamp((existing or {}).get("updated_at_shopify"))
        if existing_updated_at is not None and incoming_updated_at < existing_updated_at:
            return order_id

    customer_payload = _safe_json(payload.get("customer"))
    customer_id = _safe_id(customer_payload.get("id")) or _safe_id(payload.get("customer_id"))

    row = {
        "client_id": client_id,
        "shop_domain": _normalize_shop_domain(shop_domain),
        "shopify_order_id": order_id,
        "order_number": _safe_str(payload.get("order_number")) or None,
        "name": _safe_str(payload.get("name")) or None,
        "email": _safe_str(payload.get("email")) or _safe_str(customer_payload.get("email")) or None,
        "customer_id": customer_id,
        "currency": _safe_str(payload.get("currency")) or None,
        "financial_status": _safe_str(payload.get("financial_status")) or None,
        "fulfillment_status": _safe_str(payload.get("fulfillment_status")) or None,
        "subtotal_price": _pick_money(payload, "subtotal_price_set", "subtotal_price"),
        "total_discounts": _pick_money(payload, "total_discounts_set", "total_discounts"),
        "total_shipping_price": _pick_money(
            payload,
            "total_shipping_price_set",
            "total_shipping_price",
            "current_total_shipping_price_set",
            "current_total_shipping_price",
        ),
        "total_price": _pick_money(
            payload,
            "total_price_set",
            "total_price",
            "current_total_price_set",
            "current_total_price",
        ),
        "total_tax": _pick_money(
            payload,
            "total_tax_set",
            "total_tax",
            "current_total_tax_set",
            "current_total_tax",
        ),
        "cancelled_at": payload.get("cancelled_at"),
        "cancel_reason": _safe_str(payload.get("cancel_reason")) or None,
        "created_at_shopify": payload.get("created_at"),
        "updated_at_shopify": payload.get("updated_at"),
        "raw_payload": payload,
    }

    await sb_upsert(
        "shopify_orders",
        [row],
        on_conflict="client_id,shopify_order_id",
    )
    return order_id


async def _upsert_order_items(
    *,
    client_id: str,
    shopify_order_id: str,
    payload: Dict[str, Any],
) -> int:
    line_items = payload.get("line_items") if isinstance(payload.get("line_items"), list) else []
    rows: List[Dict[str, Any]] = []

    for item in line_items:
        line_item = _safe_json(item)
        line_item_id = _safe_id(line_item.get("id"))
        if not line_item_id:
            continue

        rows.append(
            {
                "client_id": client_id,
                "shopify_order_id": shopify_order_id,
                "shopify_line_item_id": line_item_id,
                "product_id": _safe_id(line_item.get("product_id")),
                "variant_id": _safe_id(line_item.get("variant_id")),
                "sku": _safe_str(line_item.get("sku")) or None,
                "title": _safe_str(line_item.get("title")) or None,
                "variant_title": _safe_str(line_item.get("variant_title")) or None,
                "vendor": _safe_str(line_item.get("vendor")) or None,
                "quantity": _safe_int(line_item.get("quantity"), 0),
                "price": _pick_money(line_item, "price_set", "price"),
                "total_discount": _pick_money(line_item, "total_discount_set", "total_discount"),
                "raw_payload": line_item,
            }
        )

    if not rows:
        return 0

    await sb_upsert(
        "shopify_order_items",
        rows,
        on_conflict="client_id,shopify_line_item_id",
    )
    return len(rows)


def _refund_total(payload: Dict[str, Any]) -> Optional[float]:
    total = 0.0
    has_amount = False

    for transaction in payload.get("transactions") or []:
        tx = _safe_json(transaction)
        kind = _safe_str(tx.get("kind")).lower()
        if kind and kind not in {"refund", "suggested_refund"}:
            continue
        amount = _pick_money(tx, "amount_set", "amount")
        if amount is None:
            continue
        total += amount
        has_amount = True

    for adjustment in payload.get("order_adjustments") or []:
        item = _safe_json(adjustment)
        amount = _pick_money(item, "amount_set", "amount")
        if amount is None:
            continue
        total += amount
        has_amount = True

    if not has_amount:
        for refund_line in payload.get("refund_line_items") or []:
            item = _safe_json(refund_line)
            subtotal = _pick_money(item, "subtotal_set", "subtotal") or 0.0
            total_tax = _pick_money(item, "total_tax_set", "total_tax") or 0.0
            if subtotal or total_tax:
                total += subtotal + total_tax
                has_amount = True

    return total if has_amount else None


async def _upsert_refund(
    *,
    client_id: str,
    shop_domain: str,
    payload: Dict[str, Any],
) -> Tuple[str, Optional[str]]:
    refund_id = _safe_id(payload.get("id"))
    if not refund_id:
        raise RuntimeError("Webhook de refund sem id da Shopify.")

    order_id = _safe_id(payload.get("order_id"))

    row = {
        "client_id": client_id,
        "shop_domain": _normalize_shop_domain(shop_domain),
        "shopify_refund_id": refund_id,
        "shopify_order_id": order_id,
        "note": _safe_str(payload.get("note")) or None,
        "total_refunded": _refund_total(payload),
        "created_at_shopify": payload.get("created_at"),
        "raw_payload": payload,
    }

    await sb_upsert(
        "shopify_refunds",
        [row],
        on_conflict="client_id,shopify_refund_id",
    )
    return refund_id, order_id


async def _touch_order_after_refund(
    *,
    client_id: str,
    shopify_order_id: Optional[str],
    payload: Dict[str, Any],
) -> None:
    if not _safe_str(shopify_order_id):
        return

    patch: Dict[str, Any] = {
        "updated_at_shopify": payload.get("created_at") or _iso_now(),
    }
    financial_status = _safe_str(payload.get("financial_status")) or None
    if financial_status:
        patch["financial_status"] = financial_status

    await sb_update(
        "shopify_orders",
        filters={
            "client_id": f"eq.{client_id}",
            "shopify_order_id": f"eq.{_safe_str(shopify_order_id)}",
        },
        patch=patch,
        returning="minimal",
    )


async def _handle_order_topic(
    *,
    client_id: str,
    shop_domain: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    customer_payload = _safe_json(payload.get("customer"))
    customer_id = None
    if customer_payload and _safe_id(customer_payload.get("id")):
        customer_id = await _upsert_customer(
            client_id=client_id,
            shop_domain=shop_domain,
            payload=customer_payload,
        )

    order_id = await _upsert_order(
        client_id=client_id,
        shop_domain=shop_domain,
        payload=payload,
    )
    items_upserted = await _upsert_order_items(
        client_id=client_id,
        shopify_order_id=order_id,
        payload=payload,
    )
    return {
        "order_id": order_id,
        "customer_id": customer_id,
        "items_upserted": items_upserted,
    }


async def _handle_customer_topic(
    *,
    client_id: str,
    shop_domain: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    customer_id = await _upsert_customer(
        client_id=client_id,
        shop_domain=shop_domain,
        payload=payload,
    )
    if not customer_id:
        raise RuntimeError("Webhook de customer sem id da Shopify.")
    return {"customer_id": customer_id}


async def _handle_refund_topic(
    *,
    client_id: str,
    shop_domain: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    refund_id, order_id = await _upsert_refund(
        client_id=client_id,
        shop_domain=shop_domain,
        payload=payload,
    )

    nested_order = _safe_json(payload.get("order"))
    if nested_order and _safe_id(nested_order.get("id")):
        await _handle_order_topic(
            client_id=client_id,
            shop_domain=shop_domain,
            payload=nested_order,
        )
    else:
        await _touch_order_after_refund(
            client_id=client_id,
            shopify_order_id=order_id,
            payload=payload,
        )

    return {
        "refund_id": refund_id,
        "order_id": order_id,
    }


async def list_recent_shopify_webhooks(
    *,
    client_id: str,
    shop_domain: str | None = None,
    limit: int = 20,
    include_payload: bool = False,
) -> List[Dict[str, Any]]:
    resolved_limit = _normalize_limit(limit)
    select = "id,client_id,webhook_id,topic,shop_domain,received_at,processed_at,status,error_message,payload_json"
    filters = {"client_id": f"eq.{client_id}"}
    if _normalize_shop_domain(shop_domain):
        filters["shop_domain"] = f"eq.{_normalize_shop_domain(shop_domain)}"
    rows = await sb_select(
        "shopify_webhook_events",
        select=select,
        filters=filters,
        order="received_at.desc",
        limit=resolved_limit,
    )

    result: List[Dict[str, Any]] = []
    for row in rows:
        payload = _safe_json(row.get("payload_json"))
        item = {
            "id": row.get("id"),
            "client_id": row.get("client_id"),
            "webhook_id": row.get("webhook_id"),
            "topic": row.get("topic"),
            "shop_domain": _normalize_shop_domain(row.get("shop_domain")),
            "order_id": extract_shopify_order_id(_safe_str(row.get("topic")), payload),
            "received_at": row.get("received_at"),
            "processed_at": row.get("processed_at"),
            "status": row.get("status"),
            "error_message": row.get("error_message"),
        }
        if include_payload:
            item["payload_json"] = payload
        result.append(item)

    return result


async def list_recent_shopify_orders(
    *,
    client_id: str,
    shop_domain: str | None = None,
    limit: int = 20,
    include_raw: bool = False,
) -> List[Dict[str, Any]]:
    resolved_limit = _normalize_limit(limit)
    order_select = (
        "id,client_id,shopify_order_id,shop_domain,order_number,name,email,customer_id,currency,"
        "financial_status,fulfillment_status,subtotal_price,total_discounts,total_shipping_price,"
        "total_price,total_tax,cancelled_at,cancel_reason,created_at_shopify,updated_at_shopify,"
        "created_at,updated_at"
    )
    if include_raw:
        order_select += ",raw_payload"

    filters = {"client_id": f"eq.{client_id}"}
    if _normalize_shop_domain(shop_domain):
        filters["shop_domain"] = f"eq.{_normalize_shop_domain(shop_domain)}"
    orders = await sb_select(
        "shopify_orders",
        select=order_select,
        filters=filters,
        order="updated_at_shopify.desc",
        limit=resolved_limit,
    )
    if not orders:
        return []

    order_ids = [_safe_str(row.get("shopify_order_id")) for row in orders if _safe_str(row.get("shopify_order_id"))]
    customer_ids = [_safe_str(row.get("customer_id")) for row in orders if _safe_str(row.get("customer_id"))]

    items_by_order: Dict[str, List[Dict[str, Any]]] = {}
    items_filter = _postgrest_in_filter(order_ids)
    if items_filter:
        item_select = (
            "id,client_id,shopify_order_id,shopify_line_item_id,product_id,variant_id,sku,title,"
            "variant_title,vendor,quantity,price,total_discount,created_at,updated_at"
        )
        if include_raw:
            item_select += ",raw_payload"
        item_rows = await sb_select(
            "shopify_order_items",
            select=item_select,
            filters={
                "client_id": f"eq.{client_id}",
                "shopify_order_id": items_filter,
            },
            order="updated_at.desc",
            limit=max(len(order_ids) * 20, resolved_limit * 5),
        )
        for row in item_rows:
            order_id = _safe_str(row.get("shopify_order_id"))
            items_by_order.setdefault(order_id, []).append(row)

    customers_by_id: Dict[str, Dict[str, Any]] = {}
    customers_filter = _postgrest_in_filter(customer_ids)
    if customers_filter:
        customer_select = (
            "id,client_id,shopify_customer_id,shop_domain,email,first_name,last_name,phone,"
            "orders_count,total_spent,state,created_at_shopify,updated_at_shopify,created_at,updated_at"
        )
        if include_raw:
            customer_select += ",raw_payload"
        customer_rows = await sb_select(
            "shopify_customers",
            select=customer_select,
            filters={
                "client_id": f"eq.{client_id}",
                **(
                    {"shop_domain": f"eq.{_normalize_shop_domain(shop_domain)}"}
                    if _normalize_shop_domain(shop_domain)
                    else {}
                ),
                "shopify_customer_id": customers_filter,
            },
            order="updated_at.desc",
            limit=max(len(customer_ids), resolved_limit),
        )
        customers_by_id = {
            _safe_str(row.get("shopify_customer_id")): {
                **row,
                "shop_domain": _normalize_shop_domain(row.get("shop_domain")),
            }
            for row in customer_rows
            if _safe_str(row.get("shopify_customer_id"))
        }

    result: List[Dict[str, Any]] = []
    for row in orders:
        customer_id = _safe_str(row.get("customer_id"))
        order_id = _safe_str(row.get("shopify_order_id"))
        item_rows = items_by_order.get(order_id, [])
        enriched = dict(row)
        enriched["shop_domain"] = _normalize_shop_domain(enriched.get("shop_domain"))
        enriched["items_count"] = len(item_rows)
        enriched["order_items"] = item_rows
        enriched["customer"] = customers_by_id.get(customer_id)
        result.append(enriched)

    return result


async def process_shopify_webhook_event(
    *,
    event_id: str,
    client_id: str,
    topic: str,
    shop_domain: str,
    webhook_id: Optional[str],
    payload_json: Dict[str, Any],
) -> None:
    started = time.perf_counter()
    input_order_id = extract_shopify_order_id(topic, payload_json)

    try:
        _log_shopify_event(
            status="processing",
            topic=topic,
            webhook_id=webhook_id,
            shop_domain=shop_domain,
            order_id=input_order_id,
            event_id=event_id,
            client_id=client_id,
        )

        if topic not in SUPPORTED_SHOPIFY_TOPICS:
            await _mark_shopify_webhook_status(
                event_id,
                status="ignored",
                error_message=f"Tópico sem handler: {topic}",
            )
            _log_shopify_event(
                status="ignored",
                topic=topic,
                webhook_id=webhook_id,
                shop_domain=shop_domain,
                order_id=input_order_id,
                event_id=event_id,
                client_id=client_id,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            return

        if topic.startswith("orders/"):
            result = await _handle_order_topic(
                client_id=client_id,
                shop_domain=shop_domain,
                payload=payload_json,
            )
        elif topic.startswith("customers/"):
            result = await _handle_customer_topic(
                client_id=client_id,
                shop_domain=shop_domain,
                payload=payload_json,
            )
        elif topic == "refunds/create":
            result = await _handle_refund_topic(
                client_id=client_id,
                shop_domain=shop_domain,
                payload=payload_json,
            )
        else:
            result = {"ignored": True}

        if topic.startswith("orders/") or topic == "refunds/create":
            order_payload = payload_json if topic.startswith("orders/") else _safe_json(payload_json.get("order"))
            order_date = _safe_str(order_payload.get("created_at"))[:10]
            if not order_date and topic == "refunds/create" and input_order_id:
                persisted_order = await sb_get_one_by(
                    "shopify_orders",
                    filters={"client_id": f"eq.{client_id}", "shopify_order_id": f"eq.{input_order_id}"},
                    select="created_at_shopify",
                )
                order_date = _safe_str((persisted_order or {}).get("created_at_shopify"))[:10]
            if len(order_date) == 10:
                from .dashboard_read_model import refresh_dashboard_read_model_safely
                await refresh_dashboard_read_model_safely(
                    client_id=client_id,
                    start=order_date,
                    end=order_date,
                    provider="shopify",
                )

        await _mark_shopify_webhook_status(event_id, status="processed")
        _log_shopify_event(
            status="processed",
            topic=topic,
            webhook_id=webhook_id,
            shop_domain=shop_domain,
            order_id=_safe_id(result.get("order_id")) or input_order_id,
            event_id=event_id,
            client_id=client_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
            details=result,
        )
    except Exception as exc:
        await _mark_shopify_webhook_status(
            event_id,
            status="error",
            error_message=str(exc),
        )
        _log_shopify_event(
            status="error",
            topic=topic,
            webhook_id=webhook_id,
            shop_domain=shop_domain,
            order_id=input_order_id,
            event_id=event_id,
            client_id=client_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error_type=exc.__class__.__name__,
            error_message=str(exc),
        )
        print(traceback.format_exc())
