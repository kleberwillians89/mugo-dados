"""TikTok Ads, TikTok orgânico, Pinterest e Microsoft Clarity: ligar, sincronizar e ler por empresa."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from services import channels
from services.integration_errors import IntegrationError
from services.tenant import require_agency_admin, require_client_read, require_client_role, require_user_id

router = APIRouter(prefix="/api/channels", tags=["channels"])
WRITERS = ("agency_admin", "client_admin")


def _http(exc: IntegrationError) -> HTTPException:
    return HTTPException(status_code=int(getattr(exc, "status_code", 502) or 502), detail=str(exc))


def _front(params: Dict[str, str]) -> str:
    from urllib.parse import urlencode
    from routes.shopify_oauth import _frontend_base_url
    return f"{_frontend_base_url()}/integracoes?{urlencode(params)}"


@router.get("")
async def list_channels(client_id: str = Query(...), start: Optional[str] = Query(default=None), end: Optional[str] = Query(default=None),
                        authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    cid = await require_client_read(client_id, authorization)
    s, e = channels.default_period(7)
    return await channels.overview(cid, start=start or s, end=end or e)


@router.get("/{provider}/start")
async def start(provider: str, client_id: str = Query(...), authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    await require_agency_admin(authorization)
    cid = await require_client_role(client_id, authorization, allowed_roles=("agency_admin",))
    user_id = await require_user_id(authorization)
    try:
        return {"authorization_url": await channels.start(provider, client_id=cid, user_id=user_id)}
    except IntegrationError as exc:
        raise _http(exc) from None


@router.get("/{provider}/callback")
async def callback(provider: str, code: Optional[str] = Query(default=None), auth_code: Optional[str] = Query(default=None),
                   state: Optional[str] = Query(default=None), error: Optional[str] = Query(default=None)):
    """Retorno do login (TikTok usa auth_code nos anúncios). Público: autenticado pelo state assinado."""
    try:
        if error or not (code or auth_code) or not state:
            raise RuntimeError(error or "Login cancelado.")
        out = await channels.finish_oauth(provider, code=str(code or auth_code), state=str(state))
        try:
            await channels.sync(out["client_id"], provider, force=True)
        except Exception as exc:  # noqa: BLE001 — a conexão já está salva; a próxima rodada coleta
            print(f"[channels][callback] first_sync=failed provider={provider} {type(exc).__name__}")
        return RedirectResponse(_front({"channel": provider, "channel_oauth": "success", "client_id": out["client_id"]}), status_code=302)
    except Exception as exc:  # noqa: BLE001
        print(f"[channels][callback] provider={provider} status=error {type(exc).__name__}")
        return RedirectResponse(_front({"channel": provider, "channel_oauth": "error", "error": str(exc)[:160]}), status_code=302)


class ClarityConnect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=20, max_length=4000)
    project_name: Optional[str] = Field(default=None, max_length=120)


@router.post("/clarity/connect")
async def connect_clarity(client_id: str = Query(...), payload: ClarityConnect = Body(...),
                          authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    cid = await require_client_role(client_id, authorization, allowed_roles=("agency_admin",))
    user_id = await require_user_id(authorization)
    try:
        return await channels.connect_clarity(cid, user_id=user_id, token=payload.token, project_name=payload.project_name)
    except IntegrationError as exc:
        raise _http(exc) from None


@router.post("/{provider}/sync")
async def sync_now(provider: str, client_id: str = Query(...), authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        # Clarity tem poucas consultas por dia: o "sincronizar agora" respeita o intervalo dele.
        return await channels.sync(cid, provider, force=provider != "clarity")
    except IntegrationError as exc:
        raise _http(exc) from None


@router.delete("/{provider}")
async def disconnect(provider: str, client_id: str = Query(...), authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    cid = await require_client_role(client_id, authorization, allowed_roles=("agency_admin",))
    user_id = await require_user_id(authorization)
    try:
        return await channels.disconnect(cid, provider, user_id=user_id)
    except IntegrationError as exc:
        raise _http(exc) from None
