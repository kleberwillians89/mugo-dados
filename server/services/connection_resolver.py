from __future__ import annotations

from typing import Any, Dict, Optional

from .ig_supabase import sb_select


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _normalize_ad_account_id(value: Any) -> str:
    raw = _safe_str(value)
    if not raw:
        return ""
    return raw if raw.startswith("act_") else f"act_{raw}"


def _is_status_active_like(row: Dict[str, Any]) -> bool:
    status = _safe_str(row.get("status")).lower()
    requires_reauth = _safe_str(row.get("requires_reauth")).lower() in {"true", "1", "yes", "on"}
    is_active = _safe_str(row.get("is_active")).lower()
    if is_active in {"false", "0", "no", "off"}:
        return False
    return status in {"active", "connected", "ok"} and not requires_reauth


def _is_connection_type_compatible(
    *,
    expected: str | None,
    actual: str | None,
    platform: str | None = None,
) -> bool:
    exp = _safe_str(expected).lower()
    act = _safe_str(actual).lower()
    plat = _safe_str(platform).lower()

    if not exp:
        return True
    if act == exp:
        return True

    # Compat com conexões legadas sem connection_type consistente.
    if plat == "meta_ads" and exp == "paid" and act in {"", "organic"}:
        return True
    if plat == "instagram" and exp == "organic" and act in {""}:
        return True
    return False


def _pick_best_connection(rows: list[Dict[str, Any]]) -> tuple[Optional[Dict[str, Any]], str]:
    if not rows:
        return None, "none"

    active_like = [r for r in rows if _is_status_active_like(r)]
    if active_like:
        return active_like[0], "active"

    non_disconnected = [r for r in rows if _safe_str(r.get("status")).lower() != "disconnected"]
    if non_disconnected:
        return non_disconnected[0], "latest_non_disconnected"

    return rows[0], "latest_any"


async def resolve_connection_for_scope(
    *,
    client_id: str,
    platform: str | None = None,
    connection_type: str | None = None,
    requested_connection_id: str | None = None,
    require_ad_account: bool = False,
) -> Dict[str, Any]:
    cid = _safe_str(client_id)
    requested = _safe_str(requested_connection_id)
    if not cid:
        raise RuntimeError("client_id é obrigatório")

    select_fields = (
        "id,client_id,platform,connection_type,status,ig_user_id,ad_account_id,"
        "ad_account_name,requires_reauth,is_active,last_sync_at,last_synced_at,"
        "last_sync_status,last_error,updated_at"
    )

    def _matches_scope(row: Dict[str, Any]) -> bool:
        if platform and _safe_str(row.get("platform")).lower() != _safe_str(platform).lower():
            return False
        if not _is_connection_type_compatible(
            expected=connection_type,
            actual=row.get("connection_type"),
            platform=row.get("platform"),
        ):
            return False
        if require_ad_account and not _normalize_ad_account_id(row.get("ad_account_id")):
            return False
        return True

    if requested:
        rows = await sb_select(
            "meta_connections",
            select=select_fields,
            filters={"id": f"eq.{requested}", "client_id": f"eq.{cid}"},
            limit=1,
        )
        if not rows:
            raise RuntimeError("connection_id informada não encontrada para este client_id.")
        selected = rows[0]
        if not _matches_scope(selected):
            raise RuntimeError(
                "connection_id informada não é compatível com o escopo solicitado "
                f"(platform={_safe_str(platform) or '-'} connection_type={_safe_str(connection_type) or '-'})."
            )
        return {
            "resolved": True,
            "connection_id": _safe_str(selected.get("id")),
            "source": "explicit",
            "row": selected,
        }

    filters = {"client_id": f"eq.{cid}"}
    if platform:
        filters["platform"] = f"eq.{_safe_str(platform)}"

    rows = await sb_select(
        "meta_connections",
        select=select_fields,
        filters=filters,
        order="updated_at.desc",
        limit=200,
    )
    scoped_rows = [row for row in rows if _matches_scope(row)]
    selected, source = _pick_best_connection(scoped_rows)
    if not selected:
        return {
            "resolved": False,
            "connection_id": None,
            "source": "none",
            "row": None,
        }
    return {
        "resolved": True,
        "connection_id": _safe_str(selected.get("id")),
        "source": source,
        "row": selected,
    }
