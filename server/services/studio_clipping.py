"""
Clipping da marca (trazido do iAgência) — só a equipe Mugô usa.

Fonte: feed RSS público do Google Notícias (sem chave, sem custo; o iAgência usava GNews, pago).
Cada notícia entra uma vez só (hash da URL), sempre com link da fonte. A IA lê só título e fonte
e devolve sentimento, um resumo de 1 linha e se é relevante para a marca; ela não inventa nada.
Sem IA (ou com falha), a notícia entra mesmo assim, sem classificação.

Busca: 1 vez por dia pelo job ``studio-clipping`` e no botão "Atualizar agora" (com intervalo mínimo).
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import httpx

from .ig_supabase import sb_insert_many, sb_select, sb_update, sb_upsert
from .studio_calendar import StudioError, create_item

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
SETTINGS = "studio_clipping_settings"
CLIPPINGS = "studio_clippings"
NEWS_RSS = "https://news.google.com/rss/search?q={q}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
MAX_TERMS = 6
MAX_PER_TERM = 15
MAX_NEW_PER_RUN = 40
REFRESH_COOLDOWN = timedelta(minutes=10)
SENTIMENTS = ("positivo", "neutro", "negativo")


# ------------------------------------------------------------------ configuração

def _terms(values: Any) -> List[str]:
    out: List[str] = []
    for value in values or []:
        term = re.sub(r"\s+", " ", str(value or "")).strip()[:120]
        if term and term.lower() not in {t.lower() for t in out}:
            out.append(term)
    return out[:MAX_TERMS]


async def get_settings(client_id: str) -> Dict[str, Any]:
    rows = await sb_select(SETTINGS, select="*", filters={"client_id": f"eq.{client_id}"}, limit=1)
    row = rows[0] if rows else {}
    return {"brand_terms": row.get("brand_terms") or [], "competitor_terms": row.get("competitor_terms") or [],
            "exclude_terms": row.get("exclude_terms") or [], "active": row.get("active", True) if row else True,
            "last_run_at": row.get("last_run_at"), "saved": bool(row)}


async def save_settings(client_id: str, data: Dict[str, Any], *, user_id: str) -> Dict[str, Any]:
    row = {"client_id": client_id, "brand_terms": _terms(data.get("brand_terms")),
           "competitor_terms": _terms(data.get("competitor_terms")), "exclude_terms": _terms(data.get("exclude_terms")),
           "active": bool(data.get("active", True)), "updated_by": user_id,
           "updated_at": datetime.now(timezone.utc).isoformat()}
    if not row["brand_terms"]:
        raise StudioError("CLIPPING_TERMS_REQUIRED")
    await sb_upsert(SETTINGS, [row], on_conflict="client_id")
    return await get_settings(client_id)


# ------------------------------------------------------------------ busca

def url_hash(url: str) -> str:
    return hashlib.sha1(url.strip().encode()).hexdigest()


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def parse_news_rss(xml_text: str, *, term: str, kind: str) -> List[Dict[str, Any]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out: List[Dict[str, Any]] = []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        raw_title = (item.findtext("title") or "").strip()
        source = (item.findtext("source") or "").strip()
        if not raw_title or not link.startswith("http"):
            continue
        # O Google Notícias põe " - Fonte" no fim do título.
        title = raw_title[: -len(f" - {source}")] if source and raw_title.endswith(f" - {source}") else raw_title
        published = None
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "").astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError):
            published = None
        out.append({"url": link[:2000], "url_hash": url_hash(link), "title": title[:400], "source": source[:160] or None,
                    "published_at": published, "kind": kind, "term": term})
        if len(out) >= MAX_PER_TERM:
            break
    return out


async def fetch_term(term: str, *, kind: str, exclude: List[str]) -> List[Dict[str, Any]]:
    query = f'"{term}" ' + " ".join(f"-{x}" if " " not in x else f'-"{x}"' for x in exclude) + " when:7d"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(NEWS_RSS.format(q=quote_plus(query.strip())), headers={"User-Agent": "Mugoverso/1.0"})
            response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — sem notícia hoje não é erro do painel
        print(f"[studio][clipping] term_fetch_failed kind={kind} error_type={exc.__class__.__name__}")
        return []
    items = parse_news_rss(response.text, term=term, kind=kind)
    low_ex = [x.lower() for x in exclude]
    return [i for i in items if not any(x in i["title"].lower() for x in low_ex)]


async def _classify(brand: str, items: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    if not items:
        return {}
    from .studio_llm import STR, arr, llm_json, obj
    schema = obj({"items": arr(obj({"index": {"type": "integer"}, "sentimento": {"type": "string", "enum": list(SENTIMENTS)},
                                    "resumo": STR, "relevante": {"type": "boolean"}}))})
    lines = "\n".join(f"{i}. [{it['kind']}: {it['term']}] {it['title']} ({it.get('source') or 'fonte'})" for i, it in enumerate(items))
    try:
        data = await llm_json(
            instructions=("Você faz clipping para uma agência. Para cada manchete, diga o sentimento EM RELAÇÃO À MARCA "
                          "(ou ao concorrente, quando for notícia de concorrente), um resumo de até 140 caracteres sem "
                          "travessão e se é relevante (falsa quando o termo aparece por coincidência, ex.: homônimo). "
                          "Use só a manchete e a fonte; não invente fatos."),
            prompt=f"MARCA: {brand}\nMANCHETES:\n{lines}", schema_name="studio_clipping", schema=schema,
            temperature=0.1, timeout=45)
    except StudioError:
        return {}
    out: Dict[int, Dict[str, Any]] = {}
    for row in data.get("items") or []:
        idx = row.get("index")
        if isinstance(idx, int) and 0 <= idx < len(items) and row.get("sentimento") in SENTIMENTS:
            summary = re.sub(r"\s*[—–]\s*", ", ", str(row.get("resumo") or "")).strip()[:300] or None
            out[idx] = {"sentiment": row["sentimento"], "summary": summary, "relevant": bool(row.get("relevante"))}
    return out


async def refresh(client_id: str, *, manual: bool = False) -> Dict[str, Any]:
    settings = await get_settings(client_id)
    if not settings["saved"] or not settings["brand_terms"]:
        raise StudioError("CLIPPING_NOT_CONFIGURED")
    if manual and settings.get("last_run_at"):
        last = datetime.fromisoformat(str(settings["last_run_at"]).replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - last < REFRESH_COOLDOWN:
            raise StudioError("CLIPPING_COOLDOWN")
    found: List[Dict[str, Any]] = []
    for kind, terms in (("marca", settings["brand_terms"]), ("concorrente", settings["competitor_terms"])):
        for term in terms:
            found.extend(await fetch_term(term, kind=kind, exclude=settings["exclude_terms"]))
    # Uma notícia, uma linha: mesma URL ou mesma manchete vinda de termos diferentes.
    seen_hash, seen_title, unique = set(), set(), []
    for item in found:
        key = _norm_title(item["title"])
        if item["url_hash"] in seen_hash or key in seen_title:
            continue
        seen_hash.add(item["url_hash"]); seen_title.add(key); unique.append(item)
    existing = set()
    if unique:
        rows = await sb_select(CLIPPINGS, select="url_hash", limit=1000,
                               filters={"client_id": f"eq.{client_id}", "url_hash": f"in.({','.join(i['url_hash'] for i in unique)})"})
        existing = {r["url_hash"] for r in rows}
    new = [i for i in unique if i["url_hash"] not in existing][:MAX_NEW_PER_RUN]
    from .studio_messages import _client_name
    labels = await _classify(await _client_name(client_id), new)
    rows = [{**item, "client_id": client_id, **labels.get(idx, {})} for idx, item in enumerate(new)]
    if rows:
        await sb_insert_many(CLIPPINGS, rows, returning="minimal")
    await sb_update(SETTINGS, filters={"client_id": f"eq.{client_id}"}, patch={"last_run_at": datetime.now(timezone.utc).isoformat()})
    print(f"[studio][clipping] client_id={client_id} found={len(unique)} new={len(rows)} classified={len(labels)}")
    return {"found": len(unique), "new": len(rows), "classified": len(labels)}


async def refresh_all() -> Dict[str, Any]:
    rows = await sb_select(SETTINGS, select="client_id", filters={"active": "eq.true"}, limit=200)
    done, failed = 0, 0
    for row in rows:
        try:
            await refresh(row["client_id"])
            done += 1
        except Exception as exc:  # noqa: BLE001 — uma empresa não para as outras
            failed += 1
            print(f"[studio][clipping] client_id={row.get('client_id')} failed={getattr(exc, 'code', type(exc).__name__)}")
    return {"clients": len(rows), "ok": done, "failed": failed}


# ------------------------------------------------------------------ leitura

async def list_clippings(client_id: str, *, kind: Optional[str] = None, sentiment: Optional[str] = None,
                         include_archived: bool = False, limit: int = 100) -> Dict[str, Any]:
    filters: Dict[str, str] = {"client_id": f"eq.{client_id}"}
    if kind in ("marca", "concorrente"):
        filters["kind"] = f"eq.{kind}"
    if sentiment in SENTIMENTS:
        filters["sentiment"] = f"eq.{sentiment}"
    if not include_archived:
        filters["status"] = "neq.arquivado"
    rows = await sb_select(CLIPPINGS, select="id,url,title,source,published_at,kind,term,sentiment,summary,relevant,status,calendar_item_id,created_at",
                           filters=filters, order="published_at.desc.nullslast", limit=max(1, min(limit, 200)))
    return {"items": rows, "week": await week_summary(client_id), "settings": await get_settings(client_id)}


async def week_summary(client_id: str) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=14)).isoformat()
    rows = await sb_select(CLIPPINGS, select="kind,sentiment,relevant,published_at,created_at", limit=1000,
                           filters={"client_id": f"eq.{client_id}", "created_at": f"gte.{since}"})

    def when(r: Dict[str, Any]) -> datetime:
        return datetime.fromisoformat(str(r.get("published_at") or r["created_at"]).replace("Z", "+00:00"))

    def count(lo: datetime, hi: datetime) -> Dict[str, int]:
        sel = [r for r in rows if lo <= when(r) < hi and r.get("relevant") is not False]
        return {"total": len(sel), "marca": sum(1 for r in sel if r["kind"] == "marca"),
                "concorrente": sum(1 for r in sel if r["kind"] == "concorrente"),
                **{s: sum(1 for r in sel if r["kind"] == "marca" and r.get("sentiment") == s) for s in SENTIMENTS}}
    current = count(now - timedelta(days=7), now + timedelta(days=1))
    previous = count(now - timedelta(days=14), now - timedelta(days=7))
    return {"current": current, "previous": previous,
            "marca_variacao": current["marca"] - previous["marca"]}


async def set_status(client_id: str, clipping_id: str, status: str) -> Dict[str, Any]:
    if status not in ("novo", "lido", "arquivado"):
        raise StudioError("STATUS_INVALID")
    rows = await sb_update(CLIPPINGS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{clipping_id}"}, patch={"status": status})
    if not rows:
        raise StudioError("CLIPPING_NOT_FOUND")
    return rows[0]


async def to_calendar(client_id: str, clipping_id: str, *, user_id: str, date_iso: Optional[str] = None) -> Dict[str, Any]:
    """Vira rascunho no Calendário com a fonte na justificativa; a equipe escreve a pauta de verdade."""
    rows = await sb_select(CLIPPINGS, select="*", filters={"client_id": f"eq.{client_id}", "id": f"eq.{clipping_id}"}, limit=1)
    if not rows:
        raise StudioError("CLIPPING_NOT_FOUND")
    clip = rows[0]
    if clip.get("calendar_item_id"):
        return {"calendar_item_id": clip["calendar_item_id"], "already": True}
    day = (date_iso or (datetime.now(SAO_PAULO).date() + timedelta(days=2)).isoformat())[:10]
    item = await create_item(client_id, {
        "scheduled_at": f"{day}T19:00:00-03:00", "format": "imagem", "pillar": None,
        "title": f"Pauta a partir da notícia: {clip['title']}"[:200],
        "hook": None, "caption_draft": None,
        "rationale": (f"Notícia ({clip.get('source') or 'fonte'}): {clip['title']}. "
                      f"{clip.get('summary') or ''} Fonte: {clip['url']}")[:1200],
    }, user_id=user_id)
    await sb_update(CLIPPINGS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{clipping_id}"},
                    patch={"status": "pauta", "calendar_item_id": item.get("id")})
    return {"calendar_item_id": item.get("id"), "already": False}
