from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from urllib.parse import urlencode

import httpx

from .generic_connections import get_connection, upsert_connection
from .crypto import encrypt_secret
from .ig_supabase import sb_select, sb_update
from .oauth_state import create_oauth_state

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/adwords",
]
_REFRESH_LOCKS: Dict[str, asyncio.Lock] = {}


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def settings() -> Dict[str, str]:
    values = {
        "client_id": _env("GOOGLE_OAUTH_CLIENT_ID"),
        "client_secret": _env("GOOGLE_OAUTH_CLIENT_SECRET"),
        "redirect_uri": _env("GOOGLE_OAUTH_REDIRECT_URI"),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(f"OAuth Google não configurado: {', '.join(missing)}")
    return values


async def authorization_url(*, user_id: str, client_id: str) -> str:
    config = settings()
    state = await create_oauth_state(
        provider="google",
        user_id=user_id,
        client_id=client_id,
        redirect_uri=config["redirect_uri"],
    )
    params = {
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
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
    *, client_id: str, user_id: str, token: Dict[str, Any], identity: Dict[str, str]
) -> Dict[str, Any]:
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=max(60, int(token.get("expires_in") or 3600)))
    ).isoformat()
    if not token.get("refresh_token"):
        raise RuntimeError(
            "Google não devolveu refresh_token. Revogue o acesso anterior e conecte novamente."
        )
    existing = await sb_select(
        "integration_connections",
        filters={"client_id": f"eq.{client_id}", "provider": "eq.ga4"},
        limit=10,
    )
    other_active = [
        row
        for row in existing
        if str(row.get("external_key") or "") != identity["sub"]
        and str(row.get("status") or "") != "disconnected"
    ]
    if other_active:
        raise RuntimeError(
            "Esta empresa já possui uma autorização Google. Desconecte-a antes de autorizar outra conta."
        )
    safe_token = {
        "access_token": token["access_token"],
        "refresh_token": token["refresh_token"],
        "token_type": token.get("token_type"),
        "expires_at": expires_at,
    }
    return await upsert_connection(
        client_id=client_id,
        provider="ga4",
        external_key=identity["sub"],
        token_payload=json.dumps(safe_token),
        user_id=user_id,
        status="selection_required",
        account_id=identity["sub"],
        account_name=identity["email"],
        token_expires_at=expires_at,
        scopes=str(token.get("scope") or "").split(),
        metadata={"google_email": identity["email"], "ads_developer_token_configured": bool(_env("GOOGLE_ADS_DEVELOPER_TOKEN"))},
    )


async def _access_token(client_id: str, connection_id: str) -> str:
    lock = _REFRESH_LOCKS.setdefault(connection_id, asyncio.Lock())
    async with lock:
        row = await get_connection(client_id, connection_id, include_token=True)
        token = json.loads(str(row.get("_token") or "{}"))
        expires_raw = str(token.get("expires_at") or "")
        expires_at = datetime.fromisoformat(expires_raw.replace("Z", "+00:00")) if expires_raw else None
        if expires_at and expires_at > datetime.now(timezone.utc) + timedelta(minutes=2):
            return str(token.get("access_token") or "")
        refresh_token = str(token.get("refresh_token") or "")
        if not refresh_token:
            raise RuntimeError("Conexão Google requer nova autorização.")
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
        response.raise_for_status()
        refreshed = response.json()
        access_token = str(refreshed.get("access_token") or "")
        if not access_token:
            raise RuntimeError("Google não renovou o access_token.")
        next_expires = (
            datetime.now(timezone.utc) + timedelta(seconds=int(refreshed.get("expires_in") or 3600))
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
        return access_token


async def list_ga4_properties(client_id: str, connection_id: str) -> List[Dict[str, Any]]:
    token = await _access_token(client_id, connection_id)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            "https://analyticsadmin.googleapis.com/v1beta/accountSummaries",
            headers={"Authorization": f"Bearer {token}"},
            params={"pageSize": "200"},
        )
    response.raise_for_status()
    out: List[Dict[str, Any]] = []
    for account in response.json().get("accountSummaries") or []:
        for prop in account.get("propertySummaries") or []:
            out.append({
                "account": account.get("account"),
                "account_name": account.get("displayName"),
                "property": prop.get("property"),
                "property_name": prop.get("displayName"),
            })
    return out


async def list_ga4_streams(
    client_id: str, connection_id: str, property_id: str
) -> List[Dict[str, Any]]:
    token = await _access_token(client_id, connection_id)
    normalized = str(property_id or "").strip().removeprefix("properties/")
    if not normalized:
        raise RuntimeError("property_id é obrigatório.")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"https://analyticsadmin.googleapis.com/v1beta/properties/{normalized}/dataStreams",
            headers={"Authorization": f"Bearer {token}"},
            params={"pageSize": "200"},
        )
    response.raise_for_status()
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
        return {
            "available": False,
            "reason": "Developer Token do Google Ads pendente. O GA4 pode ser usado normalmente.",
            "accounts": [],
        }
    token = await _access_token(client_id, connection_id)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            "https://googleads.googleapis.com/v19/customers:listAccessibleCustomers",
            headers={"Authorization": f"Bearer {token}", "developer-token": developer_token},
        )
    response.raise_for_status()
    accounts = [
        {"resource_name": item, "customer_id": str(item).split("/")[-1]}
        for item in response.json().get("resourceNames") or []
    ]
    return {"available": True, "accounts": accounts}
