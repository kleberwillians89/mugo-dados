from contextvars import ContextVar
from typing import Optional, Dict, Any, List

from fastapi import HTTPException

from .auth import get_user_id_from_bearer
from .ig_supabase import sb_get_client_id_for_user, sb_get_client_membership_roles as sb_get_client_memberships, sb_get_connection_for_client
from .request_performance import measured
import os


def _is_true(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _local_dev_user_id() -> str:
    return (os.getenv("DEV_USER_ID") or "").strip() or "local-dev-user"


async def require_user_id(authorization: Optional[str]) -> str:
    user_id = await get_user_id_from_bearer(authorization)
    if user_id:
        return user_id

    # Modo local/dev: permite usar API sem JWT. Nunca em produção, mesmo que
    # ALLOW_NO_AUTH seja setado por engano — mesmo guard já usado para
    # ALLOW_UNVERIFIED_JWT_DEV em auth.py.
    environment = (os.getenv("APP_ENV") or "").strip().lower()
    if _is_true(os.getenv("ALLOW_NO_AUTH", "")) and environment not in {"production", "prod"}:
        dev_user_id = _local_dev_user_id()
        print(
            "[tenant][auth_bypass] "
            f"allow_no_auth=1 reason=missing_or_invalid_bearer user_id={dev_user_id}"
        )
        return dev_user_id

    if not user_id:
        raise HTTPException(status_code=401, detail="Autenticação obrigatória")
    return user_id


async def _has_agency_admin_membership(user_id: str) -> bool:
    """
    True quando o usuário possui papel agency_admin em QUALQUER empresa —
    equipe da agência não deve precisar de membership por cliente para
    acessar empresas autorizadas, diferente de client_admin/viewer.
    """
    memberships = await sb_get_client_memberships(user_id)
    return any(str(row.get("role") or "").strip() == "agency_admin" for row in memberships)


@measured("tenant", memo=True)
async def resolve_client_id(client_id: Optional[str], authorization: Optional[str]) -> str:
    """
    Resolve tenant do request usando somente membership.
    Sem fallback de DEFAULT_CLIENT_ID.
    """
    user_id = await require_user_id(authorization)
    requested = (client_id or "").strip() or "-"
    from .platform_admin import is_platform_admin
    from .ig_supabase import sb_select
    if await is_platform_admin(user_id) or await _has_agency_admin_membership(user_id):
        explicit_client_id = (client_id or "").strip()
        if not explicit_client_id:
            raise HTTPException(
                status_code=400,
                detail="Selecione explicitamente uma empresa para o suporte administrativo.",
            )
        if not _client_known(explicit_client_id):
            rows = await sb_select(
                "clients", select="id", filters={"id": f"eq.{explicit_client_id}"}, limit=1
            )
            if not rows:
                raise HTTPException(status_code=404, detail="Empresa selecionada não existe.")
            _remember_client(explicit_client_id)
        print(
            f"[tenant] user_id={user_id} requested_client_id={requested} "
            f"resolved_client_id={explicit_client_id} source=platform_support_explicit"
        )
        return explicit_client_id
    try:
        resolved = await sb_get_client_id_for_user(user_id, requested_client_id=client_id)
        source = "explicit" if (client_id or "").strip() else "default_single_membership"
        print(
            f"[tenant] user_id={user_id} requested_client_id={requested} "
            f"resolved_client_id={resolved} source={source}"
        )
        return resolved
    except PermissionError as exc:
        print(f"[tenant] denied user_id={user_id} requested_client_id={requested}")
        raise HTTPException(status_code=403, detail=str(exc)) from exc


# Empresa que existe continua existindo: a confirmação vale 60 s no processo
# (suporte administrativo consultava `clients` a cada chamada da tela).
_CLIENT_EXISTS_SECONDS = 60
_known_clients: dict = {}


def _client_known(client_id: str) -> bool:
    import time
    expires_at = _known_clients.get(client_id)
    if expires_at and time.monotonic() < expires_at:
        return True
    _known_clients.pop(client_id, None)
    return False


def _remember_client(client_id: str) -> None:
    import time
    if len(_known_clients) > 5000:
        _known_clients.clear()
    _known_clients[client_id] = time.monotonic() + _CLIENT_EXISTS_SECONDS


async def require_user_client_access(user_id: str, client_id: str, *, fresh: bool = False) -> str:
    """Valida o tenant persistido em states OAuth, inclusive para platform_admin."""
    from .platform_admin import is_platform_admin
    from .ig_supabase import sb_select

    uid = str(user_id or "").strip()
    cid = str(client_id or "").strip()
    if not uid or not cid:
        raise PermissionError("State OAuth sem usuário ou empresa.")
    platform_access = await is_platform_admin(uid, fresh=True) if fresh else await is_platform_admin(uid)
    if platform_access or await _has_agency_admin_membership(uid):
        rows = await sb_select(
            "clients",
            select="id",
            filters={"id": f"eq.{cid}"},
            limit=1,
        )
        if not rows:
            raise PermissionError("Empresa selecionada não existe.")
        return cid
    return await sb_get_client_id_for_user(uid, requested_client_id=cid)


@measured("authorization")
async def is_agency_user(authorization: Optional[str], client_id: Optional[str] = None) -> bool:
    """Equipe Mugô (platform_admin ou agency_admin). Decide o que só a agência vê/faz no Studio.

    "Gestora da conta" (account_manager) conta como equipe Mugô só na empresa onde tem esse papel:
    a empresa vem do argumento ou da que esta requisição já autorizou (require_client_role/read).
    """
    user_id = await require_user_id(authorization)
    from .platform_admin import is_platform_admin
    if await is_platform_admin(user_id) or await _has_agency_admin_membership(user_id):
        return True
    cid = str(client_id or _REQUEST_CLIENT.get() or "").strip()
    return bool(cid) and await _client_role(user_id, cid) == ACCOUNT_MANAGER


ACCOUNT_MANAGER = "account_manager"
# Empresa já autorizada nesta requisição (cada requisição roda no seu próprio contexto).
_REQUEST_CLIENT: ContextVar[Optional[str]] = ContextVar("mugo_request_client", default=None)


async def _client_role(user_id: str, client_id: str) -> str:
    memberships = await sb_get_client_memberships(user_id)
    row = next((r for r in memberships if str(r.get("client_id") or "").strip() == client_id), None)
    return str((row or {}).get("role") or "").strip()


async def require_client_role(
    client_id: Optional[str],
    authorization: Optional[str],
    allowed_roles: tuple[str, ...] = ("agency_admin", "client_admin"),
) -> str:
    user_id = await require_user_id(authorization)
    resolved = await resolve_client_id(client_id, authorization)
    from .platform_admin import is_platform_admin
    _REQUEST_CLIENT.set(resolved)
    if await is_platform_admin(user_id) or await _has_agency_admin_membership(user_id):
        return resolved
    role = await _client_role(user_id, resolved)
    # Gestora da conta age como equipe Mugô, mas só nesta empresa.
    legacy_role = {"owner": "client_admin", "admin": "client_admin", ACCOUNT_MANAGER: "agency_admin"}.get(role, role)
    role_ok = legacy_role in allowed_roles or (role == ACCOUNT_MANAGER and "client_admin" in allowed_roles)
    # Rota fora de módulo que o papel já recusa: recusa antes de ler o banco.
    from .team_access import current_requirement
    if not role_ok and not current_requirement():
        raise HTTPException(status_code=403, detail="Perfil sem permissão para alterar esta empresa.")
    if role != ACCOUNT_MANAGER:
        granted = await _module_check(resolved, user_id, role=role, member_route=_viewer_allowed(allowed_roles))
        # Permissão do módulo (ex.: creators.edit) libera a rota que o admin do cliente poderia usar,
        # mesmo com papel viewer. Rota só da equipe Mugô continua só da equipe.
        if granted and "client_admin" in allowed_roles:
            return resolved
    if not role_ok:
        raise HTTPException(status_code=403, detail="Perfil sem permissão para alterar esta empresa.")
    return resolved


def _viewer_allowed(allowed_roles: tuple[str, ...]) -> bool:
    return "viewer" in allowed_roles


async def _module_check(client_id: str, user_id: str, *, role: str, member_route: bool) -> bool:
    """Equipe e acessos (team_access): inativo é recusado; rota de módulo exige o código do módulo.

    Devolve True quando a rota pertence a um módulo e o membro tem o código exigido; False quando a rota
    não é de módulo (vale só o papel). ``member_route``: a rota já era aberta a qualquer membro (viewer),
    então basta ver o módulo."""
    from .team_access import current_requirement, denied_message, member_access
    access = await member_access(client_id, user_id, role=role)
    if access is None:
        return False
    if access["status"] != "active":
        raise HTTPException(status_code=403, detail="Seu usuário está desativado nesta empresa. Fale com o administrador.")
    requirement = current_requirement()
    if not requirement:
        return False
    module, code = requirement
    if member_route and code.endswith(".edit"):
        code = f"{module}.view"
    if code not in access["codes"]:
        raise HTTPException(status_code=403, detail=denied_message(code))
    return True


async def require_client_read(
    client_id: Optional[str],
    authorization: Optional[str],
) -> str:
    """
    Autoriza leitura tenant-scoped.

    Membership válida (inclusive viewer) ou platform_admin com tenant explícito
    resolvido por resolve_client_id. Não confere papel de mutação.
    """
    resolved = await resolve_client_id(client_id, authorization)
    _REQUEST_CLIENT.set(resolved)
    try:
        user_id = await require_user_id(authorization)
        from .platform_admin import is_platform_admin
        if not (await is_platform_admin(user_id) or await _has_agency_admin_membership(user_id)):
            role = await _client_role(user_id, resolved)
            if role != ACCOUNT_MANAGER:
                await _module_check(resolved, user_id, role=role, member_route=True)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — autorização indisponível nunca concede acesso
        print(f"[tenant][module_check] client_id={resolved} status=failed error_type={type(exc).__name__}")
        raise HTTPException(
            status_code=503,
            detail="Não foi possível verificar sua permissão agora. Tente novamente.",
        ) from exc
    return resolved


async def require_client_manage(
    client_id: Optional[str],
    authorization: Optional[str],
) -> str:
    """Autoriza mutações da empresa para owner/admin ou platform_admin."""
    return await require_client_role(
        client_id,
        authorization,
        allowed_roles=("agency_admin", "client_admin"),
    )


async def get_client_role(client_id: str, authorization: Optional[str]) -> str:
    user_id = await require_user_id(authorization)
    resolved = await resolve_client_id(client_id, authorization)
    from .platform_admin import is_platform_admin
    if await is_platform_admin(user_id):
        return "platform_admin"
    if await _has_agency_admin_membership(user_id):
        return "agency_admin"
    memberships = await sb_get_client_memberships(user_id)
    membership = next(
        (row for row in memberships if str(row.get("client_id") or "").strip() == resolved),
        None,
    )
    return {"owner": "client_admin", "admin": "client_admin"}.get(
        str((membership or {}).get("role") or "").strip(),
        str((membership or {}).get("role") or "").strip(),
    )


async def require_agency_admin(authorization: Optional[str]) -> str:
    user_id = await require_user_id(authorization)
    memberships = await sb_get_client_memberships(user_id)
    if not any(str(row.get("role") or "").strip() == "agency_admin" for row in memberships):
        raise HTTPException(status_code=403, detail="Apenas administradores da agência podem criar empresas.")
    return user_id


async def list_memberships_from_auth(authorization: Optional[str]) -> List[Dict[str, Any]]:
    from .ig_supabase import sb_get_client_memberships as hydrated_memberships
    user_id = await require_user_id(authorization)
    return await hydrated_memberships(user_id)


@measured("connection_validation", memo=True)
async def resolve_connection_id(
    connection_id: Optional[str],
    *,
    client_id: str,
    authorization: Optional[str],
) -> Optional[str]:
    requested = (connection_id or "").strip()
    cid = (client_id or "").strip()
    if not requested:
        print(
            f"[tenant][connection] user_id={await require_user_id(authorization)} "
            f"client_id={cid or '-'} requested_connection_id=- resolved_connection_id=- source=none"
        )
        return None
    if not cid:
        raise HTTPException(status_code=400, detail="client_id é obrigatório para validar connection_id.")

    user_id = await require_user_id(authorization)
    row = await sb_get_connection_for_client(cid, requested)
    if not row:
        print(
            f"[tenant][connection] denied user_id={user_id} client_id={cid} "
            f"requested_connection_id={requested} reason=connection_not_in_client_scope"
        )
        raise HTTPException(
            status_code=403,
            detail="connection_id não pertence ao client_id autenticado.",
        )

    resolved = str(row.get("id") or "").strip()
    print(
        f"[tenant][connection] user_id={user_id} client_id={cid} "
        f"requested_connection_id={requested} resolved_connection_id={resolved or '-'} source=explicit"
    )
    return resolved or None
