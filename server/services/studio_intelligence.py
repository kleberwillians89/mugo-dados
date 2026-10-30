"""Inteligência de conteúdo do Studio: o que a marca JÁ tem de dados, num pacote só.

Todo motor de conteúdo (calendário, redação, ganchos, roteiro, chat de
estratégia, Brand Manager, Mídia On, mensagens) parte deste pacote, para que a
IA escreva a partir de fatos da conta e não de clichês:

* perfil da marca e contexto do negócio (escritos pela equipe);
* KPIs do período e campanhas que mais venderam (snapshot da Inteligência);
* posts que mais e menos alcançaram em relação ao próprio formato;
* melhores dias e horários (posting_times);
* metas do mês e a última análise salva;
* aprendizado com o cliente: o que ele aprovou e o que pediu para ajustar.

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
MAX_PROMPT_CHARS = 14000
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
    context = (await load_business_context(client_id)).get("context") or {}
    return {k: clean_text(v, 800) for k, v in context.items() if clean_text(v, 800)}


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


async def _redacao(client_id: str) -> List[Dict[str, Any]]:
    """Campanhas da Redação em andamento: o calendário e a mídia falam a mesma língua delas."""
    rows = await sb_select("studio_campaigns", select="name,briefing,status,updated_at", order="updated_at.desc", limit=5,
                           filters={"client_id": f"eq.{client_id}", "status": "in.(rascunho,pronta)"})
    out = []
    for r in rows:
        brief = r.get("briefing") or {}
        out.append({"campanha": clean_text(r.get("name"), 120), "status": r.get("status"), "objetivo": clean_text(brief.get("objective"), 300),
                    "mensagem": clean_text(brief.get("key_message") or brief.get("message"), 300), "canais": brief.get("channels") or [],
                    "inicio": brief.get("start"), "fim": brief.get("end")})
    return out


async def _midia(client_id: str) -> Dict[str, Any]:
    """Plano do Mídia On do mês e o que a memória semanal de cada campanha recomenda."""
    month = datetime.now(SAO_PAULO).date().replace(day=1).isoformat()
    plans = await sb_select("studio_media_plans", select="month,objective,budget,allocation,notes,status", limit=1,
                            filters={"client_id": f"eq.{client_id}", "month": f"eq.{month}"})
    learnings = await sb_select("studio_campaign_learnings", select="campaign_name,channel,week_end,roas,recommended_action,note",
                                filters={"client_id": f"eq.{client_id}"}, order="week_end.desc", limit=12)
    latest: Dict[str, Dict[str, Any]] = {}
    for row in learnings:
        latest.setdefault(str(row.get("campaign_name")), row)
    plan = plans[0] if plans else {}
    return {k: v for k, v in {
        "plano_do_mes": {"objetivo": plan.get("objective"), "verba": _num(plan.get("budget")), "notas": clean_text(plan.get("notes"), 400),
                         "status": plan.get("status")} if plan else None,
        "campanhas_em_veiculacao": [{"campanha": clean_text(r.get("campaign_name"), 120), "canal": r.get("channel"), "roas": _num(r.get("roas")),
                                     "recomendacao": r.get("recommended_action"), "nota": clean_text(r.get("note"), 200)} for r in list(latest.values())[:6]],
    }.items() if v}


async def _clipping(client_id: str) -> List[Dict[str, Any]]:
    """Notícias relevantes recentes da marca: pauta possível e assunto a evitar."""
    since = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    rows = await sb_select("studio_clippings", select="title,source,kind,sentiment,summary,relevant,published_at", limit=12,
                           filters={"client_id": f"eq.{client_id}", "created_at": f"gte.{since}", "status": "neq.arquivado"},
                           order="published_at.desc.nullslast")
    return [{"manchete": clean_text(r.get("title"), 200), "veiculo": r.get("source"), "tipo": r.get("kind"), "sentimento": r.get("sentiment"),
             "resumo": clean_text(r.get("summary"), 200)} for r in rows if r.get("relevant") is not False][:6]


async def _agenda(client_id: str) -> List[Dict[str, Any]]:
    """O que já está no calendário: evita pauta repetida e mantém a sequência das campanhas."""
    from .studio_calendar import ITEMS_TABLE
    now = datetime.now(SAO_PAULO)
    rows = await sb_select(ITEMS_TABLE, select="scheduled_at,format,pillar,title,status", order="scheduled_at.asc", limit=12,
                           filters={"client_id": f"eq.{client_id}", "status": "neq.rejeitado",
                                    "scheduled_at": f"gte.{now.isoformat()}", "and": f"(scheduled_at.lte.{(now + timedelta(days=21)).isoformat()})"})
    return [{"data": str(r.get("scheduled_at") or "")[:10], "formato": r.get("format"), "pilar": clean_text(r.get("pillar"), 80),
             "pauta": clean_text(r.get("title"), 160), "status": r.get("status")} for r in rows]


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
    profile, business, snap, posts, timing, goals, analysis, learnings, redacao, midia, clipping, agenda = await asyncio.gather(
        _safe("perfil_da_marca", gaps, lambda: _profile(client_id), {}),
        _safe("contexto_do_negocio", gaps, lambda: _business(client_id), {}),
        _safe("kpis_e_campanhas", gaps, lambda: _snapshot(client_id, start, end), {}),
        _safe("posts_instagram", gaps, lambda: _posts(client_id, days), {}),
        _safe("melhores_horarios", gaps, lambda: _timing(client_id), {}),
        _safe("metas", gaps, lambda: _goals(client_id), []),
        _safe("ultima_analise", gaps, lambda: _analysis(client_id), {}),
        _safe("aprendizados_de_aprovacao", gaps, lambda: approval_learnings(client_id), {}),
        _safe("redacao", gaps, lambda: _redacao(client_id), []),
        _safe("midia_on", gaps, lambda: _midia(client_id), {}),
        _safe("clipping", gaps, lambda: _clipping(client_id), []),
        _safe("agenda", gaps, lambda: _agenda(client_id), []),
    )
    package = {
        "periodo": {"inicio": start, "fim": end, "dias": days},
        "marca": {k: profile.get(k) for k in ("tone_of_voice", "personality", "audience", "pillars", "keywords_use",
                                              "keywords_avoid", "hashtags", "restrictions", "custom_dates") if profile.get(k)},
        "negocio": business,
        "kpis": snap.get("metricas") or [],
        "campanhas_que_mais_venderam": snap.get("campanhas") or [],
        "funil_do_site": snap.get("funil_do_site") or {},
        "posts": posts,
        "horarios": timing,
        "metas_do_mes": goals,
        "ultima_analise": analysis,
        "aprendizados": learnings,
        # Módulos conversando: Redação, Mídia On, Clipping e Calendário entram no mesmo pacote.
        "redacao": redacao,
        "midia": midia,
        "clipping": clipping,
        "agenda": agenda,
        "lacunas": sorted(set(gaps) | _empty_sections(profile, business, snap, posts, goals)),
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
    order = sections or ["marca", "negocio", "aprendizados", "redacao", "midia", "agenda", "clipping", "posts", "kpis",
                         "campanhas_que_mais_venderam", "metas_do_mes", "ultima_analise", "funil_do_site", "horarios", "lacunas"]
    data = {k: package.get(k) for k in order if package.get(k)}
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    while len(text) > limit and len(data) > 1:
        data.pop(list(data)[-1])
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return text[:limit]
