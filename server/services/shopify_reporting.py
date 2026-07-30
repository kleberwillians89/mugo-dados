from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

import httpx

from .ig_supabase import _is_column_compat_error, sb_select
from .shopify_webhooks import list_recent_shopify_webhooks


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _normalize_shop_domain(value: Any) -> str:
    return _safe_str(value).lower()


def _safe_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        if value is None or value == "":
            return 0
        return int(value)
    except Exception:
        return 0


def _safe_json(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _parse_date_input(value: Optional[str]) -> Optional[date]:
    text = _safe_str(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_shopify_datetime(value: Any) -> Optional[datetime]:
    text = _safe_str(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_start_of_day(day: date) -> str:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc).isoformat()


def _iso_end_of_day(day: date) -> str:
    return datetime(day.year, day.month, day.day, 23, 59, 59, 999999, tzinfo=timezone.utc).isoformat()


def _period_days(start: date, end: date) -> int:
    return max(1, (end - start).days + 1)


@dataclass(frozen=True)
class ShopifyReportPeriod:
    start: date
    end: date
    days: int


def resolve_shopify_report_period(
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    days: int = 30,
) -> ShopifyReportPeriod:
    start_date = _parse_date_input(start)
    end_date = _parse_date_input(end)
    safe_days = max(1, min(int(days or 30), 366))

    if start_date and end_date:
        if start_date <= end_date:
            return ShopifyReportPeriod(start=start_date, end=end_date, days=_period_days(start_date, end_date))
        return ShopifyReportPeriod(start=end_date, end=start_date, days=_period_days(end_date, start_date))

    today = datetime.now(timezone.utc).date()
    period_end = end_date or today
    period_start = start_date or (period_end - timedelta(days=safe_days - 1))
    if period_start > period_end:
        period_start, period_end = period_end, period_start
    return ShopifyReportPeriod(start=period_start, end=period_end, days=_period_days(period_start, period_end))


def _postgrest_in_filter(values: Iterable[str]) -> Optional[str]:
    cleaned = [_safe_str(value) for value in values if _safe_str(value)]
    if not cleaned:
        return None

    escaped = ",".join(json.dumps(value) for value in cleaned)
    return f"in.({escaped})"


def _order_date_key(order: Dict[str, Any]) -> Optional[str]:
    parsed = _parse_shopify_datetime(order.get("created_at_shopify"))
    if not parsed:
        return None
    return parsed.date().isoformat()


def _customer_identity(order: Dict[str, Any]) -> str:
    customer_id = _safe_str(order.get("customer_id"))
    if customer_id:
        return f"id:{customer_id}"
    email = _safe_str(order.get("email")).lower()
    if email:
        return f"email:{email}"
    return f"order:{_safe_str(order.get('shopify_order_id'))}"


def _customer_display_name(customer: Optional[Dict[str, Any]], order: Dict[str, Any]) -> str:
    customer_payload = _safe_json(customer)
    first_name = _safe_str(customer_payload.get("first_name"))
    last_name = _safe_str(customer_payload.get("last_name"))
    full_name = " ".join([part for part in [first_name, last_name] if part]).strip()
    if full_name:
        return full_name
    email = _safe_str(customer_payload.get("email")) or _safe_str(order.get("email"))
    if email:
        return email
    return "Cliente não identificado"


def _financial_status_label(value: Any) -> str:
    status = _safe_str(value).lower()
    if not status:
        return "unknown"
    return status


def _is_cancelled_order(order: Dict[str, Any]) -> bool:
    return bool(_safe_str(order.get("cancelled_at")) or _safe_str(order.get("cancel_reason")))


def _order_total_price(order: Dict[str, Any]) -> float:
    return max(0.0, _safe_float(order.get("total_price")))


def _customer_lookup_key(customer_id: Any, email: Any) -> str:
    resolved_customer_id = _safe_str(customer_id)
    if resolved_customer_id:
        return f"id:{resolved_customer_id}"
    resolved_email = _safe_str(email).lower()
    if resolved_email:
        return f"email:{resolved_email}"
    return ""


def _dedupe_orders(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    ordered: List[Dict[str, Any]] = []
    for row in rows:
        order_key = _safe_str(row.get("shopify_order_id")) or _safe_str(row.get("id"))
        if not order_key or order_key in seen:
            continue
        seen.add(order_key)
        ordered.append(row)
    return ordered


def _shopify_customer_name(customer: Optional[Dict[str, Any]], order: Optional[Dict[str, Any]] = None) -> str:
    customer_payload = _safe_json(customer)
    first_name = _safe_str(customer_payload.get("first_name"))
    last_name = _safe_str(customer_payload.get("last_name"))
    full_name = " ".join([part for part in [first_name, last_name] if part]).strip()
    if full_name:
        return full_name
    if order:
        fallback_name = _safe_str(order.get("name"))
        if fallback_name:
            return fallback_name
    email = _safe_str(customer_payload.get("email")) or _safe_str((order or {}).get("email"))
    if email:
        return email
    return "Cliente não identificado"


def _build_customer_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    recurring_count = sum(1 for row in rows if _safe_str(row.get("status")) == "recurring")
    multi_order_count = sum(1 for row in rows if _safe_int(row.get("total_orders")) > 1)
    top_customer = rows[0] if rows else None
    return {
        "total_customers": len(rows),
        "recurring_customers": recurring_count,
        "multi_order_customers": multi_order_count,
        "top_customer": (
            {
                "name": top_customer.get("name"),
                "email": top_customer.get("email"),
                "total_spent": round(_safe_float(top_customer.get("total_spent")), 2),
                "total_orders": _safe_int(top_customer.get("total_orders")),
                "status": top_customer.get("status"),
            }
            if top_customer
            else None
        ),
    }


async def _select_shopify_refunds(
    *,
    client_id: str,
    period: ShopifyReportPeriod,
) -> List[Dict[str, Any]]:
    period_filter = (
        f"(created_at_shopify.gte.{_iso_start_of_day(period.start)},"
        f"created_at_shopify.lte.{_iso_end_of_day(period.end)})"
    )

    try:
        return await sb_select(
            "shopify_refunds",
            select="id,shopify_refund_id,shopify_order_id,total_refunded,created_at_shopify,shop_domain,note",
            filters={
                "client_id": f"eq.{client_id}",
                "and": period_filter,
            },
            order="created_at_shopify.desc",
            limit=500,
        )
    except httpx.HTTPStatusError as exc:
        if not (_is_column_compat_error(exc, "shop_domain") or _is_column_compat_error(exc, "note")):
            raise
        fallback_rows = await sb_select(
            "shopify_refunds",
            select="id,shopify_refund_id,shopify_order_id,total_refunded,created_at_shopify",
            filters={
                "client_id": f"eq.{client_id}",
                "and": period_filter,
            },
            order="created_at_shopify.desc",
            limit=500,
        )
        return [
            {
                **row,
                "shop_domain": "",
                "note": None,
            }
            for row in fallback_rows
        ]


def _build_daily_trends(period: ShopifyReportPeriod, orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}
    for offset in range(period.days):
        day = period.start + timedelta(days=offset)
        key = day.isoformat()
        buckets[key] = {
            "date": key,
            "revenue": 0.0,
            "orders": 0,
            "customers": set(),
            "average_ticket": 0.0,
        }

    for order in orders:
        key = _order_date_key(order)
        if not key or key not in buckets:
            continue
        bucket = buckets[key]
        bucket["revenue"] += _safe_float(order.get("total_price"))
        bucket["orders"] += 1
        bucket["customers"].add(_customer_identity(order))

    trends: List[Dict[str, Any]] = []
    for key in sorted(buckets.keys()):
        bucket = buckets[key]
        orders_count = int(bucket["orders"])
        revenue = float(bucket["revenue"])
        trends.append(
            {
                "date": key,
                "revenue": round(revenue, 2),
                "orders": orders_count,
                "customers": len(bucket["customers"]),
                "average_ticket": round(revenue / orders_count, 2) if orders_count else 0.0,
            }
        )
    return trends


def _aggregate_top_products(order_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for item in order_items:
        line_item_id = _safe_str(item.get("shopify_line_item_id"))
        title = _safe_str(item.get("title")) or "Produto sem título"
        variant_title = _safe_str(item.get("variant_title"))
        vendor = _safe_str(item.get("vendor"))
        product_id = _safe_str(item.get("product_id"))
        variant_id = _safe_str(item.get("variant_id"))
        key = product_id or f"{title}|{variant_title}|{vendor}|{line_item_id}"

        revenue = max(0.0, (_safe_float(item.get("price")) * _safe_int(item.get("quantity"))) - _safe_float(item.get("total_discount")))
        entry = grouped.setdefault(
            key,
            {
                "product_id": product_id or None,
                "variant_id": variant_id or None,
                "title": title,
                "variant_title": variant_title or None,
                "vendor": vendor or None,
                "quantity_sold": 0,
                "revenue": 0.0,
            },
        )
        entry["quantity_sold"] += _safe_int(item.get("quantity"))
        entry["revenue"] += revenue

    ranked = sorted(
        grouped.values(),
        key=lambda row: (_safe_int(row.get("quantity_sold")), _safe_float(row.get("revenue"))),
        reverse=True,
    )
    return [
        {
            **row,
            "revenue": round(_safe_float(row.get("revenue")), 2),
        }
        for row in ranked[:8]
    ]


def _build_recent_orders(
    orders: List[Dict[str, Any]],
    items_by_order: Dict[str, List[Dict[str, Any]]],
    customers_by_id: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for order in orders[:10]:
        order_id = _safe_str(order.get("shopify_order_id"))
        items = items_by_order.get(order_id, [])
        customer = customers_by_id.get(_safe_str(order.get("customer_id")))
        rows.append(
            {
                "id": order.get("id"),
                "shopify_order_id": order_id,
                "order_number": order.get("order_number"),
                "name": order.get("name"),
                "customer_name": _customer_display_name(customer, order),
                "customer_email": _safe_str((customer or {}).get("email")) or _safe_str(order.get("email")) or None,
                "financial_status": _financial_status_label(order.get("financial_status")),
                "fulfillment_status": _financial_status_label(order.get("fulfillment_status")) or None,
                "total_price": round(_safe_float(order.get("total_price")), 2),
                "currency": _safe_str(order.get("currency")) or "BRL",
                "created_at_shopify": order.get("created_at_shopify"),
                "updated_at_shopify": order.get("updated_at_shopify"),
                "items_count": len(items),
                "shop_domain": _normalize_shop_domain(order.get("shop_domain")),
            }
        )
    return rows


async def build_shopify_report(
    *,
    client_id: str,
    period: ShopifyReportPeriod,
) -> Dict[str, Any]:
    period_filter = (
        f"(created_at_shopify.gte.{_iso_start_of_day(period.start)},"
        f"created_at_shopify.lte.{_iso_end_of_day(period.end)})"
    )
    orders = await sb_select(
        "shopify_orders",
        select=(
            "id,client_id,shopify_order_id,shop_domain,order_number,name,email,customer_id,currency,"
            "financial_status,fulfillment_status,subtotal_price,total_discounts,total_shipping_price,"
            "total_price,total_tax,cancelled_at,cancel_reason,created_at_shopify,updated_at_shopify"
        ),
        filters={
            "client_id": f"eq.{client_id}",
            "and": period_filter,
        },
        order="created_at_shopify.desc",
        limit=5000,
    )

    order_ids = [_safe_str(order.get("shopify_order_id")) for order in orders if _safe_str(order.get("shopify_order_id"))]
    customer_ids = [_safe_str(order.get("customer_id")) for order in orders if _safe_str(order.get("customer_id"))]

    items_by_order: Dict[str, List[Dict[str, Any]]] = {}
    if order_ids:
        items_filter = _postgrest_in_filter(order_ids)
        if items_filter:
            order_items = await sb_select(
                "shopify_order_items",
                select=(
                    "id,client_id,shopify_order_id,shopify_line_item_id,product_id,variant_id,sku,title,"
                    "variant_title,vendor,quantity,price,total_discount"
                ),
                filters={
                    "client_id": f"eq.{client_id}",
                    "shopify_order_id": items_filter,
                },
                order="updated_at.desc",
                limit=max(len(order_ids) * 20, 100),
            )
            for item in order_items:
                order_id = _safe_str(item.get("shopify_order_id"))
                items_by_order.setdefault(order_id, []).append(item)
    else:
        order_items = []

    customers_by_id: Dict[str, Dict[str, Any]] = {}
    if customer_ids:
        customers_filter = _postgrest_in_filter(customer_ids)
        if customers_filter:
            customer_rows = await sb_select(
                "shopify_customers",
                select=(
                    "id,client_id,shopify_customer_id,shop_domain,email,first_name,last_name,phone,"
                    "orders_count,total_spent,state,created_at_shopify,updated_at_shopify"
                ),
                filters={
                    "client_id": f"eq.{client_id}",
                    "shopify_customer_id": customers_filter,
                },
                order="updated_at_shopify.desc",
                limit=max(len(customer_ids), 50),
            )
            customers_by_id = {
                _safe_str(row.get("shopify_customer_id")): row
                for row in customer_rows
                if _safe_str(row.get("shopify_customer_id"))
            }

    refunds = await _select_shopify_refunds(client_id=client_id, period=period)

    revenue_total = sum(
        _safe_float(order.get("total_price"))
        for order in orders
        if not _safe_str(order.get("cancelled_at"))
    )
    orders_count = len(orders)
    customer_keys = {_customer_identity(order) for order in orders}
    paid_orders_count = sum(
        1
        for order in orders
        if _financial_status_label(order.get("financial_status")) in {"paid", "partially_paid"}
    )
    cancelled_orders_count = sum(
        1 for order in orders if _safe_str(order.get("cancelled_at")) or _safe_str(order.get("cancel_reason"))
    )
    refunds_count = len(refunds)
    refunded_amount = sum(_safe_float(refund.get("total_refunded")) for refund in refunds)

    recent_webhooks = await list_recent_shopify_webhooks(client_id=client_id, limit=8, include_payload=False)
    processed_webhooks = [item for item in recent_webhooks if _safe_str(item.get("status")).lower() == "processed"]
    error_webhooks = [item for item in recent_webhooks if _safe_str(item.get("status")).lower() == "error"]

    shop_domain = ""
    if orders:
        shop_domain = _normalize_shop_domain(orders[0].get("shop_domain"))
    elif recent_webhooks:
        shop_domain = _normalize_shop_domain(recent_webhooks[0].get("shop_domain"))

    return {
        "ok": True,
        "client_id": client_id,
        "shop_domain": shop_domain,
        "period": {
            "start": period.start.isoformat(),
            "end": period.end.isoformat(),
            "days": period.days,
        },
        "summary": {
            "revenue_total": round(revenue_total, 2),
            "orders": orders_count,
            "average_ticket": round(revenue_total / orders_count, 2) if orders_count else 0.0,
            "customers": len(customer_keys),
            "paid_orders": paid_orders_count,
            "cancelled_orders": cancelled_orders_count,
            "refunds_count": refunds_count,
            "refunded_amount": round(refunded_amount, 2),
        },
        "trends": {
            "daily": _build_daily_trends(period, orders),
        },
        "recent_orders": _build_recent_orders(orders, items_by_order, customers_by_id),
        "top_products": _aggregate_top_products(order_items),
        "technical": {
            "last_success_at": processed_webhooks[0]["processed_at"] if processed_webhooks else None,
            "last_received_at": recent_webhooks[0]["received_at"] if recent_webhooks else None,
            "processed_count": len(processed_webhooks),
            "error_count": len(error_webhooks),
            "recent_errors": error_webhooks[:3],
            "recent_webhooks": recent_webhooks,
        },
    }


async def build_shopify_customers_report(
    *,
    client_id: str,
    period: ShopifyReportPeriod,
) -> Dict[str, Any]:
    period_filter = (
        f"(created_at_shopify.gte.{_iso_start_of_day(period.start)},"
        f"created_at_shopify.lte.{_iso_end_of_day(period.end)})"
    )
    period_orders = await sb_select(
        "shopify_orders",
        select=(
            "id,client_id,shop_domain,shopify_order_id,name,email,customer_id,financial_status,"
            "total_price,cancelled_at,cancel_reason,created_at_shopify,updated_at_shopify"
        ),
        filters={
            "client_id": f"eq.{client_id}",
            "and": period_filter,
        },
        order="created_at_shopify.desc",
        limit=5000,
    )

    qualifying_orders = [order for order in period_orders if _customer_lookup_key(order.get("customer_id"), order.get("email"))]
    customer_ids = sorted({
        _safe_str(order.get("customer_id"))
        for order in qualifying_orders
        if _safe_str(order.get("customer_id"))
    })
    customer_emails = sorted({
        _safe_str(order.get("email")).lower()
        for order in qualifying_orders
        if _safe_str(order.get("email"))
    })

    customers_by_id: Dict[str, Dict[str, Any]] = {}
    if customer_ids:
        customer_rows = await sb_select(
            "shopify_customers",
            select=(
                "id,client_id,shopify_customer_id,shop_domain,email,first_name,last_name,phone,"
                "orders_count,total_spent,state,created_at_shopify,updated_at_shopify"
            ),
            filters={
                "client_id": f"eq.{client_id}",
                "shopify_customer_id": _postgrest_in_filter(customer_ids),
            },
            order="updated_at_shopify.desc",
            limit=max(100, len(customer_ids)),
        )
        customers_by_id = {
            _safe_str(row.get("shopify_customer_id")): row
            for row in customer_rows
            if _safe_str(row.get("shopify_customer_id"))
        }

    all_time_orders: List[Dict[str, Any]] = []
    if customer_ids:
        all_time_orders.extend(
            await sb_select(
                "shopify_orders",
                select=(
                    "shopify_order_id,shop_domain,name,email,customer_id,total_price,cancelled_at,"
                    "cancel_reason,created_at_shopify,updated_at_shopify"
                ),
                filters={
                    "client_id": f"eq.{client_id}",
                    "customer_id": _postgrest_in_filter(customer_ids),
                },
                order="created_at_shopify.asc",
                limit=10000,
            )
        )

    if customer_emails:
        all_time_orders.extend(
            await sb_select(
                "shopify_orders",
                select=(
                    "shopify_order_id,shop_domain,name,email,customer_id,total_price,cancelled_at,"
                    "cancel_reason,created_at_shopify,updated_at_shopify"
                ),
                filters={
                    "client_id": f"eq.{client_id}",
                    "email": _postgrest_in_filter(customer_emails),
                },
                order="created_at_shopify.asc",
                limit=10000,
            )
        )

    all_time_orders = _dedupe_orders(all_time_orders)

    grouped: Dict[str, Dict[str, Any]] = {}
    for order in qualifying_orders:
        key = _customer_lookup_key(order.get("customer_id"), order.get("email"))
        if not key:
            continue
        customer = customers_by_id.get(_safe_str(order.get("customer_id")))
        entry = grouped.setdefault(
            key,
            {
                "customer_key": key,
                "shopify_customer_id": _safe_str(order.get("customer_id")) or None,
                "name": _shopify_customer_name(customer, order),
                "email": _safe_str((customer or {}).get("email")) or _safe_str(order.get("email")) or None,
                "shop_domain": _normalize_shop_domain((customer or {}).get("shop_domain") or order.get("shop_domain")),
                "total_orders": 0,
                "total_spent": 0.0,
                "average_ticket": 0.0,
                "first_purchase_at": None,
                "last_purchase_at": None,
                "status": "new",
                "all_time_orders": 0,
            },
        )

        if _is_cancelled_order(order):
            continue

        entry["total_orders"] += 1
        entry["total_spent"] += _order_total_price(order)

    for order in all_time_orders:
        key = _customer_lookup_key(order.get("customer_id"), order.get("email"))
        if not key or key not in grouped:
            continue

        entry = grouped[key]
        if _is_cancelled_order(order):
            continue

        created_at = order.get("created_at_shopify")
        created_at_dt = _parse_shopify_datetime(created_at)
        first_dt = _parse_shopify_datetime(entry.get("first_purchase_at"))
        last_dt = _parse_shopify_datetime(entry.get("last_purchase_at"))
        entry["all_time_orders"] += 1
        if created_at_dt and (not first_dt or created_at_dt < first_dt):
            entry["first_purchase_at"] = created_at
        if created_at_dt and (not last_dt or created_at_dt > last_dt):
            entry["last_purchase_at"] = created_at

    rows: List[Dict[str, Any]] = []
    for entry in grouped.values():
        total_orders = _safe_int(entry.get("total_orders"))
        all_time_orders_count = max(
            _safe_int(entry.get("all_time_orders")),
            _safe_int(_safe_json(customers_by_id.get(_safe_str(entry.get("shopify_customer_id")))).get("orders_count")),
        )
        rows.append(
            {
                **entry,
                "total_spent": round(_safe_float(entry.get("total_spent")), 2),
                "average_ticket": round(
                    _safe_float(entry.get("total_spent")) / total_orders, 2
                ) if total_orders else 0.0,
                "status": "recurring" if all_time_orders_count > 1 else "new",
                "all_time_orders": all_time_orders_count,
            }
        )

    rows = sorted(
        rows,
        key=lambda row: (
            _safe_float(row.get("total_spent")),
            _safe_int(row.get("total_orders")),
            _safe_str(row.get("last_purchase_at")),
        ),
        reverse=True,
    )

    return {
        "ok": True,
        "client_id": client_id,
        "period": {
            "start": period.start.isoformat(),
            "end": period.end.isoformat(),
            "days": period.days,
        },
        "count": len(rows),
        "summary": _build_customer_summary(rows),
        "items": rows,
    }
