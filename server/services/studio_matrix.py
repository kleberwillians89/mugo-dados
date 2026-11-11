"""
Matriz de Conteúdo (trazida da iAgência) — parte da tela Social Media.

A partir dos pilares editoriais do Perfil de Marca e do contexto autorizado da marca (o mesmo cérebro
do Calendário e da Redação: studio_intelligence), a IA sugere oportunidades de conteúdo organizadas por
plataforma, pilar e quatro semanas. A equipe edita, refina, seleciona e descarta; as selecionadas vão
para o Calendário existente como rascunho (origem "matriz") e seguem a aprovação de sempre.

Regras que tornam isso confiável:
* O CÓDIGO confere a saída da IA: plataforma fora do pedido, pilar fora do perfil, semana fora de 1–4
  e formato que a plataforma não tem são descartados; textos são cortados no limite do banco.
* Exportar não duplica: cada oportunidade guarda a pauta criada, e o banco tem índice único em
  studio_calendar_items.matrix_opportunity_id (dois cliques ou duas abas criam uma pauta só).
* Origem "matriz": o "Gerar mês" do Calendário só troca rascunhos com origem "ia", então o que veio
  da Matriz nunca é apagado por uma nova geração.
* Nada aqui cria tarefa: o CRM continua sendo a fonte das tarefas e jobs (fluxo de aprovação de sempre).
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

import httpx

from .brand_guard import check as brand_check
from .ig_supabase import sb_delete, sb_insert, sb_insert_many, sb_select, sb_update
from .studio_calendar import (
    CHANNEL_LABELS, CHANNELS, FORMATS, SAO_PAULO, StudioError, _peak_hour_in_block, best_block_for,
    create_item, language_rule, load_profile,
)
from .studio_engines import throttle
from .studio_intelligence import build_content_intelligence, to_prompt
from .studio_llm import INT, STR, arr, flag_words, llm_json, obj

MATRICES = "studio_content_matrices"
OPPORTUNITIES = "studio_matrix_opportunities"
ITEMS = "studio_calendar_items"

WEEKS = 4
MAX_OPPORTUNITIES = 80
STATUSES = ("sugerida", "selecionada", "descartada", "exportada")
USER_STATUSES = ("sugerida", "selecionada", "descartada")
# Formatos que cada plataforma tem (os mesmos nomes do Calendário).
PLATFORM_FORMATS: Dict[str, tuple] = {
    "instagram": ("reels", "carrossel", "imagem", "stories"),
    "facebook": ("imagem", "video", "carrossel", "stories"),
    "tiktok": ("video",),
    "linkedin": ("imagem", "carrossel", "video"),
    "youtube": ("video",),
    "pinterest": ("imagem", "carrossel", "video"),
}
PLATFORM_TASKS = {
    "instagram": "Instagram: Reels com gancho nos 3 primeiros segundos, carrossel que ensina ou conta história, imagem única forte, Stories com interação.",
    "facebook": "Facebook: posts que geram conversa e compartilhamento; vídeo curto; público um pouco mais maduro.",
    "tiktok": "TikTok: vídeo nativo, cru, com tendência ou formato da plataforma; gancho imediato; nada com cara de anúncio.",
    "linkedin": "LinkedIn: bastidores, aprendizado, autoridade e números do negócio; tom profissional sem ser frio.",
    "youtube": "YouTube: vídeo (Shorts ou longo) com título buscável e promessa clara.",
    "pinterest": "Pinterest: Pin visual e buscável, com utilidade duradoura, título descritivo e destino coerente.",
}
EDIT_FIELDS = ("platform", "pillar", "week", "weekday", "format", "title", "hook", "angle", "caption_draft", "rationale", "script", "visual_idea")
LIMITS = {"title": 200, "hook": 400, "angle": 600, "caption_draft": 4000, "rationale": 1200, "pillar": 120, "script": 4000, "visual_idea": 2000}

ROLE = ("Você é estrategista de conteúdo e social media sênior de agência. Monta a matriz de conteúdo do próximo "
        "mês para a marca descrita nos DADOS: oportunidades concretas, ligadas aos pilares editoriais da marca, ao "
        "que já performou, ao que vendeu e ao momento do negócio. Cada oportunidade é uma pauta que dá para produzir.")

OPPORTUNITY_SCHEMA = obj({"plataforma": STR, "pilar": STR, "semana": INT, "dia_semana": INT, "formato": STR,
                          "titulo": STR, "gancho": STR, "angulo": STR, "legenda": STR, "por_que": STR})
MATRIX_SCHEMA = obj({"resumo": STR, "oportunidades": arr(OPPORTUNITY_SCHEMA)})


# ---------------------------------------------------------------- utilidades

def _clip(value: Any, limit: int) -> str:
    return re.sub(r"\s*[—–]\s*", ", ", str(value or "")).strip()[:limit]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def next_monday(today: Optional[date] = None) -> date:
    today = today or datetime.now(SAO_PAULO).date()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


def _pillar_names(profile: Dict[str, Any]) -> List[str]:
    return [p["name"] for p in profile.get("pillars") or [] if p.get("name")]


def _match_pillar(value: Any, pillars: Iterable[str]) -> Optional[str]:
    wanted = str(value or "").strip().lower()
    for name in pillars:
        if name.lower() == wanted:
            return name
    return None


def normalize_request(data: Dict[str, Any], profile: Dict[str, Any], *, today: Optional[date] = None) -> Dict[str, Any]:
    """Plano automático: o corpo legado não altera as premissas salvas no Perfil da marca."""
    pillars_all = _pillar_names(profile)
    if not pillars_all:
        raise StudioError("MATRIX_PILLARS_REQUIRED")
    platforms = [p for p in dict.fromkeys(profile.get("editorial_platforms") or []) if p in CHANNELS]
    if not platforms:
        raise StudioError("MATRIX_PLATFORMS_REQUIRED")
    today = today or datetime.now(SAO_PAULO).date()
    specific = profile.get("posts_per_week_by_platform") if isinstance(profile.get("posts_per_week_by_platform"), dict) else {}
    quotas = {p: max(1, min(14, int(specific[p]))) for p in platforms if specific.get(p)}
    configured_total = max(1, min(14, int(profile.get("posts_per_week") or 3)))
    # Frequências específicas são pisos exatos das redes configuradas. Quando somente algumas
    # redes têm ritmo próprio, o restante do total continua disponível para as demais.
    total = max(configured_total, sum(quotas.values())) if quotas else configured_total
    if total * WEEKS > MAX_OPPORTUNITIES:
        raise StudioError("MATRIX_FREQUENCY_TOO_HIGH")
    return {"week_start": next_monday(today), "platforms": platforms, "pillars": pillars_all,
            "posts_per_week": total, "platform_quotas": quotas, "focus": ""}


def week_dates(start: date, week: int) -> tuple[date, date]:
    first = start + timedelta(days=7 * (week - 1))
    return first, first + timedelta(days=6)


def clean_opportunity(raw: Dict[str, Any], *, platforms: List[str], pillars: List[str]) -> Optional[Dict[str, Any]]:
    """Uma oportunidade da IA, conferida campo a campo. None = descartada."""
    platform = str(raw.get("plataforma") or "").strip().lower()
    platform = {"ig": "instagram", "fb": "facebook", "tik tok": "tiktok", "yt": "youtube"}.get(platform, platform)
    if platform not in platforms:
        return None
    pillar = _match_pillar(raw.get("pilar"), pillars)
    title = _clip(raw.get("titulo"), LIMITS["title"])
    if not pillar or not title:
        return None
    try:
        week = int(raw.get("semana"))
    except (TypeError, ValueError):
        return None
    if not 1 <= week <= WEEKS:
        return None
    try:
        weekday = int(raw.get("dia_semana"))
    except (TypeError, ValueError):
        weekday = 1
    weekday = weekday if 0 <= weekday <= 6 else 1
    fmt = str(raw.get("formato") or "").strip().lower()
    allowed = PLATFORM_FORMATS[platform]
    fmt = fmt if fmt in allowed else allowed[0]
    return {"platform": platform, "pillar": pillar, "week": week, "weekday": weekday, "format": fmt, "title": title,
            "hook": _clip(raw.get("gancho"), LIMITS["hook"]) or None, "angle": _clip(raw.get("angulo"), LIMITS["angle"]) or None,
            "caption_draft": _clip(raw.get("legenda"), LIMITS["caption_draft"]) or None,
            "rationale": _clip(raw.get("por_que"), LIMITS["rationale"]) or None}


def _guard(op: Dict[str, Any], avoid: List[str], context: str) -> List[Dict[str, str]]:
    text = "\n".join(str(op.get(k) or "") for k in ("title", "hook", "angle", "caption_draft"))
    issues = [g for g in brand_check(text, avoid=avoid, context=context) if g.get("type") != "palavra_proibida"]
    words = flag_words(text, avoid)
    if words:
        issues.append({"type": "palavra_evitar", "text": ", ".join(words), "fix": f"Palavra a evitar: {', '.join(words)}"})
    return issues[:6]


def cap_to_plan(items: List[Dict[str, Any]], request: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Aplica o ritmo do Perfil sem multiplicá-lo pela quantidade de plataformas."""
    count: Dict[tuple, int] = {}
    per_week: Dict[int, int] = {}
    quotas = request.get("platform_quotas") or {}
    out: List[Dict[str, Any]] = []
    for it in items:
        key = (it["platform"], it["week"])
        if it["platform"] in quotas and count.get(key, 0) >= int(quotas[it["platform"]]):
            continue
        if per_week.get(it["week"], 0) >= int(request["posts_per_week"]):
            continue
        count[key] = count.get(key, 0) + 1
        per_week[it["week"]] = per_week.get(it["week"], 0) + 1
        out.append(it)
    return out[:MAX_OPPORTUNITIES]


def build_prompt(req: Dict[str, Any], profile: Dict[str, Any], intel: Dict[str, Any], recent: Optional[List[Dict[str, Any]]] = None) -> str:
    start: date = req["week_start"]
    weeks = "\n".join(f"- Semana {w}: {week_dates(start, w)[0].strftime('%d/%m')} a {week_dates(start, w)[1].strftime('%d/%m')}"
                      for w in range(1, WEEKS + 1))
    pillars = [p for p in profile.get("pillars") or [] if p.get("name") in req["pillars"]]
    return (
        f"PERÍODO (4 semanas, começando na segunda):\n{weeks}\n"
        f"\nPLATAFORMAS E COMO PENSAR CADA UMA:\n" + "\n".join(f"- {p} ({', '.join(PLATFORM_FORMATS[p])}): {PLATFORM_TASKS[p]}" for p in req["platforms"])
        + f"\n\nPILARES EDITORIAIS (use exatamente estes nomes; respeite o peso de cada um):\n{json.dumps(pillars, ensure_ascii=False)}"
        + f"\n\nRITMO TOTAL: exatamente {req['posts_per_week']} oportunidade(s) por semana, somadas entre todas as plataformas; "
          "não multiplique pela quantidade de plataformas. "
        + (f"Use exatamente estas quantidades por rede e distribua o restante entre as demais: "
           f"{json.dumps(req['platform_quotas'], ensure_ascii=False)}."
           if req["platform_quotas"] else "Escolha a distribuição mais pertinente à estratégia da marca.")
        + "\n\nCada oportunidade: plataforma (um dos nomes acima, minúsculo), pilar, semana (1 a 4), dia_semana "
          "(0 = segunda ... 6 = domingo), formato (um dos da plataforma), título da pauta, gancho (primeira frase ou cena), "
          "ângulo (o que torna esta pauta diferente), rascunho de legenda e por que (cite o dado da marca que sustenta). "
          "Sem travessão. Não invente oferta, preço, número ou prazo que não esteja nos DADOS."
        + "\n\nVARIEDADE: cada gancho começa de um jeito diferente (as 3 primeiras palavras não se repetem), nunca duas pautas "
          "seguidas com o mesmo ângulo, a mesma CTA no máximo 2 vezes, e nada parecido com outra oportunidade nem com o que já foi planejado "
          "recentemente (abaixo). Legenda enxuta, até 600 caracteres."
        + (f"\nJÁ PLANEJADO RECENTEMENTE (não repetir tema nem abertura):\n{json.dumps(recent, ensure_ascii=False)}" if recent else "")
        + "\nAlém das oportunidades: um resumo da estratégia do mês em 2 frases."
        + f"\n\nDADOS DA MARCA:\n{to_prompt(intel)}\n\n{language_rule(profile)}"
    )


def _guard_context(profile: Dict[str, Any], intel: Dict[str, Any], focus: str = "") -> str:
    return json.dumps({"foco": focus, "marca": profile, "negocio": intel.get("negocio"),
                       "vendas_por_origem": intel.get("vendas_por_origem"), "campanhas_ativas": intel.get("campanhas_ativas")},
                      ensure_ascii=False, default=str)


# ---------------------------------------------------------------- leitura

async def list_matrices(client_id: str) -> List[Dict[str, Any]]:
    return await sb_select(MATRICES, select="id,week_start,platforms,pillars,focus,summary,status,created_at,updated_at",
                           filters={"client_id": f"eq.{client_id}", "status": "eq.ativa"}, order="created_at.desc", limit=20)


async def get_matrix(client_id: str, matrix_id: str) -> Dict[str, Any]:
    rows = await sb_select(MATRICES, select="*", filters={"client_id": f"eq.{client_id}", "id": f"eq.{matrix_id}"}, limit=1)
    if not rows:
        raise StudioError("MATRIX_NOT_FOUND")
    ops = await sb_select(OPPORTUNITIES, select="*", filters={"client_id": f"eq.{client_id}", "matrix_id": f"eq.{matrix_id}"},
                          order="week.asc,platform.asc,position.asc", limit=MAX_OPPORTUNITIES + 20)
    return {**rows[0], "opportunities": ops}


async def _opportunity(client_id: str, opportunity_id: str) -> Dict[str, Any]:
    rows = await sb_select(OPPORTUNITIES, select="*", filters={"client_id": f"eq.{client_id}", "id": f"eq.{opportunity_id}"}, limit=1)
    if not rows:
        raise StudioError("OPPORTUNITY_NOT_FOUND")
    return rows[0]


# ---------------------------------------------------------------- geração

async def generate(client_id: str, data: Dict[str, Any], *, user_id: str, today: Optional[date] = None) -> Dict[str, Any]:
    profile = (await load_profile(client_id))["profile"]
    req = normalize_request(data, profile, today=today)
    throttle(client_id)
    intel = await build_content_intelligence(client_id)
    from .content_variety import recent_content
    prompt = build_prompt(req, profile, intel, recent=await recent_content(client_id))
    expected = req["posts_per_week"] * WEEKS

    async def attempt() -> tuple:
        raw = await llm_json(client_id=client_id, instructions=ROLE, prompt=prompt,
                             schema_name="studio_content_matrix", schema=MATRIX_SCHEMA, temperature=0.7, timeout=150)
        cleaned = [c for c in (clean_opportunity(r, platforms=req["platforms"], pillars=req["pillars"])
                               for r in raw.get("oportunidades") or [] if isinstance(r, dict)) if c]
        return raw, cleaned, cap_to_plan(cleaned, req)

    # A IA raramente acerta a contagem exata (ou erra um pilar/semana): antes a matriz inteira era recusada.
    # Agora tenta de novo uma vez e, se ainda faltar, salva o que veio e avisa o que falta.
    raw, cleaned, items = await attempt()
    if len(items) < expected:
        try:
            retry = await attempt()
            if len(retry[2]) > len(items):
                raw, cleaned, items = retry
        except StudioError:
            pass
    if not items:
        raise StudioError("AI_INVALID_OUTPUT")
    notes: List[str] = []
    if len(items) < expected:
        notes.append(f"A IA sugeriu {len(items)} de {expected} pautas planejadas. Complete à mão ou gere de novo.")
    discarded = len(raw.get("oportunidades") or []) - len(cleaned)
    if discarded > 0:
        notes.append(f"{discarded} sugestão(ões) da IA fora da plataforma, do pilar ou da semana foram descartadas.")
    missing = [p for p in req["platforms"] if not any(i["platform"] == p for i in items)]
    if missing:
        notes.append(f"A IA não sugeriu nada para {', '.join(CHANNEL_LABELS[p] for p in missing)}. Gere de novo ou crie à mão.")
    pillars = [p for p in profile.get("pillars") or [] if p.get("name") in req["pillars"]]
    matrix = await sb_insert(MATRICES, {
        "client_id": client_id, "week_start": req["week_start"].isoformat(), "platforms": req["platforms"],
        "pillars": pillars, "focus": req["focus"] or None, "summary": _clip(raw.get("resumo"), 1200) or None,
        "notes": notes, "created_by": user_id,
    })
    if not matrix or not matrix.get("id"):
        raise StudioError("MATRIX_SAVE_FAILED")
    avoid = list(profile.get("keywords_avoid") or [])
    context = _guard_context(profile, intel, req["focus"])
    rows = [{**it, "matrix_id": matrix["id"], "client_id": client_id, "position": i, "status": "sugerida",
             "guard": _guard(it, avoid, context)} for i, it in enumerate(items)]
    await sb_insert_many(OPPORTUNITIES, rows)
    return await get_matrix(client_id, matrix["id"])


# ---------------------------------------------------------------- edição

def _clean_patch(patch: Dict[str, Any]) -> Dict[str, Any]:
    clean: Dict[str, Any] = {}
    for key in EDIT_FIELDS:
        if key not in patch or patch[key] is None:
            continue
        value = patch[key]
        if key == "platform":
            if value not in PLATFORM_FORMATS:
                raise StudioError("CHANNEL_INVALID")
        elif key == "pillar":
            value = _clip(value, LIMITS["pillar"])
            if not value:
                raise StudioError("OPPORTUNITY_INVALID")
        elif key == "week":
            if not 1 <= int(value) <= WEEKS:
                raise StudioError("OPPORTUNITY_INVALID")
        elif key == "weekday":
            if not 0 <= int(value) <= 6:
                raise StudioError("OPPORTUNITY_INVALID")
        elif key == "format":
            if value not in FORMATS:
                raise StudioError("FORMAT_INVALID")
        else:
            value = _clip(value, LIMITS[key]) or None
            if key == "title" and not value:
                raise StudioError("OPPORTUNITY_INVALID")
        clean[key] = value
    return clean


async def _retitle_exported(client_id: str, current: Dict[str, Any], title: Any) -> Dict[str, Any]:
    """Texto da pauta editado direto no card, mesmo depois de ir ao Calendário: a pauta lá muda junto."""
    clean = _clean_patch({"title": title})
    now = _now().isoformat()
    rows = await sb_update(OPPORTUNITIES, filters={"client_id": f"eq.{client_id}", "id": f"eq.{current['id']}"},
                           patch={**clean, "edited": True, "updated_at": now})
    if not rows:
        raise StudioError("OPPORTUNITY_NOT_FOUND")
    if current.get("calendar_item_id"):
        await sb_update(ITEMS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{current['calendar_item_id']}"},
                        patch={"title": clean["title"], "updated_at": now})
    return rows[0]


async def update_opportunity(client_id: str, opportunity_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Equipe edita a oportunidade (texto, plataforma, pilar, semana) ou muda o status (selecionar/descartar)."""
    current = await _opportunity(client_id, opportunity_id)
    if current.get("status") == "exportada":
        if set(patch) == {"title"}:
            return await _retitle_exported(client_id, current, patch["title"])
        raise StudioError("OPPORTUNITY_EXPORTED")
    clean = _clean_patch(patch)
    status = patch.get("status")
    if status is not None:
        if status not in USER_STATUSES:
            raise StudioError("STATUS_INVALID")
        clean["status"] = status
    platform = clean.get("platform", current.get("platform"))
    fmt = clean.get("format", current.get("format"))
    if fmt not in PLATFORM_FORMATS.get(platform, FORMATS):
        if "format" in clean:
            raise StudioError("FORMAT_INVALID")
        clean["format"] = PLATFORM_FORMATS[platform][0]
    if not clean:
        raise StudioError("EMPTY_PATCH")
    if any(k in clean for k in EDIT_FIELDS):
        clean["edited"] = True
    rows = await sb_update(OPPORTUNITIES, filters={"client_id": f"eq.{client_id}", "id": f"eq.{opportunity_id}",
                                                   "status": "neq.exportada"},
                           patch={**clean, "updated_at": _now().isoformat()})
    if not rows:
        raise StudioError("OPPORTUNITY_EXPORTED")
    return rows[0]


async def create_opportunity(client_id: str, matrix_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Acrescenta uma oportunidade editável à matriz ativa, sempre dentro do mesmo tenant."""
    matrix = await get_matrix(client_id, matrix_id)
    if matrix.get("status") != "ativa":
        raise StudioError("MATRIX_NOT_FOUND")
    required = {"platform", "pillar", "week", "weekday", "format", "title"}
    if not required <= {k for k, value in data.items() if value is not None and value != ""}:
        raise StudioError("OPPORTUNITY_INVALID")
    clean = _clean_patch(data)
    if clean.get("platform") not in (matrix.get("platforms") or []):
        raise StudioError("CHANNEL_INVALID")
    known_pillars = _pillar_names({"pillars": matrix.get("pillars") or []})
    if clean.get("pillar") not in known_pillars:
        raise StudioError("OPPORTUNITY_INVALID")
    if clean.get("format") not in PLATFORM_FORMATS[clean["platform"]]:
        raise StudioError("FORMAT_INVALID")
    position = max((int(o.get("position") or 0) for o in matrix.get("opportunities") or []), default=-1) + 1
    row = await sb_insert(OPPORTUNITIES, {**clean, "matrix_id": matrix_id, "client_id": client_id, "position": position,
                                          "status": "sugerida", "edited": True, "guard": []})
    if not row or not row.get("id"):
        raise StudioError("MATRIX_SAVE_FAILED")
    return row


async def delete_opportunity(client_id: str, matrix_id: str, opportunity_id: str) -> Dict[str, Any]:
    """Exclui somente uma oportunidade não exportada; o vínculo com Calendário nunca é apagado."""
    current = await _opportunity(client_id, opportunity_id)
    if current.get("matrix_id") != matrix_id:
        raise StudioError("OPPORTUNITY_NOT_FOUND")
    if current.get("status") == "exportada" or current.get("calendar_item_id"):
        raise StudioError("OPPORTUNITY_EXPORTED")
    rows = await sb_delete(OPPORTUNITIES, filters={"client_id": f"eq.{client_id}", "matrix_id": f"eq.{matrix_id}",
                                                   "id": f"eq.{opportunity_id}",
                                                   "status": "neq.exportada"})
    if not rows:
        raise StudioError("OPPORTUNITY_NOT_FOUND")
    return current


async def set_many_status(client_id: str, matrix_id: str, ids: List[str], status: str) -> Dict[str, Any]:
    """Selecionar ou descartar várias de uma vez. As já exportadas ficam como estão."""
    if status not in USER_STATUSES:
        raise StudioError("STATUS_INVALID")
    ids = [i for i in dict.fromkeys(ids) if i][:MAX_OPPORTUNITIES]
    if not ids:
        raise StudioError("EMPTY_PATCH")
    rows = await sb_update(OPPORTUNITIES, filters={"client_id": f"eq.{client_id}", "matrix_id": f"eq.{matrix_id}",
                                                   "id": f"in.({','.join(ids)})", "status": "neq.exportada"},
                           patch={"status": status, "updated_at": _now().isoformat()})
    return {"updated": len(rows or []), "matrix": await get_matrix(client_id, matrix_id)}


async def refine_opportunity(client_id: str, opportunity_id: str, *, instruction: Optional[str]) -> Dict[str, Any]:
    """Reescreve uma oportunidade com a IA (outro ângulo ou o pedido da equipe), mantendo plataforma, pilar e semana."""
    current = await _opportunity(client_id, opportunity_id)
    if current.get("status") == "exportada":
        raise StudioError("OPPORTUNITY_EXPORTED")
    throttle(client_id)
    profile = (await load_profile(client_id))["profile"]
    intel = await build_content_intelligence(client_id)
    platform = current["platform"]
    keep = {k: current.get(k) for k in ("platform", "pillar", "week", "weekday", "format", "title", "hook", "angle", "caption_draft", "rationale")}
    prompt = (f"OPORTUNIDADE ATUAL (reescreva mantendo plataforma, pilar e semana):\n{json.dumps(keep, ensure_ascii=False)}\n"
              f"PLATAFORMA: {PLATFORM_TASKS[platform]} Formatos possíveis: {', '.join(PLATFORM_FORMATS[platform])}.\n"
              + (f"PEDIDO DA EQUIPE: {_clip(instruction, 600)}\n" if instruction and instruction.strip()
                 else "Sem pedido específico: traga outro ângulo, mais forte.\n")
              + "Sem travessão. Não invente oferta, preço, número ou prazo que não esteja nos DADOS.\n"
              + f"\nDADOS DA MARCA:\n{to_prompt(intel)}\n\n{language_rule(profile)}")
    data = await llm_json(client_id=client_id, instructions=ROLE, prompt=prompt, schema_name="studio_matrix_refine",
                          schema=obj({"oportunidade": OPPORTUNITY_SCHEMA}), temperature=0.8)
    raw = {**(data.get("oportunidade") or {}), "plataforma": platform, "pilar": current["pillar"], "semana": current["week"]}
    cleaned = clean_opportunity(raw, platforms=[platform], pillars=[current["pillar"]])
    if not cleaned:
        raise StudioError("AI_INVALID_OUTPUT")
    guard = _guard(cleaned, list(profile.get("keywords_avoid") or []), _guard_context(profile, intel))
    rows = await sb_update(OPPORTUNITIES, filters={"client_id": f"eq.{client_id}", "id": f"eq.{opportunity_id}",
                                                   "status": "neq.exportada"},
                           patch={**cleaned, "guard": guard, "edited": True, "updated_at": _now().isoformat()})
    if not rows:
        raise StudioError("OPPORTUNITY_EXPORTED")
    return rows[0]


# ---------------------------------------------------------------- criação do conteúdo (na Matriz)

SCRIPT_GUIDE = {
    "reels": "Roteiro de vídeo curto em cenas numeradas (Cena 1, Cena 2…): o que aparece e o que se fala, com o gancho nos 3 primeiros segundos e CTA no fim.",
    "video": "Roteiro de vídeo em cenas numeradas (Cena 1, Cena 2…): o que aparece e o que se fala, gancho no início e CTA no fim.",
    "carrossel": "Texto de cada slide numerado (Slide 1 = capa com o gancho, slides do meio desenvolvem, último slide com CTA). Frases curtas.",
    "stories": "Sequência de telas numeradas (Tela 1, Tela 2…), com o texto de cada uma e a interação sugerida (enquete, caixa, link).",
    "imagem": "Texto curto que vai na arte (título e, se fizer sentido, uma linha de apoio).",
}
CONTENT_SCHEMA = obj({"gancho": STR, "legenda": STR, "roteiro": STR, "ideia_imagem": STR,
                      # Briefing da peça (Atendimento do iAgência): nasce junto com o conteúdo.
                      "resumo": STR, "objetivo": STR, "mensagem_central": STR, "tom": STR, "publico": STR,
                      "entregaveis": arr(STR), "requisitos_tecnicos": arr(STR)})


async def create_content(client_id: str, opportunity_id: str, *, instruction: Optional[str] = None) -> Dict[str, Any]:
    """A IA cria o conteúdo da pauta: gancho, legenda, roteiro (cenas/slides/telas) e ideia de imagem."""
    current = await _opportunity(client_id, opportunity_id)
    if current.get("status") == "exportada":
        raise StudioError("OPPORTUNITY_EXPORTED")
    throttle(client_id)
    profile = (await load_profile(client_id))["profile"]
    intel = await build_content_intelligence(client_id)
    fmt = current.get("format") or "imagem"
    base = {k: current.get(k) for k in ("platform", "pillar", "format", "title", "hook", "angle", "rationale")}
    prompt = (f"PAUTA (crie o conteúdo completo dela, sem mudar o tema):\n{json.dumps(base, ensure_ascii=False)}\n"
              f"PLATAFORMA: {PLATFORM_TASKS[current['platform']]}\n"
              f"ROTEIRO: {SCRIPT_GUIDE.get(fmt, SCRIPT_GUIDE['imagem'])}\n"
              "IDEIA DE IMAGEM: direção da arte para o designer ou a IA de imagem: cena ou composição, enquadramento, pessoas ou objetos, "
              "cores e estilo da marca, texto na arte. 3 a 6 linhas, concreto.\n"
              "LEGENDA: no tom da marca, com CTA e hashtags do perfil se houver.\n"              "BRIEFING (para quem produz, curto e concreto): resumo (até 2 frases), objetivo (1 frase), mensagem_central (1 frase), "
              "tom (poucas palavras, do perfil), publico (1 frase), entregaveis (ex.: 'Reels 9:16 de 20 a 30 s', 'capa') e "
              "requisitos_tecnicos (proporção, duração, slides, legenda na tela, áudio), até 4 itens cada.\n"
              + (f"PEDIDO DA EQUIPE: {_clip(instruction, 600)}\n" if instruction and instruction.strip() else "")
              + "Sem travessão. Não invente oferta, preço, número ou prazo que não esteja nos DADOS.\n"
              + f"\nDADOS DA MARCA:\n{to_prompt(intel)}\n\n{language_rule(profile)}")
    data = await llm_json(client_id=client_id, instructions=ROLE, prompt=prompt, schema_name="studio_matrix_content",
                          schema=CONTENT_SCHEMA, temperature=0.7)
    patch = {"hook": _clip(data.get("gancho"), LIMITS["hook"]) or current.get("hook"),
             "caption_draft": _clip(data.get("legenda"), LIMITS["caption_draft"]) or None,
             "script": _clip(data.get("roteiro"), LIMITS["script"]) or None,
             "visual_idea": _clip(data.get("ideia_imagem"), LIMITS["visual_idea"]) or None}
    from .studio_engines import clean_briefing
    briefing = clean_briefing({"summary": data.get("resumo"), "objective": data.get("objetivo"), "key_message": data.get("mensagem_central"),
                               "tone": data.get("tom"), "target_audience": data.get("publico"),
                               "deliverables": data.get("entregaveis"), "tech_requirements": data.get("requisitos_tecnicos")})
    if not (patch["caption_draft"] or patch["script"] or patch["visual_idea"]):
        raise StudioError("AI_INVALID_OUTPUT")
    merged = {**current, **patch}
    guard = _guard(merged, list(profile.get("keywords_avoid") or []), _guard_context(profile, intel))
    filters = {"client_id": f"eq.{client_id}", "id": f"eq.{opportunity_id}", "status": "neq.exportada"}
    full = {**patch, "guard": guard, "edited": True, "updated_at": _now().isoformat()}
    try:
        rows = await sb_update(OPPORTUNITIES, filters=filters, patch={**full, "briefing": briefing} if briefing else full)
    except Exception as error:  # banco sem a migração 000099: salva o conteúdo sem o briefing
        if "briefing" not in str(error):
            raise
        rows = await sb_update(OPPORTUNITIES, filters=filters, patch=full)
    if not rows:
        raise StudioError("OPPORTUNITY_EXPORTED")
    return rows[0]


# ---------------------------------------------------------------- exportação para o Calendário

async def _posting_times(client_id: str) -> Dict[str, Any]:
    try:
        from .posting_times import build_posting_times
        today = datetime.now(SAO_PAULO).date()
        return await build_posting_times(client_id, start=(today - timedelta(days=179)).isoformat(), end=today.isoformat())
    except Exception as exc:  # noqa: BLE001 — sem histórico, horário padrão de mercado
        print(f"[studio][matrix] client_id={client_id} posting_times_failed={type(exc).__name__}")
        return {}


def schedule_for(op: Dict[str, Any], week_start: date, best: Dict[str, Any], *, now: Optional[datetime] = None) -> datetime:
    """Data da oportunidade (semana + dia sugerido) no melhor horário daquele dia da semana.
    Se o dia já passou, vai para o próximo dia livre (amanhã), no mesmo horário."""
    day = week_start + timedelta(days=7 * (int(op["week"]) - 1) + int(op.get("weekday") or 0))
    block, _ = best_block_for(day.weekday(), best)
    hour = _peak_hour_in_block(block, best)
    when = datetime.combine(day, dtime(hour=hour), tzinfo=SAO_PAULO)
    now = (now or _now()).astimezone(SAO_PAULO)
    if when <= now + timedelta(hours=1):
        when = datetime.combine(now.date() + timedelta(days=1), dtime(hour=hour), tzinfo=SAO_PAULO)
    return when


def _calendar_row(op: Dict[str, Any], when: datetime, summary: Optional[str]) -> Dict[str, Any]:
    why = " ".join(x for x in (op.get("rationale"), f"Ângulo: {op['angle']}" if op.get("angle") else None) if x)
    return {"scheduled_at": when.isoformat(), "channel": op["platform"], "format": op["format"], "title": op["title"],
            "pillar": op.get("pillar"), "hook": op.get("hook"), "caption_draft": op.get("caption_draft"),
            "script": op.get("script"), "visual_idea": op.get("visual_idea"),
            # Briefing nascido na Matriz segue para a pauta (signals.briefing).
            **({"briefing": op["briefing"]} if isinstance(op.get("briefing"), dict) and op.get("briefing") else {}),
            "rationale": (f"Matriz de conteúdo: {why}" if why else (f"Matriz de conteúdo. {summary or ''}".strip()))[:1200]}


def _is_conflict(exc: Exception) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response is not None and exc.response.status_code == 409


async def _existing_item(client_id: str, opportunity_id: str) -> Optional[Dict[str, Any]]:
    rows = await sb_select(ITEMS, select="id", filters={"client_id": f"eq.{client_id}", "matrix_opportunity_id": f"eq.{opportunity_id}"}, limit=1)
    return rows[0] if rows else None


async def export_to_calendar(client_id: str, matrix_id: str, *, user_id: str, ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Selecionadas (ou as ``ids`` pedidas) viram rascunho no Calendário. Repetir não duplica."""
    matrix = await get_matrix(client_id, matrix_id)
    wanted = set(ids or [])
    targets = [o for o in matrix["opportunities"]
               if (o["id"] in wanted if wanted else o.get("status") == "selecionada") and o.get("status") != "descartada"]
    if not targets:
        raise StudioError("MATRIX_NOTHING_SELECTED")
    week_start = date.fromisoformat(str(matrix["week_start"])[:10])
    best = await _posting_times(client_id)
    created, already, item_ids, created_ids = 0, 0, [], []
    for op in targets:
        item_id = op.get("calendar_item_id")
        if item_id:
            already += 1
            item_ids.append(item_id)
            continue
        found = await _existing_item(client_id, op["id"])
        if found:
            already += 1
        else:
            try:
                found = await create_item(client_id, _calendar_row(op, schedule_for(op, week_start, best), matrix.get("summary")),
                                          user_id=user_id, origin="matriz", matrix_opportunity_id=op["id"])
                created += 1
                created_ids.append(found.get("id"))
            except Exception as exc:  # noqa: BLE001
                if not _is_conflict(exc):
                    raise
                # Outra aba exportou ao mesmo tempo: o índice único segurou; usa a pauta que já existe.
                found = await _existing_item(client_id, op["id"])
                already += 1
        if not found or not found.get("id"):
            raise StudioError("CREATE_FAILED")
        item_ids.append(found["id"])
        await sb_update(OPPORTUNITIES, filters={"client_id": f"eq.{client_id}", "id": f"eq.{op['id']}"},
                        patch={"status": "exportada", "calendar_item_id": found["id"], "updated_at": _now().isoformat()})
    return {"created": created, "already": already, "calendar_item_ids": item_ids, "created_ids": [i for i in created_ids if i],
            "matrix": await get_matrix(client_id, matrix_id)}


async def archive(client_id: str, matrix_id: str) -> Dict[str, Any]:
    rows = await sb_update(MATRICES, filters={"client_id": f"eq.{client_id}", "id": f"eq.{matrix_id}"},
                           patch={"status": "arquivada", "updated_at": _now().isoformat()})
    if not rows:
        raise StudioError("MATRIX_NOT_FOUND")
    return rows[0]
