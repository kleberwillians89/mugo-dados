"""Mugô IA que executa: o botão "Criar" transforma a proposta da IA em RASCUNHO dentro da ferramenta certa.

- E-mail marketing → campanha em rascunho no E-mail Marketing (assunto, pré-header e blocos no layout da marca).
- Campanha na Meta → rascunho na Mídia On (o gerador de anúncios da Mídia On monta texto, público e verba).
- Briefing → briefing salvo (o gerador de briefing lê a marca e organiza o pedido).
- Modelo de WhatsApp → enviado para APROVAÇÃO da Meta (mesmo caminho da tela Modelos). Não manda mensagem a ninguém:
  o disparo para a base continua sendo feito pela equipe em Disparos em massa, com o modelo aprovado.

Uma resposta pode trazer várias peças (o pacote da campanha); cada uma tem o seu botão Criar.
Nunca envia e-mail, publica anúncio nem dispara mensagem: isso continua sendo um clique da equipe dentro da ferramenta.
A proposta vem da mensagem salva da própria pessoa nesta empresa (não do corpo da requisição): ninguém executa
uma proposta que a IA não fez. Cada proposta vira no máximo um rascunho (status "criado" na mensagem).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from .ig_supabase import sb_select, sb_update
from .studio_calendar import StudioError

MESSAGES = "brand_agent_messages"
ROUTES = {"email": "email_marketing", "campanha_meta": "media", "briefing": "briefing", "whatsapp_modelo": "whatsapp"}
LABELS = {"email": "E-mail Marketing", "campanha_meta": "Mídia On", "briefing": "Briefing",
          "whatsapp_modelo": "WhatsApp · Modelos (aguardando aprovação da Meta)"}
OBJECTIVE_ALIASES = {"venda": "vendas", "vendas": "vendas", "conversao": "vendas", "lead": "leads", "leads": "leads",
                     "cadastro": "leads", "trafego": "trafego", "tráfego": "trafego", "alcance": "alcance",
                     "engajamento": "engajamento", "remarketing": "remarketing", "retencao": "retencao",
                     "whatsapp": "whatsapp", "mensagens": "whatsapp"}


def email_body(action: Dict[str, Any]) -> Dict[str, Any]:
    """Proposta de e-mail → campanha do E-mail Marketing (blocos do editor). Puro, para teste."""
    blocks = [{"type": "logo", "align": "center"}]
    if action.get("email_titulo"):
        blocks.append({"type": "titulo", "text": action["email_titulo"]})
    for paragraph in [p.strip() for p in str(action.get("email_texto") or "").split("\n\n") if p.strip()][:12]:
        blocks.append({"type": "texto", "text": paragraph})
    blocks.append({"type": "botao", "label": action.get("botao") or "Ver na loja", "href": "{{link_loja}}", "align": "center"})
    return {"name": action.get("titulo") or "Campanha da Mugô IA", "subject": action.get("assunto") or "",
            "preheader": action.get("preheader") or "", "design": {"blocks": blocks}}


async def _message(client_id: str, user_id: str, message_id: str) -> Dict[str, Any]:
    rows = await sb_select(MESSAGES, select="id,role,meta", limit=1, filters={
        "id": f"eq.{message_id}", "client_id": f"eq.{client_id}", "user_id": f"eq.{user_id}", "meta->>channel": "eq.mugo_ia"})
    if not rows or rows[0].get("role") != "assistant":
        raise StudioError("MUGO_IA_ACTION_NOT_FOUND", "Proposta não encontrada.")
    return rows[0]


async def _create(client_id: str, action: Dict[str, Any], *, user_id: str, author: str, team: bool) -> Dict[str, Any]:
    kind = action["tipo"]
    if kind == "email":
        from .email_marketing import save_campaign
        created = await save_campaign(client_id, email_body(action), user_id=user_id)
        return {"id": created.get("id"), "name": created.get("name")}
    if kind == "campanha_meta":
        from .meta_ad_publisher import generate_draft
        objective = OBJECTIVE_ALIASES.get(str(action.get("objetivo") or "").lower(), "vendas")
        days = int(action.get("dias") or 14)
        budget = float(action.get("verba_diaria") or 0)
        month = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m")
        draft = await generate_draft(client_id, user_id=user_id, month=month, days_left=days, objective=objective, campaign={
            "campaign": action.get("titulo"), "action": action.get("pedido"), "why": "Pedido feito na Mugô IA",
            "planned_budget": round(budget * days, 2) if budget else 0})
        return {"id": draft.get("id"), "name": (draft.get("payload") or {}).get("name") or action.get("titulo")}
    if kind == "briefing":
        from .studio_briefs import create_brief
        brief = await create_brief(client_id, request=f"{action.get('titulo')}\n\n{action.get('pedido')}", links=[],
                                   user_id=user_id, author=author, team=team)
        return {"id": brief.get("id"), "name": ((brief.get("brief") or {}).get("title")) or action.get("titulo")}
    if kind == "whatsapp_modelo":
        return await _submit_template(client_id, action)
    raise StudioError("MUGO_IA_ACTION_INVALID", "Essa proposta não pode ser criada.")


async def _submit_template(client_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """Mesmo roteamento da tela Modelos: número próprio na Meta, ponte do CRM da marca ou CRM Mugozap."""
    from . import brand_whatsapp_templates, crm_whatsapp_templates
    from .whatsapp_native import WhatsAppNativeError, active_number_ids, create_template
    from .whatsapp_sources import bridge_for
    body = str(action.get("wa_corpo") or "")
    payload = {"name": action.get("wa_nome") or "mugo_ia_modelo", "category": "MARKETING", "language": "pt_BR", "body": body,
               "footer": action.get("wa_rodape") or "", "examples": ["Ana"] if "{{1}}" in body else []}
    if action.get("wa_botao_url"):
        payload["buttons"] = [{"text": action.get("wa_botao_texto") or "Saiba mais", "url": action["wa_botao_url"]}]
    try:
        if await active_number_ids(client_id):
            template = await create_template(client_id, number_id=None, **payload)
        elif bridge_for(client_id):
            template = await brand_whatsapp_templates.create_template(client_id, payload=payload)
        else:
            template = await crm_whatsapp_templates.create_template(client_id, payload=payload)
    except WhatsAppNativeError as exc:
        raise StudioError("MUGO_IA_ACTION_INVALID", f"A Meta recusou o modelo: {exc.message}") from None
    return {"id": str(template.get("id") or template.get("name") or ""), "name": template.get("name") or payload["name"],
            "status": str(template.get("status") or "PENDING").upper()}


def _actions(meta: Dict[str, Any]) -> list:
    """Peças da resposta: lista nova (acoes) ou a proposta única das respostas antigas (acao)."""
    if isinstance(meta.get("acoes"), list):
        return [dict(a) for a in meta["acoes"] if isinstance(a, dict)]
    return [dict(meta["acao"])] if isinstance(meta.get("acao"), dict) else []


def apply_edits(action: Dict[str, Any], edits: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Ajustes que a pessoa faz no cartão antes de criar (hoje: o botão do modelo de WhatsApp). Puro, para teste."""
    import re
    out = dict(action)
    if action.get("tipo") != "whatsapp_modelo" or not edits:
        return out
    url = str(edits.get("wa_botao_url") or "").strip()
    text = str(edits.get("wa_botao_texto") or "").strip()[:25]
    if url and not re.match(r"^https://\S{4,}$", url):
        raise StudioError("MUGO_IA_ACTION_INVALID", "O link do botão precisa começar com https://.")
    if "wa_botao_url" in edits:
        out["wa_botao_url"] = url
    if text:
        out["wa_botao_texto"] = text
    return out


async def execute(client_id: str, message_id: str, *, user_id: str, author: str = "", team: bool, item: int = 0,
                  edits: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    message = await _message(client_id, user_id, message_id)
    meta = dict(message.get("meta") or {})
    actions = _actions(meta)
    if not 0 <= item < len(actions) or actions[item].get("tipo") not in ROUTES:
        raise StudioError("MUGO_IA_ACTION_NOT_FOUND", "Essa resposta não tem nada para criar.")
    action = actions[item]
    if action.get("status") == "criado":
        return {"acao": action, "item": item, "already": True}
    action = apply_edits(action, edits)
    result = await _create(client_id, action, user_id=user_id, author=author, team=team)
    action.update({"status": "criado", "criado": {**result, "route": ROUTES[action["tipo"]], "label": LABELS[action["tipo"]]},
                   "criado_em": datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat()})
    actions[item] = action
    patch = {**meta, "acoes": actions} if isinstance(meta.get("acoes"), list) else {**meta, "acao": action}
    try:
        await sb_update(MESSAGES, filters={"id": f"eq.{message_id}", "client_id": f"eq.{client_id}"}, patch={"meta": patch})
    except Exception as exc:  # noqa: BLE001 — o rascunho já existe; só a marcação ficou para trás
        print(f"[mugo_ia_actions] mark client_id={client_id} error_type={type(exc).__name__}")
    return {"acao": action, "item": item, "already": False}


def creatable(action: Optional[Dict[str, Any]]) -> bool:
    return bool(action) and action.get("tipo") in ROUTES and action.get("status") != "criado"
