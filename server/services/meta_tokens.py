from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import httpx

from .crypto import decrypt_secret, encrypt_secret
from .ig_supabase import sb_get_one, sb_insert, sb_select, sb_update
from .meta_http import MetaApiError, meta_get_json


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    raw = _safe_str(value).lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _refresh_window() -> timedelta:
    raw = _safe_str(_env("META_TOKEN_REFRESH_WINDOW_DAYS"))
    try:
        return timedelta(days=max(1, int(raw or 7)))
    except Exception:
        return timedelta(days=7)


def _disable_token_refresh() -> bool:
    return _safe_bool(_env("META_DISABLE_TOKEN_REFRESH"), False)


def _env_access_token() -> str:
    return _env("META_ACCESS_TOKEN")


def _token_expiry_from_connection(conn: Dict[str, Any]) -> Optional[datetime]:
    return _parse_ts(conn.get("token_expires_at")) or _parse_ts(conn.get("expires_at"))


def _requires_reauth(conn: Dict[str, Any]) -> bool:
    return _safe_bool(conn.get("requires_reauth"), _safe_str(conn.get("status")).lower() == "needs_reauth")


def _is_active(conn: Dict[str, Any]) -> bool:
    status = _safe_str(conn.get("status")).lower()
    default = status != "disconnected"
    return _safe_bool(conn.get("is_active"), default)


def serialize_connection_status(conn: Dict[str, Any]) -> Dict[str, Any]:
    expiry = conn.get("token_expires_at") or conn.get("expires_at")
    last_sync = conn.get("last_sync_at") or conn.get("last_synced_at")
    return {
        "id": _safe_str(conn.get("id")) or None,
        "client_id": _safe_str(conn.get("client_id")) or None,
        "platform": _safe_str(conn.get("platform")),
        "connection_type": _safe_str(conn.get("connection_type")),
        "status": _safe_str(conn.get("status")) or "active",
        "requires_reauth": _requires_reauth(conn),
        "is_active": _is_active(conn),
        "token_expires_at": expiry,
        "expires_at": expiry,
        "token_last_refreshed_at": conn.get("token_last_refreshed_at"),
        "last_validated_at": conn.get("last_validated_at"),
        "last_sync_at": last_sync,
        "last_synced_at": last_sync,
        "last_sync_status": _safe_str(conn.get("last_sync_status")) or "never",
        "last_error": _safe_str(conn.get("last_error")) or None,
        "connected_at": conn.get("connected_at"),
        "updated_at": conn.get("updated_at"),
        "meta_user_id": _safe_str(conn.get("meta_user_id")) or None,
        "ig_user_id": _safe_str(conn.get("ig_user_id")) or None,
        "username": _safe_str(conn.get("username")) or None,
        "business_id": _safe_str(conn.get("business_id")) or None,
        "ad_account_id": _safe_str(conn.get("ad_account_id")) or None,
        "ad_account_name": _safe_str(conn.get("ad_account_name")) or None,
    }


def _token_from_connection(conn: Dict[str, Any]) -> str:
    plain = _safe_str(conn.get("access_token"))
    if plain:
        return plain

    encrypted = _safe_str(conn.get("encrypted_access_token"))
    if encrypted:
        return decrypt_secret(encrypted)

    # Compat com schema legado.
    return ""


def _log_token_source(source: str, *, disable_refresh: bool, connection_id: str = "") -> None:
    print(
        "[meta][token] "
        f"source={source} disable_refresh={str(bool(disable_refresh)).lower()} "
        f"connection_id={connection_id or '-'}"
    )


async def _log_event(client_id: str, event_type: str, ok: bool, details: Dict[str, Any]) -> None:
    safe_details = dict(details or {})
    safe_details.pop("access_token", None)
    safe_details.pop("new_access_token", None)
    try:
        await sb_insert(
            "meta_token_events",
            {
                "client_id": client_id,
                "event_type": event_type,
                "ok": bool(ok),
                "details_json": safe_details,
            },
            returning="minimal",
        )
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return
        print(
            "[meta_tokens][log_event_warn] "
            f"client_id={client_id} event_type={event_type} "
            f"error={exc.__class__.__name__}: {str(exc)[:260]}"
        )
    except Exception as exc:
        print(
            "[meta_tokens][log_event_warn] "
            f"client_id={client_id} event_type={event_type} "
            f"error={exc.__class__.__name__}: {str(exc)[:260]}"
        )


def _with_token_expiry_patch(patch: Dict[str, Any], expires_at: Optional[datetime]) -> Dict[str, Any]:
    if expires_at is None:
        return patch
    iso_value = _iso(expires_at)
    patch["token_expires_at"] = iso_value
    patch["expires_at"] = iso_value
    return patch


def _with_last_sync_patch(patch: Dict[str, Any], synced_at: datetime) -> Dict[str, Any]:
    iso_value = _iso(synced_at)
    patch["last_sync_at"] = iso_value
    patch["last_synced_at"] = iso_value
    return patch


async def _patch_connection(connection_id: str, patch: Dict[str, Any], *, best_effort: bool = False) -> None:
    try:
        await sb_update(
            "meta_connections",
            filters={"id": f"eq.{connection_id}"},
            patch=patch,
            returning="minimal",
        )
    except Exception as exc:
        print(
            "[meta_tokens][patch_warn] "
            f"connection_id={connection_id or '-'} best_effort={best_effort} "
            f"error={exc.__class__.__name__}: {str(exc)[:260]}"
        )
        if not best_effort:
            raise


async def _mark_connection_error(connection_id: str, error: str) -> None:
    await _patch_connection(
        connection_id,
        {
            "last_error": (error or "")[:1000],
            "status": "error",
            "requires_reauth": False,
            "is_active": True,
        },
        best_effort=True,
    )


async def clear_connection_error(connection_id: str) -> None:
    await _patch_connection(
        connection_id,
        {
            "last_error": None,
            "status": "active",
            "requires_reauth": False,
            "is_active": True,
        },
        best_effort=True,
    )


async def _mark_connection_requires_reauth(connection_id: str, error: str) -> None:
    await _patch_connection(
        connection_id,
        {
            "last_error": (error or "")[:1000],
            "status": "needs_reauth",
            "requires_reauth": True,
            "is_active": False,
        },
        best_effort=True,
    )


async def _mark_connection_validated(
    connection_id: str,
    *,
    token_expires_at: Optional[datetime],
    meta_user_id: Optional[str] = None,
    clear_error: bool = False,
) -> None:
    patch: Dict[str, Any] = {
        "last_validated_at": _iso(_utc_now()),
        "status": "active",
        "requires_reauth": False,
        "is_active": True,
    }
    if clear_error:
        patch["last_error"] = None
    if _safe_str(meta_user_id):
        patch["meta_user_id"] = _safe_str(meta_user_id)
    await _patch_connection(
        connection_id,
        _with_token_expiry_patch(patch, token_expires_at),
        best_effort=True,
    )


async def mark_connection_sync_success(connection_id: str) -> None:
    patch = {
        "status": "active",
        "requires_reauth": False,
        "is_active": True,
        "last_error": None,
        "last_sync_status": "success",
    }
    await _patch_connection(
        connection_id,
        _with_last_sync_patch(patch, _utc_now()),
        best_effort=True,
    )


async def mark_connection_sync_error(
    connection_id: str,
    error: str,
    *,
    requires_reauth: bool = False,
) -> None:
    await _patch_connection(
        connection_id,
        {
            "status": "needs_reauth" if requires_reauth else "error",
            "requires_reauth": bool(requires_reauth),
            "is_active": False if requires_reauth else True,
            "last_error": (error or "")[:1000],
            "last_sync_status": "error",
        },
        best_effort=True,
    )


async def get_connection_by_id(connection_id: str) -> Optional[Dict[str, Any]]:
    cid = _safe_str(connection_id)
    if not cid:
        return None
    rows = await sb_select("meta_connections", filters={"id": f"eq.{cid}"}, limit=1)
    return rows[0] if rows else None


async def get_active_connection_for_client(
    client_id: str,
    *,
    platform: str = "instagram",
    connection_type: str = "organic",
) -> Optional[Dict[str, Any]]:
    rows = await sb_select(
        "meta_connections",
        filters={
            "client_id": f"eq.{client_id}",
            "platform": f"eq.{platform}",
            "connection_type": f"eq.{connection_type}",
            "status": "eq.active",
        },
        order="updated_at.desc",
        limit=1,
    )
    if rows:
        return rows[0]

    # Compat: schema antigo com token em clients.
    client = await sb_get_one("clients", f"id=eq.{client_id}")
    token = _safe_str((client or {}).get("ig_access_token")) or _safe_str((client or {}).get("meta_access_token"))
    if not token:
        token = _safe_str((client or {}).get("instagram_access_token"))
    if not token:
        return None
    return {
        "id": None,
        "client_id": client_id,
        "platform": "instagram",
        "connection_type": "organic",
        "status": "active",
        "access_token": token,
        "__legacy": True,
    }


async def validate_meta_token_with_me(access_token: str) -> Dict[str, Any]:
    data = await meta_get_json(
        "/me",
        params={"fields": "id,name", "access_token": access_token},
        timeout=30,
        retries=3,
        context={"resource": "token_validate"},
    )
    return {
        "id": _safe_str(data.get("id")),
        "name": _safe_str(data.get("name")),
    }


async def _exchange_long_lived_token(current_token: str) -> Tuple[str, datetime]:
    app_id = _env("META_APP_ID")
    app_secret = _env("META_APP_SECRET")

    if not app_id or not app_secret:
        raise RuntimeError("META_APP_ID e META_APP_SECRET são obrigatórios para renovar token Meta")

    data = await meta_get_json(
        "/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": current_token,
        },
        timeout=40,
        retries=3,
        context={"resource": "token_refresh"},
    )
    token = _safe_str(data.get("access_token"))
    expires_in = int(data.get("expires_in") or 60 * 24 * 60 * 60)
    if not token:
        raise RuntimeError("Meta não retornou access_token no exchange")

    return token, _utc_now() + timedelta(seconds=expires_in)


async def _persist_refreshed_token(connection_id: str, token: str, expires_at: datetime) -> None:
    patch = {
        "encrypted_access_token": encrypt_secret(token),
        "access_token": None,
        "token_last_refreshed_at": _iso(_utc_now()),
        "status": "active",
        "requires_reauth": False,
        "is_active": True,
        "last_error": None,
    }
    await _patch_connection(
        connection_id,
        _with_token_expiry_patch(patch, expires_at),
        best_effort=True,
    )


async def ensure_valid_meta_token(
    client_id: str,
    *,
    connection_id: Optional[str] = None,
    platform: str = "instagram",
    connection_type: str = "organic",
    force_refresh: bool = False,
) -> str:
    conn = (
        await get_connection_by_id(connection_id)
        if connection_id
        else await get_active_connection_for_client(client_id, platform=platform, connection_type=connection_type)
    )

    disable_refresh = _disable_token_refresh()
    env_token = _env_access_token()

    if disable_refresh and env_token:
        _log_token_source("env", disable_refresh=True, connection_id=_safe_str(connection_id))
        return env_token

    if not conn:
        if env_token:
            _log_token_source("env", disable_refresh=disable_refresh, connection_id=_safe_str(connection_id))
            return env_token
        raise RuntimeError("Cliente sem conexão Meta ativa.")

    if _requires_reauth(conn) or _safe_str(conn.get("status")).lower() == "needs_reauth":
        if env_token:
            _log_token_source("env", disable_refresh=disable_refresh, connection_id=_safe_str(conn.get("id")))
            return env_token
        raise RuntimeError("Conexão Meta exige reconexão.")
    if not _is_active(conn):
        if env_token:
            _log_token_source("env", disable_refresh=disable_refresh, connection_id=_safe_str(conn.get("id")))
            return env_token
        raise RuntimeError("Conexão Meta está inativa.")

    current_token = _token_from_connection(conn)
    if not current_token:
        if env_token:
            _log_token_source("env", disable_refresh=disable_refresh, connection_id=_safe_str(conn.get("id")))
            return env_token
        if conn.get("id"):
            await _mark_connection_requires_reauth(str(conn.get("id")), "missing_token")
        raise RuntimeError("Token Meta ausente. Reconecte.")

    _log_token_source("connection", disable_refresh=disable_refresh, connection_id=_safe_str(conn.get("id")))

    # Compat legado: não tenta persistir refresh fora de meta_connections.
    if bool(conn.get("__legacy")):
        return current_token

    conn_id = _safe_str(conn.get("id"))
    if not conn_id:
        return current_token

    context = {
        "client_id": _safe_str(conn.get("client_id")) or client_id,
        "connection_id": conn_id,
        "platform": _safe_str(conn.get("platform")) or platform,
        "connection_type": _safe_str(conn.get("connection_type")) or connection_type,
        "ad_account_id": _safe_str(conn.get("ad_account_id")),
    }

    token = current_token
    expiry = _token_expiry_from_connection(conn)
    refresh_due = force_refresh or expiry is None or expiry <= (_utc_now() + _refresh_window())
    refreshed = False

    if refresh_due:
        try:
            token, expiry = await _exchange_long_lived_token(current_token)
            refreshed = True
            await _persist_refreshed_token(conn_id, token, expiry)
            await _log_event(
                _safe_str(conn.get("client_id")) or client_id,
                "token_refresh",
                ok=True,
                details={
                    "connection_id": conn_id,
                    "expires_at": _iso(expiry),
                    "forced": bool(force_refresh),
                },
            )
        except Exception as exc:
            msg = str(exc)
            if env_token:
                print(
                    "[meta][token] "
                    f"source=env disable_refresh={str(disable_refresh).lower()} "
                    f"connection_id={conn_id} reason=refresh_failed fallback=true"
                )
                await _log_event(
                    _safe_str(conn.get("client_id")) or client_id,
                    "token_refresh",
                    ok=False,
                    details={
                        "connection_id": conn_id,
                        "error": msg[:400],
                        "forced": bool(force_refresh),
                        "fallback": "META_ACCESS_TOKEN",
                    },
                )
                return env_token
            await _mark_connection_requires_reauth(conn_id, msg)
            await _log_event(
                _safe_str(conn.get("client_id")) or client_id,
                "token_refresh",
                ok=False,
                details={
                    "connection_id": conn_id,
                    "error": msg[:400],
                    "forced": bool(force_refresh),
                },
            )
            raise RuntimeError("Falha ao renovar token Meta. Reconecte a conta.") from exc

    should_validate = True
    if not should_validate:
        return token

    try:
        me = await meta_get_json(
            "/me",
            params={"fields": "id,name", "access_token": token},
            timeout=30,
            retries=3,
            context={"resource": "token_validate", **context},
        )
        await _mark_connection_validated(
            conn_id,
            token_expires_at=expiry,
            meta_user_id=_safe_str(me.get("id")),
            clear_error=refreshed,
        )
        return token
    except MetaApiError as exc:
        if exc.invalid_oauth and not refreshed:
            if env_token:
                print(
                    "[meta][token] "
                    f"source=env disable_refresh={str(disable_refresh).lower()} "
                    f"connection_id={conn_id} reason=connection_token_invalid fallback=true"
                )
                return env_token
            try:
                token, expiry = await _exchange_long_lived_token(token)
                await _persist_refreshed_token(conn_id, token, expiry)
                me = await meta_get_json(
                    "/me",
                    params={"fields": "id,name", "access_token": token},
                    timeout=30,
                    retries=3,
                    context={"resource": "token_validate_after_refresh", **context},
                )
                await _mark_connection_validated(
                    conn_id,
                    token_expires_at=expiry,
                    meta_user_id=_safe_str(me.get("id")),
                    clear_error=True,
                )
                await _log_event(
                    _safe_str(conn.get("client_id")) or client_id,
                    "token_refresh",
                    ok=True,
                    details={
                        "connection_id": conn_id,
                        "expires_at": _iso(expiry),
                        "forced": False,
                        "reason": "validate_after_invalid",
                    },
                )
                return token
            except Exception as refresh_exc:
                msg = str(refresh_exc)
                await _mark_connection_requires_reauth(conn_id, msg)
                await _log_event(
                    _safe_str(conn.get("client_id")) or client_id,
                    "token_validation",
                    ok=False,
                    details={"connection_id": conn_id, "error": msg[:400]},
                )
                raise RuntimeError("Token Meta inválido ou expirado. Reconecte a conta.") from refresh_exc

        msg = str(exc)
        await _mark_connection_error(conn_id, msg)
        await _log_event(
            _safe_str(conn.get("client_id")) or client_id,
            "token_validation",
            ok=False,
            details={"connection_id": conn_id, "error": msg[:400]},
        )
        raise RuntimeError("Falha ao validar token Meta antes do sync.") from exc
    except Exception as exc:
        msg = str(exc)
        await _mark_connection_error(conn_id, msg)
        await _log_event(
            _safe_str(conn.get("client_id")) or client_id,
            "token_validation",
            ok=False,
            details={"connection_id": conn_id, "error": msg[:400]},
        )
        raise RuntimeError("Falha ao validar token Meta antes do sync.") from exc


async def ensure_valid_meta_token_for_connection(connection: Dict[str, Any]) -> str:
    return await ensure_valid_meta_token(
        _safe_str(connection.get("client_id")),
        connection_id=_safe_str(connection.get("id")),
        platform=_safe_str(connection.get("platform")) or "instagram",
        connection_type=_safe_str(connection.get("connection_type")) or "organic",
    )


async def refresh_meta_token_for_connection(connection_id: str) -> Dict[str, Any]:
    conn = await get_connection_by_id(connection_id)
    if not conn:
        raise RuntimeError("Conexão Meta não encontrada.")

    token = await ensure_valid_meta_token(
        _safe_str(conn.get("client_id")),
        connection_id=_safe_str(conn.get("id")),
        platform=_safe_str(conn.get("platform")) or "instagram",
        connection_type=_safe_str(conn.get("connection_type")) or "organic",
        force_refresh=True,
    )
    refreshed_conn = await get_connection_by_id(connection_id)
    return {
        "ok": True,
        "connection": serialize_connection_status(refreshed_conn or conn),
        "token_ready": bool(_safe_str(token)),
    }


async def get_meta_connection_status(connection_id: str) -> Dict[str, Any]:
    conn = await get_connection_by_id(connection_id)
    if not conn:
        raise RuntimeError("Conexão Meta não encontrada.")
    return {
        "ok": True,
        "connection": serialize_connection_status(conn),
    }


async def upsert_meta_connection(
    client_id: str,
    access_token: str,
    expires_at: Optional[str],
    ig_user_id: Optional[str],
) -> Dict[str, Any]:
    token = _safe_str(access_token)
    if not token:
        raise RuntimeError("access_token é obrigatório")

    me = await validate_meta_token_with_me(token)
    exp = _parse_ts(expires_at)
    if expires_at and not exp:
        raise RuntimeError("expires_at inválido. Use ISO: 2026-07-01T00:00:00Z")

    ig_id = _safe_str(ig_user_id)
    rows = await sb_select(
        "meta_connections",
        filters={
            "client_id": f"eq.{client_id}",
            "platform": "eq.instagram",
            "connection_type": "eq.organic",
            "ig_user_id": f"eq.{ig_id}",
        },
        limit=1,
    )

    patch = {
        "client_id": client_id,
        "platform": "instagram",
        "connection_type": "organic",
        "meta_user_id": _safe_str(me.get("id")),
        "ig_user_id": ig_id,
        "username": "",
        "business_id": "",
        "ad_account_id": "",
        "ad_account_name": "",
        "scopes_json": [],
        "encrypted_access_token": encrypt_secret(token),
        "access_token": None,
        "expires_at": _iso(exp) if exp else None,
        "token_expires_at": _iso(exp) if exp else None,
        "token_last_refreshed_at": _iso(_utc_now()),
        "last_validated_at": _iso(_utc_now()),
        "last_sync_status": "never",
        "requires_reauth": False,
        "is_active": True,
        "status": "active",
        "connected_at": _iso(_utc_now()),
        "last_error": None,
    }

    if rows:
        conn_id = _safe_str(rows[0].get("id"))
        await sb_update("meta_connections", filters={"id": f"eq.{conn_id}"}, patch=patch, returning="minimal")
    else:
        await sb_insert("meta_connections", patch, returning="minimal")

    if ig_id:
        await sb_update(
            "clients",
            filters={"id": f"eq.{client_id}"},
            patch={"ig_user_id": ig_id},
            returning="minimal",
        )

    await _log_event(
        client_id,
        "connect_meta",
        ok=True,
        details={"meta_me_id": _safe_str(me.get("id")), "platform": "instagram"},
    )

    return {
        "ok": True,
        "client_id": client_id,
        "platform": "instagram",
        "connection_type": "organic",
        "meta_me": me,
    }
