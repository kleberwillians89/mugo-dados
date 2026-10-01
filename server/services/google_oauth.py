
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from urllib.parse import urlencode

import httpx

from .generic_connections import get_connection, upsert_connection
from .crypto import decrypt_secret, encrypt_secret
from .ig_supabase import sb_select, sb_update
from .oauth_state import create_oauth_state
from .google_ads_ids import format_google_ads_customer_id, normalize_google_ads_customer_id
from .integration_errors import IntegrationError, from_httpx_error, google_api_error, provider_http_error

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


def _safe_token_diagnostics(row: Dict[str, Any], token: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload = token if isinstance(token, dict) else _connection_token_payload(row)
    canonical_raw = str(row.get("_token") or "").strip()
    try:
        canonical = json.loads(canonical_raw or "{}")
    except (TypeError, ValueError):
        canonical = None
    if isinstance(canonical, dict) and canonical:
        storage_format = "canonical_envelope"
    elif str(row.get("encrypted_refresh_token") or "").strip():
        storage_format = "legacy_refresh_column"
    elif str(row.get("encrypted_access_token") or "").strip():
        storage_format = "legacy_access_column"
    else:
        storage_format = "missing"
    return {
        "connection_id": str(row.get("id") or ""),
        "client_id": str(row.get("client_id") or ""),
        "provider": str(row.get("provider") or ""),
        "connection_status": str(row.get("status") or ""),
        "disconnected_at": row.get("disconnected_at"),
        "token_expires_at": str(payload.get("expires_at") or row.get("token_expires_at") or "") or None,
        "access_token_available": bool(str(payload.get("access_token") or "").strip()),
        "refresh_token_available": bool(str(payload.get("refresh_token") or "").strip()),
        "token_storage_format": storage_format,
        "scopes": [str(scope) for scope in (row.get("scopes") or []) if str(scope).strip()],
        "authorized_email": str(
            (_json_metadata(row).get("google_email")) or row.get("account_name") or ""
        ) or None,
    }


def _json_metadata(row: Dict[str, Any]) -> Dict[str, Any]:
    value = row.get("metadata")
    return value if isinstance(value, dict) else {}


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _sanitized_google_error(response: httpx.Response) -> Dict[str, Any]:
    try:
        payload = response.json()
    except (TypeError, ValueError):
        payload = {}
    error = payload.get("error") if isinstance(payload, dict) and isinstance(payload.get("error"), dict) else {}
    details = error.get("details") if isinstance(error.get("details"), list) else []
    reasons = {
        str(item.get("reason") or item.get("reasonCode") or "").strip()
        for item in details
        if isinstance(item, dict) and str(item.get("reason") or item.get("reasonCode") or "").strip()
    }
    google_request_id = ""
    for detail in details:
        if not isinstance(detail, dict):
            continue
        google_request_id = google_request_id or str(detail.get("requestId") or "")[:100]
        for ads_error in detail.get("errors") or []:
            if not isinstance(ads_error, dict):
                continue
            error_code = ads_error.get("errorCode")
            if isinstance(error_code, dict):
                reasons.update(
                    f"{key}:{value}" for key, value in error_code.items()
                    if str(key).strip() and str(value).strip()
                )
    return {
        "http_status": int(response.status_code or 0),
        "google_status": str(error.get("status") or "")[:80],
        "reasons": sorted(reasons)[:8],
        "message": str(error.get("message") or "")[:240],
        "google_request_id": google_request_id or None,
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
        diagnostics = _safe_token_diagnostics(row)
        if status not in {"connected", "selection_required"} or row.get("disconnected_at"):
            raise IntegrationError(
                "A conexão Google está desconectada. Reconecte antes de sincronizar.",
                status_code=409,
                code="GOOGLE_CONNECTION_DISCONNECTED",
                provider="google",
                diagnostics={**diagnostics, "refresh_attempted": False, "refresh_result": "not_attempted"},
            )
        token = _connection_token_payload(row)
        diagnostics = _safe_token_diagnostics(row, token)
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
                    status_code=409,
                    code="GOOGLE_REAUTH_REQUIRED_REFRESH_MISSING",
                    provider="google",
                    diagnostics={**diagnostics, "refresh_attempted": False, "refresh_result": "access_missing"},
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
                diagnostics={**diagnostics, "refresh_attempted": False, "refresh_result": "refresh_missing"},
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
                    diagnostics={**diagnostics, "refresh_attempted": True, "refresh_result": "invalid_grant", "upstream_status": response.status_code, "upstream_reason": refresh_error},
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
                "A API Google não retornou um access token após a renovação.",
                status_code=503,
                code="GOOGLE_API_UNAVAILABLE",
                provider="google",
                retryable=True,
                diagnostics={**diagnostics, "refresh_attempted": True, "refresh_result": "access_missing"},
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


async def get_google_connection_diagnostics(client_id: str, connection_id: str) -> Dict[str, Any]:
    row = await get_connection(client_id, connection_id, include_token=True)
    return _safe_token_diagnostics(row)


async def list_ga4_properties(client_id: str, connection_id: str, *, request_id: str = "-") -> List[Dict[str, Any]]:
    token = await _access_token(client_id, connection_id, expected_provider="ga4", request_id=request_id)
    out: List[Dict[str, Any]] = []
    account_count = 0
    page_token = ""
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            try:
                response = await client.get(
                    "https://analyticsadmin.googleapis.com/v1beta/accountSummaries",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"pageSize": "200", **({"pageToken": page_token} if page_token else {})},
                )
                response.raise_for_status()
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise IntegrationError(
                    "A API Google está temporariamente indisponível.", status_code=503,
                    code="GOOGLE_API_UNAVAILABLE", provider="google", retryable=True,
                ) from exc
            except httpx.HTTPStatusError as exc:
                diagnostic = _sanitized_google_error(response)
                print(
                    "[google_oauth][ga4_properties_error] "
                    f"request_id={request_id} connection_id={connection_id} client_id={client_id} stage=admin_api "
                    f"http_status={diagnostic['http_status']} google_status={diagnostic['google_status'] or '-'} "
                    f"reasons={','.join(diagnostic['reasons']) or '-'} message={diagnostic['message'] or '-'}"
                )
                mapped = google_api_error(
                    response, api="Analytics Admin API",
                    unavailable_code="GOOGLE_NO_PROPERTIES_AVAILABLE",
                    operation="listar propriedades GA4",
                )
                if mapped.code not in {"GOOGLE_ADMIN_API_DISABLED", "GOOGLE_SCOPE_INSUFFICIENT", "GOOGLE_NO_PROPERTIES_AVAILABLE"}:
                    mapped = IntegrationError(
                        "A API Google está temporariamente indisponível.", status_code=503,
                        code="GOOGLE_API_UNAVAILABLE", provider="google", retryable=True,
                    )
                safe_connection = await get_connection(client_id, connection_id, include_token=True)
                mapped.diagnostics = {
                    **_safe_token_diagnostics(safe_connection),
                    "refresh_attempted": False,
                    "refresh_result": "not_required_or_completed",
                    "upstream_status": diagnostic["http_status"],
                    "upstream_reason": ",".join(diagnostic["reasons"]) or diagnostic["google_status"] or None,
                }
                raise mapped from exc
            payload = response.json()
            account_summaries = payload.get("accountSummaries") or []
            account_count += len(account_summaries)
            for account in account_summaries:
                for prop in account.get("propertySummaries") or []:
                    out.append({
                        "account": account.get("account"),
                        "account_name": account.get("displayName"),
                        "property": prop.get("property"),
                        "property_name": prop.get("displayName"),
                    })
            page_token = str(payload.get("nextPageToken") or "")
            if not page_token:
                break
    print(
        "[google_oauth][ga4_properties] "
        f"request_id={request_id} connection_id={connection_id} client_id={client_id} stage=complete "
        f"http_status={response.status_code} accounts={account_count} properties={len(out)}"
    )
    return out


async def list_ga4_streams(
    client_id: str, connection_id: str, property_id: str
) -> List[Dict[str, Any]]:
    token = await _access_token(client_id, connection_id, expected_provider="ga4")
    normalized = str(property_id or "").strip().removeprefix("properties/")
    if not normalized:
        raise RuntimeError("property_id é obrigatório.")
    endpoint = f"https://analyticsadmin.googleapis.com/v1beta/properties/{normalized}/dataStreams"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            endpoint,
            headers={"Authorization": f"Bearer {token}"},
            params={"pageSize": "200"},
        )
    # DIAGNÓSTICO TEMPORÁRIO GA4 streams — nunca registra token; remover após validar.
    try:
        if response.is_success:
            _diag_rows = response.json().get("dataStreams") or []
            _diag_streams = ";".join(
                f"{row.get('type') or '-'}:{row.get('displayName') or '-'}:{str(row.get('name') or '-').split('/')[-1]}"
                for row in _diag_rows if isinstance(row, dict)
            )
            print(
                "[google_oauth][ga4_streams_diag] "
                f"client_id={client_id} connection_id={connection_id} property_id_received={property_id!r} "
                f"endpoint={endpoint} http_status={response.status_code} "
                f"streams_count={len(_diag_rows)} next_page={'yes' if response.json().get('nextPageToken') else 'no'} "
                f"streams={_diag_streams or '-'}"
            )
        else:
            _diag = _sanitized_google_error(response)
            print(
                "[google_oauth][ga4_streams_diag] "
                f"client_id={client_id} connection_id={connection_id} property_id_received={property_id!r} "
                f"endpoint={endpoint} http_status={_diag['http_status']} "
                f"google_status={_diag['google_status'] or '-'} reasons={','.join(_diag['reasons']) or '-'} "
                f"message={_diag['message'] or '-'}"
            )
    except Exception as _diag_exc:  # diagnóstico nunca pode quebrar o fluxo
        print(f"[google_oauth][ga4_streams_diag] stage=diag_failed error_type={_diag_exc.__class__.__name__}")
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


async def list_google_ads_accounts(
    client_id: str, connection_id: str, *, request_id: str = "-",
) -> Dict[str, Any]:
    developer_token = _env("GOOGLE_ADS_DEVELOPER_TOKEN")
    if not developer_token:
        print(
            "[google_ads] stage=list_accessible_customers "
            f"request_id={request_id} client_id={client_id} connection_id={connection_id} "
            "status=blocked error_code=GOOGLE_ADS_SETUP_REQUIRED developer_token=missing"
        )
        raise IntegrationError(
            "Configure o Developer Token do Google Ads antes de listar contas.",
            status_code=409,
            code="GOOGLE_ADS_SETUP_REQUIRED",
            provider="google",
        )
    api_version = _env("GOOGLE_ADS_API_VERSION") or "v25"
    if not re.fullmatch(r"v\d+", api_version):
        raise IntegrationError(
            "A versão configurada da Google Ads API é inválida.", status_code=409,
            code="GOOGLE_ADS_API_VERSION_INVALID", provider="google",
        )
    resource = "/customers:listAccessibleCustomers"
    url = f"https://googleads.googleapis.com/{api_version}{resource}"
    token = await _access_token(
        client_id, connection_id, expected_provider="google_ads", request_id=request_id,
    )
    print(
        "[google_ads] stage=list_accessible_customers "
        f"request_id={request_id} client_id={client_id} connection_id={connection_id} "
        f"api_version={api_version} developer_token=present login_customer_id=none"
    )
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "developer-token": developer_token,
                },
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            print(
                "[google_ads] stage=list_accessible_customers "
                f"request_id={request_id} client_id={client_id} connection_id={connection_id} "
                f"status=transport_error error_type={exc.__class__.__name__}"
            )
            raise IntegrationError(
                "A Google Ads API está temporariamente indisponível.", status_code=503,
                code="GOOGLE_ADS_API_UNAVAILABLE", provider="google", retryable=True,
            ) from exc
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        details = _google_ads_error_details(response)
        _log_google_ads_error(
            "list_accessible_customers", details,
            client_id=client_id, connection_id=connection_id, request_id=request_id,
        )
        diagnostics = {
            "api_version": api_version, "resource": resource,
            "upstream_status": response.status_code,
            "upstream_reason": ",".join(details["reasons"]) or details["google_status"] or None,
            "google_request_id": details["google_request_id"],
        }
        if response.status_code == 404:
            raise IntegrationError(
                "A versão configurada da Google Ads API não está disponível.", status_code=409,
                code="GOOGLE_ADS_API_VERSION_UNAVAILABLE", provider="google",
                diagnostics=diagnostics,
            ) from exc
        mapped = google_ads_api_error(
            response, details, operation="listar contas Google Ads", provider="google",
        )
        mapped.diagnostics = diagnostics
        raise mapped from exc

    accounts: List[Dict[str, Any]] = []
    invalid_resource_names = 0
    for item in response.json().get("resourceNames") or []:
        customer_id = normalize_google_ads_customer_id(item)
        if not customer_id:
            invalid_resource_names += 1
            continue
        if any(account["customer_id"] == customer_id for account in accounts):
            continue
        # listAccessibleCustomers só devolve contas com acesso DIRETO do usuário:
        # nenhuma delas precisa de login-customer-id.
        accounts.append({
            "resource_name": f"customers/{customer_id}",
            "customer_id": customer_id,
            "access": "direct",
            "login_customer_id": None,
            "manager_customer_id": None,
        })
    google_request_id = str(
        response.headers.get("request-id") or response.headers.get("google-ads-request-id") or ""
    )[:100]
    print(
        "[google_ads] stage=list_accessible_customers "
        f"request_id={request_id} client_id={client_id} connection_id={connection_id} "
        f"http_status={response.status_code} customers_count={len(accounts)} "
        f"invalid_resource_names={invalid_resource_names} google_request_id={google_request_id or '-'}"
    )

    direct_accounts = await _enrich_google_ads_account_names(
        accounts,
        token=token,
        developer_token=developer_token,
        api_version=api_version,
        login_customer_id=None,
        request_id=request_id,
    )
    child_accounts, diagnostics = await _discover_google_ads_hierarchy(
        direct_accounts,
        token=token,
        developer_token=developer_token,
        api_version=api_version,
        request_id=request_id,
        client_id=client_id,
        connection_id=connection_id,
    )
    all_accounts = [*direct_accounts, *child_accounts]
    for account in all_accounts:
        print(
            "[google_ads] stage=account "
            f"request_id={request_id} client_id={client_id} connection_id={connection_id} "
            f"customer_id={account['customer_id']} manager={'true' if account.get('is_manager') else 'false'} "
            f"status={account.get('status') or '-'} access={account.get('access') or 'direct'} "
            f"login_customer_id={account.get('login_customer_id') or 'none'} "
            f"details_error={account.get('details_error') or '-'} "
            f"hierarchy_error={account.get('hierarchy_error') or '-'}"
        )
    await _persist_google_ads_accounts_cache(
        client_id=client_id, connection_id=connection_id, accounts=all_accounts,
    )
    return {
        "available": True, "accounts": all_accounts, "api_version": api_version,
        "request_id": request_id, "google_request_id": google_request_id or None,
        "reason": _google_ads_listing_reason(diagnostics),
        # Estruturado e sem credenciais: endpoint, IDs, HTTP, código e request ID
        # de cada etapa que falhou — visível no navegador sem acesso aos logs.
        "diagnostics": diagnostics,
    }


def _google_ads_error_details(response: httpx.Response) -> Dict[str, Any]:
    """Somente campos seguros do erro Google: status, códigos, mensagem e request id."""
    details = _sanitized_google_error(response)
    google_request_id = str(
        response.headers.get("request-id") or response.headers.get("google-ads-request-id")
        or details.get("google_request_id") or ""
    )[:100]
    message = " ".join(str(details.get("message") or "").split())[:240]
    return {**details, "message": message, "google_request_id": google_request_id or None}


def _google_ads_error_code(details: Dict[str, Any]) -> str:
    reasons = [str(reason).split(":")[-1].upper() for reason in details.get("reasons") or []]
    return ",".join(reasons) or str(details.get("google_status") or "") or f"HTTP_{details.get('http_status')}"


def _log_google_ads_error(
    stage: str, details: Dict[str, Any], *, client_id: str, connection_id: str, request_id: str,
    customer_id: str | None = None, login_customer_id: str | None = None, endpoint: str | None = None,
) -> None:
    # Nunca recebe token, header Authorization nem developer token: só o
    # resumo sanitizado de _google_ads_error_details.
    print(
        f"[google_ads] stage={stage} request_id={request_id} client_id={client_id} "
        f"connection_id={connection_id} customer_id={customer_id or '-'} "
        f"login_customer_id={login_customer_id or 'none'} endpoint={endpoint or '-'} "
        f"http_status={details.get('http_status')} google_request_id={details.get('google_request_id') or '-'} "
        f"error_code={_google_ads_error_code(details)} message={details.get('message') or '-'}"
    )


def google_ads_api_error(
    response: httpx.Response, details: Dict[str, Any], *, operation: str, provider: str = "google",
) -> IntegrationError:
    """Mapeia erros conhecidos da Google Ads API para mensagens acionáveis."""
    codes = {str(reason).split(":")[-1].upper() for reason in details.get("reasons") or []}
    message = str(details.get("message") or "").lower()
    if "SERVICE_DISABLED" in codes or "has not been used in project" in message:
        return IntegrationError(
            "A Google Ads API não está habilitada no projeto Google Cloud da credencial OAuth.",
            status_code=409, code="GOOGLE_ADS_API_DISABLED", provider=provider,
        )
    if any("DEVELOPER_TOKEN" in code for code in codes):
        return IntegrationError(
            "O Developer Token do Google Ads foi recusado para esta conta "
            f"({', '.join(sorted(code for code in codes if 'DEVELOPER_TOKEN' in code))}). "
            "Verifique o nível de acesso do token no Centro de API da conta administradora.",
            status_code=403, code="GOOGLE_ADS_DEVELOPER_TOKEN_NOT_APPROVED", provider=provider,
        )
    if "USER_PERMISSION_DENIED" in codes:
        return IntegrationError(
            "O usuário Google autorizado não tem acesso a esta conta Google Ads. "
            "Se o acesso é feito por uma conta administradora (MCC), selecione a conta pela lista "
            "do Mugô para que o login-customer-id correto seja usado.",
            status_code=403, code="GOOGLE_ADS_USER_PERMISSION_DENIED", provider=provider,
        )
    if "NOT_ADS_USER" in codes:
        return IntegrationError(
            "A conta Google autorizada não está associada a nenhuma conta Google Ads.",
            status_code=403, code="GOOGLE_ADS_NOT_ADS_USER", provider=provider,
        )
    if "CUSTOMER_NOT_ENABLED" in codes:
        return IntegrationError(
            "A conta Google Ads selecionada não está ativa (cancelada, suspensa ou não configurada).",
            status_code=409, code="GOOGLE_ADS_CUSTOMER_NOT_ENABLED", provider=provider,
        )
    if "REQUESTED_METRICS_FOR_MANAGER" in codes:
        return IntegrationError(
            "A conta selecionada é uma conta administradora (MCC), que não possui campanhas próprias. "
            "Selecione uma conta de anúncios.",
            status_code=409, code="GOOGLE_ADS_MANAGER_ACCOUNT_NOT_SUPPORTED", provider=provider,
        )
    return provider_http_error("google", response.status_code, operation=operation)


async def _fetch_google_ads_customer_info(
    *,
    customer_id: str,
    token: str,
    developer_token: str,
    api_version: str,
    login_customer_id: str | None,
    request_id: str = "-",
) -> Dict[str, Any] | None:
    """
    Detalhes de UMA conta (nome, tipo manager, status) via GAQL FROM customer.
    Falha de transporte/inesperada retorna None; falha HTTP retorna só o erro
    sanitizado ({"details_error", "details_http_status", "details_request_id"}).
    Erro aqui significa "não consegui ler os detalhes desta conta" — nunca
    "não consigo consultar a hierarquia" (isso é _discover_google_ads_hierarchy).
    """
    url = f"https://googleads.googleapis.com/{api_version}/customers/{customer_id}/googleAds:search"
    headers = {
        "Authorization": f"Bearer {token}",
        "developer-token": developer_token,
        "Content-Type": "application/json",
    }
    if login_customer_id:
        headers["login-customer-id"] = login_customer_id
    query = (
        "SELECT customer.id, customer.descriptive_name, customer.currency_code, "
        "customer.time_zone, customer.manager, customer.test_account, customer.status "
        "FROM customer LIMIT 1"
    )
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, headers=headers, json={"query": query})
        if response.status_code >= 400:
            details = _google_ads_error_details(response)
            code = _google_ads_error_code(details)
            print(
                f"[google_ads] stage=customer_info request_id={request_id} customer_id={customer_id} "
                f"login_customer_id={login_customer_id or 'none'} "
                f"endpoint={_google_ads_endpoint(api_version, customer_id)} "
                f"http_status={details.get('http_status')} google_request_id={details.get('google_request_id') or '-'} "
                f"error_code={code} message={details.get('message') or '-'}"
            )
            return {
                "details_error": code,
                "details_http_status": details.get("http_status"),
                "details_request_id": details.get("google_request_id"),
            }
        results = response.json().get("results") or []
        if not results:
            return None
        customer = results[0].get("customer") or {}
        return {
            "descriptive_name": str(customer.get("descriptiveName") or "").strip() or None,
            "currency_code": str(customer.get("currencyCode") or "").strip() or None,
            "time_zone": str(customer.get("timeZone") or "").strip() or None,
            "is_manager": bool(customer.get("manager")),
            "is_test_account": bool(customer.get("testAccount")),
            "status": str(customer.get("status") or "").strip() or None,
        }
    except Exception as exc:
        # Deliberadamente amplo: uma conta sem permissão de leitura, um
        # transporte indisponível ou qualquer outra falha nesta chamada extra
        # NUNCA pode derrubar a listagem inteira — só essa conta cai para o
        # fallback visual "Conta {customer_id}".
        print(f"[google_oauth][ads_accounts][name_lookup_failed] customer_id={customer_id} error={exc.__class__.__name__}")
        return None


async def _enrich_google_ads_account_names(
    accounts: List[Dict[str, Any]],
    *,
    token: str,
    developer_token: str,
    api_version: str,
    login_customer_id: str | None,
    request_id: str,
) -> List[Dict[str, Any]]:
    if not accounts:
        return accounts
    # return_exceptions=True: mesmo que _fetch_google_ads_customer_info
    # (que já é defensiva) escape por algum caminho inesperado, uma conta
    # com falha nunca derruba as outras nem a listagem inteira.
    infos = await asyncio.gather(*[
        _fetch_google_ads_customer_info(
            customer_id=account["customer_id"], token=token, developer_token=developer_token,
            api_version=api_version, login_customer_id=login_customer_id, request_id=request_id,
        )
        for account in accounts
    ], return_exceptions=True)
    enriched: List[Dict[str, Any]] = []
    missing = 0
    for account, info in zip(accounts, infos):
        if isinstance(info, BaseException):
            info = None
        if not info or info.get("details_error"):
            missing += 1
        enriched.append({**account, **(info or {}), "updated_at": datetime.now(timezone.utc).isoformat()})
    if missing:
        print(
            "[google_oauth][ads_accounts][name_enrichment] "
            f"request_id={request_id} accounts={len(accounts)} missing_names={missing}"
        )
    return enriched


_GOOGLE_ADS_MAX_ROOTS = 20
_GOOGLE_ADS_MAX_MANAGERS_PER_ROOT = 10
_GOOGLE_ADS_MAX_DEPTH = 2
_GOOGLE_ADS_MAX_LINKED_ACCOUNTS = 50
_GOOGLE_ADS_MAX_PAGES = 5

# Padrão documentado da Google Ads API (GetAccountHierarchy): filhas diretas
# (level <= 1) consultadas NA conta administradora, com login-customer-id da
# raiz acessível; sub-administradoras são expandidas uma a uma.
_GOOGLE_ADS_CUSTOMER_CLIENT_QUERY = (
    "SELECT customer_client.client_customer, customer_client.id, customer_client.descriptive_name, "
    "customer_client.manager, customer_client.level, customer_client.status, "
    "customer_client.currency_code, customer_client.time_zone, customer_client.test_account "
    "FROM customer_client WHERE customer_client.level <= 1"
)
# Caminho alternativo documentado para a mesma relação administradora→cliente,
# usado só quando customer_client é recusado.
_GOOGLE_ADS_CLIENT_LINK_QUERY = (
    "SELECT customer_client_link.client_customer, customer_client_link.status "
    "FROM customer_client_link WHERE customer_client_link.status = 'ACTIVE'"
)


def _google_ads_endpoint(api_version: str, customer_id: str) -> str:
    return f"POST /{api_version}/customers/{customer_id}/googleAds:search"


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


async def _google_ads_search_rows(
    *,
    customer_id: str,
    login_customer_id: str | None,
    query: str,
    token: str,
    developer_token: str,
    api_version: str,
) -> tuple[List[Dict[str, Any]], Dict[str, Any] | None]:
    """GAQL search paginado. Retorna (linhas, erro sanitizado ou None)."""
    url = f"https://googleads.googleapis.com/{api_version}/customers/{customer_id}/googleAds:search"
    headers = {
        "Authorization": f"Bearer {token}",
        "developer-token": developer_token,
        "Content-Type": "application/json",
    }
    if login_customer_id:
        headers["login-customer-id"] = login_customer_id
    rows: List[Dict[str, Any]] = []
    page_token = ""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            for _ in range(_GOOGLE_ADS_MAX_PAGES):
                body: Dict[str, Any] = {"query": query}
                if page_token:
                    body["pageToken"] = page_token
                response = await client.post(url, headers=headers, json=body)
                if response.status_code >= 400:
                    return rows, _google_ads_error_details(response)
                payload = response.json()
                rows.extend(row for row in payload.get("results") or [] if isinstance(row, dict))
                page_token = str(payload.get("nextPageToken") or "")
                if not page_token:
                    break
    except Exception as exc:
        return rows, {
            "http_status": None, "google_status": "TRANSPORT_ERROR", "reasons": [],
            "message": exc.__class__.__name__, "google_request_id": None,
        }
    return rows, None


def _google_ads_failure(
    stage: str, details: Dict[str, Any], *, customer_id: str, login_customer_id: str | None, api_version: str,
) -> Dict[str, Any]:
    return {
        "stage": stage,
        "customer_id": customer_id,
        "login_customer_id": login_customer_id,
        "endpoint": _google_ads_endpoint(api_version, customer_id),
        "http_status": details.get("http_status"),
        "error_code": _google_ads_error_code(details),
        "google_request_id": details.get("google_request_id"),
        "message": details.get("message") or None,
    }


def _google_ads_detail_failure(account: Dict[str, Any], api_version: str) -> Dict[str, Any]:
    return {
        "stage": "customer_info",
        "customer_id": account["customer_id"],
        "login_customer_id": account.get("login_customer_id") or None,
        "endpoint": _google_ads_endpoint(api_version, account["customer_id"]),
        "http_status": account.get("details_http_status"),
        "error_code": account.get("details_error"),
        "google_request_id": account.get("details_request_id"),
        "message": None,
    }


def _log_google_ads_hierarchy(
    stage: str, *, request_id: str, client_id: str, connection_id: str, manager_customer_id: str,
    login_customer_id: str | None, api_version: str, http_status: Any, google_request_id: str | None,
    error_code: str | None, message: str | None, children_count: int,
) -> None:
    print(
        f"[google_ads] stage={stage} request_id={request_id} client_id={client_id} "
        f"connection_id={connection_id} manager_customer_id={manager_customer_id} "
        f"login_customer_id={login_customer_id or 'none'} "
        f"endpoint={_google_ads_endpoint(api_version, manager_customer_id)} "
        f"http_status={http_status if http_status is not None else '-'} "
        f"google_request_id={google_request_id or '-'} error_code={error_code or '-'} "
        f"message={message or '-'} children_count={children_count}"
    )


def _fill_root_from_hierarchy(root: Dict[str, Any], item: Dict[str, Any]) -> None:
    """A linha level 0 de customer_client descreve a própria raiz: completa o
    que o detalhe (FROM customer) não conseguiu ler, sem sobrescrever."""
    if item.get("manager"):
        root["is_manager"] = True
    for target, source in (
        ("descriptive_name", "descriptiveName"), ("status", "status"),
        ("currency_code", "currencyCode"), ("time_zone", "timeZone"),
    ):
        value = str(item.get(source) or "").strip()
        if value and not root.get(target):
            root[target] = value


async def _discover_google_ads_hierarchy(
    direct_accounts: List[Dict[str, Any]],
    *,
    token: str,
    developer_token: str,
    api_version: str,
    request_id: str,
    client_id: str,
    connection_id: str,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Descobre contas acessadas via conta administradora (MCC). Raízes: MCCs
    confirmadas E contas cujo detalhe falhou — erro de detalhe não impede a
    tentativa de hierarquia. Retorna (filhas, diagnósticos de falha).
    """
    diagnostics = [_google_ads_detail_failure(account, api_version) for account in direct_accounts if account.get("details_error")]
    roots = [
        account for account in direct_accounts
        if account.get("is_manager") or account.get("details_error")
    ][:_GOOGLE_ADS_MAX_ROOTS]
    if not roots:
        return [], diagnostics
    results = await asyncio.gather(*[
        _discover_google_ads_manager_tree(
            root, token=token, developer_token=developer_token, api_version=api_version,
            request_id=request_id, client_id=client_id, connection_id=connection_id,
        )
        for root in roots
    ], return_exceptions=True)
    # Conta com acesso direto prevalece: não precisa de login-customer-id.
    seen = {account["customer_id"] for account in direct_accounts}
    children: List[Dict[str, Any]] = []
    for root, result in zip(roots, results):
        if isinstance(result, BaseException):
            root["hierarchy_error"] = "UNEXPECTED_ERROR"
            diagnostics.append({
                "stage": "manager_children", "customer_id": root["customer_id"],
                "login_customer_id": root["customer_id"],
                "endpoint": _google_ads_endpoint(api_version, root["customer_id"]),
                "http_status": None, "error_code": "UNEXPECTED_ERROR", "google_request_id": None, "message": None,
            })
            continue
        items, root_diagnostics = result
        diagnostics.extend(root_diagnostics)
        for child in items:
            if child["customer_id"] in seen:
                continue
            seen.add(child["customer_id"])
            children.append(child)
    return children, diagnostics


async def _discover_google_ads_manager_tree(
    root: Dict[str, Any],
    *,
    token: str,
    developer_token: str,
    api_version: str,
    request_id: str,
    client_id: str,
    connection_id: str,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    root_id = root["customer_id"]
    confirmed_manager = bool(root.get("is_manager"))
    items: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []
    queue: List[tuple[str, str | None, int]] = [(root_id, root.get("descriptive_name"), 0)]
    visited: set[str] = set()
    while queue and len(visited) < _GOOGLE_ADS_MAX_MANAGERS_PER_ROOT:
        manager_id, manager_name, depth = queue.pop(0)
        if manager_id in visited:
            continue
        visited.add(manager_id)
        rows, error = await _google_ads_search_rows(
            customer_id=manager_id, login_customer_id=root_id, query=_GOOGLE_ADS_CUSTOMER_CLIENT_QUERY,
            token=token, developer_token=developer_token, api_version=api_version,
        )
        if error:
            failure = _google_ads_failure(
                "manager_children", error, customer_id=manager_id, login_customer_id=root_id, api_version=api_version,
            )
            _log_google_ads_hierarchy(
                "manager_children", request_id=request_id, client_id=client_id, connection_id=connection_id,
                manager_customer_id=manager_id, login_customer_id=root_id, api_version=api_version,
                http_status=failure["http_status"], google_request_id=failure["google_request_id"],
                error_code=failure["error_code"], message=failure["message"], children_count=0,
            )
            diagnostics.append(failure)
            if manager_id == root_id:
                root["hierarchy_error"] = failure["error_code"]
                if confirmed_manager:
                    linked, link_diagnostics = await _discover_google_ads_client_links(
                        root, token=token, developer_token=developer_token, api_version=api_version,
                        request_id=request_id, client_id=client_id, connection_id=connection_id,
                    )
                    items.extend(linked)
                    diagnostics.extend(link_diagnostics)
            else:
                for item in items:
                    if item["customer_id"] == manager_id:
                        item["hierarchy_error"] = failure["error_code"]
            continue
        found = 0
        for row in rows:
            item = row.get("customerClient")
            if not isinstance(item, dict):
                continue
            child_id = (
                normalize_google_ads_customer_id(item.get("id"))
                or normalize_google_ads_customer_id(item.get("clientCustomer"))
            )
            if not child_id:
                continue
            if _int_value(item.get("level")) == 0 or child_id == manager_id:
                if manager_id == root_id:
                    _fill_root_from_hierarchy(root, item)
                continue
            if child_id == root_id or any(existing["customer_id"] == child_id for existing in items):
                continue
            entry = {
                "resource_name": f"customers/{child_id}",
                "customer_id": child_id,
                "descriptive_name": str(item.get("descriptiveName") or "").strip() or None,
                "currency_code": str(item.get("currencyCode") or "").strip() or None,
                "time_zone": str(item.get("timeZone") or "").strip() or None,
                "is_manager": bool(item.get("manager")),
                "is_test_account": bool(item.get("testAccount")),
                "status": str(item.get("status") or "").strip() or None,
                "access": "manager",
                "login_customer_id": root_id,
                "manager_customer_id": manager_id,
                "manager_name": manager_name or root.get("descriptive_name"),
                "level": depth + 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            items.append(entry)
            found += 1
            if entry["is_manager"] and depth + 1 < _GOOGLE_ADS_MAX_DEPTH:
                queue.append((child_id, entry["descriptive_name"], depth + 1))
        _log_google_ads_hierarchy(
            "manager_children", request_id=request_id, client_id=client_id, connection_id=connection_id,
            manager_customer_id=manager_id, login_customer_id=root_id, api_version=api_version,
            http_status=200, google_request_id=None, error_code=None, message=None, children_count=found,
        )
    return items, diagnostics


async def _discover_google_ads_client_links(
    root: Dict[str, Any],
    *,
    token: str,
    developer_token: str,
    api_version: str,
    request_id: str,
    client_id: str,
    connection_id: str,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Fallback documentado: vínculos ativos da MCC + detalhe de cada cliente."""
    root_id = root["customer_id"]
    rows, error = await _google_ads_search_rows(
        customer_id=root_id, login_customer_id=root_id, query=_GOOGLE_ADS_CLIENT_LINK_QUERY,
        token=token, developer_token=developer_token, api_version=api_version,
    )
    if error:
        failure = _google_ads_failure(
            "manager_links", error, customer_id=root_id, login_customer_id=root_id, api_version=api_version,
        )
        root["links_error"] = failure["error_code"]
        _log_google_ads_hierarchy(
            "manager_links", request_id=request_id, client_id=client_id, connection_id=connection_id,
            manager_customer_id=root_id, login_customer_id=root_id, api_version=api_version,
            http_status=failure["http_status"], google_request_id=failure["google_request_id"],
            error_code=failure["error_code"], message=failure["message"], children_count=0,
        )
        return [], [failure]
    linked_ids: List[str] = []
    for row in rows:
        link = row.get("customerClientLink")
        if not isinstance(link, dict):
            continue
        linked_id = normalize_google_ads_customer_id(link.get("clientCustomer"))
        if linked_id and linked_id != root_id and linked_id not in linked_ids:
            linked_ids.append(linked_id)
    linked_ids = linked_ids[:_GOOGLE_ADS_MAX_LINKED_ACCOUNTS]
    infos = await asyncio.gather(*[
        _fetch_google_ads_customer_info(
            customer_id=linked_id, token=token, developer_token=developer_token,
            api_version=api_version, login_customer_id=root_id, request_id=request_id,
        )
        for linked_id in linked_ids
    ], return_exceptions=True)
    children: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = [{
        "stage": "manager_links", "customer_id": root_id, "login_customer_id": root_id,
        "endpoint": _google_ads_endpoint(api_version, root_id), "http_status": 200,
        "error_code": None, "google_request_id": None, "message": None, "children_count": len(linked_ids),
    }]
    for linked_id, info in zip(linked_ids, infos):
        if isinstance(info, BaseException):
            info = None
        entry = {
            "resource_name": f"customers/{linked_id}",
            "customer_id": linked_id,
            "access": "manager",
            "login_customer_id": root_id,
            "manager_customer_id": root_id,
            "manager_name": root.get("descriptive_name"),
            "level": 1,
            "source": "customer_client_link",
            **(info or {}),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if entry.get("details_error"):
            diagnostics.append(_google_ads_detail_failure(entry, api_version))
        children.append(entry)
    _log_google_ads_hierarchy(
        "manager_links", request_id=request_id, client_id=client_id, connection_id=connection_id,
        manager_customer_id=root_id, login_customer_id=root_id, api_version=api_version,
        http_status=200, google_request_id=None, error_code=None, message=None, children_count=len(children),
    )
    return children, diagnostics


def _google_ads_listing_reason(diagnostics: List[Dict[str, Any]]) -> str | None:
    """Texto para a UI separando detalhe de conta, hierarquia e vínculos."""
    parts: List[str] = []
    for item in diagnostics:
        account = format_google_ads_customer_id(str(item.get("customer_id") or ""))
        meta = f"HTTP {item.get('http_status') if item.get('http_status') is not None else '-'}, código {item.get('error_code') or '-'}"
        if item.get("google_request_id"):
            meta += f", request ID {item['google_request_id']}"
        stage = item.get("stage")
        if stage == "customer_info":
            parts.append(f"Detalhes da conta {account} não puderam ser lidos ({meta}).")
        elif stage == "manager_children":
            parts.append(f"As contas vinculadas à conta administradora {account} não puderam ser listadas via customer_client ({meta}).")
        elif stage == "manager_links" and item.get("error_code"):
            parts.append(f"Os vínculos ativos da conta administradora {account} também foram recusados ({meta}).")
        elif stage == "manager_links":
            parts.append(f"Contas da administradora {account} obtidas pelos vínculos ativos (customer_client_link): {item.get('children_count', 0)}.")
    return " ".join(parts) or None


async def _persist_google_ads_accounts_cache(
    *, client_id: str, connection_id: str, accounts: List[Dict[str, Any]],
) -> None:
    """
    Persistido em integration_connections.metadata (jsonb já existente) —
    sem tabela nova. É a fonte que a seleção usa para validar a conta e
    resolver o login-customer-id; refeito a cada listagem.
    """
    try:
        row = await get_connection(client_id, connection_id)
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        metadata = {**metadata, "google_ads_accounts_cache": accounts}
        await sb_update(
            "integration_connections",
            filters={"id": f"eq.{connection_id}", "client_id": f"eq.{client_id}"},
            patch={"metadata": metadata, "updated_at": datetime.now(timezone.utc).isoformat()},
            returning="minimal",
        )
    except Exception as exc:
        print(
            "[google_oauth][ads_accounts][cache_persist_warning] "
            f"client_id={client_id} connection_id={connection_id} error={exc.__class__.__name__}"
        )
