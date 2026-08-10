"""Payload executivo: agrega, para client_id + período, os números JÁ
CALCULADOS de cada fonte (Shopify, Meta, Google Ads, GA4) em um único
formato estável. Usado pelo Dashboard ("Operação real") e pela Intelligence
(contexto para a IA) — nenhum dos dois recalcula nada, só exibe/interpreta.

Regra de transparência: `total_paid_media.included_paid_sources` sempre
lista exatamente quais fontes de mídia paga entraram na soma de
`paid_media_spend`. Google Ads nunca aparece incluído enquanto o gasto não
estiver persistido — melhor mostrar "retorno sobre mídia conectada" (só
Meta) do que fingir um total que não existe.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Optional

from .dashboard_paid import _date_window, _safe_float, _safe_int, compute_mer, get_paid_dashboard
from .ga4_connections import resolve_ga4_connection_context
from .ga4_reporting import build_ga4_report, resolve_ga4_report_period
from .ig_dashboard import get_dashboard as get_organic_dashboard
from .shopify_oauth import resolve_shopify_connection_context
from .shopify_reporting import (
    build_shopify_customers_report,
    build_shopify_report,
    resolve_shopify_report_period,
)


def _previous_window(since: str, until: str) -> tuple[str, str]:
    since_date = date.fromisoformat(since)
    until_date = date.fromisoformat(until)
    period_len = (until_date - since_date).days + 1
    prev_until = since_date - timedelta(days=1)
    prev_since = prev_until - timedelta(days=period_len - 1)
    return prev_since.isoformat(), prev_until.isoformat()


async def _build_shopify_section(
    *, client_id: str, connection_id: Optional[str], since: str, until: str
) -> Optional[Dict[str, Any]]:
    try:
        context = await resolve_shopify_connection_context(
            client_id, connection_id=connection_id, required_scopes=("read_orders", "read_customers"),
        )
    except Exception:
        return None
    period = resolve_shopify_report_period(start=since, end=until)
    report = await build_shopify_report(client_id=client_id, shop_domain=context.shop_domain, period=period)
    customers = await build_shopify_customers_report(client_id=client_id, shop_domain=context.shop_domain, period=period)
    summary = report.get("summary") or {}
    customers_summary = customers.get("summary") or {}
    total_customers = _safe_int(customers_summary.get("total_customers"))
    returning_customers = _safe_int(customers_summary.get("recurring_customers"))
    return {
        "connected": True,
        "shop_domain": context.shop_domain,
        "gross_revenue": _safe_float(summary.get("revenue_total")),
        "net_revenue": _safe_float(summary.get("net_revenue")),
        "orders": _safe_int(summary.get("orders")),
        "paid_orders": _safe_int(summary.get("paid_orders")),
        "cancelled_orders": _safe_int(summary.get("cancelled_orders")),
        "refunds": _safe_int(summary.get("refunds_count")),
        "refunded_amount": _safe_float(summary.get("refunded_amount")),
        "refunds_occurred_in_period_count": _safe_int(summary.get("refunds_occurred_in_period_count")),
        "refunds_occurred_in_period_amount": _safe_float(summary.get("refunds_occurred_in_period_amount")),
        "average_order_value": _safe_float(summary.get("average_ticket")),
        "new_customers": max(total_customers - returning_customers, 0),
        "returning_customers": returning_customers,
        # Série diária já calculada com a mesma regra temporal do resumo
        # (ver build_daily_commercial_series) — consumida pelo Dashboard
        # diário sem recálculo no frontend.
        "daily": report.get("daily_commercial") or [],
    }


async def _build_meta_section(
    *, client_id: str, connection_id: Optional[str], since: str, until: str
) -> Dict[str, Any]:
    # Erro isolado: uma falha ao consultar o Meta nunca pode derrubar o
    # payload inteiro (Shopify/GA4 continuam disponíveis na mesma resposta).
    try:
        paid = await get_paid_dashboard(client_id, connection_id=connection_id, start=since, end=until)
    except Exception:
        return {"connected": False, "spend": None, "attributed_revenue": None, "roas": None, "daily": []}
    connected = bool(paid.get("connection_id"))
    totals = paid.get("totals") or {}
    roas = totals.get("roas") if isinstance(totals.get("roas"), (int, float)) else None
    daily_source = paid.get("daily") or []
    daily = [
        {
            "date": str(row.get("date") or ""),
            "spend": _safe_float(row.get("spend")),
            "attributed_revenue": _safe_float(row.get("revenue")),
            "purchases": _safe_float(row.get("conversions")),
            # ROAS diário já vem calculado por dia em _finalize_paid_metric
            # (receita do dia / spend do MESMO dia) — nunca recalculado aqui.
            "roas": row.get("roas") if isinstance(row.get("roas"), (int, float)) else None,
        }
        for row in daily_source
        if row.get("date")
    ] if connected else []
    return {
        "connected": connected,
        "spend": _safe_float(totals.get("spend")) if connected else None,
        "attributed_revenue": _safe_float(totals.get("revenue")) if connected else None,
        "roas": roas,
        "daily": daily,
    }


def _build_google_ads_section() -> Dict[str, Any]:
    # Gasto do Google Ads ainda não é persistido — nunca simular um total
    # "Meta + Google" com dado que não existe.
    return {
        "connected": False,
        "reason": "google_ads_spend_not_persisted",
        "spend": None,
        "attributed_revenue": None,
        "roas": None,
    }


async def _build_ga4_section(
    *, client_id: str, connection_id: Optional[str], since: str, until: str
) -> Optional[Dict[str, Any]]:
    try:
        context = await resolve_ga4_connection_context(client_id, connection_id)
    except Exception:
        return None
    period = resolve_ga4_report_period(start=since, end=until)
    report = await build_ga4_report(client_id=client_id, property_id=context.property_id, period=period)
    summary = report.get("summary") or {}
    return {
        "connected": bool((report.get("meta") or {}).get("data_available")),
        "sessions": _safe_int(summary.get("sessions")),
        "users": _safe_int(summary.get("total_users")),
        "purchases": _safe_int(summary.get("purchases")),
        # Receita SOMENTE do GA4 (tracking do site) — nunca somar/misturar
        # com a receita real da loja (Shopify) nem com receita atribuída
        # (Meta/Google Ads). É uma métrica própria, de outra fonte.
        "revenue": _safe_float(summary.get("total_revenue")),
        "daily": (report.get("trends") or {}).get("daily") or [],
        "freshness": (report.get("meta") or {}).get("freshness"),
    }


async def _build_instagram_section(
    *, client_id: str, connection_id: Optional[str], since: str, until: str
) -> Optional[Dict[str, Any]]:
    try:
        report = await get_organic_dashboard(
            client_id=client_id, connection_id=connection_id, start=since, end=until,
        )
    except Exception:
        return None
    return {
        "connected": bool(report.get("connection_id")),
        "last_success_at": report.get("last_sync_at"),
        "stale": report.get("stale"),
        "last_error": report.get("last_error"),
        "coverage": report.get("coverage"),
        "daily": report.get("daily") or [],
    }


def _build_total_paid_media(
    *, meta: Dict[str, Any], google_ads: Dict[str, Any], shopify: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    included_paid_sources: list[str] = []
    spend = 0.0
    if meta.get("connected"):
        included_paid_sources.append("meta")
        spend += _safe_float(meta.get("spend"))
    if google_ads.get("connected"):
        included_paid_sources.append("google_ads")
        spend += _safe_float(google_ads.get("spend"))
    net_revenue = shopify.get("net_revenue") if shopify else None
    blended_roas = compute_mer(net_revenue, spend) if (shopify and included_paid_sources) else None
    return {
        "paid_media_spend": round(spend, 2) if included_paid_sources else 0.0,
        "included_paid_sources": included_paid_sources,
        "blended_roas": blended_roas,
    }


def _build_daily_series(
    *, shopify: Optional[Dict[str, Any]], meta: Dict[str, Any], included_paid_sources: list[str],
    since: str | None = None, until: str | None = None, ga4: Optional[Dict[str, Any]] = None,
    instagram: Optional[Dict[str, Any]] = None,
) -> list[Dict[str, Any]]:
    """Combina as séries diárias já calculadas de Shopify e Meta por data —
    nunca recalcula nada aqui, só junta pelo mesmo dia. blended_roas do dia
    usa net_revenue do MESMO dia / connected_paid_spend do MESMO dia (nunca
    receita acumulada nem spend de outro dia)."""
    shopify_daily = {row["date"]: row for row in (shopify or {}).get("daily") or [] if row.get("date")}
    meta_daily = {row["date"]: row for row in meta.get("daily") or [] if row.get("date")}
    ga4_daily = {row["date"]: row for row in (ga4 or {}).get("daily") or [] if row.get("date")}
    instagram_daily = {row["date"]: row for row in (instagram or {}).get("daily") or [] if row.get("date")}
    if since and until:
        first_day = date.fromisoformat(since)
        last_day = date.fromisoformat(until)
        dates = [(first_day + timedelta(days=offset)).isoformat() for offset in range((last_day - first_day).days + 1)]
    else:
        dates = sorted(set(shopify_daily) | set(meta_daily) | set(ga4_daily) | set(instagram_daily))

    series: list[Dict[str, Any]] = []
    for day in dates:
        shopify_row = shopify_daily.get(day)
        meta_row = meta_daily.get(day)
        connected_paid_spend = _safe_float((meta_row or {}).get("spend")) if "meta" in included_paid_sources and meta_row else 0.0
        net_revenue = shopify_row.get("net_revenue") if shopify_row else None
        blended_roas = (
            compute_mer(net_revenue, connected_paid_spend)
            if (shopify_row is not None and included_paid_sources)
            else None
        )
        series.append(
            {
                "date": day,
                "shopify": shopify_row,
                "meta": meta_row,
                "ga4": ga4_daily.get(day),
                "instagram": instagram_daily.get(day),
                "connected_paid_spend": round(connected_paid_spend, 2) if (meta_row and "meta" in included_paid_sources) else 0.0,
                "blended_return": blended_roas,
                "blended_roas": blended_roas,
            }
        )
    return series


def _delta(current: Optional[float], previous: Optional[float]) -> Dict[str, Optional[float]]:
    if current is None or previous is None:
        return {"absolute": None, "percent": None}
    absolute = current - previous
    percent = (absolute / previous * 100.0) if previous not in (0, 0.0) else None
    return {"absolute": round(absolute, 2), "percent": round(percent, 2) if percent is not None else None}


async def _build_period_payload(
    *,
    client_id: str,
    since: str,
    until: str,
    days: int,
    meta_connection_id: Optional[str],
    shopify_connection_id: Optional[str],
    ga4_connection_id: Optional[str],
) -> Dict[str, Any]:
    shopify = await _build_shopify_section(
        client_id=client_id, connection_id=shopify_connection_id, since=since, until=until,
    )
    meta = await _build_meta_section(
        client_id=client_id, connection_id=meta_connection_id, since=since, until=until,
    )
    google_ads = _build_google_ads_section()
    ga4 = await _build_ga4_section(
        client_id=client_id, connection_id=ga4_connection_id, since=since, until=until,
    )
    instagram = await _build_instagram_section(
        client_id=client_id, connection_id=None, since=since, until=until,
    )
    total_paid_media = _build_total_paid_media(meta=meta, google_ads=google_ads, shopify=shopify)
    daily = _build_daily_series(
        since=since, until=until, shopify=shopify, meta=meta, ga4=ga4, instagram=instagram,
        included_paid_sources=total_paid_media["included_paid_sources"],
    )
    return {
        "period": {"start": since, "end": until, "days": (date.fromisoformat(until) - date.fromisoformat(since)).days + 1},
        "shopify": shopify,
        "meta": meta,
        "google_ads": google_ads,
        "total_paid_media": total_paid_media,
        "ga4": ga4,
        "instagram": instagram,
        "daily": daily,
    }


async def get_executive_summary(
    client_id: str,
    *,
    days: int = 30,
    month: str | None = None,
    start: str | None = None,
    end: str | None = None,
    meta_connection_id: str | None = None,
    shopify_connection_id: str | None = None,
    ga4_connection_id: str | None = None,
    include_previous_period: bool = True,
) -> Dict[str, Any]:
    since, until = _date_window(days, month, start=start, end=end)
    current = await _build_period_payload(
        client_id=client_id, since=since, until=until, days=days,
        meta_connection_id=meta_connection_id,
        shopify_connection_id=shopify_connection_id,
        ga4_connection_id=ga4_connection_id,
    )

    previous_payload = None
    deltas = None
    if include_previous_period:
        prev_since, prev_until = _previous_window(since, until)
        previous_payload = await _build_period_payload(
            client_id=client_id, since=prev_since, until=prev_until, days=days,
            meta_connection_id=meta_connection_id,
            shopify_connection_id=shopify_connection_id,
            ga4_connection_id=ga4_connection_id,
        )
        cur_shopify = current.get("shopify") or {}
        prev_shopify = previous_payload.get("shopify") or {}
        cur_meta = current.get("meta") or {}
        prev_meta = previous_payload.get("meta") or {}
        cur_total = current.get("total_paid_media") or {}
        prev_total = previous_payload.get("total_paid_media") or {}
        deltas = {
            "shopify_net_revenue": _delta(cur_shopify.get("net_revenue"), prev_shopify.get("net_revenue")),
            "shopify_orders": _delta(cur_shopify.get("orders"), prev_shopify.get("orders")),
            "meta_spend": _delta(cur_meta.get("spend"), prev_meta.get("spend")),
            "meta_roas": _delta(cur_meta.get("roas"), prev_meta.get("roas")),
            "blended_roas": _delta(cur_total.get("blended_roas"), prev_total.get("blended_roas")),
        }

    return {
        "ok": True,
        "client_id": client_id,
        **current,
        "previous_period": previous_payload,
        "deltas": deltas,
    }
