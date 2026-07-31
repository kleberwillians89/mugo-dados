from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict
from urllib.parse import urlencode

import httpx

from .generic_connections import upsert_connection
from .ig_supabase import sb_insert, sb_select, sb_update
from .oauth_state import create_oauth_state

SHOP_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]\.myshopify\.com$")
SHOPIFY_SCOPES = ["read_orders", "read_customers", "read_products"]
SHOPIFY_WEBHOOK_TOPICS = [
    "orders/create",
    "orders/updated",
    "orders/paid",
    "orders/cancelled",
    "refunds/create",
    "customers/create",
    "customers/update",
    "app/uninstalled",
    "customers/data_request",
    "customers/redact",
    "shop/redact",
]


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def normalize_shop_domain(value: str) -> str:
    domain = str(value or "").strip().lower()
    domain = domain.removeprefix("https://").removeprefix("http://").strip("/")
    if "/" in domain or ":" in domain or not SHOP_DOMAIN_RE.fullmatch(domain):
        raise RuntimeError("Domínio Shopify inválido. Use nomedaloja.myshopify.com.")
    return domain


def settings() -> Dict[str, str]:
    result = {
        "client_id": _env("SHOPIFY_CLIENT_ID"),
        "client_secret": _env("SHOPIFY_CLIENT_SECRET"),
        "redirect_uri": _env("SHOPIFY_OAUTH_REDIRECT_URI"),
    }
    missing = [key for key, value in result.items() if not value]
    if missing:
        raise RuntimeError(f"OAuth Shopify não configurado: {', '.join(missing)}")
    return result


async def authorization_url(*, user_id: str, client_id: str, shop_domain: str) -> str:
    shop = normalize_shop_domain(shop_domain)
    config = settings()
    state = await create_oauth_state(
        provider="shopify",
        user_id=user_id,
        client_id=client_id,
        redirect_uri=config["redirect_uri"],
        context={"shop_domain": shop},
    )
    params = {
        "client_id": config["client_id"],
        "scope": ",".join(SHOPIFY_SCOPES),
        "redirect_uri": config["redirect_uri"],
        "state": state,
    }
    return f"https://{shop}/admin/oauth/authorize?{urlencode(params)}"


def verify_callback_hmac(params: Dict[str, str]) -> bool:
    provided = str(params.get("hmac") or "")
    if not provided:
        return False
    message = "&".join(
        f"{key}={value}" for key, value in sorted(params.items()) if key not in {"hmac", "signature"}
    )
    expected = hmac.new(
        settings()["client_secret"].encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, provided)


async def exchange_code(*, shop_domain: str, code: str) -> Dict[str, Any]:
    shop = normalize_shop_domain(shop_domain)
    config = settings()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"https://{shop}/admin/oauth/access_token",
            json={"client_id": config["client_id"], "client_secret": config["client_secret"], "code": code},
        )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("access_token"):
        raise RuntimeError("Shopify não retornou token offline.")
    return payload


async def fetch_shop(shop_domain: str, access_token: str) -> Dict[str, Any]:
    shop = normalize_shop_domain(shop_domain)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"https://{shop}/admin/api/2025-01/shop.json",
            headers={"X-Shopify-Access-Token": access_token},
        )
    response.raise_for_status()
    return response.json().get("shop") or {}


async def register_webhooks(shop_domain: str, access_token: str) -> None:
    shop = normalize_shop_domain(shop_domain)
    callback = _env("SHOPIFY_WEBHOOK_URL")
    if not callback.startswith("https://"):
        raise RuntimeError("SHOPIFY_WEBHOOK_URL HTTPS não configurada.")
    async with httpx.AsyncClient(timeout=30) as client:
        for topic in SHOPIFY_WEBHOOK_TOPICS:
            response = await client.post(
                f"https://{shop}/admin/api/2025-01/webhooks.json",
                headers={"X-Shopify-Access-Token": access_token},
                json={"webhook": {"topic": topic, "address": callback, "format": "json"}},
            )
            if response.status_code == 422 and "already" in response.text.lower():
                continue
            response.raise_for_status()


async def save_shopify_connection(
    *,
    client_id: str,
    user_id: str,
    shop_domain: str,
    token: Dict[str, Any],
    shop: Dict[str, Any],
) -> Dict[str, Any]:
    domain = normalize_shop_domain(shop_domain)
    existing = await sb_select("shopify_stores", filters={"shop_domain": f"eq.{domain}"}, limit=1)
    if existing and str(existing[0].get("client_id") or "") != client_id:
        raise RuntimeError("Esta loja Shopify já pertence a outra empresa.")
    connection = await upsert_connection(
        client_id=client_id,
        provider="shopify",
        external_key=domain,
        token_payload=json.dumps({"access_token": token["access_token"]}),
        user_id=user_id,
        status="connected",
        account_id=str(shop.get("id") or ""),
        account_name=str(shop.get("name") or domain),
        scopes=str(token.get("scope") or "").split(","),
        metadata={
            "shop_domain": domain,
            "currency": shop.get("currency"),
            "timezone": shop.get("iana_timezone") or shop.get("timezone"),
        },
    )
    row = {
        "client_id": client_id,
        "connection_id": connection.get("id"),
        "shop_id": str(shop.get("id") or ""),
        "shop_domain": domain,
        "shop_name": str(shop.get("name") or domain),
        "currency": str(shop.get("currency") or ""),
        "timezone": str(shop.get("iana_timezone") or shop.get("timezone") or ""),
        "status": "active",
        "uninstalled_at": None,
    }
    if existing:
        await sb_update(
            "shopify_stores", filters={"id": f"eq.{existing[0]['id']}"}, patch=row, returning="minimal"
        )
    else:
        await sb_insert("shopify_stores", row, returning="minimal")
    return connection


async def resolve_store_by_domain(shop_domain: str) -> Dict[str, Any] | None:
    domain = normalize_shop_domain(shop_domain)
    rows = await sb_select(
        "shopify_stores",
        filters={"shop_domain": f"eq.{domain}"},
        limit=1,
    )
    return rows[0] if rows else None


async def mark_store_uninstalled(shop_domain: str) -> None:
    domain = normalize_shop_domain(shop_domain)
    stores = await sb_select("shopify_stores", filters={"shop_domain": f"eq.{domain}"}, limit=1)
    if not stores:
        return
    now = datetime.now(timezone.utc).isoformat()
    await sb_update(
        "shopify_stores",
        filters={"id": f"eq.{stores[0]['id']}"},
        patch={"status": "uninstalled", "uninstalled_at": now, "updated_at": now},
        returning="minimal",
    )
    await sb_update(
        "integration_connections",
        filters={"id": f"eq.{stores[0]['connection_id']}", "client_id": f"eq.{stores[0]['client_id']}"},
        patch={"status": "disconnected", "disconnected_at": now, "updated_at": now},
        returning="minimal",
    )
