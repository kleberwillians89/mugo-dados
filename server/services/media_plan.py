"""Mídia On: plano mensal salvo e planejado x realizado.

A estratégia (diagnóstico, curvas, cenários, campanhas, calendário e
impulsionamento) é calculada em ``media_strategy``. Aqui o plano aprovado é
gravado com a estratégia congelada, e o realizado é lido na hora das tabelas de
mídia paga para mostrar o ritmo de cada canal.
"""
from __future__ import annotations

import calendar
import json
import httpx
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from .ig_supabase import _is_column_compat_error, sb_insert, sb_select, sb_upsert
from .studio_calendar import StudioError, parse_month

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
PLANS = "studio_media_plans"
HISTORY = "studio_media_strategies"
HISTORY_LIMIT = 15
CHANNELS = {"meta": "Meta Ads", "google_ads": "Google Ads"}
OBJECTIVES = ("vendas", "leads", "trafego", "alcance")
SCENARIOS = ("ritmo_atual", "meta", "eficiencia", "personalizado")
MAX_STRATEGY_BYTES = 300_000


def _f(value: Any) -> float:
    try:
        out = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return out if out == out else 0.0


def _ratio(a: float, b: float) -> Optional[float]:
    return round(a / b, 4) if b else None


def clean_allocation(raw: Dict[str, Any], budget: float) -> Dict[str, float]:
    """Divisão em reais por canal; precisa somar a verba (tolerância de 1%)."""
    alloc = {ch: round(max(0.0, _f(v)), 2) for ch, v in (raw or {}).items() if ch in CHANNELS}
    if budget <= 0:
        raise StudioError("BUDGET_INVALID")
    if not alloc or abs(sum(alloc.values()) - budget) > budget * 0.01:
        raise StudioError("ALLOCATION_INVALID")
    return alloc


async def get_plan(client_id: str, month: str) -> Optional[Dict[str, Any]]:
    target = parse_month(month)
    rows = await sb_select(PLANS, select="*", filters={"client_id": f"eq.{client_id}", "month": f"eq.{target.isoformat()}"}, limit=1)
    return rows[0] if rows else None


async def save_plan(client_id: str, month: str, data: Dict[str, Any], *, user_id: str) -> Dict[str, Any]:
    target = parse_month(month)
    if data.get("objective") not in OBJECTIVES:
        raise StudioError("OBJECTIVE_INVALID")
    if data.get("scenario") not in SCENARIOS:
        raise StudioError("SCENARIO_INVALID")
    budget = round(_f(data.get("budget")), 2)
    allocation = clean_allocation(data.get("allocation") or {}, budget)
    strategy = data.get("strategy") or {}
    if len(json.dumps(strategy, ensure_ascii=False, default=str)) > MAX_STRATEGY_BYTES:
        raise StudioError("STRATEGY_TOO_LARGE")
    margin = data.get("margin")
    row = {"client_id": client_id, "month": target.isoformat(), "objective": data["objective"], "budget": budget,
           "allocation": allocation, "assumptions": {}, "scenario": data["scenario"], "strategy": strategy,
           "margin": round(float(margin), 4) if margin else None,
           "notes": (str(data.get("notes") or "").strip()[:2000] or None),
           "status": "aprovado" if data.get("status") == "aprovado" else "rascunho", "updated_by": user_id}
    if not await get_plan(client_id, month):
        row["created_by"] = user_id
    try:
        await sb_upsert(PLANS, [row], on_conflict="client_id,month")
    except httpx.HTTPStatusError as exc:
        # Coluna/tabela ainda não existe: diz qual migration falta em vez de um erro genérico.
        if exc.response is not None and exc.response.status_code == 404:
            raise StudioError("MIGRATION_054_PENDING") from None
        if _is_column_compat_error(exc, "strategy"):
            raise StudioError("MIGRATION_055_PENDING") from None
        raise
    return await get_plan(client_id, month) or row


async def _actual(client_id: str, start: str, end: str) -> Dict[str, Dict[str, Any]]:
    from .media_strategy import READERS, totals
    out = {}
    for channel, reader in READERS.items():
        try:
            out[channel] = totals((await reader(client_id, start, end))["daily"])
        except Exception as exc:
            print(f"[media][actual] canal={channel} erro={exc.__class__.__name__}")
            out[channel] = totals([])
    return out


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
    actual = await _actual(client_id, target.isoformat(), end.isoformat())
    planned = (plan or {}).get("allocation") or {}
    # A estratégia salva guarda o cenário escolhido com a projeção por canal.
    projected_result = ((((plan or {}).get("strategy") or {}).get("scenario") or {}).get("result") or {}).get("channels") or {}
    rows = []
    for channel, label in CHANNELS.items():
        real = actual.get(channel) or {}
        planned_spend = _f(planned.get(channel)) or None
        spent = _f(real.get("spend"))
        if not planned_spend and not spent:
            continue
        projected = round(spent / elapsed * days_total, 2)
        expected = round(planned_spend * elapsed / days_total, 2) if planned_spend else None
        target_cpa = (projected_result.get(channel) or {}).get("cpa")
        target_roas = (projected_result.get(channel) or {}).get("roas")
        rows.append({
            "channel": channel, "label": label, "planned_spend": planned_spend, "spent": round(spent, 2),
            "expected_to_date": expected, "projected_spend": projected,
            "pace": _ratio(projected, planned_spend) if planned_spend else None,
            "conversions": real.get("conversions"), "revenue": real.get("revenue"), "cpa": real.get("cpa"), "roas": real.get("roas"),
            "target_cpa": target_cpa, "target_roas": target_roas,
        })
    return {"month": target.isoformat(), "plan": plan, "elapsed_days": elapsed, "days_in_month": days_total,
            "through": end.isoformat(), "channels": rows}


# --------------------------------------------------------------------------
# Histórico: cada estratégia gerada é gravada na hora
# --------------------------------------------------------------------------

def _selected(strategy: Dict[str, Any]) -> Dict[str, Any]:
    return next((s for s in strategy.get("scenarios") or [] if s.get("key") == strategy.get("selected")), {}) or {}


async def record_strategy(client_id: str, strategy: Dict[str, Any], *, objective: str, margin: Optional[float],
                          custom_budget: Optional[float], user_id: str) -> Dict[str, Any]:
    """Grava a estratégia gerada. Falha aqui não perde a estratégia da tela: volta como aviso."""
    chosen = _selected(strategy)
    row = {"client_id": client_id, "month": strategy["month"], "objective": objective, "margin": margin,
           "custom_budget": custom_budget, "selected": strategy.get("selected"), "budget": chosen.get("budget"),
           "headline": ((strategy.get("narrative") or {}).get("headline") or "")[:300] or None,
           "strategy": strategy, "created_by": user_id}
    if len(json.dumps(strategy, ensure_ascii=False, default=str)) > MAX_STRATEGY_BYTES:
        return {"saved": False, "reason": "STRATEGY_TOO_LARGE"}
    try:
        saved = await sb_insert(HISTORY, row)
    except httpx.HTTPStatusError as exc:
        missing = exc.response is not None and exc.response.status_code == 404
        print(f"[media][history] gravar_falhou status={getattr(exc.response, 'status_code', '-')}")
        return {"saved": False, "reason": "MIGRATION_056_PENDING" if missing else "HISTORY_SAVE_FAILED"}
    return {"saved": True, "id": (saved or {}).get("id"), "created_at": (saved or {}).get("created_at")}


async def list_strategies(client_id: str, month: str) -> list:
    target = parse_month(month)
    try:
        return await sb_select(HISTORY, select="id,month,objective,margin,custom_budget,selected,budget,headline,created_at",
                               filters={"client_id": f"eq.{client_id}", "month": f"eq.{target.isoformat()}"},
                               order="created_at.desc", limit=HISTORY_LIMIT)
    except httpx.HTTPStatusError:
        return []  # migration 056 ainda não aplicada: sem histórico, a página segue com o plano salvo


async def get_strategy(client_id: str, strategy_id: str) -> Dict[str, Any]:
    rows = await sb_select(HISTORY, select="id,objective,margin,custom_budget,strategy,created_at",
                           filters={"client_id": f"eq.{client_id}", "id": f"eq.{strategy_id}"}, limit=1)
    if not rows:
        raise StudioError("STRATEGY_NOT_FOUND")
    row = rows[0]
    return {**(row.get("strategy") or {}), "strategy_id": row["id"], "generated_at": row["created_at"],
            "margin": row.get("margin"), "custom_budget": row.get("custom_budget")}
