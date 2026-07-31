from typing import Optional, Dict, Any, List

from fastapi import HTTPException

from .auth import get_user_id_from_bearer
from .ig_supabase import sb_get_client_id_for_user, sb_get_client_memberships, sb_get_connection_for_client
import os


def _is_true(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _local_dev_user_id() -> str:
    return (os.getenv("DEV_USER_ID") or "").strip() or "local-dev-user"


async def require_user_id(authorization: Optional[str]) -> str:
    user_id = await get_user_id_from_bearer(authorization)
    if user_id:
        return user_id

    # Modo local/dev: permite usar API sem JWT
    if _is_true(os.getenv("ALLOW_NO_AUTH", "")):
        dev_user_id = _local_dev_user_id()
        print(
            "[tenant][auth_bypass] "
            f"allow_no_auth=1 reason=missing_or_invalid_bearer user_id={dev_user_id}"
        )
        return dev_user_id

    if not user_id:
        raise HTTPException(status_code=401, detail="Autenticação obrigatória")
    return user_id


async def resolve_client_id(client_id: Optional[str], authorization: Optional[str]) -> str:
    """
    Resolve tenant do request usando somente membership.
    Sem fallback de DEFAULT_CLIENT_ID.
    """
    user_id = await require_user_id(authorization)
    requested = (client_id or "").strip() or "-"
    from .platform_admin import is_platform_admin
    from .ig_supabase import sb_select
    if await is_platform_admin(user_id):
        explicit_client_id = (client_id or "").strip()
        if not explicit_client_id:
            raise HTTPException(
                status_code=400,
                detail="Selecione explicitamente uma empresa para o suporte administrativo.",
            )
        rows = await sb_select(
            "clients", select="id", filters={"id": f"eq.{explicit_client_id}"}, limit=1
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Empresa selecionada não existe.")
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


async def require_client_role(
    client_id: Optional[str],
    authorization: Optional[str],
    allowed_roles: tuple[str, ...] = ("agency_admin", "client_admin"),
) -> str:
    user_id = await require_user_id(authorization)
    resolved = await resolve_client_id(client_id, authorization)
    from .platform_admin import is_platform_admin
    if await is_platform_admin(user_id):
        return resolved
    memberships = await sb_get_client_memberships(user_id)
    membership = next(
        (row for row in memberships if str(row.get("client_id") or "").strip() == resolved),
        None,
    )
    role = str((membership or {}).get("role") or "").strip()
    legacy_role = {"owner": "client_admin", "admin": "client_admin"}.get(role, role)
    if legacy_role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Perfil sem permissão para alterar esta empresa.")
    return resolved


async def require_client_read(
    client_id: Optional[str],
    authorization: Optional[str],
) -> str:
    """
    Autoriza leitura tenant-scoped.

    Membership válida (inclusive viewer) ou platform_admin com tenant explícito
    resolvido por resolve_client_id. Não confere papel de mutação.
    """
    return await resolve_client_id(client_id, authorization)


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
    user_id = await require_user_id(authorization)
    return await sb_get_client_memberships(user_id)


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
