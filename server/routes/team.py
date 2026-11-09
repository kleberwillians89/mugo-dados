"""Usuários da empresa ativa, com permissões por módulo (tela Usuários).

Leitura da lista: ``team.view``; mudanças: ``team.edit`` — os dois checados pela guarda de tenant
(team_access.route_module). Equipe Mugô gerencia qualquer empresa; o admin do cliente, a própria.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from services import team_access as ta
from services import team_admin
from services.client_access import AccessError
from services.tenant import is_agency_user, require_client_read, require_client_role, require_user_id

router = APIRouter(prefix="/api/team", tags=["team"])
MANAGERS = ("agency_admin", "client_admin")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Permissions(Strict):
    preset: str = Field(min_length=1, max_length=40)
    view_all: bool = False
    access_total: bool = False
    codes: Optional[List[str]] = Field(default=None, max_length=200)


class NewMember(Permissions):
    name: str = Field(default="", max_length=120)
    login: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=8, max_length=200)


class StatusInput(Strict):
    status: str


class PasswordInput(Strict):
    password: str = Field(min_length=8, max_length=200)


def _fail(exc: AccessError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})


async def _manager(client_id: Optional[str], authorization: Optional[str]) -> tuple[str, Dict[str, Any]]:
    cid = await require_client_role(client_id, authorization, allowed_roles=MANAGERS)
    uid = await require_user_id(authorization)
    return cid, await team_admin.actor_scope(cid, uid, team=await is_agency_user(authorization, cid))


@router.get("/catalog")
async def team_catalog(authorization: Optional[str] = Header(default=None)):
    await require_user_id(authorization)
    return ta.catalog_payload()


@router.get("/me")
async def team_me(client_id: Optional[str] = Query(default=None),
                  x_client_id: Optional[str] = Header(default=None, alias="X-Client-Id"),
                  authorization: Optional[str] = Header(default=None)):
    """O que o próprio usuário pode ver e fazer na empresa ativa (menu e telas usam isto)."""
    cid = await require_client_read(client_id or x_client_id, authorization)
    uid = await require_user_id(authorization)
    if await is_agency_user(authorization, cid):
        return {"client_id": cid, "team": True, "access_total": True, "codes": sorted(ta.ALL_CODES)}
    access = await ta.member_access(cid, uid) or {"access_total": False, "codes": set(), "preset": None}
    return {"client_id": cid, "team": False, "access_total": bool(access["access_total"]),
            "preset": access.get("preset"), "codes": sorted(access["codes"])}


@router.get("/members")
async def team_members(client_id: Optional[str] = Query(default=None),
                       x_client_id: Optional[str] = Header(default=None, alias="X-Client-Id"),
                       authorization: Optional[str] = Header(default=None)):
    cid = await require_client_read(client_id or x_client_id, authorization)
    try:
        return await team_admin.list_members(cid)
    except AccessError as exc:
        raise _fail(exc) from None


@router.post("/members", status_code=201)
async def team_create(body: NewMember, client_id: Optional[str] = Query(default=None),
                      x_client_id: Optional[str] = Header(default=None, alias="X-Client-Id"),
                      authorization: Optional[str] = Header(default=None)):
    cid, actor = await _manager(client_id or x_client_id, authorization)
    try:
        return await team_admin.create_member(client_id=cid, actor=actor, name=body.name, login=body.login,
                                              password=body.password, preset=body.preset, view_all=body.view_all,
                                              access_total=body.access_total, codes=body.codes)
    except AccessError as exc:
        raise _fail(exc) from None


@router.put("/members/{user_id}")
async def team_update(user_id: str, body: Permissions, client_id: Optional[str] = Query(default=None),
                      x_client_id: Optional[str] = Header(default=None, alias="X-Client-Id"),
                      authorization: Optional[str] = Header(default=None)):
    cid, actor = await _manager(client_id or x_client_id, authorization)
    try:
        return await team_admin.update_permissions(client_id=cid, actor=actor, user_id=user_id, preset=body.preset,
                                                   view_all=body.view_all, access_total=body.access_total, codes=body.codes)
    except AccessError as exc:
        raise _fail(exc) from None


@router.post("/members/{user_id}/status")
async def team_status(user_id: str, body: StatusInput, client_id: Optional[str] = Query(default=None),
                      x_client_id: Optional[str] = Header(default=None, alias="X-Client-Id"),
                      authorization: Optional[str] = Header(default=None)):
    cid, actor = await _manager(client_id or x_client_id, authorization)
    try:
        return await team_admin.set_status(client_id=cid, actor=actor, user_id=user_id, status=body.status)
    except AccessError as exc:
        raise _fail(exc) from None


@router.post("/members/{user_id}/password")
async def team_password(user_id: str, body: PasswordInput, client_id: Optional[str] = Query(default=None),
                        x_client_id: Optional[str] = Header(default=None, alias="X-Client-Id"),
                        authorization: Optional[str] = Header(default=None)):
    cid, actor = await _manager(client_id or x_client_id, authorization)
    try:
        return await team_admin.reset_password(client_id=cid, actor=actor, user_id=user_id, password=body.password)
    except AccessError as exc:
        raise _fail(exc) from None


@router.delete("/members/{user_id}")
async def team_remove(user_id: str, client_id: Optional[str] = Query(default=None),
                      x_client_id: Optional[str] = Header(default=None, alias="X-Client-Id"),
                      authorization: Optional[str] = Header(default=None)):
    cid, actor = await _manager(client_id or x_client_id, authorization)
    try:
        return await team_admin.remove_member(client_id=cid, actor=actor, user_id=user_id)
    except AccessError as exc:
        raise _fail(exc) from None
