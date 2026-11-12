"""CAC, LTV e coortes, a partir da jornada (pessoa unificada) e do gasto em mídia (Meta + Google) por mês.

Definições (as mesmas que a tela mostra):
- Cliente novo do mês = pessoa cuja primeira compra válida, dentro da janela da jornada (13 meses), caiu no mês.
- CAC do mês = gasto Meta + Google do mês ÷ clientes novos do mês (mídia paga inteira dividida por todos os novos:
  é o CAC "misturado", o único honesto sem atribuição por pessoa).
- LTV N dias = receita média por cliente nos N dias depois da primeira compra, só de quem já completou os N dias.
- Coorte = clientes novos de um mês; retenção do mês M+k = % da coorte que comprou de novo naquele mês.
- Margem (opcional, 0–100%) transforma LTV de receita em LTV de margem para o LTV:CAC e o payback.

Limite conhecido: quem comprou antes da janela da jornada aparece como "novo" nos primeiros meses. Por isso a
tela mostra só os últimos 12 meses (o mês mais antigo da janela fica de colchão) e avisa.
"""
from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .ig_supabase import sb_select

MONTHS = 12
LTV_WINDOWS = (30, 90, 180, 365)


def _dt(value: Any) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _month(d: datetime | date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _shift(month: str, k: int) -> str:
    y, m = int(month[:4]), int(month[5:7]) - 1 + k
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


def _diff(a: str, b: str) -> int:
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


def compute(purchases: Iterable[Tuple[str, datetime, float]], spend: Dict[str, float], *, now: datetime,
            margin: Optional[float] = None, months: int = MONTHS) -> Dict[str, Any]:
    """Função pura. ``purchases`` = (pessoa, quando, valor) de compras válidas; ``spend`` = gasto por mês 'AAAA-MM'."""
    by_person: Dict[str, List[Tuple[datetime, float]]] = {}
    for person, at, value in purchases:
        by_person.setdefault(person, []).append((at, float(value or 0)))
    for items in by_person.values():
        items.sort(key=lambda x: x[0])
    current = _month(now)
    window = [_shift(current, -k) for k in range(months - 1, -1, -1)]
    factor = (margin / 100) if margin else 1.0

    monthly = {m: {"month": m, "new": 0, "returning": 0, "revenue_new": 0.0, "revenue_returning": 0.0, "spend": round(spend.get(m, 0.0), 2)}
               for m in window}
    cohorts: Dict[str, Dict[str, Any]] = {}
    gaps: List[int] = []
    repeaters = 0
    ltv_sum = {n: 0.0 for n in LTV_WINDOWS}
    ltv_n = {n: 0 for n in LTV_WINDOWS}
    for person, items in by_person.items():
        first_at = items[0][0]
        first_month = _month(first_at)
        if len(items) > 1:
            repeaters += 1
            gaps.append((items[1][0] - first_at).days)
        seen_months = set()
        for at, value in items:
            m = _month(at)
            if m in monthly:
                if m == first_month and m not in seen_months:
                    monthly[m]["new"] += 1
                elif m != first_month and m not in seen_months:
                    monthly[m]["returning"] += 1
                monthly[m]["revenue_new" if m == first_month else "revenue_returning"] += value
            seen_months.add(m)
        for n in LTV_WINDOWS:
            if now - first_at >= timedelta(days=n):
                ltv_n[n] += 1
                ltv_sum[n] += sum(v for at, v in items if at - first_at <= timedelta(days=n))
        if first_month in monthly:
            cohort = cohorts.setdefault(first_month, {"month": first_month, "size": 0, "active": [0] * months, "revenue": [0.0] * months})
            cohort["size"] += 1
            active_k = set()
            for at, value in items:
                k = _diff(first_month, _month(at))
                if 0 <= k < months:
                    cohort["revenue"][k] += value
                    active_k.add(k)
            for k in active_k:
                cohort["active"][k] += 1

    rows = []
    for m in window:
        r = monthly[m]
        r["revenue_new"] = round(r["revenue_new"], 2)
        r["revenue_returning"] = round(r["revenue_returning"], 2)
        r["cac"] = round(r["spend"] / r["new"], 2) if r["new"] and r["spend"] else None
        rows.append(r)
    cohort_rows = []
    for m in window:
        c = cohorts.get(m)
        if not c:
            continue
        age = _diff(m, current)
        cum, ltv_curve, retention = 0.0, [], []
        for k in range(min(age, months - 1) + 1):
            cum += c["revenue"][k]
            ltv_curve.append(round(cum / c["size"], 2))
            retention.append(round(c["active"][k] / c["size"] * 100, 1))
        cohort_rows.append({"month": m, "size": c["size"], "retention": retention, "ltv": ltv_curve,
                            "cac": monthly[m]["cac"]})

    ltv = {str(n): round(ltv_sum[n] / ltv_n[n], 2) if ltv_n[n] else None for n in LTV_WINDOWS}
    recent = [r for r in rows[-6:] if r["cac"] is not None]
    spend6 = sum(r["spend"] for r in rows[-6:])
    new6 = sum(r["new"] for r in rows[-6:])
    cac6 = round(spend6 / new6, 2) if new6 and spend6 else None
    ltv180 = ltv["180"]
    ratio = round(ltv180 * factor / cac6, 2) if ltv180 and cac6 else None
    payback = None
    if cac6:
        curves = [c["ltv"] for c in cohort_rows if c["size"] >= 10]
        for k in range(months):
            points = [curve[k] for curve in curves if len(curve) > k]
            if len(points) >= 2 and statistics.mean(points) * factor >= cac6:
                payback = k
                break
    customers = len(by_person)
    return {
        "months": rows, "cohorts": cohort_rows, "ltv": ltv, "ltv_basis": "margem" if margin else "receita", "margin": margin,
        "summary": {"customers": customers, "repeat_rate": round(repeaters / customers * 100, 1) if customers else None,
                    "median_days_to_second": int(statistics.median(gaps)) if gaps else None, "cac_6m": cac6, "ltv_cac": ratio,
                    "payback_months": payback, "months_with_cac": len(recent)},
    }


async def _spend_by_month(client_id: str, since: date) -> Dict[str, float]:
    rows = await sb_select("dashboard_daily_metrics", select="metric_date,meta_spend,google_ads_spend",
                           filters={"client_id": f"eq.{client_id}", "metric_date": f"gte.{since.isoformat()}"}, order="metric_date.asc", limit=1000)
    out: Dict[str, float] = {}
    for r in rows:
        m = str(r.get("metric_date") or "")[:7]
        if len(m) == 7:
            out[m] = out.get(m, 0.0) + float(r.get("meta_spend") or 0) + float(r.get("google_ads_spend") or 0)
    return out


async def overview(client_id: str, *, margin: Optional[float] = None) -> Dict[str, Any]:
    from .sales_by_origin import _paged
    runs = await sb_select("customer_journey_runs", select="built_at,stats", filters={"client_id": f"eq.{client_id}"}, limit=1)
    if not runs:
        return {"status": "not_built"}
    now = datetime.now(timezone.utc)
    events, truncated = await _paged("customer_events", select="person_id,at,value",
                                     filters={"client_id": f"eq.{client_id}", "kind": "in.(pedido,recompra)"}, order="at.asc", max_rows=200_000)
    purchases = [(e["person_id"], _dt(e["at"]), float(e.get("value") or 0)) for e in events if _dt(e.get("at"))]
    window_start = min((p[1] for p in purchases), default=now)
    spend = await _spend_by_month(client_id, (now - timedelta(days=31 * MONTHS + 31)).date())
    result = compute(purchases, spend, now=now, margin=margin)
    return {"status": "ok", "built_at": runs[0]["built_at"], "data_since": window_start.isoformat(), "truncated": truncated,
            "has_spend": any(v > 0 for v in spend.values()), **result}
