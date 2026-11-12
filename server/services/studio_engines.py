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

import json
import re
import time
from collections import deque
from typing import Any, Dict, List, Optional

from .studio_calendar import FORMATS, StudioError, language_rule, list_items, normalize_profile, parse_month
from .studio_dates import dates_for_month
from .studio_intelligence import LIBRARY_RULE, PLANS_RULE, build_content_intelligence, coverage, passages_for, to_prompt
from .studio_llm import INT, STR, arr, flag_words, llm_json, obj

ASSIST_ACTIONS = ("legenda", "variacoes", "ganchos", "hashtags", "roteiro_reels", "revisar")
MAX_CHAT_MESSAGES = 12

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


async def _post_references(client_id: str, item_id: Optional[str]) -> List[Dict[str, Any]]:
    if not item_id:
        return []
    from .studio_references import list_references
    try:
        rows = await list_references(client_id, item_id)
    except Exception:  # noqa: BLE001 — sem a tabela ainda: segue sem referência
        return []
    return [{"link": r["url"], "o_que_gostou": (r.get("note") or None)} for r in rows[:10]]


async def assist(client_id: str, action: str, item: Dict[str, Any], *, instruction: Optional[str] = None,
                 item_id: Optional[str] = None) -> Dict[str, Any]:
    if action not in ASSIST_ACTIONS:
        raise StudioError("ACTION_INVALID")
    if not (item.get("title") or "").strip():
        raise StudioError("ITEM_TITLE_REQUIRED")
    throttle(client_id)
    intel = await build_content_intelligence(client_id)
    refs = await _post_references(client_id, item_id)
    # Briefing da pauta (iAgência: "BRIEFING DO JOB (PRIORIDADE MÁXIMA)"): legenda, ganchos e roteiro seguem ele.
    briefing = ""
    if item_id:
        try:
            briefing = briefing_block(((await _load_item(client_id, item_id)).get("signals") or {}).get("briefing"))
        except Exception:  # noqa: BLE001 — sem a pauta salva, segue sem briefing
            briefing = ""
    prompt = (
        briefing
        + f"TAREFA: {ASSIST_TASKS[action]}\n"
        + (f"PEDIDO DA EQUIPE: {instruction.strip()[:600]}\n" if instruction and instruction.strip() else "")
        + f"\nPAUTA:\n{json.dumps(_item_payload(item), ensure_ascii=False)}\n"
        + (f"\nREFERÊNCIAS DESTE POST (o cliente/equipe quer nesse estilo; siga formato, estética e tom, sem copiar):\n"
           f"{json.dumps(refs, ensure_ascii=False)}\n" if refs else "")
        + f"\nDADOS DA MARCA:\n{to_prompt(intel)}\n\n{language_rule(intel.get('marca'))}"
    )
    data = await llm_json(client_id=client_id, instructions=ROLE, prompt=prompt, schema_name=f"studio_{action}",
                          schema=ASSIST_SCHEMAS[action], temperature=0.8 if action in ("variacoes", "ganchos") else 0.6)
    data = _clean_assist(action, data)
    from .brand_guard import check as brand_check, flatten
    avoid = (intel.get("marca") or {}).get("keywords_avoid") or []
    context = json.dumps({"pauta": _item_payload(item), "marca": intel.get("marca"), "negocio": intel.get("negocio"),
                          "campanhas_ativas": intel.get("campanhas_ativas")}, ensure_ascii=False, default=str)
    return {"action": action, "result": data, "flags": _flags(data, avoid),
            "guard": [i for i in brand_check(flatten(data), context=context) if i["type"] != "palavra_proibida"],
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
    data = await llm_json(client_id=client_id, 
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


async def suggest_profile(client_id: str) -> Dict[str, Any]:
    """Perfil com IA avançada (12 meses de posts, imagens, validações do cliente, Mídia On e vendas)."""
    from .studio_brand_brain import suggest
    throttle(client_id)
    return await suggest(client_id)



# ---------------------------------------------------------------- briefing da peça (trazido do iAgência)
# No iAgência o Atendimento transforma o pedido em "briefing técnico" (objetivo, mensagem-chave, tom, resumo,
# público, entregáveis, requisitos técnicos), com direcionamento opcional (objetivo, público, CTA, ousadia 1 a 5,
# referências) e esse briefing vira PRIORIDADE MÁXIMA quando a IA escreve a peça. Aqui ele mora na pauta:
# signals.briefing (texto curto) + script e visual_idea (roteiro e direção da arte, migração 000090).

BOLDNESS = {1: "Conservador", 2: "Sério", 3: "Equilibrado", 4: "Arrojado", 5: "Disruptivo"}
BRIEFING_SCHEMA = obj({
    "summary": STR, "objective": STR, "key_message": STR, "tone": STR, "target_audience": STR,
    "angle": {"type": "string", "enum": None},  # preenchido abaixo com os ângulos do rodízio
    "deliverables": arr(STR), "tech_requirements": arr(STR), "script": STR, "visual_idea": STR,
})
BRIEFING_FIELDS = ("summary", "objective", "key_message", "tone", "target_audience", "angle", "deliverables", "tech_requirements")


def _briefing_schema() -> Dict[str, Any]:
    from .content_variety import ANGLES
    schema = json.loads(json.dumps(BRIEFING_SCHEMA))
    schema["properties"]["angle"]["enum"] = list(ANGLES)
    return schema


def clean_briefing(data: Dict[str, Any]) -> Dict[str, Any]:
    """Tamanhos fixos: briefing é para ser lido em 30 segundos por quem produz."""
    from .content_variety import ANGLES
    text = lambda v, n: re.sub(r"\s+", " ", str(v or "")).strip()[:n]  # noqa: E731
    items = lambda v, n: [text(x, 160) for x in (v or []) if text(x, 160)][:n]  # noqa: E731
    out = {"summary": text(data.get("summary"), 500), "objective": text(data.get("objective"), 300),
           "key_message": text(data.get("key_message"), 300), "tone": text(data.get("tone"), 200),
           "target_audience": text(data.get("target_audience"), 300),
           "angle": data.get("angle") if data.get("angle") in ANGLES else "",
           "deliverables": items(data.get("deliverables"), 6), "tech_requirements": items(data.get("tech_requirements"), 6)}
    return {k: v for k, v in out.items() if v}


def briefing_block(briefing: Optional[Dict[str, Any]]) -> str:
    """Bloco de prioridade máxima para os outros motores (legenda, variações, ganchos, roteiro, revisar)."""
    b = briefing or {}
    labels = (("objective", "Objetivo"), ("key_message", "Mensagem-chave"), ("tone", "Tom"), ("target_audience", "Público"),
              ("summary", "Resumo"), ("angle", "Ângulo"))
    lines = [f"{label}: {b[key]}" for key, label in labels if b.get(key)]
    if b.get("tech_requirements"):
        lines.append("Requisitos técnicos: " + "; ".join(b["tech_requirements"]))
    return ("=== BRIEFING DA PEÇA (PRIORIDADE MÁXIMA) ===\n" + "\n".join(lines) + "\n=============================\n") if lines else ""


async def _load_item(client_id: str, item_id: str) -> Dict[str, Any]:
    from .ig_supabase import sb_select
    rows = await sb_select("studio_calendar_items", select="*", filters={"client_id": f"eq.{client_id}", "id": f"eq.{item_id}"}, limit=1)
    if not rows:
        raise StudioError("ITEM_NOT_FOUND")
    return rows[0]


async def generate_briefing(client_id: str, item_id: str, direction: Optional[Dict[str, Any]] = None, *,
                            throttle_calls: bool = True) -> Dict[str, Any]:
    """A IA monta o briefing da pauta (como o Atendimento do iAgência) e grava na pauta.
    ``throttle_calls=False``: a esteira de agentes controla o ritmo dela."""
    from .ig_supabase import sb_update
    from .studio_calendar import SCRIPT_HINTS
    item = await _load_item(client_id, item_id)
    if throttle_calls:
        throttle(client_id)
    d = {k: str(v).strip()[:600] for k, v in (direction or {}).items() if isinstance(v, (str, int)) and str(v).strip()}
    boldness = BOLDNESS.get(int(d.get("boldness") or 3), "Equilibrado") if str(d.get("boldness") or "3").isdigit() else "Equilibrado"
    intel = await build_content_intelligence(client_id)
    refs = await _post_references(client_id, item_id)
    passages = await passages_for(client_id, str(item.get("title") or ""), str(item.get("hook") or ""), str(item.get("pillar") or ""))
    fmt = item.get("format") if item.get("format") in FORMATS else "imagem"
    prompt = (
        "Monte o BRIEFING TÉCNICO desta pauta para quem vai produzir a peça (designer, editor de vídeo, redator).\n"
        f"DIRETRIZES DA EQUIPE (use quando preenchidas):\n- Objetivo: {d.get('objective') or 'definir a partir da pauta'}\n"
        f"- Público: {d.get('target_audience') or 'o público do perfil da marca'}\n- CTA: {d.get('cta') or 'definir'}\n"
        f"- Ousadia: {boldness}\n- Referências: {d.get('references') or 'nenhuma'}\n- Pedido: {d.get('request') or 'nenhum'}\n"
        f"\nPAUTA:\n{json.dumps(_item_payload(item), ensure_ascii=False)}\n"
        + (f"\nREFERÊNCIAS DESTE POST (o cliente/equipe quer nesse estilo):\n{json.dumps(refs, ensure_ascii=False)}\n" if refs else "")
        + "\nCAMPOS (curtos e concretos, nada genérico):\n"
          "- summary: o que é a peça, em até 2 frases.\n- objective: o que ela precisa fazer, 1 frase.\n"
          "- key_message: a única ideia que o público deve guardar, 1 frase.\n- tone: o tom, derivado do perfil da marca, em poucas palavras.\n"
          "- target_audience: para quem é, 1 frase.\n- angle: o ângulo da pauta.\n"
          "- deliverables: o que precisa ser entregue (ex.: 'Reels 9:16 de 20 a 30 s', 'capa', 'legenda').\n"
          "- tech_requirements: especificações (proporção, duração, número de slides, legendas na tela, áudio).\n"
          f"- script: {SCRIPT_HINTS.get(fmt, SCRIPT_HINTS['imagem'])} No máximo 6 itens.\n"
          "- visual_idea: direção da arte em 2 a 4 linhas (composição, enquadramento, luz, cores da marca, texto na arte).\n"
          f"{LIBRARY_RULE} Em deliverables, liste os arquivos da Biblioteca a usar.\n{PLANS_RULE}\n"
        + (f"TRECHOS DOS DOCUMENTOS DA MARCA SOBRE ESTE TEMA (fatos a usar, nunca contrariar):\n{passages}\n" if passages else "")
        + "Sem travessão. Não invente oferta, preço, número ou prazo que não esteja nos DADOS.\n"
        + f"\nDADOS DA MARCA:\n{to_prompt(intel)}\n\n{language_rule(intel.get('marca'))}"
    )
    data = await llm_json(client_id=client_id, instructions=ROLE, prompt=prompt, schema_name="studio_briefing",
                          schema=_briefing_schema(), temperature=0.4)
    briefing = clean_briefing(data)
    if not briefing.get("objective") and not briefing.get("key_message"):
        raise StudioError("AI_INVALID_OUTPUT")
    signals = {**(item.get("signals") or {}), "briefing": briefing}
    patch: Dict[str, Any] = {"signals": signals}
    script, visual = str(data.get("script") or "").strip()[:4000], str(data.get("visual_idea") or "").strip()[:2000]
    if script:
        patch["script"] = script
    if visual:
        patch["visual_idea"] = visual
    filters = {"client_id": f"eq.{client_id}", "id": f"eq.{item_id}"}
    try:
        rows = await sb_update("studio_calendar_items", filters=filters, patch=patch)
    except Exception as error:  # banco sem a migração 000090: grava só o briefing curto
        if not re.search(r"script|visual_idea", str(error)):
            raise
        rows = await sb_update("studio_calendar_items", filters=filters, patch={"signals": signals})
    return {"item": rows[0] if rows else {**item, **patch}, "based_on": coverage(intel)}
