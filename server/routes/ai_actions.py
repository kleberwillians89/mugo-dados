"""Ações da IA: ler (membros), gerar propostas e decidir (equipe Mugô e admin do cliente)."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, Header, HTTPException, Query

from services import ai_actions
from services.tenant import require_client_read, require_client_role, require_user_id

router = APIRouter(prefix="/api/ai-actions", tags=["ai-actions"])
WRITERS = ("agency_admin", "client_admin")


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, ai_actions.ActionError):
        return HTTPException(status_code=exc.status, detail=exc.message)
    import httpx
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None and exc.response.status_code in (400, 404):
        return HTTPException(status_code=409, detail="Falta aplicar a migração 000110 (ações da IA) no Supabase.")
    print(f"[ai_actions_routes] unexpected {type(exc).__name__}")
    return HTTPException(status_code=502, detail="Não foi possível concluir agora. Tente de novo.")


@router.get("")
async def actions_list(client_id: str | None = Query(default=None), x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                       authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id or x_client_id, authorization)
    try:
        return {"ok": True, "actions": await ai_actions.list_actions(cid)}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.post("/generate")
async def actions_generate(client_id: str | None = Query(default=None), x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                           authorization: str | None = Header(default=None)):
    """Olha os números agora e cria as propostas que fizerem sentido (nada é executado)."""
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    try:
        out = await ai_actions.generate(cid)
        return {"ok": True, **out, "actions": await ai_actions.list_actions(cid)}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.post("/{action_id}/decide")
async def actions_decide(action_id: str, payload: Dict[str, Any] = Body(...), client_id: str | None = Query(default=None),
                         x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                         authorization: str | None = Header(default=None)):
    """Aprovar executa na hora (campanha na fila, fluxo ou carrinho ligado). Rejeitar só registra."""
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    user_id = await require_user_id(authorization)
    try:
        return {"ok": True, "action": await ai_actions.decide(cid, action_id, str(payload.get("decision") or ""), user_id=user_id)}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc
