from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from .ig_supabase import sb_rpc, sb_select
from .freshness import source_freshness
from .ga4_attribution import build_channel_group_items, campaign_investments, enrich_campaign_items
from .periods import resolve_period

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
    period = resolve_period(start=start, end=end, days=days, max_days=366)
    return GA4ReportPeriod(start=period.start, end=period.end, days=period.days)


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
        bucket["user_count_semantics"] = "sum_of_daily_users"
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
        if "channel_group" in bucket and not bucket["channel_group"] and _safe_str(row.get("channel_group")):
            bucket["channel_group"] = _safe_str(row.get("channel_group"))
    for bucket in grouped.values():
        bucket["purchase_revenue"] = round(_safe_float(bucket.get("purchase_revenue")), 2)
        bucket["total_revenue"] = round(_safe_float(bucket.get("total_revenue")), 2)
    return list(grouped.values())


def _period_filter(period: GA4ReportPeriod) -> str:
    return f"(stat_date.gte.{period.start.isoformat()},stat_date.lte.{period.end.isoformat()})"


async def _select_persisted_pages(table: str, *, select: str, filters: dict, order: str, limit: int) -> list:
    rows = []
    for offset in range(0, 200000, 1000):
        page = await sb_select(table, select=select, filters=filters, order=order + ",id.asc", limit=1000, offset=offset)
        rows.extend(page)
        if len(page) < 1000:
            return rows
    raise RuntimeError("Paginação de fatos GA4 incompleta.")


async def _select_ga4_daily_rows(*, client_id: str, property_id: str, period: GA4ReportPeriod) -> List[Dict[str, Any]]:
    return await _select_persisted_pages(
        "ga4_daily_stats",
        select=(
            "id,client_id,property_id,stat_date,sessions,engaged_sessions,screen_page_views,key_events,transactions,new_users,active_users,total_users,event_count,"
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
    return await _select_persisted_pages(
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


_CAMPAIGN_SELECT = (
    "id,client_id,property_id,stat_date,campaign_name,source_medium,source,medium,sessions,active_users,"
    "total_users,event_count,ecommerce_purchases,purchase_revenue,total_revenue,updated_at"
)


async def _select_ga4_campaign_rows(*, client_id: str, property_id: str, period: GA4ReportPeriod) -> List[Dict[str, Any]]:
    filters = {
        "client_id": f"eq.{client_id}",
        "property_id": f"eq.{property_id}",
        "and": _period_filter(period),
    }
    try:
        rows = await _select_persisted_pages(
            "ga4_campaign_stats", select=_CAMPAIGN_SELECT + ",channel_group",
            filters=filters, order="stat_date.asc", limit=10000,
        )
    except Exception:
        # Migration 046 (channel_group) ainda não aplicada: mesma leitura de antes.
        rows = await _select_persisted_pages(
            "ga4_campaign_stats", select=_CAMPAIGN_SELECT,
            filters=filters, order="stat_date.asc", limit=10000,
        )
    # Isolamento: só linhas da empresa e da propriedade pedidas.
    return [row for row in rows if _safe_str(row.get("client_id")) == client_id
            and _safe_str(row.get("property_id")) == property_id]


async def _select_ga4_event_rows(*, client_id: str, property_id: str, period: GA4ReportPeriod) -> List[Dict[str, Any]]:
    return await _select_persisted_pages(
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


GA4_ROLLUP_PARTS = ("channels", "campaigns", "events")


async def _select_ga4_rollup(
    *, client_id: str, property_id: str, period: GA4ReportPeriod, parts: Iterable[str] = GA4_ROLLUP_PARTS,
) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    """Canais/campanhas/eventos já somados no banco (migração 047).

    Uma chamada em vez de baixar todas as linhas diárias em páginas de 1.000.
    Devolve None quando a função ainda não existe ou falha: quem chama volta
    para a leitura linha a linha, com o mesmo resultado.
    """
    wanted = [part for part in parts if part]
    try:
        payload = await sb_rpc("ga4_report_rollup", {
            "p_client_id": client_id, "p_property_id": property_id,
            "p_start": period.start.isoformat(), "p_end": period.end.isoformat(), "p_parts": wanted,
        })
    except Exception as exc:  # noqa: BLE001 — só o tipo vai para o log
        print(f"[ga4_reporting][rollup] status=fallback error={exc.__class__.__name__}")
        return None
    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
        payload = payload[0].get("ga4_report_rollup", payload[0])
    if not isinstance(payload, dict):
        print("[ga4_reporting][rollup] status=fallback error=unexpected_payload")
        return None
    # Isolamento: a resposta tem de ser da empresa e da propriedade pedidas.
    if _safe_str(payload.get("client_id")) != client_id or _safe_str(payload.get("property_id")) != property_id:
        print("[ga4_reporting][rollup] status=fallback error=scope_mismatch")
        return None
    out: Dict[str, List[Dict[str, Any]]] = {}
    for part in wanted:
        rows = payload.get(part)
        if not isinstance(rows, list):
            print(f"[ga4_reporting][rollup] status=fallback error=missing_{part}")
            return None
        out[part] = [row for row in rows if isinstance(row, dict)]
    return out


def _source_row_count(rows: List[Dict[str, Any]]) -> int:
    """Linhas diárias por trás das somas (row_count no rollup; 1 por linha no caminho antigo)."""
    return sum(_safe_int(row.get("row_count")) if "row_count" in row else 1 for row in rows)


async def _ga4_period_rows(
    *, client_id: str, property_id: str, period: GA4ReportPeriod, parts: Iterable[str] = GA4_ROLLUP_PARTS,
) -> Dict[str, List[Dict[str, Any]]]:
    parts = tuple(parts)
    rollup = await _select_ga4_rollup(client_id=client_id, property_id=property_id, period=period, parts=parts)
    if rollup is not None:
        return rollup
    readers = {
        "channels": _select_ga4_channel_rows,
        "campaigns": _select_ga4_campaign_rows,
        "events": _select_ga4_event_rows,
    }
    results = await asyncio.gather(*(
        readers[part](client_id=client_id, property_id=property_id, period=period) for part in parts
    ))
    return dict(zip(parts, results))


def _normalize_period_filters(
    *,
    client_id: str,
    property_id: str,
    period: GA4ReportPeriod,
) -> tuple[str, str, GA4ReportPeriod]:
    resolved_client_id = _safe_str(client_id)
    resolved_property_id = _safe_str(property_id).removeprefix("properties/").strip()
    if not resolved_client_id:
        raise RuntimeError("client_id é obrigatório para consultar o GA4.")
    if not resolved_property_id:
        raise RuntimeError("property_id é obrigatório para consultar o GA4.")
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
        for metric in ("engaged_sessions", "screen_page_views", "key_events", "transactions", "new_users"):
            bucket[metric] = _safe_int(row.get(metric))
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
    # Campos numéricos legados são somas diárias, nunca usuários únicos do período.
    if not daily_rows:
        return {
            "user_count_semantics": "sum_of_daily_users",
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
        "user_count_semantics": "sum_of_daily_users",
        "sessions": sessions,
        **{metric: sum(_safe_int(row.get(metric)) for row in daily_rows) for metric in ("engaged_sessions", "screen_page_views", "key_events", "transactions", "new_users")},
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
            "channel_group": _safe_str(row.get("channel_group")) or None,
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
                "user_count_semantics": "sum_of_daily_users",
                "event_count": 0,
                "total_users": 0,
                "first_seen_at": None,
                "last_seen_at": None,
            },
        )
        bucket["event_count"] = _safe_int(bucket.get("event_count")) + _safe_int(row.get("event_count"))
        bucket["total_users"] = _safe_int(bucket.get("total_users")) + _safe_int(row.get("total_users"))
        first_seen = _safe_str(row.get("first_seen_at") or row.get("stat_date")) or None
        last_seen = _safe_str(row.get("last_seen_at") or row.get("stat_date")) or None
        if first_seen and (not bucket.get("first_seen_at") or first_seen < _safe_str(bucket.get("first_seen_at"))):
            bucket["first_seen_at"] = first_seen
        if last_seen and (not bucket.get("last_seen_at") or last_seen > _safe_str(bucket.get("last_seen_at"))):
            bucket["last_seen_at"] = last_seen

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
        "user_count_semantics": "sum_of_daily_users",
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
        "user_count_semantics": "sum_of_daily_event_users",
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


async def _campaign_items_with_investment(
    client_id: str, period: GA4ReportPeriod, rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    items = _build_campaign_items(rows)
    if not items:
        return items
    investments = await campaign_investments(client_id, period.start.isoformat(), period.end.isoformat())
    return enrich_campaign_items(items, investments)


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

    daily_source_rows, period_rows = await asyncio.gather(
        _select_ga4_daily_rows(
            client_id=resolved_client_id, property_id=resolved_property_id, period=resolved_period,
        ),
        _ga4_period_rows(
            client_id=resolved_client_id, property_id=resolved_property_id, period=resolved_period,
        ),
    )
    channel_source_rows = period_rows["channels"]
    campaign_source_rows = period_rows["campaigns"]
    event_source_rows = period_rows["events"]

    daily_rows = _build_daily_rows(resolved_period, daily_source_rows)
    campaign_items = await _campaign_items_with_investment(
        resolved_client_id, resolved_period, campaign_source_rows,
    )
    event_items = _build_event_items(event_source_rows)
    event_lookup = _event_item_lookup(event_items)
    last_synced_at = None
    for row in daily_source_rows:
        updated_at = _safe_str(row.get("updated_at"))
        if updated_at and (not last_synced_at or updated_at > last_synced_at):
            last_synced_at = updated_at
    freshness = source_freshness(
        "ga4",
        last_sync_at=last_synced_at,
        data_available=bool(daily_source_rows or channel_source_rows or event_source_rows),
    )

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
        "campaigns": campaign_items,
        "acquisition": {
            "channel_groups": build_channel_group_items(campaign_items),
            "has_purchases": any(_safe_int(item.get("ecommerce_purchases")) > 0 for item in campaign_items),
            "revenue_source": "ga4_purchase_event",
            "notes": [
                "Receita atribuída pelo GA4 (evento purchase): não é o faturamento confirmado do e-commerce.",
                "Eventos purchase históricos podem conter duplicações.",
                "Investimento e ROAS só aparecem quando a campanha do GA4 corresponde a uma única campanha do Google Ads ou da Meta com o mesmo nome.",
            ],
        },
        "events": event_items,
        "meta": {
            "user_count_semantics": "sum_of_daily_users",
            "coverage": {
                "coverage_start": min((str(row["stat_date"]) for row in daily_source_rows), default=None),
                "coverage_end": max((str(row["stat_date"]) for row in daily_source_rows), default=None),
                "distinct_dates": len({row["stat_date"] for row in daily_source_rows}),
                "expected_days": resolved_period.days,
                "completeness": "unknown",
            },
            "last_synced_at": last_synced_at,
            "data_available": freshness["data_available"],
            "stale": freshness["stale"],
            "freshness": freshness,
            "daily_rows": len(daily_source_rows),
            "channel_rows": _source_row_count(channel_source_rows),
            "campaign_rows": _source_row_count(campaign_source_rows),
            "event_rows": _source_row_count(event_source_rows),
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
    rows = (await _ga4_period_rows(
        client_id=resolved_client_id,
        property_id=resolved_property_id,
        period=resolved_period,
        parts=("channels",),
    ))["channels"]
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
    rows = (await _ga4_period_rows(
        client_id=resolved_client_id,
        property_id=resolved_property_id,
        period=resolved_period,
        parts=("campaigns",),
    ))["campaigns"]
    items = await _campaign_items_with_investment(resolved_client_id, resolved_period, rows)
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
    rows = (await _ga4_period_rows(
        client_id=resolved_client_id,
        property_id=resolved_property_id,
        period=resolved_period,
        parts=("events",),
    ))["events"]
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
