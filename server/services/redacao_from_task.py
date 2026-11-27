"""Kanban → Redação e Redação → E-mail Marketing, sempre ligados à tarefa (task_work_links).

- ``document_from_task``: documento na Redação a partir do briefing da tarefa (IA da marca escreve, ou em branco
  com o briefing anotado). Já existe um para a tarefa (e entregável)? Devolve para retomar, sem criar outro.
- ``document_to_email``: o texto do documento vira rascunho no E-mail Marketing (sem copiar e colar). Se o documento
  veio de uma tarefa, o e-mail também fica ligado a ela.
- ``link_to_task``: grava o que foi criado em outro módulo (matriz do Social Media, post do Calendário) na tarefa.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_select
from .studio_calendar import StudioError
from .task_context import (LINKS, MODULES, claim_work, complete_work, fail_work,
                           record_link, task_context, work_operation_key)

KIND_BY_WORD = (("roteiro", "roteiro"), ("legenda", "legenda"), ("release", "release"), ("artigo", "artigo"),
                ("blog", "artigo"), ("e-mail", "email"), ("email", "email"), ("post", "post"), ("campanha", "campanha"))


def kind_for(deliverable: str) -> str:
    text = deliverable.lower()
    return next((kind for word, kind in KIND_BY_WORD if word in text), "livre")


def brief_instruction(ctx: Dict[str, Any], deliverable: str) -> str:
    c = ctx.get("context") or {}
    parts = [f"Entregável: {deliverable}" if deliverable else "",
             *(f"{label}: {c[key]}" for key, label in (("summary", "Resumo"), ("objective", "Objetivo"), ("key_message", "Mensagem principal"),
                                                      ("offer", "Oferta"), ("audience", "Público"), ("deadline", "Prazo"),
                                                      ("your_part", "Sua parte")) if c.get(key)),
             ("Evitar: " + "; ".join(c.get("avoid") or [])) if c.get("avoid") else ""]
    return "\n".join(p for p in parts if p)[:1500]


def _html(text: str) -> str:
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    return "".join(f"<p>{esc(block.strip()).replace(chr(10), '<br>')}</p>" for block in re.split(r"\n{2,}", text) if block.strip())


async def _linked(client_id: str, task_id: str, module: str, deliverable: str) -> List[Dict[str, Any]]:
    rows = await sb_select(LINKS, select="record_id,deliverable,created_at", order="created_at.desc", limit=20,
                           filters={"client_id": f"eq.{client_id}", "task_id": f"eq.{task_id}", "module": f"eq.{module}"})
    return [r for r in rows if not deliverable or str(r.get("deliverable") or "") == deliverable]


async def document_from_task(client_id: str, task_id: str, scope: Dict[str, Any], *, user_id: str, mode: str = "ia",
                             deliverable: str = "", new_version: bool = False) -> Dict[str, Any]:
    from .studio_documents import ai_write, create_document, get_document, update_document
    if mode not in ("ia", "branco"):
        raise StudioError("MODE_INVALID", "Escolha escrever com a IA ou começar em branco.")
    ctx = await task_context(client_id, task_id, scope, module="redacao")
    deliverable = str(deliverable or ctx.get("suggested_deliverable") or "").strip()[:160]
    if not new_version:
        for link in await _safe_linked(client_id, ctx["task"]["id"], deliverable):
            try:
                doc = await get_document(client_id, str(link["record_id"]))
            except StudioError:
                continue
            if doc.get("status") != "arquivado":
                return {"created": None, "existing": [{"id": doc["id"], "title": doc.get("title"), "deliverable": link.get("deliverable")}]}
    version = None
    if new_version:
        import uuid
        version = str(uuid.uuid4())
    claim = await claim_work(
        client_id, ctx["task"]["id"], module="redacao",
        operation_key=work_operation_key("redacao", deliverable, version=version),
        deliverable=deliverable, brief_id=ctx.get("brief_id"), user_id=user_id,
    )
    if claim.get("link_status") == "linked":
        for link in await _safe_linked(client_id, ctx["task"]["id"], deliverable):
            try:
                doc = await get_document(client_id, str(link["record_id"]))
            except StudioError:
                continue
            return {"created": None, "existing": [{"id": doc["id"], "title": doc.get("title"), "deliverable": link.get("deliverable")}]}
    if not claim.get("acquired"):
        raise StudioError("WORK_IN_PROGRESS", "Este documento já está sendo criado. Aguarde e atualize a tela.")
    title = (ctx["task"]["title"] + (f" · {deliverable}" if deliverable else ""))[:200]
    kind = kind_for(deliverable or str((ctx.get("context") or {}).get("title") or ""))
    instruction = brief_instruction(ctx, deliverable)
    try:
        doc = await create_document(client_id, {"title": title, "kind": kind}, user_id=user_id)
        if mode == "ia":
            written = await ai_write(client_id, {"action": "escrever", "kind": kind, "title": title, "instruction": instruction})
            text = written.get("text") or ""
        else:
            text = "Briefing da tarefa (apague quando escrever):\n\n" + instruction
        doc = await update_document(client_id, doc["id"], {"content_html": _html(text)}, user_id=user_id)
    except Exception:
        await fail_work(claim)
        raise
    await complete_work(claim, str(doc["id"]))
    return {"created": {"id": doc["id"], "title": doc.get("title"), "kind": doc.get("kind")}, "existing": []}


async def _safe_linked(client_id: str, task_id: str, deliverable: str) -> List[Dict[str, Any]]:
    try:
        return await _linked(client_id, task_id, "redacao", deliverable)
    except Exception:  # noqa: BLE001 — sem a migração dos vínculos, cria normalmente
        return []


async def tasks_of_document(client_id: str, document_id: str) -> List[str]:
    try:
        rows = await sb_select(LINKS, select="task_id", limit=10,
                               filters={"client_id": f"eq.{client_id}", "module": "eq.redacao", "record_id": f"eq.{document_id}"})
    except Exception:  # noqa: BLE001
        return []
    return list(dict.fromkeys(str(r["task_id"]) for r in rows if r.get("task_id")))


async def document_to_email(client_id: str, document_id: str, *, user_id: str) -> Dict[str, Any]:
    """O texto do documento vira rascunho no E-mail Marketing: título, parágrafos e botão da loja."""
    from .email_marketing import save_campaign
    from .mugo_ia_actions import email_body
    from .studio_documents import get_document
    doc = await get_document(client_id, document_id)
    text = str(doc.get("content_text") or "").strip()
    if not text:
        raise StudioError("DOCUMENT_EMPTY", "Escreva o texto antes de enviar para o E-mail Marketing.")
    title = str(doc.get("title") or "Texto da Redação")[:120]
    body = email_body({"titulo": title, "assunto": title, "email_titulo": title, "email_texto": text, "botao": "Ver na loja"})
    campaign = await save_campaign(client_id, body, user_id=user_id)
    for task_id in await tasks_of_document(client_id, document_id):
        await record_link(client_id, task_id, module="email_marketing", record_id=str(campaign["id"]),
                          deliverable=f"Da Redação: {title}"[:160], user_id=user_id)
    return {"campaign": {"id": campaign["id"], "name": campaign.get("name"), "status": campaign.get("status")}}


async def link_to_task(client_id: str, task_id: str, scope: Dict[str, Any], *, module: str, record_id: str,
                       deliverable: str = "", user_id: Optional[str] = None) -> Dict[str, Any]:
    if module not in MODULES or not re.fullmatch(r"[A-Za-z0-9-]{1,80}", record_id or ""):
        raise StudioError("MODULE_INVALID", "Vínculo inválido.")
    ctx = await task_context(client_id, task_id, scope, module=module)
    await record_link(client_id, ctx["task"]["id"], module=module, record_id=record_id, deliverable=deliverable,
                      brief_id=ctx.get("brief_id"), user_id=user_id)
    return {"ok": True}
