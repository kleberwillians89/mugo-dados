from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import httpx

from .ig_supabase import sb_insert, sb_rpc, sb_select


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


class InvitationError(RuntimeError):
    """Erro controlado de aceitação de convite, com status HTTP sugerido."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class SupabaseAccountExistsError(RuntimeError):
    """GoTrue recusou `type=invite` porque o e-mail já tem conta confirmada."""


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
    if role not in {"owner", "agency_admin", "client_admin", "viewer"}:
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

    account_exists = False
    try:
        await send_supabase_invite(
            email=normalized_email,
            invitation_id=str(invitation.get("id") or ""),
            client_id=client_id,
            role=role,
        )
    except SupabaseAccountExistsError:
        # E-mail já tem conta Mugô: a invitation registrada acima continua
        # válida e o convidado a aceita explicitamente (link / login normal).
        account_exists = True
    return {
        "id": invitation.get("id"),
        "email": normalized_email,
        "client_id": client_id,
        "role": role,
        "expires_at": expires_at,
        "account_exists": account_exists,
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
    if response.status_code in (409, 422):
        # GoTrue recusa criar o usuário porque o e-mail já tem conta. Isso NÃO
        # é uma falha da criação de empresa: a invitation já foi registrada e o
        # responsável a aceita explicitamente (link de onboarding / login).
        # Mesma convenção de `generate_supabase_action_link`.
        raise SupabaseAccountExistsError(
            "Este e-mail já possui uma conta ativa na Mugô."
        )
    if response.status_code >= 400:
        raise RuntimeError("Supabase não conseguiu enviar o convite.")


_INVITE_ROLES = {"owner", "agency_admin", "client_admin", "viewer"}


async def get_or_create_company_activation_invitation(
    *,
    client_id: str,
    email: str,
    invited_by: str,
    role: str = "owner",
    expires_hours: int = 72,
) -> Dict[str, Any]:
    """Devolve o convite pendente utilizável da empresa ou cria um novo.

    Nunca cria um segundo convite quando já existe um válido para o mesmo
    e-mail e empresa — evita convites duplicados. Persiste apenas o hash de
    um token interno (idem `create_invitation`); o token bruto é descartado.
    """
    normalized_email = str(email or "").strip().lower()
    if "@" not in normalized_email or len(normalized_email) > 254:
        raise RuntimeError("E-mail de convite inválido.")
    if role not in _INVITE_ROLES:
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
        return existing[0]

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
        raise RuntimeError("Não foi possível registrar o convite de ativação.")
    return invitation


async def generate_supabase_action_link(
    *,
    email: str,
    invitation_id: str,
    client_id: str,
    role: str,
    link_type: str = "invite",
) -> str:
    """Gera um link de ação via GoTrue Admin API (`POST /auth/v1/admin/generate_link`).

    Reaproveita a autenticação nativa do Supabase: nenhum token é persistido —
    o token vive apenas dentro do `action_link` e é gerenciado pelo GoTrue.
    """
    supabase_url = _env("SUPABASE_URL").rstrip("/")
    service_key = _env("SUPABASE_SERVICE_ROLE_KEY")
    redirect_to = _env("SUPABASE_INVITE_REDIRECT_URL")
    if not supabase_url or not service_key or not redirect_to:
        raise RuntimeError("Supabase Admin generate_link não configurado no backend.")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{supabase_url}/auth/v1/admin/generate_link",
            params={"redirect_to": redirect_to},
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "application/json",
            },
            json={
                "type": link_type,
                "email": str(email or "").strip().lower(),
                "data": {
                    "invitation_id": invitation_id,
                    "client_id": client_id,
                    "role": role,
                },
            },
        )

    if response.status_code == 422:
        raise SupabaseAccountExistsError(
            "Este e-mail já possui uma conta ativa na Mugô."
        )
    if response.status_code >= 400:
        raise RuntimeError("Supabase não conseguiu gerar o link de ativação.")

    payload: Dict[str, Any] = {}
    try:
        payload = response.json() if response.content else {}
    except ValueError:
        payload = {}
    action_link = str((payload or {}).get("action_link") or "").strip()
    if not action_link:
        raise RuntimeError("Supabase não retornou o link de ativação.")
    return action_link


async def generate_company_activation_link(
    *,
    email: str,
    invitation_id: str,
    client_id: str,
    role: str,
) -> Dict[str, Any]:
    """Um único link que serve para os dois casos.

    - Conta nova/ não confirmada: `generate_link type=invite` (o `/verify`
      confirma o e-mail e o trigger vincula a membership).
    - Conta já confirmada: fallback para `type=magiclink` — o link faz login e
      o frontend pede a aceitação explícita do convite (RPC `accept_user_invitation`).
    Nunca devolve "erro: conta já existe" para a Mugô.
    """
    try:
        url = await generate_supabase_action_link(
            email=email, invitation_id=invitation_id, client_id=client_id,
            role=role, link_type="invite",
        )
        return {"activation_url": url, "account_exists": False}
    except SupabaseAccountExistsError:
        url = await generate_supabase_action_link(
            email=email, invitation_id=invitation_id, client_id=client_id,
            role=role, link_type="magiclink",
        )
        return {"activation_url": url, "account_exists": True}


_ACCEPT_ERROR_MAP: Dict[str, tuple[str, int]] = {
    "actor_not_found": ("Sessão inválida. Entre novamente.", 401),
    "invitation_not_found": ("Convite não encontrado.", 404),
    "invitation_email_mismatch": (
        "Este convite pertence a outro e-mail. Entre com a conta que foi convidada.", 403,
    ),
    "invitation_revoked": ("Este convite foi cancelado.", 409),
    "invitation_already_accepted": ("Este convite já foi utilizado.", 409),
    "invitation_expired": ("Este convite expirou. Peça um novo link à Mugô.", 409),
}


def _map_accept_error(exc: httpx.HTTPStatusError) -> InvitationError:
    status = exc.response.status_code if exc.response is not None else 400
    message = ""
    if exc.response is not None:
        try:
            body = exc.response.json()
            message = str(
                (body or {}).get("message")
                or (body or {}).get("detail")
                or (body or {}).get("hint")
                or ""
            )
        except ValueError:
            message = str(exc.response.text or "")
    for key, (friendly, code) in _ACCEPT_ERROR_MAP.items():
        if key in message:
            return InvitationError(friendly, status_code=code)
    return InvitationError(
        "Não foi possível aceitar o convite.",
        status_code=status if 400 <= status < 500 else 400,
    )


async def accept_user_invitation(*, actor_user_id: str, invitation_id: str) -> Dict[str, Any]:
    """Aceita EXPLICITAMENTE uma invitation para o usuário autenticado.

    tenant/role vêm da RPC (linha da invitation) — nunca de parâmetro. As
    memberships anteriores do usuário são preservadas (RPC é aditiva).
    """
    actor = str(actor_user_id or "").strip()
    invitation = str(invitation_id or "").strip()
    if not actor or not invitation:
        raise InvitationError("Convite inválido.", status_code=400)
    try:
        result = await sb_rpc(
            "accept_user_invitation",
            {"p_actor_user_id": actor, "p_invitation_id": invitation},
        )
    except httpx.HTTPStatusError as exc:
        raise _map_accept_error(exc) from exc
    data = result if isinstance(result, dict) else (
        result[0] if isinstance(result, list) and result else {}
    )
    return {
        "ok": True,
        "client_id": str((data or {}).get("client_id") or "") or None,
        "role": str((data or {}).get("role") or "") or None,
    }


async def list_pending_invitations_for_email(email: str) -> list[Dict[str, Any]]:
    """Convites pendentes utilizáveis do e-mail autenticado.

    Nunca expõe `token_hash` nem `invited_by`. `client_id` volta só para
    exibição — a autoridade de vínculo é sempre a RPC.
    """
    normalized = str(email or "").strip().lower()
    if "@" not in normalized:
        return []
    rows = await sb_select(
        "user_invitations",
        filters={
            "email": f"eq.{normalized}",
            "accepted_at": "is.null",
            "revoked_at": "is.null",
        },
        order="created_at.desc",
        limit=50,
    )
    usable = [row for row in rows if invitation_is_usable(row)]
    if not usable:
        return []
    client_ids = sorted({str(row.get("client_id") or "") for row in usable if row.get("client_id")})
    names: Dict[str, str] = {}
    if client_ids:
        companies = await sb_select(
            "clients",
            select="id,name,trade_name",
            filters={"id": f"in.({','.join(client_ids)})"},
            limit=len(client_ids),
        )
        names = {
            str(company.get("id")): str(
                company.get("trade_name") or company.get("name") or company.get("id")
            )
            for company in companies
        }
    return [
        {
            "id": str(row.get("id") or ""),
            "client_id": str(row.get("client_id") or ""),
            "role": str(row.get("role") or ""),
            "company_name": names.get(str(row.get("client_id") or "")) or "Empresa",
            "expires_at": row.get("expires_at"),
        }
        for row in usable
    ]

