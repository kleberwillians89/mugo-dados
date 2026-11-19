"""Track WhatsApp group invite clicks across two ad funnels, scoped per tenant.

Clicks are NOT confirmed group joins. No identity, IP or raw user agent is stored.
The redirect destination is configured by an authenticated account member and
restricted to canonical WhatsApp group invite URLs.
"""
from __future__ import annotations

import re
import secrets
from typing import Any
from urllib.parse import urlsplit

from .ig_supabase import sb_insert, sb_rpc, sb_select, sb_update

TABLE = "relationship_group_invite_links"
CAMPAIGN = re.compile(r"^[a-z0-9_-]{2,80}$")
SLUG = re.compile(r"^[A-Za-z0-9_-]{22,90}$")
CODE = re.compile(r"^[A-Za-z0-9]+$")


class GroupLinkError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message, self.status = message, status


def validate_invite_url(raw: Any) -> str:
    value = str(raw or "").strip()
    if len(value) > 500:
        raise GroupLinkError("Convite muito longo.")
    try:
        parts = urlsplit(value)
    except ValueError:
        raise GroupLinkError("Link de convite inválido.") from None
    token = parts.path.removeprefix("/")
    if (parts.scheme != "https" or parts.hostname != "chat.whatsapp.com"
        or parts.username or parts.password or parts.port is not None
        or not CODE.fullmatch(token) or parts.fragment):
        raise GroupLinkError("Use um convite oficial https://chat.whatsapp.com/...")
    return value


def _safe(record: dict) -> dict:
    return {k: record.get(k) for k in (
        "id", "client_id", "campaign_key", "label", "variant", "slug",
        "invite_url", "active", "click_count", "created_at"
    )}


async def create_link(client_id: str, payload: dict[str, Any]) -> dict:
    campaign = str(payload.get("campaign_key") or "").strip().lower()
    variant = str(payload.get("variant") or "")
    label = " ".join(str(payload.get("label") or "").split())[:100]
    if not CAMPAIGN.fullmatch(campaign):
        raise GroupLinkError("Identificador da campanha inválido.")
    if variant not in ("direct", "post_signup"):
        raise GroupLinkError("Escolha tráfego direto ou após cadastro.")
    if len(label) < 2:
        raise GroupLinkError("Dê um nome ao link.")
    destination = validate_invite_url(payload.get("invite_url"))
    existing = await sb_select(TABLE, select="id", filters={
        "client_id": f"eq.{client_id}", "campaign_key": f"eq.{campaign}",
        "variant": f"eq.{variant}"
    }, limit=1)
    if existing:
        raise GroupLinkError("Já existe link para esta campanha e jornada. Edite ou use outra campanha.", 409)
    row = {
        "client_id": client_id, "campaign_key": campaign,
        "label": label, "variant": variant,
        "invite_url": destination,
        "slug": secrets.token_urlsafe(24),
        "active": True,
    }
    stored = await sb_insert(TABLE, row)
    if not stored:
        raise GroupLinkError("Não foi possível criar o link.", 503)
    return _safe(stored)


async def list_links(client_id: str) -> list[dict]:
    rows = await sb_select(TABLE,
        select="id,client_id,campaign_key,label,variant,slug,invite_url,active,click_count,created_at",
        filters={"client_id": f"eq.{client_id}"}, order="created_at.desc", limit=200)
    return [_safe(row) for row in rows]


async def change_status(client_id: str, link_id: str, active: bool) -> None:
    owned = await sb_select(TABLE, select="id", filters={
        "id": f"eq.{link_id}", "client_id": f"eq.{client_id}"
    }, limit=1)
    if not owned:
        raise GroupLinkError("Link não encontrado.", 404)
    await sb_update(TABLE, filters={"id": f"eq.{link_id}", "client_id": f"eq.{client_id}"},
                    patch={"active": active}, returning="minimal")


async def destination_for_click(slug: str) -> str:
    if not SLUG.fullmatch(slug):
        raise GroupLinkError("Convite indisponível.", 404)
    result = await sb_rpc("register_group_invite_click", {"p_slug": slug})
    row = (result[0] if isinstance(result, list) and result else
           result if isinstance(result, dict) else None)
    if not row:
        raise GroupLinkError("Convite indisponível.", 404)
    return validate_invite_url(row.get("destination_url"))
