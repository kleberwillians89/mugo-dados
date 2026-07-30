from __future__ import annotations
import os
from datetime import datetime, timezone, date
from typing import Any, Dict, List, Optional, Tuple
import re

from .ig_supabase import sb_get_many

DEFAULT_CLIENT_ID = (os.getenv("DEFAULT_CLIENT_ID") or "").strip()

def _ym(d: str) -> str:
    # d = 'YYYY-MM-DD'
    return d[:7]

def _safe_int(x: Any) -> int:
    try:
        if x is None:
            return 0
        return int(float(x))
    except Exception:
        return 0

def _pct(curr: int, prev: int) -> float:
    if prev <= 0:
        return 100.0 if curr > 0 else 0.0
    return round(((curr - prev) / prev) * 100.0, 1)

async def get_dashboard(client_id: Optional[str], days: int = 30) -> Dict[str, Any]:
    cid = client_id or DEFAULT_CLIENT_ID
    if not cid:
        raise RuntimeError("DEFAULT_CLIENT_ID não configurado")

    # pega 2 períodos para calcular delta (ex: 30 dias atual vs 30 dias anterior)
    total_days = max(2, min(180, days * 2))

    # snapshots: ordena desc e limita (Supabase REST: order=...&limit=...)
    rows = await sb_get_many(
        "ig_profile_snapshots",
        f"client_id=eq.{cid}&select=*&order=snapshot_date.desc&limit={total_days}"
    )

    # normaliza e ordena asc
    snaps = sorted(rows, key=lambda r: r["snapshot_date"])

    # separa períodos
    curr = snaps[-days:] if len(snaps) >= days else snaps
    prev = snaps[-(days*2):-days] if len(snaps) >= (days*2) else []

    def sum_metric(items: List[Dict[str, Any]], key: str) -> int:
        return sum(_safe_int(i.get(key)) for i in items)

    # métricas diárias (essas colunas você já salva)
    METRICS = {
        "views": None,  # se você quiser “views” do perfil, precisa salvar no snapshot (hoje não tem)
        "reach_day": "reach",
        "profile_views_day": "profile_views",
        "website_clicks_day": "website_clicks",
        "accounts_engaged_day": "accounts_engaged",
        "total_interactions_day": "total_interactions",
    }

    # série diária para os gráficos
    daily = []
    for s in curr:
        daily.append({
            "date": s["snapshot_date"],
            "reach": _safe_int(s.get("reach_day")),
            "profile_views": _safe_int(s.get("profile_views_day")),
            "website_clicks": _safe_int(s.get("website_clicks_day")),
            "accounts_engaged": _safe_int(s.get("accounts_engaged_day")),
            "total_interactions": _safe_int(s.get("total_interactions_day")),
            "followers_count": _safe_int(s.get("followers_count")),
            "profile_visits": _safe_int(s.get("profile_views_day")),  # se quiser renomear no front
        })

    # totals + delta vs período anterior
    cards = {
        "reach": {
            "total": sum_metric(curr, "reach_day"),
            "prev": sum_metric(prev, "reach_day"),
        },
        "profile_views": {
            "total": sum_metric(curr, "profile_views_day"),
            "prev": sum_metric(prev, "profile_views_day"),
        },
        "website_clicks": {
            "total": sum_metric(curr, "website_clicks_day"),
            "prev": sum_metric(prev, "website_clicks_day"),
        },
        "accounts_engaged": {
            "total": sum_metric(curr, "accounts_engaged_day"),
            "prev": sum_metric(prev, "accounts_engaged_day"),
        },
        "total_interactions": {
            "total": sum_metric(curr, "total_interactions_day"),
            "prev": sum_metric(prev, "total_interactions_day"),
        },
        # followers: aqui faz sentido usar diferença (último - primeiro) no período
        "followers": {
            "total": (_safe_int(curr[-1].get("followers_count")) if curr else 0),
            "prev": (_safe_int(prev[-1].get("followers_count")) if prev else 0),
            "net": (_safe_int(curr[-1].get("followers_count")) - _safe_int(curr[0].get("followers_count"))) if len(curr) >= 2 else 0,
            "prev_net": (_safe_int(prev[-1].get("followers_count")) - _safe_int(prev[0].get("followers_count"))) if len(prev) >= 2 else 0,
        }
    }

    # percentuais
    for k, v in cards.items():
        if k == "followers":
            v["pct"] = _pct(_safe_int(v.get("net")), _safe_int(v.get("prev_net")))
        else:
            v["pct"] = _pct(_safe_int(v.get("total")), _safe_int(v.get("prev")))

    # monthly aggregation (a partir dos snapshots)
    monthly_map: Dict[str, Dict[str, int]] = {}
    for s in snaps:
        m = _ym(s["snapshot_date"])
        monthly_map.setdefault(m, {
            "reach": 0, "profile_views": 0, "website_clicks": 0,
            "accounts_engaged": 0, "total_interactions": 0,
        })
        monthly_map[m]["reach"] += _safe_int(s.get("reach_day"))
        monthly_map[m]["profile_views"] += _safe_int(s.get("profile_views_day"))
        monthly_map[m]["website_clicks"] += _safe_int(s.get("website_clicks_day"))
        monthly_map[m]["accounts_engaged"] += _safe_int(s.get("accounts_engaged_day"))
        monthly_map[m]["total_interactions"] += _safe_int(s.get("total_interactions_day"))

    months_sorted = sorted(monthly_map.keys())
    monthly = [{"month": m, **monthly_map[m]} for m in months_sorted]

    # delta mensal (último mês vs anterior)
    monthly_delta = None
    if len(monthly) >= 2:
        a = monthly[-2]
        b = monthly[-1]
        monthly_delta = {
            "monthA": a["month"],
            "monthB": b["month"],
            "reach_pct": _pct(b["reach"], a["reach"]),
            "views_pct": _pct(b["profile_views"], a["profile_views"]),
            "interactions_pct": _pct(b["total_interactions"], a["total_interactions"]),
        }

    return {
        "ok": True,
        "days": days,
        "cards": cards,
        "daily": daily,
        "monthly": monthly,
        "monthly_delta": monthly_delta,
    }