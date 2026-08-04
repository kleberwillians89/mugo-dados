from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional

from .crypto import decrypt_secret
from .ig_supabase import sb_select
from .integration_errors import IntegrationError


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


_GENERIC_ALLOWED_STATUSES = {"connected", "selection_required"}


async def resolve_generic_connection(
    *,
    client_id: str,
    provider: str,
    requested_connection_id: str | None = None,
    capability: str | None = None,
    prefer_metadata_flag: str | None = None,
    required_asset: str | None = None,
    require_token: bool = True,
    select_fn: Callable[..., Awaitable[list[Dict[str, Any]]]] | None = None,
    candidate_rows: list[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Resolve an OAuth/catalog connection without a silent fallback.

    The returned row is tenant/provider/status validated. Tokens are decrypted
    only for the caller and must never be serialized or logged.
    """
    cid = _safe_str(client_id)
    expected_provider = _safe_str(provider).lower()
    requested = _safe_str(requested_connection_id)
    if not cid or not expected_provider:
        raise IntegrationError(
            "Empresa e provedor são obrigatórios para resolver a conexão.",
            status_code=400, code="CONNECTION_NOT_FOUND", provider="integration",
        )

    select = select_fn or sb_select
    if candidate_rows is not None:
        candidates = list(candidate_rows)
        if requested and not candidates:
            raise IntegrationError(
                "Conexão não encontrada.", status_code=404,
                code="CONNECTION_NOT_FOUND", provider=expected_provider,
            )
    elif requested:
        rows = await select(
            "integration_connections",
            filters={"id": f"eq.{requested}"},
            limit=2,
        )
        if not rows:
            raise IntegrationError(
                "Conexão não encontrada.", status_code=404,
                code="CONNECTION_NOT_FOUND", provider=expected_provider,
            )
        row = rows[0]
        if _safe_str(row.get("client_id")) != cid:
            raise IntegrationError(
                "A conexão pertence a outra empresa.", status_code=403,
                code="CONNECTION_TENANT_MISMATCH", provider=expected_provider,
            )
        if _safe_str(row.get("provider")).lower() != expected_provider:
            raise IntegrationError(
                "A conexão pertence a outro provedor.", status_code=409,
                code="CONNECTION_PROVIDER_MISMATCH", provider=expected_provider,
            )
        candidates = [row]
    else:
        candidates = await select(
            "integration_connections",
            filters={"client_id": f"eq.{cid}", "provider": f"eq.{expected_provider}"},
            order="updated_at.desc",
            limit=200,
        )

    connected: list[Dict[str, Any]] = []
    disconnected_seen = False
    tenant_mismatch_seen = False
    provider_mismatch_seen = False
    for row in candidates:
        row_client = _safe_str(row.get("client_id"))
        row_provider = _safe_str(row.get("provider")).lower()
        if row_client != cid:
            if requested:
                raise IntegrationError(
                    "A conexão pertence a outra empresa.", status_code=403,
                    code="CONNECTION_TENANT_MISMATCH", provider=expected_provider,
                )
            tenant_mismatch_seen = True
            continue
        if row_provider != expected_provider:
            if requested:
                raise IntegrationError(
                    "A conexão pertence a outro provedor.", status_code=409,
                    code="CONNECTION_PROVIDER_MISMATCH", provider=expected_provider,
                )
            provider_mismatch_seen = True
            continue
        status = _safe_str(row.get("status")).lower()
        disconnected = bool(_safe_str(row.get("disconnected_at"))) or status == "disconnected"
        if disconnected:
            disconnected_seen = True
            continue
        if status in _GENERIC_ALLOWED_STATUSES:
            connected.append(row)

    if not connected:
        if tenant_mismatch_seen:
            raise IntegrationError(
                "A conexão pertence a outra empresa.", status_code=403,
                code="CONNECTION_TENANT_MISMATCH", provider=expected_provider,
            )
        if provider_mismatch_seen:
            raise IntegrationError(
                "A conexão pertence a outro provedor.", status_code=409,
                code="CONNECTION_PROVIDER_MISMATCH", provider=expected_provider,
            )
        code = "CONNECTION_DISCONNECTED" if disconnected_seen else "CONNECTION_NOT_FOUND"
        raise IntegrationError(
            "A conexão está desconectada." if disconnected_seen else "Nenhuma conexão ativa foi encontrada.",
            status_code=409 if disconnected_seen else 404, code=code, provider=expected_provider,
        )
    preferred = [
        row for row in connected
        if prefer_metadata_flag
        and isinstance(row.get("metadata"), dict)
        and bool(row["metadata"].get(prefer_metadata_flag))
    ]
    if len(preferred) == 1:
        connected = preferred
    elif len(preferred) > 1:
        raise IntegrationError(
            "Mais de uma conexão está marcada como preferencial.",
            status_code=409, code="CONNECTION_AMBIGUOUS", provider=expected_provider,
        )
    if len(connected) > 1:
        raise IntegrationError(
            "Mais de uma conexão ativa corresponde ao escopo solicitado.",
            status_code=409, code="CONNECTION_AMBIGUOUS", provider=expected_provider,
        )

    row = dict(connected[0])
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    if capability and not bool(metadata.get(capability)):
        raise IntegrationError(
            "A conexão não oferece a capacidade solicitada.", status_code=409,
            code="CONNECTION_CAPABILITY_MISMATCH", provider=expected_provider,
        )
    if required_asset and not _safe_str(metadata.get(required_asset) or row.get(required_asset)):
        raise IntegrationError(
            "A conexão ainda não possui o ativo obrigatório selecionado.", status_code=409,
            code="CONNECTION_ASSET_REQUIRED", provider=expected_provider,
        )
    encrypted = _safe_str(row.get("encrypted_token"))
    if require_token and not encrypted:
        raise IntegrationError(
            "A credencial da conexão não está disponível.", status_code=409,
            code="CONNECTION_TOKEN_UNAVAILABLE", provider=expected_provider,
        )
    if require_token:
        row["_token"] = decrypt_secret(encrypted)
    return row


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
    if len(active_like) == 1:
        return active_like[0], "active"
    if len(active_like) > 1:
        raise IntegrationError(
            "Mais de uma conexão ativa corresponde ao escopo solicitado.",
            status_code=409, code="CONNECTION_AMBIGUOUS", provider="integration",
        )

    non_disconnected = [r for r in rows if _safe_str(r.get("status")).lower() != "disconnected"]
    if len(non_disconnected) == 1:
        return non_disconnected[0], "latest_non_disconnected"
    if len(non_disconnected) > 1:
        raise IntegrationError(
            "Mais de uma conexão utilizável corresponde ao escopo solicitado.",
            status_code=409, code="CONNECTION_AMBIGUOUS", provider="integration",
        )

    return None, "none"


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
