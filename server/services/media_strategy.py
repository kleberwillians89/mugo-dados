"""Mídia On — motor de estratégia de mídia paga a partir dos dados reais da empresa.

O que é calculado (determinístico, auditável):

1. Diagnóstico por canal (Meta Ads e Google Ads): KPIs dos últimos 30 dias vs os
   30 anteriores e achados objetivos (fadiga criativa, saturação, verba sem
   conversão, queda de eficiência).
2. Curva de retorno de cada canal ajustada nos dados semanais dos últimos 90
   dias: y = a · gasto^b, com y = receita, conversões, cliques ou impressões
   conforme o objetivo. b < 1 é o retorno decrescente MEDIDO na conta; com
   poucos pontos ou pouca variação de verba, b vem de uma referência
   conservadora e a curva é marcada como "estimada".
3. Divisão ótima da verba entre canais (maior resultado total pela curva), com
   limites de estabilidade: canal ativo mantém um mínimo para seguir
   aprendendo, canal com poucos dados tem teto, e nenhum canal salta além de
   2,5x o que já investe por mês.
4. Cenários de verba: ritmo atual, meta do mês (quando existe meta de
   faturamento) e limite de eficiência (onde o próximo real investido deixa
   de pagar o retorno mínimo).
5. Ação por campanha (escalar, manter, otimizar, pausar, aprender) com o motivo.
6. Calendário semanal com peso maior antes das datas comerciais do mês.
7. Limites de KPI (CPA máximo, ROAS mínimo, verba diária) para a operação.

A IA só escreve a leitura estratégica em cima desses números e só pode citar
campanhas que estão na lista calculada.
"""
from __future__ import annotations

import calendar
import json
import math
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from .studio_calendar import StudioError, parse_month

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
CHANNELS = {"meta": "Meta Ads", "google_ads": "Google Ads"}
OBJECTIVES = {"vendas": "Vendas", "leads": "Leads/cadastros", "trafego": "Tráfego para o site", "alcance": "Alcance e marca"}
OBJECTIVE_METRIC = {"vendas": "revenue", "leads": "conversions", "trafego": "clicks", "alcance": "impressions"}
METRIC_LABEL = {"revenue": "receita atribuída", "conversions": "conversões", "clicks": "cliques", "impressions": "impressões"}
# Elasticidade de referência quando a conta não tem variação de verba suficiente para medir.
DEFAULT_B = {"revenue": 0.7, "conversions": 0.7, "clicks": 0.85, "impressions": 0.9}
B_RANGE = (0.35, 1.0)
WINDOW_DAYS = 90
MIN_WEEKS_TO_FIT = 6
MIN_ACTIVE_SHARE = 0.05
LOW_CONFIDENCE_CAP = 0.40
MAX_GROWTH = 2.5
MAX_GROWTH_ESTIMATED = 1.5  # curva sem medição: não extrapola tanto além do que o canal já investe
STEPS = 200
MIN_MARGINAL_ROAS = 1.0
CAMPAIGN_MIN_SPEND = 50.0
# Verba diária mínima por canal e por impulsionamento. A Meta aceita a partir de ~R$ 6/dia,
# mas abaixo de R$ 10 a entrega é instável e o aprendizado não sai do lugar.
MIN_DAILY = 10.0
MIN_BOOST_DAYS = 3
DISTRIBUTIONS = ("equilibrado", "hiperfoco")
TEST_SHARE = 0.20       # equilibrado: todo canal recebe ao menos 20% (canal sem histórico entra como teste)
REFERENCE_CAP = 0.40    # canal estimado por referência não passa de 40% quando outro canal tem dados
MIN_ATTRIBUTED_ROAS = 0.2  # abaixo disso a receita atribuída é irrisória: otimiza por conversões
# Referências de mercado (Brasil, e-commerce) só para canal SEM histórico. Conversão e ticket vêm da loja quando existem.
REFERENCE = {
    "meta": {"cpm": 18.0, "ctr": 0.012, "cvr": 0.012, "store_cvr_factor": 0.8},
    "google_ads": {"cpm": 30.0, "ctr": 0.035, "cvr": 0.025, "store_cvr_factor": 1.2},
}
SUGGESTED_CAMPAIGNS = {
    "meta": {
        "vendas": [("Advantage+ Shopping / catálogo (teste)", 0.6, "conversão com catálogo para aprender quem compra"),
                   ("Remarketing de visitantes do site (teste)", 0.4, "fecha a venda de quem já visitou a loja")],
        "leads": [("Cadastro com formulário instantâneo (teste)", 0.7, "captura de lead sem sair do Instagram"),
                  ("Remarketing de engajados (teste)", 0.3, "reimpacta quem interagiu com o perfil")],
        "trafego": [("Tráfego para o site com Reels (teste)", 1.0, "leva visitas qualificadas para a loja")],
        "alcance": [("Alcance com Reels do calendário (teste)", 1.0, "amplia o alcance das pautas aprovadas")],
    },
    "google_ads": {
        "vendas": [("Search de marca e produtos (teste)", 0.6, "captura quem já procura a marca ou o produto"),
                   ("Performance Max (teste)", 0.4, "distribui em Shopping, YouTube e Display com o catálogo")],
        "leads": [("Search com palavras de intenção (teste)", 1.0, "captura quem busca o serviço")],
        "trafego": [("Search + Demand Gen (teste)", 1.0, "visitas de quem tem intenção de compra")],
        "alcance": [("YouTube / Demand Gen (teste)", 1.0, "alcance em vídeo com custo baixo por mil")],
    },
}
ACTION_WEIGHT = {"escalar": 1.3, "manter": 1.0, "otimizar": 0.7, "aprender": 0.6, "testar": 1.0, "pausar": 0.0}


def _f(value: Any) -> float:
    try:
        out = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return out if math.isfinite(out) else 0.0


def _ratio(a: float, b: float) -> Optional[float]:
    return round(a / b, 4) if b else None


def _change(now: Optional[float], before: Optional[float]) -> Optional[float]:
    if now is None or before in (None, 0):
        return None
    return round((now - before) / abs(before) * 100, 1)


# --------------------------------------------------------------------------
# Leitura (Meta Ads e Google Ads persistidos)
# --------------------------------------------------------------------------

async def _meta_rows(client_id: str, start: str, end: str) -> Dict[str, Any]:
    from .dashboard_paid import get_paid_dashboard, list_campaigns
    dash = await get_paid_dashboard(client_id, start=start, end=end)
    camps = await list_campaigns(client_id, start=start, end=end, limit=200)
    daily = [{"date": str(d.get("date")), "spend": _f(d.get("spend")), "impressions": _f(d.get("impressions")),
              "clicks": _f(d.get("clicks")), "conversions": _f(d.get("conversions")), "revenue": _f(d.get("revenue"))}
             for d in dash.get("daily") or [] if not d.get("missing")]
    return {"daily": daily, "campaigns": camps.get("campaigns") or []}


async def _google_rows(client_id: str, start: str, end: str) -> Dict[str, Any]:
    from .dashboard_paid import _sum_grouped_rows
    from .google_ads import build_google_ads_report, resolve_google_ads_context
    from .ig_supabase import sb_select
    context = await resolve_google_ads_context(client_id)
    report = await build_google_ads_report(client_id=client_id, context=context, start=start, end=end)
    daily = [{"date": d["date"], "spend": _f(d.get("spend")), "impressions": _f(d.get("impressions")), "clicks": _f(d.get("clicks")),
              "conversions": _f(d.get("conversions")), "revenue": _f(d.get("conversion_value"))} for d in report.get("daily") or []]
    rows = await sb_select("google_ads_daily_stats", select="campaign_id,campaign_name,stat_date,cost,impressions,clicks,conversions,conversion_value",
                           filters={"client_id": f"eq.{client_id}", "connection_id": f"eq.{context.connection_id}",
                                    "customer_id": f"eq.{context.customer_id}", "and": f"(stat_date.gte.{start},stat_date.lte.{end})"},
                           order="stat_date.asc", limit=20000)
    campaigns = _sum_grouped_rows([{**r, "spend": r.get("cost"), "revenue": r.get("conversion_value")} for r in rows],
                                  "campaign_id", "campaign_name")
    return {"daily": daily, "campaigns": campaigns, "rows": rows}


READERS = {"meta": _meta_rows, "google_ads": _google_rows}


async def read_window(client_id: str, end: date) -> Dict[str, Dict[str, Any]]:
    start = end - timedelta(days=WINDOW_DAYS - 1)
    out: Dict[str, Dict[str, Any]] = {}
    for channel, reader in READERS.items():
        try:
            out[channel] = await reader(client_id, start.isoformat(), end.isoformat())
        except Exception as exc:  # canal desconectado: fica fora, a estratégia segue com os outros
            print(f"[media][strategy] canal={channel} erro={exc.__class__.__name__}")
            out[channel] = {"daily": [], "campaigns": [], "disconnected": True}
    return out


# --------------------------------------------------------------------------
# Diagnóstico
# --------------------------------------------------------------------------

def totals(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    t = {k: round(sum(_f(r.get(k)) for r in rows), 2) for k in ("spend", "impressions", "clicks", "conversions", "revenue")}
    t.update(cpm=_ratio(t["spend"] * 1000, t["impressions"]), cpc=_ratio(t["spend"], t["clicks"]), ctr=_ratio(t["clicks"], t["impressions"]),
             cpa=_ratio(t["spend"], t["conversions"]), roas=_ratio(t["revenue"], t["spend"]), conversion_rate=_ratio(t["conversions"], t["clicks"]))
    return t


def diagnose(channel: str, daily: List[Dict[str, Any]], end: date) -> Dict[str, Any]:
    cut = (end - timedelta(days=29)).isoformat()
    prev_cut = (end - timedelta(days=59)).isoformat()
    recent = totals([d for d in daily if d["date"] >= cut])
    previous = totals([d for d in daily if prev_cut <= d["date"] < cut])
    window = totals(daily)
    days_with_spend = sum(1 for d in daily if d["spend"] > 0)
    confidence = ("sem_dados" if window["spend"] <= 0 else
                  "baixa" if window["impressions"] < 5000 or days_with_spend < 21 or window["conversions"] < 10 else "boa")
    changes = {k: _change(recent.get(k), previous.get(k)) for k in ("spend", "revenue", "roas", "cpa", "cpm", "ctr", "conversions")}
    findings: List[Dict[str, str]] = []
    name = CHANNELS[channel]
    if (changes["cpm"] or 0) >= 20 and (changes["ctr"] or 0) <= -10:
        findings.append({"level": "alerta", "text": f"{name}: CPM subiu {changes['cpm']}% e CTR caiu {abs(changes['ctr'])}%. Sinal de fadiga de criativo ou público saturado."})
    if (changes["spend"] or 0) >= 25 and (changes["roas"] or 0) <= -15:
        findings.append({"level": "alerta", "text": f"{name}: a verba cresceu {changes['spend']}% e o ROAS caiu {abs(changes['roas'])}%. O canal está perto do limite de escala."})
    if (changes["roas"] or 0) >= 15 and (changes["spend"] or 0) >= -10:
        findings.append({"level": "oportunidade", "text": f"{name}: ROAS subiu {changes['roas']}% nos últimos 30 dias sem cortar verba. Espaço para escalar."})
    if (changes["cpa"] or 0) >= 25:
        findings.append({"level": "alerta", "text": f"{name}: custo por conversão subiu {changes['cpa']}% em 30 dias."})
    return {"channel": channel, "label": name, "recent": recent, "previous": previous, "window": window,
            "changes": changes, "confidence": confidence, "days_with_spend": days_with_spend,
            "monthly_spend": round(recent["spend"], 2), "findings": findings}


# --------------------------------------------------------------------------
# Curva de retorno
# --------------------------------------------------------------------------

def weekly(daily: List[Dict[str, Any]], end: date) -> List[Dict[str, float]]:
    weeks: Dict[int, Dict[str, float]] = {}
    for d in daily:
        idx = (end - date.fromisoformat(d["date"])).days // 7
        if idx >= WINDOW_DAYS // 7:
            continue
        w = weeks.setdefault(idx, {"spend": 0.0, "revenue": 0.0, "conversions": 0.0, "clicks": 0.0, "impressions": 0.0})
        for k in w:
            w[k] += _f(d.get(k))
    return [weeks[i] for i in sorted(weeks, reverse=True)]


def fit_curve(points: List[Tuple[float, float]], metric: str) -> Dict[str, Any]:
    """y = a·x^b nos pontos semanais; mede b quando a verba variou o bastante."""
    usable = [(x, y) for x, y in points if x > 0 and y > 0]
    if not usable:
        return {"a": 0.0, "b": DEFAULT_B[metric], "fit": "sem_dados", "r2": None, "points": 0}
    lx = [math.log(x) for x, _ in usable]
    ly = [math.log(y) for _, y in usable]
    n = len(usable)
    mx, my = sum(lx) / n, sum(ly) / n
    sxx = sum((v - mx) ** 2 for v in lx)
    b, fit, r2 = DEFAULT_B[metric], "estimada", None
    if n >= MIN_WEEKS_TO_FIT and sxx / n >= 0.02:  # verba variou pelo menos ~15% entre semanas
        slope = sum((lx[i] - mx) * (ly[i] - my) for i in range(n)) / sxx
        pred = [my + slope * (v - mx) for v in lx]
        ss_res = sum((ly[i] - pred[i]) ** 2 for i in range(n))
        ss_tot = sum((v - my) ** 2 for v in ly) or 1e-9
        r2 = round(1 - ss_res / ss_tot, 3)
        if r2 >= 0.3:
            b, fit = slope, "medida"
    b = max(B_RANGE[0], min(B_RANGE[1], b))
    # Calibra "a" para a curva passar pelo resultado médio real da conta.
    mean_x = sum(x for x, _ in usable) / n
    mean_y = sum(y for _, y in usable) / n
    a = mean_y / (mean_x ** b)
    return {"a": a, "b": round(b, 3), "fit": fit, "r2": r2, "points": n}


def project(curve: Dict[str, Any], monthly_spend: float, days: int) -> float:
    if monthly_spend <= 0 or not curve.get("a"):
        return 0.0
    weeks = days / 7
    return curve["a"] * (monthly_spend / weeks) ** curve["b"] * weeks


def reference_curves(channel: str, store: Dict[str, Any], test_spend: float, days: int) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """Curva para canal sem histórico: conversão e ticket da loja + CPM/CTR de referência de mercado."""
    ref = REFERENCE[channel]
    orders, sessions, revenue = _f(store.get("orders")), _f(store.get("sessions")), _f(store.get("revenue"))
    ticket = round(revenue / orders, 2) if orders > 0 and revenue > 0 else None
    store_cvr = orders / sessions if sessions > 0 and orders > 0 else None
    cvr = round(min(0.08, store_cvr * ref["store_cvr_factor"]), 4) if store_cvr else ref["cvr"]
    weekly_spend = max(test_spend, MIN_DAILY * days) * 7 / days
    impressions = weekly_spend / ref["cpm"] * 1000
    clicks = impressions * ref["ctr"]
    conversions = clicks * cvr
    point = {"impressions": impressions, "clicks": clicks, "conversions": conversions,
             "revenue": conversions * ticket if ticket else 0.0}
    curves = {}
    for metric, b in DEFAULT_B.items():
        y = point[metric]
        curves[metric] = {"a": y / (weekly_spend ** b) if y > 0 else 0.0, "b": b, "fit": "referencia", "r2": None, "points": 0}
    inputs = {"cpm": ref["cpm"], "ctr": ref["ctr"], "cvr": cvr, "ticket": ticket,
              "cvr_source": "loja (sessões → pedidos)" if store_cvr else "referência de mercado",
              "ticket_source": "loja (faturamento ÷ pedidos)" if ticket else None}
    return curves, inputs


def curves_for(week_rows: List[Dict[str, float]]) -> Dict[str, Dict[str, Any]]:
    return {metric: fit_curve([(w["spend"], w[metric]) for w in week_rows], metric) for metric in DEFAULT_B}


# --------------------------------------------------------------------------
# Otimização e cenários
# --------------------------------------------------------------------------

def bounds(diag: Dict[str, Dict[str, Any]], budget: float, fits: Optional[Dict[str, str]] = None,
           days: int = 30, distribution: str = "equilibrado") -> Dict[str, Tuple[float, float]]:
    active = [c for c, d in diag.items() if d["confidence"] != "sem_dados"]
    if len(active) > 1 and budget < MIN_DAILY * days * len(active):
        # Verba não paga R$ 10/dia em todos os canais: fica só o de maior retorno recente (com dados, se houver).
        active = [max(active, key=lambda c: (diag[c]["confidence"] != "referencia", (diag[c].get("recent") or {}).get("roas") or 0))]
    has_data = any(diag[c]["confidence"] in ("boa", "baixa") for c in active)
    out = {}
    for c in active:
        d = diag[c]
        if len(active) == 1:
            out[c] = (budget, budget)
            continue
        floor_share = TEST_SHARE if distribution == "equilibrado" else MIN_ACTIVE_SHARE
        lo = max(budget * floor_share, MIN_DAILY * days) if distribution == "equilibrado" else 0.0
        hi = budget
        if d["confidence"] == "baixa":
            hi = min(hi, budget * LOW_CONFIDENCE_CAP)
        if d["confidence"] == "referencia" and has_data:
            hi = min(hi, budget * REFERENCE_CAP)
        if d.get("monthly_spend", 0) > 0:
            growth = MAX_GROWTH if (fits or {}).get(c, "medida") == "medida" else MAX_GROWTH_ESTIMATED
            hi = min(hi, max(d["monthly_spend"] * growth, lo))
        out[c] = (min(lo, hi), hi)
    total_hi = sum(h for _, h in out.values())
    if out and total_hi < budget:  # verba maior que o teto somado: abre os tetos dos canais COM dados
        measured = {c for c in out if diag[c]["confidence"] != "referencia"} or set(out)
        fixed = sum(h for c, (_, h) in out.items() if c not in measured)
        scale = (budget - fixed) / max(sum(out[c][1] for c in measured), 1e-9)
        out = {c: (lo, hi * scale if c in measured else hi) for c, (lo, hi) in out.items()}
    return out


def optimize(curves: Dict[str, Dict[str, Dict[str, Any]]], diag: Dict[str, Dict[str, Any]], budget: float,
             metric: str, days: int, distribution: str = "equilibrado") -> Dict[str, float]:
    limits = bounds(diag, budget, {c: curves[c][metric].get("fit", "medida") for c in curves}, days, distribution)
    if not limits or budget <= 0:
        return {}
    alloc = {c: lo for c, (lo, _) in limits.items()}
    step = budget / STEPS
    remaining = budget - sum(alloc.values())
    while remaining > 1e-6:
        inc = min(step, remaining)
        best, gain = None, -1.0
        for c, (_, hi) in limits.items():
            if alloc[c] + inc > hi + 1e-6:
                continue
            g = project(curves[c][metric], alloc[c] + inc, days) - project(curves[c][metric], alloc[c], days)
            if g > gain:
                best, gain = c, g
        if best is None:  # todos no teto: distribui o resto proporcionalmente
            for c in alloc:
                alloc[c] += remaining / len(alloc)
            break
        alloc[best] += inc
        remaining -= inc
    # Hiperfoco: canal que ficou com menos de R$ 10/dia sai e a verba vai para o maior.
    small = [c for c, v in alloc.items() if 0 < v < MIN_DAILY * days]
    if small and len(alloc) > 1:
        top = max(alloc, key=alloc.get)
        for c in small:
            if c != top:
                alloc[top] += alloc.pop(c)
    return {c: round(v, 2) for c, v in alloc.items() if v > 0}


def outcome(curves: Dict[str, Dict[str, Dict[str, Any]]], alloc: Dict[str, float], days: int) -> Dict[str, Any]:
    channels = {}
    for c, spend in alloc.items():
        p = {m: round(project(curves[c][m], spend, days), 2) for m in DEFAULT_B}
        channels[c] = {"spend": round(spend, 2), **p, "roas": _ratio(p["revenue"], spend), "cpa": _ratio(spend, p["conversions"]),
                       "cpc": _ratio(spend, p["clicks"]), "cpm": _ratio(spend * 1000, p["impressions"])}
    spend = sum(alloc.values())
    tot = {m: round(sum(ch[m] for ch in channels.values()), 2) for m in DEFAULT_B}
    return {"channels": channels, "totals": {"spend": round(spend, 2), **tot, "roas": _ratio(tot["revenue"], spend),
                                             "cpa": _ratio(spend, tot["conversions"])}}


def marginal_roas(curves, alloc: Dict[str, float], days: int) -> Optional[float]:
    """Receita a mais por R$ 1 a mais, no mix ótimo (derivada numérica)."""
    total = sum(alloc.values())
    if total <= 0:
        return None
    eps = max(total * 0.01, 1.0)
    base = sum(project(curves[c]["revenue"], s, days) for c, s in alloc.items())
    bumped = sum(project(curves[c]["revenue"], s + eps * s / total, days) for c, s in alloc.items())
    return round((bumped - base) / eps, 2)


def efficiency_budget(curves, diag, days: int, metric: str, floor: float, current: float, distribution: str = "equilibrado") -> Optional[float]:
    """Maior verba em que o próximo real ainda devolve pelo menos `floor` em receita atribuída."""
    if current <= 0:
        return None
    best = None
    for k in range(10, 61):  # 0,5x a 3x a verba atual
        b = current * k / 20
        alloc = optimize(curves, diag, b, metric, days, distribution)
        m = marginal_roas(curves, alloc, days)
        if m is None or m < floor:
            break
        best = b
    return round(best, -1) if best else None


def goal_budget(goal_revenue: Optional[float], store: Dict[str, Any], b_mix: float) -> Optional[Dict[str, Any]]:
    """Verba que leva o faturamento da loja à meta, pela elasticidade média medida (estimativa)."""
    revenue, spend = _f(store.get("revenue")), _f(store.get("investment"))
    if not goal_revenue or revenue <= 0 or spend <= 0:
        return None
    needed = spend * (goal_revenue / revenue) ** (1 / max(b_mix, 0.35))
    capped = needed > spend * 3
    return {"budget": round(min(needed, spend * 3), -1), "capped": capped, "goal": goal_revenue,
            "base_revenue": revenue, "base_spend": spend}


# --------------------------------------------------------------------------
# Campanhas, calendário e limites
# --------------------------------------------------------------------------

def classify_campaigns(channel: str, campaigns: List[Dict[str, Any]], channel_totals: Dict[str, Any], metric: str) -> List[Dict[str, Any]]:
    ch_roas, ch_cpa = channel_totals.get("roas"), channel_totals.get("cpa")
    total_spend = _f(channel_totals.get("spend"))
    out = []
    for row in campaigns:
        spend, conv, rev = _f(row.get("spend")), _f(row.get("conversions")), _f(row.get("revenue"))
        if spend < CAMPAIGN_MIN_SPEND:
            continue
        roas, cpa = _ratio(rev, spend), _ratio(spend, conv)
        name = str(row.get("campaign_name") or row.get("campaign_id") or "Campanha")[:140]
        if conv == 0 and spend >= max(2 * (ch_cpa or 0), 0.03 * total_spend, CAMPAIGN_MIN_SPEND * 2):
            action, why = "pausar", f"R$ {spend:,.0f} sem conversão em 30 dias"
        elif conv < 3:
            action, why = "aprender", "menos de 3 conversões: amostra pequena para decidir"
        elif metric == "revenue" and roas is not None and ch_roas and roas >= ch_roas * 1.2:
            action, why = "escalar", f"ROAS {roas:.2f} vs {ch_roas:.2f} do canal"
        elif metric != "revenue" and cpa is not None and ch_cpa and cpa <= ch_cpa * 0.8:
            action, why = "escalar", f"CPA R$ {cpa:,.2f} vs R$ {ch_cpa:,.2f} do canal"
        elif (metric == "revenue" and roas is not None and ch_roas and roas < ch_roas * 0.8) or \
             (metric != "revenue" and cpa is not None and ch_cpa and cpa > ch_cpa * 1.25):
            action, why = "otimizar", (f"ROAS {roas:.2f} abaixo de {ch_roas:.2f} do canal" if metric == "revenue"
                                       else f"CPA R$ {cpa:,.2f} acima de R$ {ch_cpa:,.2f} do canal")
        else:
            action, why = "manter", "eficiência dentro da média do canal"
        out.append({"channel": channel, "campaign": name, "action": action, "why": why.replace(",", "X").replace(".", ",").replace("X", "."),
                    "spend": round(spend, 2), "conversions": round(conv, 1), "revenue": round(rev, 2), "roas": roas, "cpa": cpa,
                    "share": _ratio(spend, total_spend)})
    order = {"escalar": 0, "pausar": 1, "otimizar": 2, "manter": 3, "aprender": 4}
    return sorted(out, key=lambda r: (order[r["action"]], -r["spend"]))


def plan_campaign_budgets(campaigns: List[Dict[str, Any]], allocation: Dict[str, float], days: int, objective: str,
                          boost_pool: float = 0.0) -> List[Dict[str, Any]]:
    """Verba planejada por campanha dentro da verba de cada canal.

    Peso = investimento atual × fator da ação (escalar 1,3 · manter 1 · otimizar 0,7 · aprender 0,6 · pausar 0).
    Campanha abaixo de R$ 10/dia sai do plano (verba concentrada nas demais). Canal sem campanhas recebe
    campanhas sugeridas de teste; Meta reserva a verba dos impulsionamentos do calendário."""
    out = [dict(r, planned_budget=0.0) for r in campaigns]
    for channel, channel_budget in allocation.items():
        budget = channel_budget - (boost_pool if channel == "meta" else 0.0)
        rows = [r for r in out if r["channel"] == channel and ACTION_WEIGHT.get(r["action"], 0) > 0]
        if not rows:
            for name, share, why in SUGGESTED_CAMPAIGNS[channel][objective]:
                out.append({"channel": channel, "campaign": name, "action": "testar", "why": why, "spend": 0.0, "conversions": 0.0,
                            "revenue": 0.0, "roas": None, "cpa": None, "share": None, "suggested": True, "planned_budget": 0.0, "_w": share})
            rows = [r for r in out if r["channel"] == channel and r.get("suggested")]
        for r in rows:
            r["_w"] = r.get("_w") or max(r["spend"], 1.0) * ACTION_WEIGHT[r["action"]]
        while True:
            total = sum(r["_w"] for r in rows) or 1
            for r in rows:
                r["planned_budget"] = round(max(budget, 0) * r["_w"] / total, 2)
            low = [r for r in rows if r["planned_budget"] / days < MIN_DAILY]
            if not low or len(rows) == 1:
                break
            drop = min(low, key=lambda r: r["_w"])
            drop["planned_budget"], drop["concentrated"] = 0.0, True
            rows.remove(drop)
        if channel == "meta" and boost_pool > 0:
            out.append({"channel": "meta", "campaign": "Impulsionamento dos posts do calendário", "action": "impulsionar",
                        "why": "verba reservada para as pautas escolhidas (ver Impulsionamento)", "spend": 0.0, "conversions": 0.0,
                        "revenue": 0.0, "roas": None, "cpa": None, "share": None, "planned_budget": round(boost_pool, 2), "boost": True})
    for r in out:
        r.pop("_w", None)
        if r.get("concentrated"):
            r["why"] = f"{r['why']}; verba concentrada nas demais (abaixo de R$ 10/dia)"
    return out


def learn_from_history(rows: List[Dict[str, Any]], memory: Dict[str, Dict[str, Any]], metric: str) -> int:
    """Compara cada campanha com o que foi decidido nos planos anteriores e ajusta a recomendação."""
    months = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
    learned = 0
    for r in rows:
        m = memory.get(r["campaign"])
        if not m or r.get("suggested") or r.get("boost"):
            continue
        label = months[int(str(m["month"])[5:7]) - 1]
        prev, now = (m.get("roas"), r.get("roas")) if metric == "revenue" else (m.get("cpa"), r.get("cpa"))
        delta = _change(now, prev)
        better = None if delta is None else (delta >= 15 if metric == "revenue" else delta <= -15)
        worse = None if delta is None else (delta <= -25 if metric == "revenue" else delta >= 25)
        unit = "ROAS" if metric == "revenue" else "CPA"
        fmt = (lambda v: f"{v:.2f}".replace(".", ",")) if metric == "revenue" else (lambda v: f"R$ {v:,.0f}".replace(",", "."))
        note = None
        if m["action"] == "escalar" and worse:
            r["action"], note = "manter", f"Escalada em {label}: {unit} foi de {fmt(prev)} para {fmt(now)} com mais verba. Segurar."
        elif m["action"] == "escalar" and delta is not None and not worse:
            note = f"Escalada em {label} sustentou o {unit} ({fmt(prev)} → {fmt(now)})."
        elif m["action"] == "pausar" and r["spend"] > 0:
            note = f"Indicada para pausar em {label} e seguiu investindo R$ {r['spend']:,.0f}.".replace(",", ".")
        elif m["action"] == "otimizar" and better:
            r["action"], note = "manter", f"Otimização de {label} funcionou: {unit} {fmt(prev)} → {fmt(now)}."
        elif m["action"] == "otimizar" and worse:
            r["action"], note = "pausar", f"Seguiu piorando depois da otimização de {label} ({unit} {fmt(prev)} → {fmt(now)})."
        elif m["action"] in ("testar", "aprender") and r["conversions"] >= 3:
            note = f"Saiu do teste de {label} com {r['conversions']:.0f} conversões."
        if m.get("edited"):
            team = f"A equipe definiu {m['action']} com R$ {_f(m.get('planned_budget')):,.0f} em {label}.".replace(",", ".")
            note = f"{note} {team}" if note else team
        if note:
            r["learning"], r["memory"] = note, {k: m.get(k) for k in ("month", "action", "roas", "cpa", "planned_budget")}
            learned += 1
    return learned


def apply_trends(rows: List[Dict[str, Any]], history: Dict[str, List[Dict[str, Any]]], metric: str, today: date) -> int:
    """Linha do tempo semanal de cada campanha (studio_campaign_learnings) ajustando a recomendação."""
    from .campaign_learning import trend_note
    learned = 0
    for r in rows:
        if r.get("suggested") or r.get("boost"):
            continue
        t = trend_note(history.get(r["campaign"]) or [], metric, today)
        if not t:
            continue
        if t["kind"] == "nova" and r["action"] in ("pausar", "otimizar"):
            r["action"] = "aprender"  # não corta campanha nova antes de sair do aprendizado
        elif t["kind"] == "queda" and r["action"] == "escalar":
            r["action"] = "manter"
        r["learning"] = f"{r['learning']} {t['text']}" if r.get("learning") else t["text"]
        learned += 1
    return learned


def month_weeks(month: date, budget: float, custom: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    from .studio_dates import COMMERCIAL, dates_for_month
    last = month.replace(day=calendar.monthrange(month.year, month.month)[1])
    events = [e for e in dates_for_month(month, custom) if e.get("kind") in (COMMERCIAL, "custom", "marca")]
    weights: Dict[date, float] = {}
    for i in range((last - month).days + 1):
        weights[month + timedelta(days=i)] = 1.0
    for e in events:
        d = date.fromisoformat(str(e["date"])[:10])
        peak = 2.2 if "Black Friday" in e["label"] or "Cyber" in e["label"] else 1.6
        lead = 12 if "Natal" in e["label"] or "Black Friday" in e["label"] else 7
        for i in range(lead + 1):
            day = d - timedelta(days=i)
            if day in weights:
                weights[day] = max(weights[day], peak - (peak - 1) * i / (lead + 1))
    total_w = sum(weights.values())
    # Semanas de segunda a domingo; pedaço de menos de 3 dias no começo/fim do mês junta com a semana vizinha.
    spans, cursor = [], month
    while cursor <= last:
        end = min(cursor + timedelta(days=6 - cursor.weekday()), last)
        spans.append([cursor, end])
        cursor = end + timedelta(days=1)
    if len(spans) > 1 and (spans[0][1] - spans[0][0]).days < 2:
        first = spans.pop(0)
        spans[0][0] = first[0]
    if len(spans) > 1 and (spans[-1][1] - spans[-1][0]).days < 2:
        tail = spans.pop()
        spans[-1][1] = tail[1]
    weeks = []
    for cursor, end in spans:
        days = [cursor + timedelta(days=i) for i in range((end - cursor).days + 1)]
        w = sum(weights[d] for d in days)
        inside = [e["label"] for e in events if cursor <= date.fromisoformat(str(e["date"])[:10]) <= end]
        ahead = [e["label"] for e in events if end < date.fromisoformat(str(e["date"])[:10]) <= end + timedelta(days=10)]
        intensity = w / len(days)
        weeks.append({"start": cursor.isoformat(), "end": end.isoformat(), "budget": round(budget * w / total_w, 2),
                      "share": round(w / total_w, 4), "daily": round(budget * w / total_w / len(days), 2),
                      "phase": "pico" if intensity >= 1.5 else "aquecimento" if intensity > 1.05 else "base",
                      "dates": sorted(set(inside)), "prepares": sorted(set(ahead) - set(inside))})
    return weeks


def guardrails(result: Dict[str, Any], days: int, margin: Optional[float]) -> List[Dict[str, Any]]:
    breakeven = round(1 / margin, 2) if margin else None
    out = []
    for c, p in result["channels"].items():
        if p["spend"] <= 0:
            continue
        min_roas = max(breakeven or 0, round((p["roas"] or 0) * 0.7, 2)) or None
        out.append({"channel": c, "label": CHANNELS[c], "daily_budget": round(p["spend"] / days, 2),
                    "target_cpa": p["cpa"], "max_cpa": round(p["cpa"] * 1.3, 2) if p["cpa"] else None,
                    "target_roas": p["roas"], "min_roas": min_roas, "breakeven_roas": breakeven,
                    "rule": "Se o CPA passar do máximo ou o ROAS ficar abaixo do mínimo por 3 dias seguidos, reduza 20% da verba diária "
                            "e revise criativos antes de voltar a escalar."})
    return out


# --------------------------------------------------------------------------
# Impulsionamento cruzado com o calendário editorial
# --------------------------------------------------------------------------

BOOST_SHARE = 0.2  # parte da verba de Meta reservada para impulsionar posts do calendário
BOOST_DAYS = 7
FORMAT_DEFAULT_RANK = {"reels": 3, "carrossel": 2, "video": 2, "imagem": 1, "stories": 0}


def boost_plan(items: List[Dict[str, Any]], weeks: List[Dict[str, Any]], *, meta_budget: float, meta_cpm: Optional[float],
               format_reach: Dict[str, Any], today: date, share: float = BOOST_SHARE) -> Dict[str, Any]:
    """Quais posts do calendário impulsionar, de quando a quando e com quanto.

    * Formato: o que mais alcança na própria conta (alcance mediano por formato); sem histórico, Reels > carrossel > imagem.
    * Data: semanas de "pico"/"aquecimento" (antes das datas comerciais) pesam mais; pauta de data sazonal ganha prioridade.
    * Início: 1 dia depois de publicar (24 h de leitura orgânica antes de pagar); em semana de pico, no mesmo dia,
      porque a janela de compra é curta. Duração de 7 dias, sem passar do fim do mês.
    * Verba: 20% do que foi planejado para Meta, dividido pelo peso de cada post, com mínimo de R$ 10/dia
      por impulsionamento (sai o post de menor nota quando a verba não fecha a conta)."""
    pool = round(meta_budget * share, 2)
    if pool <= 0 or not items:
        return {"pool": pool, "share": share, "posts": [], "note": None if items else
                "Gere o calendário do mês para receber o plano de impulsionamento dos posts."}
    ranked = sorted(format_reach.items(), key=lambda kv: -_f(kv[1])) if format_reach else []
    format_rank = {fmt: len(ranked) - i for i, (fmt, _) in enumerate(ranked)} or FORMAT_DEFAULT_RANK

    def week_of(day: date) -> Optional[Dict[str, Any]]:
        return next((w for w in weeks if w["start"] <= day.isoformat() <= w["end"]), None)

    candidates = []
    for item in items:
        if item.get("status") in ("rejeitado",) or item.get("format") == "stories":
            continue
        try:
            posted = datetime.fromisoformat(str(item["scheduled_at"]).replace("Z", "+00:00")).astimezone(SAO_PAULO).date()
        except (KeyError, ValueError):
            continue
        week = week_of(posted)
        phase = (week or {}).get("phase", "base")
        seasonal = (item.get("signals") or {}).get("seasonal")
        score = format_rank.get(item.get("format"), 1) + {"pico": 3, "aquecimento": 1.5}.get(phase, 0) \
            + (1.5 if seasonal else 0) + (0.5 if item.get("status") in ("aprovado", "publicado") else 0)
        start = posted if phase == "pico" else posted + timedelta(days=1)
        if start < today:
            continue
        last_day = date.fromisoformat(weeks[-1]["end"]) if weeks else start + timedelta(days=BOOST_DAYS - 1)
        end = min(start + timedelta(days=BOOST_DAYS - 1), last_day)
        candidates.append({"item_id": item.get("id"), "title": str(item.get("title") or "")[:200], "format": item.get("format"),
                           "status": item.get("status"), "posted": posted.isoformat(), "start": start.isoformat(), "end": end.isoformat(),
                           "phase": phase, "seasonal": seasonal, "score": round(score, 2)})
    if not candidates:
        return {"pool": pool, "share": share, "posts": [], "note": "Nenhum post futuro elegível no calendário deste mês."}
    keep = max(2, min(len(candidates), len(weeks) * 2))
    chosen = sorted(candidates, key=lambda c: -c["score"])[:keep]

    def span(c: Dict[str, Any]) -> int:
        return (date.fromisoformat(c["end"]) - date.fromisoformat(c["start"])).days + 1

    def split(posts: List[Dict[str, Any]]) -> None:
        total = sum(p["score"] for p in posts) or 1
        for p in posts:
            p["budget"] = round(pool * p["score"] / total, 2)

    # Nenhum impulsionamento abaixo de R$ 10/dia: sai o post de menor nota até a verba fechar a conta.
    split(chosen)
    while len(chosen) > 1 and any(c["budget"] / span(c) < MIN_DAILY for c in chosen):
        chosen = sorted(chosen, key=lambda c: -c["score"])[:-1]
        split(chosen)
    if chosen and chosen[0]["budget"] / span(chosen[0]) < MIN_DAILY:
        # Um post só e ainda abaixo do mínimo: encurta a duração (até 3 dias) para manter R$ 10/dia.
        days_ok = int(chosen[0]["budget"] // MIN_DAILY)
        if days_ok < MIN_BOOST_DAYS:
            return {"pool": pool, "share": share, "posts": [], "min_daily": MIN_DAILY,
                    "note": f"A verba de impulsionamento ({pool:,.0f} reais) não paga o mínimo de R$ {MIN_DAILY:.0f}/dia por {MIN_BOOST_DAYS} dias.".replace(",", ".")}
        chosen[0]["end"] = (date.fromisoformat(chosen[0]["start"]) + timedelta(days=days_ok - 1)).isoformat()
    for c in chosen:
        days = span(c)
        c["daily"] = round(c["budget"] / days, 2)
        c["impressions"] = int(c["budget"] / meta_cpm * 1000) if meta_cpm else None
        reason = [f"formato {c['format']} é dos que mais alcançam na conta" if format_rank.get(c["format"], 0) >= max(format_rank.values()) - 1 else None,
                  f"semana de {c['phase']}" if c["phase"] != "base" else None,
                  f"pauta de {c['seasonal']}" if c["seasonal"] else None,
                  "começa no dia da publicação por ser semana de pico" if c["phase"] == "pico" else "começa 24 h depois de publicar"]
        c["why"] = "; ".join(r for r in reason if r)
    return {"pool": pool, "share": share, "posts": sorted(chosen, key=lambda c: c["start"]), "note": None, "min_daily": MIN_DAILY}


# --------------------------------------------------------------------------
# Orquestração
# --------------------------------------------------------------------------

async def _store_and_goal(client_id: str, end: date, month: date) -> Tuple[Dict[str, Any], Optional[float], List[Dict[str, Any]]]:
    store: Dict[str, Any] = {}
    goal = None
    custom: List[Dict[str, Any]] = []
    try:
        from .intelligence import calculate_intelligence_snapshot
        snap = await calculate_intelligence_snapshot(client_id=client_id, start=(end - timedelta(days=29)).isoformat(), end=end.isoformat(),
                                                     include_commerce_details=False, include_external_research=False)
        metrics = {m.get("id"): m for m in snap.get("metrics") or []}
        store = {k: _f((metrics.get(k) or {}).get("value")) for k in ("revenue", "orders", "investment", "roas", "sessions")}
    except Exception as exc:
        print(f"[media][strategy] loja_indisponivel erro={exc.__class__.__name__}")
    try:
        from .goals import list_goals
        last = month.replace(day=calendar.monthrange(month.year, month.month)[1])
        data = await list_goals(client_id, month.isoformat(), last.isoformat(), include_actuals=False)
        goal = next((_f(g.get("target_value")) for g in data.get("goals") or [] if g.get("metric") == "revenue"), None)
    except Exception as exc:
        print(f"[media][strategy] metas_indisponiveis erro={exc.__class__.__name__}")
    try:
        from .studio_calendar import load_profile
        custom = ((await load_profile(client_id)).get("profile") or {}).get("custom_dates") or []
    except Exception:
        custom = []
    return store, goal, custom


async def campaign_memory(client_id: str, month: date) -> Dict[str, Dict[str, Any]]:
    """Decisões por campanha nos últimos planos salvos (mais recente primeiro)."""
    try:
        from .ig_supabase import sb_select
        plans = await sb_select("studio_media_plans", select="month,strategy,status", order="month.desc", limit=3,
                                filters={"client_id": f"eq.{client_id}", "month": f"lt.{month.isoformat()}"})
    except Exception as exc:
        print(f"[media][strategy] memoria_indisponivel erro={exc.__class__.__name__}")
        return {}
    memory: Dict[str, Dict[str, Any]] = {}
    for plan in plans:
        for row in ((plan.get("strategy") or {}).get("campaigns") or []):
            name = row.get("campaign")
            if name and name not in memory and not row.get("boost"):
                memory[name] = {"month": plan["month"], **{k: row.get(k) for k in ("action", "roas", "cpa", "spend", "planned_budget", "edited")}}
    return memory


async def _calendar_context(client_id: str, month: date, today: date) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    reach: Dict[str, Any] = {}
    try:
        from .studio_calendar import list_items
        items = await list_items(client_id, month)
    except Exception as exc:
        print(f"[media][strategy] calendario_indisponivel erro={exc.__class__.__name__}")
    try:
        from .posting_times import build_posting_times
        best = await build_posting_times(client_id, start=(today - timedelta(days=179)).isoformat(), end=today.isoformat())
        reach = best.get("format_median_reach") or {}
    except Exception as exc:
        print(f"[media][strategy] alcance_por_formato_indisponivel erro={exc.__class__.__name__}")
    return items, reach


async def build_strategy(client_id: str, *, month: str, objective: str, margin: Optional[float] = None,
                         custom_budget: Optional[float] = None, today: Optional[date] = None,
                         distribution: str = "equilibrado") -> Dict[str, Any]:
    target = parse_month(month)
    if objective not in OBJECTIVES:
        raise StudioError("OBJECTIVE_INVALID")
    if margin is not None and not 0.02 <= margin <= 0.95:
        raise StudioError("MARGIN_INVALID")
    if distribution not in DISTRIBUTIONS:
        raise StudioError("DISTRIBUTION_INVALID")
    today = today or datetime.now(SAO_PAULO).date()
    end = today - timedelta(days=1)
    days = calendar.monthrange(target.year, target.month)[1]
    metric = OBJECTIVE_METRIC[objective]
    data = await read_window(client_id, end)
    diag = {c: diagnose(c, data[c]["daily"], end) for c in CHANNELS}
    with_data = {c: d for c, d in diag.items() if d["confidence"] != "sem_dados"}
    if not with_data and not custom_budget:
        raise StudioError("NO_PAID_HISTORY")
    store, goal, custom = await _store_and_goal(client_id, end, target)
    calendar_items, format_reach = await _calendar_context(client_id, target, today)
    current = round(sum(d["recent"]["spend"] for d in with_data.values()) * days / 30, -1)
    curves = {c: curves_for(weekly(data[c]["daily"], end)) for c in with_data}
    # Canal sem histórico entra como teste estimado (loja + referência) no modo equilibrado, ou quando não há nenhum dado.
    reference_inputs: Dict[str, Dict[str, Any]] = {}
    if distribution == "equilibrado" or not with_data:
        test_budget = max(custom_budget or current, MIN_DAILY * days * len(CHANNELS)) * TEST_SHARE
        for c in CHANNELS:
            if c not in with_data:
                curves[c], reference_inputs[c] = reference_curves(c, store, test_budget, days)
                diag[c] = {**diag[c], "confidence": "referencia", "reference": reference_inputs[c]}
    usable = {c: diag[c] for c in curves}
    attributed = sum(d["window"]["revenue"] for d in with_data.values())
    spent = sum(d["window"]["spend"] for d in with_data.values())
    no_value = (with_data and (attributed <= 0 or attributed / max(spent, 1) < MIN_ATTRIBUTED_ROAS)) or \
        (not with_data and not any(i.get("ticket") for i in reference_inputs.values()))
    if metric == "revenue" and no_value:
        metric = "conversions"  # receita atribuída irrisória: otimiza por conversões e avisa
    b_mix = sum(curves[c]["revenue"]["b"] * with_data[c]["recent"]["spend"] for c in with_data) / max(sum(d["recent"]["spend"] for d in with_data.values()), 1)
    floor = max(MIN_MARGINAL_ROAS, round(1 / margin, 2)) if margin else MIN_MARGINAL_ROAS
    scenarios: List[Dict[str, Any]] = []

    def scenario(key: str, label: str, budget: Optional[float], why: str, extra: Optional[Dict[str, Any]] = None):
        if not budget or budget <= 0:
            return
        alloc = optimize(curves, usable, budget, metric, days, distribution)
        result = outcome(curves, alloc, days)
        current_alloc = {c: with_data[c]["recent"]["spend"] * days / 30 for c in with_data}
        scenarios.append({"key": key, "label": label, "budget": round(budget, 2), "why": why, "allocation": alloc,
                          "allocation_pct": {c: _ratio(v, budget) for c, v in alloc.items()},
                          "change_vs_current": {c: _change(alloc.get(c), current_alloc.get(c)) for c in alloc},
                          "result": result, "marginal_roas": marginal_roas(curves, alloc, days), **(extra or {})})

    tested = [CHANNELS[c] for c in reference_inputs]
    scenario("ritmo_atual", "Ritmo atual", current, "Mesma verba dos últimos 30 dias, redistribuída pela curva de retorno de cada canal"
             + (f", com parte em teste no {', '.join(tested)}." if tested else "."))
    goal_info = goal_budget(goal, store, b_mix)
    if goal_info:
        scenario("meta", "Bater a meta", goal_info["budget"],
                 (f"Meta de faturamento de R$ {goal_info['goal']:,.0f}. "
                  + ("A meta exige mais de 3x a verba atual; mostramos o teto de 3x." if goal_info["capped"] else
                     "Estimativa pela elasticidade medida entre verba e faturamento.")).replace(",", "."), {"goal": goal_info})
    # Limite de eficiência só com canais medidos: não extrapola verba em cima de estimativa de canal sem histórico.
    eff = efficiency_budget({c: curves[c] for c in with_data}, with_data, days, metric, floor, current, "hiperfoco") \
        if metric == "revenue" and current > 0 and with_data else None
    if eff and abs(eff - current) / max(current, 1) > 0.05:
        scenario("eficiencia", "Limite de eficiência", eff,
                 f"Maior verba em que cada R$ 1 a mais ainda devolve pelo menos R$ {floor:.2f} em receita atribuída"
                 + (" (ponto de equilíbrio pela margem informada)." if margin else "."))
    if custom_budget:
        scenario("personalizado", "Verba informada", custom_budget, "Verba definida pela equipe, dividida pela curva de retorno.")
    recommended = next((s["key"] for s in scenarios if s["key"] == "meta" and not s.get("goal", {}).get("capped")), None) \
        or (None if reference_inputs else next((s["key"] for s in scenarios if s["key"] == "eficiencia"), None)) \
        or ("ritmo_atual" if any(s["key"] == "ritmo_atual" for s in scenarios) else "personalizado")
    chosen = next(s for s in scenarios if s["key"] == (("personalizado" if custom_budget else recommended)))

    campaigns = [row for c in with_data for row in classify_campaigns(c, data[c]["campaigns"], with_data[c]["recent"], metric)]
    learned = learn_from_history(campaigns, await campaign_memory(client_id, target), metric)
    from .campaign_learning import campaign_history
    learned += apply_trends(campaigns, await campaign_history(client_id), metric, today)
    waste = round(sum(r["spend"] for r in campaigns if r["action"] == "pausar"), 2)
    findings = [f for d in with_data.values() for f in d["findings"]]
    if learned:
        findings.insert(0, {"level": "info", "text": f"Aprendizado: {learned} campanha(s) comparadas com as decisões dos planos anteriores; recomendações ajustadas."})
    for c, inputs in reference_inputs.items():
        parts = [f"CPM R$ {inputs['cpm']:.0f} e CTR {inputs['ctr'] * 100:.1f}% de referência de mercado",
                 f"conversão de {inputs['cvr'] * 100:.1f}% ({inputs['cvr_source']})"]
        if inputs.get("ticket"):
            parts.append(f"ticket de R$ {inputs['ticket']:,.0f} ({inputs['ticket_source']})".replace(",", "."))
        findings.append({"level": "oportunidade", "text": f"{CHANNELS[c]} sem histórico: entra como teste estimado com " + ", ".join(parts)
                         + ". Revise a estimativa depois de 2 semanas de dados reais."})
    if waste > 0:
        share = waste / max(sum(d["recent"]["spend"] for d in with_data.values()), 1) * 100
        findings.insert(0, {"level": "alerta", "text": f"R$ {waste:,.0f} ({share:.0f}% da verba) foram para campanhas sem conversão em 30 dias.".replace(",", ".")})
    if metric != OBJECTIVE_METRIC[objective]:
        findings.append({"level": "info", "text": "As plataformas quase não registram valor de conversão (receita atribuída irrisória): "
                                                   "a estratégia otimiza por número de conversões."})
    weak = [CHANNELS[c] for c in curves if curves[c][metric]["fit"] == "estimada"]
    if weak:
        findings.append({"level": "info", "text": f"Curva de retorno estimada (pouca variação de verba no histórico) em: {', '.join(weak)}. "
                                                   "Os cenários acima do ritmo atual têm mais incerteza."})
    weeks = month_weeks(target, chosen["budget"], custom)
    meta_cpm = (with_data["meta"]["recent"].get("cpm") if "meta" in with_data else
                (reference_inputs.get("meta") or {}).get("cpm"))
    boosts = boost_plan(calendar_items, weeks, meta_budget=chosen["allocation"].get("meta", 0.0), meta_cpm=meta_cpm,
                        format_reach=format_reach, today=today)
    pool = sum(b["budget"] for b in boosts.get("posts") or [])
    campaigns = plan_campaign_budgets(campaigns, chosen["allocation"], days, objective, boost_pool=pool)
    return {
        "boosts": boosts,
        "distribution": distribution, "reference_inputs": reference_inputs, "learned": learned,
        "month": target.isoformat(), "objective": objective, "metric": metric, "metric_label": METRIC_LABEL[metric], "days": days,
        "window": {"start": (end - timedelta(days=WINDOW_DAYS - 1)).isoformat(), "end": end.isoformat(), "days": WINDOW_DAYS},
        "diagnosis": list(diag.values()), "store": store, "goal_revenue": goal, "margin": margin,
        "curves": {c: {m: {k: curves[c][m][k] for k in ("a", "b", "fit", "r2", "points")} for m in DEFAULT_B} for c in curves},
        "channel_kind": {c: ("referencia" if c in reference_inputs else "dados") for c in curves},
        "current_budget": current, "scenarios": scenarios, "recommended": recommended, "selected": chosen["key"],
        "weeks": weeks, "guardrails": guardrails(chosen["result"], days, margin),
        "campaigns": campaigns, "waste": waste, "findings": findings,
        "method": ("Curva y = a·gasto^b por canal, ajustada nas 13 semanas mais recentes (b medido quando a verba variou e o ajuste "
                   "explica pelo menos 30% da variação; senão, referência conservadora). A divisão maximiza o resultado do objetivo com "
                   "mínimo de 5% para canais ativos, teto de 40% para canais com poucos dados e no máximo 2,5x o investimento mensal "
                   "atual de cada canal (1,5x quando a curva é estimada). Nenhum canal, campanha ou impulsionamento fica abaixo de R$ 10 por dia. "
                   "Modo equilibrado: todo canal recebe ao menos 20%; canal sem histórico entra como teste estimado (conversão e ticket da "
                   "loja, CPM e CTR de referência de mercado) com teto de 40%. Hiperfoco: a verba vai para onde a curva rende mais. "
                   "Cada campanha é comparada com a decisão do plano anterior e com a própria linha do tempo semanal (aprendizado). Receita e conversões são as atribuídas pelas plataformas."),
    }


# --------------------------------------------------------------------------
# Leitura estratégica (IA)
# --------------------------------------------------------------------------

async def narrative(client_id: str, strategy: Dict[str, Any]) -> Dict[str, Any]:
    from .studio_engines import throttle
    from .studio_intelligence import build_content_intelligence, to_prompt
    from .studio_llm import STR, arr, llm_json, obj

    throttle(client_id)
    names = sorted({c["campaign"] for c in strategy["campaigns"]})
    chosen = next(s for s in strategy["scenarios"] if s["key"] == strategy["selected"])
    facts = {
        "objetivo": OBJECTIVES[strategy["objective"]], "otimiza_por": strategy["metric_label"],
        "diagnostico": [{"canal": d["label"], "ultimos_30": {k: d["recent"].get(k) for k in ("spend", "revenue", "roas", "cpa", "cpm", "ctr", "conversions")},
                         "variacao_pct": d["changes"], "confianca": d["confidence"]} for d in strategy["diagnosis"] if d["confidence"] != "sem_dados"],
        "achados": [f["text"] for f in strategy["findings"]],
        "cenario_escolhido": {"nome": chosen["label"], "verba": chosen["budget"], "divisao": chosen["allocation"],
                              "resultado": chosen["result"]["totals"], "roas_marginal": chosen["marginal_roas"]},
        "outros_cenarios": [{"nome": s["label"], "verba": s["budget"], "resultado": s["result"]["totals"]} for s in strategy["scenarios"] if s is not chosen],
        "campanhas": [{**{k: c.get(k) for k in ("channel", "campaign", "action", "why", "spend", "roas", "cpa", "planned_budget")},
                       **({"aprendizado": c["learning"]} if c.get("learning") else {}), **({"sugerida": True} if c.get("suggested") else {})}
                      for c in strategy["campaigns"][:25]],
        "canais_estimados": strategy.get("reference_inputs") or {}, "modo": strategy.get("distribution"),
        "semanas": [{k: w.get(k) for k in ("start", "end", "budget", "phase", "dates", "prepares")} for w in strategy["weeks"]],
        "meta_faturamento": strategy.get("goal_revenue"), "loja_30_dias": strategy.get("store"),
        "impulsionamento_do_calendario": [{k: b[k] for k in ("title", "format", "start", "end", "budget", "why")}
                                          for b in (strategy.get("boosts") or {}).get("posts") or []],
    }
    intel = await build_content_intelligence(client_id)
    schema = obj({
        "headline": STR, "thesis": STR,
        "channel_roles": arr(obj({"channel": {"type": "string", "enum": list(CHANNELS)}, "role": STR, "rationale": STR})),
        "campaign_notes": arr(obj({"campaign": {"type": "string", "enum": names or ["-"]}, "note": STR})),
        "creative_guidance": arr(STR), "risks": arr(STR), "next_7_days": arr(STR),
    })
    data = await llm_json(
        instructions=("Você é o head de mídia paga da agência. Escreve a estratégia do mês para o cliente com base EXCLUSIVA nos números "
                      "calculados. Cite números concretos (verba, ROAS, CPA, variações). Não invente métricas, campanhas, públicos ou "
                      "resultados. Português do Brasil, frases curtas, tom de consultoria."),
        prompt=(f"NÚMEROS CALCULADOS:\n{json.dumps(facts, ensure_ascii=False, default=str)}\n\n"
                f"CONTEXTO DA MARCA:\n{to_prompt(intel, sections=['negocio', 'marca', 'metas_do_mes', 'ultima_analise', 'posts'], limit=5000)}\n\n"
                "Escreva: headline (1 frase com o principal número), thesis (3-4 frases: onde investir, por quê e o resultado esperado), "
                "channel_roles (papel de cada canal no funil: prospecção, remarketing, captura de demanda…), campaign_notes (até 6, só "
                "campanhas da lista, dizendo o que fazer), creative_guidance (até 4, ligados ao que performou), risks (até 3), "
                "next_7_days (até 5 ações operacionais em ordem; inclua as datas de início dos impulsionamentos do calendário, se houver)."),
        schema_name="media_strategy_narrative", schema=schema, temperature=0.35, timeout=90)
    valid = set(names)
    return {
        "headline": str(data.get("headline") or "")[:240], "thesis": str(data.get("thesis") or "")[:1500],
        "channel_roles": [r for r in data.get("channel_roles") or [] if r.get("channel") in CHANNELS][:2],
        "campaign_notes": [n for n in data.get("campaign_notes") or [] if n.get("campaign") in valid][:6],
        "creative_guidance": [str(x)[:300] for x in (data.get("creative_guidance") or [])[:4]],
        "risks": [str(x)[:300] for x in (data.get("risks") or [])[:3]],
        "next_7_days": [str(x)[:300] for x in (data.get("next_7_days") or [])[:5]],
    }
