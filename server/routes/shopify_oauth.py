from __future__ import annotations

import os
from typing import Dict
from urllib.parse import parse_qs, urlencode, urlparse

from fastapi import APIRouter, BackgroundTasks, Header, Query, Request
from fastapi.responses import RedirectResponse

from services.generic_connections import disconnect_generic_connection, get_connection
from services.oauth_state import consume_oauth_state
from services.shopify_oauth import (
    authorization_url,
    exchange_code,
    fetch_shop,
    normalize_shop_domain,
    register_webhooks,
    reconcile_shopify_period,
    resolve_shopify_reconciliation_since,
    safe_oauth_configuration,
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


def _log_stage(
    stage: str,
    *,
    client_id: str = "",
    shop_domain: str = "",
    status: str = "",
    connection_id: str = "",
    error: Exception | None = None,
) -> None:
    # Nunca logar: authorization code, client secret, access token, HMAC,
    # JWT ou payload com PII — só identificadores e status.
    parts = [f"[shopify_oauth] stage={stage}"]
    if client_id:
        parts.append(f"client_id={client_id}")
    if shop_domain:
        parts.append(f"shop_domain={shop_domain}")
    if connection_id:
        parts.append(f"connection_id={connection_id}")
    parts.append(f"status={status or 'ok'}")
    if error is not None:
        http_status = getattr(getattr(error, "response", None), "status_code", None)
        if http_status is not None:
            parts.append(f"http_status={http_status}")
        parts.append(f"error_type={error.__class__.__name__}")
    print(" ".join(parts))


async def _run_initial_sync_isolated(*, client_id: str, connection_id: str, shop_domain: str) -> None:
    """Backfill em background: uma falha aqui nunca reabre/derruba a conexão
    já persistida — só fica registrada como aviso isolado no log."""
    try:
        await sync_shopify_connection(client_id=client_id, connection_id=connection_id)
        _log_stage("initial_sync", client_id=client_id, shop_domain=shop_domain, connection_id=connection_id, status="ok")
    except Exception as exc:
        _log_stage("initial_sync", client_id=client_id, shop_domain=shop_domain, connection_id=connection_id, status="error", error=exc)


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
    diagnostic = safe_oauth_configuration()
    authorization = await authorization_url(user_id=user_id, client_id=cid, shop_domain=domain)
    query = parse_qs(urlparse(authorization).query)
    print(
        "[shopify_oauth][start] "
        f"shop={domain} redirect_uri={diagnostic['redirect_uri']} "
        f"scopes={','.join(str(query.get('scope', [''])[0]).split(','))} "
        f"client_id_present={'yes' if query.get('client_id', [''])[0] else 'no'} "
        # Últimos 6 caracteres do client_id em uso — permite confirmar em
        # produção que o app CUSTOM ATUAL está configurado (nunca o app
        # público antigo) sem expor o valor inteiro nem o secret.
        f"client_id_hint={diagnostic['client_id_hint']} "
        f"state_present={'yes' if query.get('state', [''])[0] else 'no'}"
    )
    return {
        "ok": True,
        "client_id": cid,
        "shop_domain": domain,
        "authorization_url": authorization,
    }


@router.get("/callback")
async def callback(request: Request, background_tasks: BackgroundTasks):
    client_id = ""
    shop_domain = ""
    stage = "callback_received"
    try:
        params = {key: value for key, value in request.query_params.items()}
        _log_stage(stage, status="received")
        if not verify_callback_hmac(params):
            raise RuntimeError("HMAC do callback Shopify inválido.")
        code = str(params.get("code") or "")
        state = str(params.get("state") or "")
        shop_domain = normalize_shop_domain(str(params.get("shop") or ""))
        if not code or not state:
            raise RuntimeError("Callback Shopify sem code ou state.")

        stage = "state_validated"
        session = await consume_oauth_state(state, provider="shopify")
        configured_redirect = safe_oauth_configuration()["redirect_uri"]
        if str(session.get("redirect_uri") or "").strip() != configured_redirect:
            raise RuntimeError("A redirect_uri da sessão OAuth não corresponde à configuração Shopify ativa.")
        expected_shop = normalize_shop_domain(str((session.get("context") or {}).get("shop_domain") or ""))
        if shop_domain != expected_shop:
            raise RuntimeError("A loja retornada não corresponde à loja autorizada.")
        user_id = str(session.get("user_id") or "")
        client_id = str(session.get("client_id") or "")
        await require_user_client_access(user_id, client_id)
        _log_stage(stage, client_id=client_id, shop_domain=shop_domain, status="ok")

        # token_exchange e shop_fetch já logam seu próprio status/http_status
        # (server/services/shopify_oauth.py) — nunca code/secret/token.
        stage = "token_exchange"
        token = await exchange_code(shop_domain=shop_domain, code=code)
        stage = "shop_fetch"
        shop = await fetch_shop(shop_domain, str(token.get("access_token") or ""))

        # A partir daqui a autorização é válida e o token existe: a conexão é
        # persistida IMEDIATAMENTE. Webhook e backfill são etapas
        # subsequentes e best-effort — nunca podem impedir nem reverter uma
        # conexão OAuth já concluída (ver PRIORIDADE 1 do war room).
        stage = "connection_persist"
        connection = await save_shopify_connection(
            client_id=client_id, user_id=user_id, shop_domain=shop_domain, token=token, shop=shop
        )
        connection_id = str(connection.get("id") or "")
        _log_stage(stage, client_id=client_id, shop_domain=shop_domain, connection_id=connection_id, status="ok")

        stage = "webhook_registration"
        try:
            await register_webhooks(shop_domain, str(token.get("access_token") or ""))
        except Exception as webhook_exc:
            _log_stage(stage, client_id=client_id, shop_domain=shop_domain, connection_id=connection_id, status="error", error=webhook_exc)

        stage = "initial_sync"
        background_tasks.add_task(
            _run_initial_sync_isolated,
            client_id=client_id,
            connection_id=connection_id,
            shop_domain=shop_domain,
        )
        _log_stage(stage, client_id=client_id, shop_domain=shop_domain, connection_id=connection_id, status="scheduled")

        stage = "complete"
        _log_stage(stage, client_id=client_id, shop_domain=shop_domain, connection_id=connection_id, status="ok")
        return RedirectResponse(
            _frontend_redirect({"shopify_oauth": "success", "connection_id": connection_id}),
            status_code=302,
        )
    except Exception as exc:
        _log_stage(stage, client_id=client_id, shop_domain=shop_domain, status="error", error=exc)
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
    # Reconciliação leve: refresh manual busca só o que mudou desde a última
    # sincronização bem-sucedida (mesma janela usada pelo cron de
    # reconciliação periódica), em vez de refazer o histórico inteiro a cada
    # clique. Sem sync anterior, cai para a janela de `days`.
    updated_at_min = await resolve_shopify_reconciliation_since(cid, connection_id, fallback_days=days)
    return await sync_shopify_connection(
        client_id=cid,
        connection_id=connection_id,
        updated_at_min=updated_at_min,
    )


@router.post("/{connection_id}/reconcile")
async def reconcile_store_period(
    connection_id: str,
    start: str = Query(...),
    end: str = Query(...),
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_role(
        client_id or x_client_id,
        authorization,
        allowed_roles=("agency_admin", "client_admin"),
    )
    return await reconcile_shopify_period(
        client_id=cid, connection_id=connection_id, start=start, end=end,
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
