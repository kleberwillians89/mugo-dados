from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException

from services.auth import get_user_from_bearer
from services.invitations import (
    InvitationError,
    accept_user_invitation,
    create_invitation,
    list_pending_invitations_for_email,
)
from services.tenant import get_client_role, require_client_role, require_user_id

router = APIRouter(prefix="/api/invitations", tags=["invitations"])


@router.get("/mine")
async def my_pending_invitations(authorization: str | None = Header(default=None)):
    """Convites pendentes do usuário autenticado (por e-mail verificado).

    Usado pelo frontend quando um usuário JÁ existente entra por um link de
    ativação — para oferecer a aceitação EXPLÍCITA do convite.
    """
    user = await get_user_from_bearer(authorization)
    if not user or not user.get("email"):
        raise HTTPException(status_code=401, detail="Autenticação obrigatória")
    return {
        "ok": True,
        "invitations": await list_pending_invitations_for_email(str(user.get("email"))),
    }


@router.post("/{invitation_id}/accept")
async def accept_invitation(invitation_id: str, authorization: str | None = Header(default=None)):
    """Aceita EXPLICITAMENTE uma invitation específica para o usuário logado.

    O tenant/role vêm da própria invitation (RPC). Nenhum client_id/role do
    corpo é aceito — a rota não tem corpo.
    """
    user_id = await require_user_id(authorization)
    try:
        return await accept_user_invitation(actor_user_id=user_id, invitation_id=invitation_id)
    except InvitationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("")
async def invite(payload: Dict[str, Any], authorization: str | None = Header(default=None)):
    requested_client_id = str(payload.get("client_id") or "").strip()
    cid = await require_client_role(
        requested_client_id,
        authorization,
        allowed_roles=("agency_admin",),
    )
    user_id = await require_user_id(authorization)
    requested_role = str(payload.get("role") or "viewer")
    inviter_role = await get_client_role(cid, authorization)
    if requested_role == "agency_admin" and inviter_role not in {"agency_admin", "platform_admin"}:
        raise HTTPException(status_code=403, detail="Somente agency_admin pode convidar outro agency_admin.")
    try:
        invitation = await create_invitation(
            email=str(payload.get("email") or ""),
            client_id=cid,
            role=requested_role,
            invited_by=user_id,
            expires_hours=int(payload.get("expires_hours") or 72),
        )
        return {"ok": True, "invitation": invitation}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
