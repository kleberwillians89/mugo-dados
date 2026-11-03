"""Histórico completo dos posts do Instagram (legenda, imagem e métricas), por bloco de datas.

Entra na busca de histórico de Empresas (``history_backfill``), junto com Meta Ads, Google e GA4:
o pedido "desde 01/01/2026, todas as empresas" passa a trazer também os posts antigos.

- Mesma linha que o sync diário grava em ``ig_media`` (mesmos campos, mesmo upsert por client_id+media_id).
- Métricas de post antigo são o total acumulado até hoje (é o que a Meta devolve).
- Stories antigos não existem na Meta (24 h) e não entram. Comentários não são baixados aqui.
- Mesmo lock do sync recorrente do Instagram: nunca rodam juntos. Pausa entre chamadas.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

import httpx

from .ig_meta import META_BASE, _clean_token, fetch_media_insights, meta_get_json
from .ig_supabase import sb_upsert
from .integration_errors import IntegrationError

FIELDS = ("id,media_type,media_product_type,caption,timestamp,permalink,"
          "media_url,thumbnail_url,comments_count,like_count")
MAX_PAGES = 200
PAUSE_SECONDS = 0.4


def _day(timestamp: Any) -> Optional[date]:
    from .periods import local_date
    raw = str(timestamp or "").strip()
    if not raw:
        return None
    try:
        return local_date(datetime.fromisoformat(raw.replace("+0000", "+00:00").replace("Z", "+00:00")))
    except ValueError:
        return None


async def list_media_between(ig_user_id: str, token: str, start: date, end: date) -> List[Dict[str, Any]]:
    """A Meta lista do mais novo para o mais antigo: pagina até passar da data inicial."""
    items: List[Dict[str, Any]] = []
    resp = await meta_get_json(f"/{ig_user_id}/media", {"fields": FIELDS, "limit": 100, "access_token": _clean_token(token)})
    for _ in range(MAX_PAGES):
        page = resp.get("data") or []
        oldest: Optional[date] = None
        for item in page:
            day = _day(item.get("timestamp"))
            if day is None:
                continue
            oldest = day if oldest is None or day < oldest else oldest
            if start <= day <= end and str(item.get("media_product_type") or "").upper() != "STORY":
                items.append(item)
        next_url = (resp.get("paging") or {}).get("next")
        if not page or not next_url or (oldest is not None and oldest < start):
            return items
        if urlsplit(next_url).netloc != urlsplit(META_BASE).netloc:
            raise IntegrationError("Paginação do Instagram fora da Meta.", status_code=502,
                                   code="IG_MEDIA_HISTORY_INCOMPLETE", provider="instagram")
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(next_url)
        if response.status_code >= 400:
            raise IntegrationError("A Meta recusou a listagem de posts.", status_code=502,
                                   code="IG_MEDIA_HISTORY_FAILED", provider="instagram")
        resp = response.json()
    raise IntegrationError("Paginação histórica do Instagram incompleta.", status_code=502,
                           code="IG_MEDIA_HISTORY_INCOMPLETE", provider="instagram")


def media_row(client_id: str, connection_id: str, item: Dict[str, Any], insights: Dict[str, Any]) -> Dict[str, Any]:
    """Mesmo formato do sync diário (instagram_sync), com o fallback de curtidas e comentários."""
    from .instagram_sync import _normalize_meta_ts
    insights = dict(insights or {})
    if not int(insights.get("likes") or 0) and int(item.get("like_count") or 0):
        insights["likes"] = int(item["like_count"])
    if not int(insights.get("comments") or 0) and int(item.get("comments_count") or 0):
        insights["comments"] = int(item["comments_count"])
    if not int(insights.get("total_interactions") or 0):
        total = int(insights.get("likes") or 0) + int(insights.get("comments") or 0)
        if total:
            insights["total_interactions"] = total
    media_type = str(item.get("media_type") or "").upper()
    return {
        "client_id": client_id, "connection_id": connection_id, "media_id": str(item["id"]),
        "media_type": item.get("media_type"), "media_product_type": str(item.get("media_product_type") or "FEED").upper(),
        "caption": item.get("caption"), "permalink": item.get("permalink"),
        "timestamp": _normalize_meta_ts(item.get("timestamp")),
        "thumb_url": item.get("thumbnail_url") or (item.get("media_url") if media_type in {"IMAGE", "CAROUSEL_ALBUM"} else None),
        "media_url": item.get("media_url"), "thumbnail_url": item.get("thumbnail_url"),
        "insights_json": insights,
    }


async def backfill_block(client_id: str, start: date, end: date, *, pause_seconds: float = PAUSE_SECONDS) -> int:
    from .connection_resolver import resolve_connection_for_scope
    from .meta_tokens import ensure_valid_meta_token
    from .sync_locks import guarded_sync

    context = await resolve_connection_for_scope(client_id=client_id, platform="instagram", connection_type="organic")
    connection_id = str(context.get("connection_id") or "")
    ig_user_id = str((context.get("row") or {}).get("ig_user_id") or "")
    if not connection_id or not ig_user_id:
        raise IntegrationError("Instagram não conectado.", status_code=400, code="IG_NOT_CONNECTED", provider="instagram")
    async with guarded_sync(client_id=client_id, provider="instagram", connection_id=connection_id):
        token = await ensure_valid_meta_token(client_id, connection_id=connection_id, platform="instagram",
                                              connection_type="organic", persisted_only=True)
        items = await list_media_between(ig_user_id, token, start, end)
        rows = []
        for item in {str(i["id"]): i for i in items if i.get("id")}.values():
            try:
                insights = await fetch_media_insights(str(item["id"]), token, str(item.get("media_product_type") or "FEED"))
            except Exception:  # noqa: BLE001 — post sem insight entra com curtidas/comentários da listagem
                insights = {}
            rows.append(media_row(client_id, connection_id, item, insights))
            await asyncio.sleep(pause_seconds)
        for offset in range(0, len(rows), 200):
            await sb_upsert("ig_media", rows[offset:offset + 200], on_conflict="client_id,media_id")
    return len(rows)
