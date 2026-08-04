
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from urllib.parse import urlencode

import httpx

from .generic_connections import get_connection, upsert_connection
from .crypto import decrypt_secret, encrypt_secret
from .ig_supabase import sb_select, sb_update
from .oauth_state import create_oauth_state
from .integration_errors import IntegrationError, from_httpx_error, google_api_error

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_BASIC_SCOPES = ("openid", "email")
GOOGLE_PRODUCT_SCOPES = {
    "ga4": "https://www.googleapis.com/auth/analytics.readonly",
    "google_ads": "https://www.googleapis.com/auth/adwords",
}
_REFRESH_LOCKS: Dict[str, asyncio.Lock] = {}


def _legacy_token_value(row: Dict[str, Any], column: str, token_key: str) -> str:
    encrypted = str(row.get(column) or "").strip()
    if not encrypted:
        return ""
    try:
        decrypted = str(decrypt_secret(encrypted) or "").strip()
    except (RuntimeError, TypeError, ValueError):
        return ""
    if not decrypted:
        return ""
    try:
        decoded = json.loads(decrypted)
    except (TypeError, ValueError):
        return decrypted
    if isinstance(decoded, dict):
        return str(decoded.get(token_key) or decoded.get("token") or "").strip()
    return decrypted if isinstance(decoded, str) else ""


def _connection_token_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    raw_token = str(row.get("_token") or "").strip()
    try:
        token = json.loads(raw_token or "{}")
        if not isinstance(token, dict):
            token = {"access_token": str(token).strip()} if isinstance(token, str) else {}
    except (TypeError, ValueError):
        # Alguns registros transitórios gravaram encrypted_token como token
        # puro, antes da padronização do envelope JSON.
        token = {"access_token": raw_token} if raw_token else {}
    # Compatibilidade com o schema anterior. Os valores só são usados quando
    # realmente existem e podem ser descriptografados; nenhum token é criado.
    if not str(token.get("access_token") or "").strip():
        access_token = _legacy_token_value(row, "encrypted_access_token", "access_token")
        if access_token:
            token["access_token"] = access_token
    if not str(token.get("refresh_token") or "").strip():
        refresh_token = _legacy_token_value(row, "encrypted_refresh_token", "refresh_token")
        if refresh_token:
            token["refresh_token"] = refresh_token
    if not str(token.get("expires_at") or "").strip() and row.get("token_expires_at"):
        token["expires_at"] = str(row.get("token_expires_at"))
    return token


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _sanitized_google_error(response: httpx.Response) -> Dict[str, Any]:
    try:
        payload = response.json()
    except (TypeError, ValueError):
        payload = {}
    error = payload.get("error") if isinstance(payload, dict) and isinstance(payload.get("error"), dict) else {}
    details = error.get("details") if isinstance(error.get("details"), list) else []
    reasons = sorted({
        str(item.get("reason") or item.get("reasonCode") or "").strip()
        for item in details
        if isinstance(item, dict) and str(item.get("reason") or item.get("reasonCode") or "").strip()
    })
    return {
        "http_status": int(response.status_code or 0),
        "google_status": str(error.get("status") or "")[:80],
        "reasons": reasons[:8],
        "message": str(error.get("message") or "")[:240],
    }


def settings() -> Dict[str, str]:
    values = {
        "client_id": (
            _env("GOOGLE_OAUTH_CLIENT_ID")
            or _env("GOOGLE_CLIENT_ID")
        ),
        "client_secret": (
            _env("GOOGLE_OAUTH_CLIENT_SECRET")
            or _env("GOOGLE_CLIENT_SECRET")
        ),
        "redirect_uri": (
            _env("GOOGLE_OAUTH_REDIRECT_URI")
            or _env("GOOGLE_REDIRECT_URI")
        ),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(f"OAuth Google não configurado: {', '.join(missing)}")
    return values


def normalize_integration_product(product: str) -> str:
    normalized = str(product or "").strip().lower()
    if normalized == "ads":
        normalized = "google_ads"
    if normalized not in GOOGLE_PRODUCT_SCOPES:
        raise RuntimeError("Produto Google inválido. Use ga4 ou google_ads.")
    return normalized


def scopes_for_product(product: str) -> List[str]:
    normalized = normalize_integration_product(product)
    product_scope = GOOGLE_PRODUCT_SCOPES.get(normalized)
    if not product_scope:
        raise RuntimeError("Produto Google inválido. Use ga4 ou google_ads.")
    return [*GOOGLE_BASIC_SCOPES, product_scope]


async def authorization_url(*, user_id: str, client_id: str, product: str) -> str:
    config = settings()
    normalized_product = normalize_integration_product(product)
    state = await create_oauth_state(
        provider="google",
        user_id=user_id,
        client_id=client_id,
        redirect_uri=config["redirect_uri"],
        context={"integration_product": normalized_product},
    )
    params = {
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "scope": " ".join(scopes_for_product(normalized_product)),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str, redirect_uri: str) -> Dict[str, Any]:
    config = settings()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("access_token"):
        raise RuntimeError("Google não retornou access_token.")
    return payload


async def fetch_google_identity(access_token: str) -> Dict[str, str]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    response.raise_for_status()
    data = response.json()
    return {"sub": str(data.get("sub") or ""), "email": str(data.get("email") or "")}


async def save_google_authorization(
    *, client_id: str, user_id: str, token: Dict[str, Any], identity: Dict[str, str], product: str
) -> Dict[str, Any]:
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=max(60, int(token.get("expires_in") or 3600)))
    ).isoformat()
    normalized_product = normalize_integration_product(product)
    target_provider = normalized_product
    existing = await sb_select(
        "integration_connections",
        filters={"client_id": f"eq.{client_id}"},
        limit=100,
    )
    google_existing = [row for row in existing if str(row.get("provider") or "") in {"ga4", "google_ads"}]
    other_active = [
        row
        for row in google_existing
        if str(row.get("provider") or "") == target_provider
        if str(row.get("external_key") or "") != identity["sub"]
        and str(row.get("status") or "") != "disconnected"
    ]
    for row in other_active:
        await sb_update(
            "integration_connections",
            filters={"id": f"eq.{row['id']}", "client_id": f"eq.{client_id}"},
            patch={
                "status": "disconnected",
                "disconnected_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            returning="minimal",
        )
    same_identity = next(
        (
            row
            for row in google_existing
            if str(row.get("external_key") or "") == identity["sub"]
            and str(row.get("provider") or "") == target_provider
        ),
        None,
    )
    # Nunca reutilize refresh token de outro produto: um token emitido para Ads
    # não ganha o escopo do GA4 (e vice-versa) apenas por pertencer à mesma conta.
    token_source = same_identity
    refresh_token = str(token.get("refresh_token") or "").strip()
    previous_metadata: Dict[str, Any] = {}
    if same_identity:
        previous_metadata = (
            same_identity.get("metadata")
            if isinstance(same_identity.get("metadata"), dict)
            else {}
        )
    if not refresh_token:
        encrypted = str((token_source or {}).get("encrypted_token") or "").strip()
        if encrypted:
            try:
                previous_token = json.loads(decrypt_secret(encrypted))
                refresh_token = str(previous_token.get("refresh_token") or "").strip()
            except (RuntimeError, TypeError, ValueError):
                refresh_token = ""
    if not refresh_token:
        raise RuntimeError(
            "Google não devolveu refresh_token. Revogue o acesso anterior e conecte novamente."
        )
    safe_token = {
        "access_token": token["access_token"],
        "refresh_token": refresh_token,
        "token_type": token.get("token_type"),
        "expires_at": expires_at,
    }
    granted_scopes = [scope for scope in str(token.get("scope") or "").split() if scope]
    if not granted_scopes:
        granted_scopes = scopes_for_product(normalized_product)
    return await upsert_connection(
        client_id=client_id,
        provider=target_provider,
        external_key=identity["sub"],
        token_payload=json.dumps(safe_token),
        user_id=user_id,
        status="selection_required",
        account_id=identity["sub"],
        account_name=identity["email"],
        token_expires_at=expires_at,
        scopes=granted_scopes,
        metadata={
            **previous_metadata,
            "integration_product": normalized_product,
            "google_email": identity["email"],
            "refresh_token_available": True,
            "ads_developer_token_configured": bool(_env("GOOGLE_ADS_DEVELOPER_TOKEN")),
        },
    )


async def _access_token(
    client_id: str,
    connection_id: str,
    *,
    expected_provider: str | None = None,
    request_id: str = "-",
) -> str:
    lock = _REFRESH_LOCKS.setdefault(connection_id, asyncio.Lock())
    async with lock:
        try:
            row = await get_connection(client_id, connection_id, include_token=True)
        except IntegrationError:
            raise
        except Exception as exc:
            raise IntegrationError(
                "Conexão Google não encontrada para a empresa selecionada.",
                status_code=404,
                code="GOOGLE_CONNECTION_NOT_FOUND",
                provider="google",
            ) from exc
        provider = str(row.get("provider") or "")
        if provider not in {"ga4", "google_ads"}:
            raise IntegrationError(
                "A conexão selecionada não é uma conexão Google.",
                status_code=404,
                code="GOOGLE_CONNECTION_NOT_FOUND",
                provider="google",
            )
        if expected_provider and provider != expected_provider:
            raise IntegrationError(
                "A conexão selecionada pertence a outro produto Google.",
                status_code=403,
                code="GOOGLE_SCOPE_INSUFFICIENT",
                provider="google",
            )
        status = str(row.get("status") or "").strip().lower()
        if status not in {"connected", "selection_required"} or row.get("disconnected_at"):
            raise IntegrationError(
                "A conexão Google está desconectada. Reconecte antes de sincronizar.",
                status_code=409,
                code="GOOGLE_CONNECTION_DISCONNECTED",
                provider="google",
            )
        token = _connection_token_payload(row)
        expires_raw = str(token.get("expires_at") or row.get("token_expires_at") or "")
        expires_at = (
            datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
            if expires_raw
            else None
        )
        if expires_at and expires_at > datetime.now(timezone.utc) + timedelta(minutes=2):
            access_token = str(token.get("access_token") or "")
            if not access_token:
                raise IntegrationError(
                    "A conexão Google requer nova autorização.",
                    status_code=401,
                    code="GOOGLE_REAUTH_REQUIRED",
                    provider="google",
                )
            return access_token
        refresh_token = str(token.get("refresh_token") or "")
        if not refresh_token:
            print(
                f"[google_oauth][token_refresh] request_id={request_id} connection_id={connection_id} "
                f"client_id={client_id} stage=refresh_blocked code=GOOGLE_REAUTH_REQUIRED_REFRESH_MISSING"
            )
            raise IntegrationError(
                "A conexão Google requer nova autorização.",
                status_code=409,
                code="GOOGLE_REAUTH_REQUIRED_REFRESH_MISSING",
                provider="google",
            )
        config = settings()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": config["client_id"],
                    "client_secret": config["client_secret"],
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        try:
            response.raise_for_status()
        except Exception as exc:
            try:
                refresh_error = str((response.json() or {}).get("error") or "")
            except (TypeError, ValueError):
                refresh_error = ""
            if refresh_error in {"invalid_grant", "invalid_client", "unauthorized_client"}:
                print(
                    f"[google_oauth][token_refresh] request_id={request_id} connection_id={connection_id} "
                    f"client_id={client_id} stage=refresh_failed code=GOOGLE_REAUTH_REQUIRED_INVALID_GRANT"
                )
                raise IntegrationError(
                    "A autorização Google foi revogada ou expirou. Conecte novamente.",
                    status_code=409,
                    code="GOOGLE_REAUTH_REQUIRED_INVALID_GRANT",
                    provider="google",
                ) from exc
            raise from_httpx_error(
                "google",
                exc,
                operation="renovar a autorização",
            ) from exc
        refreshed = response.json()
        access_token = str(refreshed.get("access_token") or "")
        if not access_token:
            raise IntegrationError(
                "A conexão Google requer nova autorização.",
                status_code=401,
                code="GOOGLE_REAUTH_REQUIRED",
                provider="google",
            )
        next_expires = (
            datetime.now(timezone.utc)
            + timedelta(seconds=int(refreshed.get("expires_in") or 3600))
        ).isoformat()
        token.update({"access_token": access_token, "expires_at": next_expires})
        await sb_update(
            "integration_connections",
            filters={"id": f"eq.{connection_id}", "client_id": f"eq.{client_id}"},
            patch={
                "encrypted_token": encrypt_secret(json.dumps(token)),
                "token_expires_at": next_expires,
                "status": "connected",
                "last_error": None,
            },
            returning="minimal",
        )
        print(
            f"[google_oauth][token_refresh] request_id={request_id} connection_id={connection_id} "
            f"client_id={client_id} stage=refresh_succeeded code=OK"
        )
        return access_token


async def get_google_access_token(client_id: str, connection_id: str, *, request_id: str = "-") -> str:
    return await _access_token(client_id, connection_id, request_id=request_id)


async def list_ga4_properties(client_id: str, connection_id: str, *, request_id: str = "-") -> List[Dict[str, Any]]:
    token = await _access_token(client_id, connection_id, expected_provider="ga4", request_id=request_id)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            "https://analyticsadmin.googleapis.com/v1beta/accountSummaries",
            headers={"Authorization": f"Bearer {token}"},
            params={"pageSize": "200"},
        )
    try:
        response.raise_for_status()
    except Exception as exc:
        diagnostic = _sanitized_google_error(response)
        print(
            "[google_oauth][ga4_properties_error] "
            f"request_id={request_id} connection_id={connection_id} client_id={client_id} stage=admin_api "
            f"http_status={diagnostic['http_status']} google_status={diagnostic['google_status'] or '-'} "
            f"reasons={','.join(diagnostic['reasons']) or '-'} message={diagnostic['message'] or '-'}"
        )
        raise google_api_error(
            response, api="Analytics Admin API",
            unavailable_code="GOOGLE_PROPERTY_UNAVAILABLE",
            operation="listar propriedades GA4",
        ) from exc
    out: List[Dict[str, Any]] = []
    account_summaries = response.json().get("accountSummaries") or []
    for account in account_summaries:
        for prop in account.get("propertySummaries") or []:
            out.append(
                {
                    "account": account.get("account"),
                    "account_name": account.get("displayName"),
                    "property": prop.get("property"),
                    "property_name": prop.get("displayName"),
                }
            )
    print(
        "[google_oauth][ga4_properties] "
        f"request_id={request_id} connection_id={connection_id} client_id={client_id} stage=complete "
        f"http_status={response.status_code} accounts={len(account_summaries)} properties={len(out)}"
    )
    return out


async def list_ga4_streams(
    client_id: str, connection_id: str, property_id: str
) -> List[Dict[str, Any]]:
    token = await _access_token(client_id, connection_id, expected_provider="ga4")
    normalized = str(property_id or "").strip().removeprefix("properties/")
    if not normalized:
        raise RuntimeError("property_id é obrigatório.")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"https://analyticsadmin.googleapis.com/v1beta/properties/{normalized}/dataStreams",
            headers={"Authorization": f"Bearer {token}"},
            params={"pageSize": "200"},
        )
    try:
        response.raise_for_status()
    except Exception as exc:
        raise google_api_error(
            response, api="Analytics Admin API",
            unavailable_code="GOOGLE_STREAM_UNAVAILABLE",
            operation="listar streams GA4",
        ) from exc
    return [
        {
            "name": row.get("name"),
            "display_name": row.get("displayName"),
            "type": row.get("type"),
            "web_stream_data": row.get("webStreamData"),
        }
        for row in response.json().get("dataStreams") or []
    ]


async def list_google_ads_accounts(client_id: str, connection_id: str) -> Dict[str, Any]:
    developer_token = _env("GOOGLE_ADS_DEVELOPER_TOKEN")
    if not developer_token:
        raise IntegrationError(
            "Configure o Developer Token do Google Ads antes de listar contas.",
            status_code=409,
            code="GOOGLE_ADS_SETUP_REQUIRED",
            provider="google",
        )
    token = await _access_token(client_id, connection_id, expected_provider="google_ads")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            "https://googleads.googleapis.com/v19/customers:listAccessibleCustomers",
            headers={
                "Authorization": f"Bearer {token}",
                "developer-token": developer_token,
            },
        )
    try:
        response.raise_for_status()
    except Exception as exc:
        raise from_httpx_error(
            "google",
            exc,
            operation="listar contas Google Ads",
        ) from exc
    accounts = [
        {"resource_name": item, "customer_id": str(item).split("/")[-1]}
        for item in response.json().get("resourceNames") or []
    ]
    return {"available": True, "accounts": accounts}
