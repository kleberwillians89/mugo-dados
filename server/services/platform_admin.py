from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import httpx
from fastapi import HTTPException

from .ig_supabase import sb_insert, sb_rpc, sb_select, sb_update
from .invitations import (
    SupabaseAccountExistsError,
    generate_company_activation_link,
    get_or_create_company_activation_invitation,
    send_supabase_invite,
)
from .tenant import require_user_id
from .runtime_cache import get_cached_or_load


async def is_platform_admin(user_id: str) -> bool:
    async def load():
        return await sb_select(
            "platform_admins",
            select="user_id,role,granted_at",
            filters={"user_id": f"eq.{user_id}", "role": "eq.platform_admin"},
            limit=1,
        )

    rows, _ = await get_cached_or_load(
        namespace="platform_admin",
        key=str(user_id or ""),
        ttl_seconds=60,
        loader=load,
    )
    return bool(rows)


async def require_platform_admin(
    authorization: str | None, *, allow_agency_admin: bool = True
) -> str:
    """Autoriza um endpoint de administração da plataforma.

    `allow_agency_admin=True` (padrão): equipe da agência acessa suporte/leitura
    sem membership por cliente. `allow_agency_admin=False`: apenas platform_admin
    — usado na CRIAÇÃO de empresa, cuja autoridade é o `platform_admins` +
    `is_platform_admin` na RPC `create_platform_company` (security definer).
    """
    user_id = await require_user_id(authorization)
    platform_access = await is_platform_admin(user_id)
    if platform_access:
        return user_id
    if allow_agency_admin:
        from .tenant import _has_agency_admin_membership
        try:
            if await _has_agency_admin_membership(user_id):
                return user_id
        except Exception:
            pass
    raise HTTPException(status_code=403, detail="Acesso exclusivo do administrador da plataforma.")


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

    # Chave de idempotência por request: o frontend gera uma por tentativa e a
    # reenvia em retries. Sem chave (ex.: rota legada sem UI) → uma gerada aqui,
    # que só degrada para "sem idempotência" naquele request isolado.
    creation_request_id = str(payload.get("idempotency_key") or "").strip()[:200] or uuid.uuid4().hex

    internal_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=72)
    try:
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
                "p_creation_request_id": creation_request_id,
            },
        )
    except httpx.HTTPStatusError as exc:
        # Erro da RPC (permissão, validação, CNPJ duplicado) vira uma mensagem
        # clara para o painel — nunca um 500 opaco "Erro interno da API".
        raise RuntimeError(_describe_create_company_rpc_error(exc)) from exc
    company = dict((created or {}).get("client") or {})
    invitation = dict((created or {}).get("invitation") or {})

    if (created or {}).get("idempotent_replay"):
        # Retry/concorrência: a empresa e o convite já foram criados (e o convite
        # já foi enviado) no primeiro request. Devolve a MESMA empresa sem
        # reenviar convite nem tocar em nada.
        return {
            "ok": True,
            "company": company,
            "invitation": invitation,
            "responsible_account_exists": False,
            "idempotent_replay": True,
        }

    responsible_account_exists = False
    try:
        await send_supabase_invite(
            email=email,
            invitation_id=str(invitation.get("id") or ""),
            client_id=str(company.get("id") or ""),
            role="owner",
        )
    except SupabaseAccountExistsError:
        # Responsável já tem conta Mugô: a invitation criada pela RPC continua
        # válida e ele a aceita explicitamente (link de onboarding / login
        # normal). A empresa NÃO é revertida — este é um cenário comercial
        # normal (cliente existente ganhando uma 2ª empresa).
        responsible_account_exists = True
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
    return {
        "ok": True,
        "company": company,
        "invitation": invitation,
        "responsible_account_exists": responsible_account_exists,
        "idempotent_replay": False,
    }


def _describe_create_company_rpc_error(exc: httpx.HTTPStatusError) -> str:
    body_message = ""
    if exc.response is not None:
        try:
            body = exc.response.json()
        except ValueError:
            body = {}
        body_message = str(
            (body or {}).get("message")
            or (body or {}).get("hint")
            or (body or {}).get("detail")
            or ""
        )
    if "platform_admin_required" in body_message:
        return "Apenas administradores da plataforma podem criar empresas."
    if "creation_request_id_required" in body_message:
        return "Requisição de criação inválida. Recarregue a página e tente novamente."
    if "invalid_responsible_email" in body_message:
        return "E-mail do responsável inválido."
    if "invalid_company_name" in body_message:
        return "Razão social deve ter ao menos 2 caracteres."
    if exc.response is not None and exc.response.status_code == 409:
        return "Já existe uma empresa com esses dados. Verifique o CNPJ."
    return "Não foi possível registrar a empresa agora. Tente novamente."


async def create_company_activation_link(actor_user_id: str, client_id: str) -> Dict[str, Any]:
    """Gera o link de ativação de uma empresa para a Mugô copiar e enviar.

    O tenant vem SEMPRE do path (`client_id`), validado contra `clients` — nunca
    de um valor arbitrário do frontend. Reutiliza o convite pendente válido do
    responsável quando existir; senão cria um. Nenhuma tabela nova, nenhum token
    bruto: o link é emitido pelo GoTrue Admin API.
    """
    cid = str(client_id or "").strip()
    if not cid:
        raise RuntimeError("Empresa não informada.")
    rows = await sb_select(
        "clients",
        select="id,name,trade_name,responsible_email,status",
        filters={"id": f"eq.{cid}"},
        limit=1,
    )
    if not rows:
        raise RuntimeError("Empresa não encontrada.")
    company = rows[0]
    email = str(company.get("responsible_email") or "").strip().lower()
    if "@" not in email:
        raise RuntimeError("A empresa não possui e-mail de responsável cadastrado.")

    invitation = await get_or_create_company_activation_invitation(
        client_id=cid,
        email=email,
        invited_by=actor_user_id,
        role="owner",
    )
    invitation_id = str(invitation.get("id") or "")
    role = str(invitation.get("role") or "owner")

    link = await generate_company_activation_link(
        email=email,
        invitation_id=invitation_id,
        client_id=cid,
        role=role,
    )

    await sb_insert(
        "platform_audit_events",
        {
            "actor_user_id": actor_user_id,
            "client_id": cid,
            "event_type": "activation_link_generated",
            "details": {
                "invitation_id": invitation_id,
                "responsible_email": email,
                "account_exists": bool(link.get("account_exists")),
            },
        },
        returning="minimal",
    )

    return {
        "ok": True,
        "invitation": {
            "id": invitation_id,
            "email": email,
            "client_id": cid,
            "role": role,
            "expires_at": invitation.get("expires_at"),
        },
        "activation_url": link.get("activation_url"),
        "account_exists": bool(link.get("account_exists")),
    }


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
