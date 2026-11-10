"""
Perfil da marca com IA avançada.

Lê 12 meses da conta para propor o perfil: as publicações mais curtidas e mais salvas/compartilhadas
(com a legenda inteira e as imagens), o que o cliente aprovou, pediu para ajustar, comentou e reescreveu,
e o que a Mídia On e a Origem das vendas mostram que vende. Usa um modelo mais forte
(``OPENAI_PROFILE_MODEL``) só aqui.

Nada é salvo sozinho: a sugestão volta para a equipe revisar. As palavras proibidas e as restrições
que a equipe cadastrou nunca são apagadas pela sugestão. Uma vez por mês o job ``brand-profile-monthly``
gera a sugestão de cada marca ativa e deixa pendente para revisão.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from .ig_supabase import sb_insert, sb_select, sb_update
from .studio_calendar import FORMATS, ITEMS_TABLE, StudioError, load_profile, normalize_profile
from .studio_intelligence import build_content_intelligence, clean_text, coverage, to_prompt
from .studio_llm import INT, STR, arr, llm_json, obj, profile_model

SUGGESTIONS = "studio_profile_suggestions"
DAYS = 365
MAX_IMAGES = 6
IMAGE_MAX_BYTES = 1_500_000


# ------------------------------------------------------------------ fontes

def _n(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _format(row: Dict[str, Any]) -> str:
    product = str(row.get("media_product_type") or "").upper()
    kind = str(row.get("media_type") or "").upper()
    if product == "REELS" or kind == "VIDEO":
        return "reels"
    if kind == "CAROUSEL_ALBUM":
        return "carrossel"
    return "imagem"


def _image_url(row: Dict[str, Any]) -> Optional[str]:
    """Para vídeo, a capa; para foto/carrossel, a própria imagem."""
    url = row.get("thumbnail_url") if _format(row) == "reels" else (row.get("media_url") or row.get("thumbnail_url"))
    url = str(url or "").strip()
    return url if url.startswith("https://") else None


def rank_posts(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Mais curtidas, mais salvas/compartilhadas e as mais fracas (para contraste)."""
    posts = []
    for r in rows:
        ins = r.get("insights_json") or {}
        likes, saved, shares = _n(ins.get("likes")), _n(ins.get("saved")), _n(ins.get("shares"))
        reach = _n(ins.get("reach")) or _n(ins.get("views"))
        if not (likes or saved or shares or reach):
            continue
        posts.append({"formato": _format(r), "data": str(r.get("timestamp") or "")[:10], "curtidas": likes, "salvos": saved,
                      "compartilhamentos": shares, "comentarios": _n(ins.get("comments")), "alcance": reach or None,
                      "legenda": clean_text(r.get("caption"), 900), "_image": _image_url(r), "_key": r.get("permalink") or r.get("timestamp")})
    by_likes = sorted(posts, key=lambda p: p["curtidas"], reverse=True)[:12]
    seen = {p["_key"] for p in by_likes}
    by_saves = [p for p in sorted(posts, key=lambda p: p["salvos"] + p["compartilhamentos"], reverse=True)
                if p["_key"] not in seen and (p["salvos"] + p["compartilhamentos"]) > 0][:8]
    worst = sorted([p for p in posts if p["alcance"]], key=lambda p: (p["curtidas"] + p["salvos"]) / p["alcance"])[:5] if len(posts) >= 15 else []
    images = [p["_image"] for p in by_likes if p["_image"]][:MAX_IMAGES]

    def view(p: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in p.items() if not k.startswith("_")}
    return {"analisados": len(posts), "mais_curtidos": [view(p) for p in by_likes], "mais_salvos_e_compartilhados": [view(p) for p in by_saves],
            "mais_fracos": [view(p) for p in worst], "_images": images}


async def _posts(client_id: str) -> Dict[str, Any]:
    since = (datetime.now(timezone.utc).date() - timedelta(days=DAYS)).isoformat()
    rows = await sb_select("ig_media", select="media_type,media_product_type,timestamp,insights_json,caption,media_url,thumbnail_url,permalink",
                           filters={"client_id": f"eq.{client_id}", "timestamp": f"gte.{since}"}, order="timestamp.desc", limit=500)
    return rank_posts(rows)


async def _validations(client_id: str) -> Dict[str, Any]:
    """Tudo o que o cliente disse sobre os posts: aprovou, pediu ajuste, comentou e reescreveu."""
    from .studio_comments import COMMENTS
    from .studio_team import EVENTS
    since = (datetime.now(timezone.utc) - timedelta(days=DAYS)).isoformat()
    approved, adjusted, comments, edits = await asyncio.gather(
        sb_select(ITEMS_TABLE, select="format,pillar,title,hook,caption_draft,reviewed_by", limit=30, order="reviewed_at.desc",
                  filters={"client_id": f"eq.{client_id}", "status": "in.(aprovado,publicado)", "reviewed_at": f"gte.{since}"}),
        sb_select(ITEMS_TABLE, select="format,title,review_note", limit=15, order="reviewed_at.desc",
                  filters={"client_id": f"eq.{client_id}", "status": "eq.rejeitado", "reviewed_at": f"gte.{since}", "review_note": "not.is.null"}),
        sb_select(COMMENTS, select="body,created_at", limit=20, order="created_at.desc",
                  filters={"client_id": f"eq.{client_id}", "author_side": "eq.cliente", "created_at": f"gte.{since}"}),
        sb_select(EVENTS, select="payload,created_at", limit=12, order="created_at.desc",
                  filters={"client_id": f"eq.{client_id}", "action": "eq.editado_pelo_cliente", "created_at": f"gte.{since}"}),
    )
    approved.sort(key=lambda r: 0 if str(r.get("reviewed_by") or "").startswith("cliente:") else 1)
    rewrites = []
    for row in edits:
        for field, change in ((row.get("payload") or {}).get("edits") or {}).items():
            if isinstance(change, dict) and change.get("depois"):
                rewrites.append({"campo": field, "antes": clean_text(change.get("antes"), 400), "depois": clean_text(change.get("depois"), 400)})
    return {
        "aprovados": [{"formato": r.get("format"), "pilar": clean_text(r.get("pillar"), 80), "pauta": clean_text(r.get("title"), 200),
                       "gancho": clean_text(r.get("hook"), 200), "legenda": clean_text(r.get("caption_draft"), 600),
                       "pelo_cliente": str(r.get("reviewed_by") or "").startswith("cliente:")} for r in approved[:20]],
        "ajustes_pedidos": [{"pauta": clean_text(r.get("title"), 200), "pedido": clean_text(r.get("review_note"), 400)}
                            for r in adjusted if clean_text(r.get("review_note"), 400)],
        "comentarios_do_cliente": [clean_text(c.get("body"), 400) for c in comments if clean_text(c.get("body"), 400)],
        "textos_reescritos_pelo_cliente": rewrites[:12],
    }


async def _download(url: str, client: httpx.AsyncClient) -> Optional[str]:
    """Baixa a imagem aqui (o link do Instagram expira) e manda como data URL. Falha = imagem fica de fora."""
    try:
        response = await client.get(url)
    except httpx.HTTPError:
        return None
    kind = response.headers.get("content-type", "").split(";")[0].strip()
    if response.status_code != 200 or not kind.startswith("image/") or len(response.content) > IMAGE_MAX_BYTES:
        return None
    return f"data:{kind};base64,{base64.b64encode(response.content).decode()}"


async def fetch_images(urls: List[str]) -> List[str]:
    if not urls:
        return []
    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
        results = await asyncio.gather(*(_download(u, client) for u in urls[:MAX_IMAGES]))
    return [r for r in results if r]


async def _safe(name: str, coro, gaps: List[str], fallback):
    try:
        return await asyncio.wait_for(coro, timeout=30)
    except Exception as exc:  # noqa: BLE001 — fonte que falha vira lacuna, não derruba a sugestão
        print(f"[studio][brand_brain] fonte={name} erro={exc.__class__.__name__}")
        gaps.append(name)
        return fallback


async def gather_sources(client_id: str) -> Dict[str, Any]:
    gaps: List[str] = []
    intel, posts, validations = await asyncio.gather(
        build_content_intelligence(client_id, use_cache=False),
        _safe("posts_12_meses", _posts(client_id), gaps, {"analisados": 0, "_images": []}),
        _safe("validacoes", _validations(client_id), gaps, {}),
    )
    images = await _safe("imagens", fetch_images(posts.pop("_images", [])), gaps, [])
    return {"intel": intel, "posts": posts, "validations": validations, "images": images, "gaps": gaps}


# ------------------------------------------------------------------ IA

SCHEMA = obj({
    "tone_of_voice": STR, "personality": STR, "audience": STR,
    "pillars": arr(obj({"name": STR, "weight": INT, "description": STR})),
    "keywords_use": arr(STR), "keywords_avoid": arr(STR), "hashtags": arr(STR), "restrictions": STR,
    "visual_identity": STR,
    "posts_per_week": INT, "formats_enabled": arr({"type": "string", "enum": list(FORMATS)}),
    "reasons": arr(obj({"campo": STR, "motivo": STR})),
    "notes": arr(STR),
})

INSTRUCTIONS = (
    "Você é o Brand Manager sênior da agência. Monta o perfil da marca a partir de evidência: o que o público curtiu, "
    "salvou e compartilhou; o que o cliente aprovou, pediu para mudar, comentou e reescreveu (isso pesa mais que a "
    "opinião da agência); e o que a mídia paga e as vendas mostram que funciona. Nunca invente oferta, número ou "
    "característica que não esteja nos dados."
)


def build_prompt(sources: Dict[str, Any], current: Dict[str, Any]) -> str:
    import json
    intel = sources["intel"]
    return (
        "Monte o PERFIL DA MARCA. Regras:\n"
        "- Tom de voz e personalidade: tire das legendas dos posts mais curtidos e dos textos que o cliente aprovou ou "
        "reescreveu (o 'depois' de cada reescrita mostra como o cliente quer soar).\n"
        "- Palavras proibidas e restrições: inclua o que aparece nos ajustes pedidos e comentários do cliente.\n"
        "- Pilares: 3 a 6, pesos somando 100, puxados dos temas que mais engajam e das campanhas que vendem.\n"
        "- Identidade visual: descreva, a partir das IMAGENS anexadas (posts mais curtidos), cores dominantes, "
        "composição, presença de pessoas/produto, estilo de foto e uso de texto na arte, em até 6 linhas objetivas. "
        "Sem imagens, escreva 'sem imagens para analisar'.\n"
        "- Formatos e posts por semana: pelo que a conta usa e pelo que performa (2 a 7 por semana).\n"
        "- Em reasons, para cada campo que mudou ou foi preenchido, uma frase com a evidência (ex.: 'Tom: 9 dos 12 posts "
        "mais curtidos usam humor leve').\n"
        "- Em notes, 2 a 5 observações gerais e o que ainda falta de dado.\n\n"
        f"PERFIL ATUAL (mantenha o que estiver bom):\n{json.dumps(current, ensure_ascii=False)}\n\n"
        f"PUBLICAÇÕES DOS ÚLTIMOS 12 MESES:\n{json.dumps(sources['posts'], ensure_ascii=False)}\n\n"
        f"VALIDAÇÕES DO CLIENTE:\n{json.dumps(sources['validations'], ensure_ascii=False)}\n\n"
        f"NEGÓCIO, MÍDIA ON, CAMPANHAS E VENDAS:\n"
        f"{to_prompt(intel, sections=['negocio', 'referencias_do_cliente', 'plano_de_midia', 'campanhas_ativas', 'campanhas_que_mais_venderam', 'vendas_por_origem', 'kpis', 'metas_do_mes', 'ultima_analise'], limit=7000)}\n"
    )


def protect_manual(suggested: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    """O que a equipe cadastrou à mão como proibido/restrição nunca some; datas da marca também ficam."""
    out = dict(suggested)
    avoid = list(current.get("keywords_avoid") or [])
    for word in suggested.get("keywords_avoid") or []:
        if word.lower() not in {w.lower() for w in avoid}:
            avoid.append(word)
    out["keywords_avoid"] = avoid
    manual = (current.get("restrictions") or "").strip()
    new = (suggested.get("restrictions") or "").strip()
    out["restrictions"] = manual if not new or new.lower() in manual.lower() else (f"{manual}\n{new}" if manual else new)
    out["custom_dates"] = current.get("custom_dates") or []
    out["content_language"] = current.get("content_language")  # idioma é decisão da equipe, a IA não muda
    out["editorial_platforms"] = current.get("editorial_platforms") or []
    out["posts_per_week_by_platform"] = current.get("posts_per_week_by_platform") or {}
    return normalize_profile(out)


def source_counts(sources: Dict[str, Any]) -> Dict[str, int]:
    v = sources.get("validations") or {}
    p = sources.get("posts") or {}
    return {"posts": int(p.get("analisados") or 0), "imagens": len(sources.get("images") or []),
            "aprovados": len(v.get("aprovados") or []), "ajustes": len(v.get("ajustes_pedidos") or []),
            "comentarios": len(v.get("comentarios_do_cliente") or []), "reescritas": len(v.get("textos_reescritos_pelo_cliente") or []),
            "midia_on": 1 if (sources.get("intel") or {}).get("plano_de_midia") else 0}


async def suggest(client_id: str) -> Dict[str, Any]:
    sources = await gather_sources(client_id)
    current = (await load_profile(client_id))["profile"]
    data = await llm_json(client_id=client_id, instructions=INSTRUCTIONS, prompt=build_prompt(sources, current), schema_name="studio_brand_profile_v2",
                          schema=SCHEMA, temperature=0.3, timeout=150, model=profile_model(), images=sources["images"])
    reasons = [{"campo": clean_text(r.get("campo"), 60), "motivo": clean_text(r.get("motivo"), 300)}
               for r in (data.pop("reasons", None) or []) if isinstance(r, dict) and clean_text(r.get("motivo"), 300)][:14]
    notes = [clean_text(n, 300) for n in (data.pop("notes", None) or [])[:5] if clean_text(n, 300)]
    profile = protect_manual(data, current)
    return {"profile": profile, "notes": notes, "reasons": reasons, "based_on": coverage(sources["intel"]),
            "sources": source_counts(sources), "gaps": sources["gaps"], "model": profile_model()}


# ------------------------------------------------------------------ sugestão mensal

def month_key(today: Optional[date] = None) -> str:
    return (today or datetime.now(timezone.utc).date()).strftime("%Y-%m")


async def pending_suggestion(client_id: str) -> Optional[Dict[str, Any]]:
    rows = await sb_select(SUGGESTIONS, select="id,month,suggestion,created_at", order="created_at.desc", limit=1,
                           filters={"client_id": f"eq.{client_id}", "status": "eq.pendente"})
    return rows[0] if rows else None


async def resolve_suggestion(client_id: str, suggestion_id: str, status: str, *, user_id: str) -> Dict[str, Any]:
    if status not in ("aplicada", "descartada"):
        raise StudioError("INVALID_STATUS")
    rows = await sb_update(SUGGESTIONS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{suggestion_id}", "status": "eq.pendente"},
                           patch={"status": status, "reviewed_by": user_id, "reviewed_at": datetime.now(timezone.utc).isoformat()})
    if not rows:
        raise StudioError("SUGGESTION_NOT_FOUND")
    return {"ok": True, "status": status}


async def _active_clients() -> List[str]:
    """Marcas com perfil salvo ou com post no Calendário nos últimos 60 dias."""
    since = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    profiles = await sb_select("studio_brand_profiles", select="client_id", limit=300)
    items = await sb_select(ITEMS_TABLE, select="client_id", filters={"created_at": f"gte.{since}"}, limit=2000)
    return sorted({str(r["client_id"]) for r in profiles + items if r.get("client_id")})


async def run_monthly(client_id: Optional[str] = None) -> Dict[str, Any]:
    month = month_key()
    clients = [client_id] if client_id else await _active_clients()
    done, skipped, failed = 0, 0, 0
    for cid in clients:
        existing = await sb_select(SUGGESTIONS, select="id", filters={"client_id": f"eq.{cid}", "month": f"eq.{month}"}, limit=1)
        if existing:
            skipped += 1
            continue
        try:
            result = await suggest(cid)
            await sb_insert(SUGGESTIONS, {"client_id": cid, "month": month, "suggestion": result, "status": "pendente"})
            done += 1
        except Exception as exc:  # noqa: BLE001 — uma marca não para as outras
            failed += 1
            print(f"[studio][brand_brain] monthly client_id={cid} failed={getattr(exc, 'code', type(exc).__name__)}")
    return {"month": month, "clients": len(clients), "created": done, "skipped": skipped, "failed": failed}
