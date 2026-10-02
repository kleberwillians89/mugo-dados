from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List
from zoneinfo import ZoneInfo

import httpx

from .periods import resolve_period
from .generic_connections import list_generic_connections
from .business_context import load_business_context
from .commerce_context import resolve_commerce_context
from .external_research import external_research_context
from .ig_supabase import sb_insert, sb_select, sb_update
from .instagram_organic_history import aggregate_instagram_months


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

ANALYSIS_INSTRUCTIONS = """
Você é a camada de interpretação executiva do Mugô Dados. Use somente o JSON recebido.
Os valores, totais, razões e variações já foram calculados pelo backend: nunca os recalcule,
complete, estime ou substitua. Ausente, null, disconnected e connected_no_data não são zero.

Raciocine nesta ordem: o que mudou; magnitude; referência comparável; impacto de negócio;
relações sustentadas; riscos ou contradições; oportunidade; próximo passo proporcional.
Priorize poucas conclusões por magnitude, impacto e qualidade. metric_changes separa variação
percentual, impacto absoluto e importância da métrica. material_metric_ids são candidatos, não
uma ordem automática; primary_metric_ids podem disputar o destaque principal. Uma mudança pequena
em supporting_metric_ids pode ser evidência secundária de uma contradição, nunca destaque isolado.
O resumo executivo deve ter de uma a três frases e contar uma única história.

Separe rigorosamente fato, interpretação e hipótese. Afirme fatos demonstrados com clareza.
Uma interpretação deve citar metric_ids que, em conjunto, a sustentem. Possíveis explicações
devem usar linguagem de hipótese ("os dados sugerem", "vale investigar", "ocorreu no mesmo
período") e nunca "porque", "causou", "provou" ou equivalentes sem evidência causal explícita.

Leia métricas relacionadas em conjunto quando disponíveis: receita com pedidos e ticket;
investimento com receita atribuída, compras e ROAS; sessões com conversão, pedidos e receita.
Ao dizer que a loja vendeu ou faturou, use exclusivamente receita/pedidos do provider de
e-commerce informado em commerce_context (FBITS ou Shopify) — nunca presuma a plataforma e nunca
misture a semântica de uma com a da outra. Em FBITS com kpi_source fbits_dashboard, receita,
pedidos e ticket são indicadores oficiais da própria loja: trate-os como definitivos e não os
reconstrua a partir de situações de pedido. Meta e Google medem receita atribuída segundo cada
plataforma; descreva sempre como atribuição, nunca como faturamento real nem como prova de
causalidade sobre a receita total da loja.
Procure contradições úteis, como receita e pedidos em direções opostas. Não use benchmark ou
meta que não esteja no payload. Não classifique automaticamente alta como boa ou queda como ruim.

Use historical_context apenas para contextualizar o período principal. Dois meses representam
movimento, não tendência; só descreva tendência quando recent_trend.is_trend for verdadeiro.
Não alegue sazonalidade com um único ano. Meses parciais não são diretamente comparáveis a meses
completos. Respeite source_coverage: uma fonte não explica meses anteriores à sua cobertura.
roas_real usa a receita real do provider de e-commerce do tenant; attributed_roas usa a atribuição
da plataforma e os conceitos devem permanecer explicitamente separados.

Respeite analysis_policy. Cobertura indica até que data existem dados; freshness indica quando o
job terminou. Não confunda esses conceitos. Não cruze fontes quando cross_source_comparison_allowed
for falso e explique limitações quando covers_period_end for falso.
Instagram account reach vem apenas de instagram_account_context. A soma de reach de publicações
em instagram_content_context deve ser chamada "alcance dos conteúdos" e nunca alcance da conta.
Stories sem métricas persistidas são indisponíveis, não zero, e não reduzem a cobertura de Feed/Reels.
Se includes_partial_today for verdadeiro, registre que os dados de hoje ainda estão em formação
e não compare o dia incompleto com um dia completo. Métricas em unavailable_metric_ids não podem
sustentar conclusão. Sem comparação anterior, descreva nível observado sem inventar tendência.

Cada insight deve conter metric_ids e sources válidos. Recomendações com baixa evidência devem
mandar investigar; com evidência moderada, testar; somente evidência forte permite priorizar,
escalar ou corrigir. Evite recomendações genéricas. Não escreva algarismos nos textos; a interface
renderiza números canônicos a partir dos metric_ids. Não prometa resultado.
""".strip()

ANSWER_INSTRUCTIONS = """
Responda em português brasileiro usando somente os agregados fornecidos. A resposta deve partir
da pergunta de negócio, selecionar poucas evidências materiais e distinguir fato, interpretação
e hipótese. Não recalcule nem invente valores; null e fonte sem dados não significam zero.
Não conclua causalidade a partir de simultaneidade e não use benchmark ou meta ausente.
Respeite analysis_policy, inclusive temporalidade entre fontes e parcialidade do dia atual.
Use apenas metric_ids existentes. Recomendações devem ser específicas e proporcionais à evidência:
investigar quando limitada, testar quando moderada e priorizar somente quando forte.
Não escreva algarismos nos textos; os valores são exibidos a partir dos metric_ids.
""".strip()

INTELLIGENCE_NOISE_PERCENT_THRESHOLD = float(os.getenv("INTELLIGENCE_NOISE_PERCENT_THRESHOLD", "5"))
INTELLIGENCE_MATERIAL_CURRENCY_ABSOLUTE = float(os.getenv("INTELLIGENCE_MATERIAL_CURRENCY_ABSOLUTE", "10000"))
INTELLIGENCE_CROSS_SOURCE_MAX_LAG_HOURS = float(os.getenv("INTELLIGENCE_CROSS_SOURCE_MAX_LAG_HOURS", "6"))

PRIMARY_BUSINESS_METRICS = {"revenue", "orders", "average_ticket", "investment", "roas", "conversions"}
RELATED_METRIC_GROUPS = (
    {"revenue", "orders", "average_ticket"},
    {"investment", "meta_revenue", "revenue", "roas", "conversions", "cpa"},
    {"sessions", "conversion_rate", "orders", "revenue"},
)


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


async def _query_timestamp_period(
    table: str, *, client_id: str, select: str, start: date, end: date, limit: int = 10000,
) -> List[Dict[str, Any]]:
    return await sb_select(
        table,
        select=select,
        filters={
            "client_id": f"eq.{client_id}",
            "and": f"(timestamp.gte.{start.isoformat()}T00:00:00,timestamp.lt.{(end + timedelta(days=1)).isoformat()}T00:00:00)",
        },
        order="timestamp.asc",
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


def _historical_context(
    rows: List[Dict[str, Any]], snapshots: List[Dict[str, Any]], year: int,
    selected_start: date, selected_end: date, instagram_media: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Compact, aggregate-only historical context. It intentionally contains no order/customer data."""
    source_coverage = {
        _text(item.get("provider")): {
            "start": item.get("data_min_available"), "end": item.get("data_max_available"),
        } for item in snapshots
    }
    providers = {
        "shopify": ("shopify_net_revenue", "shopify_orders"),
        "meta": ("meta_spend", "meta_attributed_revenue", "meta_purchases"),
        "google_ads": ("google_ads_spend", "google_ads_conversion_value", "google_ads_conversions"),
        "ga4": ("ga4_sessions", "ga4_users"),
    }
    months: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        metric_date = _text(row.get("metric_date"))
        if metric_date.startswith(f"{year}-"):
            months.setdefault(metric_date[:7], []).append(row)
    monthly: List[Dict[str, Any]] = []
    for month, month_rows in sorted(months.items()):
        shopify_available = any(row.get("shopify_net_revenue") is not None or row.get("shopify_orders") is not None for row in month_rows)
        meta_available = any(row.get("meta_spend") is not None for row in month_rows)
        google_available = any(row.get("google_ads_spend") is not None for row in month_rows)
        if not (shopify_available or meta_available or google_available):
            continue
        revenue, orders = _sum(month_rows, "shopify_net_revenue"), _sum(month_rows, "shopify_orders")
        meta_spend, meta_attr = _sum(month_rows, "meta_spend"), _sum(month_rows, "meta_attributed_revenue")
        google_spend, google_attr = _sum(month_rows, "google_ads_spend"), _sum(month_rows, "google_ads_conversion_value")
        calendar_start = f"{month}-01"
        next_month = (date.fromisoformat(calendar_start).replace(day=28) + timedelta(days=4)).replace(day=1)
        calendar_end = (next_month - timedelta(days=1)).isoformat()
        available_dates = [_text(row.get("metric_date")) for row in month_rows]
        monthly.append({
            "month": month, "coverage_start": min(available_dates), "coverage_end": max(available_dates),
            "is_partial": min(available_dates) > calendar_start or max(available_dates) < calendar_end,
            "shopify": {"available": shopify_available, "revenue": revenue if shopify_available else None, "orders": orders if shopify_available else None, "average_order_value": revenue / orders if shopify_available and orders else (0 if shopify_available else None)},
            "meta": {"available": meta_available, "spend": meta_spend if meta_available else None, "attributed_revenue": meta_attr if meta_available else None, "purchases": _sum(month_rows, "meta_purchases") if meta_available else None, "roas_real": revenue / meta_spend if shopify_available and meta_spend else None, "attributed_roas": meta_attr / meta_spend if meta_spend else None},
            "google_ads": {"available": google_available, "spend": google_spend if google_available else None, "attributed_revenue": google_attr if google_available else None, "conversions": _sum(month_rows, "google_ads_conversions") if google_available else None, "roas_real": revenue / google_spend if shopify_available and google_spend else None, "attributed_roas": google_attr / google_spend if google_spend else None},
        })
    shopify_months = [item for item in monthly if item["shopify"]["available"]]
    complete = [item for item in shopify_months if not item["is_partial"]]
    total_revenue = sum(item["shopify"]["revenue"] for item in complete)
    total_orders = sum(item["shopify"]["orders"] for item in complete)
    recent = complete[-3:]
    direction = None
    if len(recent) >= 3:
        values = [item["shopify"]["revenue"] for item in recent]
        direction = "increasing" if values[0] < values[1] < values[2] else "decreasing" if values[0] > values[1] > values[2] else "mixed"
    instagram_account_rows = [
        row for row in rows
        if any(row.get(field) is not None for field in (
            "instagram_followers", "instagram_reach", "instagram_impressions",
            "instagram_profile_views", "instagram_website_clicks", "instagram_accounts_engaged",
        ))
    ]
    account_dates = sorted(_text(row.get("metric_date")) for row in instagram_account_rows)
    content_months = aggregate_instagram_months(instagram_media or [])
    permanent_dates = sorted(
        str(row.get("timestamp") or "")[:10] for row in (instagram_media or [])
        if str(row.get("media_product_type") or row.get("media_type") or "").upper() != "STORY" and row.get("timestamp")
    )
    story_months = [
        {"month": item["month"], **item["stories"]}
        for item in content_months if item["stories"]["published_count"]
    ]
    story_dates = sorted(
        str(row.get("timestamp") or "")[:10] for row in (instagram_media or [])
        if str(row.get("media_product_type") or row.get("media_type") or "").upper() == "STORY" and row.get("timestamp")
    )
    return {
        "coverage_start": source_coverage.get("shopify", {}).get("start"),
        "coverage_end": source_coverage.get("shopify", {}).get("end"),
        "monthly_summary": monthly,
        "rolling_baselines": {"complete_months": len(complete), "average_monthly_revenue": total_revenue / len(complete) if complete else None, "average_monthly_orders": total_orders / len(complete) if complete else None, "weighted_average_order_value": total_revenue / total_orders if total_orders else None},
        "highs_lows": {"highest_revenue_month": max(complete, key=lambda item: item["shopify"]["revenue"])["month"] if complete else None, "lowest_revenue_month": min(complete, key=lambda item: item["shopify"]["revenue"])["month"] if complete else None},
        "recent_trend": {"evidence_periods": len(recent), "revenue_direction": direction, "is_trend": direction in {"increasing", "decreasing"}},
        "selected_period_context": {"start": selected_start.isoformat(), "end": selected_end.isoformat(), "is_partial_month": selected_end < (selected_end.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)},
        "source_coverage": {provider: source_coverage.get(provider, {"start": None, "end": None}) for provider in providers},
        "instagram_account_context": {
            "coverage_start": account_dates[0] if account_dates else None,
            "coverage_end": account_dates[-1] if account_dates else None,
            "persisted_dates": account_dates,
            "source": "ig_profile_snapshots_via_dashboard_daily_metrics",
        },
        "instagram_content_context": {
            "coverage_start": permanent_dates[0] if permanent_dates else None,
            "coverage_end": permanent_dates[-1] if permanent_dates else None,
            "monthly_summary": content_months,
            "reach_label": "Alcance dos conteúdos",
            "source": "ig_media",
        },
        "instagram_story_context": {
            "coverage_start": story_dates[0] if story_dates else None,
            "coverage_end": story_dates[-1] if story_dates else None,
            "monthly_summary": story_months,
            "source": "ig_media",
        },
    }


async def _read_model_executive_context(
    client_id: str, start_date: date, end_date: date, previous_start: date, previous_end: date
) -> Dict[str, Any]:
    history_start = date(end_date.year, 1, 1)
    history_end = max(end_date, date.today())
    rows, snapshots, instagram_media = await asyncio.gather(
        _query_period(
            "dashboard_daily_metrics", client_id=client_id, select="*", date_column="metric_date",
            start=min(previous_start, history_start), end=history_end, limit=800,
        ),
        sb_select("dashboard_source_snapshots", filters={"client_id": f"eq.{client_id}"}, limit=20),
        _query_timestamp_period(
            "ig_media", client_id=client_id,
            select="timestamp,media_type,media_product_type,insights_json",
            start=date(1970, 1, 1), end=history_end, limit=1000,
        ),
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
            "meta": {"connected": True, "data_available": any(row.get("meta_spend") is not None for row in selected), "spend": meta_spend, "attributed_revenue": meta_revenue, "roas_real": net / meta_spend if meta_spend else None, "attributed_roas": meta_revenue / meta_spend if meta_spend else None, "last_success_at": source("meta").get("last_success_at"), "data_max_available": source("meta").get("data_max_available")},
            "google_ads": {"connected": True, "data_available": any(row.get("google_ads_spend") is not None for row in selected), "spend": google_spend, "attributed_revenue": google_value, "roas_real": net / google_spend if google_spend else None, "attributed_roas": google_value / google_spend if google_spend else None, "last_success_at": source("google_ads").get("last_success_at"), "data_max_available": source("google_ads").get("data_max_available")},
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
    current["historical_context"] = _historical_context(
        rows, snapshots, end_date.year, start_date, end_date, instagram_media
    )
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
    # Provider de e-commerce resolvido pela conexão do tenant, nunca pelo nome
    # da empresa. FBITS entrega os KPIs oficiais da própria loja; Shopify, os
    # agregados já lidos do read model.
    commerce = await resolve_commerce_context(
        client_id=client_id, start=start_date.isoformat(), end=end_date.isoformat(),
        shopify_section={
            **shopify,
            "previous": previous.get("shopify") or {},
            "deltas": deltas,
        },
    )
    commerce_metrics = commerce.get("metrics") or {}
    # Contexto editorial da empresa e pesquisa externa. Sem provider externo
    # configurado, o bloco volta not_configured e nada é inventado.
    business, external = await asyncio.gather(
        load_business_context(client_id),
        external_research_context(client_id=client_id),
    )

    def commerce_metric(name: str) -> Dict[str, Any]:
        return commerce_metrics.get(name) if isinstance(commerce_metrics.get(name), dict) else {}

    commerce_source_payload = {
        "connected": bool(commerce.get("connected")),
        "data_available": commerce_metric("revenue").get("value") is not None,
        "last_success_at": commerce.get("last_success_at"),
        "data_max_available": (
            end_date.isoformat() if commerce_metric("revenue").get("value") is not None else None
        ),
    }
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
        {
            **provider_source("commerce", "E-commerce", commerce_source_payload),
            # Proveniência explícita: quem lê sabe de qual plataforma é o número.
            "provider": commerce.get("provider"),
            "provider_label": commerce.get("provider_label"),
            "kpi_source": commerce.get("kpi_source"),
            "official_kpis": bool(commerce.get("official_kpis")),
        },
        provider_source("meta", "Meta Ads", meta),
        provider_source("google_ads", "Google Ads", google_ads),
        provider_source("ga4", "Google Analytics 4", ga4),
        provider_source("instagram", "Instagram", instagram),
    ]
    prev_shopify = previous.get("shopify") or {}
    prev_meta = previous.get("meta") or {}
    metrics = [
        # Comércio: valores do provider resolvido, com a procedência no source.
        _metric("revenue", "Faturamento", commerce_metric("revenue").get("value"), fmt="currency", status="confirmed" if commerce_metric("revenue").get("value") is not None else "unavailable", source=commerce.get("provider") or "commerce", previous=commerce_metric("revenue").get("previous"), variation=commerce_metric("revenue").get("variation"), extra={"kpi_source": commerce.get("kpi_source")}),
        _metric("orders", "Pedidos", commerce_metric("orders").get("value"), fmt="integer", status="confirmed" if commerce_metric("orders").get("value") is not None else "unavailable", source=commerce.get("provider") or "commerce", previous=commerce_metric("orders").get("previous"), variation=commerce_metric("orders").get("variation"), extra={"kpi_source": commerce.get("kpi_source")}),
        _metric("average_ticket", "Ticket médio", commerce_metric("average_ticket").get("value"), fmt="currency", status="confirmed" if commerce_metric("average_ticket").get("value") is not None else "unavailable", source=commerce.get("provider") or "commerce", previous=commerce_metric("average_ticket").get("previous"), variation=commerce_metric("average_ticket").get("variation"), extra={"kpi_source": commerce.get("kpi_source")}),
        _metric("new_customers", "Novos clientes", commerce_metric("customers").get("value"), fmt="integer", status="confirmed" if commerce_metric("customers").get("value") is not None else "unavailable", source=commerce.get("provider") or "commerce"),
        _metric("repeat_customers", "Clientes recorrentes", shopify.get("returning_customers"), fmt="integer", status="confirmed" if shopify.get("returning_customers") is not None else "unavailable", source=commerce.get("provider") or "commerce"),
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
        "commerce_context": {
            "provider": commerce.get("provider"),
            "provider_label": commerce.get("provider_label"),
            "connected": bool(commerce.get("connected")),
            "status": commerce.get("status"),
            "kpi_source": commerce.get("kpi_source"),
            "official_kpis": bool(commerce.get("official_kpis")),
            "provenance": commerce.get("provenance") or {},
            "ambiguous": bool(commerce.get("ambiguous")),
            "active_providers": commerce.get("active_providers") or [],
            "status_distribution": commerce.get("status_distribution") or [],
        },
        "business_context": business,
        "external_research": external,
        "executive_context": executive_context,
        "historical_context": (executive_context or {}).get("historical_context"),
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


def _parse_timestamp(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _build_analysis_policy(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    metrics = snapshot.get("metrics") or []
    sources = snapshot.get("sources") or []
    period = snapshot.get("period") or {}
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).date().isoformat()
    active_sources = [source for source in sources if source.get("status") in {"available", "partial"}]
    sync_times = [
        parsed.astimezone(timezone.utc)
        for source in active_sources
        if (parsed := _parse_timestamp(source.get("last_sync_at"))) is not None
    ]
    sync_spread_hours = (
        round((max(sync_times) - min(sync_times)).total_seconds() / 3600, 2)
        if len(sync_times) >= 2 else None
    )
    unavailable = [
        metric["id"] for metric in metrics
        if metric.get("value") is None or metric.get("status") in {"unavailable", "disconnected", "error"}
    ]
    comparable = [
        metric["id"] for metric in metrics
        if metric.get("previous_value") is not None and metric.get("variation_percent") is not None
    ]
    metric_changes = []
    for metric in metrics:
        current, previous = metric.get("value"), metric.get("previous_value")
        variation = metric.get("variation_percent")
        absolute = (
            round(_number(current) - _number(previous), 2)
            if current is not None and previous is not None else None
        )
        metric_id = metric["id"]
        percent_material = variation is not None and abs(_number(variation)) >= INTELLIGENCE_NOISE_PERCENT_THRESHOLD
        absolute_material = (
            metric.get("format") == "currency"
            and absolute is not None
            and abs(absolute) >= INTELLIGENCE_MATERIAL_CURRENCY_ABSOLUTE
        )
        metric_changes.append({
            "metric_id": metric_id,
            "absolute_change": absolute,
            "percent_change": variation,
            "business_importance": "primary" if metric_id in PRIMARY_BUSINESS_METRICS else "supporting",
            "percent_material": percent_material,
            "absolute_material": absolute_material,
            "material_candidate": percent_material or absolute_material,
            "primary_candidate": (
                absolute_material
                if metric.get("format") == "currency"
                else percent_material and metric_id in PRIMARY_BUSINESS_METRICS
            ),
        })
    changes_by_id = {item["metric_id"]: item for item in metric_changes}
    supporting = set()
    for group in RELATED_METRIC_GROUPS:
        group_changes = [changes_by_id[item] for item in group if item in changes_by_id and changes_by_id[item]["percent_change"] is not None]
        directions = {1 if _number(item["percent_change"]) > 0 else -1 if _number(item["percent_change"]) < 0 else 0 for item in group_changes}
        if 1 in directions and -1 in directions:
            supporting.update(item["metric_id"] for item in group_changes)
    includes_partial_today = period.get("start", "") <= today <= period.get("end", "")
    coverage_by_source = {
        source["id"]: _text(source.get("data_max_available")) or None for source in active_sources
    }
    coverage_values = [value for value in coverage_by_source.values() if value]
    if len(active_sources) <= 1:
        temporal_mode, sources_temporally_compatible = "single_source", True
    elif len(coverage_values) == len(active_sources):
        temporal_mode = "coverage"
        sources_temporally_compatible = len(set(coverage_values)) == 1
    elif len(sync_times) == len(active_sources) and sync_spread_hours is not None:
        temporal_mode = "freshness_fallback"
        sources_temporally_compatible = sync_spread_hours <= INTELLIGENCE_CROSS_SOURCE_MAX_LAG_HOURS
    else:
        temporal_mode, sources_temporally_compatible = "insufficient_temporal_evidence", False
    complete_sources = all(source.get("status") == "available" for source in sources if source.get("connected"))
    return {
        "includes_partial_today": includes_partial_today,
        "today_date": today if includes_partial_today else None,
        "comparable_metric_ids": comparable,
        "metric_changes": metric_changes,
        "material_metric_ids": [item["metric_id"] for item in metric_changes if item["material_candidate"]],
        "primary_metric_ids": [item["metric_id"] for item in metric_changes if item["primary_candidate"]],
        "supporting_metric_ids": sorted(supporting),
        "unavailable_metric_ids": unavailable,
        "source_sync_spread_hours": sync_spread_hours,
        "source_coverage": coverage_by_source,
        "common_coverage_through": coverage_values[0] if coverage_values and len(set(coverage_values)) == 1 else None,
        "covers_period_end": bool(coverage_values) and all(value >= period.get("end", "") for value in coverage_values),
        "temporal_compatibility_mode": temporal_mode,
        "cross_source_comparison_allowed": sources_temporally_compatible and complete_sources,
        "quality_label": "Qualidade dos dados",
        "causal_evidence_available": False,
        "noise_percent_threshold": INTELLIGENCE_NOISE_PERCENT_THRESHOLD,
        "material_currency_absolute_threshold": INTELLIGENCE_MATERIAL_CURRENCY_ABSOLUTE,
        "cross_source_max_lag_hours_fallback": INTELLIGENCE_CROSS_SOURCE_MAX_LAG_HOURS,
    }


def _validate_analysis_grounding(analysis: Dict[str, Any], snapshot: Dict[str, Any]) -> None:
    allowed_metrics = {metric["id"] for metric in snapshot.get("metrics") or []}
    allowed_sources = {source["id"] for source in snapshot.get("sources") or []}
    forbidden_causal = re.compile(r"\b(causou|provou|certamente|sem dúvida|aconteceu porque)\b", re.IGNORECASE)
    all_text = json.dumps(analysis, ensure_ascii=False)
    if forbidden_causal.search(all_text):
        raise RuntimeError("AI_UNSUPPORTED_CAUSALITY")
    policy = _build_analysis_policy(snapshot)
    if policy["includes_partial_today"] and not re.search(r"hoje.{0,60}(formação|parcial)", all_text, re.IGNORECASE):
        raise RuntimeError("AI_MISSING_PARTIAL_TODAY_LIMITATION")
    for insight in analysis.get("insights") or []:
        metric_ids = [item for item in insight.get("metric_ids") or [] if item in allowed_metrics]
        sources = [item for item in insight.get("sources") or [] if item in allowed_sources]
        if not metric_ids or not sources:
            raise RuntimeError("AI_UNGROUNDED_INSIGHT")
        if not policy["cross_source_comparison_allowed"] and len(set(sources)) > 1:
            raise RuntimeError("AI_TEMPORALLY_INCOMPATIBLE_SOURCES")
    for action in analysis.get("actions") or []:
        sources = [item for item in action.get("sources") or [] if item in allowed_sources]
        if action.get("metric_id") not in allowed_metrics or not sources:
            raise RuntimeError("AI_UNGROUNDED_ACTION")


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


ANALYSIS_VERSION = "v2-commerce-provider"


def context_fingerprint(snapshot: Dict[str, Any]) -> str:
    """Identidade do contexto que alimenta a análise.

    Entram período, valores e status das métricas, frescor das fontes, o
    provider de e-commerce com a procedência dos KPIs e o contexto de negócio.
    Mudança relevante nos dados muda a impressão digital e invalida o reuso;
    uma nova visita com os mesmos dados reaproveita a análise e não gasta
    token. A versão entra na conta: ao mudar schema ou instruções, o reuso
    expira sozinho.
    """
    period = snapshot.get("period") or {}
    commerce = snapshot.get("commerce_context") or {}
    business = (snapshot.get("business_context") or {}).get("context") or {}
    external = snapshot.get("external_research") or {}
    material = [
        {
            "id": metric.get("id"), "value": metric.get("value"),
            "status": metric.get("status"), "previous": metric.get("previous"),
        }
        for metric in snapshot.get("metrics") or []
    ]
    sources = [
        {
            "id": source.get("id"), "status": source.get("status"),
            # Só sucesso: uma tentativa sem dado novo não invalida a análise.
            "last_sync_at": source.get("last_sync_at"),
            "data_max_available": source.get("data_max_available"),
        }
        for source in snapshot.get("sources") or []
    ]
    fingerprint_payload = {
        "version": ANALYSIS_VERSION,
        "period": {"start": period.get("start"), "end": period.get("end")},
        "metrics": material,
        "sources": sources,
        "commerce": {
            "provider": commerce.get("provider"), "kpi_source": commerce.get("kpi_source"),
        },
        "business_context": business,
        "external_research": {"status": external.get("status"), "provider": external.get("provider")},
    }
    serialized = json.dumps(fingerprint_payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


async def _reusable_analysis(
    *, client_id: str, period: Dict[str, Any], fingerprint: str,
) -> Dict[str, Any] | None:
    """Análise concluída do mesmo tenant, período e contexto."""
    try:
        rows = await sb_select(
            "ai_analyses",
            filters={
                "client_id": f"eq.{client_id}",
                "period_start": f"eq.{period['start']}",
                "period_end": f"eq.{period['end']}",
                "status": "eq.completed",
                "context_fingerprint": f"eq.{fingerprint}",
            },
            order="created_at.desc", limit=1,
        )
    except Exception as exc:
        # Coluna ainda não aplicada no remoto: segue gerando normalmente.
        print(f"[intelligence][cache] client_id={client_id} status=lookup_unavailable error_type={exc.__class__.__name__}")
        return None
    row = rows[0] if rows else None
    if not row or _text(row.get("client_id")) != client_id:
        return None
    return row


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
    fingerprint = context_fingerprint(snapshot)
    base_row = {
        "client_id": client_id,
        "requested_by": user_id,
        "period_start": period["start"],
        "period_end": period["end"],
        "context_fingerprint": fingerprint,
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
    reusable = await _reusable_analysis(client_id=client_id, period=period, fingerprint=fingerprint)
    if reusable:
        print(f"[intelligence][cache] client_id={client_id} status=reused period={period['start']}..{period['end']}")
        return {
            "ok": True,
            "provider_configured": True,
            "status": "completed",
            "reused": True,
            "snapshot": snapshot,
            "analysis": reusable,
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
                "analysis_policy": _build_analysis_policy(snapshot),
                # Números já calculados (Shopify líquido, ROAS combinado com
                # fontes incluídas explícitas, GA4 separado) — a IA só
                # interpreta, nunca soma/divide nada daqui.
                "real_operation": snapshot.get("executive_context"),
                # Provider de e-commerce com procedência dos KPIs: impede
                # atribuir a uma loja FBITS semântica de Shopify.
                "commerce_context": snapshot.get("commerce_context"),
                # Texto editorial da empresa: segmento, público, objetivos.
                "business_context": (snapshot.get("business_context") or {}).get("context"),
                # Sem provider externo, chega not_configured e nada é inventado.
                "external_research": snapshot.get("external_research"),
                # Monthly aggregates only: no order, customer, email or other PII.
                "historical_context": snapshot.get("historical_context"),
            },
            schema=ANALYSIS_SCHEMA,
            instructions=ANALYSIS_INSTRUCTIONS,
        )
        _validate_analysis_grounding(analysis, snapshot)
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
            "analysis_policy": _build_analysis_policy(snapshot),
        },
        schema=ANSWER_SCHEMA,
        instructions=ANSWER_INSTRUCTIONS,
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
