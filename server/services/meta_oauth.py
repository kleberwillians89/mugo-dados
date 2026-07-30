from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import httpx

from .env_loader import ensure_env_loaded
from .crypto import decrypt_secret, encrypt_secret
from .ig_supabase import sb_delete, sb_insert, sb_select, sb_update
from .meta_http import meta_get_json
from .meta_tokens import serialize_connection_status

META_DIALOG = "https://www.facebook.com/v19.0/dialog/oauth"
_HANDOFF_TTL_SECONDS = 15 * 60
_HANDOFF_TABLE = "meta_oauth_handoffs"
ensure_env_loaded()


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _json_object(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _json_array(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def get_meta_oauth_settings(*, require_redirect_uri: bool = False, debug: bool = True) -> Dict[str, str]:
    ensure_env_loaded()

    app_id = _env("META_APP_ID")
    app_secret = _env("META_APP_SECRET")
    redirect_uri = _env("META_OAUTH_REDIRECT_URI")

    if debug:
        print(f"[meta_oauth][env] META_APP_ID loaded: {'yes' if app_id else 'no'}")
        print(f"[meta_oauth][env] META_APP_SECRET loaded: {'yes' if app_secret else 'no'}")
        print(
            "[meta_oauth][env] META_OAUTH_REDIRECT_URI loaded: "
            f"{redirect_uri if redirect_uri else 'missing'}"
        )

    missing: List[str] = []
    if not app_id:
        missing.append("META_APP_ID")
    if not app_secret:
        missing.append("META_APP_SECRET")
    if require_redirect_uri and not redirect_uri:
        missing.append("META_OAUTH_REDIRECT_URI")

    if missing:
        raise RuntimeError(
            "Configuração OAuth Meta incompleta. "
            f"Missing environment variable(s): {', '.join(missing)}"
        )

    return {
        "app_id": app_id,
        "app_secret": app_secret,
        "redirect_uri": redirect_uri,
    }


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _b64u_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")


def _b64u_decode(value: str) -> bytes:
    padding = "=" * ((4 - (len(value) % 4)) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("utf-8"))


def _state_secret() -> str:
    for key_name in ("META_OAUTH_STATE_SECRET", "TOKEN_ENCRYPTION_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        v = _env(key_name)
        if v:
            return v
    raise RuntimeError("Segredo de state OAuth não configurado")


def _sign(payload_bytes: bytes) -> str:
    digest = hmac.new(_state_secret().encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    return _b64u_encode(digest)


def _default_scopes() -> List[str]:
    raw = _env("META_OAUTH_SCOPES")
    if raw:
        return [s.strip() for s in raw.split(",") if s.strip()]
    return [
        "public_profile",
        "email",
        "pages_show_list",
        "pages_read_engagement",
        "instagram_basic",
        "instagram_manage_insights",
        "instagram_manage_comments",
        "ads_read",
        "business_management",
    ]


def _normalize_ad_account_id(ad_account_id: str) -> str:
    raw = _safe_str(ad_account_id)
    if not raw:
        return ""
    return raw if raw.startswith("act_") else f"act_{raw}"


def _normalize_state_client_id(client_id: str) -> str:
    cid = _safe_str(client_id)
    if not cid:
        raise RuntimeError("client_id obrigatório para iniciar OAuth")
    return cid


def _is_missing_relation_error(exc: httpx.HTTPStatusError, relation_name: str) -> bool:
    if exc.response is None:
        return False
    if exc.response.status_code not in {400, 404}:
        return False
    body = str(exc.response.text or "").lower()
    relation = str(relation_name or "").lower()
    return relation in body and ("relation" in body or "does not exist" in body or "schema cache" in body)


def _handoff_cutoff_iso() -> str:
    return _iso(_now_utc() - timedelta(seconds=_HANDOFF_TTL_SECONDS))


def _handoff_schema_error(exc: httpx.HTTPStatusError) -> RuntimeError:
    if _is_missing_relation_error(exc, _HANDOFF_TABLE):
        return RuntimeError(
            "Tabela de handoff OAuth não encontrada no Supabase. "
            "Rode a migração 20260416_000009_meta_oauth_handoffs.sql e tente novamente."
        )
    return RuntimeError(f"Falha ao acessar handoff OAuth: {str(exc)[:220]}")


async def _cleanup_handoffs() -> None:
    try:
        await sb_delete(
            _HANDOFF_TABLE,
            filters={"created_at": f"lt.{_handoff_cutoff_iso()}"},
            returning="minimal",
        )
    except httpx.HTTPStatusError as exc:
        raise _handoff_schema_error(exc) from exc


async def _load_handoff_row(*, handoff: str) -> Dict[str, Any]:
    token = _safe_str(handoff)
    if not token:
        raise RuntimeError("Sessão OAuth expirada. Conecte novamente.")

    await _cleanup_handoffs()
    try:
        rows = await sb_select(
            _HANDOFF_TABLE,
            filters={"handoff": f"eq.{token}"},
            limit=1,
        )
    except httpx.HTTPStatusError as exc:
        raise _handoff_schema_error(exc) from exc

    item = rows[0] if rows else None
    if not item:
        raise RuntimeError("Sessão OAuth expirada. Conecte novamente.")
    return item


def _upsert_connection_match_filters(
    *,
    client_id: str,
    platform: str,
    connection_type: str,
    ig_user_id: str,
    ad_account_id: str,
) -> Dict[str, str]:
    return {
        "client_id": f"eq.{client_id}",
        "platform": f"eq.{platform}",
        "connection_type": f"eq.{connection_type}",
        "ig_user_id": f"eq.{ig_user_id}",
        "ad_account_id": f"eq.{ad_account_id}",
    }


def build_oauth_url(
    *,
    client_id: str,
    user_id: str,
    redirect_uri: str,
    app_id: Optional[str] = None,
) -> Dict[str, Any]:
    cid = _normalize_state_client_id(client_id)
    uid = _safe_str(user_id)
    if not uid:
        raise RuntimeError("user_id obrigatório para iniciar OAuth")
    if not _safe_str(redirect_uri):
        raise RuntimeError("redirect_uri OAuth não configurada")

    payload = {
        "client_id": cid,
        "user_id": uid,
        "nonce": str(uuid.uuid4()),
        "iat": int(time.time()),
    }
    payload_raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    state = f"{_b64u_encode(payload_raw)}.{_sign(payload_raw)}"

    resolved_app_id = _safe_str(app_id) or _env("META_APP_ID")

    params = {
        "client_id": resolved_app_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": ",".join(_default_scopes()),
        "state": state,
    }
    if not params["client_id"]:
        raise RuntimeError("META_APP_ID não configurado")

    return {"state": state, "url": f"{META_DIALOG}?{urlencode(params)}"}


def verify_state(state: str, *, expected_user_id: Optional[str] = None, max_age_seconds: int = 900) -> Dict[str, Any]:
    raw_state = _safe_str(state)
    if "." not in raw_state:
        raise RuntimeError("state OAuth inválido")

    encoded_payload, encoded_sig = raw_state.split(".", 1)
    payload_bytes = _b64u_decode(encoded_payload)
    expected_sig = _sign(payload_bytes)
    if not hmac.compare_digest(encoded_sig, expected_sig):
        raise RuntimeError("state OAuth inválido (assinatura)")

    payload = json.loads(payload_bytes.decode("utf-8"))
    iat = int(payload.get("iat") or 0)
    if not iat:
        raise RuntimeError("state OAuth sem iat")
    age = int(time.time()) - iat
    if age < 0 or age > max_age_seconds:
        raise RuntimeError("state OAuth expirado")

    uid = _safe_str(payload.get("user_id"))
    if expected_user_id and uid != _safe_str(expected_user_id):
        raise RuntimeError("state OAuth não pertence ao usuário autenticado")
    if not _safe_str(payload.get("client_id")):
        raise RuntimeError("state OAuth sem client_id")
    return payload


async def _meta_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    return await meta_get_json(
        path,
        params=params,
        timeout=45,
        retries=3,
        context={"resource": "oauth_meta"},
    )


async def exchange_code_for_token(*, code: str, redirect_uri: str) -> Dict[str, Any]:
    settings = get_meta_oauth_settings(debug=False)
    app_id = _safe_str(settings.get("app_id"))
    app_secret = _safe_str(settings.get("app_secret"))

    short = await _meta_get(
        "/oauth/access_token",
        {
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": redirect_uri,
            "code": _safe_str(code),
        },
    )
    short_token = _safe_str(short.get("access_token"))
    if not short_token:
        raise RuntimeError("Meta não retornou access_token")

    # Troca para long-lived quando possível.
    access_token = short_token
    expires_in = int(short.get("expires_in") or 3600)
    try:
        ll = await _meta_get(
            "/oauth/access_token",
            {
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": short_token,
            },
        )
        if _safe_str(ll.get("access_token")):
            access_token = _safe_str(ll.get("access_token"))
            expires_in = int(ll.get("expires_in") or expires_in)
    except Exception:
        # Mantém token short-lived se exchange falhar.
        pass

    expires_at = _iso(_now_utc() + timedelta(seconds=max(60, expires_in)))
    return {
        "access_token": access_token,
        "expires_in": expires_in,
        "expires_at": expires_at,
    }


async def fetch_instagram_identity(access_token: str) -> Dict[str, Any]:
    me = await _meta_get(
        "/me",
        {
            "fields": "id,name",
            "access_token": access_token,
        },
    )

    pages = await _meta_get(
        "/me/accounts",
        {
            "fields": "id,name,instagram_business_account{id,username},connected_instagram_account{id,username}",
            "limit": 200,
            "access_token": access_token,
        },
    )

    out: List[Dict[str, str]] = []
    seen: set[str] = set()
    for p in pages.get("data") or []:
        ig = (p or {}).get("instagram_business_account") or (p or {}).get("connected_instagram_account") or {}
        ig_id = _safe_str((ig or {}).get("id"))
        if not ig_id or ig_id in seen:
            continue
        seen.add(ig_id)
        out.append(
            {
                "ig_user_id": ig_id,
                "username": _safe_str((ig or {}).get("username")),
                "business_id": _safe_str((p or {}).get("id")),
                "business_name": _safe_str((p or {}).get("name")),
            }
        )

    return {
        "meta_user": {"id": _safe_str(me.get("id")), "name": _safe_str(me.get("name"))},
        "instagram_accounts": out,
    }


async def fetch_ad_accounts(access_token: str) -> List[Dict[str, Any]]:
    accounts: List[Dict[str, Any]] = []
    next_url: Optional[str] = None
    seen: set[str] = set()

    while True:
        if next_url:
            data = await meta_get_json(
                next_url,
                timeout=45,
                retries=3,
                context={"resource": "oauth_adaccounts_paging"},
            )
        else:
            data = await _meta_get(
                "/me/adaccounts",
                {
                    "fields": "id,account_id,name,account_status,currency",
                    "limit": 200,
                    "access_token": access_token,
                },
            )

        for row in data.get("data") or []:
            act_id = _normalize_ad_account_id(_safe_str(row.get("id")) or _safe_str(row.get("account_id")))
            if not act_id or act_id in seen:
                continue
            seen.add(act_id)
            accounts.append(
                {
                    "ad_account_id": act_id,
                    "ad_account_name": _safe_str(row.get("name")),
                    "account_status": row.get("account_status"),
                    "currency": _safe_str(row.get("currency")),
                }
            )

        paging = data.get("paging") or {}
        next_url = _safe_str(paging.get("next")) or None
        if not next_url:
            break

    return accounts


async def _fetch_granted_scopes(access_token: str) -> List[str]:
    try:
        perms = await _meta_get("/me/permissions", {"access_token": access_token})
    except Exception:
        return []
    scopes: List[str] = []
    for p in perms.get("data") or []:
        if _safe_str((p or {}).get("status")).lower() != "granted":
            continue
        name = _safe_str((p or {}).get("permission"))
        if name:
            scopes.append(name)
    return scopes


async def discover_assets(access_token: str) -> Dict[str, Any]:
    identity = await fetch_instagram_identity(access_token)
    ad_accounts = await fetch_ad_accounts(access_token)
    scopes = await _fetch_granted_scopes(access_token)
    return {
        "meta_user": identity.get("meta_user") or {},
        "instagram_accounts": identity.get("instagram_accounts") or [],
        "ad_accounts": ad_accounts,
        "scopes": scopes,
    }


async def create_discovery_handoff(
    *,
    user_id: str,
    client_id: str,
    access_token: str,
    expires_at: Optional[str],
    discovered: Dict[str, Any],
) -> str:
    handoff = str(uuid.uuid4())
    await _cleanup_handoffs()
    row = {
        "handoff": handoff,
        "user_id": _safe_str(user_id),
        "client_id": _safe_str(client_id),
        "encrypted_access_token": encrypt_secret(access_token),
        "expires_at": _safe_str(expires_at) or None,
        "meta_user_json": _json_object(discovered.get("meta_user")),
        "instagram_accounts_json": _json_array(discovered.get("instagram_accounts")),
        "ad_accounts_json": _json_array(discovered.get("ad_accounts")),
        "scopes_json": _json_array(discovered.get("scopes")),
    }
    try:
        await sb_insert(_HANDOFF_TABLE, row, returning="minimal")
    except httpx.HTTPStatusError as exc:
        raise _handoff_schema_error(exc) from exc
    return handoff


async def read_discovery_handoff(*, handoff: str, user_id: str, client_id: Optional[str] = None) -> Dict[str, Any]:
    item = await _load_handoff_row(handoff=handoff)
    if _safe_str(item.get("user_id")) != _safe_str(user_id):
        raise RuntimeError("Sessão OAuth não pertence ao usuário autenticado.")
    if client_id and _safe_str(item.get("client_id")) != _safe_str(client_id):
        raise RuntimeError("Sessão OAuth não pertence ao cliente informado.")

    return {
        "handoff": _safe_str(item.get("handoff")),
        "client_id": _safe_str(item.get("client_id")),
        "meta_user": _json_object(item.get("meta_user_json")),
        "instagram_accounts": _json_array(item.get("instagram_accounts_json")),
        "ad_accounts": _json_array(item.get("ad_accounts_json")),
        "scopes": _json_array(item.get("scopes_json")),
        "expires_at": item.get("expires_at"),
    }


async def _save_connection_row(row: Dict[str, Any]) -> Dict[str, Any]:
    filters = _upsert_connection_match_filters(
        client_id=_safe_str(row.get("client_id")),
        platform=_safe_str(row.get("platform")),
        connection_type=_safe_str(row.get("connection_type")),
        ig_user_id=_safe_str(row.get("ig_user_id")),
        ad_account_id=_safe_str(row.get("ad_account_id")),
    )

    existing = await sb_select("meta_connections", filters=filters, limit=1)
    if existing:
        conn_id = _safe_str(existing[0].get("id"))
        await sb_update("meta_connections", filters={"id": f"eq.{conn_id}"}, patch=row, returning="minimal")
        rows = await sb_select("meta_connections", filters={"id": f"eq.{conn_id}"}, limit=1)
        return rows[0] if rows else {"id": conn_id, **row}

    inserted = await sb_insert("meta_connections", row, returning="representation")
    return inserted or row


async def save_connections(
    *,
    user_id: str,
    client_id: str,
    handoff: str,
    instagram_ig_user_ids: List[str],
    ad_account_ids: List[str],
) -> Dict[str, Any]:
    item = await _load_handoff_row(handoff=handoff)
    token = _safe_str(item.get("handoff"))
    if _safe_str(item.get("user_id")) != _safe_str(user_id):
        raise RuntimeError("Sessão OAuth inválida para este usuário.")
    if _safe_str(item.get("client_id")) != _safe_str(client_id):
        raise RuntimeError("Sessão OAuth inválida para este cliente.")

    encrypted_access = _safe_str(item.get("encrypted_access_token"))
    access_token = decrypt_secret(encrypted_access)

    ig_requested = {_safe_str(i) for i in instagram_ig_user_ids if _safe_str(i)}
    ads_requested = {_normalize_ad_account_id(i) for i in ad_account_ids if _safe_str(i)}
    selected_igs = [
        a
        for a in _json_array(item.get("instagram_accounts_json"))
        if _safe_str((a or {}).get("ig_user_id")) in ig_requested
    ]
    selected_ads = [
        a
        for a in _json_array(item.get("ad_accounts_json"))
        if _normalize_ad_account_id(_safe_str((a or {}).get("ad_account_id"))) in ads_requested
    ]

    if not selected_igs and not selected_ads:
        raise RuntimeError("Selecione ao menos um ativo Instagram ou Meta Ads para vincular.")

    meta_user = _json_object(item.get("meta_user_json"))
    scopes = _json_array(item.get("scopes_json"))
    now_iso = _iso(_now_utc())
    expires_at = item.get("expires_at")
    current_meta_user_id = _safe_str(meta_user.get("id"))

    if current_meta_user_id:
        existing_rows = await sb_select(
            "meta_connections",
            filters={"client_id": f"eq.{client_id}"},
            limit=500,
        )
        existing_meta_ids = {
            _safe_str(r.get("meta_user_id"))
            for r in existing_rows
            if _safe_str(r.get("meta_user_id"))
        }
        if existing_meta_ids and current_meta_user_id not in existing_meta_ids:
            raise RuntimeError(
                "Este cliente já está vinculado a outra conta Meta. "
                "Use a mesma conta para reconectar ativos."
            )

    saved: List[Dict[str, Any]] = []

    for ig in selected_igs:
        row = {
            "client_id": client_id,
            "platform": "instagram",
            "connection_type": "organic",
            "meta_user_id": _safe_str(meta_user.get("id")),
            "ig_user_id": _safe_str(ig.get("ig_user_id")),
            "username": _safe_str(ig.get("username")),
            "business_id": _safe_str(ig.get("business_id")),
            "ad_account_id": "",
            "ad_account_name": "",
            "scopes_json": scopes,
            "encrypted_access_token": encrypt_secret(access_token),
            "access_token": None,
            "expires_at": expires_at,
            "token_expires_at": expires_at,
            "token_last_refreshed_at": now_iso,
            "last_validated_at": now_iso,
            "last_sync_status": "never",
            "requires_reauth": False,
            "is_active": True,
            "connected_at": now_iso,
            "last_error": None,
            "status": "active",
        }
        saved_conn = await _save_connection_row(row)
        saved.append(
            {
                "id": _safe_str(saved_conn.get("id")),
                "platform": "instagram",
                "connection_type": "organic",
                "ig_user_id": _safe_str(saved_conn.get("ig_user_id")),
                "username": _safe_str(saved_conn.get("username")),
                "status": _safe_str(saved_conn.get("status")) or "active",
            }
        )

    for ad in selected_ads:
        row = {
            "client_id": client_id,
            "platform": "meta_ads",
            "connection_type": "paid",
            "meta_user_id": _safe_str(meta_user.get("id")),
            "ig_user_id": "",
            "username": _safe_str(meta_user.get("name")),
            "business_id": "",
            "ad_account_id": _normalize_ad_account_id(_safe_str(ad.get("ad_account_id"))),
            "ad_account_name": _safe_str(ad.get("ad_account_name")),
            "scopes_json": scopes,
            "encrypted_access_token": encrypt_secret(access_token),
            "access_token": None,
            "expires_at": expires_at,
            "token_expires_at": expires_at,
            "token_last_refreshed_at": now_iso,
            "last_validated_at": now_iso,
            "last_sync_status": "never",
            "requires_reauth": False,
            "is_active": True,
            "connected_at": now_iso,
            "last_error": None,
            "status": "active",
        }
        saved_conn = await _save_connection_row(row)
        saved.append(
            {
                "id": _safe_str(saved_conn.get("id")),
                "platform": "meta_ads",
                "connection_type": "paid",
                "ad_account_id": _safe_str(saved_conn.get("ad_account_id")),
                "ad_account_name": _safe_str(saved_conn.get("ad_account_name")),
                "status": _safe_str(saved_conn.get("status")) or "active",
            }
        )

    # Compatibilidade com fluxos existentes que ainda usam clients.ig_user_id
    if selected_igs:
        await sb_update(
            "clients",
            filters={"id": f"eq.{client_id}"},
            patch={"ig_user_id": _safe_str(selected_igs[0].get("ig_user_id"))},
            returning="minimal",
        )

    try:
        await sb_delete(
            _HANDOFF_TABLE,
            filters={"handoff": f"eq.{token}"},
            returning="minimal",
        )
    except httpx.HTTPStatusError as exc:
        raise _handoff_schema_error(exc) from exc

    return {
        "ok": True,
        "client_id": client_id,
        "saved_count": len(saved),
        "connections": saved,
    }


async def list_connections(client_id: str) -> List[Dict[str, Any]]:
    rows = await sb_select(
        "meta_connections",
        filters={"client_id": f"eq.{client_id}"},
        order="updated_at.desc",
        limit=500,
    )
    out: List[Dict[str, Any]] = []
    for r in rows:
        serialized = serialize_connection_status(r)
        serialized["scopes_json"] = r.get("scopes_json") or []
        out.append(serialized)
    return out


async def disconnect_connection(client_id: str, connection_id: str) -> Dict[str, Any]:
    rows = await sb_update(
        "meta_connections",
        filters={"id": f"eq.{_safe_str(connection_id)}", "client_id": f"eq.{_safe_str(client_id)}"},
        patch={
            "status": "disconnected",
            "requires_reauth": False,
            "is_active": False,
            "last_error": None,
            "updated_at": _iso(_now_utc()),
        },
        returning="representation",
    )
    if not rows:
        raise RuntimeError("Conexão não encontrada")
    row = rows[0]
    return {
        "ok": True,
        "connection": {
            "id": _safe_str(row.get("id")),
            "status": _safe_str(row.get("status")),
            "platform": _safe_str(row.get("platform")),
            "connection_type": _safe_str(row.get("connection_type")),
        },
    }


def build_frontend_callback_redirect(*, success: bool, client_id: str, handoff: Optional[str], error: Optional[str]) -> str:
    allow_origin = _env("ALLOW_ORIGIN")
    frontend_base = [o.strip() for o in allow_origin.split(",") if o.strip()]
    target = frontend_base[0] if frontend_base else "http://localhost:5173"
    params = {"onboarding": "1", "client_id": client_id}
    if success and handoff:
        params["meta_oauth"] = "success"
        params["handoff"] = handoff
    else:
        params["meta_oauth"] = "error"
        params["error"] = _safe_str(error)[:180] or "oauth_failed"
    return f"{target.rstrip('/')}/?{urlencode(params)}"


def resolve_meta_redirect_uri(backend_origin: str) -> str:
    ensure_env_loaded()
    configured = _env("META_OAUTH_REDIRECT_URI")
    if configured:
        return configured
    base = backend_origin.rstrip("/")
    return f"{base}/api/oauth/meta/callback"
