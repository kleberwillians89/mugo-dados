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
from .meta_config import META_OAUTH_DIALOG_URL
from .meta_http import MetaApiError, meta_get_json
from .integration_errors import IntegrationError
from .meta_tokens import serialize_connection_status
from .generic_connections import audit_connection, disconnect_generic_connection, get_connection, upsert_connection
from .runtime_cache import invalidate_namespace

META_DIALOG = META_OAUTH_DIALOG_URL
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
    return [
        "public_profile",
        "email",
        "pages_show_list",
        "pages_read_engagement",
        "instagram_basic",
        "instagram_manage_insights",
        "ads_read",
        "business_management",
    ]


def _normalize_ad_account_id(ad_account_id: str) -> str:
    raw = _safe_str(ad_account_id)
    if not raw:
        return ""
    return raw if raw.startswith("act_") else f"act_{raw}"


def _manual_numeric_id(value: Any, *, code: str, label: str) -> str:
    normalized = _safe_str(value)
    if not normalized or not normalized.isdigit():
        raise IntegrationError(
            f"{label} inválido.", status_code=400, code=code, provider="meta",
        )
    return normalized


def _manual_meta_api_error(exc: MetaApiError, *, code: str, label: str) -> IntegrationError:
    if exc.invalid_oauth:
        return IntegrationError(
            "A conexão Meta exige nova autorização.", status_code=401,
            code="META_REAUTH_REQUIRED", provider="meta",
        )
    if exc.status_code in {400, 403, 404}:
        return IntegrationError(
            f"O token atual não possui acesso ao {label} informado.", status_code=403,
            code="META_ASSET_PERMISSION_DENIED" if exc.status_code == 403 else code,
            provider="meta",
        )
    return IntegrationError(
        "A API da Meta está temporariamente indisponível.", status_code=503,
        code="META_GRAPH_UNAVAILABLE", provider="meta", retryable=True,
    )


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
    state_override: Optional[str] = None,
) -> Dict[str, Any]:
    cid = _normalize_state_client_id(client_id)
    uid = _safe_str(user_id)
    if not uid:
        raise RuntimeError("user_id obrigatório para iniciar OAuth")
    if not _safe_str(redirect_uri):
        raise RuntimeError("redirect_uri OAuth não configurada")

    state = _safe_str(state_override)

    if not state:
        payload = {
            "client_id": cid,
            "user_id": uid,
            "nonce": str(uuid.uuid4()),
            "iat": int(time.time()),
        }
        payload_raw = json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
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

    page_rows: List[Dict[str, Any]] = []
    next_url: Optional[str] = None
    while True:
        pages = (
            await meta_get_json(next_url, timeout=45, retries=3, context={"resource": "oauth_pages_paging"})
            if next_url
            else await _meta_get(
                "/me/accounts",
                {
                    "fields": "id,name,instagram_business_account{id,username},connected_instagram_account{id,username}",
                    "limit": 200,
                    "access_token": access_token,
                },
            )
        )
        page_rows.extend(row for row in (pages.get("data") or []) if isinstance(row, dict))
        next_url = _safe_str((pages.get("paging") or {}).get("next")) or None
        if not next_url:
            break

    out: List[Dict[str, str]] = []
    available_pages: List[Dict[str, str]] = []
    seen: set[str] = set()
    for p in page_rows:
        page_id = _safe_str((p or {}).get("id"))
        if page_id:
            available_pages.append(
                {"page_id": page_id, "page_name": _safe_str((p or {}).get("name"))}
            )
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
        "pages": available_pages,
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
                    "fields": "id,account_id,name,account_status,currency,timezone_name",
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
                    "timezone_name": _safe_str(row.get("timezone_name")),
                }
            )

        paging = data.get("paging") or {}
        next_url = _safe_str(paging.get("next")) or None
        if not next_url:
            break

    print(
        "[meta_oauth][ad_accounts] "
        f"http_status=200 count={len(accounts)} accounts="
        + ",".join(
            f"{_safe_str(row.get('ad_account_id'))}:{_safe_str(row.get('ad_account_name'))[:80]}"
            for row in accounts
        )
    )
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


async def _fetch_business_managers(access_token: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, Any]] = []
    next_url: Optional[str] = None
    try:
        while True:
            response = (
                await meta_get_json(next_url, timeout=45, retries=3, context={"resource": "oauth_businesses_paging"})
                if next_url
                else await _meta_get(
                    "/me/businesses",
                    {"fields": "id,name", "limit": 200, "access_token": access_token},
                )
            )
            rows.extend(row for row in (response.get("data") or []) if isinstance(row, dict))
            next_url = _safe_str((response.get("paging") or {}).get("next")) or None
            if not next_url:
                break
    except Exception:
        return []
    return [
        {"business_id": _safe_str(row.get("id")), "business_name": _safe_str(row.get("name"))}
        for row in rows
        if isinstance(row, dict) and _safe_str(row.get("id"))
    ]


async def discover_assets(access_token: str) -> Dict[str, Any]:
    identity = await fetch_instagram_identity(access_token)
    ad_accounts = await fetch_ad_accounts(access_token)
    scopes = await _fetch_granted_scopes(access_token)
    business_managers = await _fetch_business_managers(access_token)
    return {
        "meta_user": identity.get("meta_user") or {},
        "pages": identity.get("pages") or [],
        "instagram_accounts": identity.get("instagram_accounts") or [],
        "ad_accounts": ad_accounts,
        "business_managers": business_managers,
        "scopes": scopes,
    }


async def discover_existing_meta_organic_assets(
    *, user_id: str, client_id: str, connection_id: str
) -> Dict[str, Any]:
    connection = await get_connection(client_id, connection_id, include_token=True)
    if _safe_str(connection.get("provider")) != "meta":
        raise IntegrationError(
            "A conexão selecionada não é uma conexão Meta.", status_code=404,
            code="META_CONNECTION_NOT_FOUND", provider="meta",
        )
    status = _safe_str(connection.get("status")).lower()
    if (status and status not in {"connected", "selection_required"}) or connection.get("disconnected_at"):
        raise IntegrationError(
            "A conexão Meta está desconectada e exige nova autorização.", status_code=409,
            code="META_CONNECTION_DISCONNECTED", provider="meta",
        )
    scopes = {_safe_str(scope) for scope in _json_array(connection.get("scopes"))}
    required = {"pages_show_list", "pages_read_engagement", "instagram_basic"}
    if not required.issubset(scopes):
        raise IntegrationError(
            "A autorização Meta não possui as permissões necessárias para listar o Instagram profissional.",
            status_code=403, code="META_PERMISSION_MISSING", provider="meta",
        )
    try:
        token_payload = json.loads(_safe_str(connection.get("_token")) or "{}")
        access_token = _safe_str(token_payload.get("access_token"))
    except (TypeError, ValueError) as exc:
        raise IntegrationError(
            "A conexão Meta exige nova autorização.", status_code=401,
            code="META_REAUTH_REQUIRED", provider="meta",
        ) from exc
    if not access_token:
        raise IntegrationError(
            "A conexão Meta exige nova autorização.", status_code=401,
            code="META_REAUTH_REQUIRED", provider="meta",
        )
    try:
        identity = await fetch_instagram_identity(access_token)
        discovered = {
            "meta_user": identity.get("meta_user") or {},
            "pages": identity.get("pages") or [],
            "instagram_accounts": identity.get("instagram_accounts") or [],
            # Configuração orgânica não relista nem modifica Meta Ads.
            "ad_accounts": [],
            "business_managers": await _fetch_business_managers(access_token),
            "scopes": sorted(scopes),
        }
    except MetaApiError as exc:
        code = "META_REAUTH_REQUIRED" if exc.invalid_oauth else (
            "META_PERMISSION_MISSING" if exc.status_code == 403 else "META_GRAPH_UNAVAILABLE"
        )
        status_code = 401 if exc.invalid_oauth else (403 if exc.status_code == 403 else 503)
        raise IntegrationError(
            "Não foi possível consultar os ativos orgânicos da Meta.",
            status_code=status_code, code=code, provider="meta", retryable=status_code == 503,
        ) from exc
    handoff = await create_discovery_handoff(
        user_id=user_id,
        client_id=client_id,
        access_token=access_token,
        expires_at=_safe_str(connection.get("token_expires_at")) or None,
        discovered=discovered,
    )
    result = await read_discovery_handoff(handoff=handoff, user_id=user_id, client_id=client_id)
    pages = _json_array(result.get("pages"))
    instagram_accounts = _json_array(result.get("instagram_accounts"))
    result["organic_status"] = "available" if instagram_accounts else "asset_unavailable"
    result["availability_code"] = (
        None if instagram_accounts else
        "META_PAGE_UNAVAILABLE" if not pages else
        "META_INSTAGRAM_UNAVAILABLE"
    )
    result["message"] = (
        None if instagram_accounts else
        "Nenhuma Página acessível foi encontrada para esta autorização."
        if not pages else
        "As Páginas acessíveis não possuem uma conta profissional do Instagram vinculada."
    )
    return result


async def _manual_meta_connection(
    *, client_id: str, connection_id: str
) -> tuple[Dict[str, Any], str, Dict[str, Any]]:
    try:
        connection = await get_connection(client_id, connection_id, include_token=True)
    except IntegrationError as exc:
        if exc.code == "OAUTH_CONNECTION_TENANT_MISMATCH":
            raise IntegrationError(
                "A conexão Meta pertence a outra empresa.", status_code=403,
                code="META_CONNECTION_TENANT_MISMATCH", provider="meta",
            ) from exc
        raise
    if _safe_str(connection.get("provider")) != "meta":
        raise IntegrationError(
            "Conexão Meta não encontrada.", status_code=404,
            code="META_CONNECTION_NOT_FOUND", provider="meta",
        )
    status = _safe_str(connection.get("status")).lower()
    if (status and status not in {"connected", "selection_required"}) or connection.get("disconnected_at"):
        raise IntegrationError(
            "A conexão Meta está desconectada e exige nova autorização.", status_code=409,
            code="META_CONNECTION_DISCONNECTED", provider="meta",
        )
    try:
        token_payload = json.loads(_safe_str(connection.get("_token")) or "{}")
    except (TypeError, ValueError) as exc:
        raise IntegrationError(
            "A conexão Meta exige nova autorização.", status_code=401,
            code="META_REAUTH_REQUIRED", provider="meta",
        ) from exc
    access_token = _safe_str(token_payload.get("access_token"))
    if not access_token:
        raise IntegrationError(
            "A conexão Meta exige nova autorização.", status_code=401,
            code="META_REAUTH_REQUIRED", provider="meta",
        )
    return connection, access_token, _json_object(connection.get("metadata"))


async def validate_manual_meta_assets(
    *, client_id: str, connection_id: str,
    page_id: str = "", instagram_id: str = "", ad_account_id: str = "",
) -> Dict[str, Any]:
    _, access_token, previous = await _manual_meta_connection(
        client_id=client_id, connection_id=connection_id
    )
    page: Dict[str, Any] | None = None
    instagram: Dict[str, Any] | None = None
    ad_account: Dict[str, Any] | None = None

    normalized_page = _manual_numeric_id(
        page_id, code="META_MANUAL_PAGE_INVALID", label="Facebook Page ID"
    ) if _safe_str(page_id) else ""
    normalized_instagram = _manual_numeric_id(
        instagram_id, code="META_MANUAL_INSTAGRAM_INVALID", label="Instagram Business Account ID"
    ) if _safe_str(instagram_id) else ""
    raw_ad = _safe_str(ad_account_id).removeprefix("act_")
    normalized_ad = _normalize_ad_account_id(_manual_numeric_id(
        raw_ad, code="META_MANUAL_AD_ACCOUNT_INVALID", label="Meta Ad Account ID"
    )) if _safe_str(ad_account_id) else ""
    if not any((normalized_page, normalized_instagram, normalized_ad)):
        raise IntegrationError(
            "Informe ao menos um ativo Meta para validar.", status_code=400,
            code="META_MANUAL_PAGE_INVALID", provider="meta",
        )

    if normalized_page:
        try:
            payload = await _meta_get(
                f"/{normalized_page}", {
                    "fields": "id,name,instagram_business_account{id,username}",
                    "access_token": access_token,
                },
            )
        except MetaApiError as exc:
            raise _manual_meta_api_error(
                exc, code="META_MANUAL_PAGE_INVALID", label="Facebook Page",
            ) from exc
        page = {
            "id": _safe_str(payload.get("id")),
            "name": _safe_str(payload.get("name")),
            "instagram_business_account": _json_object(payload.get("instagram_business_account")),
        }
        if page["id"] != normalized_page:
            raise IntegrationError(
                "A Página informada não pôde ser validada.", status_code=400,
                code="META_MANUAL_PAGE_INVALID", provider="meta",
            )

    if normalized_instagram:
        try:
            payload = await _meta_get(
                f"/{normalized_instagram}", {
                    "fields": "id,username,name", "access_token": access_token,
                },
            )
        except MetaApiError as exc:
            raise _manual_meta_api_error(
                exc, code="META_MANUAL_INSTAGRAM_INVALID", label="Instagram Business Account",
            ) from exc
        instagram = {
            "id": _safe_str(payload.get("id")),
            "username": _safe_str(payload.get("username")),
            "name": _safe_str(payload.get("name")),
        }
        if instagram["id"] != normalized_instagram:
            raise IntegrationError(
                "A conta profissional do Instagram não pôde ser validada.", status_code=400,
                code="META_MANUAL_INSTAGRAM_INVALID", provider="meta",
            )

    effective_page = normalized_page or _safe_str(previous.get("selected_page_id"))
    if normalized_instagram and effective_page:
        linked_id = _safe_str((_json_object(page.get("instagram_business_account")) if page else {}).get("id"))
        if not page:
            try:
                page_payload = await _meta_get(
                    f"/{effective_page}", {
                        "fields": "id,name,instagram_business_account{id,username}",
                        "access_token": access_token,
                    },
                )
                linked_id = _safe_str(_json_object(page_payload.get("instagram_business_account")).get("id"))
            except MetaApiError as exc:
                raise _manual_meta_api_error(
                    exc, code="META_MANUAL_PAGE_INVALID", label="Facebook Page",
                ) from exc
        if linked_id != normalized_instagram:
            raise IntegrationError(
                "O Instagram informado não está vinculado à Página selecionada.",
                status_code=409, code="META_PAGE_INSTAGRAM_MISMATCH", provider="meta",
            )

    if normalized_ad:
        try:
            payload = await _meta_get(
                f"/{normalized_ad}", {
                    "fields": "id,account_id,name,account_status", "access_token": access_token,
                },
            )
        except MetaApiError as exc:
            raise _manual_meta_api_error(
                exc, code="META_MANUAL_AD_ACCOUNT_INVALID", label="Meta Ad Account",
            ) from exc
        returned_id = _normalize_ad_account_id(
            _safe_str(payload.get("id")) or _safe_str(payload.get("account_id"))
        )
        status = int(payload.get("account_status") or 0)
        if returned_id != normalized_ad:
            raise IntegrationError(
                "A conta de anúncios não pôde ser validada.", status_code=400,
                code="META_MANUAL_AD_ACCOUNT_INVALID", provider="meta",
            )
        if status != 1:
            raise IntegrationError(
                "A conta de anúncios informada não está ativa.", status_code=409,
                code="META_AD_ACCOUNT_DISABLED", provider="meta",
            )
        ad_account = {
            "id": normalized_ad, "name": _safe_str(payload.get("name")),
            "account_status": status,
        }

    return {
        "ok": True, "client_id": client_id, "connection_id": connection_id,
        "page": page, "instagram": instagram, "ad_account": ad_account,
    }


async def save_manual_meta_assets(
    *, user_id: str, client_id: str, connection_id: str,
    page_id: str = "", instagram_id: str = "", ad_account_id: str = "",
) -> Dict[str, Any]:
    connection, access_token, previous = await _manual_meta_connection(
        client_id=client_id, connection_id=connection_id
    )
    validated = await validate_manual_meta_assets(
        client_id=client_id, connection_id=connection_id,
        page_id=page_id, instagram_id=instagram_id, ad_account_id=ad_account_id,
    )
    page = _json_object(validated.get("page"))
    instagram = _json_object(validated.get("instagram"))
    ad_account = _json_object(validated.get("ad_account"))
    selected_page_id = _safe_str(page.get("id")) or _safe_str(previous.get("selected_page_id"))
    selected_instagram_id = _safe_str(instagram.get("id")) or _safe_str(previous.get("selected_instagram_id"))
    selected_ad_id = _safe_str(ad_account.get("id")) or _safe_str(previous.get("selected_ad_account_id"))
    page_ids = {_safe_str(value) for value in _json_array(previous.get("page_ids")) if _safe_str(value)}
    ig_ids = {_safe_str(value) for value in _json_array(previous.get("instagram_ig_user_ids")) if _safe_str(value)}
    ad_ids = {_normalize_ad_account_id(_safe_str(value)) for value in _json_array(previous.get("ad_account_ids")) if _safe_str(value)}
    if _safe_str(page.get("id")):
        page_ids.add(_safe_str(page.get("id")))
    if _safe_str(instagram.get("id")):
        ig_ids.add(_safe_str(instagram.get("id")))
    if _safe_str(ad_account.get("id")):
        ad_ids.add(_safe_str(ad_account.get("id")))

    now_iso = _iso(_now_utc())
    scopes = _json_array(connection.get("scopes"))
    encrypted_access = encrypt_secret(access_token)
    organic_connection: Dict[str, Any] = {}
    if instagram:
        organic_connection = await _save_connection_row({
            "client_id": client_id, "platform": "instagram", "connection_type": "organic",
            "meta_user_id": _safe_str(previous.get("meta_user_id")),
            "ig_user_id": selected_instagram_id,
            "username": _safe_str(instagram.get("username")),
            "business_id": selected_page_id,
            "ad_account_id": "", "ad_account_name": "", "scopes_json": scopes,
            "encrypted_access_token": encrypted_access, "access_token": None,
            "token_expires_at": connection.get("token_expires_at"),
            "expires_at": connection.get("token_expires_at"),
            "last_validated_at": now_iso, "last_sync_status": "never",
            "requires_reauth": False, "is_active": True, "last_error": None,
            "status": "active", "updated_at": now_iso,
        })
    if ad_account:
        await _save_connection_row({
            "client_id": client_id, "platform": "meta_ads", "connection_type": "paid",
            "meta_user_id": _safe_str(previous.get("meta_user_id")),
            "ig_user_id": "", "username": "", "business_id": "",
            "ad_account_id": selected_ad_id, "ad_account_name": _safe_str(ad_account.get("name")),
            "scopes_json": scopes, "encrypted_access_token": encrypted_access,
            "access_token": None, "token_expires_at": connection.get("token_expires_at"),
            "expires_at": connection.get("token_expires_at"),
            "last_validated_at": now_iso, "last_sync_status": "never",
            "requires_reauth": False, "is_active": True, "last_error": None,
            "status": "active", "updated_at": now_iso,
        })

    metadata = {
        **previous,
        "page_ids": sorted(page_ids), "instagram_ig_user_ids": sorted(ig_ids),
        "ad_account_ids": sorted(ad_ids),
        "selected_page_id": selected_page_id or None,
        "selected_page_name": _safe_str(page.get("name")) or previous.get("selected_page_name"),
        "selected_instagram_id": selected_instagram_id or None,
        "selected_instagram_username": _safe_str(instagram.get("username")) or previous.get("selected_instagram_username"),
        "selected_ad_account_id": selected_ad_id or None,
        "selected_ad_account_name": _safe_str(ad_account.get("name")) or previous.get("selected_ad_account_name"),
        "organic_selection_source": "manual" if page or instagram else previous.get("organic_selection_source"),
        "ads_selection_source": "manual" if ad_account else previous.get("ads_selection_source"),
        "organic_status": "connected" if selected_instagram_id else "asset_required",
        "ads_status": "connected" if selected_ad_id else "asset_required",
        "coverage": "full" if selected_instagram_id and selected_ad_id else "partial",
        "selection_required": not bool(selected_instagram_id or selected_ad_id),
    }
    updated = await sb_update(
        "integration_connections",
        filters={"id": f"eq.{connection_id}", "client_id": f"eq.{client_id}", "provider": "eq.meta"},
        patch={
            "status": "connected", "metadata": metadata,
            "account_id": selected_ad_id or selected_instagram_id or connection.get("account_id"),
            "account_name": _safe_str(ad_account.get("name")) or _safe_str(instagram.get("username")) or connection.get("account_name"),
            "last_error": None, "updated_at": now_iso,
        },
        returning="representation",
    )
    organic_projection_consistent = (
        not selected_instagram_id
        or (
            _safe_str(organic_connection.get("id"))
            and _safe_str(organic_connection.get("client_id")) == _safe_str(client_id)
            and _safe_str(organic_connection.get("ig_user_id")) == selected_instagram_id
            and _safe_str(organic_connection.get("business_id")) == selected_page_id
        )
    )
    if not organic_projection_consistent:
        raise IntegrationError(
            "A projeção orgânica criada não corresponde aos ativos Meta selecionados.",
            status_code=409, code="META_CONNECTION_DRIFT", provider="meta",
        )
    await audit_connection(
        client_id=client_id, connection_id=connection_id, user_id=user_id,
        event_type="manual_assets_selected",
        details={
            "provider": "meta", "fields": sorted(
                key for key, value in {
                    "page_id": page_id, "instagram_id": instagram_id, "ad_account_id": ad_account_id,
                }.items() if _safe_str(value)
            ),
        },
    )
    await invalidate_namespace("integration_connections")
    return {
        "ok": True,
        "validated": validated,
        "connection": updated[0] if updated else {},
        "organic_connection_id": _safe_str(organic_connection.get("id")) or None,
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
        "meta_user_json": {
            **_json_object(discovered.get("meta_user")),
            "business_managers": _json_array(discovered.get("business_managers")),
        },
        "instagram_accounts_json": _json_array(discovered.get("instagram_accounts")),
        "pages_json": _json_array(discovered.get("pages")),
        "ad_accounts_json": _json_array(discovered.get("ad_accounts")),
        "scopes_json": _json_array(discovered.get("scopes")),
    }
    try:
        await sb_insert(_HANDOFF_TABLE, row, returning="minimal")
    except httpx.HTTPStatusError as exc:
        raise _handoff_schema_error(exc) from exc
    return handoff


async def save_pending_meta_authorization(
    *,
    user_id: str,
    client_id: str,
    access_token: str,
    expires_at: Optional[str],
    discovered: Dict[str, Any],
    handoff: str,
) -> Dict[str, Any]:
    meta_user = _json_object(discovered.get("meta_user"))
    meta_user_id = _safe_str(meta_user.get("id"))
    return await upsert_connection(
        client_id=client_id,
        provider="meta",
        external_key=meta_user_id or f"meta:{client_id}",
        token_payload=json.dumps({"access_token": access_token}),
        user_id=user_id,
        status="selection_required",
        account_id=meta_user_id or None,
        account_name=_safe_str(meta_user.get("name")) or None,
        token_expires_at=_safe_str(expires_at) or None,
        scopes=[_safe_str(scope) for scope in _json_array(discovered.get("scopes")) if _safe_str(scope)],
        metadata={
            "integration_product": "meta",
            "selection_required": True,
            "oauth_handoff": _safe_str(handoff),
            "discovered_instagram_count": len(_json_array(discovered.get("instagram_accounts"))),
            "discovered_ad_account_count": len(_json_array(discovered.get("ad_accounts"))),
        },
    )


async def read_discovery_handoff(*, handoff: str, user_id: str, client_id: Optional[str] = None) -> Dict[str, Any]:
    item = await _load_handoff_row(handoff=handoff)
    if _safe_str(item.get("user_id")) != _safe_str(user_id):
        raise RuntimeError("Sessão OAuth não pertence ao usuário autenticado.")
    if client_id and _safe_str(item.get("client_id")) != _safe_str(client_id):
        raise RuntimeError("Sessão OAuth não pertence ao cliente informado.")

    instagram_accounts = _json_array(item.get("instagram_accounts_json"))
    pages_by_id = {
        _safe_str(account.get("business_id")): {
            "page_id": _safe_str(account.get("business_id")),
            "page_name": _safe_str(account.get("business_name")),
        }
        for account in instagram_accounts
        if isinstance(account, dict) and _safe_str(account.get("business_id"))
    }
    for page in _json_array(item.get("pages_json")):
        page_id = _safe_str((page or {}).get("page_id"))
        if page_id:
            pages_by_id[page_id] = {
                "page_id": page_id,
                "page_name": _safe_str((page or {}).get("page_name")),
            }
    return {
        "handoff": _safe_str(item.get("handoff")),
        "client_id": _safe_str(item.get("client_id")),
        "meta_user": _json_object(item.get("meta_user_json")),
        "business_managers": _json_array(_json_object(item.get("meta_user_json")).get("business_managers")),
        "pages": list(pages_by_id.values()),
        "instagram_accounts": instagram_accounts,
        "ad_accounts": _json_array(item.get("ad_accounts_json")),
        "scopes": _json_array(item.get("scopes_json")),
        "expires_at": item.get("expires_at"),
    }


async def read_latest_discovery_handoff(*, user_id: str, client_id: str) -> Dict[str, Any]:
    await _cleanup_handoffs()
    rows = await sb_select(
        _HANDOFF_TABLE,
        filters={
            "user_id": f"eq.{_safe_str(user_id)}",
            "client_id": f"eq.{_safe_str(client_id)}",
            "finalized_at": "is.null",
        },
        order="created_at.desc",
        limit=1,
    )
    if not rows:
        raise RuntimeError("Nenhuma seleção de ativos Meta pendente foi encontrada. Corrija a conexão para autorizar novamente.")
    return await read_discovery_handoff(
        handoff=_safe_str(rows[0].get("handoff")),
        user_id=user_id,
        client_id=client_id,
    )


async def _save_connection_row(row: Dict[str, Any]) -> Dict[str, Any]:
    filters = _upsert_connection_match_filters(
        client_id=_safe_str(row.get("client_id")),
        platform=_safe_str(row.get("platform")),
        connection_type=_safe_str(row.get("connection_type")),
        ig_user_id=_safe_str(row.get("ig_user_id")),
        ad_account_id=_safe_str(row.get("ad_account_id")),
    )

    existing = await sb_select("meta_connections", filters=filters, limit=2)
    if len(existing) > 1:
        raise IntegrationError(
            "Mais de uma projeção operacional Meta corresponde aos mesmos ativos.",
            status_code=409, code="META_CONNECTION_DRIFT", provider="meta",
        )
    if existing:
        conn_id = _safe_str(existing[0].get("id"))
        await sb_update("meta_connections", filters={"id": f"eq.{conn_id}"}, patch=row, returning="minimal")
        rows = await sb_select("meta_connections", filters={"id": f"eq.{conn_id}"}, limit=1)
        return rows[0] if rows else {"id": conn_id, **row}

    inserted = await sb_insert("meta_connections", row, returning="representation")
    return inserted or row


def validate_page_selection(
    *,
    discovered_instagram_accounts: List[Any],
    requested_page_ids: set[str],
    selected_instagram_accounts: List[Any],
) -> None:
    discovered_page_ids = {
        _safe_str((account or {}).get("business_id"))
        for account in discovered_instagram_accounts
        if isinstance(account, dict) and _safe_str(account.get("business_id"))
    }
    if not requested_page_ids.issubset(discovered_page_ids):
        raise RuntimeError("A Página selecionada não pertence aos ativos descobertos nesta autorização.")
    if any(
        _safe_str((account or {}).get("business_id")) not in requested_page_ids
        for account in selected_instagram_accounts
    ):
        raise RuntimeError(
            "Selecione a Página do Facebook associada a cada conta profissional do Instagram."
        )


async def save_connections(
    *,
    user_id: str,
    client_id: str,
    handoff: str,
    page_ids: List[str],
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

    pages_requested = {_safe_str(i) for i in page_ids if _safe_str(i)}
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
    if len(selected_igs) > 1:
        raise IntegrationError(
            "Selecione apenas uma conta do Instagram por conexão.",
            status_code=409, code="META_INSTAGRAM_SELECTION_AMBIGUOUS", provider="meta",
        )
    if len(selected_ads) > 1:
        raise IntegrationError(
            "Selecione apenas uma conta Meta Ads por conexão.",
            status_code=409, code="META_AD_ACCOUNT_SELECTION_AMBIGUOUS", provider="meta",
        )

    validate_page_selection(
        discovered_instagram_accounts=_json_array(item.get("instagram_accounts_json")),
        requested_page_ids=pages_requested,
        selected_instagram_accounts=selected_igs,
    )

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

    generic_rows = await sb_select(
        "integration_connections",
        filters={
            "client_id": f"eq.{client_id}", "provider": "eq.meta",
            "status": "in.(connected,selection_required)", "disconnected_at": "is.null",
        },
        order="updated_at.desc",
        limit=2,
    )
    if len(generic_rows) > 1:
        raise IntegrationError(
            "Mais de uma conexão-base Meta está ativa para esta empresa.",
            status_code=409, code="CONNECTION_AMBIGUOUS", provider="meta",
        )
    previous_generic = generic_rows[0] if generic_rows else {}
    previous_metadata = _json_object(previous_generic.get("metadata"))
    selected_ad = selected_ads[0] if selected_ads else {}
    selected_ad_id = (
        _normalize_ad_account_id(_safe_str(selected_ad.get("ad_account_id")))
        or _normalize_ad_account_id(_safe_str(previous_metadata.get("selected_ad_account_id")))
    )
    selected_ad_name = (
        _safe_str(selected_ad.get("ad_account_name"))
        or _safe_str(previous_metadata.get("selected_ad_account_name"))
    )
    preserved_ad_ids = {
        _normalize_ad_account_id(_safe_str(value))
        for value in _json_array(previous_metadata.get("ad_account_ids"))
        if _safe_str(value)
    }
    merged_ad_ids = sorted(ads_requested | preserved_ad_ids | ({selected_ad_id} if selected_ad_id else set()))
    selected_ig = selected_igs[0] if selected_igs else {}
    selected_page_id = _safe_str(selected_ig.get("business_id"))
    selected_page_name = _safe_str(selected_ig.get("business_name"))
    selected_ig_id = _safe_str(selected_ig.get("ig_user_id"))
    selected_ig_username = _safe_str(selected_ig.get("username"))
    generic_connection = await upsert_connection(
        client_id=client_id,
        provider="meta",
        external_key=f"meta:{client_id}",
        token_payload=json.dumps({"access_token": access_token}),
        user_id=user_id,
        status="connected" if selected_ad_id or selected_ig_id else "selection_required",
        account_id=selected_ad_id or None,
        account_name=selected_ad_name or None,
        token_expires_at=_safe_str(expires_at) or None,
        scopes=[_safe_str(scope) for scope in scopes if _safe_str(scope)],
        metadata={
            **previous_metadata,
            "integration_product": "meta",
            "selection_required": not bool(selected_ad_id or selected_ig_id),
            "oauth_handoff": None,
            "meta_user_id": current_meta_user_id or None,
            "meta_user_name": _safe_str(meta_user.get("name")) or None,
            "page_ids": sorted(pages_requested),
            "instagram_ig_user_ids": sorted(ig_requested),
            "selected_page_id": selected_page_id or None,
            "selected_page_name": selected_page_name or None,
            "selected_instagram_id": selected_ig_id or None,
            "selected_instagram_username": selected_ig_username or None,
            "organic_status": "connected" if selected_ig_id else "asset_required",
            "ads_status": "connected" if selected_ad_id else "asset_required",
            "coverage": "full" if selected_ig_id and selected_ad_id else "partial",
            "ad_account_ids": merged_ad_ids,
            "selected_ad_account_id": selected_ad_id or None,
            "selected_ad_account_name": selected_ad_name or None,
            "accessible_ad_accounts": [
                {
                    "ad_account_id": _normalize_ad_account_id(_safe_str(ad.get("ad_account_id"))),
                    "ad_account_name": _safe_str(ad.get("ad_account_name")),
                    "account_status": ad.get("account_status"),
                    "currency": _safe_str(ad.get("currency")),
                    "timezone_name": _safe_str(ad.get("timezone_name")),
                }
                for ad in _json_array(item.get("ad_accounts_json"))
            ],
        },
    )

    try:
        await sb_update(
            _HANDOFF_TABLE,
            filters={"handoff": f"eq.{token}"},
            patch={"finalized_at": now_iso, "consumed_at": now_iso},
            returning="minimal",
        )
    except httpx.HTTPStatusError as exc:
        raise _handoff_schema_error(exc) from exc

    await invalidate_namespace("integration_connections")
    return {
        "ok": True,
        "client_id": client_id,
        "saved_count": len(saved),
        "connections": saved,
        "integration_connection": generic_connection,
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


async def select_paid_connection(*, client_id: str, ad_account_id: str, user_id: str) -> Dict[str, Any]:
    normalized = _normalize_ad_account_id(ad_account_id)
    rows = await sb_select(
        "meta_connections",
        filters={
            "client_id": f"eq.{_safe_str(client_id)}",
            "platform": "eq.meta_ads",
            "connection_type": "eq.paid",
            "ad_account_id": f"eq.{normalized}",
            "status": "eq.active",
        },
        limit=2,
    )
    if len(rows) > 1:
        raise IntegrationError(
            "Mais de uma conexão Meta Ads corresponde à conta selecionada.",
            status_code=409, code="CONNECTION_AMBIGUOUS", provider="meta",
        )
    if not rows:
        raise RuntimeError("A conta de anúncios selecionada não pertence à empresa ativa.")
    selected = rows[0]
    if "ads_read" not in {_safe_str(scope) for scope in _json_array(selected.get("scopes_json"))}:
        raise RuntimeError("A autorização Meta não possui a permissão ads_read.")
    await sb_update(
        "meta_connections",
        filters={"id": f"eq.{_safe_str(selected.get('id'))}", "client_id": f"eq.{_safe_str(client_id)}"},
        patch={"status": "active", "is_active": True, "last_error": None, "updated_at": _iso(_now_utc())},
        returning="minimal",
    )
    generic_rows = await sb_select(
        "integration_connections",
        filters={
            "client_id": f"eq.{_safe_str(client_id)}", "provider": "eq.meta",
            "status": "in.(connected,selection_required)", "disconnected_at": "is.null",
        },
        order="updated_at.desc",
        limit=2,
    )
    if len(generic_rows) > 1:
        raise IntegrationError(
            "Mais de uma conexão-base Meta está ativa para esta empresa.",
            status_code=409, code="CONNECTION_AMBIGUOUS", provider="meta",
        )
    if not generic_rows:
        raise RuntimeError("Conexão-base Meta não encontrada para esta empresa.")
    generic = generic_rows[0]
    metadata = _json_object(generic.get("metadata"))
    updated = await sb_update(
        "integration_connections",
        filters={"id": f"eq.{_safe_str(generic.get('id'))}", "client_id": f"eq.{_safe_str(client_id)}"},
        patch={
            "status": "connected",
            "external_key": f"meta:{_safe_str(client_id)}",
            "account_id": normalized,
            "account_name": _safe_str(selected.get("ad_account_name")) or normalized,
            "metadata": {
                **metadata,
                "selection_required": False,
                "selected_ad_account_id": normalized,
                "selected_ad_account_name": _safe_str(selected.get("ad_account_name")) or None,
            },
            "last_error": None,
            "updated_at": _iso(_now_utc()),
        },
        returning="representation",
    )
    await audit_connection(
        client_id=client_id,
        connection_id=_safe_str(generic.get("id")),
        user_id=user_id,
        event_type="account_selected",
        details={"provider": "meta", "ad_account_id": normalized},
    )
    await invalidate_namespace("integration_connections")
    return {
        "connection_id": _safe_str(selected.get("id")),
        "ad_account_id": normalized,
        "ad_account_name": _safe_str(selected.get("ad_account_name")),
        "integration_connection": updated[0] if updated else {},
    }


async def disconnect_connection(client_id: str, connection_id: str, user_id: str) -> Dict[str, Any]:
    rows = await sb_update(
        "meta_connections",
        filters={
            "id": f"eq.{_safe_str(connection_id)}",
            "client_id": f"eq.{_safe_str(client_id)}",
            "status": "neq.disconnected",
        },
        patch={
            "status": "disconnected",
            "requires_reauth": False,
            "is_active": False,
            "encrypted_access_token": None,
            "access_token": None,
            "token_expires_at": None,
            "expires_at": None,
            "last_error": None,
            "updated_at": _iso(_now_utc()),
        },
        returning="representation",
    )
    if not rows:
        persisted = await sb_select(
            "meta_connections",
            select="id,status,platform,connection_type",
            filters={"id": f"eq.{_safe_str(connection_id)}", "client_id": f"eq.{_safe_str(client_id)}"},
            limit=1,
        )
        if not persisted:
            raise RuntimeError("Conexão não encontrada")
        if _safe_str(persisted[0].get("status")).lower() != "disconnected":
            raise RuntimeError("Não foi possível confirmar a desconexão Meta")
        return {
            "ok": True,
            "disconnect_result": {
                "local_status": "already_disconnected",
                "local_token_removed": True,
                "external_revocation": "not_supported",
            },
            "connection": {
                "id": _safe_str(persisted[0].get("id")),
                "status": "disconnected",
                "platform": _safe_str(persisted[0].get("platform")),
                "connection_type": _safe_str(persisted[0].get("connection_type")),
            },
        }
    row = rows[0]
    await audit_connection(
        client_id=client_id,
        connection_id=connection_id,
        user_id=user_id,
        event_type="disconnected",
        details={
            "provider": "meta",
            "platform": _safe_str(row.get("platform")),
            "connection_type": _safe_str(row.get("connection_type")),
            "local_status": "disconnected",
            "local_token_removed": True,
            "external_revocation": "not_supported",
        },
    )
    remaining = await sb_select(
        "meta_connections",
        select="id",
        filters={"client_id": f"eq.{_safe_str(client_id)}", "status": "eq.active"},
        limit=1,
    )
    if not remaining:
        generic_rows = await sb_select(
            "integration_connections",
            select="id,status",
            filters={"client_id": f"eq.{_safe_str(client_id)}", "provider": "eq.meta"},
            limit=20,
        )
        for generic in generic_rows:
            await disconnect_generic_connection(client_id, _safe_str(generic.get("id")), user_id)
    await invalidate_namespace("integration_connections")
    return {
        "ok": True,
        "disconnect_result": {
            "local_status": "disconnected",
            "local_token_removed": True,
            "external_revocation": "not_supported",
        },
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
