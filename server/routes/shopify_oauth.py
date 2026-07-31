from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Dict
from urllib.parse import urlencode

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import RedirectResponse

from services.generic_connections import disconnect_generic_connection, get_connection
from services.oauth_state import consume_oauth_state
from services.shopify_oauth import (
    authorization_url,
    exchange_code,
    fetch_shop,
    normalize_shop_domain,
    register_webhooks,
    select_shopify_connection,
    sync_shopify_connection,
    save_shopify_connection,
    verify_callback_hmac,
)
from services.tenant import require_client_role, require_user_client_access, require_user_id

router = APIRouter(prefix="/api/oauth/shopify", tags=["shopify-oauth"])


def _frontend_redirect(params: Dict[str, str]) -> str:
    base = (os.getenv("FRONTEND_URL") or "http://localhost:5173").strip().rstrip("/")
    return f"{base}/?onboarding=1&{urlencode(params)}"


@router.get("/start")
async def start(
    shop: str,
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_role(client_id or x_client_id, authorization)
    user_id = await require_user_id(authorization)
    domain = normalize_shop_domain(shop)
    return {
        "ok": True,
        "client_id": cid,
        "shop_domain": domain,
        "authorization_url": await authorization_url(user_id=user_id, client_id=cid, shop_domain=domain),
    }


@router.get("/callback")
async def callback(request: Request):
    try:
        params = {key: value for key, value in request.query_params.items()}
        if not verify_callback_hmac(params):
            raise RuntimeError("HMAC do callback Shopify inválido.")
        code = str(params.get("code") or "")
        state = str(params.get("state") or "")
        shop_domain = normalize_shop_domain(str(params.get("shop") or ""))
        if not code or not state:
            raise RuntimeError("Callback Shopify sem code ou state.")
        session = await consume_oauth_state(state, provider="shopify")
        expected_shop = normalize_shop_domain(str((session.get("context") or {}).get("shop_domain") or ""))
        if shop_domain != expected_shop:
            raise RuntimeError("A loja retornada não corresponde à loja autorizada.")
        user_id = str(session.get("user_id") or "")
        client_id = str(session.get("client_id") or "")
        await require_user_client_access(user_id, client_id)
        token = await exchange_code(shop_domain=shop_domain, code=code)
        shop = await fetch_shop(shop_domain, str(token.get("access_token") or ""))
        await register_webhooks(shop_domain, str(token.get("access_token") or ""))
        connection = await save_shopify_connection(
            client_id=client_id, user_id=user_id, shop_domain=shop_domain, token=token, shop=shop
        )
        return RedirectResponse(
            _frontend_redirect({"shopify_oauth": "success", "connection_id": str(connection.get("id") or "")}),
            status_code=302,
        )
    except Exception as exc:
        return RedirectResponse(
            _frontend_redirect({"shopify_oauth": "error", "error": str(exc)[:160]}),
            status_code=302,
        )


@router.get("/{connection_id}/status")
async def status(
    connection_id: str,
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_role(
        client_id or x_client_id, authorization, allowed_roles=("agency_admin", "client_admin", "viewer")
    )
    row = await get_connection(cid, connection_id)
    return {"ok": True, "connection": {k: v for k, v in row.items() if not k.startswith("encrypted")}}


@router.post("/{connection_id}/select")
async def select_store(
    connection_id: str,
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_role(client_id or x_client_id, authorization)
    user_id = await require_user_id(authorization)
    connection = await select_shopify_connection(
        client_id=cid,
        connection_id=connection_id,
        user_id=user_id,
    )
    return {"ok": True, "connection": connection}


@router.post("/{connection_id}/sync")
async def sync_store(
    connection_id: str,
    days: int = Query(default=30, ge=1, le=366),
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_role(client_id or x_client_id, authorization)
    created_at_min = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).isoformat()
    return await sync_shopify_connection(
        client_id=cid,
        connection_id=connection_id,
        created_at_min=created_at_min,
    )


@router.delete("/{connection_id}")
async def disconnect(
    connection_id: str,
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_role(client_id or x_client_id, authorization)
    user_id = await require_user_id(authorization)
    return {"ok": True, "connection": await disconnect_generic_connection(cid, connection_id, user_id)}
