from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from services.ai_runtime import AiRuntimeError, model_catalog, public_settings, revoke_credential, save_settings
from services.tenant import require_client_role, require_user_id

router = APIRouter(prefix="/api/clients/{client_id}/ai-settings", tags=["ai-settings"])
ADMINS = ("agency_admin", "client_admin")


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["platform_managed", "byok"]
    model: str = Field(min_length=1, max_length=80)
    api_key: Optional[str] = Field(default=None, min_length=20, max_length=500)


def _http(exc: AiRuntimeError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})


@router.get("")
async def get_settings(client_id: str, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=ADMINS)
    try:
        return {"settings": await public_settings(cid), "models": model_catalog()}
    except AiRuntimeError as exc:
        raise _http(exc) from None


@router.put("")
async def put_settings(client_id: str, body: SettingsInput, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=ADMINS)
    uid = await require_user_id(authorization)
    try:
        return {"settings": await save_settings(client_id=cid, user_id=uid, mode=body.mode, model=body.model, api_key=body.api_key)}
    except AiRuntimeError as exc:
        raise _http(exc) from None


@router.delete("/credential")
async def delete_credential(client_id: str, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=ADMINS)
    uid = await require_user_id(authorization)
    return {"settings": await revoke_credential(client_id=cid, user_id=uid)}
