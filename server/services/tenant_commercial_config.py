"""Persistência administrativa comercial por tenant. Não participa de guardas de acesso."""
from __future__ import annotations

from typing import Any

import httpx

from .commercial_modules import BASIC_CAPABILITIES, COMMERCIAL_MODULES
from .ig_supabase import sb_rpc, sb_select

TABLE = "tenant_commercial_modules"


class CommercialConfigError(ValueError):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def validate_selection(value: Any) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        raise CommercialConfigError("invalid_module_keys")
    # Aliases such as "redacao" are deliberately rejected on write.
    if len(value) != len(set(value)) or any(x not in COMMERCIAL_MODULES for x in value):
        raise CommercialConfigError("invalid_module_keys")
    return sorted(value)


def as_state(client_id: str, row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {
            "client_id": client_id, "state": "not_configured", "configured": False,
            "module_keys": None, "version": None, "updated_at": None,
            "basic_capabilities": sorted(BASIC_CAPABILITIES),
        }
    modules = validate_selection(row["module_keys"])
    return {
        "client_id": client_id,
        "state": "selected" if modules else "explicitly_empty",
        "configured": True,
        "module_keys": modules, "version": row["version"],
        "updated_at": row.get("updated_at"),
        "basic_capabilities": sorted(BASIC_CAPABILITIES),
    }


async def get_configuration(client_id: str) -> dict[str, Any]:
    rows = await sb_select(
        TABLE, select="client_id,module_keys,version,updated_at",
        filters={"client_id": f"eq.{client_id}"}, limit=1,
    )
    return as_state(client_id, rows[0] if rows else None)


async def save_configuration(
    client_id: str, module_keys: Any, *, expected_version: int | None,
    actor_user_id: str,
) -> dict[str, Any]:
    normalized = validate_selection(module_keys)
    if expected_version is not None and (
        type(expected_version) is not int or expected_version < 1
    ):
        raise CommercialConfigError("invalid_expected_version")
    if not actor_user_id or not client_id:
        raise CommercialConfigError("invalid_configuration")
    try:
        row = await sb_rpc("save_tenant_commercial_modules", {
            "p_client_id": client_id,
            "p_module_keys": normalized,
            "p_expected_version": expected_version,
            "p_actor_user_id": actor_user_id,
        })
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text if exc.response is not None else ""
        if "commercial_config_conflict" in detail:
            raise CommercialConfigError("commercial_config_conflict", 409) from exc
        if "commercial_client_not_found" in detail:
            raise CommercialConfigError("commercial_client_not_found", 404) from exc
        if "commercial_admin_required" in detail:
            raise CommercialConfigError("commercial_admin_required", 403) from exc
        if "commercial_modules_invalid" in detail:
            raise CommercialConfigError("invalid_module_keys", 400) from exc
        raise
    if not isinstance(row, dict) or row.get("client_id") != client_id:
        raise RuntimeError("commercial_config_write_unconfirmed")
    return as_state(client_id, row)


def catalog() -> list[dict[str, str]]:
    return [{"key": key, "label": item.label} for key, item in COMMERCIAL_MODULES.items()]
