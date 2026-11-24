"""Música e áudios do Instagram para o Reels (Instagram Audio API, login pelo Facebook).

A busca devolve só o que a Meta liberou para uso por apps (pode ser menos do que aparece no app do Instagram).
A música escolhida vai no contêiner do Reels como ``audio_configuration`` (ver ig_reels.apply_reels_options).
"""
from __future__ import annotations

from typing import Any, Dict, List
import re
import unicodedata

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


def _terms(value: str) -> list[str]:
    """Normaliza acentos, caixa e pontuação sem apagar palavras relevantes."""
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", normalized)


def _relevance(audio: Dict[str, Any], query: str) -> int:
    """Evita mostrar um áudio completamente diferente como resultado da busca."""
    words = _terms(query)
    if not words:
        return 1
    title = _terms(str(audio.get("title") or ""))
    artist = _terms(str(audio.get("artist") or ""))
    needle = " ".join(words)
    title_text = " ".join(title)
    artist_text = " ".join(artist)
    if title_text == needle:
        return 100
    if artist_text == needle:
        return 90
    if title_text.startswith(needle + " "):
        return 85
    if artist_text.startswith(needle + " "):
        return 80
    if needle in title_text:
        return 75
    if needle in artist_text:
        return 70
    # Título + artista, independentemente da ordem.
    combined = set(title + artist)
    if all(w in combined for w in words):
        return 60
    if len(words) >= 2 and sum(w in combined for w in words) >= max(2, len(words) - 1):
        return 30
    if len(words) == 1 and words[0] in combined:
        return 20
    return 0


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
    normalized = [a for a in (normalize(r) for r in rows if isinstance(r, dict)) if a]
    # A Meta pode retornar resultados fora do termo pesquisado. Nunca ofereça música
    # incompatível como se fosse a solicitada; mantenha a ordenação original em "Em alta".
    if not (query or "").strip():
        return normalized[:30]
    ranked = sorted(((score, n, a) for n, a in enumerate(normalized)
                     if (score := _relevance(a, query)) > 0), key=lambda row: (-row[0], row[1]))
    if ranked:
        return [a for _, _, a in ranked[:30]]

    # A biblioteca da Meta pode não interpretar a combinação "artista + música".
    # Só se não houve correspondência, consulta até dois fragmentos e cruza com
    # a pesquisa COMPLETA. Não cria títulos/IDs ou apresenta faixa diferente.
    terms = (query or "").strip().split()
    if len(terms) < 2:
        return []
    candidates = ([" ".join(terms[:2]), " ".join(terms[-2:])] if len(terms) >= 4
                  else [terms[0], terms[-1]])
    seen = {a["audio_id"] for a in normalized}
    async with httpx.AsyncClient(timeout=20) as client:
        for candidate in dict.fromkeys(candidates):
            if candidate.casefold() == query.strip().casefold():
                continue
            try:
                alt = await client.get(f"{META_GRAPH_BASE_URL}/ig_audio",
                                       params={**params, "search_query": candidate})
                if alt.status_code >= 400:
                    continue
                payload = alt.json() if alt.content else {}
                matches = payload.get("audio") or payload.get("data") or []
                for raw in matches:
                    audio = normalize(raw) if isinstance(raw, dict) else None
                    if audio and audio["audio_id"] not in seen:
                        seen.add(audio["audio_id"])
                        normalized.append(audio)
            except (httpx.HTTPError, ValueError, TypeError, AttributeError):
                continue
    ranked = sorted(((score, n, a) for n, a in enumerate(normalized)
                     if (score := _relevance(a, query)) > 0), key=lambda row: (-row[0], row[1]))
    return [a for _, _, a in ranked[:30]]
