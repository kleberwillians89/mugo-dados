"""Administração de acessos da empresa ativa.

A empresa vem SEMPRE do contexto autorizado (`require_client_role`), que já
aceita platform_admin, agency_admin e client_admin da própria empresa, e
recusa viewer. Um `client_id` vindo do browser é apenas o pedido: se o ator não
tiver papel nela, a própria guarda recusa — então não há como administrar o
tenant de outra pessoa mandando outro id.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException, Query

from services.client_access import (
    AccessError,
    create_client_access,
    list_client_access,
    remove_client_access,
    reset_client_access_password,
)
from services.tenant import require_client_role, require_user_id, resolve_client_id

router = APIRouter(prefix="/api/client-access", tags=["client-access"])


def _fail(exc: AccessError) -> None:
    raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})


async def _manage_context(
    client_id: str | None, x_client_id: str | None, authorization: str | None,
) -> tuple[str, str]:
    """Empresa autorizada + ator. Viewer é recusado por require_client_role."""
    cid = await require_client_role(client_id or x_client_id, authorization)
    actor = await require_user_id(authorization)
    return cid, actor


@router.get("")
async def access_list(
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    # Leitura: qualquer membro da empresa, inclusive viewer.
    await require_user_id(authorization)
    cid = await resolve_client_id(client_id or x_client_id, authorization)
    try:
        return await list_client_access(cid)
    except AccessError as exc:
        _fail(exc)


@router.post("")
async def access_create(
    payload: Dict[str, Any],
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid, actor = await _manage_context(client_id, x_client_id, authorization)
    try:
        return await create_client_access(
            client_id=cid,
            actor_user_id=actor,
            name=payload.get("name"),
            email=payload.get("email"),
            password=payload.get("password"),
            password_confirmation=payload.get("password_confirmation"),
            role=payload.get("role"),
        )
    except AccessError as exc:
        _fail(exc)


@router.post("/{user_id}/password")
async def access_reset_password(
    user_id: str,
    payload: Dict[str, Any],
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid, actor = await _manage_context(client_id, x_client_id, authorization)
    try:
        return await reset_client_access_password(
            client_id=cid,
            actor_user_id=actor,
            user_id=user_id,
            password=payload.get("password"),
            password_confirmation=payload.get("password_confirmation"),
        )
    except AccessError as exc:
        _fail(exc)


@router.delete("/{user_id}")
async def access_remove(
    user_id: str,
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid, actor = await _manage_context(client_id, x_client_id, authorization)
    try:
        return await remove_client_access(client_id=cid, actor_user_id=actor, user_id=user_id)
    except AccessError as exc:
        _fail(exc)
