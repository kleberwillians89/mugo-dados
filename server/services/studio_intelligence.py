"""Inteligência de conteúdo do Studio: o que a marca JÁ tem de dados, num pacote só.

Todo motor de conteúdo (calendário, redação, ganchos, roteiro, chat de
estratégia, Brand Manager, Mídia On, mensagens) parte deste pacote, para que a
IA escreva a partir de fatos da conta e não de clichês:

* perfil da marca e contexto do negócio (escritos pela equipe);
* KPIs do período e campanhas que mais venderam (snapshot da Inteligência);
* posts que mais e menos alcançaram em relação ao próprio formato, com curtidas, comentários, salvamentos e
  compartilhamentos separados, dia e hora, e a pauta do MUGOVERSO que gerou o post;
* anúncio por anúncio nos últimos 12 meses (não só a campanha): melhores e piores, até quando rodaram, e o texto
  e o título dos criados no Mídia On;
* melhores dias e horários (posting_times);
* metas do mês e a última análise salva;
* aprendizado com o cliente: o que ele aprovou e o que pediu para ajustar;
* CÉREBRO DA MARCA (ligação entre módulos): vendas por origem, plano do Mídia On do mês,
  campanhas ativas da Redação, notícias relevantes do Clipping e o andamento do Calendário.
  Assim a pauta, a copy, o anúncio e a mensagem de sexta seguem a mesma linha.
* MUNDO DO CLIENTE: saúde da marca (índice, sentimento, assuntos e alertas), voz do público
  (comentários, Direct e notícias agregados), concorrentes do Clipping e produtos que mais vendem.
* O QUE A EQUIPE JÁ DECIDIU: briefings aprovados, planejamentos (grande ideia, estratégia, fases, KPIs) e
  eventos que vêm por aí, e o material da marca na Biblioteca (logo, identidade, produto, fotos e vídeos da marca,
  referências e documentos, por nome). Arte de post não conta.

Nada é cortado em silêncio: quando o pacote passa do limite do prompt, as seções menos importantes são
RESUMIDAS primeiro (listas e textos encurtados) e só depois omitidas, e o prompt diz à IA o que foi resumido.

Cada fonte é lida com limite de tempo; fonte que falha vira "lacuna" e o
pacote segue. Nada aqui chama a IA nem expõe dado de comprador.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from .ig_supabase import sb_select

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
SOURCE_TIMEOUT = 12.0
CACHE_SECONDS = 180          # curto: o que a equipe acabou de mudar entra na próxima geração
MAX_PROMPT_CHARS = 24000
_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}

# Mesmo filtro do MCP: texto com cara de e-mail, CPF/CNPJ ou telefone sai inteiro.
_PERSONAL = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.-]+|\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b|\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"
    r"|\(?\b\d{2}\)?[\s-]?9?\d{4}[\s-]?\d{4}\b|\d{10,}"
)
METRIC_IDS = (
    "revenue", "orders", "average_ticket", "investment", "roas", "cpa", "ctr", "cpc", "sessions",
    "conversion_rate", "followers_growth", "instagram_reach", "instagram_profile_views", "new_customers",
    "repeat_rate",
)


def clean_text(value: Any, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text or _PERSONAL.search(text):
        return ""
    return text[:limit]


def _num(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return round(out, 2) if out == out else None  # NaN fora


async def _safe(name: str, gaps: List[str], fn: Callable[[], Awaitable[Any]], default: Any) -> Any:
    try:
        return await asyncio.wait_for(fn(), timeout=SOURCE_TIMEOUT)
    except Exception as exc:  # fonte indisponível não derruba o pacote
        print(f"[studio][intel] fonte={name} erro={exc.__class__.__name__}")
        gaps.append(name)
        return default


# --------------------------------------------------------------------------
# Fontes
# --------------------------------------------------------------------------

async def _profile(client_id: str) -> Dict[str, Any]:
    from .studio_calendar import load_profile
    return (await load_profile(client_id)).get("profile") or {}


async def _business(client_id: str) -> Dict[str, Any]:
    from .business_context import load_business_context
    from .brand_knowledge import knowledge_for_prompt
    context = (await load_business_context(client_id)).get("context") or {}
    out = {k: clean_text(v, 800) for k, v in context.items() if clean_text(v, 800)}
    knowledge = await knowledge_for_prompt(client_id)
    if knowledge:
        out["conhecimento_da_marca"] = knowledge  # documentos enviados pela equipe/cliente, já consolidados
    return out


async def _snapshot(client_id: str, start: str, end: str) -> Dict[str, Any]:
    from .intelligence import calculate_intelligence_snapshot
    snap = await calculate_intelligence_snapshot(client_id=client_id, start=start, end=end,
                                                 include_commerce_details=False, include_external_research=False)
    metrics = []
    for row in snap.get("metrics") or []:
        if row.get("id") in METRIC_IDS and _num(row.get("value")) is not None:
            metrics.append({"id": row["id"], "rotulo": clean_text(row.get("label"), 60) or row["id"],
                            "valor": _num(row.get("value")), "anterior": _num(row.get("previous_value")),
                            "variacao_pct": _num(row.get("variation_percent")), "fonte": row.get("source")})
    campaigns = []
    for row in (snap.get("top_campaigns") or [])[:8]:
        name = clean_text(row.get("name") or row.get("campaign_name"), 120)
        spend, revenue, conv = _num(row.get("spend")) or 0, _num(row.get("revenue")) or 0, _num(row.get("conversions")) or 0
        if name and spend:
            campaigns.append({"campanha": name, "investimento": spend, "receita": revenue, "conversoes": conv,
                              "roas": round(revenue / spend, 2) if spend else None,
                              "custo_por_conversao": round(spend / conv, 2) if conv else None})
    funnel = next((c.get("funnel") for c in snap.get("crossings") or []
                   if isinstance(c, dict) and c.get("id") == "commerce_funnel" and c.get("status") == "available"), None)
    return {"metricas": metrics, "campanhas": campaigns,
            "funil_do_site": {k: _num(v) for k, v in (funnel or {}).items() if k != "status" and _num(v) is not None},
            "qualidade": (snap.get("quality") or {}).get("status")}


WEEKDAYS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
BREAKDOWN = (("curtidas", "likes"), ("comentarios", "comments"), ("salvamentos", "saved"), ("compartilhamentos", "shares"))
TOP_POSTS, WORST_POSTS = 10, 5


def _int(value: Any) -> Optional[int]:
    number = _num(value)
    return int(number) if number is not None else None


async def _pautas_by_media(client_id: str, media_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Pauta do Calendário que gerou cada post publicado pelo MUGOVERSO (pauta, gancho, pilar)."""
    ids = [m for m in media_ids if re.fullmatch(r"\d{5,40}", str(m or ""))]
    if not ids:
        return {}
    rows = await sb_select("studio_calendar_items", select="published_media_id,title,hook,pillar,format", limit=len(ids),
                           filters={"client_id": f"eq.{client_id}", "published_media_id": f"in.({','.join(ids)})"})
    return {str(r["published_media_id"]): {k: v for k, v in {
        "pauta": clean_text(r.get("title"), 160), "gancho": clean_text(r.get("hook"), 160),
        "pilar": clean_text(r.get("pillar"), 80)}.items() if v} for r in rows if r.get("published_media_id")}


async def _posts(client_id: str, days: int) -> Dict[str, Any]:
    """Posts do Instagram que mais e menos alcançaram em relação ao próprio formato, com curtidas, comentários,
    salvamentos e compartilhamentos separados, dia e hora, e a pauta do MUGOVERSO que gerou o post (quando gerou)."""
    from .posting_times import score_posts
    since = datetime.now(timezone.utc).date() - timedelta(days=days)
    rows = await sb_select("ig_media", select="media_id,media_type,media_product_type,timestamp,insights_json,caption",
                           filters={"client_id": f"eq.{client_id}", "timestamp": f"gte.{since.isoformat()}"},
                           order="timestamp.desc", limit=300)
    insights = {str(r.get("media_id")): (r.get("insights_json") or {}) for r in rows if r.get("media_id")}
    scored = sorted(score_posts(rows, start=since, end=date.max), key=lambda p: p["reach_index"], reverse=True)
    best = scored[:TOP_POSTS]
    worst = scored[max(TOP_POSTS, len(scored) - WORST_POSTS):]
    try:
        pautas = await _pautas_by_media(client_id, [str(p.get("media_id")) for p in best + worst])
    except Exception:  # noqa: BLE001 - sem a ligação com a pauta, o resto segue
        pautas = {}

    def counts(p: Dict[str, Any]) -> Dict[str, int]:
        data = insights.get(str(p.get("media_id"))) or {}
        return {label: value for label, key in BREAKDOWN if (value := _int(data.get(key))) is not None}

    def view(p: Dict[str, Any]) -> Dict[str, Any]:
        detail = counts(p)
        out: Dict[str, Any] = {"formato": p["format"], "alcance": p["reach"], "alcance_vs_media_do_formato": round(p["reach_index"], 2),
                               "interacoes": p.get("interactions"), **detail,
                               "dia": WEEKDAYS[p["weekday"]], "hora": p["hour"], "legenda": clean_text(p.get("caption"), 220)}
        if detail.get("salvamentos") is not None and p["reach"]:
            out["salvamentos_por_mil_alcance"] = round(detail["salvamentos"] / p["reach"] * 1000, 1)
        pauta = pautas.get(str(p.get("media_id")))
        if pauta:
            out["pauta_do_mugoverso"] = pauta
        return out

    averages: Dict[str, float] = {}
    for label, key in BREAKDOWN:
        values = [v for p in scored if (v := _int((insights.get(str(p.get("media_id"))) or {}).get(key))) is not None]
        if values:
            averages[label] = round(sum(values) / len(values), 1)
    return {"analisados": len(scored), "media_por_post": averages, "melhores": [view(p) for p in best],
            "piores": [view(p) for p in worst],
            "ligados_a_pauta": len(pautas)}


PAID_DAYS = 365
PAGE = 1000          # o Supabase devolve no máximo 1000 linhas por vez
MAX_PAGES = 30
PAID_SECONDS = 8.0     # abaixo do limite de 12 s por fonte


async def _paid_creatives(client_id: str, days: int = PAID_DAYS) -> Dict[str, Any]:
    """Anúncio por anúncio (não só a campanha), nos últimos 12 meses: o que performou melhor e pior, até quando rodou,
    e o texto e o título quando o anúncio foi criado no Mídia On."""
    since = (datetime.now(SAO_PAULO).date() - timedelta(days=days)).isoformat()
    rows: List[Dict[str, Any]] = []
    started = time.monotonic()
    for page in range(MAX_PAGES):  # mais recentes primeiro: se a conta for enorme, o que fica de fora é o mais antigo
        if page and time.monotonic() - started > PAID_SECONDS:
            break  # fica com o que leu (o mais recente) em vez de perder a seção inteira no limite de tempo
        chunk = await sb_select("ad_daily_stats", select="ad_id,ad_name,campaign_name,stat_date,spend,impressions,clicks,conversions,revenue",
                                filters={"client_id": f"eq.{client_id}", "stat_date": f"gte.{since}"},
                                order="stat_date.desc", limit=PAGE, offset=page * PAGE)
        rows.extend(chunk)
        if len(chunk) < PAGE:
            break
    ads: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        ad_id = str(r.get("ad_id") or "")
        if not ad_id:
            continue
        a = ads.setdefault(ad_id, {"anuncio": clean_text(r.get("ad_name"), 120), "campanha": clean_text(r.get("campaign_name"), 120),
                                   "investimento": 0.0, "impressoes": 0.0, "cliques": 0.0, "conversoes": 0.0, "receita": 0.0,
                                   "rodou_de": None, "rodou_ate": None})
        for field, key in (("investimento", "spend"), ("impressoes", "impressions"), ("cliques", "clicks"),
                           ("conversoes", "conversions"), ("receita", "revenue")):
            a[field] += _num(r.get(key)) or 0.0
        day = str(r.get("stat_date") or "")[:10]
        if day and (_num(r.get("spend")) or 0) > 0:
            a["rodou_de"] = min(a["rodou_de"] or day, day)
            a["rodou_ate"] = max(a["rodou_ate"] or day, day)
    spent = [dict(a, ad_id=k) for k, a in ads.items() if a["investimento"] >= 20]
    if not spent:
        return {}
    for a in spent:
        a["ctr_pct"] = round(a["cliques"] / a["impressoes"] * 100, 2) if a["impressoes"] else None
        a["custo_por_conversao"] = round(a["investimento"] / a["conversoes"], 2) if a["conversoes"] else None
        a["roas"] = round(a["receita"] / a["investimento"], 2) if a["receita"] else None
        for key in ("investimento", "receita"):
            a[key] = round(a[key], 2)
        for key in ("impressoes", "cliques", "conversoes"):
            a[key] = int(a[key])
    if any(a["roas"] for a in spent):
        metric, rank = "roas", lambda a: a["roas"] or 0
    elif any(a["conversoes"] for a in spent):
        metric, rank = "custo_por_conversao", lambda a: -(a["custo_por_conversao"] or 1e12)
    else:
        metric, rank = "ctr_pct", lambda a: a["ctr_pct"] or 0
    spent.sort(key=rank, reverse=True)
    best, worst = spent[:6], spent[max(6, len(spent) - 3):]
    try:
        copies = await _mugo_ad_copies(client_id)
    except Exception:  # noqa: BLE001
        copies = {}

    def view(a: Dict[str, Any]) -> Dict[str, Any]:
        out = {k: v for k, v in a.items() if k != "ad_id" and v not in (None, "")}
        if a["ad_id"] in copies:
            out["criado_no_mugoverso"] = copies[a["ad_id"]]
        return out
    return {"periodo": f"últimos {days} dias", "comparado_por": metric, "anuncios_com_gasto": len(spent),
            "melhores": [view(a) for a in best], "piores": [view(a) for a in worst]}


async def _brand_lessons(client_id: str) -> List[Dict[str, Any]]:
    """Conclusões guardadas pelo ciclo fechado (brand_learnings): o que cada post e anúncio rendeu contra a média."""
    from .brand_learnings import recent
    return await recent(client_id)


async def _mugo_ad_copies(client_id: str) -> Dict[str, Dict[str, Any]]:
    """Texto, título e formato de cada anúncio que o Mídia On criou (ID do anúncio na Meta → criativo)."""
    from .meta_ad_publisher import ad_units, clean_payload
    rows = await sb_select("studio_ad_drafts", select="payload,meta_ids", limit=100,
                           filters={"client_id": f"eq.{client_id}", "meta_ids": "not.is.null"}, order="updated_at.desc")
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        ids = r.get("meta_ids") or {}
        ad_ids = [str(x) for x in (ids.get("ad_ids") or ([ids["ad_id"]] if ids.get("ad_id") else []))]
        if not ad_ids:
            continue
        try:
            payload = clean_payload(r.get("payload") or {})
        except Exception:  # noqa: BLE001 - rascunho antigo fora do formato
            continue
        ad = payload["ad"]
        units = ad_units(ad)
        for i, ad_id in enumerate(ad_ids):
            unit = units[i] if i < len(units) else {}
            fmt = "carrossel" if unit.get("format") == "carousel" else "vídeo" if unit.get("media_type") == "video" else "imagem"
            out[ad_id] = {k: v for k, v in {"objetivo": payload.get("objective"), "formato": fmt,
                                            "texto": clean_text(ad.get("primary_text"), 300), "titulo": clean_text(ad.get("headline"), 80),
                                            "botao": ad.get("cta")}.items() if v}
    return out


async def _timing(client_id: str) -> Dict[str, Any]:
    from .posting_times import build_posting_times
    today = datetime.now(SAO_PAULO).date()
    best = await build_posting_times(client_id, start=(today - timedelta(days=179)).isoformat(), end=today.isoformat())
    return {"melhores_horarios": [{"dia": s.get("weekday"), "faixa": s.get("hours"), "alcance_idx": _num(s.get("reach_index"))}
                                  for s in (best.get("best_slots") or [])[:4]],
            "alcance_mediano_por_formato": best.get("format_median_reach") or {}}


async def _goals(client_id: str) -> List[Dict[str, Any]]:
    from .goals import list_goals
    today = datetime.now(SAO_PAULO).date()
    data = await list_goals(client_id, today.replace(day=1).isoformat(), today.isoformat())
    return [{"metrica": g.get("metric"), "meta": _num(g.get("target_value")), "realizado": _num(g.get("actual")),
             "progresso_pct": _num(g.get("progress_percent")), "status": g.get("status")}
            for g in (data.get("goals") or [])[:10]]


async def _analysis(client_id: str) -> Dict[str, Any]:
    rows = await sb_select("ai_analyses", select="analysis,created_at", order="created_at.desc", limit=1,
                           filters={"client_id": f"eq.{client_id}", "status": "eq.completed"})
    executive = ((rows[0].get("analysis") or {}).get("executive") or {}) if rows else {}
    if not isinstance(executive, dict):
        return {}
    return {k: clean_text(executive.get(k), 400) for k in ("main_change", "opportunity", "attention", "priority_action")
            if clean_text(executive.get(k), 400)}


async def approval_learnings(client_id: str, *, days: int = 180) -> Dict[str, Any]:
    """O que o cliente aprovou (exemplo a seguir) e o que pediu para mudar (a evitar)."""
    from .studio_calendar import ITEMS_TABLE
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    approved = await sb_select(ITEMS_TABLE, select="format,pillar,title,hook,caption_draft,reviewed_by", limit=8,
                               filters={"client_id": f"eq.{client_id}", "status": "in.(aprovado,publicado)", "reviewed_at": f"gte.{since}"},
                               order="reviewed_at.desc")
    adjusted = await sb_select(ITEMS_TABLE, select="format,title,review_note", limit=8,
                               filters={"client_id": f"eq.{client_id}", "status": "eq.rejeitado", "reviewed_at": f"gte.{since}",
                                        "review_note": "not.is.null"}, order="reviewed_at.desc")
    # Aprovação do próprio cliente pesa mais: vem primeiro.
    approved.sort(key=lambda r: 0 if str(r.get("reviewed_by") or "").startswith("cliente:") else 1)
    return {
        "aprovados": [{"formato": r.get("format"), "pilar": clean_text(r.get("pillar"), 80), "pauta": clean_text(r.get("title"), 200),
                       "gancho": clean_text(r.get("hook"), 200), "legenda": clean_text(r.get("caption_draft"), 400),
                       "pelo_cliente": str(r.get("reviewed_by") or "").startswith("cliente:")} for r in approved[:5]],
        "ajustes_pedidos": [{"formato": r.get("format"), "pauta": clean_text(r.get("title"), 200),
                             "comentario": clean_text(r.get("review_note"), 300)} for r in adjusted[:6] if clean_text(r.get("review_note"), 300)],
    }


# --------------------------------------------------------------------------
# Pacote
# --------------------------------------------------------------------------

async def build_content_intelligence(client_id: str, *, days: int = 90, use_cache: bool = True) -> Dict[str, Any]:
    key = f"{client_id}:{days}"
    cached = _CACHE.get(key)
    if use_cache and cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    today = datetime.now(SAO_PAULO).date()
    start, end = (today - timedelta(days=days - 1)).isoformat(), today.isoformat()
    gaps: List[str] = []
    month = today.replace(day=1)
    (profile, business, snap, posts, timing, goals, analysis, learnings,
     origin, media, campaigns, clipping, calendar_month, references,
     health, voice, competitors, products, briefs, plans, library, whatsapp, creatives, brand_lessons) = await asyncio.gather(
        _safe("perfil_da_marca", gaps, lambda: _profile(client_id), {}),
        _safe("contexto_do_negocio", gaps, lambda: _business(client_id), {}),
        _safe("kpis_e_campanhas", gaps, lambda: _snapshot(client_id, start, end), {}),
        _safe("posts_instagram", gaps, lambda: _posts(client_id, days), {}),
        _safe("melhores_horarios", gaps, lambda: _timing(client_id), {}),
        _safe("metas", gaps, lambda: _goals(client_id), []),
        _safe("ultima_analise", gaps, lambda: _analysis(client_id), {}),
        _safe("aprendizados_de_aprovacao", gaps, lambda: approval_learnings(client_id), {}),
        _safe("vendas_por_origem", gaps, lambda: _sales_origin(client_id, today), {}),
        _safe("plano_de_midia", gaps, lambda: _media_plan(client_id, month), {}),
        _safe("campanhas_ativas", gaps, lambda: _active_campaigns(client_id), []),
        _safe("clipping", gaps, lambda: _clipping(client_id), {}),
        _safe("calendario_do_mes", gaps, lambda: _calendar_month(client_id, month), {}),
        _safe("referencias_do_cliente", gaps, lambda: _references(client_id), []),
        _safe("saude_da_marca", gaps, lambda: _health(client_id), {}),
        _safe("voz_do_publico", gaps, lambda: _audience_voice(client_id), ""),
        _safe("concorrentes", gaps, lambda: _competitors(client_id), {}),
        _safe("produtos_mais_vendidos", gaps, lambda: _top_products(client_id), []),
        _safe("briefings_aprovados", gaps, lambda: _approved_briefs(client_id, today), []),
        _safe("planos_aprovados", gaps, lambda: _plans(client_id, today), {}),
        _safe("biblioteca", gaps, lambda: _library(client_id), {}),
        _safe("whatsapp", gaps, lambda: _whatsapp(client_id), {}),
        _safe("criativos_pagos", gaps, lambda: _paid_creatives(client_id), {}),
        _safe("aprendizados_da_marca", gaps, lambda: _brand_lessons(client_id), []),
    )
    package = {
        "periodo": {"inicio": start, "fim": end, "dias": days},
        "marca": {k: profile.get(k) for k in ("tone_of_voice", "personality", "audience", "pillars", "keywords_use",
                                              "keywords_avoid", "hashtags", "restrictions", "visual_identity", "custom_dates",
                                              "content_language") if profile.get(k)},
        "negocio": business,
        "kpis": snap.get("metricas") or [],
        "campanhas_que_mais_venderam": snap.get("campanhas") or [],
        "criativos_pagos": creatives,
        "aprendizados_da_marca": brand_lessons,
        "funil_do_site": snap.get("funil_do_site") or {},
        "posts": posts,
        "horarios": timing,
        "metas_do_mes": goals,
        "ultima_analise": analysis,
        "aprendizados": learnings,
        "vendas_por_origem": origin,
        "plano_de_midia": media,
        "campanhas_ativas": campaigns,
        "clipping": clipping,
        "calendario_do_mes": calendar_month,
        "referencias_do_cliente": references,
        "saude_da_marca": health,
        "voz_do_publico": voice,
        "whatsapp": whatsapp,
        "concorrentes": competitors,
        "produtos_mais_vendidos": products,
        "briefings_aprovados": briefs,
        "planos_aprovados": plans,
        "biblioteca": library,
        "lacunas":sorted(set(gaps) | _empty_sections(profile, business, snap, posts, goals)),
        "_client_id": client_id,  # só para o registro de tamanho do contexto; não vai para a IA
    }
    _CACHE[key] = (time.monotonic(), package)
    return package


def _empty_sections(profile, business, snap, posts, goals) -> set:
    missing = set()
    if not profile.get("pillars") and not profile.get("tone_of_voice"):
        missing.add("perfil_da_marca_vazio")
    if not business:
        missing.add("contexto_do_negocio_vazio")
    if not (snap or {}).get("metricas"):
        missing.add("sem_kpis_no_periodo")
    if not (posts or {}).get("analisados"):
        missing.add("sem_historico_de_posts")
    if not goals:
        missing.add("sem_metas_no_mes")
    return missing


# --------------------------------------------------------------------------
# Cérebro da marca: o que cada módulo decidiu, para os outros saberem
# --------------------------------------------------------------------------

async def _sales_origin(client_id: str, today: date) -> Dict[str, Any]:
    from .sales_by_origin import build_sales_by_origin
    end = today - timedelta(days=1)
    data = await build_sales_by_origin(client_id, start=(end - timedelta(days=29)).isoformat(), end=end.isoformat())
    if data.get("status") not in ("available", "partial"):
        return {}
    totals = data.get("totals") or {}
    return {"periodo": "30 dias", "faturamento": _num(totals.get("revenue")), "pedidos": totals.get("orders"),
            "por_origem": [{"origem": c.get("channel"), "vendas": _num(c.get("revenue")), "pedidos": c.get("orders")}
                           for c in (data.get("channels") or [])[:6]],
            "campanhas_que_venderam": [{"campanha": clean_text(c.get("campaign"), 120), "vendas": _num(c.get("revenue")),
                                        "pedidos": c.get("orders")} for c in (data.get("campaigns") or [])[:5]]}


async def _media_plan(client_id: str, month: date) -> Dict[str, Any]:
    from .media_plan import plan_vs_actual
    data = await plan_vs_actual(client_id, month.strftime("%Y-%m"))
    plan = data.get("plan") or {}
    if not plan and not data.get("channels"):
        return {}
    return {"mes": month.strftime("%Y-%m"), "objetivo": plan.get("objective"), "verba_total": _num(plan.get("budget")),
            "por_canal": [{"canal": r["label"], "planejado": r.get("planned_spend"), "gasto_ate_agora": r.get("spent"),
                           "ritmo": r.get("pace"), "roas": r.get("roas"), "cpa": r.get("cpa")} for r in data.get("channels") or []],
            "observacoes": clean_text(plan.get("notes"), 300) or None}


async def _active_campaigns(client_id: str) -> List[Dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    rows = await sb_select("studio_campaigns", select="name,briefing,package,status,created_at", order="created_at.desc", limit=5,
                           filters={"client_id": f"eq.{client_id}", "status": "neq.arquivada", "created_at": f"gte.{since}"})
    out = []
    for r in rows:
        brief, concept = r.get("briefing") or {}, (r.get("package") or {}).get("concept") or {}
        out.append({"campanha": clean_text(r.get("name"), 120), "objetivo": clean_text(brief.get("objective"), 200),
                    "oferta": clean_text(brief.get("offer"), 300), "periodo": f"{brief.get('start') or '?'} a {brief.get('end') or '?'}",
                    "conceito": clean_text(concept.get("ideia"), 300), "status": r.get("status")})
    return out


async def _clipping(client_id: str) -> Dict[str, Any]:
    since = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    rows = await sb_select("studio_clippings", select="title,source,kind,sentiment,relevant,published_at", order="published_at.desc.nullslast",
                           limit=40, filters={"client_id": f"eq.{client_id}", "created_at": f"gte.{since}", "status": "neq.arquivado"})
    rows = [r for r in rows if r.get("relevant") is not False]
    if not rows:
        return {}
    return {"ultimos_14_dias": len(rows),
            "negativas_da_marca": sum(1 for r in rows if r["kind"] == "marca" and r.get("sentiment") == "negativo"),
            "noticias": [{"manchete": clean_text(r.get("title"), 160), "fonte": clean_text(r.get("source"), 60), "tipo": r["kind"],
                          "sentimento": r.get("sentiment")} for r in rows[:6]]}


async def _references(client_id: str) -> List[Dict[str, Any]]:
    """Links e artes que o cliente marcou como referência (Aprovação → Referências): norte de estética e tom."""
    rows = await sb_select("studio_references", select="url,kind,note,author_side,created_at", order="created_at.desc",
                           limit=20, filters={"client_id": f"eq.{client_id}"})
    return [{"link": r["url"], "tipo": "imagem" if r.get("kind") == "arte" else "link",
             "o_que_gostou": clean_text(r.get("note"), 300) or None,
             "de_quem": "cliente" if r.get("author_side") == "cliente" else "equipe Mugô"} for r in rows]


async def _calendar_month(client_id: str, month: date) -> Dict[str, Any]:
    rows = await sb_select("studio_calendar_items", select="status,format,pillar", limit=300,
                           filters={"client_id": f"eq.{client_id}", "month": f"eq.{month.isoformat()}"})
    if not rows:
        return {}
    counts: Dict[str, int] = {}
    for r in rows:
        counts[r.get("status") or "?"] = counts.get(r.get("status") or "?", 0) + 1
    pillars: Dict[str, int] = {}
    for r in rows:
        if r.get("pillar"):
            pillars[r["pillar"]] = pillars.get(r["pillar"], 0) + 1
    return {"posts": len(rows), "por_status": counts, "por_pilar": dict(sorted(pillars.items(), key=lambda kv: -kv[1])[:6])}


async def _health(client_id: str) -> Dict[str, Any]:
    """Saúde da marca (Clipping → Saúde): índice, sentimento e assuntos dos últimos 30 dias, mais alertas abertos."""
    from .brand_health import summary
    end = datetime.now(SAO_PAULO).date()
    data = await summary(client_id, start=end - timedelta(days=29), end=end, grain="month", sources=[])
    kpis = data.get("kpis") or {}
    if not kpis.get("mentions"):
        return {}
    return {"periodo": "30 dias", "indice": kpis.get("index"), "indice_anterior": kpis.get("index_previous"),
            "situacao": kpis.get("index_label"), "mencoes": kpis.get("mentions"), "variacao_mencoes_pct": kpis.get("mentions_change"),
            "sentimento_liquido": kpis.get("net"), "negativas_pct": kpis.get("negative_share"),
            "assuntos": [{"assunto": clean_text(t.get("theme"), 80), "tom": t.get("tone"), "mencoes": t.get("mentions")}
                         for t in (data.get("themes") or [])[:6] if clean_text(t.get("theme"), 80)],
            "alertas_abertos": [{"tipo": a.get("kind"), "termo": clean_text(a.get("term"), 60) or None, "gravidade": a.get("severity")}
                                for a in (data.get("alerts") or [])[:5]]}


async def _whatsapp(client_id: str) -> Dict[str, Any]:
    """O que os clientes perguntam no WhatsApp da marca (últimos 30 dias), sem quem perguntou: vira pauta e resposta."""
    from .brand_signals import whatsapp_section
    return await whatsapp_section(client_id)


async def _audience_voice(client_id: str) -> str:
    """Como o público fala da marca (comentários, Direct e notícias), já agregado e sem dado de pessoa."""
    from .brand_health import audience_voice
    return clean_text(await audience_voice(client_id), 700)


async def _competitors(client_id: str) -> Dict[str, Any]:
    """Concorrentes cadastrados (Clipping e Benchmarking, inclusive os vindos do planejamento) e o que saiu sobre eles
    nos últimos 30 dias."""
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    settings = await sb_select("studio_clipping_settings", select="competitor_terms", limit=1, filters={"client_id": f"eq.{client_id}"})
    try:
        bench = await sb_select("benchmark_competitors", select="name", limit=30,
                                filters={"client_id": f"eq.{client_id}", "active": "is.true"})
    except Exception:  # noqa: BLE001 — Benchmarking indisponível não tira os concorrentes do Clipping
        bench = []
    names: List[str] = []
    for term in [*((settings[0].get("competitor_terms") if settings else None) or []), *(r.get("name") for r in bench)]:
        name = clean_text(term, 60)
        if name and name.lower() not in {n.lower() for n in names}:
            names.append(name)
    names = names[:12]
    rows = await sb_select("studio_clippings", select="title,source,term,sentiment,summary,relevant,published_at", limit=30,
                           order="published_at.desc.nullslast",
                           filters={"client_id": f"eq.{client_id}", "kind": "eq.concorrente", "created_at": f"gte.{since}",
                                    "status": "neq.arquivado"})
    rows = [r for r in rows if r.get("relevant") is not False]
    if not names and not rows:
        return {}
    return {"cadastrados": names, "noticias_30_dias": len(rows),
            "noticias": [{"concorrente": clean_text(r.get("term"), 60), "manchete": clean_text(r.get("title"), 160),
                          "resumo": clean_text(r.get("summary"), 240) or None, "fonte": clean_text(r.get("source"), 60),
                          "sentimento": r.get("sentiment")} for r in rows[:6]]}


async def _top_products(client_id: str, days: int = 90) -> List[Dict[str, Any]]:
    """Produtos que mais venderam (Shopify e FBits), pelos itens dos pedidos: o que de fato sai da loja."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    shop, fbits = await asyncio.gather(
        sb_select("shopify_order_items", select="title,quantity,price,total_discount", limit=2000,
                  filters={"client_id": f"eq.{client_id}", "created_at": f"gte.{since}"}),
        sb_select("fbits_order_items", select="product_name,quantity,total_value", limit=2000,
                  filters={"client_id": f"eq.{client_id}", "created_at": f"gte.{since}"}),
        return_exceptions=True,
    )
    totals: Dict[str, Dict[str, Any]] = {}

    def add(name: Any, qty: Any, revenue: Optional[float]) -> None:
        label = clean_text(name, 120)
        if not label:
            return
        entry = totals.setdefault(label.lower(), {"produto": label, "unidades": 0, "vendas": 0.0})
        entry["unidades"] += int(_num(qty) or 0)
        entry["vendas"] += max(0.0, revenue or 0.0)
    for r in shop if isinstance(shop, list) else []:
        add(r.get("title"), r.get("quantity"), (_num(r.get("price")) or 0) * (_num(r.get("quantity")) or 0) - (_num(r.get("total_discount")) or 0))
    for r in fbits if isinstance(fbits, list) else []:
        add(r.get("product_name"), r.get("quantity"), _num(r.get("total_value")))
    ranked = sorted(totals.values(), key=lambda p: (p["vendas"], p["unidades"]), reverse=True)[:10]
    return [{**p, "vendas": round(p["vendas"], 2), "periodo": f"{days} dias"} for p in ranked]


# --------------------------------------------------------------------------
# O que a equipe já decidiu: briefings, planejamentos, eventos e Biblioteca
# --------------------------------------------------------------------------

def _texts(values: Any, n: int, limit: int = 200) -> List[str]:
    return [t for t in (clean_text(v, limit) for v in (values or []) if isinstance(v, str)) if t][:n]


async def _approved_briefs(client_id: str, today: date) -> List[Dict[str, Any]]:
    """Briefings prontos ou distribuídos dos últimos 60 dias: o que a equipe já combinou com o cliente."""
    since = (today - timedelta(days=60)).isoformat()
    rows = await sb_select("studio_briefs", select="brief,status,created_at", order="created_at.desc", limit=6,
                           filters={"client_id": f"eq.{client_id}", "status": "in.(pronto,distribuido)", "created_at": f"gte.{since}"})
    out = []
    for r in rows:
        b = r.get("brief") or {}
        item = {"titulo": clean_text(b.get("title"), 160), "objetivo": clean_text(b.get("objective"), 300),
                "mensagem": clean_text(b.get("key_message"), 300), "publico": clean_text(b.get("audience"), 200),
                "prazo": clean_text(b.get("deadline"), 40), "meta": clean_text(b.get("goal"), 160),
                "entregaveis": _texts(b.get("deliverables"), 6, 120), "nao_fazer": _texts(b.get("avoid"), 6, 160)}
        item = {k: v for k, v in item.items() if v}
        if item.get("titulo"):
            out.append(item)
    return out


async def _plans(client_id: str, today: date) -> Dict[str, Any]:
    """Planejamentos com plano gerado (o mais recente manda) e eventos/produções dos próximos 90 dias."""
    rows = await sb_select("studio_projects", select="kind,title,status,format,target_date,inputs,plan,updated_at",
                           order="updated_at.desc", limit=20, filters={"client_id": f"eq.{client_id}"})
    planning, events = [], []
    for r in rows:
        p, i = r.get("plan") or {}, r.get("inputs") or {}
        if r.get("kind") == "planejamento" and p and len(planning) < 3:
            planning.append({k: v for k, v in {
                "titulo": clean_text(r.get("title"), 160), "etapa": r.get("status"), "prazo": r.get("target_date"),
                "objetivo": clean_text(i.get("objective"), 300), "grande_ideia": clean_text(p.get("big_idea"), 200),
                "insight": clean_text(p.get("insight"), 300), "estrategia": clean_text(p.get("strategy"), 600),
                "mensagens": _texts(p.get("messages"), 5),
                "canais": [f"{clean_text(c.get('channel'), 40)}: {clean_text(c.get('role'), 120)}" for c in p.get("channels") or [] if isinstance(c, dict)][:6],
                "fases": [f"{clean_text(f.get('phase'), 60)} ({clean_text(f.get('when'), 40)}): {clean_text(f.get('what'), 200)}" for f in p.get("phases") or [] if isinstance(f, dict)][:6],
                "kpis": [f"{clean_text(k.get('kpi'), 60)} = {clean_text(k.get('target'), 60)}" for k in p.get("kpis") or [] if isinstance(k, dict)][:5],
            }.items() if v})
        elif r.get("kind") == "evento" and r.get("status") != "finalizado":
            when = str(r.get("target_date") or "")[:10]
            try:
                soon = not when or today <= date.fromisoformat(when) <= today + timedelta(days=90)
            except ValueError:
                soon = False
            if soon and len(events) < 4:
                events.append({k: v for k, v in {"titulo": clean_text(r.get("title"), 160), "formato": r.get("format"), "data": when or None,
                                                  "local": clean_text(i.get("location"), 120), "ideia": clean_text(i.get("idea"), 300),
                                                  "resumo": clean_text(p.get("summary"), 300)}.items() if v})
    return {k: v for k, v in {"planejamentos": planning, "eventos": events}.items() if v}


async def _library(client_id: str) -> Dict[str, Any]:
    """Material da MARCA na Biblioteca, por nome e categoria (logo, identidade, produto, fotos e vídeos da marca,
    referências, documentos). Arte de post e de anúncio não conta: a IA aprende com o que foi publicado e o resultado."""
    from .studio_library import POST_NOTES
    rows = await sb_select("studio_library", select="kind,category,title,note,side,mime_type", order="created_at.desc",
                           limit=80, filters={"client_id": f"eq.{client_id}"})
    groups: Dict[str, List[str]] = {}
    for r in rows:
        name = clean_text(r.get("title"), 100)
        if not name or str(r.get("note") or "").strip() in POST_NOTES:
            continue
        kind = "link" if r.get("kind") == "link" else str(r.get("mime_type") or "arquivo").split("/")[0]
        note = clean_text(r.get("note"), 120)
        who = " (do cliente)" if r.get("side") == "cliente" else ""
        groups.setdefault(str(r.get("category") or "outro"), []).append(f"{name} [{kind}]{who}" + (f": {note}" if note else ""))
    return {k: v[:15] for k, v in groups.items()}


async def passages_for(client_id: str, *texts: str, limit: int = 4) -> str:
    """Trechos dos DOCUMENTOS da marca (manual, apresentação, tabela de preços) mais ligados a esta peça.
    O pacote traz o conhecimento consolidado; aqui vai o texto original do que importa para a pauta, com o nome do documento
    entre colchetes para a IA citar a origem. Nunca levanta."""
    try:
        from .brand_knowledge import search_chunks
        rows = await search_chunks(client_id, *[t for t in texts if t], limit=limit)
    except Exception:  # noqa: BLE001
        return ""
    names: Dict[str, str] = {}
    ids = sorted({str(r.get("document_id")) for r in rows if r.get("document_id")})
    if ids:
        try:
            docs = await sb_select("brand_documents", select="id,name", limit=len(ids),
                                   filters={"client_id": f"eq.{client_id}", "id": f"in.({','.join(ids)})"})
            names = {str(d.get("id")): clean_text(d.get("name"), 80) for d in docs}
        except Exception:  # noqa: BLE001 — sem o nome, o trecho continua valendo
            names = {}
    out = []
    for r in rows:
        text = _PERSONAL.sub("[…]", re.sub(r"\s+", " ", str(r.get("content") or ""))).strip()[:700]
        if text:
            # O nome do documento vai junto: a IA cita de onde tirou ("conforme o Planejamento 2027").
            source = names.get(str(r.get("document_id") or ""))
            out.append(f"- [{source}] {text}" if source else f"- {text}")
    return "\n".join(out)


LIBRARY_RULE = ("A BIBLIOTECA dos DADOS é só material da marca (logo, identidade, produto, fotos e vídeos da marca, referências). "
                "Se tiver o arquivo certo, cite-o pelo nome exato na ideia de imagem para a equipe achar; não invente arquivo "
                "que não está lá. O que funcionou vem dos posts, anúncios e aprovações, não da Biblioteca.")
PLANS_RULE = ("Use os aprendizados_da_marca (o que já funcionou ou não nesta marca) antes de qualquer ideia nova. No 'por que' de "
              "cada post, pauta ou anúncio, comece com 'Baseado em:' e cite o aprendizado, post ou anúncio dos DADOS que sustenta "
              "a ideia (ex.: 'Baseado em: Reels de 12/11 com 2,1× o alcance médio'); se for teste sem histórico, diga 'Teste: ...'. "
              "Briefings aprovados e planejamentos dos DADOS mandam: siga a grande ideia, as mensagens, a fase do momento e o "
              "que está em 'nao_fazer'. Evento próximo vira pauta de antes, durante e depois. As perguntas reais dos clientes "
              "(seção whatsapp e voz_do_publico) são ponto de partida para pauta, FAQ e objeção a quebrar. Ao usar um trecho de "
              "documento da marca, cite o nome do documento (entre colchetes nos trechos) na justificativa.")


def invalidate(client_id: str) -> None:
    for key in [k for k in _CACHE if k.startswith(f"{client_id}:")]:
        _CACHE.pop(key, None)


def coverage(package: Dict[str, Any]) -> Dict[str, Any]:
    """Resumo do que foi usado, para a tela mostrar 'com base em…'."""
    return {
        "kpis": len(package.get("kpis") or []),
        "campanhas": len(package.get("campanhas_que_mais_venderam") or []),
        "posts_analisados": (package.get("posts") or {}).get("analisados", 0),
        "anuncios_analisados": (package.get("criativos_pagos") or {}).get("anuncios_com_gasto", 0),
        "metas": len(package.get("metas_do_mes") or []),
        "aprovados": len((package.get("aprendizados") or {}).get("aprovados") or []),
        "ajustes": len((package.get("aprendizados") or {}).get("ajustes_pedidos") or []),
        "biblioteca": sum(len(v) for v in (package.get("biblioteca") or {}).values()),
        "briefings": len(package.get("briefings_aprovados") or []),
        "planejamentos": len((package.get("planos_aprovados") or {}).get("planejamentos") or []),
        "eventos": len((package.get("planos_aprovados") or {}).get("eventos") or []),
        "lacunas": package.get("lacunas") or [],
    }


# Ordem de importância: quando o contexto passa do limite, o FIM da lista é resumido (e, se preciso, omitido) primeiro.
# Resultado real (aprovações, posts, anúncios) vem logo depois da marca e do que a equipe decidiu; a lista de arquivos
# da Biblioteca fica por último.
PROMPT_ORDER = ["marca", "negocio", "briefings_aprovados", "planos_aprovados", "aprendizados", "aprendizados_da_marca", "posts", "criativos_pagos",
                "referencias_do_cliente", "voz_do_publico", "whatsapp", "campanhas_ativas", "produtos_mais_vendidos", "plano_de_midia",
                "kpis", "saude_da_marca", "concorrentes", "campanhas_que_mais_venderam", "vendas_por_origem", "metas_do_mes",
                "clipping", "calendario_do_mes", "ultima_analise", "funil_do_site", "horarios", "lacunas", "biblioteca"]


def _shrink(value: Any) -> Any:
    """Metade de cada lista e textos longos encurtados: a seção continua lá, menor."""
    if isinstance(value, list):
        return [_shrink(v) for v in value[:max(1, len(value) // 2)]]
    if isinstance(value, dict):
        return {k: _shrink(v) for k, v in value.items()}
    if isinstance(value, str) and len(value) > 300:
        return value[:300].rsplit(" ", 1)[0] + "…"
    return value


def _dump(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)


def to_prompt(package: Dict[str, Any], *, sections: Optional[List[str]] = None, limit: int = MAX_PROMPT_CHARS) -> str:
    """JSON compacto para o prompt. Se passar do limite, RESUME primeiro as seções menos importantes (até 3 vezes
    cada, de trás para frente) e só então omite; o prompt avisa a IA do que foi resumido ou omitido."""
    order = sections or PROMPT_ORDER
    data = {k: package.get(k) for k in order if package.get(k)}
    full = len(_dump(data))
    budget = max(200, limit - 220)  # espaço para o aviso
    resumed: List[str] = []
    dropped: List[str] = []
    text = _dump(data)
    rounds = 0
    while len(text) > budget and rounds < 3:
        for key in reversed(list(data)):
            if len(text) <= budget or (key == list(data)[0] and len(data) > 1):
                continue
            data[key] = _shrink(data[key])
            if key not in resumed:
                resumed.append(key)
            text = _dump(data)
        rounds += 1
    while len(text) > budget and len(data) > 1:
        key = list(data)[-1]
        data.pop(key)
        dropped.append(key)
        text = _dump(data)
    for _ in range(3):  # sobrou só a seção principal e ainda não cabe: ela também é resumida
        if len(text) <= budget or not data:
            break
        key = list(data)[0]
        data[key] = _shrink(data[key])
        if key not in resumed:
            resumed.append(key)
        text = _dump(data)
    if resumed or dropped:
        data["_aviso"] = {"resumidas": [k for k in resumed if k not in dropped], "omitidas_por_tamanho": dropped}
        text = _dump(data)
    # Registro para medir se o contexto está sendo cortado em cada marca (só nomes de seção e tamanhos, nada de dado).
    print(f"[studio][intel][prompt] cliente={package.get('_client_id') or '?'} secoes={len(order)} "
          f"tamanho_completo={full} enviado={min(len(text), limit)} limite={limit} "
          f"resumidas={','.join(k for k in resumed if k not in dropped) or '-'} omitidas={','.join(dropped) or '-'}")
    return text[:limit]
