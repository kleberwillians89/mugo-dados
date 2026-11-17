"""Planejamento de campanhas WhatsApp — sem qualquer ação de envio.

Somente perfis com consentimento WhatsApp verificado podem ser contados como
potencialmente elegíveis. Não expõe telefones nem transforma conversas em opt-in.
"""
from __future__ import annotations
from typing import Any
from .ig_supabase import sb_insert, sb_select

DRAFTS = "whatsapp_campaign_drafts"
CONTACTS = "relationship_contacts"
PAGE = 500
MAX_SCAN = 10000


async def audience_preview(client_id: str, provider: str = "all") -> dict[str, Any]:
    if provider not in ("all", "shopify", "fbits", "whatsapp"):
        raise ValueError("Origem inválida.")
    base = {"client_id": f"eq.{client_id}"}
    if provider != "all":
        base["provider"] = f"eq.{provider}"
    total = eligible = 0
    seen = set()
    # A versão atual não tem lista telefônica e opt-out efetivo de WA:
    # mesmo com flag verificada, NÃO habilitar qualquer envio.
    for offset in range(0, MAX_SCAN + PAGE, PAGE):
        rows = await sb_select(CONTACTS,
            select="client_id,provider,identity_hash,marketing_whatsapp_verified",
            filters=base, order="identity_hash.asc", limit=PAGE, offset=offset)
        for row in rows:
            if row.get("client_id") != client_id:
                continue
            key = (row.get("provider"), row.get("identity_hash"))
            if key in seen:
                continue
            seen.add(key)
            total += 1
            if row.get("marketing_whatsapp_verified") is True:
                eligible += 1
        if len(rows) < PAGE:
            return {"total_contacts": total, "consent_verified_count": eligible,
                    "sendable_count": 0, "truncated": False,
                    "reason": "Envio bloqueado: falta resolver telefone, supressões e fila segura."}
    return {"total_contacts": total, "consent_verified_count": eligible,
            "sendable_count": 0, "truncated": True,
            "reason": "Amostra incompleta; público não pode ser usado para disparo."}


async def list_drafts(client_id: str) -> list[dict]:
    rows = await sb_select(DRAFTS,
        select="id,client_id,name,template_name,language,provider,audience_provider,audience_source,status,simulated_count,created_at",
        filters={"client_id": f"eq.{client_id}"}, order="created_at.desc", limit=100)
    return [r for r in rows if r.get("client_id") == client_id]


async def save_draft(client_id: str, payload: dict, *, approved: bool) -> dict:
    name = str(payload.get("name") or "").strip()
    template = str(payload.get("template_name") or "").strip()
    language = str(payload.get("language") or "pt_BR")
    provider = str(payload.get("provider") or "all")
    if not 3 <= len(name) <= 120:
        raise ValueError("Dê um nome de 3 a 120 caracteres.")
    if not 3 <= len(template) <= 81:
        raise ValueError("Selecione um modelo.")
    if language not in ("pt_BR", "en_US", "es_ES"):
        raise ValueError("Idioma inválido.")
    if not approved:
        raise ValueError("O template precisa estar aprovado pela Meta para salvar a simulação.")
    audience = await audience_preview(client_id, provider)
    if audience["truncated"]:
        raise ValueError("Público incompleto. Não é possível salvar a simulação.")
    row = await sb_insert(DRAFTS, {
        "client_id": client_id, "name": name, "template_name": template,
        "language": language, "provider": "whatsapp",
        "audience_source": "relationship_contacts", "audience_provider": provider, "status": "draft",
        "simulated_count": 0,
    })
    return {"draft": row, "audience": audience, "messages_sent": 0}
