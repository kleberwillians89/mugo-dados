"""E-mail Marketing a partir de uma tarefa do Kanban (Caminho A do briefing: criar direto no módulo).

Nova campanha → escolher a tarefa → ver o contexto → escolher o entregável → gerar (IA) ou escrever (em branco)
→ rascunho no editor. Sempre RASCUNHO: nada é agendado nem enviado. A campanha fica ligada à tarefa
(``task_work_links``); escolher de novo a mesma tarefa oferece retomar em vez de duplicar.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .studio_calendar import StudioError
from .task_context import links_for, max_percent_allowed, percents_over, record_link, task_context

MODULE = "email_marketing"


def _schema() -> Dict[str, Any]:
    from .studio_llm import STR, arr, obj
    return obj({"assunto": STR, "preheader": STR, "titulo": STR, "texto": STR, "botao": STR, "fotos": arr(STR)})


def _prompt(ctx: Dict[str, Any], deliverable: str, instruction: str) -> str:
    c = ctx["context"]
    lines = [f"Marca: {ctx.get('client_name') or 'a marca'}", f"Tarefa: {ctx['task']['title']}",
             f"Entregável a produzir AGORA (só este): {deliverable or 'e-mail'}"]
    for key, label in (("title", "Campanha"), ("summary", "Resumo"), ("objective", "Objetivo"), ("key_message", "Mensagem principal"),
                       ("offer", "Oferta"), ("audience", "Público"), ("deadline", "Prazo"), ("goal", "Meta"), ("your_part", "Sua parte")):
        if c.get(key):
            lines.append(f"{label}: {c[key]}")
    if c.get("avoid"):
        lines.append("Restrições (obrigatórias): " + "; ".join(c["avoid"]))
    if ctx.get("source") == "notas" and c.get("notes"):
        lines.append(f"Notas da tarefa:\n{c['notes'][:1500]}")
    if instruction:
        lines.append(f"Pedido do profissional: {instruction[:600]}")
    return "\n".join(lines)


INSTRUCTIONS = (
    "Você escreve e-mail marketing para a marca, em português do Brasil, no nível das grandes marcas: assunto curto "
    "(até 60 caracteres), pré-cabeçalho que complementa o assunto, título forte, texto em 2 a 4 parágrafos curtos "
    "separados por linha em branco, e um botão (CTA) de até 4 palavras. Em 'fotos', descreva de 1 a 3 fotos que "
    "ilustrariam o e-mail. Use SOMENTE as informações do briefing: não invente preços, produtos, prazos, condições "
    "comerciais nem benefícios que não estejam escritos. Respeite TODAS as restrições. Linguagem simples, sem jargão. "
    "Escreva só o entregável pedido (um e-mail), nada além."
)


async def _generate(client_id: str, ctx: Dict[str, Any], deliverable: str, instruction: str) -> Dict[str, Any]:
    from .studio_llm import llm_json
    c = ctx["context"]
    limit = max_percent_allowed(c.get("avoid") or [], " ".join(str(c.get(k) or "") for k in ("offer", "summary", "key_message")))
    prompt = _prompt(ctx, deliverable, instruction)
    rules = INSTRUCTIONS + (f" Nunca mencione desconto maior que {limit}%." if limit is not None else "")
    for attempt in range(2):
        data = await llm_json(instructions=rules, prompt=prompt, schema_name="email_da_tarefa", schema=_schema(),
                              client_id=client_id, brand="conteudo", temperature=0.6)
        written = " ".join(str(data.get(k) or "") for k in ("assunto", "preheader", "titulo", "texto", "botao"))
        over = percents_over(written, limit)
        if not over:
            return data
        print(f"[email_from_task] offer_over_limit client_id={client_id} attempt={attempt} limit={limit} found={over}")
        rules += f" ATENÇÃO: a versão anterior citou {', '.join(f'{x}%' for x in over)}; o máximo permitido é {limit}%."
    raise StudioError("EMAIL_OFFER_OVER_LIMIT",
                      f"A IA insistiu em uma oferta acima de {limit}% (proibido no briefing). Tente de novo ou escreva o e-mail.")


async def existing_campaigns(client_id: str, task_id: str, deliverable: Optional[str] = None) -> List[Dict[str, Any]]:
    from .email_marketing import CAMPAIGNS
    from .ig_supabase import sb_select
    links = [l for l in await links_for(client_id, task_id, MODULE) if not deliverable or l.get("deliverable") == deliverable]
    ids = [str(l["record_id"]) for l in links if l.get("record_id")]
    if not ids:
        return []
    rows = await sb_select(CAMPAIGNS, select="id,name,subject,status,updated_at",
                           filters={"client_id": f"eq.{client_id}", "id": f"in.({','.join(ids[:50])})"}, limit=50)
    by_id = {str(r["id"]): r for r in rows}
    return [{**by_id[i], "deliverable": next((l.get("deliverable") for l in links if str(l["record_id"]) == i), "")}
            for i in ids if i in by_id]


async def create_from_task(client_id: str, task_id: str, scope: Dict[str, Any], *, user_id: str, deliverable: str = "",
                           mode: str = "ia", new_version: bool = False, instruction: str = "") -> Dict[str, Any]:
    """Cria o rascunho ligado à tarefa. Já existe um para a tarefa (e entregável)? Devolve para retomar, sem criar."""
    if mode not in ("ia", "branco"):
        raise StudioError("MODE_INVALID", "Escolha gerar com a IA ou escrever.")
    ctx = await task_context(client_id, task_id, scope, module=MODULE)
    deliverable = str(deliverable or ctx.get("suggested_deliverable") or "").strip()[:160]
    if not new_version:
        found = await existing_campaigns(client_id, ctx["task"]["id"], deliverable)
        if found:
            return {"created": None, "existing": found}
    from .email_marketing import save_campaign
    name = f"{ctx['task']['title']}" + (f" · {deliverable}" if deliverable else "")
    if mode == "branco":
        campaign = await save_campaign(client_id, {"name": name[:120]}, user_id=user_id)
    else:
        from .email_brand_look import ensure_brand_look, library_photos, pick_photos
        from .mugo_ia_actions import email_body
        data = await _generate(client_id, ctx, deliverable, instruction)
        action = {"titulo": name[:120], "assunto": data.get("assunto"), "preheader": data.get("preheader"),
                  "email_titulo": data.get("titulo"), "email_texto": data.get("texto"), "botao": data.get("botao"),
                  "email_fotos": list(data.get("fotos") or [])[:3]}
        try:
            await ensure_brand_look(client_id, user_id=user_id)
            photos = pick_photos(action["email_fotos"], await library_photos(client_id))
        except Exception:  # noqa: BLE001 — sem foto/cor da marca, o rascunho sai igual, com os espaços marcados
            photos = []
        campaign = await save_campaign(client_id, email_body(action, photos), user_id=user_id)
    await record_link(client_id, ctx["task"]["id"], module=MODULE, record_id=str(campaign["id"]), deliverable=deliverable,
                      brief_id=ctx.get("brief_id"), user_id=user_id)
    return {"created": {"id": campaign["id"], "name": campaign.get("name"), "status": campaign.get("status")}, "existing": []}
