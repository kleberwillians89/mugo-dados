"""Leituras autorizadas e minimizadas. Nenhum texto livre é atestado como seguro."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
from contextvars import ContextVar
import json
import math
import os
import re
from datetime import date, datetime, timedelta, timezone

from services.tenant import require_user_client_access
from services.ig_supabase import sb_select

authorized_company = ContextVar("mcp_authorized_company", default=None)
# Empresas escolhidas na autorização do conector (None = conexão anterior ao escopo).
company_scope = ContextVar("mcp_company_scope", default=None)
reference_key = ContextVar("mcp_reference_key", default=None)

TOOLS = (
    "list_companies", "get_data_freshness", "get_business_overview", "get_paid_media",
    "get_site_traffic", "get_sales_by_origin", "get_customer_summary", "get_goals",
    "get_business_context", "get_latest_analysis",
)
SOURCES = frozenset({"meta", "meta_ads", "google_ads", "ga4", "shopify", "fbits", "instagram", "commerce", "paid_media", "shopify+paid_media"})
STATUSES = frozenset({"available", "partial", "unavailable", "no_data", "disconnected", "error", "good", "limited", "ok", "stale", "not_connected", "migration_pending", "connected", "active", "ready", "confirmed", "connected_no_data"})
NUMERIC = frozenset({"spend", "investment", "revenue", "orders", "average_ticket", "impressions", "clicks", "ctr", "cpc", "conversions", "conversion_value", "roas", "cpa", "sessions", "active_users", "total_users", "event_count", "purchases", "purchase_revenue", "total_revenue", "customers", "new_customers", "repeat_customers", "recurring_customers", "repeat_rate", "target_value", "actual", "progress_percent", "remaining", "share_of_revenue", "orders_with_origin", "orders_with_utm", "origin_coverage_percent", "utm_coverage_percent", "transactions", "key_events", "engaged_sessions", "screen_page_views", "new_users", "ecommerce_purchases", "elapsed_percent", "projected_value", "pace_delta"})
OMITTED = "Itens de texto que continham padrão de e-mail, CPF/CNPJ ou telefone foram omitidos. Dados de compradores nunca são retornados."

# Dados de NEGÓCIO (nome de campanha, origem/mídia, página, contexto e análise)
# são da empresa e voltam em texto. O que protegemos é a pessoa compradora:
# qualquer texto com cara de e-mail, CPF/CNPJ, telefone ou sequência longa de
# dígitos é descartado inteiro (nunca "mascarado" pela metade).
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_CPF_CNPJ = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b|\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
_PHONE = re.compile(r"\(?\b\d{2}\)?[\s-]?9?\d{4}[\s-]?\d{4}\b")
_LONG_DIGITS = re.compile(r"\d{10,}")
_SPACES = re.compile(r"\s+")


def business_text(value, limit=200):
    if not isinstance(value, str):
        return None
    text = _SPACES.sub(" ", value).strip()
    if not text or any(pattern.search(text) for pattern in (_EMAIL, _CPF_CNPJ, _PHONE, _LONG_DIGITS)):
        return None
    return text[:limit]


def page_path(value):
    from urllib.parse import unquote, urlsplit
    if not isinstance(value, str) or not value.strip():
        return None
    # Só o caminho: query string e fragmento podem carregar e-mail ou token.
    return business_text(unquote(urlsplit(value.strip()).path or "/"), limit=200)


class ToolFailure(Exception):
    """Mensagem pública fixa, nunca a mensagem original de uma dependência."""


def number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return value
    return None


def numeric_fields(row):
    return {key: number(row.get(key)) for key in sorted(NUMERIC & row.keys())}


def timestamp(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).isoformat()
    except (ValueError, TypeError):
        return None


def iso_day(value):
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (ValueError, TypeError):
        return None


def period(start=None, end=None):
    try:
        if (start is None) != (end is None):
            raise ValueError
        until = date.fromisoformat(end) if end else datetime.now(timezone.utc).date()
        since = date.fromisoformat(start) if start else until - timedelta(days=29)
        if not 1 <= (until - since).days + 1 <= 400:
            raise ValueError
        return {"start": since.isoformat(), "end": until.isoformat()}
    except (ValueError, TypeError):
        raise ToolFailure("Informe início e fim no formato AAAA-MM-DD, com intervalo de até 400 dias.") from None


def opaque(value):
    key = reference_key.get()
    if key is None:
        raise ToolFailure("Consulta sem contexto de privacidade.")
    return hmac.new(key, str(value).encode(), hashlib.sha256).hexdigest()[:24]


def state(value):
    return value if value in STATUSES else "unavailable"


def source_rows(rows):
    result = []
    for row in rows:
        key = row.get("id")
        if key not in SOURCES:
            continue
        if key == "commerce" and row.get("provider") in {"shopify", "fbits"}:
            key = row["provider"]
        coverage = row.get("coverage") or {}
        result.append({"id": key, "status": state(row.get("status")), "connected": row.get("connected") is True,
            "last_sync_at": timestamp(row.get("last_sync_at")),
            "coverage": {"covered_days": number(coverage.get("covered_days", row.get("covered_days"))),
                "expected_days": number(coverage.get("expected_days")), "is_partial": coverage.get("is_partial") if isinstance(coverage.get("is_partial"), bool) else None,
                "start": iso_day(coverage.get("coverage_start")), "end": iso_day(coverage.get("coverage_end"))},
            "data_max_available": iso_day(row.get("data_max_available"))})
    return result


def metrics(rows):
    # IDs/unidades/fontes pertencem ao catálogo determinístico, não a rótulos do modelo.
    result = []
    for row in rows:
        mid = row.get("id", "")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", str(mid)):
            continue
        result.append({"id": mid, "value": number(row.get("value")),
            "previous_value": number(row.get("previous_value")), "variation_percent": number(row.get("variation_percent")),
            "unit": row.get("format") if row.get("format") in {"currency", "integer", "percent", "decimal", "ratio", "number"} else None,
            "source": row.get("source") if row.get("source") in SOURCES else None, "status": state(row.get("status"))})
    return result


async def snapshot(cid, window):
    if (date.fromisoformat(window["end"]) - date.fromisoformat(window["start"])).days >= 366:
        raise ToolFailure("O serviço canônico existente suporta até 366 dias. Reduza o período; os dados não foram recortados nem somados artificialmente.")
    from services.intelligence import calculate_intelligence_snapshot
    result = await calculate_intelligence_snapshot(client_id=cid, **window,
        include_commerce_details=False, include_external_research=False)
    if (result.get("client") or {}).get("id") != cid:
        raise ToolFailure("A origem dos dados não pôde ser confirmada.")
    return result


async def connected(cid, window):
    from services.intelligence_tools import ReadTools
    reader = ReadTools(cid, window, None)
    discovery = await reader.discover()
    return discovery["sources"], discovery["limitations"]


_SOURCES_LIMIT = asyncio.Semaphore(8)
_COMPANY_SOURCES_TIMEOUT = 4.0


async def authorized_companies(uid, pilots=None):
    """Empresas que o usuário acessa agora (membership/papéis lidos sem cache).

    `list_clients_for_user(fresh=True)` já aplica as regras de acesso do painel
    (platform_admin e agency_admin veem todas; os demais, só as memberships).
    Leve o bastante para a tela de consentimento: só id e nome da empresa.
    """
    if pilots is None:
        pilots = {v.strip() for v in os.getenv("MCP_PILOT_CLIENT_IDS", "").split(",") if v.strip()}
    from services.clients import list_clients_for_user
    candidates = (await list_clients_for_user(uid, limit=100, fresh=True))["clients"]
    companies = []
    for candidate in candidates[:100]:
        key = str(candidate.get("client_id") or "")
        if not key or (pilots and key not in pilots):
            continue
        # Nome empresarial cadastrado, não nome de comprador.
        companies.append({"id": key, "name": candidate.get("name")})
    return companies


async def dispatch(user_id: str, name: str, company_id=None, start=None, end=None, provider=None):
    key_token = reference_key.set(secrets.token_bytes(32))
    try:
        return await _dispatch(user_id, name, company_id, start, end, provider)
    finally:
        reference_key.reset(key_token)


async def _dispatch(user_id, name, company_id, start, end, provider):
    if name not in TOOLS or not user_id:
        raise ToolFailure("Ferramenta ou usuário não autorizado.")
    window = period(start, end)
    pilots = {v.strip() for v in os.getenv("MCP_PILOT_CLIENT_IDS", "").split(",") if v.strip()}
    if name != "list_companies":
        # IDs não são expressões PostgREST. Falha antes de consultar qualquer dado.
        if not isinstance(company_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", company_id):
            raise ToolFailure("Identificador de empresa inválido.")
        if pilots and company_id not in pilots:
            raise ToolFailure("Empresa não disponível no piloto.")
        scope = company_scope.get()
        if scope is not None and company_id not in scope:
            raise ToolFailure("Empresa fora das autorizadas nesta conexão. Reconecte o conector para incluí-la.")
        try:
            async with asyncio.timeout(8):
                await require_user_client_access(user_id, company_id, fresh=True)
                authorized_company.set(company_id)
        except Exception:
            # Nenhum detalhe de existência, conexão ou credencial vaza ao solicitante.
            raise ToolFailure("Acesso à empresa não autorizado ou indisponível.") from None
    try:
        async with asyncio.timeout(20):
            data = await _read(user_id, name, company_id, window, provider, pilots)
    except ToolFailure:
        raise
    except TimeoutError:
        raise ToolFailure("A leitura excedeu o tempo disponível. Tente novamente mais tarde.") from None
    except Exception:
        raise ToolFailure("Dados indisponíveis no momento. Nenhuma sincronização foi executada.") from None
    result = {"period": window, **data}
    result.setdefault("observacoes", [])
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > 65536:
        raise ToolFailure("Resultado excede o limite de leitura. Selecione um período menor.")
    return result


async def _read(uid, name, cid, window, provider, pilots):
    if name == "list_companies":
        companies = await authorized_companies(uid, pilots)
        scope = company_scope.get()
        if scope is not None:
            companies = [company for company in companies if company["id"] in scope]

        async def with_sources(company):
            # Leitura curta e paralela: uma empresa lenta não trava a lista.
            async with _SOURCES_LIMIT:
                try:
                    async with asyncio.timeout(_COMPANY_SOURCES_TIMEOUT):
                        sources, _ = await connected(company["id"], window)
                except Exception:
                    sources = None
            return {**company, "sources": sources}

        listed = await asyncio.gather(*(with_sources(company) for company in companies))
        return {"companies": list(listed), "observacoes": [
            "Listagem limitada a 100 empresas; acesso revalidado nesta chamada.",
            "sources nulo = fontes não verificadas a tempo; consulte get_data_freshness da empresa."]}
    if name == "get_business_context":
        from services.business_context import load_business_context
        context = await load_business_context(cid)
        from services.business_context import FIELDS
        fields = context.get("context") or {}
        text = {field: business_text(fields.get(field), 1200) for field in FIELDS}
        return {"available": context.get("available") is True, "updated_at": timestamp(context.get("updated_at")),
                "context": {key: value for key, value in text.items() if value}, "observacoes": [OMITTED,
                "Contexto escrito pela própria empresa/agência; use como premissa, não como dado medido."]}
    if name == "get_latest_analysis":
        from services.technical_text import humanize_analysis_row
        rows = await sb_select("ai_analyses", select="client_id,period_start,period_end,status,created_at,completed_at,analysis,metrics_snapshot,sources",
            filters={"client_id": f"eq.{cid}", "status": "eq.completed"}, order="created_at.desc", limit=1)
        row = next((r for r in rows if r.get("client_id") == cid), None)
        if not row:
            return {"analysis": None, "observacoes": ["Nenhuma análise salva para esta empresa. Nenhuma análise foi gerada agora."]}
        analysis = (humanize_analysis_row(dict(row)).get("analysis") or {}) if isinstance(row.get("analysis"), dict) else {}
        executive = analysis.get("executive") if isinstance(analysis.get("executive"), dict) else {}
        insights = [item for item in analysis.get("insights") or [] if isinstance(item, dict)][:8]
        actions = [item for item in analysis.get("actions") or [] if isinstance(item, dict)][:8]
        return {"analysis": {
            "period_start": iso_day(row.get("period_start")), "period_end": iso_day(row.get("period_end")),
            "created_at": timestamp(row.get("created_at")),
            "executive": {key: business_text(value, 600) for key, value in executive.items()
                          if key in {"overall", "main_change", "opportunity", "attention", "priority_action"}},
            "insights": [{"category": business_text(item.get("category"), 40), "title": business_text(item.get("title"), 200),
                          "interpretation": business_text(item.get("interpretation"), 600), "action": business_text(item.get("action"), 400)}
                         for item in insights],
            "actions": [{"recommendation": business_text(item.get("recommendation"), 400),
                         "justification": business_text(item.get("justification"), 600),
                         "impact_expected": business_text(item.get("impact_expected"), 200)} for item in actions],
        }, "observacoes": [OMITTED, "Análise salva anteriormente; os números podem ter mudado desde então. Confirme com get_business_overview."]}
    if name == "get_goals":
        from services.goals import list_goals, METRICS
        data = await list_goals(cid, **window)
        return {"goals": [{**numeric_fields(row), "metric": row.get("metric") if row.get("metric") in METRICS else None,
            "status": row.get("status") if row.get("status") in {"FUTURA", "INDISPONIVEL", "META_ATINGIDA", "NO_RITMO", "ATENCAO", "ABAIXO_DO_RITMO"} else None, "period_start": iso_day(row.get("period_start")),
            "period_end": iso_day(row.get("period_end"))} for row in data.get("goals", [])[:50]], "observacoes": [OMITTED, "Máximo de 50 metas."]}
    if name == "get_sales_by_origin":
        from services.sales_by_origin import build_sales_by_origin, CHANNEL_LABELS
        data = await build_sales_by_origin(cid, **window)
        return {"provider": data.get("provider") if data.get("provider") in {"shopify", "fbits"} else None,
            "status": state(data.get("status")), "totals": numeric_fields(data.get("totals", {})),
            "channels": [{"channel": row.get("channel"), **numeric_fields(row)} for row in data.get("channels", [])[:50] if row.get("channel") in CHANNEL_LABELS],
            "campaigns": [{"campaign": business_text(row.get("campaign")), "source": business_text(row.get("source"), 80),
                "medium": business_text(row.get("medium"), 80), "channel": row.get("channel") if row.get("channel") in CHANNEL_LABELS else None,
                **numeric_fields(row)} for row in data.get("campaigns", [])[:50]],
            "observacoes": [OMITTED, "Atribuição por origem não comprova causalidade nem equivale à atribuição das plataformas."]}
    if name == "get_paid_media":
        if provider not in {"meta", "google_ads"}:
            raise ToolFailure("Selecione meta ou google_ads.")
        sources, limitations = await connected(cid, window)
        if provider not in sources:
            return {"provider": provider, "totals": {}, "campaigns": [], "observacoes": ["Integração indisponível.", *limitations]}
        if provider == "meta":
            from services.dashboard_paid import get_paid_dashboard, list_campaigns
            data = await get_paid_dashboard(cid, **window)
            campaigns = await list_campaigns(cid, **window, limit=50)
            return {"provider": provider, "totals": numeric_fields(data.get("totals", {})),
                "campaigns": [{"name": business_text(row.get("campaign_name") or row.get("name")), **numeric_fields(row)}
                    for row in campaigns.get("campaigns", [])[:50]], "observacoes": [OMITTED, *limitations]}
        from services.google_ads import resolve_google_ads_context, build_google_ads_report
        context = await resolve_google_ads_context(cid)
        if context.client_id != cid:
            raise ToolFailure("A conexão não pertence à empresa autorizada.")
        data = await build_google_ads_report(client_id=cid, context=context, **window)
        rows = await sb_select("google_ads_daily_stats", select="client_id,connection_id,customer_id,stat_date,campaign_id,campaign_name,cost,impressions,clicks,conversions,conversion_value",
            filters={"client_id": f"eq.{cid}", "connection_id": f"eq.{context.connection_id}", "customer_id": f"eq.{context.customer_id}",
                "and": f"(stat_date.gte.{window['start']},stat_date.lte.{window['end']})"}, order="stat_date.asc", limit=2001)
        campaigns = []
        if len(rows) <= 2000:
            from services.dashboard_paid import _sum_grouped_rows
            safe = [{**r, "spend": r.get("cost"), "revenue": r.get("conversion_value")} for r in rows
                if r.get("client_id") == cid and r.get("connection_id") == context.connection_id
                and r.get("customer_id") == context.customer_id and window["start"] <= str(r.get("stat_date") or "") <= window["end"]]
            campaigns = [{"name": business_text(r.get("campaign_name")), **numeric_fields(r)}
                for r in _sum_grouped_rows(safe, "campaign_id", "campaign_name")[:50]]
        else:
            limitations.append("Detalhamento excede 2.000 registros; campanhas omitidas para não publicar totais truncados.")
        return {"provider": provider, "totals": numeric_fields(data.get("totals", {})), "campaigns": campaigns,
            "coverage": {k: number(v) for k, v in data.get("coverage", {}).items() if k in {"covered_days", "expected_days"}},
            "observacoes": [OMITTED, "Totais usam o relatório persistido existente, limitado a 20.000 registros.", *limitations]}
    if name == "get_site_traffic":
        sources, limitations = await connected(cid, window)
        if "ga4" not in sources:
            return {"summary": {}, "channels": [], "landing_pages": [], "observacoes": ["Integração GA4 indisponível.", *limitations]}
        from services.ga4_connections import resolve_ga4_connection_context
        from services.ga4_reporting import _build_summary, _build_daily_rows, _build_channel_items, _select_ga4_rollup, GA4ReportPeriod
        context = await resolve_ga4_connection_context(cid)
        if context.client_id != cid:
            raise ToolFailure("A conexão não pertence à empresa autorizada.")
        report_period = GA4ReportPeriod(start=date.fromisoformat(window["start"]), end=date.fromisoformat(window["end"]),
            days=(date.fromisoformat(window["end"]) - date.fromisoformat(window["start"])).days + 1)
        filters = {"client_id": f"eq.{cid}", "property_id": f"eq.{context.property_id}",
            "and": f"(stat_date.gte.{window['start']},stat_date.lte.{window['end']})"}
        def scoped(rows):
            return [r for r in rows if r.get("client_id") == cid and str(r.get("property_id")) == context.property_id
                and window["start"] <= str(r.get("stat_date") or "") <= window["end"]]
        daily = await sb_select("ga4_daily_stats", select="client_id,property_id,stat_date,sessions,engaged_sessions,screen_page_views,key_events,transactions,new_users,active_users,total_users,event_count,ecommerce_purchases,purchase_revenue,total_revenue",
            filters=filters, order="stat_date.asc", limit=401)
        if len(daily) > 400:
            daily = []
            limitations.append("Métricas diárias excedem o limite de leitura e foram omitidas.")
        daily = scoped(daily)
        # Somas prontas no banco (migração 047): o ano inteiro cabe numa chamada.
        rollup = await _select_ga4_rollup(client_id=cid, property_id=context.property_id, period=report_period,
            parts=("channels", "landing_pages"))
        if rollup is not None:
            channels = _build_channel_items(rollup["channels"])
        else:
            channels = await sb_select("ga4_channel_stats", select="client_id,property_id,stat_date,source_medium,source,medium,sessions,active_users,total_users,event_count,ecommerce_purchases,purchase_revenue,total_revenue",
                filters=filters, order="stat_date.asc", limit=2001)
            if len(channels) > 2000:
                channels = []
                limitations.append("Canais excedem 2.000 registros; detalhamento omitido para não apresentar somas truncadas.")
            channels = _build_channel_items(scoped(channels))
        summary = _build_summary(_build_daily_rows(report_period, daily)) if daily else {}
        dates = {str(r["stat_date"]) for r in daily}
        coverage = {"coverage_start": min(dates, default=None), "coverage_end": max(dates, default=None),
            "distinct_dates": len(dates), "expected_days": report_period.days}
        if rollup is not None:
            # Já somadas e do escopo pedido; mantêm o formato da leitura diária.
            pages = [{"client_id": cid, "property_id": context.property_id, "stat_date": window["start"],
                      "landing_page": row.get("landing_page"), "sessions": row.get("sessions")}
                     for row in rollup["landing_pages"]]
        else:
            pages = await sb_select("ga4_landing_page_stats", select="client_id,property_id,stat_date,landing_page,sessions",
                filters={"client_id": f"eq.{cid}", "property_id": f"eq.{context.property_id}",
                    "and": f"(stat_date.gte.{window['start']},stat_date.lte.{window['end']})"}, order="stat_date.asc", limit=2001)
        landing = {}
        if rollup is None and len(pages) > 2000:
            limitations.append("Landing pages excedem 2.000 registros; detalhamento omitido para não apresentar somas truncadas.")
        else:
            for row in pages:
                sessions = number(row.get("sessions"))
                if (row.get("client_id") != cid or str(row.get("property_id")) != context.property_id
                        or not window["start"] <= str(row.get("stat_date") or "") <= window["end"]
                        or not row.get("landing_page") or sessions is None):
                    continue
                path = page_path(row["landing_page"])
                if path is None:
                    continue
                landing[path] = landing.get(path, 0) + sessions
        return {"source": "ga4", "summary": numeric_fields(summary),
            "user_count_semantics": "sum_of_daily_users",
            "coverage": {"start": iso_day(coverage.get("coverage_start")), "end": iso_day(coverage.get("coverage_end")),
                "distinct_dates": number(coverage.get("distinct_dates")), "expected_days": number(coverage.get("expected_days"))},
            "channels": [{"source_medium": business_text(row.get("source_medium"), 120), **numeric_fields(row)} for row in channels[:50]],
            "landing_pages": [{"path": path, "sessions": value} for path, value in sorted(landing.items(), key=lambda item: item[1], reverse=True)[:50]],
            "observacoes": [OMITTED, "Usuários seguem a soma diária do relatório existente; não são visitantes únicos deduplicados no período.",
                "Landing pages mostram só o caminho da página, sem parâmetros da URL.", *limitations]}
    data = await snapshot(cid, window)
    sources = source_rows(data.get("sources", []))
    values = metrics(data.get("metrics", []))
    if name == "get_data_freshness":
        from services.freshness import source_freshness
        by_id = {r["id"]: r for r in sources}
        result = []
        for key in ("meta", "google_ads", "ga4", "shopify", "fbits", "instagram"):
            row = by_id.get(key, {"id": key, "connected": False, "status": "unavailable"})
            fresh = source_freshness("meta_ads" if key == "meta" else key, row.get("last_sync_at"), data_available=row.get("status") in {"available", "partial"})
            result.append({**row, "status": "sem_dados" if row.get("status") not in {"available", "partial"} else "atrasada" if fresh.get("stale") else "ok",
                "stale": fresh.get("stale"), "coverage_status": row.get("status")})
        return {"sources": result, "observacoes": ["Consulte a cobertura antes de comparar fontes; tentativa ou coleta parcial não atesta sucesso integral."]}
    if name == "get_customer_summary":
        return {"total": None, "repurchase_rate": None, "ticket_by_group": None,
            "metrics": [m for m in values if m["id"] in {"new_customers", "repeat_customers", "recurring_customers", "average_ticket", "repurchase_rate"}],
            "sources": sources, "observacoes": ["Somente agregados canônicos disponíveis. Grupos sem agregado persistido não são calculados a partir de compradores."]}
    return {"metrics": values, "sources": sources, "previous_period": {
        "start": iso_day((data.get("period") or {}).get("previous_start")), "end": iso_day((data.get("period") or {}).get("previous_end"))},
        "observacoes": ["Comparativos dependem da cobertura e da compatibilidade de cada métrica. Valores ausentes não equivalem a zero."]}
