"""Motor de notícias: porte em Python das regras puras do CRM Mugô.

Origem (crmmugo, mantida intacta; a newsletter do CRM não depende deste módulo):
- supabase/functions/_shared/newsletterCore.js: parseFeed, bestExcerpt, extractArticleText, balanceCandidates,
  validateCuration (a IA só pode citar itens que existem na coleta);
- src/lib/temporalIntelligence.js: temporalPriority (recência → prioridade).

Mesmo comportamento, mesma ordem das regras. Se mudar no CRM, ajustar aqui e em test_news_engine.py.
Fontes ficam atrás de NewsProvider: RSS/Atom e Google Notícias ativos; GDELT preparado e desligado.
"""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote_plus

import httpx

USER_AGENT = "Mozilla/5.0 (compatible; MugoClipping/1.0)"
ACCEPT = "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"
GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
_BOILERPLATE = re.compile(r"(the post .{0,300}? appeared first on .{0,120}?\.?$|o post .{0,300}? apareceu primeiro em .{0,120}?\.?$|"
                          r"\[(?:…|\.\.\.)\]|continue reading.*$|leia mais.*$|read more.*$)", re.I)
_NOISE = re.compile(r"(cookie|newsletter|assine|inscreva|todos os direitos|all rights reserved|publicidade|subscribe)", re.I)


def url_hash(url: str) -> str:
    return hashlib.sha1(url.strip().encode()).hexdigest()


def _decode(value: Any) -> str:
    text = re.sub(r"<!\[CDATA\[([\s\S]*?)\]\]>", r"\1", str(value or ""))
    return html.unescape(text).replace("\xa0", " ")


def strip_tags(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _decode(value))).strip()


def _tag(block: str, name: str) -> str:
    match = re.search(rf"<{name}(?:\s[^>]*)?>([\s\S]*?)</{name}>", block, re.I)
    return match.group(1) if match else ""


def best_excerpt(candidates: Iterable[str]) -> str:
    cleaned = [re.sub(r"\s+", " ", _BOILERPLATE.sub("", strip_tags(c))).strip() for c in candidates]
    return max([c for c in cleaned if c], key=len, default="")


def _date(raw: str) -> Optional[str]:
    raw = raw.strip()
    if not raw:
        return None
    try:
        moment = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()


def parse_feed(xml: str, *, limit: int = 30) -> List[Dict[str, Any]]:
    """RSS 2.0 e Atom. Tolera feed truncado (o último item incompleto é ignorado)."""
    source = str(xml or "")
    blocks = [(m.group(0), False) for m in re.finditer(r"<item[\s>][\s\S]*?</item>", source, re.I)]
    blocks += [(m.group(0), True) for m in re.finditer(r"<entry[\s>][\s\S]*?</entry>", source, re.I)]
    items: List[Dict[str, Any]] = []
    for block, atom in blocks:
        title = strip_tags(_tag(block, "title"))
        if atom:
            match = re.search(r"<link[^>]*rel=[\"']alternate[\"'][^>]*href=[\"']([^\"']+)[\"']", block, re.I) or \
                re.search(r"<link[^>]*href=[\"']([^\"']+)[\"']", block, re.I)
            link = match.group(1) if match else ""
        else:
            link = strip_tags(_tag(block, "link")) or strip_tags(_tag(block, "guid"))
        source_name = strip_tags(_tag(block, "source"))
        if source_name and title.endswith(f" - {source_name}"):  # Google Notícias põe " - Fonte" no fim
            title = title[: -len(f" - {source_name}")]
        if not title or not re.match(r"^https?://", link, re.I):
            continue
        items.append({
            "title": title[:400], "url": _decode(link).strip()[:2000], "source": source_name[:160] or None,
            "excerpt": best_excerpt([_tag(block, "content:encoded"), _tag(block, "description"), _tag(block, "summary"), _tag(block, "content")])[:1500] or None,
            "published_at": _date(strip_tags(_tag(block, "pubDate") or _tag(block, "published") or _tag(block, "updated") or _tag(block, "dc:date"))),
        })
        if len(items) >= limit:
            break
    return items


def extract_article_text(page: str, *, max_len: int = 1500) -> str:
    """Descrição (og/meta) + primeiros parágrafos do artigo, para a IA resumir com substância."""
    page = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<!--[\s\S]*?-->", " ", str(page or ""), flags=re.I)

    def meta(name: str) -> str:
        m = re.search(rf"<meta[^>]+(?:property|name)=[\"']{name}[\"'][^>]*content=[\"']([^\"']+)[\"']", page, re.I) or \
            re.search(rf"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]*(?:property|name)=[\"']{name}[\"']", page, re.I)
        return m.group(1) if m else ""

    description = strip_tags(meta("og:description") or meta("description") or meta("twitter:description"))
    scope_match = re.search(r"<article[\s\S]*?</article>", page, re.I) or re.search(r"<main[\s\S]*?</main>", page, re.I)
    scope = scope_match.group(0) if scope_match else page
    paragraphs = [strip_tags(m.group(1)) for m in re.finditer(r"<p[^>]*>([\s\S]*?)</p>", scope, re.I)]
    paragraphs = [p for p in paragraphs if len(p) >= 60 and not _NOISE.search(p)]
    out = ""
    for part in [description] + [p for p in paragraphs if p != description]:
        if not part:
            continue
        if len(f"{out} {part}") > max_len:
            break
        out = f"{out} {part}" if out else part
    return out[:max_len]


def fold(text: Any) -> str:
    raw = unicodedata.normalize("NFD", str(text or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")).strip()


def dedupe(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Uma notícia, uma linha: mesma URL ou mesma manchete (sem acento/pontuação) contam como repetidas."""
    seen_url, seen_title, out = set(), set(), []
    for item in items:
        key_url, key_title = url_hash(item["url"]), fold(item["title"])
        if key_url in seen_url or key_title in seen_title:
            continue
        seen_url.add(key_url); seen_title.add(key_title)
        out.append({**item, "url_hash": key_url})
    return out


def balance_by_source(items: List[Dict[str, Any]], *, per_source: int = 12, max_items: int = 60) -> List[Dict[str, Any]]:
    """Um veículo não domina o lote (balanceCandidates do CRM), intercalando por tipo de menção."""
    counts: Dict[str, int] = {}
    queues: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        name = item.get("source") or "?"
        counts[name] = counts.get(name, 0) + 1
        if counts[name] > per_source:
            continue
        queues.setdefault(item.get("kind") or "outros", []).append(item)
    out: List[Dict[str, Any]] = []
    lists = list(queues.values())
    while len(out) < max_items and any(lists):
        for queue in lists:
            if queue and len(out) < max_items:
                out.append(queue.pop(0))
    return out


def evidence_in(quotes: Iterable[Any], *texts: Any) -> List[str]:
    """Só fica a evidência que está, de fato, no texto coletado (validateCuration: nada fora da fonte)."""
    haystack = fold(" ".join(str(t or "") for t in texts))
    kept = []
    for quote in quotes or []:
        q = str(quote or "").strip()[:240]
        if len(fold(q)) >= 8 and fold(q) in haystack:
            kept.append(q)
    return kept[:3]


def recency_priority(published_at: Optional[str], now: Optional[datetime] = None) -> Dict[str, Any]:
    """temporalPriority do CRM aplicado à idade da matéria."""
    if not published_at:
        return {"priority": "low", "score": 30}
    age = abs(((now or datetime.now(timezone.utc)) - datetime.fromisoformat(published_at.replace("Z", "+00:00"))).total_seconds())
    day = 86400
    if age <= day:
        return {"priority": "critical", "score": 100}
    if age <= 3 * day:
        return {"priority": "high", "score": 85}
    if age <= 15 * day:
        return {"priority": "medium", "score": 60}
    return {"priority": "low", "score": 30}


# ---------------------------------------------------------------- fontes


class ProviderDisabled(RuntimeError):
    pass


async def _get(url: str, *, timeout: float = 15) -> Optional[str]:
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": USER_AGENT, "Accept": ACCEPT, "Accept-Language": "pt-BR,pt;q=0.9"})
        return response.text if response.status_code < 400 else None
    except Exception as exc:  # noqa: BLE001 — fonte fora do ar não para a coleta
        print(f"[news_engine] fetch_failed error_type={exc.__class__.__name__}")
        return None


class GoogleNewsProvider:
    name = "google_news"

    async def search(self, term: str, *, exclude: List[str], days: int = 7) -> List[Dict[str, Any]]:
        query = f'"{term}" ' + " ".join(f'-"{x}"' if " " in x else f"-{x}" for x in exclude) + f" when:{days}d"
        xml = await _get(GOOGLE_NEWS.format(q=quote_plus(query.strip())))
        return parse_feed(xml or "", limit=15)


class FeedProvider:
    name = "rss"

    async def read(self, url: str) -> List[Dict[str, Any]]:
        if not re.match(r"^https://", url or ""):
            return []
        return parse_feed(await _get(url) or "", limit=40)


class GdeltProvider:
    """Interface pronta para o GDELT DOC API; desligada nesta etapa (nenhum serviço novo ativado)."""
    name = "gdelt"
    enabled = False

    async def search(self, term: str, *, exclude: List[str], days: int = 7) -> List[Dict[str, Any]]:
        raise ProviderDisabled("GDELT não está ativado.")


async def fetch_article_text(url: str) -> str:
    page = await _get(url, timeout=12)
    return extract_article_text(page or "")
