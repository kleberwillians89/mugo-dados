"""Motores de conteúdo do Studio (trazidos do iAgência e ligados aos dados do Dados).

* Redação no modal da pauta: legenda final, variações, ganchos, hashtags,
  roteiro de Reels e revisão — cada um com o pacote de inteligência da marca.
* Head de Estratégia: conversa sobre o mês com o calendário como contexto.
* Brand Manager: sugere o perfil da marca a partir dos dados e do guia em PDF
  da Biblioteca. Nada é salvo sem a pessoa aplicar.

Toda resposta volta com ``based_on`` (o que foi usado) e ``flags`` (clichês ou
palavras proibidas encontradas), para a equipe revisar antes de usar.
"""
from __future__ import annotations

import io
import json
import re
import time
from collections import deque
from typing import Any, Dict, List, Optional

from .studio_calendar import FORMATS, StudioError, list_items, normalize_profile, parse_month
from .studio_dates import dates_for_month
from .studio_intelligence import build_content_intelligence, coverage, to_prompt
from .studio_llm import INT, STR, arr, flag_words, llm_json, obj

ASSIST_ACTIONS = ("legenda", "variacoes", "ganchos", "hashtags", "roteiro_reels", "revisar")
MAX_CHAT_MESSAGES = 12
GUIDE_MAX_BYTES = 12 * 1024 * 1024
GUIDE_MAX_PAGES = 40
GUIDE_MAX_CHARS = 18000

AI_CALLS_PER_MINUTE = 20
_calls: Dict[str, deque] = {}


def throttle(client_id: str) -> None:
    """Teto simples por empresa (memória do processo) para a IA não virar custo descontrolado."""
    now = time.monotonic()
    window = _calls.setdefault(client_id, deque())
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= AI_CALLS_PER_MINUTE:
        raise StudioError("AI_RATE_LIMIT")
    window.append(now)


ROLE = ("Você é social media e redator sênior de agência. Escreve para a marca descrita nos DADOS, "
        "a partir do que já funcionou na conta e do que o cliente aprovou.")

ASSIST_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "legenda": obj({"caption": STR, "cta": STR, "why": STR}),
    "variacoes": obj({"variations": arr(obj({"angle": STR, "caption": STR})), "recommended_index": INT, "why": STR}),
    "ganchos": obj({"hooks": arr(obj({"hook": STR, "angle": STR}))}),
    "hashtags": obj({"hashtags": arr(STR), "why": STR}),
    "roteiro_reels": obj({"duration_seconds": INT, "cover_text": STR, "audio_suggestion": STR,
                          "scenes": arr(obj({"seconds": STR, "visual": STR, "text_on_screen": STR, "voiceover": STR}))}),
    "revisar": obj({"issues": arr(obj({"problem": STR, "fix": STR})), "improved_caption": STR}),
}

ASSIST_TASKS = {
    "legenda": "Escreva a LEGENDA FINAL desta pauta: abertura forte (pode reaproveitar o gancho), corpo curto e CTA claro. "
               "Use hashtags do perfil no fim, se houver. Em 'why', diga em 1 frase qual dado orientou a escolha.",
    "variacoes": "Escreva 3 VARIAÇÕES de legenda com ângulos realmente diferentes (ex.: autoridade, conexão, venda). "
                 "Indique a recomendada (índice 0-2) e por quê, citando o dado que sustenta a escolha.",
    "ganchos": "Escreva 5 GANCHOS (primeira frase ou cena) que façam parar o scroll, adequados ao formato. "
               "Cada um com um ângulo diferente; inspire-se nos posts que mais alcançaram.",
    "hashtags": "Sugira de 8 a 15 HASHTAGS: as do perfil primeiro, depois de nicho e de produto. Sem hashtags genéricas "
                "como #love ou #instagood. Em 'why', explique o critério.",
    "roteiro_reels": "Escreva o ROTEIRO DO REELS (15 a 45 s): cenas com tempo ('0-3s'), o que aparece, texto na tela e "
                     "narração. Primeira cena = gancho. Inclua texto de capa e sugestão de áudio (estilo, não música com direito autoral).",
    "revisar": "REVISE a legenda: aponte até 6 problemas (clichê, falta de CTA, fora do tom, promessa sem dado, palavra proibida, "
               "texto genérico) com a correção, e devolva a legenda melhorada.",
}


def _item_payload(item: Dict[str, Any]) -> Dict[str, Any]:
    fmt = item.get("format") if item.get("format") in FORMATS else "imagem"
    return {"formato": fmt, "pilar": (item.get("pillar") or "")[:120], "pauta": (item.get("title") or "")[:200],
            "gancho": (item.get("hook") or "")[:400], "legenda_atual": (item.get("caption_draft") or "")[:4000],
            "data": (item.get("scheduled_at") or "")[:25]}


def _flags(data: Dict[str, Any], avoid: List[str]) -> List[str]:
    return flag_words(json.dumps(data, ensure_ascii=False), avoid)


async def assist(client_id: str, action: str, item: Dict[str, Any], *, instruction: Optional[str] = None) -> Dict[str, Any]:
    if action not in ASSIST_ACTIONS:
        raise StudioError("ACTION_INVALID")
    if not (item.get("title") or "").strip():
        raise StudioError("ITEM_TITLE_REQUIRED")
    throttle(client_id)
    intel = await build_content_intelligence(client_id)
    prompt = (
        f"TAREFA: {ASSIST_TASKS[action]}\n"
        + (f"PEDIDO DA EQUIPE: {instruction.strip()[:600]}\n" if instruction and instruction.strip() else "")
        + f"\nPAUTA:\n{json.dumps(_item_payload(item), ensure_ascii=False)}\n"
        + f"\nDADOS DA MARCA:\n{to_prompt(intel)}"
    )
    data = await llm_json(instructions=ROLE, prompt=prompt, schema_name=f"studio_{action}",
                          schema=ASSIST_SCHEMAS[action], temperature=0.8 if action in ("variacoes", "ganchos") else 0.6)
    data = _clean_assist(action, data)
    return {"action": action, "result": data, "flags": _flags(data, (intel.get("marca") or {}).get("keywords_avoid") or []),
            "based_on": coverage(intel)}


def _clean_assist(action: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Corta tamanhos e quantidades: a IA não decide o tamanho do que vai para a tela."""
    if action == "variacoes":
        data["variations"] = [v for v in data.get("variations") or [] if (v.get("caption") or "").strip()][:3]
        if not data["variations"]:
            raise StudioError("AI_INVALID_OUTPUT")
        if not 0 <= int(data.get("recommended_index") or 0) < len(data["variations"]):
            data["recommended_index"] = 0
    elif action == "ganchos":
        data["hooks"] = [h for h in data.get("hooks") or [] if (h.get("hook") or "").strip()][:5]
        if not data["hooks"]:
            raise StudioError("AI_INVALID_OUTPUT")
    elif action == "hashtags":
        seen: List[str] = []
        for tag in data.get("hashtags") or []:
            clean = "#" + re.sub(r"[^\wÀ-ÿ]", "", str(tag).lstrip("#"))
            if len(clean) > 2 and clean.lower() not in [s.lower() for s in seen]:
                seen.append(clean)
        data["hashtags"] = seen[:15]
    elif action == "roteiro_reels":
        data["scenes"] = (data.get("scenes") or [])[:12]
        if not data["scenes"]:
            raise StudioError("AI_INVALID_OUTPUT")
        data["duration_seconds"] = max(5, min(90, int(data.get("duration_seconds") or 30)))
    elif action in ("legenda", "revisar"):
        key = "caption" if action == "legenda" else "improved_caption"
        data[key] = str(data.get(key) or "").strip()[:2200]  # limite de legenda do Instagram
        if not data[key]:
            raise StudioError("AI_INVALID_OUTPUT")
        if action == "revisar":
            data["issues"] = (data.get("issues") or [])[:6]
    return data


# --------------------------------------------------------------------------
# Head de Estratégia
# --------------------------------------------------------------------------

CHAT_SCHEMA = obj({"reply": STR, "suggested_actions": arr(STR)})


async def strategy_chat(client_id: str, month: str, messages: List[Dict[str, str]]) -> Dict[str, Any]:
    target = parse_month(month)
    history = [{"role": m.get("role"), "content": str(m.get("content") or "")[:2000]}
               for m in messages[-MAX_CHAT_MESSAGES:] if m.get("role") in ("user", "assistant") and str(m.get("content") or "").strip()]
    if not history or history[-1]["role"] != "user":
        raise StudioError("CHAT_EMPTY")
    throttle(client_id)
    intel = await build_content_intelligence(client_id)
    items = await list_items(client_id, target)
    plan = [{"data": str(i.get("scheduled_at"))[:10], "formato": i.get("format"), "pilar": i.get("pillar"),
             "pauta": i.get("title"), "status": i.get("status")} for i in items]
    seasonal = dates_for_month(target, ((intel.get("marca") or {}).get("custom_dates")))
    prompt = (
        f"MÊS EM PLANEJAMENTO: {target.strftime('%Y-%m')}\n"
        f"CALENDÁRIO ATUAL DO MÊS:\n{json.dumps(plan, ensure_ascii=False)}\n"
        f"DATAS DO MÊS: {json.dumps(seasonal, ensure_ascii=False, default=str)}\n"
        f"DADOS DA MARCA:\n{to_prompt(intel)}\n\n"
        f"CONVERSA (responda à última mensagem):\n{json.dumps(history, ensure_ascii=False)}"
    )
    data = await llm_json(
        instructions=("Você é o Head de Estratégia de conteúdo da agência. Direto, específico e provocativo quando ajudar. "
                      "Use os números e aprendizados dos DADOS para justificar; se um dado faltar, diga qual. "
                      "Responda em Markdown curto (até 12 linhas). Em suggested_actions, até 3 próximos passos objetivos."),
        prompt=prompt, schema_name="studio_strategy_chat", schema=CHAT_SCHEMA, temperature=0.6)
    reply = str(data.get("reply") or "").strip()[:6000]
    if not reply:
        raise StudioError("AI_INVALID_OUTPUT")
    return {"reply": reply, "suggested_actions": [str(a)[:200] for a in (data.get("suggested_actions") or [])[:3]],
            "based_on": coverage(intel)}


# --------------------------------------------------------------------------
# Brand Manager
# --------------------------------------------------------------------------

PROFILE_SCHEMA = obj({
    "tone_of_voice": STR, "personality": STR, "audience": STR,
    "pillars": arr(obj({"name": STR, "weight": INT, "description": STR})),
    "keywords_use": arr(STR), "keywords_avoid": arr(STR), "hashtags": arr(STR), "restrictions": STR,
    "posts_per_week": INT, "formats_enabled": arr({"type": "string", "enum": list(FORMATS)}),
    "notes": arr(STR),
})


def extract_pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        parts = []
        for page in reader.pages[:GUIDE_MAX_PAGES]:
            parts.append(page.extract_text() or "")
            if sum(len(p) for p in parts) > GUIDE_MAX_CHARS:
                break
    except Exception:
        raise StudioError("GUIDE_UNREADABLE") from None
    text = re.sub(r"[ \t]+", " ", "\n".join(parts)).strip()
    if len(text) < 80:
        raise StudioError("GUIDE_UNREADABLE")
    return text[:GUIDE_MAX_CHARS]


async def _guide_text(client_id: str, asset_id: str) -> str:
    from .studio_assets import ASSETS_TABLE, storage_download
    from .ig_supabase import sb_select

    rows = await sb_select(ASSETS_TABLE, select="storage_path,kind,size_bytes,status", limit=1,
                           filters={"client_id": f"eq.{client_id}", "id": f"eq.{asset_id}", "status": "eq.pronto"})
    if not rows or rows[0].get("kind") != "pdf":
        raise StudioError("GUIDE_NOT_FOUND")
    if int(rows[0].get("size_bytes") or 0) > GUIDE_MAX_BYTES:
        raise StudioError("GUIDE_TOO_LARGE")
    return extract_pdf_text(await storage_download(str(rows[0]["storage_path"]), max_bytes=GUIDE_MAX_BYTES))


async def suggest_profile(client_id: str, *, guide_asset_id: Optional[str] = None) -> Dict[str, Any]:
    throttle(client_id)
    intel = await build_content_intelligence(client_id, use_cache=False)
    guide = await _guide_text(client_id, guide_asset_id) if guide_asset_id else ""
    prompt = (
        "Monte o PERFIL DA MARCA para o Studio a partir dos dados abaixo. Mantenha o que o perfil atual já tem de bom; "
        "complete o que falta. Pilares: 3 a 6, pesos somando 100, cada um com descrição de 1 frase. "
        "Formatos: só os que a conta usa ou que fazem sentido para ela. posts_per_week entre 2 e 7. "
        "Em notes, liste de 2 a 5 observações sobre o que nos dados sustentou as escolhas e o que ainda falta.\n\n"
        f"PERFIL ATUAL E DADOS:\n{to_prompt(intel)}\n"
        + (f"\nGUIA DA MARCA (texto extraído do PDF):\n{guide}\n" if guide else "\nSem guia da marca anexado.\n")
    )
    data = await llm_json(instructions="Você é o Brand Manager da agência: transforma dados e o guia da marca em um perfil objetivo e utilizável.",
                          prompt=prompt, schema_name="studio_brand_profile", schema=PROFILE_SCHEMA, temperature=0.4)
    notes = [str(n)[:300] for n in (data.pop("notes", None) or [])[:5]]
    # Datas próprias não fazem parte da sugestão: ficam as que a equipe cadastrou.
    profile = normalize_profile({**data, "custom_dates": (intel.get("marca") or {}).get("custom_dates") or []})
    return {"profile": profile, "notes": notes, "used_guide": bool(guide), "based_on": coverage(intel)}

