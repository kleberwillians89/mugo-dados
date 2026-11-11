"""Inteligência de conteúdo do Studio: o que a marca JÁ tem de dados, num pacote só.

Todo motor de conteúdo (calendário, redação, ganchos, roteiro, chat de
estratégia, Brand Manager, Mídia On, mensagens) parte deste pacote, para que a
IA escreva a partir de fatos da conta e não de clichês:

* perfil da marca e contexto do negócio (escritos pela equipe);
* KPIs do período e campanhas que mais venderam (snapshot da Inteligência);
* posts que mais e menos alcançaram em relação ao próprio formato;
* melhores dias e horários (posting_times);
* metas do mês e a última análise salva;
* aprendizado com o cliente: o que ele aprovou e o que pediu para ajustar;
* CÉREBRO DA MARCA (ligação entre módulos): vendas por origem, plano do Mídia On do mês,
  campanhas ativas da Redação, notícias relevantes do Clipping e o andamento do Calendário.
  Assim a pauta, a copy, o anúncio e a mensagem de sexta seguem a mesma linha.
* MUNDO DO CLIENTE: saúde da marca (índice, sentimento, assuntos e alertas), voz do público
  (comentários, Direct e notícias agregados), concorrentes do Clipping e produtos que mais vendem.

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
CACHE_SECONDS = 600
MAX_PROMPT_CHARS = 18000
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


async def _posts(client_id: str, days: int) -> Dict[str, Any]:
    from .posting_times import score_posts
    since = datetime.now(timezone.utc).date() - timedelta(days=days)
    rows = await sb_select("ig_media", select="media_type,media_product_type,timestamp,insights_json,caption",
                           filters={"client_id": f"eq.{client_id}", "timestamp": f"gte.{since.isoformat()}"},
                           order="timestamp.desc", limit=300)
    scored = sorted(score_posts(rows, start=since, end=date.max), key=lambda p: p["reach_index"], reverse=True)

    def view(p: Dict[str, Any]) -> Dict[str, Any]:
        return {"formato": p["format"], "alcance_vs_media_do_formato": round(p["reach_index"], 2),
                "interacoes": p.get("interactions"), "legenda": clean_text(p.get("caption"), 220)}
    return {"analisados": len(scored), "melhores": [view(p) for p in scored[:6]],
            "piores": [view(p) for p in scored[-3:]] if len(scored) >= 8 else []}


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
     health, voice, competitors, products) = await asyncio.gather(
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
    )
    package = {
        "periodo": {"inicio": start, "fim": end, "dias": days},
        "marca": {k: profile.get(k) for k in ("tone_of_voice", "personality", "audience", "pillars", "keywords_use",
                                              "keywords_avoid", "hashtags", "restrictions", "visual_identity", "custom_dates",
                                              "content_language") if profile.get(k)},
        "negocio": business,
        "kpis": snap.get("metricas") or [],
        "campanhas_que_mais_venderam": snap.get("campanhas") or [],
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
        "concorrentes": competitors,
        "produtos_mais_vendidos": products,
        "lacunas":sorted(set(gaps) | _empty_sections(profile, business, snap, posts, goals)),
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


async def _audience_voice(client_id: str) -> str:
    """Como o público fala da marca (comentários, Direct e notícias), já agregado e sem dado de pessoa."""
    from .brand_health import audience_voice
    return clean_text(await audience_voice(client_id), 700)


async def _competitors(client_id: str) -> Dict[str, Any]:
    """Concorrentes cadastrados no Clipping e o que saiu sobre eles nos últimos 30 dias."""
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    settings = await sb_select("studio_clipping_settings", select="competitor_terms", limit=1, filters={"client_id": f"eq.{client_id}"})
    names = [clean_text(t, 60) for t in ((settings[0].get("competitor_terms") if settings else None) or []) if clean_text(t, 60)][:10]
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


def invalidate(client_id: str) -> None:
    for key in [k for k in _CACHE if k.startswith(f"{client_id}:")]:
        _CACHE.pop(key, None)


def coverage(package: Dict[str, Any]) -> Dict[str, Any]:
    """Resumo do que foi usado, para a tela mostrar 'com base em…'."""
    return {
        "kpis": len(package.get("kpis") or []),
        "campanhas": len(package.get("campanhas_que_mais_venderam") or []),
        "posts_analisados": (package.get("posts") or {}).get("analisados", 0),
        "metas": len(package.get("metas_do_mes") or []),
        "aprovados": len((package.get("aprendizados") or {}).get("aprovados") or []),
        "ajustes": len((package.get("aprendizados") or {}).get("ajustes_pedidos") or []),
        "lacunas": package.get("lacunas") or [],
    }


def to_prompt(package: Dict[str, Any], *, sections: Optional[List[str]] = None, limit: int = MAX_PROMPT_CHARS) -> str:
    """JSON compacto para o prompt; corta as seções menos importantes se passar do limite."""
    order = sections or ["marca", "negocio", "referencias_do_cliente", "aprendizados", "voz_do_publico", "campanhas_ativas",
                         "produtos_mais_vendidos", "plano_de_midia", "posts", "kpis", "saude_da_marca", "concorrentes",
                         "campanhas_que_mais_venderam", "vendas_por_origem", "metas_do_mes", "clipping", "calendario_do_mes",
                         "ultima_analise", "funil_do_site", "horarios", "lacunas"]
    data = {k: package.get(k) for k in order if package.get(k)}
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    while len(text) > limit and len(data) > 1:
        data.pop(list(data)[-1])
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return text[:limit]
