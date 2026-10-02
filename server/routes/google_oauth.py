from __future__ import annotations

import os
from datetime import datetime, timezone
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
    get_google_connection_diagnostics,
    normalize_integration_product,
    save_google_authorization,
)
from services.ga4_sync import sync_ga4_for_period
from services.google_ads_ids import normalize_google_ads_customer_id
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
    request_id = str(getattr(getattr(request, "state", None), "request_id", "") or "-")
    try:
        if error:
            raise RuntimeError(f"Google recusou a autorização: {error}")
        if not code or not state:
            raise RuntimeError("Callback Google sem code ou state.")
        session = await consume_oauth_state(state, provider="google")
        print(f"[google_oauth][callback] request_id={request_id} stage=state_validated")
        user_id = str(session.get("user_id") or "")
        client_id = str(session.get("client_id") or "")
        context = session.get("context") if isinstance(session.get("context"), dict) else {}
        product = normalize_integration_product(
            str(context.get("integration_product") or context.get("product") or "")
        )
        request.state.integration_product = product
        await require_user_client_access(user_id, client_id)
        print(
            f"[google_oauth][callback] request_id={request_id} user_id={user_id} "
            f"client_id={client_id} provider={product} stage=client_resolved"
        )
        token = await exchange_code(code, str(session.get("redirect_uri") or ""))
        print(
            f"[google_oauth][callback] request_id={request_id} client_id={client_id} "
            f"provider={product} stage=token_exchanged scopes_received={bool(token.get('scope'))}"
        )
        identity = await fetch_google_identity(str(token.get("access_token") or ""))
        connection = await save_google_authorization(
            client_id=client_id, user_id=user_id, token=token, identity=identity, product=product
        )
        print(
            f"[google_oauth][callback] request_id={request_id} client_id={client_id} "
            f"provider={product} connection_id={connection.get('id') or '-'} stage=connection_saved"
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
        print(
            f"[google_oauth][callback] request_id={request_id} stage=error "
            f"error_type={exc.__class__.__name__}"
        )
        public_error = (
            exc.public_message
            if isinstance(exc, IntegrationError)
            else "Não foi possível concluir a autorização Google. Tente novamente."
        )
        return RedirectResponse(
            _frontend_redirect({"google_oauth": "error", "error": public_error[:160]}),
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
    request: Request = None,
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_read(client_id or x_client_id, authorization)
    row = await get_connection(cid, connection_id)
    request_id = str(getattr(getattr(request, "state", None), "request_id", "") or "-")
    try:
        diagnostics = await get_google_connection_diagnostics(cid, connection_id)
    except Exception:
        diagnostics = {
            "connection_id": connection_id, "client_id": cid,
            "provider": str(row.get("provider") or ""), "connection_status": str(row.get("status") or ""),
            "disconnected_at": row.get("disconnected_at"), "scopes": row.get("scopes") or [],
            "token_expires_at": row.get("token_expires_at"),
            "access_token_available": bool(row.get("token_available")),
            "refresh_token_available": bool((row.get("metadata") or {}).get("refresh_token_available")) if isinstance(row.get("metadata"), dict) else False,
            "token_storage_format": "unavailable", "authorized_email": row.get("account_name"),
        }
    if not google_capabilities(row)["ga4_authorized"]:
        raise IntegrationError(
            "Autorize o Google Analytics com o escopo analytics.readonly.",
            status_code=403, code="GOOGLE_SCOPE_INSUFFICIENT", provider="google",
            diagnostics={**diagnostics, "refresh_attempted": False, "refresh_result": "not_attempted", "request_id": request_id},
        )
    expires_raw = str(diagnostics.get("token_expires_at") or "")
    try:
        expired = bool(expires_raw) and datetime.fromisoformat(expires_raw.replace("Z", "+00:00")) <= datetime.now(timezone.utc)
    except ValueError:
        expired = False
    properties = await list_ga4_properties(cid, connection_id, request_id=request_id)
    if not properties:
        raise IntegrationError(
            "O usuário Google autorizado não possui acesso a nenhuma propriedade GA4.",
            status_code=409, code="GOOGLE_NO_PROPERTIES_AVAILABLE", provider="google",
            diagnostics={
                **diagnostics, "refresh_attempted": expired,
                "refresh_result": "succeeded" if expired else "not_required", "request_id": request_id,
            },
        )
    return {
        "ok": True,
        "properties": properties,
        "property_count": len(properties),
        "message": None,
        "diagnostics": {
            **diagnostics, "refresh_attempted": expired,
            "refresh_result": "succeeded" if expired else "not_required", "request_id": request_id,
        },
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
            code="GOOGLE_SCOPE_INSUFFICIENT",
            provider="google",
        )
    property_id = str(payload.get("property_id") or "").strip().removeprefix("properties/")
    if not property_id:
        raise HTTPException(status_code=400, detail="property_id é obrigatório.")
    stream_id = str(payload.get("stream_id") or "").strip()
    streams = await list_ga4_streams(cid, connection_id, property_id)
    if not streams:
        raise IntegrationError(
            "A propriedade selecionada não possui streams acessíveis.", status_code=404,
            code="GOOGLE_STREAM_UNAVAILABLE", provider="google",
        )
    selected_stream = next(
        (item for item in streams if str(item.get("name") or "").split("/")[-1] == stream_id),
        None,
    )
    if not selected_stream:
        raise IntegrationError(
            "O stream selecionado não está disponível nesta propriedade.", status_code=404,
            code="GOOGLE_STREAM_UNAVAILABLE", provider="google",
        )
    connection = await update_connection_selection(
        client_id=cid,
        connection_id=connection_id,
        user_id=user_id,
        metadata_patch={
            "ga4_property_id": property_id,
            "ga4_account_id": str(payload.get("account_id") or "").strip() or None,
            "ga4_property_name": str(payload.get("property_name") or "").strip() or None,
            "ga4_stream_id": stream_id,
            "ga4_stream_name": str(selected_stream.get("display_name") or "").strip() or None,
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
    row = await get_connection(cid, connection_id)
    if not google_capabilities(row)["ga4_authorized"]:
        raise IntegrationError(
            "Autorize o Google Analytics com o escopo analytics.readonly.",
            status_code=403,
            code="GOOGLE_SCOPE_INSUFFICIENT",
            provider="google",
        )
    return {"ok": True, "streams": await list_ga4_streams(cid, connection_id, property_id)}


@router.get("/{connection_id}/ads/accounts")
async def ads_accounts(
    connection_id: str,
    request: Request = None,
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
            code="GOOGLE_SCOPE_INSUFFICIENT",
            provider="google",
        )
    request_id = str(getattr(getattr(request, "state", None), "request_id", "") or "-")
    return {"ok": True, **(await list_google_ads_accounts(cid, connection_id, request_id=request_id))}


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
            code="GOOGLE_SCOPE_INSUFFICIENT",
            provider="google",
        )
    customer_id = normalize_google_ads_customer_id(payload.get("customer_id"))
    if not customer_id:
        raise HTTPException(status_code=400, detail="customer_id do Google Ads inválido.")
    selection = _resolve_google_ads_selection(row, customer_id)
    print(
        "[google_ads] stage=select_customer "
        f"client_id={cid} connection_id={connection_id} customer_id={customer_id} "
        f"login_customer_id={selection['login_customer_id'] or 'none'} source={selection['source']}"
    )
    connection = await update_connection_selection(
        client_id=cid,
        connection_id=connection_id,
        user_id=user_id,
        metadata_patch={
            "google_ads_customer_id": customer_id,
            "google_ads_login_customer_id": selection["login_customer_id"],
            "google_ads_customer_name": selection["customer_name"],
        },
    )
    return {"ok": True, "connection": connection}


_GOOGLE_ADS_NOT_ENABLED_STATUSES = {"CANCELED", "SUSPENDED", "CLOSED"}


def _resolve_google_ads_selection(row: Dict[str, Any], customer_id: str) -> Dict[str, Any]:
    """
    Resolve a seleção SÓ pela listagem desta conexão (cache em metadata): é de
    lá que saem o login-customer-id (acesso via MCC), o nome e o tipo da conta.
    O login_customer_id enviado pelo navegador nunca é usado.
    """
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    cache = metadata.get("google_ads_accounts_cache")
    if not isinstance(cache, list) or not cache:
        raise IntegrationError(
            "Atualize a lista de contas Google Ads antes de selecionar a conta.",
            status_code=409, code="GOOGLE_ADS_ACCOUNTS_NOT_LISTED", provider="google_ads",
        )
    listed = next(
        (
            item for item in cache
            if isinstance(item, dict) and normalize_google_ads_customer_id(item.get("customer_id")) == customer_id
        ),
        None,
    )
    if listed is None:
        raise IntegrationError(
            "Esta conta não está na lista de contas Google Ads desta autorização. Atualize a lista e selecione novamente.",
            status_code=409, code="GOOGLE_ADS_ACCOUNT_NOT_LISTED", provider="google_ads",
        )
    if listed.get("is_manager"):
        raise IntegrationError(
            "Conta administradora (MCC) não possui campanhas próprias. Selecione uma conta de anúncios.",
            status_code=400, code="GOOGLE_ADS_MANAGER_ACCOUNT_NOT_SUPPORTED", provider="google_ads",
        )
    status = str(listed.get("status") or "").strip().upper()
    if (listed.get("details_error") or listed.get("lookup_error")) == "CUSTOMER_NOT_ENABLED" or status in _GOOGLE_ADS_NOT_ENABLED_STATUSES:
        raise IntegrationError(
            "A conta Google Ads selecionada não está ativa (cancelada, suspensa ou não configurada).",
            status_code=409, code="GOOGLE_ADS_CUSTOMER_NOT_ENABLED", provider="google_ads",
        )
    return {
        "login_customer_id": normalize_google_ads_customer_id(listed.get("login_customer_id")),
        "customer_name": str(listed.get("descriptive_name") or "").strip() or None,
        "source": "accounts_cache",
    }

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
    request: Request = None,
    days: int = Query(default=30, ge=1, le=366),
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_role(client_id or x_client_id, authorization)
    row = await get_connection(cid, connection_id)
    provider = str(row.get("provider") or "").strip()
    if provider == "google_ads":
        from services.google_ads import sync_google_ads

        return await sync_google_ads(
            client_id=cid, connection_id=connection_id, start=None, end=None, days=days,
            job_name="google_ads_sync_manual", trigger_source="manual_oauth_connection",
        )
    if not google_capabilities(row)["ga4_authorized"]:
        raise IntegrationError(
            "A conexão selecionada não possui autorização válida para o Analytics.",
            status_code=403,
            code="GOOGLE_SCOPE_INSUFFICIENT",
            provider="google",
        )
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    property_id = str(metadata.get("ga4_property_id") or "")
    request_id = str(getattr(getattr(request, "state", None), "request_id", "") or "-")
    print(
        "[google_sync][temporary_diagnostic] "
        f"request_id={request_id} connection_id={connection_id} client_id={cid} "
        f"property_id={property_id or '-'} stream_id={str(metadata.get('ga4_stream_id') or '-') } "
        f"customer_id={str(metadata.get('google_ads_customer_id') or '-')} "
        f"login_customer_id={str(metadata.get('google_ads_login_customer_id') or '-')} "
        f"developer_token_present={'yes' if os.getenv('GOOGLE_ADS_DEVELOPER_TOKEN') else 'no'} "
        f"days={days}"
    )
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
    return {"ok": True, "ga4": payload}
