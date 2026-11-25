"""Campanhas WhatsApp: público, rascunho e histórico. O envio fica em whatsapp_campaign_send.

O envio vai para todos os contatos com telefone da origem (decisão da agência), menos quem pediu para sair.
Nada aqui expõe telefone: só contagens.
"""
from __future__ import annotations
from typing import Any
from .ig_supabase import sb_insert, sb_select

DRAFTS = "whatsapp_campaign_drafts"
CONTACTS = "relationship_contacts"
CAPTURED = "lead_capture_events"
PAGE = 500
MAX_SCAN = 10000


async def _captured_audience(client_id: str) -> dict[str, Any]:
    """Count landing-page signups, without decrypting or returning contact PII.

    Claimed consent is informational only; it does not authorize a WhatsApp send.
    """
    seen: dict[str, tuple[bool, bool]] = {}
    for offset in range(0, MAX_SCAN, PAGE):
        rows = await sb_select(
            CAPTURED,
            select="client_id,phone_hash,email_hash,consent_whatsapp_claimed,consent_verified",
            filters={"client_id": f"eq.{client_id}"},
            order="id.asc", limit=PAGE, offset=offset,
        )
        for row in rows:
            if row.get("client_id") != client_id:
                continue
            key = str(row.get("phone_hash") or row.get("email_hash") or "")
            if not key:
                continue
            claimed = row.get("consent_whatsapp_claimed") is True
            verified = claimed and row.get("consent_verified") is True
            old_claimed, old_verified = seen.get(key, (False, False))
            seen[key] = (old_claimed or claimed, old_verified or verified)
        if len(rows) < PAGE:
            return {
                "total_contacts": len(seen),
                "consent_claimed_count": sum(claimed for claimed, _ in seen.values()),
                "consent_verified_count": sum(verified for _, verified in seen.values()),
                "sendable_count": 0, "truncated": False,
                "reason": "Leads captados nas landing pages.",
            }
    return {
        "total_contacts": len(seen), "consent_claimed_count": sum(claimed for claimed, _ in seen.values()),
        "consent_verified_count": sum(verified for _, verified in seen.values()),
        "sendable_count": 0, "truncated": True,
        "reason": "Captação acima do limite de prévia. Não é possível simular público incompleto.",
    }


async def audience_preview(client_id: str, provider: str = "all") -> dict[str, Any]:
    if provider not in ("all", "shopify", "fbits", "whatsapp", "capture", "planilha"):
        raise ValueError("Origem inválida.")
    if provider == "capture":
        return await _captured_audience(client_id)

    base = {"client_id": f"eq.{client_id}"}
    if provider != "all":
        base["provider"] = f"eq.{provider}"
    total = eligible = 0
    seen = set()
    truncated = False
    for offset in range(0, MAX_SCAN, PAGE):
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
            break
    else:
        truncated = True

    claimed = 0
    if provider == "all":
        captured = await _captured_audience(client_id)
        # Count source records independently, not a falsely merged customer identity.
        total += captured["total_contacts"]
        eligible += captured["consent_verified_count"]
        claimed = captured["consent_claimed_count"]
        truncated = truncated or captured["truncated"]
    return {
        "total_contacts": total, "consent_claimed_count": claimed,
        "consent_verified_count": eligible, "sendable_count": 0,
        "truncated": truncated,
        "reason": ("Público incompleto: refine a origem antes de simular." if truncated else
                   "Recebem todos os contatos com telefone desta origem, menos quem pediu para sair."),
    }


async def audience_with_sendable(client_id: str, provider: str = "all") -> dict[str, Any]:
    """Prévia com quantos telefones realmente recebem (sem repetir e sem quem pediu para sair)."""
    from .whatsapp_campaign_send import count_sendable
    base = await audience_preview(client_id, provider)
    try:
        base.update(await count_sendable(client_id, provider))
        base["reason"] = "Recebem todos os contatos com telefone desta origem, menos quem pediu para sair."
    except Exception:  # noqa: BLE001 - a prévia segue sem a contagem de telefones
        pass
    return base


BASE_FIELDS = "id,client_id,name,template_name,language,provider,audience_provider,audience_source,status,simulated_count,created_at"
SEND_FIELDS = ",sent_count,failed_count,skipped_count,recipients_count,started_at,finished_at,last_error"
QUEUE_FIELDS = ",scheduled_at,header_media_url"


async def list_drafts(client_id: str) -> list[dict]:
    try:
        rows = await sb_select(DRAFTS, select=BASE_FIELDS + SEND_FIELDS + QUEUE_FIELDS,
                               filters={"client_id": f"eq.{client_id}"}, order="created_at.desc", limit=100)
    except Exception:  # noqa: BLE001 - migration 000138 (ou 000137) ainda não rodou
        try:
            rows = await sb_select(DRAFTS, select=BASE_FIELDS + SEND_FIELDS,
                                   filters={"client_id": f"eq.{client_id}"}, order="created_at.desc", limit=100)
        except Exception:  # noqa: BLE001
            rows = await sb_select(DRAFTS, select=BASE_FIELDS,
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
        raise ValueError("O modelo precisa estar aprovado pela Meta para salvar a campanha.")
    header = str(payload.get("header_media_url") or "").strip() or None
    if header and (not header.startswith("https://") or len(header) > 1000):
        raise ValueError("Link da imagem do topo inválido.")
    import re
    selection = sorted({str(h) for h in (payload.get("selected_contacts") or []) if re.fullmatch(r"[0-9a-f]{64}", str(h))})
    if payload.get("selected_contacts") and provider != "planilha":
        raise ValueError("Escolher contatos à mão só vale para a planilha importada.")
    if len(selection) > 5000:
        raise ValueError("Escolha até 5 mil contatos, ou envie para todos da planilha.")
    audience = await audience_preview(client_id, provider)
    if audience["truncated"]:
        raise ValueError("Público incompleto. Escolha uma origem menor.")
    if selection:
        audience = {**audience, "total_contacts": len(selection), "reason": f"{len(selection)} contato(s) escolhido(s) da planilha."}
    row = await sb_insert(DRAFTS, {
        "client_id": client_id, "name": name, "template_name": template,
        "language": language, "provider": "whatsapp",
        "audience_source": "lead_capture_events" if provider == "capture" else "relationship_contacts",
        "audience_provider": provider, "status": "draft",
        "simulated_count": 0,
        **({"header_media_url": header} if header else {}),
        **({"audience_selection": selection} if selection else {}),
    })
    return {"draft": row, "audience": audience, "messages_sent": 0}
