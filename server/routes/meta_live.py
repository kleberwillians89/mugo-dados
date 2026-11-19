"""Tela Meta (padrão Mídia On): leitura ao vivo das campanhas, quebras e qualidade, e as permissões por função."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from services.studio_calendar import StudioError
from services.tenant import require_client_role

router = APIRouter(prefix="/api/clients/{client_id}/meta/live", tags=["meta-live"])
MEMBERS = ("agency_admin", "client_admin", "viewer", "owner", "admin")
MESSAGES = {
    "AD_ACCOUNT_MISSING": (404, "Conecte uma conta Meta Ads desta empresa em Integrações."),
    "AD_PERMISSION_MISSING": (403, "A conexão Meta não tem permissão de leitura dos anúncios (ads_read). Reconecte em Integrações."),
    "PERIOD_INVALID": (422, "Período inválido (até 92 dias)."),
}


def _http(exc: StudioError) -> HTTPException:
    status, text = MESSAGES.get(exc.code, (502, "Não foi possível ler a Meta agora. Tente de novo em instantes."))
    return HTTPException(status_code=status, detail=text)


@router.get("")
async def read_overview(client_id: str, since: Optional[str] = Query(default=None, max_length=10),
                        until: Optional[str] = Query(default=None, max_length=10), fresh: bool = False,
                        authorization: Optional[str] = Header(default=None)):
    from services.meta_live_insights import overview
    cid = await require_client_role(client_id, authorization, allowed_roles=MEMBERS)
    try:
        return await overview(cid, since=since, until=until, fresh=fresh)
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/permissions")
async def read_permissions(client_id: str, authorization: Optional[str] = Header(default=None)):
    from services.meta_live_insights import permissions
    cid = await require_client_role(client_id, authorization, allowed_roles=MEMBERS)
    return await permissions(cid)
