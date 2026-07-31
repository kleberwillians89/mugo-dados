from __future__ import annotations

import os
from typing import Any, Dict
from urllib.parse import urlencode

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from services.generic_connections import (
    disconnect_generic_connection,
    get_connection,
    list_generic_connections,
    update_connection_selection,
    google_capabilities,
)
from services.google_oauth import (
    authorization_url,
    exchange_code,
    fetch_google_identity,
    list_ga4_properties,
    list_ga4_streams,
    list_google_ads_accounts,
    get_google_access_token,
    normalize_integration_product,
    save_google_authorization,
)
from services.ga4_sync import sync_ga4_for_period
from services.integration_errors import IntegrationError
from services.oauth_state import consume_oauth_state
from services.tenant import require_client_read, require_client_role, require_user_client_access, require_user_id

router = APIRouter(prefix="/api/oauth/google", tags=["google-oauth"])


def _frontend_redirect(params: Dict[str, str]) -> str:
    base = (os.getenv("FRONTEND_URL") or "http://localhost:5173").strip().rstrip("/")
    return f"{base}/?onboarding=1&{urlencode(params)}"


async def _start_product(
    product: str,
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_role(client_id or x_client_id, authorization)
    user_id = await require_user_id(authorization)
    integration_product = normalize_integration_product(product)
    return {
        "ok": True,
        "client_id": cid,
        "integration_product": integration_product,
        "authorization_url": await authorization_url(user_id=user_id, client_id=cid, product=integration_product),
    }


@router.get("/ga4/start")
async def start_ga4(
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    return await _start_product("ga4", client_id, x_client_id, authorization)


@router.get("/ads/start")
async def start_ads(
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    return await _start_product("google_ads", client_id, x_client_id, authorization)


@router.get("/start", deprecated=True)
async def start_legacy(
    product: str = Query(default="ga4"),
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    return await _start_product(product, client_id, x_client_id, authorization)


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    try:
        if error:
            raise RuntimeError(f"Google recusou a autorização: {error}")
        if not code or not state:
            raise RuntimeError("Callback Google sem code ou state.")
        session = await consume_oauth_state(state, provider="google")
        user_id = str(session.get("user_id") or "")
        client_id = str(session.get("client_id") or "")
        context = session.get("context") if isinstance(session.get("context"), dict) else {}
        product = normalize_integration_product(
            str(context.get("integration_product") or context.get("product") or "")
        )
        request.state.integration_product = product
        await require_user_client_access(user_id, client_id)
        token = await exchange_code(code, str(session.get("redirect_uri") or ""))
        identity = await fetch_google_identity(str(token.get("access_token") or ""))
        connection = await save_google_authorization(
            client_id=client_id, user_id=user_id, token=token, identity=identity, product=product
        )
        return RedirectResponse(
            _frontend_redirect({
                "google_oauth": "success",
                "integration_product": product,
                "connection_id": str(connection.get("id") or ""),
            }),
            status_code=302,
        )
    except Exception as exc:
        return RedirectResponse(
            _frontend_redirect({"google_oauth": "error", "error": str(exc)[:160]}),
            status_code=302,
        )


@router.get("/connections")
async def connections(
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_read(client_id or x_client_id, authorization)
    rows = await list_generic_connections(cid)
    return {"ok": True, "connections": [row for row in rows if row.get("provider") in {"ga4", "google_ads"}]}


@router.get("/{connection_id}/ga4/properties")
async def ga4_properties(
    connection_id: str,
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_read(client_id or x_client_id, authorization)
    row = await get_connection(cid, connection_id)
    if not google_capabilities(row)["ga4_authorized"]:
        raise IntegrationError(
            "Autorize o Google Analytics com o escopo analytics.readonly.",
            status_code=403,
            code="GOOGLE_INSUFFICIENT_SCOPE",
            provider="google",
        )
    properties = await list_ga4_properties(cid, connection_id)
    return {
        "ok": True,
        "properties": properties,
        "property_count": len(properties),
        "message": None if properties else f"O usuário {row.get('account_name') or 'Google autorizado'} não possui acesso a nenhuma propriedade GA4.",
    }


@router.post("/{connection_id}/ga4/select")
async def select_ga4(
    connection_id: str,
    payload: Dict[str, Any],
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_role(client_id or x_client_id, authorization)
    user_id = await require_user_id(authorization)
    row = await get_connection(cid, connection_id)
    if not google_capabilities(row)["ga4_authorized"]:
        raise IntegrationError(
            "Autorize o Google Analytics com o escopo analytics.readonly.",
            status_code=403,
            code="GOOGLE_INSUFFICIENT_SCOPE",
            provider="google",
        )
    property_id = str(payload.get("property_id") or "").strip().removeprefix("properties/")
    if not property_id:
        raise HTTPException(status_code=400, detail="property_id é obrigatório.")
    connection = await update_connection_selection(
        client_id=cid,
        connection_id=connection_id,
        user_id=user_id,
        metadata_patch={
            "ga4_property_id": property_id,
            "ga4_account_id": str(payload.get("account_id") or "").strip() or None,
            "ga4_property_name": str(payload.get("property_name") or "").strip() or None,
            "ga4_stream_id": str(payload.get("stream_id") or "").strip() or None,
        },
    )
    return {"ok": True, "connection": connection}


@router.get("/{connection_id}/ga4/streams")
async def ga4_streams(
    connection_id: str,
    property_id: str,
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_read(client_id or x_client_id, authorization)
    return {"ok": True, "streams": await list_ga4_streams(cid, connection_id, property_id)}


@router.get("/{connection_id}/ads/accounts")
async def ads_accounts(
    connection_id: str,
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_read(client_id or x_client_id, authorization)
    row = await get_connection(cid, connection_id)
    if not google_capabilities(row)["ads_authorized"]:
        raise IntegrationError(
            "Autorize o Google Ads com o escopo adwords.",
            status_code=403,
            code="GOOGLE_ADS_INSUFFICIENT_SCOPE",
            provider="google",
        )
    return {"ok": True, **(await list_google_ads_accounts(cid, connection_id))}


@router.post("/{connection_id}/ads/select")
async def select_ads(
    connection_id: str,
    payload: Dict[str, Any],
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_role(client_id or x_client_id, authorization)
    user_id = await require_user_id(authorization)
    row = await get_connection(cid, connection_id)
    if not google_capabilities(row)["ads_authorized"]:
        raise IntegrationError(
            "Autorize o Google Ads com o escopo adwords.",
            status_code=403,
            code="GOOGLE_ADS_INSUFFICIENT_SCOPE",
            provider="google",
        )
    customer_id = str(payload.get("customer_id") or "").replace("-", "").strip()
    if not customer_id.isdigit():
        raise HTTPException(status_code=400, detail="customer_id do Google Ads inválido.")
    connection = await update_connection_selection(
        client_id=cid,
        connection_id=connection_id,
        user_id=user_id,
        metadata_patch={
            "google_ads_customer_id": customer_id,
            "google_ads_login_customer_id": str(payload.get("login_customer_id") or "").replace("-", "").strip() or None,
        },
    )
    return {"ok": True, "connection": connection}


@router.get("/{connection_id}/status")
async def status(
    connection_id: str,
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_read(client_id or x_client_id, authorization)
    row = await get_connection(cid, connection_id)
    return {"ok": True, "connection": {k: v for k, v in row.items() if not k.startswith("encrypted")}}


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


@router.post("/{connection_id}/sync")
async def sync(
    connection_id: str,
    days: int = Query(default=30, ge=1, le=366),
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_role(client_id or x_client_id, authorization)
    row = await get_connection(cid, connection_id)
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    property_id = str(metadata.get("ga4_property_id") or "")
    if not property_id:
        raise HTTPException(status_code=409, detail="Selecione uma propriedade GA4 antes da sincronização.")
    access_token = await get_google_access_token(cid, connection_id)
    payload = await sync_ga4_for_period(
        client_id=cid,
        property_id=property_id,
        access_token=access_token,
        days=days,
        job_name="ga4_sync_manual",
        trigger_source="manual_oauth_connection",
        record_job_run=True,
    )
    return {"ok": True, "ga4": payload, "google_ads": {"synced": False, "reason": "Sincronização Google Ads ainda não implementada."}}
