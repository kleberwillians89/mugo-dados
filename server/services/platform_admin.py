from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from fastapi import HTTPException

from .ig_supabase import sb_insert, sb_rpc, sb_select, sb_update
from .invitations import send_supabase_invite
from .tenant import require_user_id


async def is_platform_admin(user_id: str) -> bool:
    rows = await sb_select(
        "platform_admins",
        select="user_id,role,granted_at",
        filters={"user_id": f"eq.{user_id}", "role": "eq.platform_admin"},
        limit=1,
    )
    return bool(rows)


async def require_platform_admin(authorization: str | None) -> str:
    user_id = await require_user_id(authorization)
    if not await is_platform_admin(user_id):
        raise HTTPException(status_code=403, detail="Acesso exclusivo do administrador da plataforma.")
    return user_id


async def list_platform_companies() -> Dict[str, Any]:
    rows = await sb_select(
        "clients",
        select="id,name,trade_name,cnpj,responsible_email,status,created_by,created_at,updated_at",
        order="created_at.desc",
    )
    invitations = await sb_select(
        "user_invitations",
        select="id,client_id,email,role,expires_at,accepted_at,revoked_at,created_at",
        order="created_at.desc",
    )
    by_client: Dict[str, Dict[str, Any]] = {}
    for invitation in invitations:
        by_client.setdefault(str(invitation.get("client_id") or ""), invitation)
    now = datetime.now(timezone.utc)
    companies = []
    for row in rows:
        invitation = by_client.get(str(row.get("id") or ""))
        invite_status = None
        if invitation:
            if invitation.get("accepted_at"):
                invite_status = "accepted"
            elif invitation.get("revoked_at"):
                invite_status = "revoked"
            else:
                expires = datetime.fromisoformat(str(invitation.get("expires_at")).replace("Z", "+00:00"))
                invite_status = "expired" if expires <= now else "pending"
        companies.append({**row, "invitation_status": invite_status})
    return {"ok": True, "companies": companies}


async def create_platform_company(actor_user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    trade_name = str(payload.get("trade_name") or "").strip()
    email = str(payload.get("responsible_email") or "").strip().lower()
    cnpj_raw = str(payload.get("cnpj") or "").strip()
    cnpj = re.sub(r"\D", "", cnpj_raw) or None
    if len(name) < 2:
        raise RuntimeError("Razão social deve ter ao menos 2 caracteres.")
    if "@" not in email or len(email) > 254:
        raise RuntimeError("E-mail do responsável inválido.")
    if cnpj and len(cnpj) != 14:
        raise RuntimeError("CNPJ deve conter 14 dígitos.")

    internal_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=72)
    created = await sb_rpc(
        "create_platform_company",
        {
            "p_actor_user_id": actor_user_id,
            "p_name": name,
            "p_trade_name": trade_name,
            "p_cnpj": cnpj,
            "p_responsible_email": email,
            "p_token_hash": hashlib.sha256(internal_token.encode()).hexdigest(),
            "p_expires_at": expires_at.isoformat(),
        },
    )
    company = dict((created or {}).get("client") or {})
    invitation = dict((created or {}).get("invitation") or {})
    try:
        await send_supabase_invite(
            email=email,
            invitation_id=str(invitation.get("id") or ""),
            client_id=str(company.get("id") or ""),
            role="owner",
        )
    except Exception:
        rolled_back = await sb_rpc(
            "rollback_platform_company_creation",
            {
                "p_actor_user_id": actor_user_id,
                "p_client_id": company.get("id"),
                "p_invitation_id": invitation.get("id"),
            },
        )
        if not rolled_back:
            raise RuntimeError("Falha no convite e na compensação segura da empresa.")
        raise
    return {"ok": True, "company": company, "invitation": invitation}


async def update_platform_company(
    actor_user_id: str,
    client_id: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    patch: Dict[str, Any] = {}
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if len(name) < 2:
            raise RuntimeError("Razão social deve ter ao menos 2 caracteres.")
        patch["name"] = name
    if "trade_name" in payload:
        patch["trade_name"] = str(payload.get("trade_name") or "").strip() or None
    if "cnpj" in payload:
        cnpj = re.sub(r"\D", "", str(payload.get("cnpj") or "")) or None
        if cnpj and len(cnpj) != 14:
            raise RuntimeError("CNPJ deve conter 14 dígitos.")
        patch["cnpj"] = cnpj
    if "status" in payload:
        status = str(payload.get("status") or "").strip()
        if status not in {"active", "inactive", "invitation_pending"}:
            raise RuntimeError("Status de empresa inválido.")
        patch["status"] = status
    if not patch:
        raise RuntimeError("Nenhuma alteração válida foi informada.")

    updated = await sb_update(
        "clients",
        filters={"id": f"eq.{client_id}"},
        patch=patch,
        returning="representation",
    )
    if not updated:
        raise RuntimeError("Empresa não encontrada.")
    await sb_insert(
        "platform_audit_events",
        {
            "actor_user_id": actor_user_id,
            "client_id": client_id,
            "event_type": "company_updated",
            "details": {"fields": sorted(patch.keys())},
        },
        returning="minimal",
    )
    return {"ok": True, "company": updated[0]}
