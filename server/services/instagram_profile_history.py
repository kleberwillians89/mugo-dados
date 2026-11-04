"""KPIs diários do perfil do Instagram para os dias que ainda não têm snapshot.

O sync grava `ig_profile_snapshots` só para o dia em que roda. Conta recém-conectada ficava com
1 dia de alcance/visitas/interações no período e a tela parecia "não atualizada".

Aqui, para cada dia sem snapshot nos últimos N dias (padrão 30), uma leitura da Meta com
`metric_type=total_value` e `since/until` daquele dia. Regras:
- Só cria dia que não existe: nunca sobrescreve o snapshot gravado pelo sync.
- Seguidores por dia não existem na API: o dia histórico leva o total atual e registra
  `followers_count` em `metrics_unavailable` (crescimento do período anterior à conexão fica 0, nunca inventado).
- Dia que a Meta recusar (fora da janela dela, permissão) fica sem linha.
- Mesmo lock do sync orgânico; poucas leituras em paralelo.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

from .ig_meta import _clean_token, fetch_profile, meta_get_json
from .ig_supabase import sb_select, sb_upsert

METRICS = ("reach", "profile_views", "website_clicks", "accounts_engaged", "total_interactions", "views")
DEFAULT_DAYS = 30
CONCURRENCY = 4


def _bounds(day: date) -> Dict[str, int]:
    start = datetime.combine(day, time.min, timezone.utc)
    return {"since": int(start.timestamp()), "until": int((start + timedelta(days=1)).timestamp())}


async def fetch_day(ig_user_id: str, token: str, day: date) -> Optional[Dict[str, int]]:
    try:
        data = await meta_get_json(f"/{ig_user_id}/insights", {
            "metric": ",".join(METRICS), "period": "day", "metric_type": "total_value",
            **_bounds(day), "access_token": _clean_token(token),
        })
    except Exception:  # noqa: BLE001 — dia fora da janela da Meta ou métrica indisponível
        return None
    out: Dict[str, int] = {}
    for item in data.get("data") or []:
        value = (item.get("total_value") or {}).get("value")
        if item.get("name") and value is not None:
            out[str(item["name"])] = int(value or 0)
    return out or None


def snapshot_row(client_id: str, connection_id: str, day: date, kpis: Dict[str, int], profile: Dict[str, Any]) -> Dict[str, Any]:
    available = sorted(kpis)
    return {
        "client_id": client_id, "connection_id": connection_id, "snapshot_date": day.isoformat(),
        "followers_count": int(profile.get("followers_count") or 0), "media_count": int(profile.get("media_count") or 0),
        "impressions_day": int(kpis.get("views") or 0), "reach_day": int(kpis.get("reach") or 0),
        "total_interactions_day": int(kpis.get("total_interactions") or 0),
        "website_clicks_day": int(kpis.get("website_clicks") or 0),
        "profile_views_day": int(kpis.get("profile_views") or 0),
        "accounts_engaged_day": int(kpis.get("accounts_engaged") or 0),
        "metrics_available": available,
        "metrics_unavailable": sorted(set(METRICS) - set(available)) + ["followers_count"],
    }


async def backfill_profile_days(client_id: str, connection_id: str, ig_user_id: str, token: str, *,
                                days: int = DEFAULT_DAYS, today: Optional[date] = None) -> Dict[str, int]:
    today = today or datetime.now(timezone.utc).date()
    wanted = [today - timedelta(days=offset) for offset in range(1, max(1, days) + 1)]
    existing = await sb_select("ig_profile_snapshots", select="snapshot_date", limit=500, filters={
        "client_id": f"eq.{client_id}", "snapshot_date": f"gte.{wanted[-1].isoformat()}"})
    have = {str(r.get("snapshot_date"))[:10] for r in existing}
    missing = [d for d in wanted if d.isoformat() not in have]
    if not missing:
        return {"missing": 0, "written": 0, "refused": 0}
    profile = await fetch_profile(ig_user_id, token)
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def one(day: date):
        async with semaphore:
            return day, await fetch_day(ig_user_id, token, day)

    results = await asyncio.gather(*(one(d) for d in missing))
    rows = [snapshot_row(client_id, connection_id, day, kpis, profile) for day, kpis in results if kpis]
    if rows:
        # Só dias ausentes (lidos acima); o conflito por client_id+data nunca pega o dia do sync.
        await sb_upsert("ig_profile_snapshots", rows, on_conflict="client_id,snapshot_date")
    return {"missing": len(missing), "written": len(rows), "refused": len(missing) - len(rows)}


async def backfill_connection(connection_id: str, *, days: int = DEFAULT_DAYS) -> Dict[str, Any]:
    from .dashboard_read_model import refresh_dashboard_read_model_safely
    from .meta_tokens import ensure_valid_meta_token
    from .sync_locks import guarded_sync

    rows = await sb_select("meta_connections", select="id,client_id,ig_user_id,status,platform,connection_type", limit=1,
                           filters={"id": f"eq.{connection_id}", "platform": "eq.instagram", "connection_type": "eq.organic"})
    conn = rows[0] if rows else {}
    client_id, ig_user_id = str(conn.get("client_id") or ""), str(conn.get("ig_user_id") or "")
    if not client_id or not ig_user_id:
        return {"status": "skipped", "reason": "sem_instagram"}
    async with guarded_sync(client_id=client_id, provider="meta_organic", connection_id=connection_id, ttl_seconds=900):
        token = await ensure_valid_meta_token(client_id, connection_id=connection_id, platform="instagram",
                                              connection_type="organic", persisted_only=True)
        result = await backfill_profile_days(client_id, connection_id, ig_user_id, token, days=days)
    if result["written"]:
        today = datetime.now(timezone.utc).date()
        await refresh_dashboard_read_model_safely(client_id=client_id, start=(today - timedelta(days=days)).isoformat(),
                                                  end=today.isoformat(), provider="instagram")
    return {"status": "ok", "client_id": client_id, **result}


async def backfill_all(*, days: int = DEFAULT_DAYS) -> Dict[str, Any]:
    conns = await sb_select("meta_connections", select="id,client_id", limit=500, filters={
        "platform": "eq.instagram", "connection_type": "eq.organic", "status": "eq.active"})
    totals: Dict[str, Any] = {"connections": len(conns), "written": 0, "failed": 0}
    for conn in conns:
        try:
            out = await backfill_connection(str(conn["id"]), days=days)
            totals["written"] += int(out.get("written") or 0)
        except Exception as exc:  # noqa: BLE001 — uma marca não para as outras
            totals["failed"] += 1
            print(f"[ig_profile_history] client_id={conn.get('client_id')} failed={getattr(exc, 'code', type(exc).__name__)}")
    return totals
