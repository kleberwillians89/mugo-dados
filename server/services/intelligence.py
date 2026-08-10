from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List

import httpx

from .periods import resolve_period
from .generic_connections import list_generic_connections
from .ig_supabase import sb_insert, sb_select, sb_update


ANALYSIS_SCHEMA = {
    "name": "mugo_intelligence_analysis_v1",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "executive": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "overall": {"type": "string"},
                    "main_change": {"type": "string"},
                    "opportunity": {"type": "string"},
                    "attention": {"type": "string"},
                    "priority_action": {"type": "string"},
                },
                "required": ["overall", "main_change", "opportunity", "attention", "priority_action"],
            },
            "insights": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ["opportunity", "attention", "risk", "positive", "anomaly", "data_quality"],
                        },
                        "title": {"type": "string"},
                        "interpretation": {"type": "string"},
                        "metric_ids": {"type": "array", "items": {"type": "string"}},
                        "sources": {"type": "array", "items": {"type": "string"}},
                        "impact": {"type": "string", "enum": ["high", "medium", "low"]},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "action": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": [
                        "category", "title", "interpretation", "metric_ids", "sources",
                        "impact", "confidence", "action", "reason",
                    ],
                },
                "maxItems": 10,
            },
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "priority": {"type": "string", "enum": ["now", "week", "monitor", "investigate"]},
                        "recommendation": {"type": "string"},
                        "justification": {"type": "string"},
                        "sources": {"type": "array", "items": {"type": "string"}},
                        "impact_expected": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "metric_id": {"type": "string"},
                    },
                    "required": [
                        "priority", "recommendation", "justification", "sources",
                        "impact_expected", "confidence", "metric_id",
                    ],
                },
                "maxItems": 12,
            },
        },
        "required": ["executive", "insights", "actions"],
    },
}

ANSWER_SCHEMA = {
    "name": "mugo_intelligence_answer_v1",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "direct_answer": {"type": "string"},
            "metric_ids": {"type": "array", "items": {"type": "string"}},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "attention_points": {"type": "array", "items": {"type": "string"}},
            "recommendations": {"type": "array", "items": {"type": "string"}},
            "next_steps": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "direct_answer", "metric_ids", "evidence", "attention_points",
            "recommendations", "next_steps",
        ],
    },
}


def provider_configured() -> bool:
    return bool((os.getenv("OPENAI_API_KEY") or "").strip())


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _text(value: Any) -> str:
    return str(value or "").strip()


def _parse_period(start: str | None, end: str | None, days: int = 30) -> tuple[date, date]:
    period = resolve_period(start=start, end=end, days=days, max_days=366)
    if period.days > 366:
        raise RuntimeError("O período da análise não pode ultrapassar 366 dias.")
    return period.start, period.end


def _period_filter(column: str, start: date, end: date) -> str:
    return f"({column}.gte.{start.isoformat()},{column}.lte.{end.isoformat()})"


async def _query_period(
    table: str,
    *,
    client_id: str,
    select: str,
    date_column: str,
    start: date,
    end: date,
    limit: int = 10000,
) -> List[Dict[str, Any]]:
    return await sb_select(
        table,
        select=select,
        filters={
            "client_id": f"eq.{client_id}",
            "and": _period_filter(date_column, start, end),
        },
        order=f"{date_column}.asc",
        limit=limit,
    )


def _safe_result(value: Any) -> tuple[List[Dict[str, Any]], bool]:
    if isinstance(value, Exception):
        return [], True
    return value if isinstance(value, list) else [], False


def _sum(rows: Iterable[Dict[str, Any]], field: str) -> float:
    return sum(_number(row.get(field)) for row in rows)


def _variation(current: float, previous: float, previous_available: bool) -> float | None:
    if not previous_available or previous == 0:
        return None
    return round(((current - previous) / abs(previous)) * 100, 2)


def _metric(
    metric_id: str,
    label: str,
    value: float | None,
    *,
    fmt: str,
    status: str,
    source: str,
    previous: float | None = None,
    variation: float | None = None,
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "id": metric_id,
        "label": label,
        "value": round(value, 2) if isinstance(value, float) else value,
        "format": fmt,
        "status": status,
        "source": source,
        "previous_value": round(previous, 2) if isinstance(previous, float) else previous,
        "variation_percent": variation,
        **(extra or {}),
    }


def _source_status(
    source_id: str,
    label: str,
    *,
    connections: List[Dict[str, Any]],
    providers: set[str],
    rows: List[Dict[str, Any]],
    failed: bool,
    expected_days: int | None = None,
    date_field: str | None = None,
) -> Dict[str, Any]:
    relevant = [row for row in connections if _text(row.get("provider")).lower() in providers]
    connected = any(_text(row.get("status")).lower() in {"connected", "active", "ready"} for row in relevant)
    latest = max((_text(row.get("last_sync_at")) for row in relevant), default="") or None
    if failed:
        state = "error"
    elif rows:
        covered_days = (
            len({_text(row.get(date_field)) for row in rows if _text(row.get(date_field))})
            if date_field else 0
        )
        state = (
            "partial"
            if expected_days and date_field and covered_days < max(1, round(expected_days * 0.6))
            else "available"
        )
    elif connected:
        state = "no_data"
    else:
        state = "disconnected"
    return {
        "id": source_id,
        "label": label,
        "status": state,
        "connected": connected,
        "data_points": len(rows),
        "covered_days": covered_days if rows and date_field else None,
        "last_sync_at": latest,
    }


def _status_for(source: Dict[str, Any]) -> str:
    return {
        "available": "confirmed",
        "partial": "partial",
        "no_data": "unavailable",
        "disconnected": "disconnected",
        "error": "error",
    }.get(_text(source.get("status")), "unavailable")


async def _read_model_executive_context(
    client_id: str, start_date: date, end_date: date, previous_start: date, previous_end: date
) -> Dict[str, Any]:
    rows, snapshots = await asyncio.gather(
        _query_period(
            "dashboard_daily_metrics", client_id=client_id, select="*", date_column="metric_date",
            start=previous_start, end=end_date, limit=800,
        ),
        sb_select("dashboard_source_snapshots", filters={"client_id": f"eq.{client_id}"}, limit=20),
    )
    by_provider = {_text(row.get("provider")): row for row in snapshots}

    def section(period_start: date, period_end: date) -> Dict[str, Any]:
        selected = [row for row in rows if period_start.isoformat() <= _text(row.get("metric_date")) <= period_end.isoformat()]
        net = _sum(selected, "shopify_net_revenue")
        orders = _sum(selected, "shopify_orders")
        meta_spend = _sum(selected, "meta_spend")
        meta_revenue = _sum(selected, "meta_attributed_revenue")
        google_spend = _sum(selected, "google_ads_spend")
        google_value = _sum(selected, "google_ads_conversion_value")
        paid = meta_spend + google_spend
        source = lambda provider: by_provider.get(provider, {})
        return {
            "shopify": {"connected": True, "data_available": any(row.get("shopify_net_revenue") is not None for row in selected), "net_revenue": net, "orders": orders, "average_order_value": net / orders if orders else None, "new_customers": _sum(selected, "shopify_customers"), "returning_customers": None, "last_success_at": source("shopify").get("last_success_at"), "data_max_available": source("shopify").get("data_max_available")},
            "meta": {"connected": True, "data_available": any(row.get("meta_spend") is not None for row in selected), "spend": meta_spend, "attributed_revenue": meta_revenue, "roas": meta_revenue / meta_spend if meta_spend else None, "last_success_at": source("meta").get("last_success_at"), "data_max_available": source("meta").get("data_max_available")},
            "google_ads": {"connected": True, "data_available": any(row.get("google_ads_spend") is not None for row in selected), "spend": google_spend, "attributed_revenue": google_value, "roas": google_value / google_spend if google_spend else None, "last_success_at": source("google_ads").get("last_success_at"), "data_max_available": source("google_ads").get("data_max_available")},
            "ga4": {"connected": True, "data_available": any(row.get("ga4_sessions") is not None for row in selected), "sessions": _sum(selected, "ga4_sessions"), "users": _sum(selected, "ga4_users"), "last_success_at": source("ga4").get("last_success_at"), "data_max_available": source("ga4").get("data_max_available")},
            "instagram": {"connected": True, "data_available": any(row.get("instagram_reach") is not None for row in selected), "last_success_at": source("instagram").get("last_success_at"), "data_max_available": source("instagram").get("data_max_available")},
            "total_paid_media": {"paid_media_spend": paid, "included_paid_sources": [provider for provider, value in (("meta", meta_spend), ("google_ads", google_spend)) if value], "blended_roas": net / paid if paid else None},
        }

    current = section(start_date, end_date)
    previous = section(previous_start, previous_end)
    def delta(current_value: Any, previous_value: Any) -> Dict[str, float | None]:
        current_number, previous_number = _number(current_value), _number(previous_value)
        return {"absolute": current_number - previous_number, "percent": ((current_number - previous_number) / abs(previous_number) * 100) if previous_number else None}
    current["previous_period"] = previous
    current["deltas"] = {
        "shopify_net_revenue": delta(current["shopify"]["net_revenue"], previous["shopify"]["net_revenue"]),
        "shopify_orders": delta(current["shopify"]["orders"], previous["shopify"]["orders"]),
        "meta_spend": delta(current["meta"]["spend"], previous["meta"]["spend"]),
        "blended_roas": delta(current["total_paid_media"]["blended_roas"], previous["total_paid_media"]["blended_roas"]),
    }
    return current


async def calculate_intelligence_snapshot(
    *,
    client_id: str,
    start: str | None,
    end: str | None,
    days: int = 30,
) -> Dict[str, Any]:
    start_date, end_date = _parse_period(start, end, days)
    period_days = (end_date - start_date).days + 1
    previous_end = start_date - timedelta(days=1)
    previous_start = previous_end - timedelta(days=period_days - 1)

    executive_context = await _read_model_executive_context(
        client_id, start_date, end_date, previous_start, previous_end
    )
    current = executive_context or {}
    previous = current.get("previous_period") or {}
    deltas = current.get("deltas") or {}
    shopify = current.get("shopify") or {}
    meta = current.get("meta") or {}
    google_ads = current.get("google_ads") or {}
    ga4 = current.get("ga4") or {}
    instagram = current.get("instagram") or {}
    total_media = current.get("total_paid_media") or {}

    def provider_source(source_id: str, label: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
        connected = bool(payload.get("connected"))
        available = bool(payload.get("data_available", connected and payload.get("data_max_available")))
        state = "partial" if coverage.get("is_partial") else "available" if available else "connected_no_data" if connected else "not_connected"
        return {
            "id": source_id, "label": label, "status": state,
            "connected": connected, "last_sync_at": payload.get("last_success_at"),
            "data_max_available": payload.get("data_max_available"), "coverage": coverage,
            "last_error": payload.get("last_error"),
        }

    sources = [
        provider_source("commerce", "E-commerce", shopify),
        provider_source("meta", "Meta Ads", meta),
        provider_source("google_ads", "Google Ads", google_ads),
        provider_source("ga4", "Google Analytics 4", ga4),
        provider_source("instagram", "Instagram", instagram),
    ]
    prev_shopify = previous.get("shopify") or {}
    prev_meta = previous.get("meta") or {}
    metrics = [
        _metric("revenue", "Faturamento", shopify.get("net_revenue"), fmt="currency", status="confirmed" if shopify.get("net_revenue") is not None else "unavailable", source="shopify", previous=prev_shopify.get("net_revenue"), variation=(deltas.get("shopify_net_revenue") or {}).get("percent")),
        _metric("orders", "Pedidos", shopify.get("orders"), fmt="integer", status="confirmed" if shopify.get("orders") is not None else "unavailable", source="shopify", previous=prev_shopify.get("orders"), variation=(deltas.get("shopify_orders") or {}).get("percent")),
        _metric("average_ticket", "Ticket médio", shopify.get("average_order_value"), fmt="currency", status="confirmed" if shopify.get("average_order_value") is not None else "unavailable", source="shopify"),
        _metric("new_customers", "Novos clientes", shopify.get("new_customers"), fmt="integer", status="confirmed" if shopify.get("new_customers") is not None else "unavailable", source="shopify"),
        _metric("repeat_customers", "Clientes recorrentes", shopify.get("returning_customers"), fmt="integer", status="confirmed" if shopify.get("returning_customers") is not None else "unavailable", source="shopify"),
        _metric("meta_investment", "Investimento Meta", meta.get("spend"), fmt="currency", status="partial" if (meta.get("coverage") or {}).get("is_partial") else "confirmed" if meta.get("spend") is not None else "unavailable", source="meta", previous=prev_meta.get("spend"), variation=(deltas.get("meta_spend") or {}).get("percent")),
        _metric("google_ads_investment", "Investimento Google Ads", google_ads.get("spend"), fmt="currency", status="partial" if (google_ads.get("coverage") or {}).get("is_partial") else "confirmed" if google_ads.get("spend") is not None else "unavailable", source="google_ads"),
        _metric("investment", "Investimento total", total_media.get("paid_media_spend"), fmt="currency", status="confirmed" if total_media.get("paid_media_spend") is not None else "unavailable", source="paid_media", extra={"included_paid_sources": total_media.get("included_paid_sources") or []}),
        _metric("roas", "Retorno real geral", total_media.get("blended_roas"), fmt="decimal", status="confirmed" if total_media.get("blended_roas") is not None else "unavailable", source="shopify+paid_media", variation=(deltas.get("blended_roas") or {}).get("percent"), extra={"included_paid_sources": total_media.get("included_paid_sources") or []}),
        _metric("sessions", "Sessões", ga4.get("sessions"), fmt="integer", status="confirmed" if ga4.get("sessions") is not None else "unavailable", source="ga4"),
    ]
    available_sources = sum(1 for source in sources if source["status"] in {"available", "partial"})
    quality_score = round(available_sources / len(sources) * 100)
    return {
        "client": {"id": client_id, "name": "Empresa ativa"},
        "period": {
            "start": start_date.isoformat(), "end": end_date.isoformat(), "days": period_days,
            "previous_start": previous_start.isoformat(), "previous_end": previous_end.isoformat(),
        },
        "sources": sources,
        "quality": {
            "score": quality_score, "status": "good" if quality_score >= 75 else "partial" if quality_score >= 40 else "limited",
            "available_sources": available_sources, "total_sources": len(sources), "errors": 0,
            "message": "Qualidade baseada exclusivamente no contexto executivo persistido.",
        },
        "last_sync_at": max((str(source.get("last_sync_at") or "") for source in sources), default="") or None,
        "metrics": metrics, "crossings": [], "top_campaigns": [],
        "executive_context": executive_context,
    }

    shop_select = "shopify_order_id,customer_id,email,total_price,cancelled_at,created_at_shopify"
    paid_select = "stat_date,spend,conversions,revenue,updated_at"
    ga4_select = (
        "stat_date,sessions,total_users,ecommerce_purchases,purchase_revenue,total_revenue,"
        "view_item_count,add_to_cart_count,begin_checkout_count,purchase_count,updated_at"
    )
    instagram_select = (
        "snapshot_date,followers_count,reach_day,total_interactions_day,website_clicks_day,"
        "profile_views_day,updated_at"
    )
    campaign_select = "stat_date,campaign_name,spend,conversions,revenue"

    results = await asyncio.gather(
        sb_select("clients", select="id,name,trade_name", filters={"id": f"eq.{client_id}"}, limit=1),
        list_generic_connections(client_id),
        _query_period(
            "shopify_orders", client_id=client_id, select=shop_select,
            date_column="created_at_shopify", start=start_date, end=end_date,
        ),
        _query_period(
            "shopify_orders", client_id=client_id, select=shop_select,
            date_column="created_at_shopify", start=previous_start, end=previous_end,
        ),
        sb_select(
            "shopify_orders",
            select="customer_id,email,created_at_shopify",
            filters={
                "client_id": f"eq.{client_id}",
                "created_at_shopify": f"lt.{start_date.isoformat()}",
            },
            limit=10000,
        ),
        _query_period(
            "ad_account_daily_stats", client_id=client_id, select=paid_select,
            date_column="stat_date", start=start_date, end=end_date,
        ),
        _query_period(
            "ad_account_daily_stats", client_id=client_id, select=paid_select,
            date_column="stat_date", start=previous_start, end=previous_end,
        ),
        _query_period(
            "ga4_daily_stats", client_id=client_id, select=ga4_select,
            date_column="stat_date", start=start_date, end=end_date,
        ),
        _query_period(
            "ga4_daily_stats", client_id=client_id, select=ga4_select,
            date_column="stat_date", start=previous_start, end=previous_end,
        ),
        _query_period(
            "ig_profile_snapshots", client_id=client_id, select=instagram_select,
            date_column="snapshot_date", start=start_date, end=end_date,
        ),
        _query_period(
            "ig_profile_snapshots", client_id=client_id, select=instagram_select,
            date_column="snapshot_date", start=previous_start, end=previous_end,
        ),
        _query_period(
            "campaign_daily_stats", client_id=client_id, select=campaign_select,
            date_column="stat_date", start=start_date, end=end_date,
        ),
        return_exceptions=True,
    )

    company_rows, company_failed = _safe_result(results[0])
    connections, connections_failed = _safe_result(results[1])
    shop, shop_failed = _safe_result(results[2])
    shop_previous, shop_previous_failed = _safe_result(results[3])
    older_orders, older_failed = _safe_result(results[4])
    paid, paid_failed = _safe_result(results[5])
    paid_previous, paid_previous_failed = _safe_result(results[6])
    ga4, ga4_failed = _safe_result(results[7])
    ga4_previous, ga4_previous_failed = _safe_result(results[8])
    instagram, instagram_failed = _safe_result(results[9])
    instagram_previous, instagram_previous_failed = _safe_result(results[10])
    campaigns, campaigns_failed = _safe_result(results[11])

    commerce_source = _source_status(
        "commerce", "E-commerce", connections=connections,
        providers={"shopify", "fbits"}, rows=shop, failed=shop_failed,
    )
    paid_source = _source_status(
        "paid_media", "Mídia paga", connections=connections,
        providers={"meta", "google"}, rows=paid, failed=paid_failed,
        expected_days=period_days, date_field="stat_date",
    )
    ga4_source = _source_status(
        "ga4", "Google Analytics 4", connections=connections,
        providers={"google"}, rows=ga4, failed=ga4_failed,
        expected_days=period_days, date_field="stat_date",
    )
    instagram_source = _source_status(
        "instagram", "Instagram", connections=connections,
        providers={"meta"}, rows=instagram, failed=instagram_failed or connections_failed,
        expected_days=period_days, date_field="snapshot_date",
    )
    sources = [commerce_source, paid_source, ga4_source, instagram_source]

    valid_shop = [row for row in shop if not _text(row.get("cancelled_at"))]
    valid_previous_shop = [row for row in shop_previous if not _text(row.get("cancelled_at"))]
    revenue = _sum(valid_shop, "total_price")
    previous_revenue = _sum(valid_previous_shop, "total_price")
    orders = float(len(valid_shop))
    previous_orders = float(len(valid_previous_shop))
    investment = _sum(paid, "spend")
    previous_investment = _sum(paid_previous, "spend")
    conversions = _sum(paid, "conversions")
    sessions = _sum(ga4, "sessions")
    ga4_purchases = _sum(ga4, "ecommerce_purchases") or _sum(ga4, "purchase_count")
    profile_views = _sum(instagram, "profile_views_day")
    previous_profile_views = _sum(instagram_previous, "profile_views_day")
    followers_growth = (
        _number(instagram[-1].get("followers_count")) - _number(instagram[0].get("followers_count"))
        if len(instagram) >= 2 else 0.0
    )
    previous_followers_growth = (
        _number(instagram_previous[-1].get("followers_count"))
        - _number(instagram_previous[0].get("followers_count"))
        if len(instagram_previous) >= 2 else 0.0
    )

    def customer_key(row: Dict[str, Any]) -> str:
        return _text(row.get("customer_id")) or _text(row.get("email")).lower()

    current_customer_counts: Dict[str, int] = {}
    for row in valid_shop:
        key = customer_key(row)
        if key:
            current_customer_counts[key] = current_customer_counts.get(key, 0) + 1
    older_keys = {customer_key(row) for row in older_orders if customer_key(row)}
    new_customers = float(sum(1 for key in current_customer_counts if key not in older_keys))
    repeat_customers = float(sum(1 for key, count in current_customer_counts.items() if key in older_keys or count > 1))

    commerce_status = _status_for(commerce_source)
    paid_status = _status_for(paid_source)
    ga4_status = _status_for(ga4_source)
    instagram_status = _status_for(instagram_source)

    # Contexto executivo real (Shopify líquido + ROAS combinado transparente):
    # a IA nunca recalcula isso, só interpreta o que o backend já calculou.
    # Se algo falhar aqui, a Intelligence degrada para os campos legados
    # abaixo (revenue bruto / roas ad hoc) em vez de quebrar a tela.
    try:
        executive_context = await get_executive_summary(
            client_id,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            include_previous_period=True,
        )
    except Exception:
        executive_context = None
    executive_shopify = (executive_context or {}).get("shopify")
    executive_previous_shopify = ((executive_context or {}).get("previous_period") or {}).get("shopify")
    executive_deltas = (executive_context or {}).get("deltas") or {}
    executive_total_media = (executive_context or {}).get("total_paid_media") or {}

    net_revenue_value = executive_shopify.get("net_revenue") if executive_shopify else None
    revenue_display = net_revenue_value if net_revenue_value is not None else (
        revenue if commerce_status == "confirmed" else None
    )
    revenue_previous_display = (
        executive_previous_shopify.get("net_revenue")
        if executive_previous_shopify
        else (previous_revenue if valid_previous_shop else None)
    )
    revenue_variation = (
        (executive_deltas.get("shopify_net_revenue") or {}).get("percent")
        if executive_shopify
        else _variation(revenue, previous_revenue, bool(valid_previous_shop) and not shop_previous_failed)
    )

    blended_roas_value = executive_total_media.get("blended_roas")
    included_paid_sources = executive_total_media.get("included_paid_sources") or []
    roas_value = (
        blended_roas_value
        if executive_context is not None
        else (revenue / investment if investment > 0 and commerce_status == "confirmed" else None)
    )
    roas_status = (
        "confirmed"
        if roas_value is not None
        else "partial"
        if executive_shopify and included_paid_sources
        else "unavailable"
    )

    metrics = [
        _metric(
            "revenue", "Faturamento", revenue_display,
            fmt="currency", status=commerce_status, source="commerce",
            previous=revenue_previous_display,
            variation=revenue_variation,
        ),
        _metric(
            "investment", "Investimento", investment if paid_status in {"confirmed", "partial"} else None,
            fmt="currency", status=paid_status, source="paid_media",
            previous=previous_investment if paid_previous else None,
            variation=_variation(investment, previous_investment, bool(paid_previous) and not paid_previous_failed),
        ),
        _metric(
            "roas", "ROAS", roas_value,
            fmt="decimal", status=roas_status, source="commerce+paid_media",
            variation=(executive_deltas.get("blended_roas") or {}).get("percent"),
            extra={"included_paid_sources": included_paid_sources},
        ),
        _metric(
            "cpa", "CPA", investment / conversions if conversions > 0 else None,
            fmt="currency", status="confirmed" if conversions > 0 and paid_status == "confirmed" else paid_status,
            source="paid_media",
        ),
        _metric(
            "orders", "Pedidos", orders if commerce_status == "confirmed" else None,
            fmt="integer", status=commerce_status, source="commerce",
            previous=previous_orders if valid_previous_shop else None,
            variation=_variation(orders, previous_orders, bool(valid_previous_shop) and not shop_previous_failed),
        ),
        _metric(
            "average_ticket", "Ticket médio", revenue / orders if orders > 0 else None,
            fmt="currency", status="confirmed" if orders > 0 and commerce_status == "confirmed" else commerce_status,
            source="commerce",
        ),
        _metric(
            "conversion_rate", "Taxa de conversão", (ga4_purchases / sessions) * 100 if sessions > 0 else None,
            fmt="percent", status="confirmed" if sessions > 0 and ga4_status == "confirmed" else ga4_status,
            source="ga4",
        ),
        _metric(
            "new_customers", "Novos clientes", new_customers if commerce_status == "confirmed" and not older_failed else None,
            fmt="integer", status=commerce_status if not older_failed else "error", source="commerce",
        ),
        _metric(
            "repeat_customers", "Clientes recorrentes", repeat_customers if commerce_status == "confirmed" and not older_failed else None,
            fmt="integer", status=commerce_status if not older_failed else "error", source="commerce",
        ),
        _metric(
            "sessions", "Sessões", sessions if ga4_status in {"confirmed", "partial"} else None,
            fmt="integer", status=ga4_status, source="ga4",
        ),
        _metric(
            "followers_growth", "Crescimento de seguidores",
            followers_growth if instagram_status in {"confirmed", "partial"} else None,
            fmt="integer", status=instagram_status, source="instagram",
            previous=previous_followers_growth if instagram_previous else None,
            variation=_variation(
                followers_growth,
                previous_followers_growth,
                bool(instagram_previous) and not instagram_previous_failed,
            ),
        ),
        _metric(
            "instagram_profile_views", "Visitas ao perfil",
            profile_views if instagram_status in {"confirmed", "partial"} else None,
            fmt="integer", status=instagram_status, source="instagram",
            previous=previous_profile_views if instagram_previous else None,
            variation=_variation(
                profile_views,
                previous_profile_views,
                bool(instagram_previous) and not instagram_previous_failed,
            ),
        ),
    ]

    campaign_totals: Dict[str, Dict[str, float | str]] = {}
    for row in campaigns:
        name = _text(row.get("campaign_name")) or "Campanha sem nome"
        item = campaign_totals.setdefault(name, {"name": name, "spend": 0.0, "revenue": 0.0, "conversions": 0.0})
        item["spend"] = _number(item["spend"]) + _number(row.get("spend"))
        item["revenue"] = _number(item["revenue"]) + _number(row.get("revenue"))
        item["conversions"] = _number(item["conversions"]) + _number(row.get("conversions"))
    top_campaigns = sorted(
        campaign_totals.values(), key=lambda item: _number(item.get("spend")), reverse=True,
    )[:5]

    funnel = {
        "sessions": sessions,
        "view_item": _sum(ga4, "view_item_count"),
        "add_to_cart": _sum(ga4, "add_to_cart_count"),
        "begin_checkout": _sum(ga4, "begin_checkout_count"),
        "purchase": _sum(ga4, "purchase_count") or ga4_purchases,
        "status": ga4_status,
    }
    crossings = [
        {
            "id": "paid_to_revenue",
            "label": "Investimento × faturamento",
            "sources": ["paid_media", "commerce"],
            "status": "available" if investment > 0 and commerce_status == "confirmed" else "insufficient_data",
            "note": "Relação observada no mesmo período; não demonstra causalidade.",
            "metrics": ["investment", "revenue", "roas"],
        },
        {
            "id": "ga4_to_sales",
            "label": "GA4 × vendas",
            "sources": ["ga4", "commerce"],
            "status": "available" if sessions > 0 and commerce_status == "confirmed" else "insufficient_data",
            "note": "Compara comportamento e vendas sem atribuir causalidade.",
            "metrics": ["sessions", "conversion_rate", "orders", "revenue"],
        },
        {
            "id": "commerce_funnel",
            "label": "Sessão × carrinho × checkout × compra",
            "sources": ["ga4"],
            "status": "available" if sessions > 0 else "insufficient_data",
            "note": "Etapas calculadas a partir dos eventos persistidos no GA4.",
            "metrics": ["sessions", "conversion_rate"],
            "funnel": funnel,
        },
        {
            "id": "instagram_to_commerce",
            "label": "Instagram × visitas × pedidos",
            "sources": ["instagram", "commerce"],
            "status": (
                "available"
                if instagram_status == "confirmed" and commerce_status == "confirmed"
                else "insufficient_data"
            ),
            "note": "Sinais comparados no mesmo período; crescimento social não comprova geração de pedidos.",
            "metrics": ["followers_growth", "instagram_profile_views", "orders", "revenue"],
        },
    ]

    source_available = sum(1 for source in sources if source["status"] == "available")
    source_partial = sum(1 for source in sources if source["status"] == "partial")
    source_errors = sum(1 for source in sources if source["status"] == "error")
    quality_score = max(
        0,
        min(100, round(((source_available + source_partial * 0.5) / len(sources)) * 100 - source_errors * 10)),
    )
    quality = {
        "score": quality_score,
        "status": "good" if quality_score >= 75 else "partial" if quality_score >= 40 else "limited",
        "available_sources": source_available,
        "total_sources": len(sources),
        "errors": source_errors,
        "message": (
            "Fontes principais disponíveis para o período."
            if quality_score >= 75
            else "A análise possui limitações porque parte das fontes está sem dados ou desconectada."
        ),
    }
    last_sync_at = max(
        (_text(source.get("last_sync_at")) for source in sources if source.get("last_sync_at")),
        default="",
    ) or None
    company = company_rows[0] if company_rows and not company_failed else {}
    return {
        "client": {
            "id": client_id,
            "name": _text(company.get("trade_name")) or _text(company.get("name")) or "Empresa ativa",
        },
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "days": period_days,
            "previous_start": previous_start.isoformat(),
            "previous_end": previous_end.isoformat(),
        },
        "sources": sources,
        "quality": quality,
        "last_sync_at": last_sync_at,
        "metrics": metrics,
        "crossings": crossings,
        "top_campaigns": top_campaigns if not campaigns_failed else [],
        "executive_context": executive_context,
    }


def _extract_output_text(response: Dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"].strip()
    for item in response.get("output") or []:
        for block in item.get("content") or []:
            if block.get("type") in {"output_text", "text"} and isinstance(block.get("text"), str):
                return block["text"].strip()
    return ""


def _assert_no_untrusted_numeric_text(value: Any, path: str = "response") -> None:
    """Números exibidos devem vir dos objetos de métricas calculados pelo backend."""
    if isinstance(value, str):
        if re.search(r"\d", value):
            raise RuntimeError(f"AI_UNTRUSTED_NUMERIC_TEXT:{path}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_untrusted_numeric_text(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {
                "metric_ids", "metric_id", "sources", "category",
                "impact", "confidence", "priority",
            }:
                continue
            _assert_no_untrusted_numeric_text(item, f"{path}.{key}")


async def _call_provider(*, payload: Dict[str, Any], schema: Dict[str, Any], instructions: str) -> Dict[str, Any]:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("AI_PROVIDER_NOT_CONFIGURED")
    model = (os.getenv("OPENAI_MODEL") or "gpt-4.1-mini").strip()
    body = {
        "model": model,
        "instructions": instructions,
        "input": json.dumps(payload, ensure_ascii=False),
        "temperature": 0.2,
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema["name"],
                "schema": schema["schema"],
            }
        },
    }
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"AI_PROVIDER_ERROR_{response.status_code}")
    text = _extract_output_text(response.json())
    if not text:
        raise RuntimeError("AI_PROVIDER_EMPTY_RESPONSE")
    parsed = json.loads(text)
    _assert_no_untrusted_numeric_text(parsed)
    return parsed


def _sanitize_analysis(analysis: Dict[str, Any], snapshot: Dict[str, Any]) -> Dict[str, Any]:
    allowed_metrics = {metric["id"] for metric in snapshot["metrics"]}
    allowed_sources = {source["id"] for source in snapshot["sources"]}
    for insight in analysis.get("insights") or []:
        insight["metric_ids"] = [item for item in insight.get("metric_ids") or [] if item in allowed_metrics]
        insight["sources"] = [item for item in insight.get("sources") or [] if item in allowed_sources]
    for action in analysis.get("actions") or []:
        if action.get("metric_id") not in allowed_metrics:
            action["metric_id"] = ""
        action["sources"] = [item for item in action.get("sources") or [] if item in allowed_sources]
    return analysis


async def generate_analysis(
    *,
    client_id: str,
    user_id: str,
    start: str | None,
    end: str | None,
    days: int = 30,
) -> Dict[str, Any]:
    snapshot = await calculate_intelligence_snapshot(
        client_id=client_id, start=start, end=end, days=days,
    )
    period = snapshot["period"]
    base_row = {
        "client_id": client_id,
        "requested_by": user_id,
        "period_start": period["start"],
        "period_end": period["end"],
        "provider": "openai" if provider_configured() else None,
        "model": (os.getenv("OPENAI_MODEL") or "gpt-4.1-mini") if provider_configured() else None,
        "sources": snapshot["sources"],
        "data_quality": snapshot["quality"],
        "metrics_snapshot": snapshot["metrics"],
    }
    if not provider_configured():
        saved = await sb_insert(
            "ai_analyses",
            {**base_row, "status": "configuration_pending", "error_code": "AI_PROVIDER_NOT_CONFIGURED"},
        )
        return {
            "ok": True,
            "provider_configured": False,
            "status": "configuration_pending",
            "snapshot": snapshot,
            "analysis": saved,
        }
    try:
        analysis = await _call_provider(
            payload={
                "period": period,
                "metrics": snapshot["metrics"],
                "sources": snapshot["sources"],
                "quality": snapshot["quality"],
                "crossings": snapshot["crossings"],
                "top_campaigns": snapshot["top_campaigns"],
                # Números já calculados (Shopify líquido, ROAS combinado com
                # fontes incluídas explícitas, GA4 separado) — a IA só
                # interpreta, nunca soma/divide nada daqui.
                "real_operation": snapshot.get("executive_context"),
            },
            schema=ANALYSIS_SCHEMA,
            instructions=(
                "Você é a central analítica do Mugô Dados. Interprete somente o JSON recebido. "
                "Não invente números, não trate ausente como zero e não afirme causalidade. "
                "Evidências devem ser referenciadas apenas por metric_ids e sources existentes. "
                "Não escreva algarismos nos textos; os números serão renderizados pelo backend a partir dos metric_ids. "
                "Recomendações são hipóteses práticas, nunca promessas de resultado."
            ),
        )
        analysis = _sanitize_analysis(analysis, snapshot)
        saved = await sb_insert(
            "ai_analyses",
            {
                **base_row,
                "status": "completed",
                "analysis": analysis,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return {
            "ok": True,
            "provider_configured": True,
            "status": "completed",
            "snapshot": snapshot,
            "analysis": saved,
        }
    except Exception as exc:
        code = _text(exc)[:80] or "AI_PROVIDER_ERROR"
        await sb_insert("ai_analyses", {**base_row, "status": "failed", "error_code": code})
        raise RuntimeError(code) from exc


async def latest_analysis(client_id: str, start: str | None, end: str | None) -> Dict[str, Any]:
    start_date, end_date = _parse_period(start, end)
    rows = await sb_select(
        "ai_analyses",
        filters={
            "client_id": f"eq.{client_id}",
            "period_start": f"eq.{start_date.isoformat()}",
            "period_end": f"eq.{end_date.isoformat()}",
        },
        order="created_at.desc",
        limit=1,
    )
    return {
        "ok": True,
        "provider_configured": provider_configured(),
        "analysis": rows[0] if rows else None,
    }


async def analysis_history(client_id: str, limit: int = 20) -> Dict[str, Any]:
    rows = await sb_select(
        "ai_analyses",
        select=(
            "id,client_id,period_start,period_end,status,provider,model,sources,data_quality,"
            "metrics_snapshot,analysis,error_code,created_at,completed_at"
        ),
        filters={"client_id": f"eq.{client_id}"},
        order="created_at.desc",
        limit=max(1, min(limit, 100)),
    )
    return {"ok": True, "items": rows}


async def conversation_messages(client_id: str, user_id: str, conversation_id: str) -> Dict[str, Any]:
    conversations = await sb_select(
        "ai_conversations",
        filters={
            "id": f"eq.{conversation_id}",
            "client_id": f"eq.{client_id}",
            "user_id": f"eq.{user_id}",
        },
        limit=1,
    )
    if not conversations:
        raise RuntimeError("CONVERSATION_NOT_FOUND")
    messages = await sb_select(
        "ai_messages",
        filters={
            "conversation_id": f"eq.{conversation_id}",
            "client_id": f"eq.{client_id}",
            "user_id": f"eq.{user_id}",
        },
        order="created_at.asc",
        limit=100,
    )
    return {"ok": True, "conversation": conversations[0], "messages": messages}


async def ask_intelligence(
    *,
    client_id: str,
    user_id: str,
    question: str,
    conversation_id: str | None,
    start: str | None,
    end: str | None,
) -> Dict[str, Any]:
    clean_question = " ".join(question.split())
    if len(clean_question) < 3 or len(clean_question) > 600:
        raise RuntimeError("QUESTION_INVALID")
    if not provider_configured():
        raise RuntimeError("AI_PROVIDER_NOT_CONFIGURED")
    snapshot = await calculate_intelligence_snapshot(client_id=client_id, start=start, end=end)
    period = snapshot["period"]
    analysis_rows = await sb_select(
        "ai_analyses",
        filters={
            "client_id": f"eq.{client_id}",
            "period_start": f"eq.{period['start']}",
            "period_end": f"eq.{period['end']}",
            "status": "eq.completed",
        },
        order="created_at.desc",
        limit=1,
    )
    analysis_id = _text((analysis_rows[0] if analysis_rows else {}).get("id")) or None
    if conversation_id:
        existing = await conversation_messages(client_id, user_id, conversation_id)
        conversation = existing["conversation"]
    else:
        conversation = await sb_insert(
            "ai_conversations",
            {
                "client_id": client_id,
                "user_id": user_id,
                "title": clean_question[:90],
            },
        )
    resolved_conversation_id = _text((conversation or {}).get("id"))
    if not resolved_conversation_id:
        raise RuntimeError("CONVERSATION_CREATE_FAILED")
    user_message = await sb_insert(
        "ai_messages",
        {
            "conversation_id": resolved_conversation_id,
            "client_id": client_id,
            "user_id": user_id,
            "analysis_id": analysis_id,
            "role": "user",
            "content": {"question": clean_question},
            "period_start": period["start"],
            "period_end": period["end"],
            "sources": snapshot["sources"],
        },
    )
    answer = await _call_provider(
        payload={
            "question": clean_question,
            "period": period,
            "metrics": snapshot["metrics"],
            "sources": snapshot["sources"],
            "quality": snapshot["quality"],
            "crossings": snapshot["crossings"],
            "top_campaigns": snapshot["top_campaigns"],
        },
        schema=ANSWER_SCHEMA,
        instructions=(
            "Responda sobre a empresa usando somente os agregados fornecidos. "
            "Não invente valores e não conclua causalidade a partir de correlação. "
            "Use metric_ids existentes para sustentar a resposta. "
            "Não escreva algarismos nos textos; os valores serão exibidos a partir dos metric_ids. "
            "Inclua limitações e próximos passos concretos, sem prometer resultados."
        ),
    )
    allowed_metrics = {metric["id"] for metric in snapshot["metrics"]}
    answer["metric_ids"] = [item for item in answer.get("metric_ids") or [] if item in allowed_metrics]
    assistant_message = await sb_insert(
        "ai_messages",
        {
            "conversation_id": resolved_conversation_id,
            "client_id": client_id,
            "user_id": user_id,
            "analysis_id": analysis_id,
            "role": "assistant",
            "content": answer,
            "period_start": period["start"],
            "period_end": period["end"],
            "sources": snapshot["sources"],
        },
    )
    await sb_update(
        "ai_conversations",
        filters={
            "id": f"eq.{resolved_conversation_id}",
            "client_id": f"eq.{client_id}",
            "user_id": f"eq.{user_id}",
        },
        patch={"updated_at": datetime.now(timezone.utc).isoformat()},
        returning="minimal",
    )
    return {
        "ok": True,
        "conversation_id": resolved_conversation_id,
        "user_message": user_message,
        "assistant_message": assistant_message,
        "snapshot": snapshot,
    }
