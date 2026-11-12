"""Brave Search: pesquisa pública verificável para o snapshot de inteligência.

Não envia briefings, documentos, métricas ou dados de compradores à Brave.
Usa somente o nome público da empresa cadastrada e consultas genéricas.
Descoberta de criadores continua nas APIs oficiais existentes; busca web não
comprova identidade nem métricas de criadores.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx

from .ig_supabase import sb_select

API_URL = "https://api.search.brave.com/res/v1/web/search"
CACHE_SECONDS = 3600
MAX_CACHE = 128
_cache: Dict[tuple[str, str], tuple[float, List[Dict[str, Any]]]] = {}


def _safe_name(value: Any) -> str:
    name = re.sub(r"\s+", " ", str(value or "")).strip()
    # Pesquisa apenas o nome público, nunca conteúdo arbitrário do tenant.
    return name[:80] if 2 <= len(name) <= 120 else ""


async def _public_brand_name(client_id: str) -> str:
    rows = await sb_select("clients", select="id,name",
                           filters={"id": f"eq.{client_id}"}, limit=1)
    return _safe_name(rows[0].get("name")) if rows else ""


def _results(data: Any, *, category: str) -> List[Dict[str, Any]]:
    entries = ((data.get("web") or {}).get("results") or []) if isinstance(data, dict) else []
    now = datetime.now(timezone.utc).isoformat()
    output: List[Dict[str, Any]] = []
    for entry in entries[:6]:
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("url") or "").strip()
        # Não aceitar URL sem HTTPS ou origem verificável.
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            continue
        title = re.sub(r"\s+", " ", str(entry.get("title") or "")).strip()[:180]
        summary = re.sub(r"\s+", " ", str(entry.get("description") or "")).strip()[:300]
        if not title:
            continue
        output.append({
            "kind": "CONTENT_REFERENCE",
            "handle": None,
            "platform": "web",
            "profile_url": None,
            "category": category,
            "reason_relevant": title,
            "observed_format": "resultado de pesquisa",
            "public_signal": summary or title,
            "source_url": url,
            "researched_at": now,
        })
    return output


class BraveSearchProvider:
    name = "brave"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def _search(self, client_id: str, kind: str) -> List[Dict[str, Any]]:
        key = (client_id, kind)
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
            return [dict(row) for row in cached[1]]
        brand = await _public_brand_name(client_id)
        if not brand:
            return []
        suffix = {
            "market": "mercado tendências setor notícias",
            "references": "campanhas marketing conteúdo referências",
        }.get(kind)
        if not suffix:
            return []
        async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
            response = await client.get(
                API_URL,
                headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
                params={"q": f'"{brand}" {suffix}', "count": 6, "country": "BR", "search_lang": "pt"},
            )
            response.raise_for_status()
            results = _results(response.json(), category=kind)
        if len(_cache) >= MAX_CACHE:
            oldest = min(_cache, key=lambda k: _cache[k][0])
            _cache.pop(oldest, None)
        _cache[key] = (time.monotonic(), results)
        return [dict(row) for row in results]

    async def research_brand_context(self, *, client_id: str, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        return await self._search(client_id, "market")

    async def find_market_signals(self, *, client_id: str, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        return await self._search(client_id, "market")

    async def find_creators(self, *, client_id: str, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        # Nome ou perfil retornado por busca web não é identidade verificada.
        return []

    async def find_content_references(self, *, client_id: str, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        return await self._search(client_id, "references")


def from_environment() -> BraveSearchProvider | None:
    if (os.getenv("EXTERNAL_RESEARCH_PROVIDER") or "").strip().lower() != "brave":
        return None
    key = (os.getenv("BRAVE_SEARCH_API_KEY") or "").strip()
    return BraveSearchProvider(key) if key else None
