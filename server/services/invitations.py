from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import httpx

from .ig_supabase import sb_insert, sb_select


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def invitation_is_usable(row: Dict[str, Any], *, now: datetime | None = None) -> bool:
    current = now or datetime.now(timezone.utc)
    if row.get("accepted_at") or row.get("revoked_at"):
        return False
    try:
        expires = datetime.fromisoformat(str(row.get("expires_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return False
    return expires > current


async def create_invitation(
    *,
    email: str,
    client_id: str,
    role: str,
    invited_by: str,
    expires_hours: int = 72,
) -> Dict[str, Any]:
    normalized_email = str(email or "").strip().lower()
    if "@" not in normalized_email or len(normalized_email) > 254:
        raise RuntimeError("E-mail de convite inválido.")
    if role not in {"agency_admin", "client_admin", "viewer"}:
        raise RuntimeError("Função de convite inválida.")
    existing = await sb_select(
        "user_invitations",
        filters={
            "email": f"eq.{normalized_email}",
            "client_id": f"eq.{client_id}",
            "accepted_at": "is.null",
            "revoked_at": "is.null",
        },
        order="created_at.desc",
        limit=1,
    )
    if existing and invitation_is_usable(existing[0]):
        raise RuntimeError("Já existe um convite válido para este e-mail e empresa.")

    internal_token = secrets.token_urlsafe(32)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(hours=max(1, min(expires_hours, 168)))
    ).isoformat()
    invitation = await sb_insert(
        "user_invitations",
        {
            "email": normalized_email,
            "client_id": client_id,
            "role": role,
            "token_hash": hashlib.sha256(internal_token.encode("utf-8")).hexdigest(),
            "invited_by": invited_by,
            "expires_at": expires_at,
        },
        returning="representation",
    )
    if not invitation:
        raise RuntimeError("Não foi possível registrar o convite.")

    await send_supabase_invite(
        email=normalized_email,
        invitation_id=str(invitation.get("id") or ""),
        client_id=client_id,
        role=role,
    )
    return {
        "id": invitation.get("id"),
        "email": normalized_email,
        "client_id": client_id,
        "role": role,
        "expires_at": expires_at,
    }
async def send_supabase_invite(
    *, email: str, invitation_id: str, client_id: str, role: str
) -> None:
    supabase_url = _env("SUPABASE_URL").rstrip("/")
    service_key = _env("SUPABASE_SERVICE_ROLE_KEY")
    redirect_to = _env("SUPABASE_INVITE_REDIRECT_URL")
    if not supabase_url or not service_key or not redirect_to:
        raise RuntimeError("Supabase Admin Invite não configurado no backend.")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{supabase_url}/auth/v1/invite",
            params={"redirect_to": redirect_to},
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "application/json",
            },
            json={"email": email, "data": {
                "invitation_id": invitation_id, "client_id": client_id, "role": role
            }},
        )
    if response.status_code >= 400:
        raise RuntimeError("Supabase não conseguiu enviar o convite.")

