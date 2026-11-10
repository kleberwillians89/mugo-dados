"""
Clipping Intelligence: radar de notícias por cliente, com análise contextual.

Coleta com o motor de notícias portado do CRM (``news_engine``: RSS/Atom, Google Notícias, limpeza,
deduplicação, extração de texto). A notícia vai para ``news_articles`` (catálogo público, coletado uma
vez para todas as empresas); a análise fica em ``studio_clippings``, sempre com ``client_id``: a mesma
matéria pode ser relevante para dois clientes por motivos diferentes, e um nunca vê a análise do outro.

A IA só usa título, fonte, trecho e texto extraído; evidência que não está no texto é descartada.
Sem IA (ou acima do limite diário), a notícia entra sem análise, nunca com análise inventada.
Alerta de matéria crítica vai só para a equipe Mugô (Central de Automações); cliente nunca recebe crise
automaticamente.

Busca: job ``studio-clipping`` (1x/dia) e botão "Atualizar agora" (com intervalo mínimo).
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from . import news_engine
from .ig_supabase import _request, sb_insert_many, sb_select, sb_update, sb_upsert
from .studio_calendar import StudioError, create_item

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
SETTINGS = "studio_clipping_settings"
CLIPPINGS = "studio_clippings"
ARTICLES = "news_articles"
USAGE = "clipping_ai_usage"
MAX_TERMS = 6
MAX_FEEDS = 10
MAX_PER_TERM = 15
MAX_NEW_PER_RUN = 40
MAX_TEXT_FETCH = 15
AI_BATCH = 12
REFRESH_COOLDOWN = timedelta(minutes=10)
SENTIMENTS = ("positivo", "neutro", "negativo", "misto")
CRITICALITY = ("baixa", "media", "alta", "critica")
KINDS = ("marca", "concorrente", "pessoa", "tema")
TERM_FIELDS = {"brand_terms": "marca", "competitor_terms": "concorrente", "people": "pessoa", "keywords": "tema", "themes": "tema"}
ANALYSIS_FIELDS = "relevance,criticality,main_theme,entities,opportunities,risks,justification,evidence,analyzed_at,alert_status"


# ------------------------------------------------------------------ radar

def _terms(values: Any, limit: int = MAX_TERMS) -> List[str]:
    out: List[str] = []
    for value in values or []:
        term = re.sub(r"\s+", " ", str(value or "")).strip()[:120]
        if term and term.lower() not in {t.lower() for t in out}:
            out.append(term)
    return out[:limit]


def _feeds(values: Any) -> List[str]:
    return [u for u in _terms(values, MAX_FEEDS) if re.match(r"^https://[^\s]+$", u)]


async def get_settings(client_id: str) -> Dict[str, Any]:
    rows = await sb_select(SETTINGS, select="*", filters={"client_id": f"eq.{client_id}"}, limit=1)
    row = rows[0] if rows else {}
    return {"brand_terms": row.get("brand_terms") or [], "competitor_terms": row.get("competitor_terms") or [],
            "exclude_terms": row.get("exclude_terms") or [], "people": row.get("people") or [], "keywords": row.get("keywords") or [],
            "themes": row.get("themes") or [], "feeds": row.get("feeds") or [], "region": row.get("region"),
            "relevance_criteria": row.get("relevance_criteria"), "min_relevance": row.get("min_relevance", 40),
            "ai_daily_limit": row.get("ai_daily_limit", 60),
            "active": row.get("active", True) if row else True, "last_run_at": row.get("last_run_at"), "saved": bool(row)}


async def save_settings(client_id: str, data: Dict[str, Any], *, user_id: str) -> Dict[str, Any]:
    row = {"client_id": client_id, "brand_terms": _terms(data.get("brand_terms")),
           "competitor_terms": _terms(data.get("competitor_terms")), "exclude_terms": _terms(data.get("exclude_terms")),
           "active": bool(data.get("active", True)), "updated_by": user_id, "updated_at": datetime.now(timezone.utc).isoformat()}
    # Campos do radar só entram quando enviados (a tela antiga manda só marca/concorrentes/ignorar).
    for key in ("people", "keywords", "themes"):
        if key in data:
            row[key] = _terms(data.get(key))
    if "feeds" in data:
        row["feeds"] = _feeds(data.get("feeds"))
    if "region" in data:
        row["region"] = (str(data.get("region") or "").strip()[:120] or None)
    if "relevance_criteria" in data:
        row["relevance_criteria"] = (str(data.get("relevance_criteria") or "").strip()[:1000] or None)
    if "min_relevance" in data:
        row["min_relevance"] = max(0, min(100, int(data.get("min_relevance") or 0)))
    if not row["brand_terms"]:
        raise StudioError("CLIPPING_TERMS_REQUIRED")
    await sb_upsert(SETTINGS, [row], on_conflict="client_id")
    return await get_settings(client_id)


# ------------------------------------------------------------------ coleta

url_hash = news_engine.url_hash


def parse_news_rss(xml_text: str, *, term: str, kind: str) -> List[Dict[str, Any]]:
    """Google Notícias/RSS → itens do radar (mesmas regras do parseFeed do CRM)."""
    return [{**item, "url_hash": url_hash(item["url"]), "kind": kind, "term": term}
            for item in news_engine.parse_feed(xml_text, limit=MAX_PER_TERM)]


def _excluded(item: Dict[str, Any], exclude: List[str]) -> bool:
    text = news_engine.fold(f"{item.get('title')} {item.get('excerpt') or ''}")
    return any(news_engine.fold(x) and news_engine.fold(x) in text for x in exclude)


async def fetch_term(term: str, *, kind: str, exclude: List[str]) -> List[Dict[str, Any]]:
    items = await news_engine.GoogleNewsProvider().search(term, exclude=exclude)
    return [{**i, "url_hash": url_hash(i["url"]), "kind": kind, "term": term} for i in items if not _excluded(i, exclude)]


async def fetch_feeds(settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fontes próprias do radar: entra só a matéria que cita algum termo do cliente."""
    terms = [(t, kind) for field, kind in TERM_FIELDS.items() for t in settings.get(field) or []]
    out: List[Dict[str, Any]] = []
    for feed in settings.get("feeds") or []:
        for item in await news_engine.FeedProvider().read(feed):
            text = news_engine.fold(f"{item['title']} {item.get('excerpt') or ''}")
            hit = next(((t, k) for t, k in terms if news_engine.fold(t) and news_engine.fold(t) in text), None)
            if hit and not _excluded(item, settings.get("exclude_terms") or []):
                out.append({**item, "url_hash": url_hash(item["url"]), "kind": hit[1], "term": hit[0]})
    return out


async def store_articles(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Catálogo compartilhado: só busca o texto da matéria que ainda não está nele (cache entre empresas)."""
    if not items:
        return {}
    hashes = [i["url_hash"] for i in items]
    known = {r["url_hash"]: r for r in await sb_select(ARTICLES, select="url_hash,excerpt,content_text",
                                                       filters={"url_hash": f"in.({','.join(hashes)})"}, limit=len(hashes))}
    fresh = [i for i in items if i["url_hash"] not in known]
    # Link do Google Notícias é página de redirecionamento: não tem texto para extrair, fica o trecho do feed.
    for item in [i for i in fresh if "news.google." not in i["url"]][:MAX_TEXT_FETCH]:
        item["content_text"] = await news_engine.fetch_article_text(item["url"]) or None
    rows = [{"url_hash": i["url_hash"], "url": i["url"], "title": i["title"], "source": i.get("source"), "published_at": i.get("published_at"),
             "excerpt": i.get("excerpt"), "content_text": i.get("content_text"), "provider": "google_news" if "news.google." in i["url"] else "rss"}
            for i in fresh]
    if rows:
        await _request("POST", f"/{ARTICLES}", params={"on_conflict": "url_hash"}, json=rows,
                       headers={"Prefer": "resolution=ignore-duplicates,return=minimal"})
    return {**known, **{r["url_hash"]: r for r in rows}}


# ------------------------------------------------------------------ análise

async def _ai_budget(client_id: str, limit: int) -> int:
    today = datetime.now(SAO_PAULO).date().isoformat()
    rows = await sb_select(USAGE, select="items", filters={"client_id": f"eq.{client_id}", "day": f"eq.{today}"}, limit=1)
    return max(0, int(limit) - int((rows[0] if rows else {}).get("items") or 0))


async def _spend(client_id: str, items: int) -> None:
    today = datetime.now(SAO_PAULO).date().isoformat()
    rows = await sb_select(USAGE, select="calls,items", filters={"client_id": f"eq.{client_id}", "day": f"eq.{today}"}, limit=1)
    current = rows[0] if rows else {"calls": 0, "items": 0}
    await sb_upsert(USAGE, [{"client_id": client_id, "day": today, "calls": int(current["calls"]) + 1,
                             "items": int(current["items"]) + items}], on_conflict="client_id,day")


def _context(brand: str, settings: Dict[str, Any]) -> str:
    parts = [f"MARCA: {brand} (variações: {', '.join(settings.get('brand_terms') or [])})"]
    for label, key in (("CONCORRENTES", "competitor_terms"), ("PESSOAS E PORTA-VOZES", "people"),
                       ("PALAVRAS-CHAVE", "keywords"), ("TEMAS ESTRATÉGICOS", "themes")):
        if settings.get(key):
            parts.append(f"{label}: {', '.join(settings[key])}")
    if settings.get("region"):
        parts.append(f"REGIÃO DE INTERESSE: {settings['region']}")
    if settings.get("relevance_criteria"):
        parts.append(f"CRITÉRIOS DE RELEVÂNCIA: {settings['relevance_criteria']}")
    return "\n".join(parts)


def _clean(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\s*[—–]\s*", ", ", str(value or ""))).strip()[:limit]


def _list(values: Any, limit: int = 4, size: int = 200) -> List[str]:
    return [c for c in (_clean(v, size) for v in (values or [])[:limit]) if c] if isinstance(values, list) else []


async def _classify(context: str, items: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """Análise contextual por cliente. Saída validada: índice existente, enums, evidência presente no texto."""
    if not items:
        return {}
    from .studio_llm import INT, STR, arr, llm_json, obj
    schema = obj({"items": arr(obj({
        "index": INT, "resumo": STR, "tema": STR, "entidades": arr(STR), "relevancia": INT,
        "sentimento": {"type": "string", "enum": list(SENTIMENTS)}, "criticidade": {"type": "string", "enum": list(CRITICALITY)},
        "oportunidades": arr(STR), "riscos": arr(STR), "justificativa": STR, "evidencias": arr(STR)}))})
    lines = "\n\n".join(
        f"[{i}] ({it['kind']}: {it['term']}) {it['title']} | fonte: {it.get('source') or 'desconhecida'} | data: {it.get('published_at') or 's/d'}\n"
        f"TEXTO: {(it.get('content_text') or it.get('excerpt') or '')[:1200]}" for i, it in enumerate(items))
    try:
        # Matérias de terceiros podem citar concorrentes (às vezes outro cliente): aqui não é vazamento.
        data = await llm_json(leak_check=False,
            instructions=("Você faz clipping para uma agência. Analise cada matéria SÓ em relação ao cliente descrito no CONTEXTO "
                          "(a mesma matéria pode importar para outro cliente por outros motivos). Use apenas título, fonte e TEXTO; "
                          "não invente fatos, números nem conclusões. relevancia: 0 a 100 para ESTE cliente (homônimo ou citação de "
                          "passagem = baixa). sentimento em relação ao cliente (ou ao concorrente, quando a matéria é dele). criticidade: "
                          "critica só para risco reputacional sério e imediato. oportunidades e riscos: ações de comunicação concretas, "
                          "vazias se não houver. evidencias: trechos COPIADOS literalmente do título ou do TEXTO que sustentam a análise."),
            prompt=f"CONTEXTO DO CLIENTE:\n{context}\n\nMATÉRIAS:\n{lines}", schema_name="clipping_intelligence", schema=schema,
            temperature=0.1, timeout=60)
    except StudioError:
        return {}
    out: Dict[int, Dict[str, Any]] = {}
    for row in data.get("items") or []:
        idx = row.get("index")
        if not (isinstance(idx, int) and 0 <= idx < len(items)) or row.get("sentimento") not in SENTIMENTS or row.get("criticidade") not in CRITICALITY:
            continue
        item = items[idx]
        relevance = max(0, min(100, int(row.get("relevancia") or 0)))
        evidence = news_engine.evidence_in(row.get("evidencias"), item["title"], item.get("excerpt"), item.get("content_text"))
        if not evidence:  # sem trecho que sustente, a análise não pode afirmar alta relevância nem crise
            relevance = min(relevance, 40)
        out[idx] = {
            "sentiment": row["sentimento"], "summary": _clean(row.get("resumo"), 700) or None,
            "main_theme": _clean(row.get("tema"), 80) or None, "entities": _list(row.get("entidades"), 8, 80),
            "relevance": relevance, "criticality": row["criticidade"] if evidence else "baixa",
            "opportunities": _list(row.get("oportunidades")), "risks": _list(row.get("riscos")),
            "justification": _clean(row.get("justificativa"), 700) or None, "evidence": evidence,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }
    return out


def needs_alert(row: Dict[str, Any]) -> bool:
    return row.get("relevance") is not None and row["relevance"] >= 60 and (
        row.get("criticality") == "critica" or (row.get("criticality") == "alta" and row.get("sentiment") == "negativo"))


async def _alert_team(client_id: str, brand: str, rows: List[Dict[str, Any]]) -> int:
    """Matéria crítica → fila da Central de Automações, SÓ equipe Mugô. Idempotente por empresa + matéria."""
    critical = [r for r in rows if needs_alert(r)]
    if not critical:
        return 0
    try:
        from . import automations
        definition = (await automations.load_definitions()).get("clipping_critico")
        if not definition or not definition.get("automation_enabled") or definition["owner"] != "dados":
            return 0
        team = await automations.team_members("receives_campaign_alerts")
        queued = 0
        for row in critical:
            for member in team:
                out = await automations.enqueue(definition, client_id=client_id, recipient={**member, "team_member": True},
                                                source_type="clipping", source_id=row["url_hash"],
                                                params={"nome": str(member["name"]).split()[0], "marca": brand,
                                                        "titulo": row["title"][:60], "criticidade": row["criticality"]})
                queued += 1 if out else 0
            row["alert_status"] = "enfileirado"
        return queued
    except Exception as exc:  # noqa: BLE001 — alerta é complemento; a coleta vale sem ele
        print(f"[studio][clipping] alerta_falhou client_id={client_id} {type(exc).__name__}")
        return 0


async def refresh(client_id: str, *, manual: bool = False) -> Dict[str, Any]:
    settings = await get_settings(client_id)
    if not settings["saved"] or not settings["brand_terms"]:
        raise StudioError("CLIPPING_NOT_CONFIGURED")
    if manual and settings.get("last_run_at"):
        last = datetime.fromisoformat(str(settings["last_run_at"]).replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - last < REFRESH_COOLDOWN:
            raise StudioError("CLIPPING_COOLDOWN")
    found: List[Dict[str, Any]] = []
    for field, kind in TERM_FIELDS.items():
        for term in settings.get(field) or []:
            found.extend(await fetch_term(term, kind=kind, exclude=settings["exclude_terms"]))
    if settings.get("feeds"):
        found.extend(await fetch_feeds(settings))
    unique = news_engine.dedupe(found)
    existing = set()
    if unique:
        rows = await sb_select(CLIPPINGS, select="url_hash", limit=1000,
                               filters={"client_id": f"eq.{client_id}", "url_hash": f"in.({','.join(i['url_hash'] for i in unique)})"})
        existing = {r["url_hash"] for r in rows}
    new = news_engine.balance_by_source([i for i in unique if i["url_hash"] not in existing], max_items=MAX_NEW_PER_RUN)
    catalog: Dict[str, Dict[str, Any]] = {}
    try:
        catalog = await store_articles(new)
    except Exception as exc:  # noqa: BLE001 — sem catálogo (migração pendente) a análise usa o trecho do feed
        print(f"[studio][clipping] catalogo_indisponivel {type(exc).__name__}")
    for item in new:
        item["content_text"] = item.get("content_text") or (catalog.get(item["url_hash"]) or {}).get("content_text")
    from .studio_messages import _client_name
    brand = await _client_name(client_id)
    labels: Dict[int, Dict[str, Any]] = {}
    try:
        budget = await _ai_budget(client_id, settings.get("ai_daily_limit", 60))
    except Exception:  # noqa: BLE001
        budget = AI_BATCH
    analyzable = new[:budget]
    context = _context(brand, settings)
    for start in range(0, len(analyzable), AI_BATCH):
        batch = analyzable[start:start + AI_BATCH]
        result = await _classify(context, batch)
        labels.update({start + k: v for k, v in result.items()})
        try:
            await _spend(client_id, len(batch))
        except Exception:  # noqa: BLE001
            pass
    rows = []
    for idx, item in enumerate(new):
        row = {k: item.get(k) for k in ("url", "url_hash", "title", "source", "published_at", "kind", "term")}
        label = labels.get(idx)
        if label:
            row.update(label)
            row["relevant"] = label["relevance"] >= int(settings.get("min_relevance", 40))
        rows.append({**row, "client_id": client_id})
    alerts = await _alert_team(client_id, brand, rows)
    if rows:
        await sb_insert_many(CLIPPINGS, rows, returning="minimal")
    await sb_update(SETTINGS, filters={"client_id": f"eq.{client_id}"}, patch={"last_run_at": datetime.now(timezone.utc).isoformat()})
    print(f"[studio][clipping] client_id={client_id} found={len(unique)} new={len(rows)} classified={len(labels)} alerts={alerts}")
    return {"found": len(unique), "new": len(rows), "classified": len(labels), "alerts": alerts,
            "not_analyzed": len(rows) - len(labels)}


PENDING_LOOKBACK = timedelta(days=120)


async def analyze_pending(client_id: str, *, limit: int = AI_BATCH * 2, ignore_budget: bool = False) -> Dict[str, int]:
    """Matéria que entrou sem análise (IA sem crédito, fora do ar ou acima do limite do dia) é analisada depois.

    Mesma análise da busca (relevância, sentimento, criticidade, evidência). Para na primeira rodada sem resposta
    da IA. ``ignore_budget``: botão "Analisar agora" da equipe, que limpa o atraso sem esperar o limite diário."""
    settings = await get_settings(client_id)
    out = {"news_analyzed": 0, "news_pending": 0}
    if not settings["saved"]:
        return out
    since = (datetime.now(timezone.utc) - PENDING_LOOKBACK).isoformat()
    pending = await sb_select(CLIPPINGS, select="id,url,url_hash,title,source,published_at,kind,term", order="published_at.desc.nullslast",
                              limit=500, filters={"client_id": f"eq.{client_id}", "analyzed_at": "is.null", "created_at": f"gte.{since}"})
    out["news_pending"] = len(pending)
    if not pending:
        return out
    cap = limit if ignore_budget else min(limit, await _ai_budget(client_id, settings.get("ai_daily_limit", 60)))
    todo = pending[:max(0, cap)]
    if not todo:
        return out
    try:
        texts = await sb_select(ARTICLES, select="url_hash,excerpt,content_text", limit=len(todo),
                                filters={"url_hash": f"in.({','.join(r['url_hash'] for r in todo)})"})
    except Exception:  # noqa: BLE001 — sem catálogo, analisa só pelo título
        texts = []
    by_hash = {t["url_hash"]: t for t in texts}
    items = [{**r, **{k: (by_hash.get(r["url_hash"]) or {}).get(k) for k in ("excerpt", "content_text")}} for r in todo]
    from .studio_messages import _client_name
    brand = await _client_name(client_id)
    context = _context(brand, settings)
    for start in range(0, len(items), AI_BATCH):
        batch = items[start:start + AI_BATCH]
        labels = await _classify(context, batch)
        if not labels:
            break
        try:
            await _spend(client_id, len(batch))
        except Exception:  # noqa: BLE001
            pass
        rows = []
        for idx, label in labels.items():
            row = {**batch[idx], **label, "relevant": label["relevance"] >= int(settings.get("min_relevance", 40))}
            rows.append(row)
        await _alert_team(client_id, brand, rows)
        for row in rows:
            patch = {k: row[k] for k in ("sentiment", "summary", "main_theme", "entities", "relevance", "criticality", "opportunities",
                                         "risks", "justification", "evidence", "analyzed_at", "relevant")}
            if row.get("alert_status"):
                patch["alert_status"] = row["alert_status"]
            await sb_update(CLIPPINGS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{row['id']}"}, patch=patch, returning="minimal")
            out["news_analyzed"] += 1
    out["news_pending"] = len(pending) - out["news_analyzed"]
    return out


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

BASE_FIELDS = "id,url,url_hash,title,source,published_at,kind,term,sentiment,summary,relevant,status,calendar_item_id,created_at"


async def list_clippings(client_id: str, *, kind: Optional[str] = None, sentiment: Optional[str] = None,
                         include_archived: bool = False, limit: int = 100, q: Optional[str] = None,
                         theme: Optional[str] = None, min_relevance: Optional[int] = None,
                         criticality: Optional[str] = None) -> Dict[str, Any]:
    filters: Dict[str, str] = {"client_id": f"eq.{client_id}"}
    if kind in KINDS:
        filters["kind"] = f"eq.{kind}"
    if sentiment in SENTIMENTS:
        filters["sentiment"] = f"eq.{sentiment}"
    if criticality in CRITICALITY:
        filters["criticality"] = f"eq.{criticality}"
    if min_relevance:
        filters["relevance"] = f"gte.{int(min_relevance)}"
    if theme:
        filters["main_theme"] = f"ilike.*{_safe(theme)}*"
    if q and _safe(q):
        filters["or"] = f"(title.ilike.*{_safe(q)}*,summary.ilike.*{_safe(q)}*,source.ilike.*{_safe(q)}*)"
    if not include_archived:
        filters["status"] = "neq.arquivado"
    try:
        rows = await sb_select(CLIPPINGS, select=f"{BASE_FIELDS},{ANALYSIS_FIELDS}", filters=filters,
                               order="published_at.desc.nullslast", limit=max(1, min(limit, 200)))
    except Exception:  # noqa: BLE001 — antes da migração 000063 só existem as colunas antigas
        rows = await sb_select(CLIPPINGS, select=BASE_FIELDS, filters={k: v for k, v in filters.items() if k in {"client_id", "kind", "sentiment", "status"}},
                               order="published_at.desc.nullslast", limit=max(1, min(limit, 200)))
    return {"items": rows, "week": await week_summary(client_id), "settings": await get_settings(client_id)}


def _safe(text: Any) -> str:
    return "".join(ch for ch in str(text or "") if ch.isalnum() or ch in " ._-")[:60].strip()


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


# ------------------------------------------------------------------ painel, relatórios e exportação

PERIODS = {"diario": 1, "semanal": 7, "mensal": 30}
FOCUS = {"cobertura": ("marca", "pessoa"), "concorrentes": ("concorrente",), "setor": ("tema",), "riscos": KINDS}


async def period_rows(client_id: str, days: int, *, relevant_only: bool = False) -> List[Dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = await sb_select(CLIPPINGS, select=f"{BASE_FIELDS},{ANALYSIS_FIELDS}", limit=2000, order="published_at.desc.nullslast",
                           filters={"client_id": f"eq.{client_id}", "created_at": f"gte.{since}", "status": "neq.arquivado"})
    rows = [r for r in rows if r.get("client_id", client_id) == client_id]
    return [r for r in rows if r.get("relevant") is not False] if relevant_only else rows


def _day(row: Dict[str, Any]) -> str:
    moment = datetime.fromisoformat(str(row.get("published_at") or row["created_at"]).replace("Z", "+00:00"))
    return moment.astimezone(SAO_PAULO).date().isoformat()


def insights_from(rows: List[Dict[str, Any]], days: int) -> Dict[str, Any]:
    def count(key_fn) -> List[Dict[str, Any]]:
        acc: Dict[str, int] = {}
        for r in rows:
            key = key_fn(r)
            if key:
                acc[key] = acc.get(key, 0) + 1
        return [{"key": k, "count": v} for k, v in sorted(acc.items(), key=lambda kv: -kv[1])]
    today = datetime.now(SAO_PAULO).date()
    timeline = {(today - timedelta(days=i)).isoformat(): 0 for i in range(days)}
    for r in rows:
        if _day(r) in timeline:
            timeline[_day(r)] += 1
    return {
        "total": len(rows), "analyzed": sum(1 for r in rows if r.get("analyzed_at")),
        "sentiment": count(lambda r: r.get("sentiment")), "themes": count(lambda r: r.get("main_theme"))[:10],
        "sources": count(lambda r: r.get("source"))[:10],
        "mentions": count(lambda r: f"{r['kind']}:{r['term']}" if r.get("kind") in ("marca", "concorrente") else None),
        "timeline": [{"day": d, "count": c} for d, c in sorted(timeline.items())],
        "critical": [{k: r.get(k) for k in ("id", "title", "url", "source", "published_at", "criticality", "relevance", "sentiment", "risks")}
                     for r in rows if needs_alert(r)][:10],
    }


async def insights(client_id: str, days: int, *, relevant_only: bool) -> Dict[str, Any]:
    return insights_from(await period_rows(client_id, days, relevant_only=relevant_only), days)


def _report_fallback(rows: List[Dict[str, Any]], label: str) -> Dict[str, Any]:
    top = sorted(rows, key=lambda r: -(r.get("relevance") or 0))[:5]
    return {"summary": f"{len(rows)} matéria(s) no {label}.", "highlights": [{"text": r["title"], "url": r["url"]} for r in top],
            "risks": [{"text": risk, "url": r["url"]} for r in rows for risk in (r.get("risks") or [])][:5],
            "opportunities": [{"text": o, "url": r["url"]} for r in rows for o in (r.get("opportunities") or [])][:5], "ai": False}


async def build_report(client_id: str, period: str, focus: str) -> Dict[str, Any]:
    """Relatório só com matérias coletadas e analisadas; todo item cita a URL de uma delas (validado)."""
    if period not in PERIODS or focus not in FOCUS:
        raise StudioError("REPORT_INVALID")
    settings = await get_settings(client_id)
    rows = [r for r in await period_rows(client_id, PERIODS[period], relevant_only=True) if r.get("kind") in FOCUS[focus]]
    if focus == "riscos":
        rows = [r for r in rows if r.get("risks") or r.get("criticality") in ("alta", "critica")]
    label = {"diario": "último dia", "semanal": "últimos 7 dias", "mensal": "últimos 30 dias"}[period]
    if not rows:
        return {"period": period, "focus": focus, "items": 0, "summary": f"Nenhuma matéria relevante no {label}.", "highlights": [], "risks": [], "opportunities": [], "sources": []}
    from .studio_llm import STR, arr, llm_json, obj
    from .studio_messages import _client_name
    brand = await _client_name(client_id)
    allowed = {r["url"]: r for r in rows}
    ref = obj({"text": STR, "url": STR})
    lines = "\n".join(f"- {r['title']} ({r.get('source') or 'fonte'}, {_day(r)}) [{r['kind']}: {r['term']}] relevância {r.get('relevance')}, "
                      f"{r.get('sentiment') or 'sem análise'}. {r.get('summary') or ''} URL: {r['url']}" for r in rows[:60])
    try:
        data = await llm_json(client_id=client_id, 
            instructions=("Escreva um relatório de clipping para a agência usando SOMENTE as matérias listadas. Cada destaque, risco e "
                          "oportunidade precisa citar a URL exata de uma matéria da lista. Não invente fatos, números ou matérias."),
            prompt=f"{_context(brand, settings)}\nFOCO: {focus}\nPERÍODO: {label}\nMATÉRIAS:\n{lines}",
            schema_name="clipping_report", schema=obj({"summary": STR, "highlights": arr(ref), "risks": arr(ref), "opportunities": arr(ref)}),
            temperature=0.2, timeout=60)
        def keep(values: Any) -> List[Dict[str, str]]:
            return [{"text": _clean(v.get("text"), 400), "url": v["url"]} for v in (values or [])[:8]
                    if isinstance(v, dict) and v.get("url") in allowed and _clean(v.get("text"), 400)]
        report = {"summary": _clean(data.get("summary"), 1500), "highlights": keep(data.get("highlights")), "risks": keep(data.get("risks")),
                  "opportunities": keep(data.get("opportunities")), "ai": True}
        if not report["summary"]:
            report = _report_fallback(rows, label)
    except StudioError:
        report = _report_fallback(rows, label)
    return {"period": period, "focus": focus, "items": len(rows), **report,
            "sources": [{"title": r["title"], "url": r["url"], "source": r.get("source")} for r in rows[:30]]}


def export_csv(rows: List[Dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["data", "veículo", "título", "url", "tipo", "termo", "relevância", "sentimento", "criticidade", "tema", "resumo"])
    for r in rows:
        writer.writerow([_day(r), r.get("source") or "", r["title"], r["url"], r["kind"], r["term"], r.get("relevance") if r.get("relevance") is not None else "",
                         r.get("sentiment") or "", r.get("criticality") or "", r.get("main_theme") or "", r.get("summary") or ""])
    return buffer.getvalue()
