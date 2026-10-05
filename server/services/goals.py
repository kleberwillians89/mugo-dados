"""Metas: somente leituras persistidas, sem sync, credenciais ou IA."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from math import isfinite
from .ig_supabase import sb_select
from .fbits_reporting import _valid_metrics
from .commerce_context import select_commerce_connection

METRICS = {"revenue", "orders", "average_ticket", "ad_spend", "roas", "conversions", "followers", "reach", "impressions", "engagement"}
ADDITIVE = {"revenue", "orders", "ad_spend", "conversions", "impressions", "engagement"}
PACE_TOLERANCE = 5
ATTENTION_TOLERANCE = 15
MIN_PROJECTION_FRACTION = 0.05
MAX_ROWS = 20000

def unavailable(reason):
    return {"available": False, "actual": None, "origin": None, "reason": reason}

def value(actual, origin, projection_ready=False):
    if actual is None or not isfinite(float(actual)):
        return unavailable("Não há valor válido persistido para este indicador.")
    return {"available": True, "actual": float(actual), "origin": origin, "reason": None, "projection_ready": projection_ready}

async def own_rows(table, cid, **kwargs):
    filters = {**kwargs.pop("filters", {}), "client_id": f"eq.{cid}"}
    kwargs.setdefault("order", "metric_date.asc" if table == "dashboard_daily_metrics" else "id.asc")
    rows = []
    # Não presumir que PostgREST devolve todo o limit solicitado.
    while True:
        page = await sb_select(table, filters=filters, limit=500, offset=len(rows), **kwargs)
        if not page:
            break
        rows.extend(page)
        if len(rows) >= MAX_ROWS:
            raise ValueError("A leitura excede o limite seguro de agregação.")
    return [row for row in rows if row.get("client_id") == cid]

async def resolve_goal_actual(client_id, metric, period_start, period_end):
    if metric not in METRICS:
        return unavailable("Indicador não suportado.")
    start, end = str(period_start), str(period_end)
    # Nunca incluir datas posteriores a hoje na observação do progresso.
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).date().isoformat()
    observed_end = min(end, today)
    if start > observed_end:
        return unavailable("O período ainda não começou.")
    if metric == "reach" and start != end:
        return unavailable("Alcance único do período não está persistido; somar dias duplicaria pessoas.")
    if metric in {"revenue", "orders", "average_ticket"}:
        connections = await own_rows("integration_connections", client_id, select="client_id,provider,status,disconnected_at,metadata")
        connection = select_commerce_connection(connections)
        if connection is None:
            return unavailable("Não há origem ativa de Ecommerce para reporting.")
        if connection["provider"] == "fbits":
            ids = {str(v) for v in (connection.get("metadata") or {}).get("revenue_status_ids", [])}
            if not ids:
                return unavailable("As situações de receita FBITS não estão configuradas.")
            rows = await own_rows("fbits_orders", client_id, select="client_id,order_date,status_id,is_valid,total_value", filters={"order_date": f"gte.{start}T00:00:00-03:00", "and": f"(order_date.lt.{(date.fromisoformat(observed_end)+timedelta(days=1)).isoformat()}T00:00:00-03:00)"})
            rows = [r for r in rows if r.get("order_date") and start <= datetime.fromisoformat(r["order_date"].replace("Z", "+00:00")).astimezone(ZoneInfo("America/Sao_Paulo")).date().isoformat() <= observed_end]
            if not rows:
                return unavailable("Não há pedidos persistidos no período.")
            totals = _valid_metrics(rows, ids)
            if metric == "average_ticket" and not totals["pedidos"]:
                return unavailable("Não há pedidos reconhecidos para calcular ticket.")
            metadata = connection.get("metadata") or {}
            covered = False
            if metadata.get("history_completed_at") and metadata.get("history_start") and metadata.get("incremental_marker"):
                tz = ZoneInfo("America/Sao_Paulo")
                history_start = datetime.fromisoformat(metadata["history_start"].replace("Z", "+00:00"))
                query_end = datetime.fromisoformat(metadata["incremental_marker"].replace("Z", "+00:00"))
                covered = history_start <= datetime.fromisoformat(start).replace(tzinfo=tz) and query_end.astimezone(tz).date().isoformat() >= observed_end
            return value(totals[{"revenue":"receita_oficial", "orders":"pedidos", "average_ticket":"ticket_medio"}[metric]], "FBITS · pedidos persistidos (regra de situações; não é o KPI oficial)", covered)
    daily = await own_rows("dashboard_daily_metrics", client_id, filters={"metric_date":f"gte.{start}", "and":f"(metric_date.lte.{observed_end})"}, order="metric_date.asc")
    daily = [r for r in daily if start <= str(r.get("metric_date") or "") <= observed_end]
    if metric in {"revenue", "orders", "average_ticket"}:
        rows = [r for r in daily if r.get("shopify_net_revenue") is not None and r.get("shopify_orders") is not None]
        if not rows:
            return unavailable("Não há métricas Shopify persistidas no período.")
        revenue = sum(float(r["shopify_net_revenue"]) for r in rows)
        orders = sum(float(r["shopify_orders"]) for r in rows)
        if metric == "average_ticket" and orders <= 0:
            return unavailable("Não há pedidos reconhecidos para calcular ticket.")
        return value(revenue if metric == "revenue" else orders if metric == "orders" else revenue / orders, "Shopify · dashboard_daily_metrics", len({r["metric_date"] for r in rows}) == (date.fromisoformat(observed_end)-date.fromisoformat(start)).days+1)
    if metric == "roas":
        sources = [("Meta Ads", "meta_spend", "meta_attributed_revenue"), ("Google Ads", "google_ads_spend", "google_ads_conversion_value")]
        available = [(name, spend, revenue) for name, spend, revenue in sources if any(r.get(spend) is not None for r in daily)]
        if len(available) != 1:
            return unavailable("ROAS requer uma única fonte; atribuições diferentes não são combinadas.")
        name, spend, revenue = available[0]
        rows = [r for r in daily if r.get(spend) is not None]
        if any(r.get(revenue) is None for r in rows):
            return unavailable("Receita atribuída não está disponível para toda a leitura.")
        total = sum(float(r[spend]) for r in rows)
        if total <= 0:
            return unavailable("Não há investimento positivo para calcular ROAS.")
        return value(sum(float(r[revenue]) for r in rows) / total, name + " · receita atribuída / investimento persistidos")
    fields = {"ad_spend":["meta_spend", "google_ads_spend"], "conversions":["meta_purchases"], "followers":["instagram_followers"], "impressions":["instagram_impressions"], "engagement":["instagram_interactions"], "reach":["instagram_reach"]}[metric]
    numbers = [float(r[f]) for r in daily for f in fields if r.get(f) is not None]
    if not numbers:
        return unavailable("Não há valores persistidos para este indicador no período.")
    expected_days = (date.fromisoformat(observed_end)-date.fromisoformat(start)).days+1
    present_fields = [field for field in fields if any(row.get(field) is not None for row in daily)]
    covered = all(len({row["metric_date"] for row in daily if row.get(field) is not None}) == expected_days for field in present_fields)
    return value(numbers[-1] if metric == "followers" else sum(numbers), "Instagram · snapshot persistido" if metric in {"followers","impressions","engagement","reach"} else "Meta Ads · compras atribuídas" if metric == "conversions" else " + ".join(name for name, field in [("Meta Ads", "meta_spend"), ("Google Ads", "google_ads_spend")] if any(r.get(field) is not None for r in daily)) + " · investimento persistido", covered)

def evaluate_goal(goal, actual, today=None):
    today = today or datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    start, end = date.fromisoformat(str(goal["period_start"])), date.fromisoformat(str(goal["period_end"]))
    duration = (end - start).days + 1
    days = min(duration, max(0, (today - start).days + 1))
    fraction = days / duration
    target = float(goal["target_value"])
    progress = float(actual["actual"]) / target * 100 if actual["available"] and target > 0 else None
    elapsed = fraction * 100
    delta = progress - elapsed if progress is not None else None
    status = "FUTURA" if days == 0 else "INDISPONIVEL" if progress is None else "META_ATINGIDA" if progress >= 100 else "NO_RITMO" if delta >= -PACE_TOLERANCE else "ATENCAO" if delta >= -ATTENTION_TOLERANCE else "ABAIXO_DO_RITMO"
    projected = float(actual["actual"]) / fraction if progress is not None and target > 0 and fraction >= MIN_PROJECTION_FRACTION and goal["metric"] in ADDITIVE and actual.get("projection_ready") is True else None
    # Estrutura já pronta para contexto futuro; não ligada à Intelligence.
    return {**goal, **actual, "progress_percent":progress, "elapsed_percent":elapsed, "pace_delta":delta, "projected_value":projected, "remaining":max(0, target-float(actual["actual"])) if progress is not None else None, "status":status}

async def list_goals(client_id, start=None, end=None):
    rows = await own_rows("client_goals", client_id, order="period_end.asc,created_at.asc,id.asc")
    rows = [r for r in rows if (not start or r["period_end"] >= start) and (not end or r["period_start"] <= end)]
    results, cache = [], {}
    for goal in rows:
        key=(goal["metric"],goal["period_start"],goal["period_end"])
        if key not in cache:
            try: cache[key]=await resolve_goal_actual(client_id,*key)
            except Exception: cache[key]=unavailable("A fonte persistida não pôde ser lida agora.")
        results.append(evaluate_goal(goal,cache[key]))
    return {"ok":True, "client_id":client_id, "goals":results}
