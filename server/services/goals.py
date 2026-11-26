"""Metas: somente leituras persistidas, sem sync, credenciais ou IA."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from math import isfinite
from .ig_supabase import sb_select
from .fbits_reporting import _valid_metrics
from .commerce_context import select_commerce_connection
from .request_performance import measured

METRICS = {"revenue", "orders", "average_ticket", "ad_spend", "roas", "conversions", "followers", "reach", "impressions", "engagement",
           "cpa_meta", "google_conversions", "sessions", "conversion_rate", "followers_gained"}
# Somam dia a dia (ritmo, projeção e "necessário por dia" fazem sentido). Razões e níveis (ROAS, ticket, CPA, taxa,
# seguidores totais) não: são comparados ao alvo pelo valor do período.
ADDITIVE = {"revenue", "orders", "ad_spend", "conversions", "impressions", "engagement", "google_conversions", "sessions", "followers_gained"}
# Meta máxima ("não passar de"): teto. As demais nascem como mínima; a pessoa pode mudar.
DEFAULT_DIRECTION = {"ad_spend": "max", "cpa_meta": "max"}
MIN_OBSERVED_DAYS = 3
PACE_TOLERANCE = 5
ATTENTION_TOLERANCE = 15
MIN_PROJECTION_FRACTION = 0.05
MAX_ROWS = 20000

def unavailable(reason):
    return {"available": False, "actual": None, "origin": None, "reason": reason}

def value(actual, origin, projection_ready=False, covered_days=None):
    if actual is None or not isfinite(float(actual)):
        return unavailable("Não há valor válido persistido para este indicador.")
    return {"available": True, "actual": float(actual), "origin": origin, "reason": None, "projection_ready": projection_ready,
            "covered_days": covered_days}

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
        days_with_data = len({r["metric_date"] for r in rows})
        return value(revenue if metric == "revenue" else orders if metric == "orders" else revenue / orders, "Shopify · dashboard_daily_metrics",
                     days_with_data == (date.fromisoformat(observed_end)-date.fromisoformat(start)).days+1, days_with_data)
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
    if metric == "cpa_meta":
        rows = [r for r in daily if r.get("meta_spend") is not None and r.get("meta_purchases") is not None]
        purchases = sum(float(r["meta_purchases"]) for r in rows)
        if not rows or purchases <= 0:
            return unavailable("CPA da Meta precisa de compras atribuídas pela Meta no período.")
        return value(sum(float(r["meta_spend"]) for r in rows) / purchases, "Meta Ads · investimento / compras atribuídas (atribuição da Meta)",
                     covered_days=len({r["metric_date"] for r in rows}))
    if metric == "conversion_rate":
        # Numerador e denominador da MESMA fonte e do mesmo recorte (GA4): compras / sessões.
        rows = [r for r in daily if r.get("ga4_sessions") is not None and r.get("ga4_purchases") is not None]
        sessions = sum(float(r["ga4_sessions"]) for r in rows)
        if not rows or sessions <= 0:
            return unavailable("Taxa de conversão precisa de sessões e compras do GA4 no mesmo período (integração necessária).")
        return value(sum(float(r["ga4_purchases"]) for r in rows) / sessions * 100, "GA4 · compras / sessões (%)",
                     covered_days=len({r["metric_date"] for r in rows}))
    if metric == "followers_gained":
        # Diferença entre snapshots confiáveis: o do dia anterior ao início (ou do próprio início) e o mais recente.
        before = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
        snaps = await own_rows("dashboard_daily_metrics", client_id, filters={"metric_date": f"gte.{before}", "and": f"(metric_date.lte.{observed_end})"},
                               order="metric_date.asc", select="client_id,metric_date,instagram_followers")
        snaps = [r for r in snaps if r.get("instagram_followers") is not None and before <= str(r.get("metric_date")) <= observed_end]
        if not snaps or str(snaps[0]["metric_date"]) > start:
            return unavailable("Sem snapshot de seguidores no início do período: não dá para calcular quantos foram ganhos.")
        if len(snaps) < 2:
            return unavailable("Só há um snapshot de seguidores no período.")
        return value(float(snaps[-1]["instagram_followers"]) - float(snaps[0]["instagram_followers"]),
                     f"Instagram · snapshot de {snaps[-1]['metric_date']} menos o de {snaps[0]['metric_date']} (não é o total de seguidores)",
                     covered_days=len({r["metric_date"] for r in snaps if str(r["metric_date"]) >= start}))
    fields = {"ad_spend":["meta_spend", "google_ads_spend"], "google_conversions":["google_ads_conversions"], "sessions":["ga4_sessions"], "conversions":["meta_purchases"], "followers":["instagram_followers"], "impressions":["instagram_impressions"], "engagement":["instagram_interactions"], "reach":["instagram_reach"]}[metric]
    numbers = [float(r[f]) for r in daily for f in fields if r.get(f) is not None]
    if not numbers:
        return unavailable("Não há valores persistidos para este indicador no período.")
    expected_days = (date.fromisoformat(observed_end)-date.fromisoformat(start)).days+1
    present_fields = [field for field in fields if any(row.get(field) is not None for row in daily)]
    covered = all(len({row["metric_date"] for row in daily if row.get(field) is not None}) == expected_days for field in present_fields)
    days_with_data = len({row["metric_date"] for row in daily if any(row.get(f) is not None for f in fields)})
    origin = ("Instagram · snapshot persistido" if metric in {"followers","impressions","engagement","reach"} else "Meta Ads · compras atribuídas" if metric == "conversions"
              else "Google Ads · conversões (atribuição do Google)" if metric == "google_conversions" else "GA4 · sessões" if metric == "sessions"
              else " + ".join(name for name, field in [("Meta Ads", "meta_spend"), ("Google Ads", "google_ads_spend")] if any(r.get(field) is not None for r in daily)) + " · investimento persistido")
    return value(numbers[-1] if metric == "followers" else sum(numbers), origin, covered, days_with_data)

def evaluate_goal(goal, actual, today=None):
    """Progresso, status e ritmo respeitando a direção da meta (mínima: atingir; máxima: não passar)."""
    today = today or datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    start, end = date.fromisoformat(str(goal["period_start"])), date.fromisoformat(str(goal["period_end"]))
    duration = (end - start).days + 1
    days = min(duration, max(0, (today - start).days + 1))
    fraction = days / duration
    target = float(goal["target_value"])
    metric = goal["metric"]
    direction = goal.get("direction") or DEFAULT_DIRECTION.get(metric, "min")
    additive = metric in ADDITIVE
    available = bool(actual["available"]) and target > 0
    real = float(actual["actual"]) if available else None
    progress = real / target * 100 if available else None
    elapsed = fraction * 100
    delta = progress - elapsed if progress is not None else None
    projected = real / fraction if available and fraction >= MIN_PROJECTION_FRACTION and additive and actual.get("projection_ready") is True else None
    days_left = max(0, (end - max(today, start)).days + (0 if today > end else 1)) if days else duration
    covered = actual.get("covered_days")
    observed_daily = real / covered if available and additive and covered and covered >= MIN_OBSERVED_DAYS else None
    if days == 0:
        status = "FUTURA"
    elif not available:
        status = "INDISPONIVEL"
    elif direction == "max":
        # Teto: passar é o problema. Para o que soma (investimento), a projeção avisa antes de estourar.
        status = "ACIMA_DO_TETO" if real > target else "RISCO_DE_PASSAR" if projected is not None and projected > target else "DENTRO_DO_TETO"
    elif not additive:
        # Razão ou nível (ROAS, ticket, CPA, taxa, seguidores): compara o valor do período ao alvo, sem ritmo de calendário.
        status = "META_ATINGIDA" if real >= target else "ATENCAO" if real >= target * 0.9 else "ABAIXO_DA_META"
    else:
        status = "META_ATINGIDA" if progress >= 100 else "NO_RITMO" if delta >= -PACE_TOLERANCE else "ATENCAO" if delta >= -ATTENTION_TOLERANCE else "ABAIXO_DO_RITMO"
    remaining = max(0.0, target - real) if available else None
    # Mínima: quanto precisa por dia daqui até o fim. Máxima: quanto ainda pode por dia sem passar do teto.
    required_daily = remaining / days_left if available and additive and days_left > 0 and remaining and remaining > 0 else None
    pace_note = None
    if required_daily is not None and observed_daily is not None and direction == "min" and status != "META_ATINGIDA":
        gap = observed_daily - required_daily
        pace_note = ("O ritmo observado já cobre o necessário." if gap >= 0
                     else f"O ritmo observado está {abs(gap) / required_daily * 100:.0f}% abaixo do necessário por dia.")
    return {**goal, **actual, "direction": direction, "additive": additive, "progress_percent": progress, "elapsed_percent": elapsed, "pace_delta": delta,
            "projected_value": projected, "remaining": remaining, "status": status, "days_total": duration, "days_left": days_left,
            "required_daily": required_daily, "observed_daily": observed_daily, "pace_model": "linear" if additive else None, "pace_note": pace_note}

@measured("data_goals")
async def list_goals(client_id, start=None, end=None, *, include_actuals=True):
    rows = await own_rows("client_goals", client_id, order="period_end.asc,created_at.asc,id.asc")
    rows = [r for r in rows if (not start or r["period_end"] >= start) and (not end or r["period_start"] <= end)]
    if not include_actuals:
        return {"ok": True, "client_id": client_id, "goals": [evaluate_goal(row, unavailable("Progresso em carregamento.")) for row in rows]}
    results, cache = [], {}
    for goal in rows:
        key=(goal["metric"],goal["period_start"],goal["period_end"])
        if key not in cache:
            try: cache[key]=await resolve_goal_actual(client_id,*key)
            except Exception: cache[key]=unavailable("A fonte persistida não pôde ser lida agora.")
        evaluated = evaluate_goal(goal,cache[key])
        # Ritmo sazonal (dias da semana) só quando o histórico da própria marca sustenta; senão, linear.
        if evaluated.get("additive") and evaluated.get("status") not in ("FUTURA", "INDISPONIVEL"):
            ckey=("curve",goal["metric"],goal["period_start"])
            if ckey not in cache:
                try: cache[ckey]=await seasonal_curve(client_id,goal["metric"],goal["period_start"])
                except Exception: cache[ckey]=None
            evaluated = apply_curve(evaluated, cache[ckey])
        results.append(evaluated)
    from .goal_ops import alerts
    return {"ok":True, "client_id":client_id, "goals":results, "alerts":alerts(results)}


# ---------------------------------------------------------------- desdobramento (indicadores relacionados)

# Relações explicáveis e com a MESMA fonte de dados. Exemplos, não regras universais: só aparecem quando os dados existem.
DRIVERS = {
    "revenue": [("orders", "Pedidos"), ("average_ticket", "Ticket médio")],          # Faturamento = Pedidos × Ticket médio
    "orders": [("sessions", "Sessões (GA4)"), ("conversion_rate", "Taxa de conversão (GA4)")],  # Pedidos ≈ Sessões × Conversão
    "conversions": [("ad_spend", "Investimento em anúncios"), ("cpa_meta", "CPA (Meta Ads)")],  # Compras = Investimento ÷ CPA
}
RELATION = {"revenue": "Faturamento = Pedidos × Ticket médio", "orders": "Pedidos ≈ Sessões × Taxa de conversão",
            "conversions": "Compras ≈ Investimento ÷ CPA"}


def driver_targets(metric, target, actuals):
    """Quanto cada indicador relacionado precisaria ser, mantendo o outro no valor observado. Puro, para teste."""
    out = {}
    a = {k: (v["actual"] if v.get("available") else None) for k, v in actuals.items()}
    if metric == "revenue":
        if a.get("average_ticket"):
            out["orders"] = target / a["average_ticket"]
        if a.get("orders"):
            out["average_ticket"] = target / a["orders"]
    elif metric == "orders":
        if a.get("conversion_rate"):
            out["sessions"] = target / (a["conversion_rate"] / 100)
        if a.get("sessions"):
            out["conversion_rate"] = target / a["sessions"] * 100
    elif metric == "conversions":
        if a.get("cpa_meta"):
            out["ad_spend"] = target * a["cpa_meta"]
        if a.get("ad_spend"):
            out["cpa_meta"] = a["ad_spend"] / target
    return out


async def goal_drivers(client_id, goal):
    """Indicadores relacionados à meta, com o valor observado no mesmo período e o necessário para bater o alvo."""
    pairs = DRIVERS.get(goal["metric"], [])
    if not pairs:
        return {"relation": None, "drivers": [], "note": "Este indicador não tem um desdobramento direto com os dados disponíveis."}
    actuals = {}
    for key, _ in pairs:
        try:
            actuals[key] = await resolve_goal_actual(client_id, key, goal["period_start"], goal["period_end"])
        except Exception:  # noqa: BLE001
            actuals[key] = unavailable("A fonte persistida não pôde ser lida agora.")
    needed = driver_targets(goal["metric"], float(goal["target_value"]), actuals)
    drivers = [{"metric": key, "label": label, "available": actuals[key]["available"], "actual": actuals[key].get("actual"),
                "origin": actuals[key].get("origin"), "reason": actuals[key].get("reason"), "needed": needed.get(key),
                "direction": DEFAULT_DIRECTION.get(key, "min")} for key, label in pairs]
    note = ("Cada valor necessário mantém o outro indicador como está hoje; é uma referência, não uma previsão."
            + (" Sessões e conversão vêm do GA4 e podem não bater exatamente com os pedidos da loja." if goal["metric"] == "orders" else ""))
    return {"relation": RELATION.get(goal["metric"]), "drivers": drivers, "note": note}


# ---------------------------------------------------------------- sugestão de meta (cenários com premissas)

COMMERCIAL_DATES = [("11-20", "11-30", "Black Friday"), ("12-01", "12-25", "Natal"), ("05-01", "05-12", "Dia das Mães")]
MIN_COVERAGE = 0.8


def scenarios(metric, direction, windows):
    """Cenários a partir de períodos anteriores de mesmo tamanho. Puro, para teste.

    ``windows``: [{start, end, value, coverage}] do mais antigo ao mais recente. Só períodos com cobertura ≥ 80% contam."""
    valid = [w for w in windows if w.get("value") is not None and w.get("coverage", 0) >= MIN_COVERAGE]
    if len(valid) < 2:
        return None
    values = [float(w["value"]) for w in valid]
    avg = sum(values) / len(values)
    lo, hi = min(values), max(values)
    trend = (values[-1] - values[0]) / values[0] * 100 if values[0] else None
    spread = (hi - lo) / avg * 100 if avg else None
    if direction == "max":  # teto: conservador é o teto mais folgado
        picks = {"conservador": hi * 1.05, "referencia": avg, "agressivo": lo}
    else:
        picks = {"conservador": lo, "referencia": avg if trend is None or trend <= 0 else avg * (1 + min(trend, 30) / 200), "agressivo": hi * 1.1}
    uncertainty = "alta" if len(valid) < 3 or (spread or 0) > 40 else "média" if (spread or 0) > 15 else "baixa"
    return {"values": picks, "average": avg, "trend_percent": trend, "spread_percent": spread, "uncertainty": uncertainty, "used": valid}


async def suggest_goal(client_id, metric, period_start, period_end):
    """Cenários conservador, de referência e agressivo com as premissas. Sem histórico suficiente, diz isso (meta manual)."""
    if metric not in METRICS:
        return {"available": False, "reason": "Indicador não suportado."}
    start, end = date.fromisoformat(str(period_start)), date.fromisoformat(str(period_end))
    length = (end - start).days + 1
    windows = []
    for back in (3, 2, 1):
        w_end = start - timedelta(days=1 + (back - 1) * length)
        w_start = w_end - timedelta(days=length - 1)
        try:
            r = await resolve_goal_actual(client_id, metric, w_start.isoformat(), w_end.isoformat())
        except Exception:  # noqa: BLE001
            r = unavailable("leitura indisponível")
        coverage = (r.get("covered_days") or (length if r.get("projection_ready") else 0)) / length if r.get("available") else 0
        windows.append({"start": w_start.isoformat(), "end": w_end.isoformat(), "value": r.get("actual"), "coverage": round(coverage, 2),
                        "origin": r.get("origin"), "reason": r.get("reason")})
    direction = DEFAULT_DIRECTION.get(metric, "min")
    result = scenarios(metric, direction, windows)
    dates = [label for a, b, label in COMMERCIAL_DATES
             if any(f"{y}-{a}" <= end.isoformat() and f"{y}-{b}" >= start.isoformat() for y in {start.year, end.year})]
    try:
        record = await past_goal_record(client_id, metric, start.isoformat())
    except Exception:  # noqa: BLE001
        record = None
    premises = {"history": windows, "model": "Períodos anteriores do mesmo tamanho; ritmo linear, sem ajuste de sazonalidade.",
                "past_goals": record,
                "commercial_dates": dates,
                "seasonality_note": (f"O período inclui {', '.join(dates)}. O histórico usado não tem essas datas e não foi ajustado: trate os cenários com cuidado."
                                     if dates else None)}
    if not result:
        return {"available": False, "reason": "Não há histórico suficiente (pelo menos 2 períodos anteriores com 80% dos dias cobertos). Defina a meta manualmente.",
                "premises": premises}
    return {"available": True, "metric": metric, "direction": direction, "scenarios": [
        {"key": k, "label": {"conservador": "Conservador", "referencia": "Referência", "agressivo": "Agressivo"}[k], "value": round(v, 2)}
        for k, v in result["values"].items()],
        "average": result["average"], "trend_percent": result["trend_percent"], "spread_percent": result["spread_percent"],
        "uncertainty": result["uncertainty"], "premises": premises}


# ---------------------------------------------------------------- histórico de alterações

async def record_history(client_id, goal_id, action, before, after, actor):
    from .ig_supabase import sb_insert
    try:
        await sb_insert("client_goal_history", {"client_id": client_id, "goal_id": str(goal_id), "action": action,
                                                "before": before, "after": after, "actor": actor}, returning="minimal")
    except Exception as exc:  # noqa: BLE001 — antes da migração 000150: a meta segue, o histórico não
        print(f"[goals] history_failed client_id={client_id} action={action} error_type={type(exc).__name__}")


async def goal_history(client_id, goal_id):
    try:
        rows = await sb_select("client_goal_history", select="action,before,after,actor,created_at,client_id",
                               filters={"client_id": f"eq.{client_id}", "goal_id": f"eq.{goal_id}"}, order="created_at.desc", limit=50)
    except Exception:  # noqa: BLE001
        return {"available": False, "events": []}
    return {"available": True, "events": [r for r in rows if r.get("client_id") == client_id]}


# ---------------------------------------------------------------- ritmo sazonal (dias da semana) e avaliação

SEASONAL_FIELDS = {"orders": ["shopify_orders"], "revenue": ["shopify_net_revenue"], "ad_spend": ["meta_spend", "google_ads_spend"],
                   "sessions": ["ga4_sessions"], "conversions": ["meta_purchases"], "google_conversions": ["google_ads_conversions"],
                   "impressions": ["instagram_impressions"], "engagement": ["instagram_interactions"]}
CURVE_WEEKS = 8
MIN_PER_WEEKDAY = 4      # cada dia da semana precisa de pelo menos 4 dias com dado
MIN_SPREAD = 1.15        # curva só vale se o dia mais forte for 15% maior que o mais fraco; abaixo disso, linear


def weekday_curve(rows, fields):
    """Peso médio de cada dia da semana (seg=0..dom=6), média 1. None sem dado suficiente ou sem diferença relevante. Puro."""
    by_day = {d: [] for d in range(7)}
    for r in rows:
        vals = [r.get(f) for f in fields]
        if all(v is None for v in vals):
            continue
        by_day[date.fromisoformat(str(r["metric_date"])).weekday()].append(sum(float(v or 0) for v in vals))
    if any(len(v) < MIN_PER_WEEKDAY for v in by_day.values()):
        return None
    avgs = [sum(v) / len(v) for _, v in sorted(by_day.items())]
    mean = sum(avgs) / 7
    if mean <= 0 or min(avgs) <= 0 or max(avgs) / min(avgs) < MIN_SPREAD:
        return None
    return [a / mean for a in avgs]


async def seasonal_curve(client_id, metric, period_start):
    """Curva dos dias da semana a partir das 8 semanas antes do período (dados da própria marca)."""
    fields = SEASONAL_FIELDS.get(metric)
    if not fields:
        return None
    start = date.fromisoformat(str(period_start))
    since = (start - timedelta(weeks=CURVE_WEEKS)).isoformat()
    rows = await own_rows("dashboard_daily_metrics", client_id, filters={"metric_date": f"gte.{since}", "and": f"(metric_date.lt.{start.isoformat()})"},
                          select="client_id,metric_date," + ",".join(fields))
    return weekday_curve(rows, fields)


def apply_curve(result, curve, today=None):
    """Troca o ritmo linear pelo sazonal quando há curva: % esperado até hoje, necessário HOJE e projeção. Puro."""
    if not curve or not result.get("additive") or result.get("status") in ("FUTURA", "INDISPONIVEL"):
        return result
    today = today or datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    start, end = date.fromisoformat(str(result["period_start"])), date.fromisoformat(str(result["period_end"]))
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    w = {d: curve[d.weekday()] for d in days}
    total = sum(w.values())
    elapsed_w = sum(v for d, v in w.items() if d <= today)
    remaining_w = sum(v for d, v in w.items() if d >= today)
    out = dict(result)
    out["elapsed_percent"] = elapsed_w / total * 100
    out["pace_model"] = "sazonal"
    out["curve"] = [round(c, 3) for c in curve]
    if result.get("progress_percent") is not None and result.get("direction") != "max":
        delta = result["progress_percent"] - out["elapsed_percent"]
        out["pace_delta"] = delta
        if result["status"] not in ("META_ATINGIDA",):
            out["status"] = "NO_RITMO" if delta >= -PACE_TOLERANCE else "ATENCAO" if delta >= -ATTENTION_TOLERANCE else "ABAIXO_DO_RITMO"
    if result.get("remaining") and today <= end and remaining_w > 0:
        out["required_today"] = result["remaining"] * w.get(today, 0) / remaining_w if today >= start else None
    if result.get("projected_value") is not None and elapsed_w > 0:
        out["projected_value"] = float(result["actual"]) / (elapsed_w / total)
    return out


async def goal_evaluation(client_id, goal, evaluated):
    """Leitura de uma meta para aprender depois: alvo original x alterações, resultado, desvio, premissas e ações."""
    hist = await goal_history(client_id, str(goal["id"]))
    events = list(reversed(hist.get("events") or []))
    created = next((e for e in events if e.get("action") == "criada"), None)
    original = (created or {}).get("after", {}) or {}
    edits = [e for e in events if e.get("action") == "editada" and (e.get("before") or {}).get("target_value") != (e.get("after") or {}).get("target_value")]
    target = float(goal["target_value"])
    actual = evaluated.get("actual")
    deviation = (float(actual) - target) / target * 100 if actual is not None and target else None
    tasks = []
    try:
        recs = await sb_select("goal_recommendations", select="items,client_id,created_at", filters={"client_id": f"eq.{client_id}", "goal_id": f"eq.{goal['id']}"}, limit=20)
        tasks = [i.get("task_id") for r in recs if r.get("client_id") == client_id for i in (r.get("items") or []) if i.get("task_id")]
    except Exception:  # noqa: BLE001
        pass
    ended = date.fromisoformat(str(goal["period_end"])) < datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    return {"ended": ended, "original_target": original.get("target_value"), "current_target": target, "target_changes": len(edits),
            "actual": actual, "deviation_percent": deviation, "result": evaluated.get("status"), "direction": evaluated.get("direction"),
            "suggestion": goal.get("suggestion"), "tasks_created": len(tasks), "history_available": hist.get("available", False)}


async def past_goal_record(client_id, metric, before):
    """Metas encerradas do mesmo indicador: quantas foram atingidas e o desvio médio (premissa da sugestão; não muda nada sozinho)."""
    rows = await own_rows("client_goals", client_id, order="period_end.desc")
    past = [r for r in rows if r.get("metric") == metric and str(r.get("period_end")) < str(before)][:6]
    out = []
    for g in past:
        try:
            a = await resolve_goal_actual(client_id, metric, g["period_start"], g["period_end"])
        except Exception:  # noqa: BLE001
            continue
        if a.get("available") and float(g["target_value"]) > 0:
            out.append((float(a["actual"]) - float(g["target_value"])) / float(g["target_value"]) * 100)
    if not out:
        return None
    hit = sum(1 for d in out if d >= 0) if DEFAULT_DIRECTION.get(metric, "min") == "min" else sum(1 for d in out if d <= 0)
    return {"goals": len(out), "hit": hit, "average_deviation_percent": sum(out) / len(out)}
