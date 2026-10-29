"""Assuntos em alta no Brasil, com fonte verificável.

Fonte: feed RSS público do Google Trends ("Em alta agora", geo=BR). Cada item
só é aproveitado se tiver um link de notícia/consulta que a equipe possa
abrir: assunto sem fonte é descartado, nunca inventado (mesma regra de
services/external_research.py).

São assuntos do momento, não previsão para o mês seguinte. O calendário usa
no máximo alguns, e só quando combinam com a marca; a decisão é da revisão.
Falha de rede ou formato inesperado devolve lista vazia: o calendário segue
sem tendências.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import quote_plus

import httpx

TRENDS_RSS_URL = "https://trends.google.com/trending/rss?geo=BR"
MAX_TRENDS = 15


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag.split(":")[-1]


def _child_text(node: ET.Element, name: str) -> str:
    for child in node:
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return ""


def parse_trends_rss(xml_text: str, *, researched_at: str | None = None) -> List[Dict[str, Any]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    when = researched_at or datetime.now(timezone.utc).isoformat()
    out: List[Dict[str, Any]] = []
    seen = set()
    for item in root.iter():
        if _local(item.tag) != "item":
            continue
        topic = _child_text(item, "title")[:120]
        if not topic or topic.lower() in seen:
            continue
        news = []
        for child in item:
            if _local(child.tag) == "news_item":
                url = _child_text(child, "news_item_url")
                if url.startswith("https://") or url.startswith("http://"):
                    news.append({"title": _child_text(child, "news_item_title")[:200], "url": url,
                                 "source": _child_text(child, "news_item_source")[:80]})
        # Sem notícia, a própria consulta no Google Trends é a evidência.
        source_url = news[0]["url"] if news else f"https://trends.google.com/trends/explore?geo=BR&q={quote_plus(topic)}"
        seen.add(topic.lower())
        out.append({
            "id": f"t{len(out) + 1}",
            "topic": topic,
            "approx_traffic": _child_text(item, "approx_traffic")[:20] or None,
            "news_title": news[0]["title"] if news else None,
            "source_url": source_url,
            "researched_at": when,
        })
        if len(out) >= MAX_TRENDS:
            break
    return out


async def fetch_trends_br() -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.get(TRENDS_RSS_URL, headers={"User-Agent": "MugoDados/1.0"})
            response.raise_for_status()
    except Exception as exc:
        print(f"[studio][trends] status=unavailable error_type={exc.__class__.__name__}")
        return {"status": "unavailable", "items": []}
    items = parse_trends_rss(response.text)
    return {"status": "ok" if items else "empty", "items": items}
