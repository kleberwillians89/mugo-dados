"""Radar Cultural: read-only aggregation of authorized tenant data and public trends.

Does not invent competitor metrics, cultural affinity or share-of-attention.
Uses the existing tenant authorization and creator linking model.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header

from services import creators
from services.studio_trends import fetch_trends_br
from services.tenant import require_client_read

router = APIRouter(prefix="/api/clients/{client_id}/radar", tags=["radar"])

_TRENDS_TTL_SECONDS = 900
_trends_cached: Optional[Dict[str, Any]] = None
_trends_expires = 0.0


async def _trends() -> Dict[str, Any]:
    """Public BR trends are cached globally; they contain no tenant data."""
    global _trends_cached, _trends_expires
    if _trends_cached is not None and time.monotonic() < _trends_expires:
        return _trends_cached
    data = await fetch_trends_br()
    if data.get("status") == "ok":
        _trends_cached = data
        _trends_expires = time.monotonic() + _TRENDS_TTL_SECONDS
    return data


def source_status() -> Dict[str, str]:
    """Expose configuration presence, never API keys or tokens."""
    return {
        "youtube": "configured" if os.getenv("YOUTUBE_API_KEY", "").strip() else "not_configured",
        "apify": "configured" if os.getenv("APIFY_TOKEN", "").strip() else "not_configured",
        "instagram": "requires_client_meta_connection",
        "trends": "public_feed",
    }


def creator_digest(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A creator is not a competitor; surface only profile evidence and provenance."""
    result = []
    for row in rows[:30]:
        profile_url = row.get("profile_url")
        if not isinstance(profile_url, str) or not profile_url.startswith(("https://", "http://")):
            profile_url = None
        result.append({
            "id": row.get("id"),
            "network": row.get("network"),
            "handle": row.get("handle"),
            "display_name": row.get("display_name"),
            "followers": row.get("followers"),
            "engagement_rate": row.get("engagement_rate"),
            "sample_size": row.get("sample_size"),
            "profile_url": profile_url,
            "source": row.get("source"),
            "collected_at": row.get("collected_at"),
            "missing_fields": row.get("missing_fields") or [],
        })
    return result


@router.get("/overview")
async def radar_overview(
    client_id: str, authorization: Optional[str] = Header(default=None)
) -> Dict[str, Any]:
    cid = await require_client_read(client_id, authorization)
    # Even an agency_admin sees ONLY the creators linked to the requested tenant.
    linked = await creators.linked_ids(cid)
    profiles = await creators.list_creators(
        network=None, q=None, min_followers=None, limit=30, offset=0, only_ids=linked
    ) if linked else []
    try:
        public = await _trends()
    except Exception:
        public = {"status": "unavailable", "items": []}
    # Cada marca vê só o que conversa com ela (o feed público é igual para todas).
    from services.radar_brand import brand_trends
    trends = await brand_trends(cid, public)
    return {
        "client_id": cid,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "sources": source_status(),
        "trends": trends,
        "creators": creator_digest(profiles),
        "methodology": {
            "trends": "Assuntos em alta no Brasil (Google Trends) filtrados para esta marca: só entra o que tem ligação com o segmento, o público e os termos dela.",
            "creators": "Perfis explicitamente vinculados à empresa; não representam concorrentes.",
            "brand_intelligence": "Leituras competitivas disponíveis no módulo Clipping; sem estimativa de alcance privado.",
            "share_of_attention": "Indisponível: faltam observações comparáveis de uma amostra de marcas.",
        },
    }
