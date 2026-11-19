"""Música e áudios do Instagram para o Reels (Instagram Audio API, login pelo Facebook).

A busca devolve só o que a Meta liberou para uso por apps (pode ser menos do que aparece no app do Instagram).
A música escolhida vai no contêiner do Reels como ``audio_configuration`` (ver ig_reels.apply_reels_options).
"""
from __future__ import annotations

from typing import Any, Dict, List

import httpx

from .meta_config import META_GRAPH_BASE_URL
from .studio_calendar import StudioError

AUDIO_TYPES = ("music", "original_sound")


def _https(value: Any) -> str | None:
    text = str(value or "")
    return text if text.startswith("https://") else None


def normalize(row: Dict[str, Any]) -> Dict[str, Any] | None:
    audio_id = str(row.get("audio_id") or row.get("id") or "").strip()
    if not audio_id.isdigit():
        return None
    try:
        duration = int(row.get("duration_in_ms") or 0) or None
    except (TypeError, ValueError):
        duration = None
    return {
        "audio_id": audio_id,
        "title": str(row.get("title") or "").strip()[:120] or "Sem título",
        "artist": str(row.get("display_artist") or row.get("ig_username") or "").strip()[:120] or None,
        "duration_ms": duration,
        "cover": _https(row.get("cover_artwork_thumbnail_uri") or row.get("cover_artwork_thumbnail_url") or row.get("profile_picture_url")),
        "preview_url": _https(row.get("download_url")),
        "type": "original_sound" if str(row.get("audio_type") or "").lower() == "original_sound" else "music",
    }


async def search_audio(client_id: str, query: str = "", audio_type: str = "music") -> List[Dict[str, Any]]:
    """Músicas (ou áudios originais de Reels) para escolher. Sem busca, vêm as que estão em alta."""
    from .ig_engagement import credentials
    if audio_type not in AUDIO_TYPES:
        audio_type = "music"
    creds = await credentials(client_id)
    params: Dict[str, Any] = {"audio_type": audio_type, "user_id": creds["ig_user_id"], "access_token": creds["token"]}
    if (query or "").strip():
        params["search_query"] = query.strip()[:100]
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{META_GRAPH_BASE_URL}/ig_audio", params=params)
    body: Dict[str, Any] = {}
    try:
        body = response.json() if response.content else {}
    except ValueError:
        body = {}
    if response.status_code >= 400:
        error = (body or {}).get("error") or {}
        message = str(error.get("error_user_msg") or error.get("message") or f"HTTP {response.status_code}")[:250]
        raise StudioError("IG_AUDIO_FAILED", f"A Meta não liberou a busca de músicas: {message}")
    rows = body.get("audio") or body.get("data") or []
    return [a for a in (normalize(r) for r in rows if isinstance(r, dict)) if a][:30]
