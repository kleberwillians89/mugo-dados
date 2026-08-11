from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException

from services.invitations import create_invitation
from services.tenant import get_client_role, require_client_role, require_user_id

router = APIRouter(prefix="/api/invitations", tags=["invitations"])


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
