"""
Redação (trazida da iAgência) — parte da tela Social Media.

Editor de texto estilo Word por marca: a equipe cria documentos (post, legenda, roteiro, artigo,
e-mail, release, texto livre), formata, e usa a IA da marca para escrever, continuar, reescrever,
encurtar, expandir ou corrigir. A IA escreve com o mesmo cérebro do Calendário, da Matriz e das
Campanhas (studio_intelligence) e com a auditoria anti-vazamento entre marcas (llm_json).

O documento pode virar post no Calendário (rascunho, aprovação de sempre). Repetir o envio não
duplica: o documento guarda a pauta e atualiza o texto dela enquanto ela não foi aprovada.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .brand_guard import check as brand_check
from .ig_supabase import sb_insert, sb_select, sb_update
from .studio_calendar import CHANNELS, FORMATS, StudioError, create_item, delete_item, language_rule, load_profile, update_item
from .studio_engines import throttle
from .studio_intelligence import build_content_intelligence, to_prompt
from .studio_llm import STR, arr, flag_words, llm_json, obj

DOCUMENTS = "studio_documents"
ITEMS = "studio_calendar_items"
KINDS = {"livre": "Texto livre", "post": "Post", "legenda": "Legenda", "roteiro": "Roteiro de vídeo", "artigo": "Artigo / blog",
         "email": "E-mail", "release": "Release", "campanha": "Texto de campanha"}
KIND_GUIDE = {
    "livre": "Texto corrido, no formato que o pedido indicar.",
    "post": "Post de rede social: abertura forte, corpo curto, CTA claro.",
    "legenda": "Legenda de Instagram: primeira linha que segura, parágrafos curtos, CTA e até 5 hashtags no fim.",
    "roteiro": "Roteiro de vídeo curto: cenas com tempo (0-3s), o que aparece, texto na tela e fala; gancho na primeira cena.",
    "artigo": "Artigo de blog: título, introdução, intertítulos e conclusão com CTA; escaneável.",
    "email": "E-mail: assunto (até 60 caracteres), pré-cabeçalho e corpo curto com um CTA.",
    "release": "Release para imprensa: título, lide com o fato principal, citação e informações para a imprensa.",
    "campanha": "Texto-base de campanha: conceito, mensagem principal e variações por canal.",
}
ACTIONS = {
    "escrever": "Escreva o texto pedido do zero.",
    "continuar": "Continue o texto a partir de onde ele parou, no mesmo tom e formato. Devolva só a continuação.",
    "reescrever": "Reescreva o TRECHO com outro ângulo, mantendo a informação. Devolva só o trecho novo.",
    "encurtar": "Deixe o TRECHO mais curto e direto, sem perder a informação. Devolva só o trecho novo.",
    "expandir": "Desenvolva o TRECHO com mais detalhe e exemplos, sem inventar dado. Devolva só o trecho novo.",
    "corrigir": "Corrija ortografia, gramática e pontuação do TRECHO sem mudar o estilo. Devolva só o trecho corrigido.",
    "titulos": "Sugira 5 títulos fortes para o texto.",
}
SELECTION_ACTIONS = ("reescrever", "encurtar", "expandir", "corrigir")
ROLE = ("Você é redator sênior de agência. Escreve para a marca descrita nos DADOS, no tom de voz dela, "
        "a partir do que o cliente aprovou e do que performou. Não invente oferta, preço, número ou prazo.")
MAX_HTML = 300_000
MAX_TEXT = 100_000
LIST_COLUMNS = "id,title,kind,status,calendar_item_id,updated_at,created_at"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


_SCRIPT = re.compile(r"<\s*(script|style|iframe|object|embed)[^>]*>.*?<\s*/\s*\1\s*>", re.I | re.S)
_EVENT_ATTR = re.compile(r"\s+on[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)
_JS_URL = re.compile(r"(href|src)\s*=\s*([\"'])\s*javascript:[^\"']*\2", re.I)


def clean_html(html: Any) -> str:
    """O editor só produz HTML simples; ainda assim, nada executável é guardado."""
    text = str(html or "")[:MAX_HTML]
    text = _SCRIPT.sub("", text)
    text = _EVENT_ATTR.sub("", text)
    return _JS_URL.sub(r'\1="#"', text)


def html_to_text(html: str) -> str:
    text = re.sub(r"<\s*br\s*/?>", "\n", html or "", flags=re.I)
    text = re.sub(r"</\s*(p|h[1-6]|li|blockquote)\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    for a, b in (("&nbsp;", " "), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'"), ("&amp;", "&")):
        text = text.replace(a, b)
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:MAX_TEXT]


# ---------------------------------------------------------------- CRUD

async def list_documents(client_id: str) -> List[Dict[str, Any]]:
    rows = await sb_select(DOCUMENTS, select=f"{LIST_COLUMNS},content_text",
                           filters={"client_id": f"eq.{client_id}", "status": "eq.rascunho"}, order="updated_at.desc", limit=100)
    return [{**{k: v for k, v in r.items() if k != "content_text"}, "excerpt": _clip(r.get("content_text"), 160)} for r in rows]


async def get_document(client_id: str, document_id: str) -> Dict[str, Any]:
    rows = await sb_select(DOCUMENTS, select="*", filters={"client_id": f"eq.{client_id}", "id": f"eq.{document_id}"}, limit=1)
    if not rows:
        raise StudioError("DOCUMENT_NOT_FOUND")
    return rows[0]


async def create_document(client_id: str, data: Dict[str, Any], *, user_id: str) -> Dict[str, Any]:
    kind = data.get("kind") or "livre"
    if kind not in KINDS:
        raise StudioError("DOCUMENT_KIND_INVALID")
    html = clean_html(data.get("content_html"))
    row = await sb_insert(DOCUMENTS, {"client_id": client_id, "title": _clip(data.get("title"), 200) or "Sem título", "kind": kind,
                                      "content_html": html, "content_text": html_to_text(html), "created_by": user_id, "updated_by": user_id})
    if not row:
        raise StudioError("DOCUMENT_SAVE_FAILED")
    return row


async def update_document(client_id: str, document_id: str, data: Dict[str, Any], *, user_id: str) -> Dict[str, Any]:
    patch: Dict[str, Any] = {}
    if data.get("title") is not None:
        patch["title"] = _clip(data["title"], 200) or "Sem título"
    if data.get("kind") is not None:
        if data["kind"] not in KINDS:
            raise StudioError("DOCUMENT_KIND_INVALID")
        patch["kind"] = data["kind"]
    if data.get("content_html") is not None:
        html = clean_html(data["content_html"])
        patch.update({"content_html": html, "content_text": html_to_text(html)})
    if data.get("status") is not None:
        if data["status"] not in ("rascunho", "arquivado"):
            raise StudioError("STATUS_INVALID")
        patch["status"] = data["status"]
    if not patch:
        raise StudioError("EMPTY_PATCH")
    rows = await sb_update(DOCUMENTS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{document_id}"},
                           patch={**patch, "updated_by": user_id, "updated_at": _now()})
    if not rows:
        raise StudioError("DOCUMENT_NOT_FOUND")
    return rows[0]


# ---------------------------------------------------------------- IA da marca

def build_ai_prompt(action: str, *, kind: str, title: str, instruction: str, selection: str, document_text: str,
                    intel: Dict[str, Any], profile: Dict[str, Any]) -> str:
    parts = [f"TAREFA: {ACTIONS[action]}", f"TIPO DE TEXTO: {KINDS[kind]}. {KIND_GUIDE[kind]}"]
    if title:
        parts.append(f"TÍTULO DO DOCUMENTO: {title}")
    if instruction:
        parts.append(f"PEDIDO DA EQUIPE: {instruction}")
    if action in SELECTION_ACTIONS:
        parts.append(f"TRECHO:\n{selection}")
        if document_text:
            parts.append(f"CONTEXTO (texto completo, só para referência):\n{document_text[-4000:]}")
    elif document_text and action in ("continuar", "titulos"):
        parts.append(f"TEXTO ATÉ AGORA:\n{document_text[-8000:]}")
    parts.append("Sem travessão. Parágrafos separados por linha em branco. Sem markdown (nada de **, #).")
    parts.append(f"DADOS DA MARCA:\n{to_prompt(intel)}")
    parts.append(language_rule(profile))
    return "\n\n".join(parts)


def _clean_ai_text(text: Any, limit: int = 20000) -> str:
    out = re.sub(r"\s*[—–]\s*", ", ", str(text or ""))
    out = re.sub(r"\*\*(.+?)\*\*", r"\1", out)
    out = re.sub(r"^#{1,6}\s*", "", out, flags=re.M)
    return out.strip()[:limit]


async def ai_write(client_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    action = data.get("action") or "escrever"
    if action not in ACTIONS:
        raise StudioError("ACTION_INVALID")
    kind = data.get("kind") or "livre"
    if kind not in KINDS:
        raise StudioError("DOCUMENT_KIND_INVALID")
    instruction = _clip(data.get("instruction"), 1500)
    selection = _clip(data.get("selection"), 12000)
    document_text = _clip(data.get("document_text"), MAX_TEXT)
    if action in SELECTION_ACTIONS and not selection:
        raise StudioError("DOCUMENT_SELECTION_REQUIRED")
    if action == "escrever" and not instruction and not _clip(data.get("title"), 200):
        raise StudioError("DOCUMENT_INSTRUCTION_REQUIRED")
    if action in ("continuar", "titulos") and not document_text:
        raise StudioError("DOCUMENT_EMPTY")
    throttle(client_id)
    profile = (await load_profile(client_id))["profile"]
    intel = await build_content_intelligence(client_id)
    prompt = build_ai_prompt(action, kind=kind, title=_clip(data.get("title"), 200), instruction=instruction,
                             selection=selection, document_text=document_text, intel=intel, profile=profile)
    if action == "titulos":
        raw = await llm_json(client_id=client_id, instructions=ROLE, prompt=prompt, schema_name="studio_doc_titles",
                             schema=obj({"titulos": arr(STR)}), temperature=0.8)
        titles = [_clean_ai_text(t, 200) for t in raw.get("titulos") or [] if str(t or "").strip()][:5]
        if not titles:
            raise StudioError("AI_INVALID_OUTPUT")
        return {"action": action, "titles": titles, "text": "", "flags": [], "guard": []}
    raw = await llm_json(client_id=client_id, instructions=ROLE, prompt=prompt, schema_name=f"studio_doc_{action}",
                         schema=obj({"texto": STR}), temperature=0.3 if action == "corrigir" else 0.7, timeout=120)
    text = _clean_ai_text(raw.get("texto"))
    if not text:
        raise StudioError("AI_INVALID_OUTPUT")
    avoid = list(profile.get("keywords_avoid") or [])
    context = json.dumps({"pedido": instruction, "documento": document_text[:6000], "marca": profile, "negocio": intel.get("negocio"),
                          "campanhas_ativas": intel.get("campanhas_ativas")}, ensure_ascii=False, default=str)
    guard = [g for g in brand_check(text, avoid=avoid, context=context) if g.get("type") != "palavra_proibida"]
    return {"action": action, "text": text, "flags": flag_words(text, avoid), "guard": guard[:6], "titles": []}


# ---------------------------------------------------------------- Calendário

async def to_calendar(client_id: str, document_id: str, data: Dict[str, Any], *, user_id: str) -> Dict[str, Any]:
    """O documento vira post em rascunho no Calendário. Repetir não duplica: atualiza o texto da pauta
    enquanto ela não foi aprovada; depois disso, avisa que já está lá."""
    doc = await get_document(client_id, document_id)
    text = (doc.get("content_text") or "").strip()
    if not text:
        raise StudioError("DOCUMENT_EMPTY")
    caption = text[:4000]
    item_id = doc.get("calendar_item_id")
    if item_id:
        rows = await sb_select(ITEMS, select="id,status", filters={"client_id": f"eq.{client_id}", "id": f"eq.{item_id}"}, limit=1)
        if rows:
            if rows[0].get("status") in ("rascunho", "em_revisao", "rejeitado"):
                item = await update_item(client_id, item_id, {"title": doc["title"][:200], "caption_draft": caption}, user_id=user_id)
                return {"calendar_item_id": item_id, "created": False, "updated": True, "item": item}
            return {"calendar_item_id": item_id, "created": False, "updated": False}
    channel = data.get("channel") or "instagram"
    fmt = data.get("format") or "imagem"
    if channel not in CHANNELS:
        raise StudioError("CHANNEL_INVALID")
    if fmt not in FORMATS:
        raise StudioError("FORMAT_INVALID")
    scheduled_at = str(data.get("scheduled_at") or "").strip()
    if not scheduled_at:
        raise StudioError("DOCUMENT_DATE_REQUIRED")
    item = await create_item(client_id, {"scheduled_at": scheduled_at, "channel": channel, "format": fmt, "title": doc["title"][:200],
                                         "caption_draft": caption, "rationale": f"Texto da Redação: {doc['title']}"[:1200]},
                             user_id=user_id)
    if not item or not item.get("id"):
        raise StudioError("CREATE_FAILED")
    claimed = await sb_update(DOCUMENTS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{document_id}", "calendar_item_id": "is.null"},
                              patch={"calendar_item_id": item["id"], "updated_at": _now()})
    if not claimed:
        # Dois cliques ao mesmo tempo: o outro envio já ligou uma pauta a este documento. Desfaz a nossa.
        await delete_item(client_id, item["id"])
        current = await get_document(client_id, document_id)
        return {"calendar_item_id": current.get("calendar_item_id"), "created": False, "updated": False}
    return {"calendar_item_id": item["id"], "created": True, "updated": False, "item": item}
