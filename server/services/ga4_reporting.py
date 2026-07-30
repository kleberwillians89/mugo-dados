from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from .ig_supabase import sb_select
from .single_tenant import resolve_ga4_context_for_client

GA4_EVENT_GROUPS: Dict[str, Dict[str, Any]] = {
    "behavior": {
        "title": "Navegação e comércio",
        "description": "Como o visitante percorre listas, produtos e carrinho antes de avançar no funil.",
        "events": ("view_item_list", "select_item", "view_cart", "remove_from_cart"),
    },
    "merchandising": {
        "title": "Merchandising e intenção",
        "description": "Leitura dos gatilhos de vitrine e das interações com destaques comerciais do site.",
        "events": ("view_promotion", "buy_now_click"),
    },
    "engagement": {
        "title": "Engajamento de navegação",
        "description": "Sinais de atenção e profundidade de consumo do conteúdo durante a sessão.",
        "events": ("page_time_30s", "scroll_depth"),
    },
}

GA4_EVENT_LABELS: Dict[str, str] = {
    "view_item": "Visualizou produto",
    "add_to_cart": "Adicionou ao carrinho",
    "begin_checkout": "Iniciou checkout",
    "add_payment_info": "Informou pagamento",
    "purchase": "Comprou",
    "view_item_list": "Visualizou lista de produtos",
    "select_item": "Selecionou produto da lista",
    "view_cart": "Visualizou carrinho",
    "remove_from_cart": "Removeu do carrinho",
    "view_promotion": "Visualizou promoção",
    "buy_now_click": "Clicou em comprar agora",
    "page_time_30s": "Permaneceu 30s na página",
    "scroll_depth": "Atingiu profundidade de scroll",
}

GA4_EVENT_DESCRIPTIONS: Dict[str, str] = {
    "view_item": "Base do funil comercial, indicando interesse em produto.",
    "add_to_cart": "Sinal de intenção direta de compra.",
    "begin_checkout": "Usuário avançou para a etapa de fechamento.",
    "add_payment_info": "Checkout qualificado com dados de pagamento iniciados.",
    "purchase": "Conversão final do e-commerce.",
    "view_item_list": "Exposição a listas e grades de produtos.",
    "select_item": "Clique em item a partir de vitrine ou coleção.",
    "view_cart": "Revisão do carrinho no processo de compra.",
    "remove_from_cart": "Atrito ou reconsideração dentro do carrinho.",
    "view_promotion": "Contato com banners e destaques promocionais.",
    "buy_now_click": "Intenção forte captada em CTA direto de compra.",
    "page_time_30s": "Tempo mínimo de permanência indicando atenção qualificada.",
    "scroll_depth": "Exploração ativa do conteúdo da página.",
}

GA4_COMMERCE_JOURNEY_EVENTS = (
    "view_item",
    "add_to_cart",
    "begin_checkout",
    "add_payment_info",
    "purchase",
)


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any) -> int:
    try:
        if value is None or value == "":
            return 0
        return int(float(value))
    except Exception:
        return 0


def _safe_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _parse_date_input(value: Optional[str]) -> Optional[date]:
    text = _safe_str(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _iso_start_of_day(day: date) -> str:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc).isoformat()


def _iso_end_of_day(day: date) -> str:
    return datetime(day.year, day.month, day.day, 23, 59, 59, 999999, tzinfo=timezone.utc).isoformat()


def _period_days(start: date, end: date) -> int:
    return max(1, (end - start).days + 1)


def _sort_date_value(value: Any) -> tuple[int, str]:
    text = _safe_str(value)
    if not text:
        return (1, "")
    return (0, text)


def _parse_source_medium(value: Any) -> tuple[str, str]:
    source_medium = _safe_str(value)
    if not source_medium:
        return ("", "")
    if " / " in source_medium:
        source, medium = source_medium.split(" / ", 1)
        return (source.strip(), medium.strip())
    return (source_medium, "")


@dataclass(frozen=True)
class GA4ReportPeriod:
    start: date
    end: date
    days: int


def resolve_ga4_report_period(
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    days: int = 30,
) -> GA4ReportPeriod:
    start_date = _parse_date_input(start)
    end_date = _parse_date_input(end)
    safe_days = max(1, min(int(days or 30), 366))

    if start_date and end_date:
        if start_date <= end_date:
            return GA4ReportPeriod(start=start_date, end=end_date, days=_period_days(start_date, end_date))
        return GA4ReportPeriod(start=end_date, end=start_date, days=_period_days(end_date, start_date))

    today = datetime.now(timezone.utc).date()
    period_end = end_date or today
    period_start = start_date or (period_end - timedelta(days=safe_days - 1))
    if period_start > period_end:
        period_start, period_end = period_end, period_start
    return GA4ReportPeriod(start=period_start, end=period_end, days=_period_days(period_start, period_end))


def _empty_daily_map(period: GA4ReportPeriod) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    current = period.start
    while current <= period.end:
        key = current.isoformat()
        rows[key] = {
            "date": key,
            "sessions": 0,
            "active_users": 0,
            "total_users": 0,
            "event_count": 0,
            "ecommerce_purchases": 0,
            "purchase_revenue": 0.0,
            "total_revenue": 0.0,
            "view_item_count": 0,
            "add_to_cart_count": 0,
            "begin_checkout_count": 0,
            "purchase_count": 0,
        }
        current += timedelta(days=1)
    return rows


def _group_rollup(
    rows: Iterable[Dict[str, Any]],
    *,
    key_builder,
    value_builder,
) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key = _safe_str(key_builder(row))
        if not key:
            continue
        bucket = grouped.setdefault(key, value_builder(row))
        bucket["sessions"] = _safe_int(bucket.get("sessions")) + _safe_int(row.get("sessions"))
        bucket["active_users"] = _safe_int(bucket.get("active_users")) + _safe_int(row.get("active_users"))
        bucket["total_users"] = _safe_int(bucket.get("total_users")) + _safe_int(row.get("total_users"))
        bucket["event_count"] = _safe_int(bucket.get("event_count")) + _safe_int(row.get("event_count"))
        bucket["ecommerce_purchases"] = _safe_int(bucket.get("ecommerce_purchases")) + _safe_int(
            row.get("ecommerce_purchases")
        )
        bucket["purchase_revenue"] = _safe_float(bucket.get("purchase_revenue")) + _safe_float(
            row.get("purchase_revenue")
        )
        bucket["total_revenue"] = _safe_float(bucket.get("total_revenue")) + _safe_float(row.get("total_revenue"))
    return list(grouped.values())


def _period_filter(period: GA4ReportPeriod) -> str:
    return f"(stat_date.gte.{period.start.isoformat()},stat_date.lte.{period.end.isoformat()})"


async def _select_ga4_daily_rows(*, client_id: str, property_id: str, period: GA4ReportPeriod) -> List[Dict[str, Any]]:
    return await sb_select(
        "ga4_daily_stats",
        select=(
            "id,client_id,property_id,stat_date,sessions,active_users,total_users,event_count,"
            "ecommerce_purchases,purchase_revenue,total_revenue,view_item_count,add_to_cart_count,"
            "begin_checkout_count,purchase_count,updated_at"
        ),
        filters={
            "client_id": f"eq.{client_id}",
            "property_id": f"eq.{property_id}",
            "and": _period_filter(period),
        },
        order="stat_date.asc",
        limit=max(period.days + 10, 400),
    )


async def _select_ga4_channel_rows(*, client_id: str, property_id: str, period: GA4ReportPeriod) -> List[Dict[str, Any]]:
    return await sb_select(
        "ga4_channel_stats",
        select=(
            "id,client_id,property_id,stat_date,source_medium,source,medium,sessions,active_users,total_users,"
            "event_count,ecommerce_purchases,purchase_revenue,total_revenue,updated_at"
        ),
        filters={
            "client_id": f"eq.{client_id}",
            "property_id": f"eq.{property_id}",
            "and": _period_filter(period),
        },
        order="stat_date.asc",
        limit=10000,
    )


async def _select_ga4_campaign_rows(*, client_id: str, property_id: str, period: GA4ReportPeriod) -> List[Dict[str, Any]]:
    return await sb_select(
        "ga4_campaign_stats",
        select=(
            "id,client_id,property_id,stat_date,campaign_name,source_medium,source,medium,sessions,active_users,"
            "total_users,event_count,ecommerce_purchases,purchase_revenue,total_revenue,updated_at"
        ),
        filters={
            "client_id": f"eq.{client_id}",
            "property_id": f"eq.{property_id}",
            "and": _period_filter(period),
        },
        order="stat_date.asc",
        limit=10000,
    )


async def _select_ga4_event_rows(*, client_id: str, property_id: str, period: GA4ReportPeriod) -> List[Dict[str, Any]]:
    return await sb_select(
        "ga4_event_stats",
        select="id,client_id,property_id,stat_date,event_name,event_count,total_users,updated_at",
        filters={
            "client_id": f"eq.{client_id}",
            "property_id": f"eq.{property_id}",
            "and": _period_filter(period),
        },
        order="stat_date.asc",
        limit=10000,
    )


def _normalize_period_filters(
    *,
    client_id: str,
    property_id: str,
    period: GA4ReportPeriod,
) -> tuple[str, str, GA4ReportPeriod]:
    resolved_client_id = _safe_str(client_id)
    context_client_id, context_property_id = resolve_ga4_context_for_client(resolved_client_id or None)
    resolved_client_id = resolved_client_id or context_client_id
    resolved_property_id = _safe_str(property_id) or context_property_id
    return resolved_client_id, resolved_property_id, period


def _build_daily_rows(period: GA4ReportPeriod, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    daily_map = _empty_daily_map(period)
    last_synced_at = None

    for row in rows:
        day_key = _safe_str(row.get("stat_date"))
        if day_key not in daily_map:
            continue
        bucket = daily_map[day_key]
        bucket["sessions"] = _safe_int(row.get("sessions"))
        bucket["active_users"] = _safe_int(row.get("active_users"))
        bucket["total_users"] = _safe_int(row.get("total_users"))
        bucket["event_count"] = _safe_int(row.get("event_count"))
        bucket["ecommerce_purchases"] = _safe_int(row.get("ecommerce_purchases"))
        bucket["purchase_revenue"] = round(_safe_float(row.get("purchase_revenue")), 2)
        bucket["total_revenue"] = round(_safe_float(row.get("total_revenue")), 2)
        bucket["view_item_count"] = _safe_int(row.get("view_item_count"))
        bucket["add_to_cart_count"] = _safe_int(row.get("add_to_cart_count"))
        bucket["begin_checkout_count"] = _safe_int(row.get("begin_checkout_count"))
        bucket["purchase_count"] = _safe_int(row.get("purchase_count"))
        updated_at = _safe_str(row.get("updated_at"))
        if updated_at and (not last_synced_at or updated_at > last_synced_at):
            last_synced_at = updated_at

    ordered = list(daily_map.values())
    ordered.sort(key=lambda row: row["date"])
    return ordered


def _build_summary(daily_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not daily_rows:
        return {
            "sessions": 0,
            "active_users": 0,
            "total_users": 0,
            "event_count": 0,
            "purchases": 0,
            "purchase_revenue": 0.0,
            "total_revenue": 0.0,
            "average_daily_active_users": 0.0,
            "average_daily_total_users": 0.0,
        }

    days_count = max(1, len(daily_rows))
    sessions = sum(_safe_int(row.get("sessions")) for row in daily_rows)
    active_users = sum(_safe_int(row.get("active_users")) for row in daily_rows)
    total_users = sum(_safe_int(row.get("total_users")) for row in daily_rows)
    event_count = sum(_safe_int(row.get("event_count")) for row in daily_rows)
    purchases = sum(_safe_int(row.get("ecommerce_purchases")) for row in daily_rows)
    purchase_revenue = sum(_safe_float(row.get("purchase_revenue")) for row in daily_rows)
    total_revenue = sum(_safe_float(row.get("total_revenue")) for row in daily_rows)

    return {
        "sessions": sessions,
        "active_users": active_users,
        "total_users": total_users,
        "event_count": event_count,
        "purchases": purchases,
        "purchase_revenue": round(purchase_revenue, 2),
        "total_revenue": round(total_revenue, 2),
        "average_daily_active_users": round(active_users / days_count, 2),
        "average_daily_total_users": round(total_users / days_count, 2),
    }


def _build_funnel(daily_rows: List[Dict[str, Any]]) -> Dict[str, int]:
    return {
        "view_item": sum(_safe_int(row.get("view_item_count")) for row in daily_rows),
        "add_to_cart": sum(_safe_int(row.get("add_to_cart_count")) for row in daily_rows),
        "begin_checkout": sum(_safe_int(row.get("begin_checkout_count")) for row in daily_rows),
        "add_payment_info": 0,
        "purchase": sum(_safe_int(row.get("purchase_count")) for row in daily_rows),
    }


def _build_channel_items(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items = _group_rollup(
        rows,
        key_builder=lambda row: row.get("source_medium"),
        value_builder=lambda row: {
            "source_medium": _safe_str(row.get("source_medium")),
            "source": _safe_str(row.get("source")),
            "medium": _safe_str(row.get("medium")),
            "sessions": 0,
            "active_users": 0,
            "total_users": 0,
            "event_count": 0,
            "ecommerce_purchases": 0,
            "purchase_revenue": 0.0,
            "total_revenue": 0.0,
        },
    )
    items.sort(
        key=lambda row: (
            -_safe_float(row.get("purchase_revenue")),
            -_safe_int(row.get("sessions")),
            _safe_str(row.get("source_medium")).lower(),
        )
    )
    return items


def _build_campaign_items(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items = _group_rollup(
        rows,
        key_builder=lambda row: f"{_safe_str(row.get('campaign_name'))}||{_safe_str(row.get('source_medium'))}",
        value_builder=lambda row: {
            "campaign_name": _safe_str(row.get("campaign_name")) or "(not set)",
            "source_medium": _safe_str(row.get("source_medium")),
            "source": _safe_str(row.get("source")),
            "medium": _safe_str(row.get("medium")),
            "sessions": 0,
            "active_users": 0,
            "total_users": 0,
            "event_count": 0,
            "ecommerce_purchases": 0,
            "purchase_revenue": 0.0,
            "total_revenue": 0.0,
        },
    )
    items.sort(
        key=lambda row: (
            -_safe_float(row.get("purchase_revenue")),
            -_safe_int(row.get("sessions")),
            _safe_str(row.get("campaign_name")).lower(),
        )
    )
    return items


def _build_event_items(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        event_name = _safe_str(row.get("event_name"))
        if not event_name:
            continue
        bucket = grouped.setdefault(
            event_name,
            {
                "event_name": event_name,
                "label": GA4_EVENT_LABELS.get(event_name) or event_name,
                "description": GA4_EVENT_DESCRIPTIONS.get(event_name) or None,
                "event_count": 0,
                "total_users": 0,
                "first_seen_at": _safe_str(row.get("stat_date")) or None,
                "last_seen_at": _safe_str(row.get("stat_date")) or None,
            },
        )
        bucket["event_count"] = _safe_int(bucket.get("event_count")) + _safe_int(row.get("event_count"))
        bucket["total_users"] = _safe_int(bucket.get("total_users")) + _safe_int(row.get("total_users"))
        stat_date = _safe_str(row.get("stat_date")) or None
        if stat_date and (not bucket.get("first_seen_at") or stat_date < _safe_str(bucket.get("first_seen_at"))):
            bucket["first_seen_at"] = stat_date
        if stat_date and (not bucket.get("last_seen_at") or stat_date > _safe_str(bucket.get("last_seen_at"))):
            bucket["last_seen_at"] = stat_date

    items = list(grouped.values())
    items.sort(
        key=lambda row: (
            -_safe_int(row.get("event_count")),
            -_safe_int(row.get("total_users")),
            _safe_str(row.get("event_name")).lower(),
        )
    )
    return items


def _event_item_lookup(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {
        _safe_str(item.get("event_name")): item
        for item in items
        if _safe_str(item.get("event_name"))
    }


def _build_group_item(event_name: str, lookup: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    item = lookup.get(event_name) or {}
    return {
        "event_name": event_name,
        "label": GA4_EVENT_LABELS.get(event_name) or event_name,
        "description": GA4_EVENT_DESCRIPTIONS.get(event_name) or None,
        "event_count": _safe_int(item.get("event_count")),
        "total_users": _safe_int(item.get("total_users")),
        "first_seen_at": item.get("first_seen_at"),
        "last_seen_at": item.get("last_seen_at"),
    }


def _rate(numerator: Any, denominator: Any) -> float:
    base = _safe_float(denominator)
    if base <= 0:
        return 0.0
    return round((_safe_float(numerator) / base) * 100, 2)


def _build_event_group(
    group_key: str,
    lookup: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    config = GA4_EVENT_GROUPS[group_key]
    items = [_build_group_item(event_name, lookup) for event_name in config["events"]]
    total_events = sum(_safe_int(item.get("event_count")) for item in items)
    total_users = sum(_safe_int(item.get("total_users")) for item in items)
    return {
        "key": group_key,
        "title": config["title"],
        "description": config["description"],
        "total_events": total_events,
        "total_users": total_users,
        "items": items,
    }


def _build_commerce_journey(lookup: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    items = [_build_group_item(event_name, lookup) for event_name in GA4_COMMERCE_JOURNEY_EVENTS]
    values = {item["event_name"]: _safe_int(item.get("event_count")) for item in items}
    return {
        "summary": {
            "view_item": values.get("view_item", 0),
            "add_to_cart": values.get("add_to_cart", 0),
            "begin_checkout": values.get("begin_checkout", 0),
            "add_payment_info": values.get("add_payment_info", 0),
            "purchase": values.get("purchase", 0),
            "add_to_cart_rate": _rate(values.get("add_to_cart"), values.get("view_item")),
            "checkout_rate": _rate(values.get("begin_checkout"), values.get("add_to_cart")),
            "payment_info_rate": _rate(values.get("add_payment_info"), values.get("begin_checkout")),
            "purchase_rate": _rate(values.get("purchase"), values.get("add_payment_info") or values.get("begin_checkout")),
            "purchase_rate_from_view_item": _rate(values.get("purchase"), values.get("view_item")),
        },
        "items": items,
    }


async def build_ga4_report(
    *,
    client_id: str,
    property_id: Optional[str],
    period: GA4ReportPeriod,
) -> Dict[str, Any]:
    resolved_client_id, resolved_property_id, resolved_period = _normalize_period_filters(
        client_id=client_id,
        property_id=property_id or "",
        period=period,
    )

    daily_source_rows = await _select_ga4_daily_rows(
        client_id=resolved_client_id,
        property_id=resolved_property_id,
        period=resolved_period,
    )
    channel_source_rows = await _select_ga4_channel_rows(
        client_id=resolved_client_id,
        property_id=resolved_property_id,
        period=resolved_period,
    )
    campaign_source_rows = await _select_ga4_campaign_rows(
        client_id=resolved_client_id,
        property_id=resolved_property_id,
        period=resolved_period,
    )
    event_source_rows = await _select_ga4_event_rows(
        client_id=resolved_client_id,
        property_id=resolved_property_id,
        period=resolved_period,
    )

    daily_rows = _build_daily_rows(resolved_period, daily_source_rows)
    event_items = _build_event_items(event_source_rows)
    event_lookup = _event_item_lookup(event_items)
    last_synced_at = None
    for row in daily_source_rows:
        updated_at = _safe_str(row.get("updated_at"))
        if updated_at and (not last_synced_at or updated_at > last_synced_at):
            last_synced_at = updated_at

    return {
        "ok": True,
        "client_id": resolved_client_id,
        "property_id": resolved_property_id,
        "period": {
            "start": resolved_period.start.isoformat(),
            "end": resolved_period.end.isoformat(),
            "days": resolved_period.days,
        },
        "summary": _build_summary(daily_rows),
        "funnel": {
            **_build_funnel(daily_rows),
            "add_payment_info": _safe_int((event_lookup.get("add_payment_info") or {}).get("event_count")),
        },
        "commerce_journey": _build_commerce_journey(event_lookup),
        "behavior": _build_event_group("behavior", event_lookup),
        "engagement": _build_event_group("engagement", event_lookup),
        "merchandising": _build_event_group("merchandising", event_lookup),
        "trends": {
            "daily": daily_rows,
        },
        "channels": _build_channel_items(channel_source_rows),
        "campaigns": _build_campaign_items(campaign_source_rows),
        "events": event_items,
        "meta": {
            "last_synced_at": last_synced_at,
            "daily_rows": len(daily_source_rows),
            "channel_rows": len(channel_source_rows),
            "campaign_rows": len(campaign_source_rows),
            "event_rows": len(event_source_rows),
        },
    }


async def build_ga4_channels_report(
    *,
    client_id: str,
    property_id: Optional[str],
    period: GA4ReportPeriod,
) -> Dict[str, Any]:
    resolved_client_id, resolved_property_id, resolved_period = _normalize_period_filters(
        client_id=client_id,
        property_id=property_id or "",
        period=period,
    )
    rows = await _select_ga4_channel_rows(
        client_id=resolved_client_id,
        property_id=resolved_property_id,
        period=resolved_period,
    )
    items = _build_channel_items(rows)
    return {
        "ok": True,
        "client_id": resolved_client_id,
        "property_id": resolved_property_id,
        "period": {
            "start": resolved_period.start.isoformat(),
            "end": resolved_period.end.isoformat(),
            "days": resolved_period.days,
        },
        "count": len(items),
        "items": items,
    }


async def build_ga4_campaigns_report(
    *,
    client_id: str,
    property_id: Optional[str],
    period: GA4ReportPeriod,
) -> Dict[str, Any]:
    resolved_client_id, resolved_property_id, resolved_period = _normalize_period_filters(
        client_id=client_id,
        property_id=property_id or "",
        period=period,
    )
    rows = await _select_ga4_campaign_rows(
        client_id=resolved_client_id,
        property_id=resolved_property_id,
        period=resolved_period,
    )
    items = _build_campaign_items(rows)
    return {
        "ok": True,
        "client_id": resolved_client_id,
        "property_id": resolved_property_id,
        "period": {
            "start": resolved_period.start.isoformat(),
            "end": resolved_period.end.isoformat(),
            "days": resolved_period.days,
        },
        "count": len(items),
        "items": items,
    }


async def build_ga4_events_report(
    *,
    client_id: str,
    property_id: Optional[str],
    period: GA4ReportPeriod,
) -> Dict[str, Any]:
    resolved_client_id, resolved_property_id, resolved_period = _normalize_period_filters(
        client_id=client_id,
        property_id=property_id or "",
        period=period,
    )
    rows = await _select_ga4_event_rows(
        client_id=resolved_client_id,
        property_id=resolved_property_id,
        period=resolved_period,
    )
    items = _build_event_items(rows)
    return {
        "ok": True,
        "client_id": resolved_client_id,
        "property_id": resolved_property_id,
        "period": {
            "start": resolved_period.start.isoformat(),
            "end": resolved_period.end.isoformat(),
            "days": resolved_period.days,
        },
        "count": len(items),
        "items": items,
    }
