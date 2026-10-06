from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List
from zoneinfo import ZoneInfo

import httpx

from .periods import resolve_period
from .generic_connections import list_generic_connections
from .business_context import load_business_context
from .commerce_context import resolve_commerce_context
from .external_research import external_research_context
from .customers import recurring_customers_in_period
from .ig_supabase import _is_column_compat_error, sb_insert, sb_select, sb_update
from .instagram_organic_history import aggregate_instagram_months


# ---------------------------------------------------------------------------
# Observabilidade da análise (POST /api/intelligence/analyses)
#
# Mesmo mecanismo que já aparece no Render: print() em stdout, que o app.py
# deixa com line buffering. flush=True aqui é cinto e suspensório: se o
# processo for iniciado por outro comando que não passe pelo app.py, a linha
# ainda sai antes de um eventual kill/timeout.
# ---------------------------------------------------------------------------

LOG_PREFIX = "[intelligence]"

LOG_STAGE_AUTHORIZATION = "authorization"
LOG_STAGE_SNAPSHOT = "snapshot"
LOG_STAGE_COMMERCE_CONTEXT = "commerce_context"
LOG_STAGE_BUSINESS_CONTEXT = "business_context"
LOG_STAGE_EXTERNAL_RESEARCH = "external_research"
LOG_STAGE_MODEL_REQUEST = "model_request"
LOG_STAGE_MODEL_RESPONSE = "model_response"
LOG_STAGE_VALIDATION = "validation"
LOG_STAGE_PERSISTENCE = "persistence"

# Qualquer coisa com cara de credencial sai da linha antes de ser impressa.
# A ordem importa: os padrões específicos limpam primeiro, o genérico de
# cadeia longa fecha o que sobrou.
_LOG_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:bearer|basic)\s+\S+"),
    re.compile(
        r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|token|"
        r"secret|service[_-]?role|password|senha|credential)s?\s*[:=]\s*\S+"
    ),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{6,}(?:\.[A-Za-z0-9_\-]*){0,2}"),
    re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"),
)


# Campos estruturais: identificadores e enums gerados pelo próprio backend,
# nunca texto de fora. Ficam fora da redação porque o padrão de cadeia longa
# apagaria justamente o request_id (32 hex) e o client_id (UUID) — que são o
# motivo de existir deste log.
_LOG_STRUCTURAL_FIELDS = frozenset(
    {
        "request_id", "client_id", "stage", "elapsed_ms", "period_start", "period_end",
        "upstream_status", "error_code", "error_type", "provider",
        "model", "success", "status", "commerce_provider", "commerce_status",
        "business_context", "external_research", "reused", "fingerprint",
        "insights", "actions", "metrics", "sources",
    }
)


def _log_safe(value: Any, *, key: str = "") -> str:
    """Valor pronto para log: uma linha, sem credencial, com tamanho limitado."""
    text = re.sub(r"\s+", " ", str(value if value is not None else "")).strip()
    if key not in _LOG_STRUCTURAL_FIELDS:
        for pattern in _LOG_SECRET_PATTERNS:
            text = pattern.sub("[redacted]", text)
    if len(text) > 160:
        text = f"{text[:160]}..."
    return text or "-"


def _log_line(event: str, **fields: Any) -> None:
    parts = [f"event={event}"]
    for key, value in fields.items():
        if value is None or value == "":
            continue
        parts.append(f"{key}={_log_safe(value, key=key)}")
    print(f"{LOG_PREFIX} " + " ".join(parts), flush=True)


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _upstream_status(exc: BaseException | None) -> int | None:
    """Status HTTP do serviço de fora, quando a exceção carrega resposta."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status
    match = re.search(r"AI_PROVIDER_ERROR_(\d{3})", str(exc or ""))
    return int(match.group(1)) if match else None


def _postgrest_code(exc: BaseException | None) -> str:
    """Código do PostgREST (ex.: PGRST204). Só o código, nunca o body."""
    response = getattr(exc, "response", None)
    if response is None:
        return ""
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - body ilegível não pode derrubar o log
        return ""
    code = body.get("code") if isinstance(body, dict) else None
    return _log_safe(code) if code else ""


def _error_code_of(exc: BaseException | None) -> str:
    """Código curto do erro: a mensagem já é um código nos RuntimeError daqui."""
    text = re.sub(r"\s+", " ", str(exc or "")).strip()
    if text and re.fullmatch(r"[A-Za-z0-9_:.\-]{1,80}", text):
        return text
    return exc.__class__.__name__ if exc is not None else "UNKNOWN_ERROR"


def log_request_started(
    *, request_id: str | None, client_id: str, period_start: Any, period_end: Any,
) -> None:
    _log_line(
        "request_started",
        request_id=request_id or "-",
        client_id=client_id,
        period_start=period_start or "-",
        period_end=period_end or "-",
    )


def log_stage_completed(
    *, stage: str, request_id: str | None, elapsed_ms: int, **extra: Any,
) -> None:
    _log_line(
        "stage_completed",
        stage=stage,
        request_id=request_id or "-",
        elapsed_ms=elapsed_ms,
        **extra,
    )


def log_stage_failed(
    *,
    stage: str,
    request_id: str | None,
    elapsed_ms: int,
    exc: BaseException | None = None,
    error_code: str | None = None,
    **extra: Any,
) -> None:
    fields: Dict[str, Any] = {
        "stage": stage,
        "request_id": request_id or "-",
        "error_code": error_code or _error_code_of(exc),
        "error_type": exc.__class__.__name__ if exc is not None else "ConfigurationError",
        "elapsed_ms": elapsed_ms,
    }
    upstream = extra.pop("upstream_status", None) or _upstream_status(exc)
    if upstream is not None:
        fields["upstream_status"] = upstream
    postgrest = extra.pop("postgrest_code", None) or _postgrest_code(exc)
    if postgrest:
        fields["postgrest_code"] = postgrest
    fields.update(extra)
    _log_line("stage_failed", **fields)
    if exc is not None:
        try:
            exc._intelligence_stage_logged = True  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - exceção imutável não pode quebrar o log
            pass


def _already_logged(exc: BaseException) -> bool:
    return bool(getattr(exc, "_intelligence_stage_logged", False))


async def _timed_stage(stage: str, request_id: str | None, awaitable: Any) -> Any:
    """Executa uma etapa medindo o tempo e registrando sucesso ou falha."""
    started = time.monotonic()
    try:
        result = await awaitable
    except BaseException as exc:
        log_stage_failed(
            stage=stage, request_id=request_id, elapsed_ms=_elapsed_ms(started), exc=exc,
        )
        raise
    log_stage_completed(stage=stage, request_id=request_id, elapsed_ms=_elapsed_ms(started))
    return result


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
job terminou. Não confunda esses conceitos. Só compare fontes que estejam juntas em um mesmo grupo
de comparable_source_groups: fontes de grupos diferentes têm cobertura diferente e não são
comparáveis entre si, ainda que cada uma sustente conclusões isoladas. cross_source_comparison_allowed
resume se todas as fontes ativas estão em um único grupo. Citar um indicador que o backend já
calculou a partir de várias fontes, como investment ou roas, não é cruzar fontes. Explique
limitações quando covers_period_end for falso.
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
    since, until = resolve_period(start=start.isoformat(), end=end.isoformat()).utc_bounds()
    return await sb_select(
        table,
        select=select,
        filters={
            "client_id": f"eq.{client_id}",
            "and": f"(timestamp.gte.{since.isoformat()},timestamp.lte.{until.isoformat()})",
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
        if metric_date:
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
    client_id: str, start_date: date, end_date: date, previous_start: date, previous_end: date, *, include_media: bool = True
) -> Dict[str, Any]:
    rows, snapshots, instagram_media = await asyncio.gather(
        _query_period(
            "dashboard_daily_metrics", client_id=client_id, select="*", date_column="metric_date",
            start=previous_start, end=end_date, limit=800,
        ),
        sb_select("dashboard_source_snapshots", filters={"client_id": f"eq.{client_id}"}, limit=20),
        _query_timestamp_period(
            "ig_media", client_id=client_id,
            select="timestamp,media_type,media_product_type,insights_json",
            start=start_date, end=end_date, limit=1000,
        ) if include_media else asyncio.sleep(0, result=[]),
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
            "ga4": {"connected": True, "data_available": any(row.get("ga4_sessions") is not None for row in selected), "sessions": _sum(selected, "ga4_sessions"), "users": None, "users_status": "unavailable", "daily_user_sum": _sum(selected, "ga4_users"), "user_count_semantics": "sum_of_daily_users", "last_success_at": source("ga4").get("last_success_at"), "data_max_available": source("ga4").get("data_max_available")},
            "instagram": {"connected": True, "data_available": any(row.get("instagram_reach") is not None for row in selected), "last_success_at": source("instagram").get("last_success_at"), "data_max_available": source("instagram").get("data_max_available")},
            "total_paid_media": {"paid_media_spend": paid, "included_paid_sources": [provider for provider, value in (("meta", meta_spend), ("google_ads", google_spend)) if value], "blended_roas": net / paid if paid else None},
        }

    def add_coverage(payload: Dict[str, Any], since: date, until: date) -> None:
        for provider, field in (("shopify", "shopify_net_revenue"), ("meta", "meta_spend"),
                                ("google_ads", "google_ads_spend"), ("ga4", "ga4_sessions"),
                                ("instagram", "instagram_reach")):
            dates = sorted({str(row["metric_date"]) for row in rows
                            if since.isoformat() <= str(row.get("metric_date") or "") <= until.isoformat()
                            and row.get(field) is not None})
            if not dates:
                fields = {"shopify": ("net_revenue", "orders", "new_customers"),
                          "meta": ("spend", "attributed_revenue"), "google_ads": ("spend", "attributed_revenue"),
                          "ga4": ("sessions", "daily_user_sum"), "instagram": ()}
                for metric in fields[provider]:
                    payload[provider][metric] = None
            payload[provider]["coverage"] = {
                "coverage_start": dates[0] if dates else None, "coverage_end": dates[-1] if dates else None,
                "distinct_dates": len(dates), "covered_days": len(dates),
                "expected_days": (until - since).days + 1,
                "is_partial": bool(dates) and len(dates) < (until - since).days + 1,
                "completeness": "unknown", "last_sync_at": None,
                "projection_success_at": by_provider.get(provider, {}).get("last_success_at"),
            }

        shop = payload["shopify"]
        covered = shop["coverage"]["covered_days"] == shop["coverage"]["expected_days"]
        if not covered:
            for metric in ("net_revenue", "orders", "new_customers"):
                if shop.get(metric) == 0:
                    shop[metric] = None
        if not shop.get("orders"):
            shop["average_order_value"] = None
        if not payload["shopify"]["data_available"]:
            payload["meta"]["roas_real"] = None
            payload["google_ads"]["roas_real"] = None
            payload["total_paid_media"]["blended_roas"] = None
        paid_sources = [provider for provider in ("meta", "google_ads") if payload[provider]["data_available"]]
        payload["total_paid_media"]["included_paid_sources"] = paid_sources
        if not paid_sources:
            payload["total_paid_media"]["paid_media_spend"] = None

    current = section(start_date, end_date)
    previous = section(previous_start, previous_end)
    add_coverage(current, start_date, end_date)
    add_coverage(previous, previous_start, previous_end)
    def delta(current_value: Any, previous_value: Any) -> Dict[str, float | None]:
        if current_value is None or previous_value is None:
            return {"absolute": None, "percent": None}
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
        [row for row in rows if start_date.isoformat() <= _text(row.get("metric_date")) <= end_date.isoformat()],
        snapshots, end_date.year, start_date, end_date, instagram_media
    )
    return current


async def calculate_intelligence_snapshot(
    *,
    client_id: str,
    start: str | None,
    end: str | None,
    days: int = 30,
    request_id: str | None = None,
    include_commerce_details: bool = True,
    include_external_research: bool = True,
) -> Dict[str, Any]:
    start_date, end_date = _parse_period(start, end, days)
    period_days = (end_date - start_date).days + 1
    previous_end = start_date - timedelta(days=1)
    previous_start = previous_end - timedelta(days=period_days - 1)

    executive_context = await _read_model_executive_context(
        client_id, start_date, end_date, previous_start, previous_end,
        **({"include_media": False} if not include_commerce_details else {}),
    )
    current = executive_context or {}
    previous = current.get("previous_period") or {}
    deltas = current.get("deltas") or {}
    shopify = current.get("shopify") or {}
    # Provider de e-commerce resolvido pela conexão do tenant, nunca pelo nome
    # da empresa. FBITS entrega os KPIs oficiais da própria loja; Shopify, os
    # agregados já lidos do read model.
    # As três leituras são independentes: em paralelo, o tempo total é o da
    # mais lenta (a consulta oficial da FBITS), não a soma.
    started_at = time.monotonic()
    # Cada leitura é cronometrada e registrada separadamente: num 502 sem
    # resposta dá para ver qual das três não voltou.
    commerce, business, external = await asyncio.gather(
        _timed_stage(
            LOG_STAGE_COMMERCE_CONTEXT, request_id,
            resolve_commerce_context(
                client_id=client_id, start=start_date.isoformat(), end=end_date.isoformat(),
                **({"include_details": False} if not include_commerce_details else {}),
                shopify_section={
                    **shopify,
                    "previous": previous.get("shopify") or {},
                    "deltas": deltas,
                },
            ),
        ),
        _timed_stage(LOG_STAGE_BUSINESS_CONTEXT, request_id, load_business_context(client_id)),
        _timed_stage(
            LOG_STAGE_EXTERNAL_RESEARCH, request_id,
            external_research_context(client_id=client_id) if include_external_research else asyncio.sleep(0, result={"status": "unavailable", "provider": None, "market_signals": [], "content_references": [], "ugc_creators": []}),
        ),
    )
    print(
        f"[intelligence][snapshot] client_id={client_id} stage=context status=ok "
        f"commerce_provider={commerce.get('provider') or '-'} "
        f"commerce_status={commerce.get('status') or '-'} "
        f"business_context={'yes' if business.get('available') else 'no'} "
        f"external_research={external.get('status')} "
        f"elapsed_ms={int((time.monotonic() - started_at) * 1000)}"
    )
    commerce_metrics = commerce.get("metrics") or {}

    def commerce_metric(name: str) -> Dict[str, Any]:
        return commerce_metrics.get(name) if isinstance(commerce_metrics.get(name), dict) else {}

    # Priorizar o valor já fornecido pelo provider correto; FBITS nunca usa
    # a seção Shopify. Fallback: mesma identidade/pedidos do Customer 360.
    repeat_customers = 0 if (commerce.get("provider") == "shopify" and shopify.get("orders") == 0 and (shopify.get("coverage") or {}).get("covered_days") == period_days) else None
    repeat_kpi_source = None
    official_repeat = commerce_metric("repeat_customers")
    if (commerce.get("official_kpis") and commerce.get("status") == "ok"
            and official_repeat.get("value") is not None
            and official_repeat.get("status", "confirmed") == "confirmed"):
        repeat_customers = official_repeat["value"]
        repeat_kpi_source = commerce.get("kpi_source")
    elif (commerce.get("provider") == "shopify" and shopify.get("connected")
            and shopify.get("data_available") and shopify.get("returning_customers") is not None):
        repeat_customers = shopify["returning_customers"]
        repeat_kpi_source = "shopify_read_model"
    elif repeat_customers is None and include_commerce_details and commerce.get("provider") in {"fbits", "shopify"} and (commerce.get("provider") != "shopify" or ((shopify.get("coverage") or {}).get("covered_days") == period_days and shopify.get("data_available"))):
        try:
            repeat_customers = await recurring_customers_in_period(
                client_id=client_id, start=start_date.isoformat(), end=end_date.isoformat(),
                provider=commerce["provider"],
            )
            if repeat_customers is not None:
                repeat_kpi_source = "customer_360_persisted_orders"
        except Exception:
            # Falha de leitura mantém desconhecido; não vira zero nem derruba
            # as demais métricas já obtidas para o snapshot.
            repeat_customers = None

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
        _metric("repeat_customers", "Clientes recorrentes", repeat_customers, fmt="integer", status="confirmed" if repeat_customers is not None else "unavailable", source=commerce.get("provider") or "commerce", extra={"kpi_source": repeat_kpi_source}),
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
        # Combinações válidas, explícitas: o modelo sabe antes de responder.
        "comparable_source_groups": _comparable_source_groups(snapshot),
        "quality_label": "Qualidade dos dados",
        "causal_evidence_available": False,
        "noise_percent_threshold": INTELLIGENCE_NOISE_PERCENT_THRESHOLD,
        "material_currency_absolute_threshold": INTELLIGENCE_MATERIAL_CURRENCY_ABSOLUTE,
        "cross_source_max_lag_hours_fallback": INTELLIGENCE_CROSS_SOURCE_MAX_LAG_HOURS,
    }


# `metrics[].source` é rótulo de procedência exibido ao usuário (o painel
# mostra "fbits", "paid media"), não identificador de fonte. Os IDs reais
# vivem em `sources[].id`. O modelo recebe os dois vocabulários e o schema não
# restringe `sources` por enum, então ele pode citar o rótulo que vê ao lado da
# métrica. Estes nomes são compostos pelo próprio snapshot e não são IDs.
_COMPOSITE_SOURCE_LABELS = {
    "paid_media": ("meta", "google_ads"),
    # A perna de comércio do ROAS vem rotulada "shopify" mesmo em tenant FBITS.
    "shopify": ("commerce",),
}


def _source_alias_index(snapshot: Dict[str, Any]) -> Dict[str, tuple[str, ...]]:
    """Apelidos legítimos de fonte → IDs reais, derivados do snapshot.

    Nada é fixado no código: o provider ("fbits", "shopify") e o rótulo
    ("FBITS/Wake") de cada fonte saem do próprio snapshot. Um ID inventado
    continua sem resolver.
    """
    source_ids = {_text(source.get("id")) for source in snapshot.get("sources") or []}
    index: Dict[str, tuple[str, ...]] = {}
    for source in snapshot.get("sources") or []:
        source_id = _text(source.get("id"))
        if not source_id:
            continue
        for alias in (source_id, source.get("provider"), source.get("provider_label")):
            key = _text(alias).lower()
            if key:
                index.setdefault(key, (source_id,))
    for label, targets in _COMPOSITE_SOURCE_LABELS.items():
        present = tuple(target for target in targets if target in source_ids)
        if present:
            index.setdefault(label, present)
    return index


def _metric_source_ids(metric: Dict[str, Any], index: Dict[str, tuple[str, ...]]) -> List[str]:
    """IDs de fonte reais por trás do rótulo de procedência de uma métrica."""
    resolved: List[str] = []
    for part in _text(metric.get("source")).split("+"):
        resolved.extend(index.get(part.strip().lower(), ()))
    return sorted(set(resolved))


def _metrics_with_source_ids(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Cópia das métricas para o payload, com os IDs de fonte explícitos.

    Elimina a ambiguidade na origem: o modelo deixa de ter que inferir o
    identificador a partir de um rótulo de exibição. O snapshot persistido e o
    que o frontend recebe não mudam — a anotação existe só no payload.
    """
    index = _source_alias_index(snapshot)
    return [
        {**metric, "source_ids": _metric_source_ids(metric, index)}
        for metric in snapshot.get("metrics") or []
    ]


def _normalize_grounding_ids(
    analysis: Dict[str, Any], snapshot: Dict[str, Any], *, request_id: str | None = None,
) -> Dict[str, Any]:
    """Traduz apelidos de fonte citados pelo modelo para os IDs reais.

    Resolve só o que o snapshot prova ser a mesma fonte — "fbits" é a fonte
    `commerce` daquele tenant. ID inexistente não é inventado nem descartado
    aqui: segue adiante e a validação o acusa (fail-closed).
    """
    index = _source_alias_index(snapshot)
    allowed_sources = {_text(source.get("id")) for source in snapshot.get("sources") or []}
    rewritten = 0

    def normalize(values: Any) -> List[str]:
        nonlocal rewritten
        out: List[str] = []
        for value in values or []:
            name = _text(value)
            if name in allowed_sources:
                out.append(name)
                continue
            resolved = index.get(name.lower(), ())
            if resolved:
                rewritten += 1
                out.extend(resolved)
            else:
                out.append(name)  # desconhecido: a validação decide
        return list(dict.fromkeys(out))

    normalized = {
        **analysis,
        "insights": [
            {**insight, "sources": normalize(insight.get("sources"))}
            for insight in analysis.get("insights") or []
        ],
        "actions": [
            {**action, "sources": normalize(action.get("sources"))}
            for action in analysis.get("actions") or []
        ],
    }
    if rewritten:
        _log_line(
            "source_alias_normalized",
            request_id=request_id or "-",
            rewritten=rewritten,
        )
    return normalized


# Ressalva do dia parcial. Fonte única: a garantia determinística e a
# validação usam exatamente o mesmo critério, então não há como a análise
# entregue satisfazer uma e não a outra.
_PARTIAL_TODAY_CAVEAT = re.compile(r"hoje.{0,60}(formação|parcial)", re.IGNORECASE)

PARTIAL_TODAY_INSIGHT_TITLE = "Dados de hoje ainda em formação"

# Limitação canônica do backend: texto fixo, sem algarismo, sem causalidade e
# sem métrica inventada. Entra na estrutura que o schema e o frontend já têm
# (`insights` com categoria `data_quality`), não numa arquitetura paralela.
_PARTIAL_TODAY_INSIGHT = {
    "category": "data_quality",
    "title": PARTIAL_TODAY_INSIGHT_TITLE,
    "interpretation": (
        "O período analisado inclui o dia de hoje, cujos dados ainda estão parciais "
        "e em formação. Um dia incompleto não é comparável a um dia completo."
    ),
    "impact": "medium",
    "confidence": "high",
    "action": "Reavaliar os números do período após o fechamento do dia de hoje.",
    "reason": "A leitura do dia corrente ainda pode mudar até o fim do dia.",
}


def _partial_today_anchor(snapshot: Dict[str, Any]) -> tuple[str, str] | None:
    """Métrica e fonte reais em que a ressalva se apoia.

    A limitação é sobre o período, não sobre um cruzamento: basta uma métrica
    confirmada e uma fonte do snapshot. A fonte preferida é a que o próprio
    snapshot marca como cobertura parcial. Uma única fonte, para a ressalva
    nunca disparar AI_TEMPORALLY_INCOMPATIBLE_SOURCES.
    """
    metrics = [metric for metric in snapshot.get("metrics") or [] if _text(metric.get("id"))]
    sources = [source for source in snapshot.get("sources") or [] if _text(source.get("id"))]
    if not metrics or not sources:
        return None

    def source_rank(source: Dict[str, Any]) -> tuple[int, int]:
        coverage = source.get("coverage") if isinstance(source.get("coverage"), dict) else {}
        return (
            0 if coverage.get("is_partial") else 1,
            0 if source.get("status") in {"available", "partial"} else 1,
        )

    metric = next(
        (item for item in metrics if item.get("status") == "confirmed"), metrics[0],
    )
    source = sorted(sources, key=source_rank)[0]
    return _text(metric.get("id")), _text(source.get("id"))


def _ensure_partial_today_limitation(
    analysis: Dict[str, Any], snapshot: Dict[str, Any], *, policy: Dict[str, Any] | None = None,
) -> tuple[Dict[str, Any], bool]:
    """Garante a ressalva do dia parcial na análise entregue.

    Quando o período inclui hoje e o modelo não registrou a limitação, o
    backend acrescenta a versão canônica. Nada do que o modelo escreveu é
    alterado e a análise original não é mutada. Devolve a análise entregue e
    se a injeção foi necessária.
    """
    resolved = policy if policy is not None else _build_analysis_policy(snapshot)
    if not resolved.get("includes_partial_today"):
        return analysis, False
    if _PARTIAL_TODAY_CAVEAT.search(json.dumps(analysis, ensure_ascii=False)):
        return analysis, False
    anchor = _partial_today_anchor(snapshot)
    if anchor is None:
        # Sem métrica ou fonte não há ressalva aterrada possível. Devolvemos
        # sem injetar para a validação acusar, em vez de omitir em silêncio.
        return analysis, False
    metric_id, source_id = anchor
    limitation = {**_PARTIAL_TODAY_INSIGHT, "metric_ids": [metric_id], "sources": [source_id]}
    return {**analysis, "insights": [*(analysis.get("insights") or []), limitation]}, True


def _comparable_source_groups(snapshot: Dict[str, Any]) -> List[List[str]]:
    """Fontes agrupadas por cobertura idêntica: dentro de um grupo, comparar é
    temporalmente sólido; entre grupos, não.

    É o que o modelo precisa saber ANTES de responder. Um booleano global só
    diz "nada pode ser cruzado" e não informa quais combinações servem.
    """
    groups: Dict[str, List[str]] = {}
    for source in snapshot.get("sources") or []:
        if source.get("status") != "available":
            continue
        coverage = _text(source.get("data_max_available"))
        source_id = _text(source.get("id"))
        if coverage and source_id:
            groups.setdefault(coverage, []).append(source_id)
    return [sorted(ids) for _, ids in sorted(groups.items())]


def _cited_sources_comparable(
    snapshot: Dict[str, Any], source_ids: Iterable[str],
) -> tuple[bool, str]:
    """Compatibilidade temporal entre as fontes que o insight realmente cita.

    Mesmo critério da política global, mas escopado ao par citado. A precedência
    é preservada: havendo cobertura para todas as fontes citadas, ela decide
    sozinha — freshness é quando o job terminou, não até quando existe dado, e
    não pode substituir a cobertura.
    """
    by_id = {_text(source.get("id")): source for source in snapshot.get("sources") or []}
    cited = [by_id[source_id] for source_id in dict.fromkeys(source_ids) if source_id in by_id]
    if len(cited) <= 1:
        return True, "single_source"
    if any(source.get("status") != "available" for source in cited):
        return False, "source_not_available"
    coverage = [_text(source.get("data_max_available")) for source in cited]
    if all(coverage):
        aligned = len(set(coverage)) == 1
        return aligned, "coverage" if aligned else "coverage_mismatch"
    sync_times = [
        parsed.astimezone(timezone.utc)
        for source in cited
        if (parsed := _parse_timestamp(source.get("last_sync_at"))) is not None
    ]
    if len(sync_times) == len(cited):
        spread = (max(sync_times) - min(sync_times)).total_seconds() / 3600
        if spread <= INTELLIGENCE_CROSS_SOURCE_MAX_LAG_HOURS:
            return True, "freshness_fallback"
        return False, "freshness_spread_exceeded"
    return False, "insufficient_temporal_evidence"


def _aggregate_only_sources(
    snapshot: Dict[str, Any], metric_ids: List[str], source_ids: List[str],
) -> bool:
    """As fontes citadas vêm todas de um único indicador já calculado?

    `investment` (Meta + Google) e `roas` (comércio + mídia paga) são números
    que o backend compôs. Citar um deles não é o modelo cruzar fontes: o
    cruzamento aconteceu em código confiável. Dois indicadores lado a lado,
    sim, são comparação e seguem para a verificação temporal.
    """
    if len(metric_ids) != 1:
        return False
    metric = next(
        (item for item in snapshot.get("metrics") or [] if _text(item.get("id")) == metric_ids[0]),
        None,
    )
    if metric is None:
        return False
    aggregate = set(_metric_source_ids(metric, _source_alias_index(snapshot)))
    return bool(aggregate) and set(source_ids) <= aggregate


def _log_grounding_failure(
    *,
    kind: str,
    index: int,
    category: str,
    reason: str,
    request_id: str | None,
    metric_ids_count: int,
    sources_count: int,
    unknown: Iterable[str] = (),
    metric_ids: Iterable[str] = (),
    source_ids: Iterable[str] = (),
    detail: str = "",
    coverage: Dict[str, Any] | None = None,
) -> None:
    """Razão estrutural da recusa. Nada de prosa do modelo.

    `unknown` traz só os identificadores que não existem no catálogo — sem
    eles não há como distinguir um apelido legítimo ("fbits") de um ID
    inventado em produção. Passam pela sanitização do log como qualquer campo.
    """
    _log_line(
        "grounding_validation_failed",
        request_id=request_id or "-",
        kind=kind,
        index=index,
        category=category or "-",
        reason=reason,
        metric_ids_count=metric_ids_count,
        sources_count=sources_count,
        unknown_ids=",".join(sorted({_text(item) for item in unknown if _text(item)})) or "-",
        metric_ids=",".join(_text(item) for item in metric_ids) or "-",
        source_ids=",".join(_text(item) for item in source_ids) or "-",
        detail=detail or "-",
        # Datas de cobertura são cálculo do backend, não texto do modelo.
        coverage=",".join(
            f"{key}:{_text(value) or 'none'}" for key, value in sorted((coverage or {}).items())
        ) or "-",
    )


def _grounding_reason(raw: List[str], valid: List[str], *, subject: str) -> str:
    if not raw:
        return f"no_{subject}"
    if not valid:
        return f"unknown_{subject}"
    return ""


def _validate_analysis_grounding(
    analysis: Dict[str, Any],
    snapshot: Dict[str, Any],
    *,
    policy: Dict[str, Any] | None = None,
    request_id: str | None = None,
) -> None:
    allowed_metrics = {metric["id"] for metric in snapshot.get("metrics") or []}
    allowed_sources = {source["id"] for source in snapshot.get("sources") or []}
    forbidden_causal = re.compile(r"\b(causou|provou|certamente|sem dúvida|aconteceu porque)\b", re.IGNORECASE)
    all_text = json.dumps(analysis, ensure_ascii=False)
    if forbidden_causal.search(all_text):
        raise RuntimeError("AI_UNSUPPORTED_CAUSALITY")
    # A política pode vir de fora para que uma geração que atravesse a
    # meia-noite valide contra o mesmo "hoje" que o modelo recebeu.
    policy = policy if policy is not None else _build_analysis_policy(snapshot)
    if policy["includes_partial_today"] and not _PARTIAL_TODAY_CAVEAT.search(all_text):
        raise RuntimeError("AI_MISSING_PARTIAL_TODAY_LIMITATION")
    for index, insight in enumerate(analysis.get("insights") or []):
        category = _text(insight.get("category"))
        raw_metrics = [_text(item) for item in insight.get("metric_ids") or [] if _text(item)]
        raw_sources = [_text(item) for item in insight.get("sources") or [] if _text(item)]
        metric_ids = [item for item in raw_metrics if item in allowed_metrics]
        sources = [item for item in raw_sources if item in allowed_sources]
        reason = _grounding_reason(raw_metrics, metric_ids, subject="metric_id") or _grounding_reason(
            raw_sources, sources, subject="source",
        )
        if reason:
            _log_grounding_failure(
                kind="insight", index=index, category=category, reason=reason,
                request_id=request_id, metric_ids_count=len(raw_metrics),
                sources_count=len(raw_sources),
                unknown=[
                    *(item for item in raw_metrics if item not in allowed_metrics),
                    *(item for item in raw_sources if item not in allowed_sources),
                ],
            )
            raise RuntimeError("AI_UNGROUNDED_INSIGHT")
        cited_sources = list(dict.fromkeys(sources))
        if len(cited_sources) > 1 and not _aggregate_only_sources(
            snapshot, metric_ids, cited_sources,
        ):
            # A compatibilidade é avaliada entre as fontes CITADAS. O veredito
            # global reprovava um par alinhado por causa de uma fonte
            # desalinhada que o insight nem menciona.
            compatible, mode = _cited_sources_comparable(snapshot, cited_sources)
            if not compatible:
                _log_grounding_failure(
                    kind="insight", index=index, category=category,
                    reason="cross_source_not_allowed", request_id=request_id,
                    metric_ids_count=len(raw_metrics), sources_count=len(cited_sources),
                    metric_ids=metric_ids, source_ids=cited_sources, detail=mode,
                    coverage={
                        source_id: (policy.get("source_coverage") or {}).get(source_id)
                        for source_id in cited_sources
                    },
                )
                raise RuntimeError("AI_TEMPORALLY_INCOMPATIBLE_SOURCES")
    for index, action in enumerate(analysis.get("actions") or []):
        metric_id = _text(action.get("metric_id"))
        raw_sources = [_text(item) for item in action.get("sources") or [] if _text(item)]
        sources = [item for item in raw_sources if item in allowed_sources]
        valid_metric = [metric_id] if metric_id in allowed_metrics else []
        reason = _grounding_reason(
            [metric_id] if metric_id else [], valid_metric, subject="metric_id",
        ) or _grounding_reason(raw_sources, sources, subject="source")
        if reason:
            _log_grounding_failure(
                kind="action", index=index, category=_text(action.get("priority")),
                reason=reason, request_id=request_id,
                metric_ids_count=1 if metric_id else 0, sources_count=len(raw_sources),
                unknown=[
                    *([metric_id] if metric_id and not valid_metric else []),
                    *(item for item in raw_sources if item not in allowed_sources),
                ],
            )
            raise RuntimeError("AI_UNGROUNDED_ACTION")


# Número escrito em prosa. As bordas impedem ler o "4" de GA4 ou o "5" de
# "top5" como valor: só conta o algarismo que não está colado em letra.
_NUMBER_IN_TEXT = re.compile(
    r"(?<![0-9A-Za-zÀ-ÖØ-öø-ÿ])\d+(?:[.,]\d+)*(?![0-9A-Za-zÀ-ÖØ-öø-ÿ])"
)

# Chaves do schema que são identificadores ou enums, não prosa.
_NON_PROSE_KEYS = frozenset(
    {"metric_ids", "metric_id", "sources", "category", "impact", "confidence", "priority"}
)


def _number_candidates(token: str) -> List[tuple[float, int]]:
    """Leituras legítimas de um número escrito, com as casas decimais de cada.

    `3.506,79`, `3,506.79`, `3506.79` e `3506,79` são o mesmo valor escrito de
    formas diferentes. `12.345` é ambíguo (milhar ou decimal): as duas leituras
    são devolvidas e basta uma estar suportada pelo snapshot.
    """
    digits_only = token.replace(".", "").replace(",", "")
    if not digits_only.isdigit():
        return []
    has_dot, has_comma = "." in token, "," in token
    readings: List[str] = []
    if has_dot and has_comma:
        # O último separador é o decimal; o outro é o de milhar.
        decimal_sep = "." if token.rfind(".") > token.rfind(",") else ","
        readings.append(token.replace("." if decimal_sep == "," else ",", "").replace(decimal_sep, "."))
    elif has_dot or has_comma:
        separator = "." if has_dot else ","
        tail = token.rsplit(separator, 1)[1]
        if token.count(separator) > 1:
            readings.append(digits_only)  # 1.234.567 só pode ser milhar
        elif len(tail) == 3:
            readings.append(digits_only)  # leitura de milhar
            readings.append(token.replace(separator, "."))  # leitura decimal
        else:
            readings.append(token.replace(separator, "."))
    else:
        readings.append(token)
    candidates: List[tuple[float, int]] = []
    for reading in readings:
        try:
            value = float(reading)
        except ValueError:
            continue
        _, _, decimals = reading.partition(".")
        candidates.append((value, len(decimals)))
    return candidates


def _collect_trusted_numbers(value: Any, out: set[float]) -> None:
    # bool é subclasse de int: True/False não podem virar os números 1 e 0.
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        out.add(float(value))
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect_trusted_numbers(item, out)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _collect_trusted_numbers(item, out)


def _trusted_numbers(payload: Dict[str, Any]) -> set[float]:
    """Números verificáveis: os que o backend calculou e enviou ao modelo.

    A fonte é o próprio payload da chamada — o modelo não recebeu nada além
    disso, então qualquer outro número no texto é invenção. Strings do payload
    não entram de propósito: um `last_sync_at` traria dezenas de inteiros
    pequenos e abriria a porta para percentuais arbitrários.
    """
    trusted: set[float] = set()
    for key, section in payload.items():
        if key in {"period", "question", "business_context"}:
            continue
        _collect_trusted_numbers(section, trusted)
    # O período analisado pode ser nomeado: datas de início/fim e duração.
    period = payload.get("period") or {}
    bounds: List[date] = []
    for key in ("start", "end"):
        try:
            parsed = date.fromisoformat(_text(period.get(key)))
        except ValueError:
            continue
        bounds.append(parsed)
        trusted.update({float(parsed.year), float(parsed.month), float(parsed.day)})
    if len(bounds) == 2:
        trusted.add(float((bounds[1] - bounds[0]).days + 1))
    return trusted


def _is_number_supported(token: str, trusted: set[float]) -> bool:
    """O número escrito corresponde a algum valor verificado do snapshot?

    A comparação respeita a precisão escrita: quem escreve `11%` para uma
    variação de 11,11 arredondou um número real; quem escreve `97%` não.
    """
    for value, decimals in _number_candidates(token):
        for known in trusted:
            if round(known, decimals) == round(value, decimals):
                return True
    return False


def _log_numeric_validation_failure(
    *, token: str, text: str, path: str, trusted: set[float], request_id: str | None,
) -> None:
    # Não imprimir fragmentos de contatos/identificadores: inclusive telefones
    # com separadores, que o tokenizer divide em vários números menores.
    sensitive = "@" in text or any(pattern.search(text) for pattern in _LOG_SECRET_PATTERNS) or any(
        len(re.sub(r"\D", "", match)) >= 7
        for match in re.findall(r"\+?\d[\d .()/\-]*\d", text)
    )
    numeric_token = "[redacted]" if sensitive else token
    normalized = "[redacted]" if sensitive else "|".join(
        str(value) for value, _ in _number_candidates(token)
    )
    # O caminho também pode receber uma chave inesperada de JSON. Só expor
    # nomes de campos definidos nos contratos de análise/pergunta.
    fields = {"response", "executive", "overall", "main_change", "opportunity",
              "attention", "priority_action", "insights", "title", "interpretation",
              "action", "reason", "actions", "recommendation", "justification",
              "impact_expected", "answer", "direct_answer", "limitations"}
    safe_path = path if all(
        part in fields for part in re.sub(r"\[\d+\]", "", path).split(".")
    ) else "response.unknown_field"
    print(
        "[intelligence][numeric_validation_failed] "
        f"request_id={_log_safe(request_id or '-', key='request_id')} "
        f"field={safe_path} numeric_token={numeric_token} "
        f"normalized_value={normalized or '-'} reason=unsupported_numeric_value "
        f"trusted_numeric_count={len(trusted)}",
        flush=True,
    )


def _assert_no_untrusted_numeric_text(
    value: Any, path: str = "response", *, trusted: set[float] | None = None,
    request_id: str | None = None,
) -> None:
    """Texto da IA só pode citar número que o backend tenha calculado e enviado.

    Sem conjunto verificado (`trusted` ausente ou vazio) nenhum algarismo é
    aceito, que era o comportamento anterior desta função.
    """
    known = trusted or set()
    if isinstance(value, str):
        for token in _NUMBER_IN_TEXT.findall(value):
            if not _is_number_supported(token, known):
                _log_numeric_validation_failure(
                    token=token, text=value, path=path, trusted=known, request_id=request_id,
                )
                raise RuntimeError(f"AI_UNTRUSTED_NUMERIC_TEXT:{path}")
        # Algarismo colado em letra é identificador, não valor citado: GA4 e
        # Meta Ads são rótulos reais do produto, não afirmações numéricas.
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_untrusted_numeric_text(item, f"{path}[{index}]", trusted=known, request_id=request_id)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _NON_PROSE_KEYS:
                continue
            _assert_no_untrusted_numeric_text(item, f"{path}.{key}", trusted=known, request_id=request_id)


async def _call_provider(
    *,
    payload: Dict[str, Any],
    schema: Dict[str, Any],
    instructions: str,
    request_id: str | None = None,
) -> Dict[str, Any]:
    started = time.monotonic()
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        # Só o código: o valor da variável nunca entra no log.
        log_stage_failed(
            stage=LOG_STAGE_MODEL_REQUEST, request_id=request_id,
            elapsed_ms=_elapsed_ms(started), error_code="MODEL_CONFIGURATION_MISSING",
            provider="openai",
        )
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
    # Só metadados da chamada: nem prompt, nem payload, nem chave.
    log_stage_completed(
        stage=LOG_STAGE_MODEL_REQUEST, request_id=request_id,
        elapsed_ms=_elapsed_ms(started), provider="openai", model=model,
    )
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
            )
    except Exception as exc:
        log_stage_failed(
            stage=LOG_STAGE_MODEL_RESPONSE, request_id=request_id,
            elapsed_ms=_elapsed_ms(started), exc=exc,
            provider="openai", model=model, success="false",
        )
        raise
    if response.status_code >= 400:
        log_stage_failed(
            stage=LOG_STAGE_MODEL_RESPONSE, request_id=request_id,
            elapsed_ms=_elapsed_ms(started), error_code=f"AI_PROVIDER_ERROR_{response.status_code}",
            upstream_status=response.status_code,
            provider="openai", model=model, success="false",
        )
        raise RuntimeError(f"AI_PROVIDER_ERROR_{response.status_code}")
    log_stage_completed(
        stage=LOG_STAGE_MODEL_RESPONSE, request_id=request_id,
        elapsed_ms=_elapsed_ms(started), provider="openai", model=model,
        upstream_status=response.status_code, success="true",
    )
    text = _extract_output_text(response.json())
    if not text:
        raise RuntimeError("AI_PROVIDER_EMPTY_RESPONSE")
    parsed = json.loads(text)
    # O payload é tudo que o modelo recebeu: é ele que define o que é
    # verificável. Vale para a análise e para o /ask, que usam este caminho.
    _assert_no_untrusted_numeric_text(parsed, trusted=_trusted_numbers(payload), request_id=request_id)
    return parsed


async def _call_analysis_with_numeric_repair(
    *, payload: Dict[str, Any], schema: Dict[str, Any], instructions: str,
    request_id: str | None = None,
) -> Dict[str, Any]:
    """Uma regeneração, apenas para rejeição numérica; mesmo contexto/schema.
    A resposta inválida nunca sai de _call_provider nem entra no repair.
    """
    try:
        return await _call_provider(
            payload=payload, schema=schema, instructions=instructions, request_id=request_id,
        )
    except RuntimeError as exc:
        if not str(exc).startswith("AI_UNTRUSTED_NUMERIC_TEXT:"):
            raise
    _log_line("numeric_grounding_repair_started", request_id=request_id or "-", attempt="repair")
    try:
        repaired = await _call_provider(
            payload=payload, schema=schema,
            instructions=instructions + "\nA tentativa anterior foi rejeitada por conter número não suportado. "
            "Gere novamente a resposta estruturada usando somente números explicitamente presentes "
            "nos dados confiáveis fornecidos. Quando não houver número suportado, descreva "
            "qualitativamente. Não invente percentuais, contagens, datas ou valores.",
            request_id=request_id,
        )
    except Exception:
        _log_line("numeric_grounding_repair_failed", request_id=request_id or "-", attempt="repair")
        raise
    _log_line("numeric_grounding_repair_succeeded", request_id=request_id or "-", attempt="repair")
    return repaired


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


ANALYSIS_VERSION = "v2-commerce-provider-ga4-user-semantics"


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


# Etapas da análise, para o log dizer o que falhou sem vazar nada.
STAGE_CONTEXT = "INTELLIGENCE_CONTEXT_ERROR"
STAGE_COMMERCE = "INTELLIGENCE_COMMERCE_ERROR"
STAGE_MODEL = "INTELLIGENCE_MODEL_ERROR"
STAGE_VALIDATION = "INTELLIGENCE_VALIDATION_ERROR"
STAGE_PERSISTENCE = "INTELLIGENCE_PERSISTENCE_ERROR"
# Colunas que só existem depois da migration 039. Enquanto ela não for
# aplicada, a análise é gravada sem elas e o log diz que falta migration —
# em vez de a geração inteira falhar por coluna ausente.
OPTIONAL_ANALYSIS_COLUMNS = ("context_fingerprint",)


async def _insert_analysis(
    row: Dict[str, Any], *, request_id: str | None = None,
) -> Dict[str, Any] | None:
    """Grava a análise tolerando coluna ainda não migrada."""
    attempt = dict(row)
    started = time.monotonic()
    while True:
        try:
            saved = await sb_insert("ai_analyses", attempt)
        except httpx.HTTPStatusError as exc:
            missing = next(
                (
                    column for column in OPTIONAL_ANALYSIS_COLUMNS
                    if column in attempt and _is_column_compat_error(exc, column)
                ),
                "",
            )
            if not missing:
                # PostgREST recusou por outro motivo: código e status no log,
                # nunca o body (pode carregar a linha inteira).
                log_stage_failed(
                    stage=LOG_STAGE_PERSISTENCE, request_id=request_id,
                    elapsed_ms=_elapsed_ms(started), exc=exc,
                )
                raise
            print(
                f"[intelligence][schema_pending] column={missing} "
                "migration=20261003_000039_client_business_context action=insert_without_column"
            )
            attempt.pop(missing, None)
        except Exception as exc:
            log_stage_failed(
                stage=LOG_STAGE_PERSISTENCE, request_id=request_id,
                elapsed_ms=_elapsed_ms(started), exc=exc,
            )
            raise
        else:
            log_stage_completed(
                stage=LOG_STAGE_PERSISTENCE, request_id=request_id,
                elapsed_ms=_elapsed_ms(started), status=_log_safe(attempt.get("status")),
            )
            return saved


# Geração chama a OpenAI e custa dinheiro. Qualquer membro da empresa pode
# pedir, então a proteção é no servidor, não na interface. O cooldown mede
# contra a última análise REALMENTE gerada para o tenant+período, lida do
# banco — vale entre instâncias do Render, sem depender de estado em memória.
INTELLIGENCE_GENERATION_COOLDOWN_SECONDS = float(
    os.getenv("INTELLIGENCE_GENERATION_COOLDOWN_SECONDS", "60")
)

# Cliques concorrentes no mesmo worker colapsam no mesmo lock: o segundo
# espera o primeiro terminar e, ao seguir, encontra a análise recém-gravada
# reutilizável pelo fingerprint — sem uma segunda chamada ao provedor.
_GENERATION_LOCKS: Dict[str, asyncio.Lock] = {}


def _generation_lock(client_id: str, period: Dict[str, Any]) -> asyncio.Lock:
    key = f"{_text(client_id)}|{_text(period.get('start'))}|{_text(period.get('end'))}"
    lock = _GENERATION_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _GENERATION_LOCKS[key] = lock
    return lock


async def _generation_cooldown_remaining(
    *, client_id: str, period: Dict[str, Any],
) -> float:
    """Segundos que faltam para o tenant poder gerar de novo.

    Só conta análise concluída: uma tentativa que falhou não bloqueia quem
    está tentando resolver o problema.
    """
    if INTELLIGENCE_GENERATION_COOLDOWN_SECONDS <= 0:
        return 0.0
    try:
        rows = await sb_select(
            "ai_analyses",
            select="client_id,created_at,completed_at,status",
            filters={
                "client_id": f"eq.{_text(client_id)}",
                "period_start": f"eq.{period['start']}",
                "period_end": f"eq.{period['end']}",
                "status": "eq.completed",
            },
            order="created_at.desc", limit=1,
        )
    except Exception as exc:  # noqa: BLE001 - sem leitura, não bloqueia
        print(
            f"[intelligence][cooldown] client_id={_text(client_id)} "
            f"status=lookup_unavailable error_type={exc.__class__.__name__}",
            flush=True,
        )
        return 0.0
    row = rows[0] if rows else None
    if not row or _text(row.get("client_id")) != _text(client_id):
        return 0.0
    generated_at = _parse_timestamp(row.get("completed_at") or row.get("created_at"))
    if generated_at is None:
        return 0.0
    elapsed = (datetime.now(timezone.utc) - generated_at.astimezone(timezone.utc)).total_seconds()
    return max(0.0, INTELLIGENCE_GENERATION_COOLDOWN_SECONDS - elapsed)


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
    request_id: str | None = None,
) -> Dict[str, Any]:
    # request_started é emitido pela rota, que é a entrada real do HTTP e
    # conhece o período pedido antes de qualquer resolução.
    snapshot_started = time.monotonic()
    try:
        snapshot = await calculate_intelligence_snapshot(
            client_id=client_id, start=start, end=end, days=days, request_id=request_id,
        )
    except BaseException as exc:
        log_stage_failed(
            stage=LOG_STAGE_SNAPSHOT, request_id=request_id,
            elapsed_ms=_elapsed_ms(snapshot_started), exc=exc,
        )
        raise
    log_stage_completed(
        stage=LOG_STAGE_SNAPSHOT, request_id=request_id,
        elapsed_ms=_elapsed_ms(snapshot_started),
        metrics=len(snapshot.get("metrics") or []),
        sources=len(snapshot.get("sources") or []),
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
        saved = await _insert_analysis(
            {**base_row, "status": "configuration_pending", "error_code": "AI_PROVIDER_NOT_CONFIGURED"},
            request_id=request_id,
        )
        return {
            "ok": True,
            "provider_configured": False,
            "status": "configuration_pending",
            "snapshot": snapshot,
            "analysis": saved,
        }
    def reused_payload(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "ok": True,
            "provider_configured": True,
            "status": "completed",
            "reused": True,
            "snapshot": snapshot,
            "analysis": row,
        }

    reusable = await _reusable_analysis(client_id=client_id, period=period, fingerprint=fingerprint)
    if reusable:
        print(f"[intelligence][cache] client_id={client_id} status=reused period={period['start']}..{period['end']}")
        return reused_payload(reusable)

    # Daqui para baixo a chamada ao provedor é real. O lock serializa cliques
    # concorrentes no mesmo worker; o cooldown protege contra insistência.
    async with _generation_lock(client_id, period):
        # Quem esperou no lock pode encontrar pronta a análise que o primeiro
        # acabou de gravar: devolve aquela em vez de gerar outra igual.
        reusable = await _reusable_analysis(
            client_id=client_id, period=period, fingerprint=fingerprint,
        )
        if reusable:
            print(
                f"[intelligence][cache] client_id={client_id} status=reused_after_wait "
                f"period={period['start']}..{period['end']}",
                flush=True,
            )
            return reused_payload(reusable)
        remaining = await _generation_cooldown_remaining(client_id=client_id, period=period)
        if remaining > 0:
            print(
                f"[intelligence][cooldown] client_id={client_id} request_id={request_id or '-'} "
                f"status=blocked retry_after_seconds={int(remaining) + 1}",
                flush=True,
            )
            raise RuntimeError(f"AI_GENERATION_COOLDOWN:{int(remaining) + 1}")
        return await _generate_with_provider(
            client_id=client_id, snapshot=snapshot, period=period,
            base_row=base_row, request_id=request_id,
        )


async def _generate_with_provider(
    *,
    client_id: str,
    snapshot: Dict[str, Any],
    period: Dict[str, Any],
    base_row: Dict[str, Any],
    request_id: str | None,
) -> Dict[str, Any]:
    """Chamada real ao provedor, validação e persistência."""
    generation_started = time.monotonic()
    policy = _build_analysis_policy(snapshot)
    try:
        analysis = await _call_analysis_with_numeric_repair(
            payload={
                "period": period,
                # source_ids resolve o rótulo de procedência para os IDs reais
                # de `sources`, o único vocabulário que a validação aceita.
                "metrics": _metrics_with_source_ids(snapshot),
                "sources": snapshot["sources"],
                "quality": snapshot["quality"],
                "crossings": snapshot["crossings"],
                "top_campaigns": snapshot["top_campaigns"],
                "analysis_policy": policy,
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
            request_id=request_id,
        )
        validation_started = time.monotonic()
        # Apelido de fonte ("fbits") traduzido para o ID real ("commerce")
        # antes de qualquer verificação. ID inexistente segue adiante e é
        # recusado pela validação.
        analysis = _normalize_grounding_ids(analysis, snapshot, request_id=request_id)
        # Quando o período inclui hoje, a ressalva de dia parcial é garantida
        # pelo backend antes da validação — que continua sendo o portão e
        # ainda acusa AI_MISSING_PARTIAL_TODAY_LIMITATION se faltar.
        analysis, limitation_applied = _ensure_partial_today_limitation(
            analysis, snapshot, policy=policy,
        )
        if limitation_applied:
            _log_line(
                "partial_today_limitation_applied",
                request_id=request_id or "-",
                client_id=client_id,
                stage=LOG_STAGE_VALIDATION,
            )
        try:
            _validate_analysis_grounding(
                analysis, snapshot, policy=policy, request_id=request_id,
            )
        except BaseException as exc:
            # O código específico do grounding (AI_UNGROUNDED_INSIGHT etc.)
            # sai no log sem nenhuma regra ser relaxada.
            log_stage_failed(
                stage=LOG_STAGE_VALIDATION, request_id=request_id,
                elapsed_ms=_elapsed_ms(validation_started), exc=exc,
            )
            raise
        log_stage_completed(
            stage=LOG_STAGE_VALIDATION, request_id=request_id,
            elapsed_ms=_elapsed_ms(validation_started),
            insights=len(analysis.get("insights") or []),
            actions=len(analysis.get("actions") or []),
        )
        analysis = _sanitize_analysis(analysis, snapshot)
        saved = await _insert_analysis(
            {
                **base_row,
                "status": "completed",
                "analysis": analysis,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
            request_id=request_id,
        )
        return {
            "ok": True,
            "provider_configured": True,
            "status": "completed",
            "snapshot": snapshot,
            "analysis": saved,
        }
    except Exception as exc:
        # Etapa identificada no log; o cliente recebe mensagem genérica.
        stage = STAGE_VALIDATION if isinstance(exc, AssertionError) else STAGE_MODEL
        code = _text(exc)[:80] or "AI_PROVIDER_ERROR"
        if not _already_logged(exc):
            # Falha que não passou por nenhuma etapa instrumentada (ex.:
            # AI_PROVIDER_EMPTY_RESPONSE, JSON inválido): nenhuma exceção
            # chega ao 502 sem uma linha estruturada antes.
            log_stage_failed(
                stage=(
                    LOG_STAGE_VALIDATION if isinstance(exc, AssertionError)
                    else LOG_STAGE_MODEL_RESPONSE
                ),
                request_id=request_id,
                elapsed_ms=_elapsed_ms(generation_started),
                exc=exc,
            )
        # `code` é a mensagem crua da exceção: uma falha de rede pode trazer a
        # URL com Authorization dentro. Vai sanitizada para o log; o valor
        # gravado na linha `failed` segue o mesmo de antes.
        print(
            f"[intelligence][generate] client_id={client_id} request_id={request_id or '-'} "
            f"stage={stage} status=error error_type={exc.__class__.__name__} "
            f"code={_log_safe(code)}"
        )
        try:
            await _insert_analysis(
                {**base_row, "status": "failed", "error_code": code}, request_id=request_id,
            )
        except Exception as persistence_error:
            # Falha ao registrar não pode esconder a falha original.
            print(
                f"[intelligence][generate] client_id={client_id} stage={STAGE_PERSISTENCE} "
                f"status=error error_type={persistence_error.__class__.__name__}"
            )
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
