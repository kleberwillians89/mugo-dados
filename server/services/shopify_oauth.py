from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict
from urllib.parse import urlencode, urlsplit

import httpx

from .generic_connections import (
    audit_connection,
    get_connection,
    upsert_connection,
)
from .ig_supabase import sb_insert, sb_select, sb_update
from .integration_errors import IntegrationError, from_httpx_error
from .oauth_state import create_oauth_state
from .shopify_config import shopify_admin_url

SHOP_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]\.myshopify\.com$")
SHOPIFY_SCOPES = ["read_orders", "read_customers", "read_products"]
SHOPIFY_PRODUCTION_REDIRECT_URI = "https://api.dados.mugoagencia.com.br/api/oauth/shopify/callback"
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


def _is_production() -> bool:
    return _env("APP_ENV").lower() in {"prod", "production"} or _env("RENDER").lower() == "true"


def _validated_redirect_uri(value: str) -> str:
    redirect_uri = str(value or "").strip()
    if not redirect_uri:
        raise RuntimeError("OAuth Shopify não configurado: redirect_uri")
    parsed = urlsplit(redirect_uri)
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise RuntimeError("SHOPIFY_OAUTH_REDIRECT_URI deve ser uma URL de callback sem query ou fragmento.")
    if parsed.path != "/api/oauth/shopify/callback" or redirect_uri.endswith("/"):
        raise RuntimeError("SHOPIFY_OAUTH_REDIRECT_URI deve terminar exatamente em /api/oauth/shopify/callback.")
    if _is_production() and redirect_uri != SHOPIFY_PRODUCTION_REDIRECT_URI:
        raise RuntimeError(
            "SHOPIFY_OAUTH_REDIRECT_URI de produção deve ser "
            f"{SHOPIFY_PRODUCTION_REDIRECT_URI}."
        )
    if parsed.scheme == "https" and parsed.netloc:
        return redirect_uri
    if not _is_production() and parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}:
        return redirect_uri
    raise RuntimeError("SHOPIFY_OAUTH_REDIRECT_URI deve usar HTTPS (HTTP é permitido apenas em localhost).")


def safe_oauth_configuration() -> Dict[str, str]:
    config = settings()
    client_id = config["client_id"]
    return {
        "redirect_uri": config["redirect_uri"],
        "client_id_hint": f"...{client_id[-6:]}" if len(client_id) > 6 else "configured",
    }


def normalize_shop_domain(value: str) -> str:
    domain = str(value or "").strip().lower()
    domain = domain.removeprefix("https://").removeprefix("http://").strip("/")
    if "/" in domain or ":" in domain or not SHOP_DOMAIN_RE.fullmatch(domain):
        raise RuntimeError("Domínio Shopify inválido. Use nomedaloja.myshopify.com.")
    return domain


@dataclass(frozen=True)
class ShopifyConnectionContext:
    client_id: str
    connection_id: str | None
    shop_domain: str
    access_token: str
    scopes: frozenset[str]
    auth_mode: str


def _legacy_shopify_context(client_id: str) -> ShopifyConnectionContext | None:
    domain = _env("SHOPIFY_SHOP_DOMAIN") or _env("SHOPIFY_STORE_DOMAIN")
    token = _env("SHOPIFY_ACCESS_TOKEN") or _env("SHOPIFY_ADMIN_ACCESS_TOKEN")
    if not domain and not token:
        return None
    if not domain:
        raise IntegrationError(
            "O domínio da loja Shopify não está configurado.",
            status_code=409,
            code="SHOPIFY_STORE_SELECTION_REQUIRED",
            provider="shopify",
        )
    if not token:
        raise IntegrationError(
            "A conexão Shopify requer nova autorização.",
            status_code=401,
            code="SHOPIFY_REAUTH_REQUIRED",
            provider="shopify",
        )
    return ShopifyConnectionContext(
        client_id=client_id,
        connection_id=None,
        shop_domain=normalize_shop_domain(domain),
        access_token=token,
        scopes=frozenset(SHOPIFY_SCOPES),
        auth_mode="legacy",
    )


async def resolve_shopify_connection_context(
    client_id: str,
    *,
    connection_id: str | None = None,
    required_scopes: tuple[str, ...] = (),
) -> ShopifyConnectionContext:
    cid = str(client_id or "").strip()
    requested_connection_id = str(connection_id or "").strip()
    if requested_connection_id:
        try:
            rows = [await get_connection(cid, requested_connection_id, include_token=True)]
        except Exception as exc:
            raise IntegrationError(
                "Conexão Shopify não encontrada para a empresa selecionada.",
                status_code=404,
                code="SHOPIFY_CONNECTION_NOT_FOUND",
                provider="shopify",
            ) from exc
    else:
        rows = await sb_select(
            "integration_connections",
            filters={"client_id": f"eq.{cid}", "provider": "eq.shopify"},
            order="updated_at.desc",
            limit=50,
        )
        rows = [
            row
            for row in rows
            if str(row.get("status") or "").strip().lower() != "disconnected"
        ]
        selected = [
            row
            for row in rows
            if isinstance(row.get("metadata"), dict)
            and bool(row["metadata"].get("selected_for_reporting"))
        ]
        if len(selected) == 1:
            rows = selected
        elif len(rows) > 1:
            raise IntegrationError(
                "Selecione qual loja Shopify deve alimentar os relatórios.",
                status_code=409,
                code="SHOPIFY_STORE_SELECTION_REQUIRED",
                provider="shopify",
            )
        if rows:
            try:
                rows = [await get_connection(cid, str(rows[0].get("id") or ""), include_token=True)]
            except Exception as exc:
                raise IntegrationError(
                    "A conexão Shopify requer nova autorização.",
                    status_code=401,
                    code="SHOPIFY_REAUTH_REQUIRED",
                    provider="shopify",
                ) from exc

    if not rows:
        legacy = _legacy_shopify_context(cid)
        if legacy:
            return legacy
        raise IntegrationError(
            "Nenhuma conexão Shopify ativa foi encontrada para a empresa selecionada.",
            status_code=404,
            code="SHOPIFY_CONNECTION_NOT_FOUND",
            provider="shopify",
        )

    row = rows[0]
    if str(row.get("client_id") or "").strip() != cid or str(row.get("provider") or "") != "shopify":
        raise IntegrationError(
            "Conexão Shopify não encontrada para a empresa selecionada.",
            status_code=404,
            code="SHOPIFY_CONNECTION_NOT_FOUND",
            provider="shopify",
        )
    status = str(row.get("status") or "").strip().lower()
    if status in {"needs_reauth", "reauth_required", "token_expired", "error"}:
        raise IntegrationError(
            "A conexão Shopify requer nova autorização.",
            status_code=401,
            code="SHOPIFY_REAUTH_REQUIRED",
            provider="shopify",
        )
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    domain_value = metadata.get("shop_domain") or row.get("external_key")
    if not str(domain_value or "").strip():
        raise IntegrationError(
            "Selecione uma loja Shopify para esta conexão.",
            status_code=409,
            code="SHOPIFY_STORE_SELECTION_REQUIRED",
            provider="shopify",
        )
    domain = normalize_shop_domain(str(domain_value))
    try:
        token_payload = json.loads(str(row.get("_token") or "{}"))
    except (TypeError, ValueError) as exc:
        raise IntegrationError(
            "A conexão Shopify requer nova autorização.",
            status_code=401,
            code="SHOPIFY_REAUTH_REQUIRED",
            provider="shopify",
        ) from exc
    access_token = str(token_payload.get("access_token") or "").strip()
    if not access_token:
        raise IntegrationError(
            "A conexão Shopify requer nova autorização.",
            status_code=401,
            code="SHOPIFY_REAUTH_REQUIRED",
            provider="shopify",
        )
    scopes = frozenset(
        str(scope or "").strip()
        for scope in (row.get("scopes") or [])
        if str(scope or "").strip()
    )
    missing_scopes = sorted(set(required_scopes) - set(scopes))
    if missing_scopes:
        raise IntegrationError(
            "A conexão Shopify não possui os escopos necessários. Autorize novamente a loja.",
            status_code=403,
            code="SHOPIFY_INSUFFICIENT_SCOPE",
            provider="shopify",
        )
    return ShopifyConnectionContext(
        client_id=cid,
        connection_id=str(row.get("id") or "").strip() or None,
        shop_domain=domain,
        access_token=access_token,
        scopes=scopes,
        auth_mode="oauth",
    )


async def select_shopify_connection(
    *,
    client_id: str,
    connection_id: str,
    user_id: str,
) -> Dict[str, Any]:
    selected = await get_connection(client_id, connection_id)
    if str(selected.get("provider") or "") != "shopify":
        raise IntegrationError(
            "Conexão Shopify não encontrada para a empresa selecionada.",
            status_code=404,
            code="SHOPIFY_CONNECTION_NOT_FOUND",
            provider="shopify",
        )
    rows = await sb_select(
        "integration_connections",
        filters={"client_id": f"eq.{client_id}", "provider": "eq.shopify"},
        limit=50,
    )
    for row in rows:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        should_select = str(row.get("id") or "") == connection_id
        if bool(metadata.get("selected_for_reporting")) == should_select:
            continue
        await sb_update(
            "integration_connections",
            filters={"id": f"eq.{row['id']}", "client_id": f"eq.{client_id}"},
            patch={"metadata": {**metadata, "selected_for_reporting": should_select}},
            returning="minimal",
        )
    await audit_connection(
        client_id=client_id,
        connection_id=connection_id,
        user_id=user_id,
        event_type="shopify_store_selected",
        details={"provider": "shopify"},
    )
    return {
        "id": connection_id,
        "client_id": client_id,
        "provider": "shopify",
        "metadata": {
            **(selected.get("metadata") if isinstance(selected.get("metadata"), dict) else {}),
            "selected_for_reporting": True,
        },
    }


def settings() -> Dict[str, str]:
    result = {
        "client_id": _env("SHOPIFY_CLIENT_ID"),
        "client_secret": _env("SHOPIFY_CLIENT_SECRET"),
        "redirect_uri": _validated_redirect_uri(_env("SHOPIFY_OAUTH_REDIRECT_URI")),
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
        try:
            response = await client.get(
                shopify_admin_url(shop, "shop.json"),
                headers={"X-Shopify-Access-Token": access_token},
            )
            response.raise_for_status()
        except Exception as exc:
            raise from_httpx_error(
                "shopify",
                exc,
                operation="consultar a loja",
            ) from exc
    return response.json().get("shop") or {}


async def register_webhooks(shop_domain: str, access_token: str) -> None:
    shop = normalize_shop_domain(shop_domain)
    callback = _env("SHOPIFY_WEBHOOK_URL")
    if not callback.startswith("https://"):
        raise RuntimeError("SHOPIFY_WEBHOOK_URL HTTPS não configurada.")
    async with httpx.AsyncClient(timeout=30) as client:
        for topic in SHOPIFY_WEBHOOK_TOPICS:
            response = await client.post(
                shopify_admin_url(shop, "webhooks.json"),
                headers={"X-Shopify-Access-Token": access_token},
                json={"webhook": {"topic": topic, "address": callback, "format": "json"}},
            )
            if response.status_code == 422 and "already" in response.text.lower():
                continue
            response.raise_for_status()


async def _fetch_shopify_collection(
    context: ShopifyConnectionContext,
    resource: str,
    *,
    params: Dict[str, Any] | None = None,
) -> list[Dict[str, Any]]:
    url = shopify_admin_url(context.shop_domain, resource)
    query = dict(params or {})
    rows: list[Dict[str, Any]] = []
    collection_key = resource.split(".", 1)[0]
    async with httpx.AsyncClient(timeout=45) as client:
        for _ in range(20):
            try:
                response = await client.get(
                    url,
                    headers={"X-Shopify-Access-Token": context.access_token},
                    params=query,
                )
                response.raise_for_status()
            except Exception as exc:
                raise from_httpx_error(
                    "shopify",
                    exc,
                    operation=f"consultar {collection_key}",
                ) from exc
            payload = response.json()
            page_rows = payload.get(collection_key) if isinstance(payload, dict) else []
            if isinstance(page_rows, list):
                rows.extend(item for item in page_rows if isinstance(item, dict))
            next_link = response.links.get("next", {}).get("url")
            if not next_link:
                break
            url = str(next_link)
            query = {}
    return rows


async def sync_shopify_connection(
    *,
    client_id: str,
    connection_id: str,
    created_at_min: str | None = None,
) -> Dict[str, Any]:
    context = await resolve_shopify_connection_context(
        client_id,
        connection_id=connection_id,
        required_scopes=("read_orders", "read_customers", "read_products"),
    )
    order_params: Dict[str, Any] = {"status": "any", "limit": 250}
    if str(created_at_min or "").strip():
        order_params["created_at_min"] = str(created_at_min).strip()
    orders = await _fetch_shopify_collection(
        context,
        "orders.json",
        params=order_params,
    )
    customers = await _fetch_shopify_collection(
        context,
        "customers.json",
        params={"limit": 250},
    )
    products = await _fetch_shopify_collection(
        context,
        "products.json",
        params={"limit": 250},
    )

    from .shopify_webhooks import _handle_customer_topic, _handle_order_topic

    item_count = 0
    for customer in customers:
        await _handle_customer_topic(
            client_id=client_id,
            shop_domain=context.shop_domain,
            payload=customer,
        )
    for order in orders:
        result = await _handle_order_topic(
            client_id=client_id,
            shop_domain=context.shop_domain,
            payload=order,
        )
        item_count += int(result.get("items_upserted") or 0)

    now = datetime.now(timezone.utc).isoformat()
    if context.connection_id:
        await sb_update(
            "integration_connections",
            filters={
                "id": f"eq.{context.connection_id}",
                "client_id": f"eq.{client_id}",
            },
            patch={
                "status": "connected",
                "last_sync_at": now,
                "last_error": None,
                "updated_at": now,
            },
            returning="minimal",
        )
    return {
        "ok": True,
        "client_id": client_id,
        "connection_id": context.connection_id,
        "shop_domain": context.shop_domain,
        "synced": {
            "orders": len(orders),
            "customers": len(customers),
            "products_checked": len(products),
            "order_items": item_count,
        },
    }


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
            "selected_for_reporting": True,
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
    return await select_shopify_connection(
        client_id=client_id,
        connection_id=str(connection.get("id") or ""),
        user_id=user_id,
    )


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
