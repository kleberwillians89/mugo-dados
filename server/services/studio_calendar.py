"""Mugô Studio — perfil de marca e calendário editorial do mês.

Divisão de responsabilidades (o que torna o calendário confiável):

* O CÓDIGO decide QUANDO e EM QUE FORMATO: dias e faixas de horário vêm do
  desempenho real dos posts (services/posting_times.py), o formato segue o
  alcance mediano de cada formato na conta, e datas sazonais ganham post.
* A IA decide O QUÊ: pilar, pauta, gancho e rascunho de legenda, com o perfil
  da marca, o contexto do negócio, os posts que mais performaram e, se
  combinar, um assunto em alta com fonte. Saída validada campo a campo:
  slot desconhecido, pilar fora do perfil ou tendência sem fonte são
  descartados.
* A PESSOA decide se vai ao ar: tudo nasce "rascunho" e só a revisão aprova.
  Nada aqui publica em rede social.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import httpx

from .business_context import load_business_context
from .ig_supabase import sb_delete, sb_insert_many, sb_select, sb_update, sb_upsert
from .posting_times import WEEKDAYS, build_posting_times
from .studio_dates import COMMERCIAL, CUSTOM, dates_for_month
from .studio_trends import fetch_trends_br

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
FORMATS = ("reels", "carrossel", "imagem", "stories", "video")
DEFAULT_FORMATS = ("reels", "carrossel", "imagem")
STATUSES = ("rascunho", "em_revisao", "aprovado", "rejeitado")
DEFAULT_WEEKDAY_ORDER = (1, 3, 2, 0, 4, 5, 6)  # ter, qui, qua, seg, sex, sáb, dom
DEFAULT_BLOCK = "18h-21h"
GENERATION_COOLDOWN_SECONDS = 90
MAX_TRENDS_IN_PROMPT = 10
MAX_TOP_POSTS = 8

PROFILE_TABLE = "studio_brand_profiles"
ITEMS_TABLE = "studio_calendar_items"


class StudioError(RuntimeError):
    """Erro com código estável para a rota traduzir em HTTP."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


# --------------------------------------------------------------------------
# Perfil de marca
# --------------------------------------------------------------------------

def _text(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _str_list(values: Any, *, item_limit: int, max_items: int) -> List[str]:
    if isinstance(values, str):
        values = re.split(r"[,\n]", values)
    out: List[str] = []
    for value in values or []:
        item = _text(value, item_limit)
        if item and item.lower() not in {v.lower() for v in out}:
            out.append(item)
        if len(out) >= max_items:
            break
    return out


def normalize_profile(raw: Dict[str, Any] | None) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    pillars = []
    for p in raw.get("pillars") or []:
        if isinstance(p, str):
            p = {"name": p}
        if not isinstance(p, dict):
            continue
        name = _text(p.get("name"), 80)
        if not name:
            continue
        try:
            weight = max(0, min(100, int(round(float(p.get("weight") or 0)))))
        except (TypeError, ValueError):
            weight = 0
        pillars.append({"name": name, "weight": weight, "description": _text(p.get("description"), 400)})
        if len(pillars) >= 8:
            break
    try:
        ppw = int(raw.get("posts_per_week") or 3)
    except (TypeError, ValueError):
        ppw = 3
    formats = [f for f in _str_list(raw.get("formats_enabled"), item_limit=20, max_items=5) if f in FORMATS]
    custom_dates = []
    for entry in raw.get("custom_dates") or []:
        if isinstance(entry, dict) and _text(entry.get("label"), 80) and _text(entry.get("date"), 10):
            custom_dates.append({"date": _text(entry.get("date"), 10), "label": _text(entry.get("label"), 80)})
        if len(custom_dates) >= 30:
            break
    return {
        "tone_of_voice": _text(raw.get("tone_of_voice"), 1000),
        "personality": _text(raw.get("personality"), 500),
        "audience": _text(raw.get("audience"), 1000),
        "pillars": pillars,
        "keywords_use": _str_list(raw.get("keywords_use"), item_limit=40, max_items=30),
        "keywords_avoid": _str_list(raw.get("keywords_avoid"), item_limit=40, max_items=30),
        "hashtags": _str_list(raw.get("hashtags"), item_limit=40, max_items=30),
        "restrictions": _text(raw.get("restrictions"), 1500),
        "posts_per_week": max(1, min(14, ppw)),
        "formats_enabled": formats or list(DEFAULT_FORMATS),
        "custom_dates": custom_dates,
    }


async def load_profile(client_id: str) -> Dict[str, Any]:
    try:
        rows = await sb_select(PROFILE_TABLE, select="client_id,profile,updated_at",
                               filters={"client_id": f"eq.{client_id}"}, limit=1)
    except Exception as exc:
        print(f"[studio][profile] client_id={client_id} status=unavailable error_type={exc.__class__.__name__}")
        rows = []
    row = rows[0] if rows and str(rows[0].get("client_id")) == client_id else {}
    return {"profile": normalize_profile(row.get("profile")), "updated_at": row.get("updated_at"),
            "saved": bool(row)}


async def save_profile(client_id: str, profile: Dict[str, Any], *, user_id: str) -> Dict[str, Any]:
    normalized = normalize_profile(profile)
    await sb_upsert(PROFILE_TABLE, [{"client_id": client_id, "profile": normalized, "updated_by": user_id}],
                    on_conflict="client_id")
    return {"profile": normalized, "saved": True}


# --------------------------------------------------------------------------
# Quando e em que formato (determinístico)
# --------------------------------------------------------------------------

def parse_month(value: str) -> date:
    try:
        raw = str(value or "").strip()
        parsed = date.fromisoformat(raw + "-01" if len(raw) == 7 else raw)
    except ValueError:
        raise StudioError("MONTH_INVALID", "Use o mês no formato AAAA-MM.") from None
    return parsed.replace(day=1)


def month_end(month: date) -> date:
    nxt = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return nxt - timedelta(days=1)


def _block_start(label: str) -> int:
    match = re.match(r"(\d{2})h", label or "")
    return int(match.group(1)) if match else 18


def rank_weekdays(best: Dict[str, Any]) -> List[Tuple[int, Dict[str, Any] | None]]:
    """Dias da semana do melhor para o pior; sem amostra, ordem padrão de mercado."""
    measured = []
    for row in best.get("by_weekday") or []:
        if row.get("weekday") in WEEKDAYS and (row.get("posts") or 0) >= 2:
            measured.append((WEEKDAYS.index(row["weekday"]), row))
    measured.sort(key=lambda item: (item[1].get("reach_index") or 0, item[1].get("posts") or 0), reverse=True)
    order = [wd for wd, _ in measured] + [wd for wd in DEFAULT_WEEKDAY_ORDER if wd not in {w for w, _ in measured}]
    by_wd = dict(measured)
    return [(wd, by_wd.get(wd)) for wd in order]


def best_block_for(weekday: int, best: Dict[str, Any]) -> Tuple[str, Dict[str, Any] | None]:
    name = WEEKDAYS[weekday]
    for slot in best.get("best_slots") or []:
        if slot.get("weekday") == name:
            return slot.get("hours") or DEFAULT_BLOCK, slot
    hours = [h for h in best.get("by_hours") or [] if (h.get("posts") or 0) >= 2]
    if hours:
        top = max(hours, key=lambda h: (h.get("reach_index") or 0, h.get("posts") or 0))
        return top.get("hours") or DEFAULT_BLOCK, top
    return DEFAULT_BLOCK, None


def _peak_hour_in_block(block: str, best: Dict[str, Any]) -> int:
    start = _block_start(block)
    online = {int(str(h.get("hour", "0"))[:2]): h.get("followers_online") or 0
              for h in (best.get("online_followers") or {}).get("by_hour") or []
              if str(h.get("hour", ""))[:2].isdigit()}
    candidates = [h for h in range(start, min(start + 3, 24)) if h in online]
    if candidates:
        return max(candidates, key=lambda h: online[h])
    return min(start + 1, 23)


def format_rotation(best: Dict[str, Any], enabled: Iterable[str]) -> List[str]:
    """Sequência de formatos ponderada pelo alcance mediano real (50/30/20)."""
    enabled = [f for f in enabled if f in FORMATS] or list(DEFAULT_FORMATS)
    medians = best.get("format_median_reach") or {}
    ranked = sorted(enabled, key=lambda f: medians.get(f, 0), reverse=True)
    pattern = {0: 5, 1: 3, 2: 2}
    seq: List[str] = []
    for idx, fmt in enumerate(ranked[:3]):
        seq.extend([fmt] * pattern.get(idx, 1))
    # Intercala para não ficar "reels, reels, reels, reels, reels" em sequência.
    out: List[str] = []
    buckets = {f: seq.count(f) for f in ranked[:3]}
    while any(buckets.values()):
        for fmt in ranked[:3]:
            if buckets.get(fmt):
                out.append(fmt)
                buckets[fmt] -= 1
    return out or list(DEFAULT_FORMATS)


def plan_slots(
    month: date, best: Dict[str, Any], profile: Dict[str, Any], *,
    today: date, seasonal: List[Dict[str, Any]], busy_days: Iterable[str] = (),
) -> List[Dict[str, Any]]:
    last = month_end(month)
    first_day = max(month, today + timedelta(days=1))
    if first_day > last:
        raise StudioError("MONTH_PAST", "Esse mês já passou; escolha o mês atual ou um próximo.")
    ppw = profile.get("posts_per_week") or 3
    weekdays = rank_weekdays(best)[: min(ppw, 7)]
    chosen_wd = {wd: meta for wd, meta in weekdays}
    busy = set(busy_days)
    days: Dict[str, Dict[str, Any]] = {}
    d = first_day
    while d <= last:
        if d.weekday() in chosen_wd and d.isoformat() not in busy:
            days[d.isoformat()] = {"date": d, "reason": "melhor_dia", "weekday_meta": chosen_wd[d.weekday()]}
        d += timedelta(days=1)
    # Datas comerciais e da marca ganham post no próprio dia (ou no dia útil anterior se já passou).
    for item in seasonal:
        when = date.fromisoformat(item["date"])
        if item["kind"] not in {COMMERCIAL, CUSTOM} or when < first_day or when.isoformat() in busy:
            continue
        days.setdefault(when.isoformat(), {"date": when, "reason": "data_sazonal", "weekday_meta": None})
        days[when.isoformat()]["seasonal"] = item["label"]
    rotation = format_rotation(best, profile.get("formats_enabled") or DEFAULT_FORMATS)
    slots = []
    for idx, key in enumerate(sorted(days)):
        info = days[key]
        block, slot_meta = best_block_for(info["date"].weekday(), best)
        hour = _peak_hour_in_block(block, best)
        local = datetime.combine(info["date"], time(hour, 0), tzinfo=SAO_PAULO)
        slots.append({
            "slot_id": f"s{idx + 1}",
            "date": key,
            "weekday": WEEKDAYS[info["date"].weekday()],
            "time": f"{hour:02d}:00",
            "scheduled_at": local.isoformat(),
            "format": rotation[idx % len(rotation)],
            "seasonal": info.get("seasonal"),
            "basis": {
                "reason": info["reason"],
                "weekday_reach_index": (info.get("weekday_meta") or {}).get("reach_index"),
                "hours": block,
                "slot_reach_index": (slot_meta or {}).get("reach_index"),
                "confidence": (slot_meta or {}).get("confidence") or ("baixa" if not best.get("posts_analyzed") else None),
            },
        })
    return slots


# --------------------------------------------------------------------------
# O quê (IA, com saída validada)
# --------------------------------------------------------------------------

LLM_SCHEMA = {
    "name": "studio_calendar",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "slot_id": {"type": "string"},
                        "pillar": {"type": "string"},
                        "title": {"type": "string"},
                        "hook": {"type": "string"},
                        "caption_draft": {"type": "string"},
                        "rationale": {"type": "string"},
                        "trend_id": {"type": ["string", "null"]},
                    },
                    "required": ["slot_id", "pillar", "title", "hook", "caption_draft", "rationale", "trend_id"],
                },
            }
        },
        "required": ["items"],
    },
}


async def top_posts(client_id: str, *, days: int = 90) -> List[Dict[str, Any]]:
    """Posts que mais alcançaram em relação ao próprio formato (só texto de negócio)."""
    from .posting_times import score_posts

    since = datetime.now(timezone.utc).date() - timedelta(days=days)
    rows = await sb_select(
        "ig_media", select="media_type,media_product_type,timestamp,insights_json,caption",
        filters={"client_id": f"eq.{client_id}", "timestamp": f"gte.{since.isoformat()}"},
        order="timestamp.desc", limit=300,
    )
    out = [{"format": p["format"], "reach_index": round(p["reach_index"], 2), "caption": _text(p.get("caption"), 220)}
           for p in score_posts(rows, start=since, end=date.max)]
    out.sort(key=lambda p: p["reach_index"], reverse=True)
    return out[:MAX_TOP_POSTS]


def build_prompt(
    *, slots: List[Dict[str, Any]], profile: Dict[str, Any], business: Dict[str, Any],
    top: List[Dict[str, Any]], trends: List[Dict[str, Any]], seasonal: List[Dict[str, Any]], month: date,
) -> str:
    payload = {
        "mes": month.strftime("%Y-%m"),
        "perfil_da_marca": {k: profile.get(k) for k in (
            "tone_of_voice", "personality", "audience", "pillars", "keywords_use", "keywords_avoid",
            "hashtags", "restrictions")},
        "contexto_do_negocio": {k: v for k, v in (business or {}).items() if v},
        "posts_que_mais_performaram": top,
        "datas_do_mes": seasonal,
        "assuntos_em_alta_agora": [{"trend_id": t["id"], "assunto": t["topic"], "noticia": t.get("news_title")}
                                   for t in trends[:MAX_TRENDS_IN_PROMPT]],
        "slots": [{k: s[k] for k in ("slot_id", "date", "weekday", "time", "format", "seasonal")} for s in slots],
    }
    return (
        "Monte o calendário editorial de Instagram do mês para a marca abaixo.\n"
        "Preencha UMA pauta para CADA slot (mesmo slot_id). Não mude data, horário nem formato.\n"
        "Regras:\n"
        "- pillar: use exatamente o nome de um pilar do perfil; respeite os pesos ao longo do mês.\n"
        "- title: a pauta em uma frase específica desta marca (nada que sirva para qualquer marca).\n"
        "- hook: a primeira frase/cena que faz parar o scroll, adequada ao formato.\n"
        "- caption_draft: rascunho de legenda no tom de voz da marca, com CTA; use hashtags do perfil se houver.\n"
        "- rationale: 1 frase dizendo por que essa pauta neste dia (pilar, data, aprendizado dos posts que performaram).\n"
        "- Slot com 'seasonal' preenchido: a pauta deve tratar dessa data do jeito da marca.\n"
        "- trend_id: só use um assunto em alta se ele combinar de verdade com a marca; senão null. No máximo 2 no mês.\n"
        "- Nunca use palavras de keywords_avoid nem desrespeite restrictions.\n"
        "- Não invente números, resultados, depoimentos, preços nem promoções que não estejam nos dados.\n"
        "- Português do Brasil.\n\n"
        f"DADOS:\n{json.dumps(payload, ensure_ascii=False)}"
    )


async def call_llm(prompt: str) -> Dict[str, Any]:
    from .ai_summary import _extract_output_text

    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise StudioError("AI_PROVIDER_NOT_CONFIGURED")
    payload = {
        "model": (os.getenv("OPENAI_MODEL") or "gpt-4.1-mini").strip(),
        "instructions": "Você é social media sênior de agência. Escreve pautas específicas da marca e nunca inventa dados.",
        "input": prompt,
        "temperature": 0.5,
        "text": {"format": {"type": "json_schema", "name": LLM_SCHEMA["name"], "schema": LLM_SCHEMA["schema"], "strict": True}},
    }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post("https://api.openai.com/v1/responses",
                                         headers={"Authorization": f"Bearer {api_key}"}, json=payload)
    except httpx.TimeoutException:
        raise StudioError("AI_PROVIDER_TIMEOUT") from None
    if response.status_code >= 400:
        print(f"[studio][llm] status={response.status_code}")
        raise StudioError("AI_PROVIDER_ERROR")
    try:
        return json.loads(_extract_output_text(response.json()))
    except (ValueError, TypeError):
        raise StudioError("AI_INVALID_OUTPUT") from None


def validate_items(
    raw: Dict[str, Any], *, slots: List[Dict[str, Any]], profile: Dict[str, Any], trends: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    by_slot = {s["slot_id"]: s for s in slots}
    pillars = {p["name"].lower(): p["name"] for p in profile.get("pillars") or []}
    trend_by_id = {t["id"]: t for t in trends}
    avoid = [w.lower() for w in profile.get("keywords_avoid") or []]
    used, warnings, out = set(), [], []
    trends_used = 0
    for item in (raw or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        slot = by_slot.get(str(item.get("slot_id")))
        if not slot or slot["slot_id"] in used:
            continue
        title = _text(item.get("title"), 200)
        if not title:
            continue
        used.add(slot["slot_id"])
        pillar = _text(item.get("pillar"), 120)
        if pillars:
            pillar = pillars.get(pillar.lower())
            if pillar is None:
                warnings.append(f"{slot['date']}: pilar fora do perfil foi removido.")
        caption = str(item.get("caption_draft") or "").strip()[:4000]
        hook = _text(item.get("hook"), 400)
        flagged = sorted({w for w in avoid if w and w in f"{title} {hook} {caption}".lower()})
        trend = trend_by_id.get(str(item.get("trend_id") or ""))
        if trend and trends_used >= 2:
            trend = None
        trends_used += 1 if trend else 0
        signals = {"basis": slot["basis"], "seasonal": slot.get("seasonal")}
        if trend:
            signals["trend"] = {"topic": trend["topic"], "source_url": trend["source_url"],
                                "researched_at": trend["researched_at"]}
        if flagged:
            signals["palavras_evitar_encontradas"] = flagged
            warnings.append(f"{slot['date']}: contém palavra a evitar ({', '.join(flagged)}); revisar.")
        out.append({
            "slot": slot, "pillar": pillar, "title": title, "hook": hook or None,
            "caption_draft": caption or None, "rationale": _text(item.get("rationale"), 1200) or None,
            "signals": signals,
        })
    missing = [s["date"] for s in slots if s["slot_id"] not in used]
    if missing:
        warnings.append(f"{len(missing)} dia(s) sem pauta válida da IA: {', '.join(missing)}.")
    return out, warnings


# --------------------------------------------------------------------------
# Orquestração e persistência
# --------------------------------------------------------------------------

async def list_items(client_id: str, month: date) -> List[Dict[str, Any]]:
    return await sb_select(
        ITEMS_TABLE, select="*",
        filters={"client_id": f"eq.{client_id}", "month": f"eq.{month.isoformat()}"},
        order="scheduled_at.asc", limit=200,
    )


async def _recent_generation(client_id: str) -> bool:
    since = (datetime.now(timezone.utc) - timedelta(seconds=GENERATION_COOLDOWN_SECONDS)).isoformat()
    rows = await sb_select(ITEMS_TABLE, select="id",
                           filters={"client_id": f"eq.{client_id}", "origin": "eq.ia", "created_at": f"gte.{since}"},
                           limit=1)
    return bool(rows)


async def generate_month(client_id: str, month_value: str, *, user_id: str, today: date | None = None) -> Dict[str, Any]:
    month = parse_month(month_value)
    today = today or datetime.now(SAO_PAULO).date()
    current = today.replace(day=1)
    horizon = (current + timedelta(days=32 * 3)).replace(day=1)
    if month < current or month > horizon:
        raise StudioError("MONTH_OUT_OF_RANGE", "Gere do mês atual até 3 meses à frente.")
    if await _recent_generation(client_id):
        raise StudioError("AI_GENERATION_COOLDOWN", "Um calendário acabou de ser gerado. Aguarde um instante.")

    profile = (await load_profile(client_id))["profile"]
    end_today = today.isoformat()
    best = await build_posting_times(client_id, start=(today - timedelta(days=179)).isoformat(), end=end_today)
    seasonal = dates_for_month(month, profile.get("custom_dates"))
    existing = await list_items(client_id, month)
    # Itens revisados ou manuais são da equipe: ficam, e o dia deles não recebe outro post.
    kept = [r for r in existing if not (r.get("origin") == "ia" and r.get("status") == "rascunho")]
    busy_days = {datetime.fromisoformat(str(r["scheduled_at"]).replace("Z", "+00:00")).astimezone(SAO_PAULO).date().isoformat()
                 for r in kept if r.get("scheduled_at")}
    slots = plan_slots(month, best, profile, today=today, seasonal=seasonal, busy_days=busy_days)
    if not slots:
        raise StudioError("NO_SLOTS", "Não sobrou dia livre neste mês para novas pautas.")

    business = (await load_business_context(client_id)).get("context") or {}
    top = await top_posts(client_id)
    trends = (await fetch_trends_br()).get("items") or []
    prompt = build_prompt(slots=slots, profile=profile, business=business, top=top,
                          trends=trends, seasonal=seasonal, month=month)
    raw = await call_llm(prompt)
    items, warnings = validate_items(raw, slots=slots, profile=profile, trends=trends)
    if not items:
        raise StudioError("AI_INVALID_OUTPUT", "A IA não devolveu pautas válidas. Tente de novo.")

    # Só agora troca os rascunhos antigos da IA: se a IA falhar, nada se perde.
    await sb_delete(ITEMS_TABLE, filters={"client_id": f"eq.{client_id}", "month": f"eq.{month.isoformat()}",
                                          "origin": "eq.ia", "status": "eq.rascunho"})
    batch_id = str(uuid.uuid4())
    rows = [{
        "client_id": client_id, "month": month.isoformat(), "scheduled_at": it["slot"]["scheduled_at"],
        "channel": "instagram", "format": it["slot"]["format"], "pillar": it["pillar"], "title": it["title"],
        "hook": it["hook"], "caption_draft": it["caption_draft"], "rationale": it["rationale"],
        "signals": it["signals"], "status": "rascunho", "origin": "ia", "batch_id": batch_id,
        "created_by": user_id,
    } for it in items]
    await sb_insert_many(ITEMS_TABLE, rows)

    notes = list(warnings)
    if not best.get("posts_analyzed"):
        notes.append("Sem histórico de posts: dias e horários seguem o padrão de mercado.")
    if not profile.get("pillars"):
        notes.append("Perfil de marca sem pilares: preencha o perfil para pautas mais específicas.")
    if not trends:
        notes.append("Assuntos em alta indisponíveis agora; calendário gerado sem tendências.")
    return {"month": month.isoformat(), "batch_id": batch_id, "created": len(rows),
            "kept": len(kept), "items": await list_items(client_id, month), "observacoes": notes}


EDITABLE = ("scheduled_at", "format", "pillar", "title", "hook", "caption_draft", "rationale", "status", "review_note")


async def update_item(client_id: str, item_id: str, patch: Dict[str, Any], *, user_id: str) -> Dict[str, Any]:
    clean = {k: v for k, v in patch.items() if k in EDITABLE and v is not None}
    if "status" in clean:
        if clean["status"] not in STATUSES:
            raise StudioError("STATUS_INVALID")
        if clean["status"] in {"aprovado", "rejeitado"}:
            clean["reviewed_by"] = user_id
            clean["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    if "format" in clean and clean["format"] not in FORMATS:
        raise StudioError("FORMAT_INVALID")
    if "scheduled_at" in clean:
        when = datetime.fromisoformat(str(clean["scheduled_at"]).replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=SAO_PAULO)
        clean["scheduled_at"] = when.isoformat()
        clean["month"] = when.astimezone(SAO_PAULO).date().replace(day=1).isoformat()
    if not clean:
        raise StudioError("EMPTY_PATCH")
    rows = await sb_update(ITEMS_TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{item_id}"}, patch=clean)
    if not rows:
        raise StudioError("ITEM_NOT_FOUND")
    return rows[0]


async def create_item(client_id: str, data: Dict[str, Any], *, user_id: str) -> Dict[str, Any]:
    when = datetime.fromisoformat(str(data["scheduled_at"]).replace("Z", "+00:00"))
    if when.tzinfo is None:
        when = when.replace(tzinfo=SAO_PAULO)
    if data.get("format") not in FORMATS:
        raise StudioError("FORMAT_INVALID")
    row = {
        "client_id": client_id, "month": when.astimezone(SAO_PAULO).date().replace(day=1).isoformat(),
        "scheduled_at": when.isoformat(), "channel": "instagram", "format": data["format"],
        "pillar": data.get("pillar"), "title": data["title"], "hook": data.get("hook"),
        "caption_draft": data.get("caption_draft"), "rationale": data.get("rationale"),
        "status": "rascunho", "origin": "manual", "created_by": user_id,
    }
    rows = await sb_insert_many(ITEMS_TABLE, [row], returning="representation")
    if not rows:
        raise StudioError("CREATE_FAILED")
    return rows[0] if isinstance(rows, list) else row


async def delete_item(client_id: str, item_id: str) -> None:
    rows = await sb_delete(ITEMS_TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{item_id}"})
    if not rows:
        raise StudioError("ITEM_NOT_FOUND")
