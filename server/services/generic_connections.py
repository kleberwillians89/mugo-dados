from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from .crypto import decrypt_secret, encrypt_secret
from .ig_supabase import sb_insert, sb_select, sb_update
from .runtime_cache import invalidate_namespace


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_connection(row: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {
        "id", "client_id", "provider", "status", "account_id", "account_name",
        "token_expires_at", "last_sync_at", "next_sync_at", "historical_start",
        "historical_end", "last_error", "metadata", "created_at", "updated_at",
        "external_key", "scopes", "disconnected_at",
    }
    sanitized = {key: row.get(key) for key in allowed}
    if str(row.get("provider") or "") in {"ga4", "google_ads"}:
        sanitized["capabilities"] = google_capabilities(row)
    return sanitized


def google_capabilities(row: Dict[str, Any]) -> Dict[str, Any]:
    scopes = {
        str(scope or "").strip().lower()
        for scope in (row.get("scopes") or [])
        if str(scope or "").strip()
    }
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    has_ga4_scope = any(scope.endswith("/analytics.readonly") for scope in scopes)
    has_ads_scope = any(scope.endswith("/adwords") for scope in scopes)
    ga4_property_id = str(metadata.get("ga4_property_id") or "").strip()
    ads_customer_id = str(metadata.get("google_ads_customer_id") or "").strip()
    return {
        "ga4_authorized": has_ga4_scope,
        "ga4_configured": has_ga4_scope and bool(ga4_property_id),
        "ga4_status": (
            "connected"
            if has_ga4_scope and ga4_property_id
            else "property_required"
            if has_ga4_scope
            else "authorization_required"
        ),
        "ads_authorized": has_ads_scope,
        "ads_configured": has_ads_scope and bool(ads_customer_id),
        "ads_status": (
            "connected"
            if has_ads_scope and ads_customer_id
            else "account_required"
            if has_ads_scope
            else "not_connected"
        ),
    }


async def list_generic_connections(client_id: str) -> List[Dict[str, Any]]:
    rows = await sb_select(
        "integration_connections",
        filters={"client_id": f"eq.{client_id}"},
        order="updated_at.desc",
        limit=100,
    )
    return [sanitize_connection(row) for row in rows]


async def get_connection(client_id: str, connection_id: str, *, include_token: bool = False) -> Dict[str, Any]:
    rows = await sb_select(
        "integration_connections",
        filters={"client_id": f"eq.{client_id}", "id": f"eq.{connection_id}"},
        limit=1,
    )
    if not rows:
        raise RuntimeError("Conexão não encontrada para esta empresa.")
    row = rows[0]
    if include_token:
        encrypted = str(row.get("encrypted_token") or "").strip()
        row["_token"] = decrypt_secret(encrypted) if encrypted else ""
    return row


async def upsert_connection(
    *,
    client_id: str,
    provider: str,
    external_key: str,
    token_payload: str,
    user_id: str,
    status: str,
    account_id: str | None = None,
    account_name: str | None = None,
    token_expires_at: str | None = None,
    scopes: List[str] | None = None,
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    rows = await sb_select(
        "integration_connections",
        filters={
            "client_id": f"eq.{client_id}",
            "provider": f"eq.{provider}",
            "external_key": f"eq.{external_key}",
        },
        limit=1,
    )
    patch = {
        "status": status,
        "account_id": account_id,
        "account_name": account_name,
        "external_key": external_key,
        "encrypted_token": encrypt_secret(token_payload),
        "token_expires_at": token_expires_at,
        "scopes": scopes or [],
        "metadata": metadata or {},
        "connected_by": user_id,
        "disconnected_at": None,
        "last_error": None,
        "updated_at": _iso_now(),
    }
    if rows:
        updated = await sb_update(
            "integration_connections",
            filters={"id": f"eq.{rows[0]['id']}", "client_id": f"eq.{client_id}"},
            patch=patch,
            returning="representation",
        )
        result = updated[0] if updated else {**rows[0], **patch}
    else:
        result = await sb_insert(
            "integration_connections",
            {"client_id": client_id, "provider": provider, **patch},
            returning="representation",
        ) or {"client_id": client_id, "provider": provider, **patch}
    await audit_connection(
        client_id=client_id,
        connection_id=str(result.get("id") or "") or None,
        user_id=user_id,
        event_type="connected",
        details={"provider": provider, "external_key": external_key},
    )
    await invalidate_namespace("integration_connections")
    return sanitize_connection(result)


async def disconnect_generic_connection(client_id: str, connection_id: str, user_id: str) -> Dict[str, Any]:
    updated = await sb_update(
        "integration_connections",
        filters={"id": f"eq.{connection_id}", "client_id": f"eq.{client_id}"},
        patch={"status": "disconnected", "disconnected_at": _iso_now(), "updated_at": _iso_now()},
        returning="representation",
    )
    if not updated:
        raise RuntimeError("Conexão não encontrada para esta empresa.")
    await audit_connection(
        client_id=client_id,
        connection_id=connection_id,
        user_id=user_id,
        event_type="disconnected",
        details={"provider": updated[0].get("provider")},
    )
    await invalidate_namespace("integration_connections")
    return sanitize_connection(updated[0])


async def update_connection_selection(
    *,
    client_id: str,
    connection_id: str,
    user_id: str,
    metadata_patch: Dict[str, Any],
) -> Dict[str, Any]:
    row = await get_connection(client_id, connection_id)
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    metadata = {**metadata, **metadata_patch}
    updated = await sb_update(
        "integration_connections",
        filters={"id": f"eq.{connection_id}", "client_id": f"eq.{client_id}"},
        patch={"metadata": metadata, "status": "connected", "updated_at": _iso_now()},
        returning="representation",
    )
    if not updated:
        raise RuntimeError("Conexão não encontrada para esta empresa.")
    await audit_connection(
        client_id=client_id,
        connection_id=connection_id,
        user_id=user_id,
        event_type="account_selected",
        details={"fields": sorted(metadata_patch.keys())},
    )
    await invalidate_namespace("integration_connections")
    return sanitize_connection(updated[0])


async def audit_connection(
    *,
    client_id: str,
    connection_id: str | None,
    user_id: str | None,
    event_type: str,
    details: Dict[str, Any] | None = None,
) -> None:
    await sb_insert(
        "connection_audit_events",
        {
            "client_id": client_id,
            "connection_id": connection_id or None,
            "user_id": user_id or None,
            "event_type": event_type,
            "details": details or {},
        },
        returning="minimal",
    )
