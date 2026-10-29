"""Mídia On: baseline real por canal, simulador, plano mensal e planejado x realizado.

Trazido do Media.tsx do iAgência, mas com os números da própria empresa: CPM,
CPC, CTR, taxa de conversão e valor por conversão saem dos últimos 90 dias de
Meta Ads e Google Ads já persistidos no Dados. Canal sem dados não recebe
número inventado: a equipe informa a premissa ou o canal fica de fora.

A simulação é transparente (cada número mostra a fórmula e a premissa) e usa
um fator de retorno decrescente quando a verba planejada passa muito do que o
canal costuma investir por mês.
"""
from __future__ import annotations

import calendar
import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from .ig_supabase import sb_select, sb_upsert
from .studio_calendar import StudioError, parse_month

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
PLANS = "studio_media_plans"
CHANNELS = {"meta": "Meta Ads", "google_ads": "Google Ads"}
OBJECTIVES = {"vendas": "Vendas", "leads": "Leads/cadastros", "trafego": "Tráfego para o site", "alcance": "Alcance e marca"}
BASELINE_DAYS = 90
MIN_IMPRESSIONS = 1000
MIN_DAYS = 14
SCENARIOS = {"conservador": 0.8, "esperado": 1.0, "otimista": 1.15}
SATURATION_EXPONENT = 0.15  # quanto a eficiência cai quando a verba passa do ritmo habitual


def _f(value: Any) -> float:
    try:
        out = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return out if out == out else 0.0


def _div(a: float, b: float) -> Optional[float]:
    return round(a / b, 4) if b else None


def channel_metrics(totals: Dict[str, Any], *, days_covered: int, period_days: int) -> Dict[str, Any]:
    spend, imp, clicks = _f(totals.get("spend")), _f(totals.get("impressions")), _f(totals.get("clicks"))
    conv = _f(totals.get("conversions"))
    value = _f(totals.get("revenue") if totals.get("revenue") is not None else totals.get("conversion_value"))
    confidence = "sem_dados" if spend <= 0 else "baixa" if imp < MIN_IMPRESSIONS or days_covered < MIN_DAYS else "boa"
    return {
        "spend": round(spend, 2), "impressions": int(imp), "clicks": int(clicks), "conversions": round(conv, 2),
        "conversion_value": round(value, 2), "days_covered": days_covered,
        "cpm": _div(spend * 1000, imp), "cpc": _div(spend, clicks), "ctr": _div(clicks, imp),
        "conversion_rate": _div(conv, clicks), "cpa": _div(spend, conv), "value_per_conversion": _div(value, conv),
        "roas": _div(value, spend), "monthly_spend": round(spend / max(period_days, 1) * 30, 2),
        "confidence": confidence,
    }


async def _meta(client_id: str, start: str, end: str) -> Dict[str, Any]:
    from .dashboard_paid import get_paid_dashboard
    data = await get_paid_dashboard(client_id, start=start, end=end)
    return {"totals": data.get("totals") or {}, "days": int((data.get("coverage") or {}).get("covered_days") or 0)}


async def _google(client_id: str, start: str, end: str) -> Dict[str, Any]:
    from .google_ads import build_google_ads_report, resolve_google_ads_context
    context = await resolve_google_ads_context(client_id)
    data = await build_google_ads_report(client_id=client_id, context=context, start=start, end=end)
    return {"totals": data.get("totals") or {}, "days": int((data.get("coverage") or {}).get("covered_days") or 0)}


READERS = {"meta": _meta, "google_ads": _google}


async def read_channels(client_id: str, start: str, end: str) -> Dict[str, Dict[str, Any]]:
    period_days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    out: Dict[str, Dict[str, Any]] = {}
    for channel, reader in READERS.items():
        try:
            raw = await reader(client_id, start, end)
            out[channel] = channel_metrics(raw["totals"], days_covered=raw["days"], period_days=period_days)
        except Exception as exc:  # canal desconectado ou sem conexão: fica sem dados, não quebra o plano
            print(f"[media][baseline] canal={channel} erro={exc.__class__.__name__}")
            out[channel] = {**channel_metrics({}, days_covered=0, period_days=period_days), "confidence": "desconectado"}
    return out


async def baseline(client_id: str) -> Dict[str, Any]:
    today = datetime.now(SAO_PAULO).date()
    end = today - timedelta(days=1)
    start = end - timedelta(days=BASELINE_DAYS - 1)
    channels = await read_channels(client_id, start.isoformat(), end.isoformat())
    return {"period": {"start": start.isoformat(), "end": end.isoformat(), "days": BASELINE_DAYS},
            "channels": channels, "channel_labels": CHANNELS, "objectives": OBJECTIVES}


# --------------------------------------------------------------------------
# Simulação
# --------------------------------------------------------------------------

def default_assumptions(channels: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Premissas iniciais = números reais do canal (None quando não há dado)."""
    return {ch: {k: m.get(k) for k in ("cpm", "cpc", "conversion_rate", "value_per_conversion")} | {"monthly_spend": m.get("monthly_spend")}
            for ch, m in channels.items()}


def saturation(planned: float, usual: Optional[float]) -> float:
    """1,0 até 1,5x o ritmo habitual; depois a eficiência cai devagar (retorno decrescente)."""
    if not usual or planned <= usual * 1.5:
        return 1.0
    return round((usual * 1.5 / planned) ** SATURATION_EXPONENT, 4)


def simulate(*, budget: float, allocation: Dict[str, float], assumptions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    if budget <= 0:
        raise StudioError("BUDGET_INVALID")
    total_pct = sum(max(0.0, _f(v)) for v in allocation.values())
    if not 99.5 <= total_pct <= 100.5:
        raise StudioError("ALLOCATION_INVALID")
    rows, warnings = [], []
    for channel, pct in allocation.items():
        if channel not in CHANNELS or _f(pct) <= 0:
            continue
        a = assumptions.get(channel) or {}
        cpm, cpc, cr, vpc = _f(a.get("cpm")), _f(a.get("cpc")), _f(a.get("conversion_rate")), _f(a.get("value_per_conversion"))
        spend = round(budget * _f(pct) / 100, 2)
        if not cpc and not cpm:
            warnings.append(f"{CHANNELS[channel]}: sem CPM/CPC real nem informado; canal fora da projeção.")
            rows.append({"channel": channel, "spend": spend, "scenarios": {}, "missing": True})
            continue
        factor = saturation(spend, _f(a.get("monthly_spend")) or None)
        if factor < 1:
            warnings.append(f"{CHANNELS[channel]}: verba {round(spend / _f(a.get('monthly_spend')), 1)}x o ritmo dos últimos 90 dias; "
                            f"eficiência reduzida em {round((1 - factor) * 100)}%.")
        scenarios = {}
        for name, mult in SCENARIOS.items():
            eff = factor * mult
            impressions = spend / cpm * 1000 * eff if cpm else None
            clicks = spend / cpc * eff if cpc else (impressions * 0.01 if impressions else None)
            conversions = clicks * cr if clicks and cr else None
            revenue = conversions * vpc if conversions and vpc else None
            scenarios[name] = {
                "impressions": int(impressions) if impressions else None, "clicks": int(clicks) if clicks else None,
                "conversions": round(conversions, 1) if conversions else None, "revenue": round(revenue, 2) if revenue else None,
                "cpa": round(spend / conversions, 2) if conversions else None, "roas": round(revenue / spend, 2) if revenue else None,
            }
        rows.append({"channel": channel, "spend": spend, "pct": round(_f(pct), 1), "saturation": factor, "scenarios": scenarios})
    totals = {}
    for name in SCENARIOS:
        conv = sum(r["scenarios"].get(name, {}).get("conversions") or 0 for r in rows)
        rev = sum(r["scenarios"].get(name, {}).get("revenue") or 0 for r in rows)
        totals[name] = {"conversions": round(conv, 1), "revenue": round(rev, 2),
                        "cpa": round(budget / conv, 2) if conv else None, "roas": round(rev / budget, 2) if rev else None}
    return {"budget": round(budget, 2), "channels": rows, "totals": totals, "warnings": warnings,
            "method": ("impressões = verba ÷ CPM × 1000; cliques = verba ÷ CPC; conversões = cliques × taxa de conversão; "
                       "receita = conversões × valor por conversão. Cenários: 80% / 100% / 115% da eficiência real, "
                       "com retorno decrescente acima de 1,5x o investimento mensal habitual do canal.")}


# --------------------------------------------------------------------------
# Plano mensal e planejado x realizado
# --------------------------------------------------------------------------

def _clean_allocation(raw: Dict[str, Any]) -> Dict[str, float]:
    return {ch: round(max(0.0, min(100.0, _f(v))), 2) for ch, v in (raw or {}).items() if ch in CHANNELS}


def _clean_assumptions(raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for ch, values in (raw or {}).items():
        if ch in CHANNELS and isinstance(values, dict):
            out[ch] = {k: (round(_f(values.get(k)), 4) if values.get(k) not in (None, "") else None)
                       for k in ("cpm", "cpc", "conversion_rate", "value_per_conversion", "monthly_spend")}
    return out


async def get_plan(client_id: str, month: str) -> Optional[Dict[str, Any]]:
    target = parse_month(month)
    rows = await sb_select(PLANS, select="*", filters={"client_id": f"eq.{client_id}", "month": f"eq.{target.isoformat()}"}, limit=1)
    return rows[0] if rows else None


async def save_plan(client_id: str, month: str, data: Dict[str, Any], *, user_id: str) -> Dict[str, Any]:
    target = parse_month(month)
    if data.get("objective") not in OBJECTIVES:
        raise StudioError("OBJECTIVE_INVALID")
    allocation = _clean_allocation(data.get("allocation") or {})
    assumptions = _clean_assumptions(data.get("assumptions") or {})
    simulate(budget=_f(data.get("budget")), allocation=allocation, assumptions=assumptions)  # valida verba e soma 100%
    row = {"client_id": client_id, "month": target.isoformat(), "objective": data["objective"],
           "budget": round(_f(data.get("budget")), 2), "allocation": allocation, "assumptions": assumptions,
           "notes": (str(data.get("notes") or "").strip()[:2000] or None),
           "status": "aprovado" if data.get("status") == "aprovado" else "rascunho", "updated_by": user_id}
    existing = await get_plan(client_id, month)
    if not existing:
        row["created_by"] = user_id
    await sb_upsert(PLANS, [row], on_conflict="client_id,month")
    return await get_plan(client_id, month) or row


async def plan_vs_actual(client_id: str, month: str) -> Dict[str, Any]:
    target = parse_month(month)
    plan = await get_plan(client_id, month)
    today = datetime.now(SAO_PAULO).date()
    last_day = target.replace(day=calendar.monthrange(target.year, target.month)[1])
    end = min(last_day, today - timedelta(days=1))
    days_total = last_day.day
    if end < target:
        return {"month": target.isoformat(), "plan": plan, "elapsed_days": 0, "days_in_month": days_total, "channels": []}
    elapsed = (end - target).days + 1
    actual = await read_channels(client_id, target.isoformat(), end.isoformat())
    rows = []
    for channel, label in CHANNELS.items():
        planned_spend = round(_f((plan or {}).get("budget")) * _f(((plan or {}).get("allocation") or {}).get(channel)) / 100, 2) if plan else None
        real = actual.get(channel) or {}
        spent = _f(real.get("spend"))
        projected = round(spent / elapsed * days_total, 2) if elapsed else None
        rows.append({
            "channel": channel, "label": label, "planned_spend": planned_spend, "spent": round(spent, 2),
            "projected_spend": projected, "pace": round(projected / planned_spend, 2) if planned_spend and projected is not None else None,
            "expected_to_date": round(planned_spend * elapsed / days_total, 2) if planned_spend else None,
            "clicks": real.get("clicks"), "conversions": real.get("conversions"), "conversion_value": real.get("conversion_value"),
            "cpc": real.get("cpc"), "cpa": real.get("cpa"), "roas": real.get("roas"),
        })
    return {"month": target.isoformat(), "plan": plan, "elapsed_days": elapsed, "days_in_month": days_total,
            "through": end.isoformat(), "channels": rows}


# --------------------------------------------------------------------------
# Recomendação da IA (a partir do baseline e da inteligência da conta)
# --------------------------------------------------------------------------

async def recommend(client_id: str, *, month: str, budget: float, objective: str) -> Dict[str, Any]:
    from .studio_engines import throttle
    from .studio_intelligence import build_content_intelligence, to_prompt
    from .studio_llm import INT, STR, arr, llm_json, obj

    parse_month(month)
    if objective not in OBJECTIVES or budget <= 0:
        raise StudioError("OBJECTIVE_INVALID" if objective not in OBJECTIVES else "BUDGET_INVALID")
    base = await baseline(client_id)
    usable = {ch: m for ch, m in base["channels"].items() if m.get("confidence") in ("boa", "baixa")}
    if not usable:
        raise StudioError("NO_PAID_DATA")
    throttle(client_id)
    intel = await build_content_intelligence(client_id)
    schema = obj({"allocation": arr(obj({"channel": {"type": "string", "enum": list(usable)}, "pct": INT})),
                  "rationale": STR, "main_risk": STR, "next_steps": arr(STR)})
    data = await llm_json(
        instructions=("Você é o planejador de mídia paga da agência. Divide a verba entre canais com base no desempenho REAL "
                      "de cada canal (CPA, ROAS, taxa de conversão, confiança dos dados) e no objetivo. Justifique com os números."),
        prompt=(f"OBJETIVO: {OBJECTIVES[objective]}\nVERBA DO MÊS: R$ {budget:.2f}\nMÊS: {month}\n"
                f"DESEMPENHO DOS ÚLTIMOS 90 DIAS POR CANAL:\n{json.dumps(usable, ensure_ascii=False)}\n"
                f"CONTEXTO DA MARCA:\n{to_prompt(intel, sections=['negocio', 'kpis', 'metas_do_mes', 'campanhas_que_mais_venderam', 'ultima_analise'], limit=6000)}\n"
                "Regras: percentuais inteiros somando 100; só canais listados; se a confiança for 'baixa', limite o canal a 40% "
                "e diga por quê; next_steps com até 4 ações práticas."),
        schema_name="media_recommendation", schema=schema, temperature=0.3)
    allocation: Dict[str, float] = {}
    for row in data.get("allocation") or []:
        if row.get("channel") in usable:
            allocation[row["channel"]] = allocation.get(row["channel"], 0) + max(0, int(row.get("pct") or 0))
    total = sum(allocation.values())
    if not total:
        raise StudioError("AI_INVALID_OUTPUT")
    allocation = {ch: round(v * 100 / total, 1) for ch, v in allocation.items()}  # normaliza para 100%
    assumptions = default_assumptions(base["channels"])
    return {"allocation": allocation, "rationale": str(data.get("rationale") or "")[:1200],
            "main_risk": str(data.get("main_risk") or "")[:400], "next_steps": [str(s)[:200] for s in (data.get("next_steps") or [])[:4]],
            "simulation": simulate(budget=budget, allocation=allocation, assumptions=assumptions), "assumptions": assumptions}
