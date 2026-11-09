"""Usuários da empresa com permissões por módulo (tela Usuários, modelo do CRM Ruah).

Reaproveita ``client_access`` (Supabase Auth como dono da conta, ``client_memberships`` como vínculo,
senha nunca gravada nem devolvida) e acrescenta:

- **login por usuário**: "joao.vendas" vira, só internamente, joao.vendas@acesso.mugo.ag (sem e-mail real);
- **preset + ver tudo + acesso total + ajustes por código** (ver team_access);
- **status** ativo/inativo (inativo não entra em nada da empresa; a conta continua existindo).

Regras do servidor:
- quem não é equipe Mugô nem tem acesso total só concede códigos que ele mesmo tem, e nunca acesso total;
- ninguém altera o próprio acesso (evita se trancar fora);
- contas da equipe Mugô não são administradas aqui.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from . import team_access as ta
from .client_access import (
    GLOBAL_ROLES, AccessError, _admin_request, _auth_user_view, _create_auth_user, _delete_auth_user,
    _holds_global_role, _membership, find_auth_user_by_email, normalize_email, validate_password,
)
from .ig_supabase import sb_delete, sb_insert, sb_select, sb_update, sb_upsert

INTERNAL_LOGIN_DOMAIN = "acesso.mugo.ag"
USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,32}$")
MEMBER_COLUMNS = "id,user_id,client_id,role,status,permission_preset,view_all,access_total,username,created_at"


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def login_email(identifier: Any) -> tuple[str, Optional[str]]:
    """(e-mail de login, usuário). "joao.vendas" → e-mail interno; um e-mail real passa direto."""
    raw = _text(identifier).lower()
    if "@" in raw:
        return normalize_email(raw), None
    if not USERNAME_RE.match(raw):
        raise AccessError("TEAM_USERNAME_INVALID",
                          "Usuário deve ter de 3 a 32 caracteres: letras minúsculas, números, ponto, hífen ou _.")
    return f"{raw}@{INTERNAL_LOGIN_DOMAIN}", raw


def display_login(email: Optional[str], username: Optional[str]) -> str:
    if username:
        return username
    value = _text(email).lower()
    suffix = f"@{INTERNAL_LOGIN_DOMAIN}"
    return value[: -len(suffix)] if value.endswith(suffix) else value


def _preset(value: Any) -> str:
    preset = _text(value).lower() or "personalizado"
    if preset not in ta.PRESETS:
        raise AccessError("TEAM_PRESET_INVALID", "Escolha um perfil de acesso válido.")
    return preset


def _check_grant(actor: Dict[str, Any], *, access_total: bool, codes: set) -> None:
    """Quem não pode tudo só repassa o que tem."""
    if actor["team"] or actor["access_total"]:
        return
    if access_total:
        raise AccessError("TEAM_GRANT_NOT_ALLOWED", "Só quem tem acesso total pode dar acesso total.", status_code=403)
    extra = codes - actor["codes"]
    if extra:
        raise AccessError("TEAM_GRANT_NOT_ALLOWED",
                          "Você não pode conceder permissões que o seu usuário não tem.", status_code=403)


async def actor_scope(client_id: str, user_id: str, *, team: bool) -> Dict[str, Any]:
    if team:
        return {"user_id": user_id, "team": True, "access_total": True, "codes": set(ta.ALL_CODES)}
    access = await ta.member_access(client_id, user_id) or {"access_total": False, "codes": set()}
    return {"user_id": user_id, "team": False, "access_total": bool(access["access_total"]), "codes": set(access["codes"])}


async def _members(client_id: str, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    filters = {"client_id": f"eq.{client_id}"}
    if user_id:
        filters["user_id"] = f"eq.{user_id}"
    try:
        return await sb_select("client_memberships", select=MEMBER_COLUMNS, filters=filters, order="created_at.asc", limit=500)
    except Exception as exc:  # noqa: BLE001 — sem a migração 000083
        print(f"[team][members] client_id={client_id} schema_compat error_type={type(exc).__name__}")
        raise AccessError("TEAM_MIGRATION_PENDING",
                          "Falta aplicar a migração 000083 (usuários e permissões) no banco.", status_code=503) from None


async def _overrides(client_id: str) -> Dict[str, List[tuple]]:
    rows = await sb_select("client_member_permissions", select="user_id,permission_code,granted",
                           filters={"client_id": f"eq.{client_id}"}, limit=5000)
    out: Dict[str, List[tuple]] = {}
    for r in rows:
        out.setdefault(_text(r.get("user_id")), []).append((_text(r.get("permission_code")), bool(r.get("granted"))))
    return out


def _member_view(row: Dict[str, Any], detail: Dict[str, Any], overrides: List[tuple]) -> Dict[str, Any]:
    role = _text(row.get("role")).lower()
    flags = ({"preset": row.get("permission_preset"), "view_all": bool(row.get("view_all")),
              "access_total": bool(row.get("access_total"))}
             if row.get("permission_preset") else ta.legacy_flags(role))
    status = _text(row.get("status")) or "active"
    return {
        "user_id": _text(row.get("user_id")),
        "name": detail.get("name"),
        "login": display_login(detail.get("email"), row.get("username")),
        "role": role,
        "is_global_role": role in GLOBAL_ROLES or role == "account_manager",
        "preset": flags["preset"],
        "preset_label": ta.PRESETS.get(str(flags["preset"]), {}).get("label", flags["preset"]),
        "view_all": flags["view_all"],
        "access_total": flags["access_total"],
        "status": status,
        "permission_overrides": len(overrides),
        "codes": sorted(ta.resolve_codes(status=status, preset=flags["preset"], view_all=flags["view_all"],
                                         access_total=flags["access_total"], overrides=overrides)),
        "last_sign_in_at": detail.get("last_sign_in_at"),
        "created_at": row.get("created_at"),
    }


async def list_members(client_id: str) -> Dict[str, Any]:
    rows = await _members(client_id)
    overrides = await _overrides(client_id)
    users: Dict[str, Dict[str, Any]] = {}
    try:
        payload = await _admin_request("GET", "/users", params={"page": 1, "per_page": 1000})
        listed = payload.get("users") if isinstance(payload, dict) else payload
        for user in listed if isinstance(listed, list) else []:
            if isinstance(user, dict) and _text(user.get("id")):
                users[_text(user.get("id"))] = _auth_user_view(user)
    except AccessError as exc:
        print(f"[team][list] client_id={client_id} status=auth_unavailable code={exc.code}")
    items = [_member_view(r, users.get(_text(r.get("user_id")), {}), overrides.get(_text(r.get("user_id")), []))
             for r in rows if _text(r.get("client_id")) == client_id]
    return {"ok": True, "client_id": client_id, "items": items}


async def _save_overrides(client_id: str, user_id: str, overrides: Iterable[tuple]) -> None:
    await sb_delete("client_member_permissions", filters={"client_id": f"eq.{client_id}", "user_id": f"eq.{user_id}"},
                    returning="minimal")
    rows = [{"client_id": client_id, "user_id": user_id, "permission_code": c, "granted": g} for c, g in overrides]
    if rows:
        await sb_upsert("client_member_permissions", rows, on_conflict="client_id,user_id,permission_code")


def _permission_fields(preset: str, view_all: bool, access_total: bool) -> Dict[str, Any]:
    return {"permission_preset": preset, "view_all": view_all, "access_total": access_total,
            "role": ta.role_for(access_total)}


async def create_member(*, client_id: str, actor: Dict[str, Any], name: Any, login: Any, password: Any,
                        preset: Any, view_all: Any, access_total: Any, codes: Optional[Iterable[str]]) -> Dict[str, Any]:
    email, username = login_email(login)
    safe_name = _text(name)[:120]
    secret = validate_password(password, password)
    safe_preset = _preset(preset)
    total, see_all = bool(access_total), bool(view_all)
    wanted = set(codes) if codes is not None else ta.base_codes(safe_preset)
    effective = ta.resolve_codes(status="active", preset=safe_preset, view_all=see_all, access_total=total,
                                 overrides=ta.overrides_for(safe_preset, see_all, wanted))
    _check_grant(actor, access_total=total, codes=effective)

    existing = await find_auth_user_by_email(email)
    created_now = False
    if existing:
        if username:
            raise AccessError("TEAM_USERNAME_TAKEN", "Este usuário já existe. Escolha outro nome.", status_code=409)
        user_id = _text(existing.get("id"))
        if await _membership(client_id, user_id):
            raise AccessError("ACCESS_ALREADY_EXISTS", "Este e-mail já tem acesso a esta empresa.", status_code=409)
        if await _holds_global_role(user_id):
            raise AccessError("ACCESS_ROLE_NOT_ALLOWED", "Contas da equipe Mugô não são administradas nesta tela.",
                              status_code=403)
    else:
        created = await _create_auth_user(email=email, password=secret, name=safe_name)
        user_id = _text(created.get("id"))
        created_now = True

    try:
        await sb_insert("client_memberships", {"user_id": user_id, "client_id": client_id, "status": "active",
                                               "username": username, **_permission_fields(safe_preset, see_all, total)},
                        returning="minimal")
        await _save_overrides(client_id, user_id, ta.overrides_for(safe_preset, see_all, wanted))
    except Exception as exc:  # noqa: BLE001
        print(f"[team][create] client_id={client_id} stage=membership error_type={type(exc).__name__}")
        if created_now:
            await _delete_auth_user(user_id)
        raise AccessError("ACCESS_MEMBERSHIP_FAILED", "A conta não pôde ser vinculada à empresa. Tente novamente.",
                          status_code=502) from None
    if not created_now:
        await _admin_request("PUT", f"/users/{user_id}", json={"password": secret, "email_confirm": True})
    ta.invalidate(client_id, user_id)
    print(f"[team][create] client_id={client_id} actor={actor['user_id']} preset={safe_preset} status=ok")
    return {"ok": True, "user_id": user_id, "login": display_login(email, username), "account_created": created_now}


async def _target(client_id: str, actor: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    if _text(user_id) == actor["user_id"]:
        raise AccessError("TEAM_SELF_EDIT", "Você não pode alterar o seu próprio acesso.", status_code=403)
    rows = await _members(client_id, _text(user_id))
    if not rows:
        raise AccessError("ACCESS_NOT_FOUND", "Este usuário não tem acesso a esta empresa.", status_code=404)
    row = rows[0]
    if _text(row.get("role")).lower() in (*GLOBAL_ROLES, "account_manager"):
        raise AccessError("ACCESS_ROLE_NOT_ALLOWED", "Contas da equipe Mugô não são administradas nesta tela.",
                          status_code=403)
    if not actor["team"] and not actor["access_total"] and bool(row.get("access_total")):
        raise AccessError("TEAM_GRANT_NOT_ALLOWED", "Só quem tem acesso total altera um administrador.", status_code=403)
    return row


async def update_permissions(*, client_id: str, actor: Dict[str, Any], user_id: str, preset: Any, view_all: Any,
                             access_total: Any, codes: Optional[Iterable[str]]) -> Dict[str, Any]:
    await _target(client_id, actor, user_id)
    safe_preset = _preset(preset)
    total, see_all = bool(access_total), bool(view_all)
    wanted = set(codes) if codes is not None else ta.base_codes(safe_preset)
    overrides = ta.overrides_for(safe_preset, see_all, wanted)
    effective = ta.resolve_codes(status="active", preset=safe_preset, view_all=see_all, access_total=total, overrides=overrides)
    _check_grant(actor, access_total=total, codes=effective)
    await sb_update("client_memberships", filters={"client_id": f"eq.{client_id}", "user_id": f"eq.{user_id}"},
                    patch=_permission_fields(safe_preset, see_all, total))
    await _save_overrides(client_id, user_id, overrides)
    ta.invalidate(client_id, user_id)
    print(f"[team][permissions] client_id={client_id} actor={actor['user_id']} preset={safe_preset} status=ok")
    return {"ok": True, "user_id": user_id, "codes": sorted(effective)}


async def set_status(*, client_id: str, actor: Dict[str, Any], user_id: str, status: Any) -> Dict[str, Any]:
    await _target(client_id, actor, user_id)
    value = _text(status).lower()
    if value not in ("active", "inactive"):
        raise AccessError("TEAM_STATUS_INVALID", "Status inválido.")
    await sb_update("client_memberships", filters={"client_id": f"eq.{client_id}", "user_id": f"eq.{user_id}"},
                    patch={"status": value})
    ta.invalidate(client_id, user_id)
    print(f"[team][status] client_id={client_id} actor={actor['user_id']} status={value}")
    return {"ok": True, "user_id": user_id, "status": value}


async def reset_password(*, client_id: str, actor: Dict[str, Any], user_id: str, password: Any) -> Dict[str, Any]:
    await _target(client_id, actor, user_id)
    secret = validate_password(password, password)
    await _admin_request("PUT", f"/users/{_text(user_id)}", json={"password": secret})
    print(f"[team][reset_password] client_id={client_id} actor={actor['user_id']} status=ok")
    return {"ok": True, "user_id": user_id}


async def remove_member(*, client_id: str, actor: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    await _target(client_id, actor, user_id)
    await sb_delete("client_member_permissions", filters={"client_id": f"eq.{client_id}", "user_id": f"eq.{user_id}"},
                    returning="minimal")
    await sb_delete("client_memberships", filters={"client_id": f"eq.{client_id}", "user_id": f"eq.{user_id}"})
    ta.invalidate(client_id, user_id)
    print(f"[team][remove] client_id={client_id} actor={actor['user_id']} status=ok")
    return {"ok": True, "user_id": user_id, "account_preserved": True}
