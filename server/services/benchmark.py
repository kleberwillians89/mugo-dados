"""Benchmarking no Instagram: a marca contra os concorrentes, só com dado público.

A Meta deixa uma conta profissional ler o perfil público de outra conta profissional (Business Discovery):
seguidores, total de posts e os posts recentes com curtidas e comentários. É o mesmo caminho do módulo
Criadores. Com isso o MUGOVERSO compara, no mesmo critério para todos:

- ritmo: posts por semana no período;
- interações médias por post (curtidas + comentários);
- taxa de engajamento: interações médias ÷ seguidores;
- share de atenção: fatia das interações do período que foi para a marca, contra os concorrentes
  (a ideia do "Share of Attention" da Winnin, restrita ao que a API pública entrega).

Limites honestos: a Meta devolve só os posts mais recentes (até 50 por perfil); se o mais antigo da amostra
ainda está dentro do período, os números do período são o mínimo e a tela avisa ("amostra"). Conta pessoal ou
que ocultou curtidas não entra com número inventado: fica sem dado. Visualizações de concorrente não existem
nessa API e não são estimadas.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_select, sb_upsert

SNAPSHOTS = "benchmark_ig_snapshots"
POSTS_PER_PROFILE = 30
REFRESH_COOLDOWN = timedelta(hours=6)
PARALLEL = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00").replace("+0000", "+00:00"))
    except (TypeError, ValueError):
        return None


def _handle(value: Any) -> str:
    return str(value or "").strip().lstrip("@").lower()


def _interactions(post: Dict[str, Any]) -> Optional[int]:
    likes, comments = post.get("likes"), post.get("comments")
    if likes is None and comments is None:
        return None
    return int(likes or 0) + int(comments or 0)


def ig_metrics(snapshot: Dict[str, Any], *, days: int, now: datetime) -> Dict[str, Any]:
    """Números de um perfil no período, a partir da amostra pública de posts."""
    since = now - timedelta(days=days)
    posts = [p for p in snapshot.get("posts") or [] if _ts(p.get("timestamp"))]
    posts.sort(key=lambda p: _ts(p["timestamp"]), reverse=True)
    window = [p for p in posts if _ts(p["timestamp"]) >= since]
    counted = [i for i in (_interactions(p) for p in posts) if i is not None]
    in_window = [i for i in (_interactions(p) for p in window) if i is not None]
    followers = snapshot.get("followers")
    avg = round(sum(counted) / len(counted), 1) if counted else None
    oldest = _ts(posts[-1]["timestamp"]) if posts else None
    hidden = sum(1 for p in posts if p.get("likes") is None)
    top = max(window, key=lambda p: _interactions(p) or 0, default=None)
    return {
        "handle": snapshot.get("handle"),
        "is_brand": bool(snapshot.get("is_brand")),
        "competitor_id": snapshot.get("competitor_id"),
        "followers": followers,
        "posts_in_period": len(window),
        "posts_per_week": round(len(window) / (days / 7), 1),
        "avg_interactions": avg,
        "engagement_rate": round(avg / followers * 100, 2) if avg is not None and followers else None,
        "interactions_in_period": sum(in_window) if in_window else 0,
        # A amostra não cobre o período inteiro: os números do período são o mínimo.
        "sampled": bool(posts) and len(posts) >= POSTS_PER_PROFILE and oldest is not None and oldest >= since,
        "hidden_likes": hidden,
        "top_post": ({"url": top.get("url"), "interactions": _interactions(top), "type": top.get("type")} if top else None),
        "collected_at": snapshot.get("collected_at"),
    }


def with_share(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Share de atenção: fatia das interações do período de cada perfil no total (marca + concorrentes)."""
    total = sum(int(r.get("interactions_in_period") or 0) for r in rows)
    for r in rows:
        r["share"] = round(int(r.get("interactions_in_period") or 0) / total * 100, 1) if total else None
    rows.sort(key=lambda r: (not r["is_brand"], -(r["share"] or 0)))
    return rows


async def latest_snapshots(client_id: str) -> List[Dict[str, Any]]:
    rows = await sb_select(SNAPSHOTS, select="*", filters={"client_id": f"eq.{client_id}"}, order="collected_at.desc", limit=200)
    seen, out = set(), []
    for r in rows:
        key = str(r.get("handle") or "").lower()
        if key and key not in seen:
            seen.add(key)
            out.append(r)
    return out


async def instagram_block(client_id: str, competitors: List[Dict[str, Any]], *, days: int) -> Dict[str, Any]:
    """Comparativo pronto para a tela: só a marca e os concorrentes ativos com @ cadastrado."""
    try:
        snaps = await latest_snapshots(client_id)
    except Exception as exc:  # noqa: BLE001 — tabela da 000106 ainda não aplicada
        print(f"[benchmark] snapshots_unavailable client_id={client_id} {type(exc).__name__}")
        return {"rows": [], "collected_at": None, "available": False}
    active = {_handle(c.get("instagram_handle")): c for c in competitors if _handle(c.get("instagram_handle")) and c.get("active", True)}
    now = _now()
    rows = []
    for s in snaps:
        handle = str(s.get("handle") or "").lower()
        if s.get("is_brand") or handle in active:
            row = ig_metrics(s, days=days, now=now)
            row["name"] = "Sua marca" if s.get("is_brand") else active[handle].get("name")
            rows.append(row)
    collected = max((str(s["collected_at"]) for s in snaps if s.get("collected_at")), default=None)
    return {"rows": with_share(rows), "collected_at": collected, "available": True}


async def refresh_instagram(client_id: str, competitors: List[Dict[str, Any]], *, force: bool = False) -> Dict[str, Any]:
    """Busca agora o perfil público da marca e de cada concorrente com @ (no máximo a cada 6 horas)."""
    from . import creators_providers as providers
    from .creators import _meta_credentials, record_usage
    from .studio_calendar import StudioError

    snaps = await latest_snapshots(client_id)
    last = max((_ts(s.get("collected_at")) for s in snaps if _ts(s.get("collected_at"))), default=None)
    if last and not force and _now() - last < REFRESH_COOLDOWN:
        raise StudioError("BENCHMARK_COOLDOWN")
    ig_user_id, token = await _meta_credentials(client_id)
    connection_handle = await _brand_handle(client_id)
    targets: List[Dict[str, Any]] = []
    if connection_handle:
        targets.append({"handle": connection_handle, "is_brand": True, "competitor_id": None})
    for c in competitors:
        handle = _handle(c.get("instagram_handle"))
        if handle and c.get("active", True) and handle != connection_handle:
            targets.append({"handle": handle, "is_brand": False, "competitor_id": c.get("id")})
    if len(targets) <= int(bool(connection_handle)):
        raise StudioError("BENCHMARK_NO_HANDLES")

    gate = asyncio.Semaphore(PARALLEL)
    errors: List[Dict[str, str]] = []
    saved: List[Dict[str, Any]] = []
    today = date.today().isoformat()

    async def one(target: Dict[str, Any]) -> None:
        async with gate:
            try:
                profile = await providers.meta_business_discovery(ig_user_id, token, target["handle"], posts=POSTS_PER_PROFILE)
                await record_usage(client_id, "meta", "business_discovery", units=1)
            except Exception as exc:  # noqa: BLE001 — um perfil com problema não derruba os outros
                await record_usage(client_id, "meta", "business_discovery", units=1, ok=False)
                errors.append({"handle": target["handle"], "error": str(exc)[:200] or "Perfil indisponível."})
                return
            saved.append({"client_id": client_id, "competitor_id": target["competitor_id"], "handle": target["handle"],
                          "is_brand": target["is_brand"], "day": today, "followers": profile.get("followers"),
                          "media_count": profile.get("media_count"), "collected_at": _now().isoformat(),
                          "posts": [{k: p.get(k) for k in ("url", "timestamp", "type", "likes", "comments")}
                                    for p in profile.get("posts") or []]})

    await asyncio.gather(*(one(t) for t in targets))
    if saved:
        await sb_upsert(SNAPSHOTS, saved, on_conflict="client_id,handle,day")
    return {"updated": len(saved), "errors": errors}


async def _brand_handle(client_id: str) -> Optional[str]:
    from .meta_tokens import get_active_connection_for_client
    connection = await get_active_connection_for_client(client_id)
    handle = str((connection or {}).get("username") or "").strip().lstrip("@").lower()
    return handle or None
