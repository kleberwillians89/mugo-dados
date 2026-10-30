"""Aprendizado contínuo por campanha (Meta Ads e Google Ads).

Toda sexta o job ``studio-weekly-digest`` tira uma foto da semana de cada
campanha e grava em ``studio_campaign_learnings``:

* desempenho da semana e média do canal;
* o que o Mídia On recomendaria hoje (mesma régua da estratégia);
* o que a equipe planejou para a campanha no plano do mês (ação e verba);
* quando a campanha apareceu pela primeira vez (campanha nova é sinalizada);
* uma nota do que mudou em relação à semana anterior.

O Mídia On lê essa linha do tempo para ajustar as recomendações: campanha nova
ainda aprendendo, ROAS caindo há semanas, escala que funcionou, campanha que
parou. É a mesma base do resumo semanal enviado ao cliente pelo WhatsApp.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from .ig_supabase import sb_select, sb_upsert

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
TABLE = "studio_campaign_learnings"
HISTORY_WEEKS = 8
NEW_CAMPAIGN_DAYS = 21
MIN_WEEK_SPEND = 20.0


def _f(value: Any) -> float:
    try:
        out = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return out if out == out else 0.0


def week_bounds(today: Optional[date] = None) -> tuple[date, date]:
    """Os 7 dias fechados até ontem (na sexta: sexta passada a quinta)."""
    today = today or datetime.now(SAO_PAULO).date()
    end = today - timedelta(days=1)
    return end - timedelta(days=6), end


def _key(row: Dict[str, Any]) -> str:
    return str(row.get("campaign_id") or row.get("campaign_name") or "").strip()[:200]


def _pct(now: Optional[float], before: Optional[float]) -> Optional[float]:
    if now is None or not before:
        return None
    return round((now - before) / abs(before) * 100, 1)


def week_note(row: Dict[str, Any], previous: Optional[Dict[str, Any]], metric: str, today: date) -> Optional[str]:
    """O que mudou na campanha em relação à semana anterior, em uma frase."""
    first_seen = date.fromisoformat(str(row["first_seen"])[:10])
    if (today - first_seen).days <= NEW_CAMPAIGN_DAYS and not previous:
        return f"Campanha nova (desde {first_seen.strftime('%d/%m')}): {row['conversions']:.0f} conversões na primeira semana."
    if not previous:
        return None
    if row["spend"] < MIN_WEEK_SPEND <= _f(previous.get("spend")):
        return "Parou de investir nesta semana."
    spend_change = _pct(row["spend"], _f(previous.get("spend")))
    if metric == "revenue":
        change = _pct(row.get("roas"), previous.get("roas") and _f(previous["roas"]))
        good, bad, unit = (change or 0) >= 20, (change or 0) <= -20, "ROAS"
    else:
        change = _pct(row.get("cpa"), previous.get("cpa") and _f(previous["cpa"]))
        good, bad, unit = (change or 0) <= -20, (change or 0) >= 20, "CPA"
    if change is None:
        return None
    if bad and (spend_change or 0) >= 20:
        return f"Verba subiu {spend_change:.0f}% e o {unit} piorou {abs(change):.0f}%: sinal de saturação."
    if bad:
        return f"{unit} piorou {abs(change):.0f}% na semana."
    if good:
        return f"{unit} melhorou {abs(change):.0f}% na semana" + (f" com {spend_change:+.0f}% de verba." if spend_change else ".")
    return None


async def _planned(client_id: str, month: date) -> Dict[str, Dict[str, Any]]:
    try:
        rows = await sb_select("studio_media_plans", select="strategy", limit=1,
                               filters={"client_id": f"eq.{client_id}", "month": f"eq.{month.isoformat()}"})
    except Exception:
        return {}
    campaigns = ((rows[0].get("strategy") or {}).get("campaigns") or []) if rows else []
    return {c["campaign"]: c for c in campaigns if c.get("campaign")}


async def _previous(client_id: str, week_start: date) -> Dict[tuple, Dict[str, Any]]:
    rows = await sb_select(TABLE, select="channel,campaign_key,first_seen,spend,roas,cpa,week_start", limit=2000,
                           filters={"client_id": f"eq.{client_id}", "week_start": f"lt.{week_start.isoformat()}"},
                           order="week_start.desc")
    first: Dict[tuple, str] = {}
    last: Dict[tuple, Dict[str, Any]] = {}
    for r in rows:
        k = (r["channel"], r["campaign_key"])
        first[k] = min(first.get(k, str(r["first_seen"])), str(r["first_seen"]))
        last.setdefault(k, r)
    return {k: {**v, "first_seen": first[k]} for k, v in last.items()}


async def snapshot_week(client_id: str, *, today: Optional[date] = None) -> Dict[str, Any]:
    """Grava a semana de cada campanha e devolve o resumo usado no WhatsApp."""
    from .media_strategy import CHANNELS, READERS, classify_campaigns, totals

    today = today or datetime.now(SAO_PAULO).date()
    start, end = week_bounds(today)
    planned = await _planned(client_id, end.replace(day=1))
    try:
        previous = await _previous(client_id, start)
    except Exception:
        previous = {}
    rows, channels = [], {}
    for channel, reader in READERS.items():
        try:
            data = await reader(client_id, start.isoformat(), end.isoformat())
        except Exception as exc:
            print(f"[learning] canal={channel} erro={exc.__class__.__name__}")
            continue
        week = totals(data.get("daily") or [])
        if week["spend"] <= 0:
            continue
        metric = "revenue" if week["revenue"] / week["spend"] >= 0.2 else "conversions"
        channels[channel] = {**week, "label": CHANNELS[channel], "metric": metric}
        recommended = {r["campaign"]: r for r in classify_campaigns(channel, data.get("campaigns") or [], week, metric)}
        for c in data.get("campaigns") or []:
            key, name = _key(c), str(c.get("campaign_name") or c.get("campaign_id") or "Campanha")[:200]
            spend = _f(c.get("spend"))
            prev = previous.get((channel, key))
            if not key or (spend < MIN_WEEK_SPEND and not prev):
                continue
            conv, rev = _f(c.get("conversions")), _f(c.get("revenue"))
            plan = planned.get(name) or {}
            row = {"client_id": client_id, "channel": channel, "campaign_key": key, "campaign_name": name,
                   "week_start": start.isoformat(), "week_end": end.isoformat(),
                   "first_seen": (prev or {}).get("first_seen") or start.isoformat(),
                   "spend": round(spend, 2), "impressions": round(_f(c.get("impressions"))), "clicks": round(_f(c.get("clicks"))),
                   "conversions": round(conv, 2), "revenue": round(rev, 2),
                   "roas": round(rev / spend, 4) if spend else None, "cpa": round(spend / conv, 4) if conv else None,
                   "channel_roas": week.get("roas"), "channel_cpa": week.get("cpa"),
                   "recommended_action": (recommended.get(name) or {}).get("action"),
                   "planned_action": plan.get("action"), "planned_budget": plan.get("planned_budget")}
            row["note"] = week_note(row, prev, metric, today)
            rows.append(row)
    if rows:
        await sb_upsert(TABLE, rows, on_conflict="client_id,channel,campaign_key,week_start")
    return {"client_id": client_id, "week": {"start": start.isoformat(), "end": end.isoformat()}, "channels": channels,
            "campaigns": rows, "new": [r for r in rows if r["note"] and r["note"].startswith("Campanha nova")],
            "notes": [f"{r['campaign_name']}: {r['note']}" for r in rows if r["note"]]}


async def campaign_history(client_id: str, weeks: int = HISTORY_WEEKS) -> Dict[str, List[Dict[str, Any]]]:
    """{nome da campanha: semanas mais recentes primeiro} para o Mídia On aprender."""
    since = (datetime.now(SAO_PAULO).date() - timedelta(days=7 * weeks)).isoformat()
    try:
        rows = await sb_select(TABLE, select="channel,campaign_name,week_start,first_seen,spend,conversions,roas,cpa,planned_action,recommended_action",
                               filters={"client_id": f"eq.{client_id}", "week_start": f"gte.{since}"}, order="week_start.desc", limit=3000)
    except Exception:
        return {}
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(r["campaign_name"], []).append(r)
    return out


def trend_note(history: List[Dict[str, Any]], metric: str, today: date) -> Optional[Dict[str, Any]]:
    """Leitura de várias semanas: campanha nova, queda ou alta consistente."""
    if not history:
        return None
    first_seen = date.fromisoformat(str(history[-1]["first_seen"])[:10])
    if (today - first_seen).days <= NEW_CAMPAIGN_DAYS:
        conv = sum(_f(h.get("conversions")) for h in history)
        return {"kind": "nova", "text": f"Campanha nova (desde {first_seen.strftime('%d/%m')}): {conv:.0f} conversões até agora; ainda em aprendizado."}
    key = "roas" if metric == "revenue" else "cpa"
    values = [_f(h.get(key)) for h in history[:3] if h.get(key) is not None]
    if len(values) == 3:
        falling = values[0] < values[1] < values[2] if key == "roas" else values[0] > values[1] > values[2]
        rising = values[0] > values[1] > values[2] if key == "roas" else values[0] < values[1] < values[2]
        unit = "ROAS" if key == "roas" else "CPA"
        if falling:
            return {"kind": "queda", "text": f"{unit} piorando há 3 semanas seguidas."}
        if rising:
            return {"kind": "alta", "text": f"{unit} melhorando há 3 semanas seguidas."}
    return None
