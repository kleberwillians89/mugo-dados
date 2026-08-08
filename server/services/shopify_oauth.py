from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from urllib.parse import urlencode, urlsplit

import httpx

from .generic_connections import (
    audit_connection,
    get_connection,
    upsert_connection,
)
from .connection_resolver import resolve_generic_connection
from .ig_supabase import sb_insert, sb_select, sb_update
from .integration_errors import IntegrationError, from_httpx_error
from .job_runs import finish_job_run, start_job_run
from .oauth_state import create_oauth_state
from .shopify_config import shopify_admin_url
from .sync_locks import build_sync_lock_name, guarded_sync, is_sync_lock_stale, peek_sync_lock

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
    """Normaliza para exatamente "nomedaloja.myshopify.com", uma única vez.

    Aceita "amalie-6421", "amalie-6421.myshopify.com" ou
    "https://amalie-6421.myshopify.com" (inclusive com esquema duplicado,
    ex.: "https://https://..."). Nunca produz um sufixo duplicado
    (".myshopify.com.myshopify.com") — só concatena o sufixo quando ainda
    não está presente.
    """
    domain = str(value or "").strip().lower()
    while True:
        stripped = re.sub(r"^[a-z][a-z0-9+.-]*://", "", domain)
        if stripped == domain:
            break
        domain = stripped
    # Só remove barras/pontos FINAIS (ex.: copiar a URL com "/" sobrando no
    # fim) — um path real ("/algo") nunca é descartado silenciosamente,
    # cai na validação abaixo e é rejeitado.
    domain = domain.rstrip("/").strip(".")
    has_stray_chars = any(char in domain for char in ("/", "?", "#", ":"))
    if domain and not has_stray_chars and not domain.endswith(".myshopify.com"):
        domain = f"{domain}.myshopify.com"
    if not domain or has_stray_chars or not SHOP_DOMAIN_RE.fullmatch(domain):
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


async def resolve_shopify_connection_context(
    client_id: str,
    *,
    connection_id: str | None = None,
    required_scopes: tuple[str, ...] = (),
) -> ShopifyConnectionContext:
    cid = str(client_id or "").strip()
    requested_connection_id = str(connection_id or "").strip()
    try:
        explicit_rows = None
        if requested_connection_id:
            try:
                explicit_rows = [await get_connection(cid, requested_connection_id, include_token=True)]
            except Exception as exc:
                raise IntegrationError(
                    "Conexão Shopify não encontrada para a empresa selecionada.", status_code=404,
                    code="SHOPIFY_CONNECTION_NOT_FOUND", provider="shopify",
                ) from exc
        row = await resolve_generic_connection(
            client_id=cid,
            provider="shopify",
            requested_connection_id=requested_connection_id or None,
            prefer_metadata_flag="selected_for_reporting",
            require_token=False,
            select_fn=sb_select,
            candidate_rows=explicit_rows,
        )
    except IntegrationError as exc:
        if exc.code == "CONNECTION_TENANT_MISMATCH" and requested_connection_id:
            raise IntegrationError(
                "Conexão Shopify não encontrada para a empresa selecionada.", status_code=404,
                code="SHOPIFY_CONNECTION_NOT_FOUND", provider="shopify",
            ) from exc
        if exc.code == "CONNECTION_NOT_FOUND":
            row = None
        elif exc.code == "CONNECTION_AMBIGUOUS":
            raise IntegrationError(
                "Selecione qual loja Shopify deve alimentar os relatórios.",
                status_code=409, code="SHOPIFY_STORE_SELECTION_REQUIRED", provider="shopify",
            ) from exc
        elif exc.code in {"CONNECTION_TOKEN_UNAVAILABLE", "CONNECTION_DISCONNECTED"}:
            raise IntegrationError(
                "A conexão Shopify requer nova autorização.", status_code=401,
                code="SHOPIFY_REAUTH_REQUIRED", provider="shopify",
            ) from exc
        else:
            raise

    if not row:
        raise IntegrationError(
            "Nenhuma conexão Shopify ativa foi encontrada para a empresa selecionada.",
            status_code=404,
            code="SHOPIFY_CONNECTION_NOT_FOUND",
            provider="shopify",
        )

    if not row.get("_token"):
        try:
            row = await get_connection(cid, str(row.get("id") or ""), include_token=True)
        except Exception as exc:
            raise IntegrationError(
                "A conexão Shopify requer nova autorização.", status_code=401,
                code="SHOPIFY_REAUTH_REQUIRED", provider="shopify",
            ) from exc

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
    # Authorization Code Grant: SEMPRE o endpoint raiz da loja, nunca um
    # recurso da Admin API versionada (nunca /admin/api/{version}/oauth/...).
    shop = normalize_shop_domain(shop_domain)
    path = "/admin/oauth/access_token"
    config = settings()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"https://{shop}{path}",
                json={"client_id": config["client_id"], "client_secret": config["client_secret"], "code": code},
            )
            response.raise_for_status()
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        # Nunca logar query string, code ou secret — só loja, caminho e status.
        print(f"[shopify_oauth] stage=token_exchange shop={shop} path={path} status={status if status is not None else 'network_error'}")
        raise from_httpx_error(
            "shopify", exc, operation="trocar o código de autorização por um token de acesso",
        ) from exc
    print(f"[shopify_oauth] stage=token_exchange shop={shop} path={path} status={response.status_code}")
    payload = response.json()
    if not payload.get("access_token"):
        raise RuntimeError("Shopify não retornou token offline.")
    return payload


async def fetch_shop(shop_domain: str, access_token: str) -> Dict[str, Any]:
    shop = normalize_shop_domain(shop_domain)
    path = shopify_admin_url(shop, "shop.json")
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(
                path,
                headers={"X-Shopify-Access-Token": access_token},
            )
            response.raise_for_status()
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            print(f"[shopify_oauth] stage=shop_fetch shop={shop} status={status if status is not None else 'network_error'}")
            raise from_httpx_error(
                "shopify",
                exc,
                operation="consultar a loja",
            ) from exc
    print(f"[shopify_oauth] stage=shop_fetch shop={shop} status={response.status_code}")
    return response.json().get("shop") or {}


async def register_webhooks(shop_domain: str, access_token: str) -> Dict[str, Any]:
    """Registra cada tópico de forma independente — um tópico que falhe (ex.:
    um tópico de compliance que a Shopify exige configurar via Partner
    Dashboard em vez da API) nunca pode impedir o registro dos demais, nem
    (na chamada feita pelo callback) impedir que a conexão OAuth já
    persistida permaneça válida. Retorna um resumo seguro (sem token/secret)
    para diagnóstico: registered/skipped/failed por tópico.
    """
    shop = normalize_shop_domain(shop_domain)
    callback = _env("SHOPIFY_WEBHOOK_URL")
    if not callback.startswith("https://"):
        raise RuntimeError("SHOPIFY_WEBHOOK_URL HTTPS não configurada.")
    registered: list[str] = []
    skipped: list[str] = []
    failed: list[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for topic in SHOPIFY_WEBHOOK_TOPICS:
            try:
                response = await client.post(
                    shopify_admin_url(shop, "webhooks.json"),
                    headers={"X-Shopify-Access-Token": access_token},
                    json={"webhook": {"topic": topic, "address": callback, "format": "json"}},
                )
                if response.status_code == 422 and "already" in response.text.lower():
                    skipped.append(topic)
                    continue
                response.raise_for_status()
                registered.append(topic)
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                failed.append({"topic": topic, "status": status if status is not None else "network_error"})
    print(
        "[shopify_oauth] stage=webhook_registration "
        f"shop={shop} registered={len(registered)} skipped={len(skipped)} "
        f"failed={[(item['topic'], item['status']) for item in failed]}"
    )
    return {"registered": registered, "skipped": skipped, "failed": failed}


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


async def _check_shopify_scopes(context: "ShopifyConnectionContext") -> Dict[str, bool]:
    """Consulta os escopos REALMENTE concedidos à instalação via GraphQL
    Admin (currentAppInstallation.accessScopes) — nunca confia apenas na
    lista de scopes persistida no momento do OAuth, que pode ter ficado
    desatualizada em relação ao que a Shopify concede de fato hoje.
    """
    query = "{ currentAppInstallation { accessScopes { handle } } }"
    handles: set[str] = set()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                shopify_admin_url(context.shop_domain, "graphql.json"),
                headers={
                    "X-Shopify-Access-Token": context.access_token,
                    "Content-Type": "application/json",
                },
                json={"query": query},
            )
            response.raise_for_status()
        body = response.json()
        scopes_data = (((body or {}).get("data") or {}).get("currentAppInstallation") or {}).get("accessScopes")
        handles = {
            str(item.get("handle") or "").strip()
            for item in (scopes_data or [])
            if isinstance(item, dict) and item.get("handle")
        }
    except Exception as exc:
        print(
            "[shopify_sync] stage=scope_check "
            f"shop={context.shop_domain} status=check_failed error_type={exc.__class__.__name__}"
        )
        # Sem confirmar os scopes reais (falha de rede/GraphQL), cai para o
        # que já está persistido em vez de bloquear o backfill por uma
        # instabilidade transitória.
        handles = set(context.scopes)

    result = {
        "read_orders": "read_orders" in handles,
        "read_customers": "read_customers" in handles,
        "read_products": "read_products" in handles,
    }
    print(
        "[shopify_sync] stage=scope_check "
        f"shop={context.shop_domain} "
        f"read_orders={str(result['read_orders']).lower()} "
        f"read_customers={str(result['read_customers']).lower()} "
        f"read_products={str(result['read_products']).lower()}"
    )
    return result


async def _mark_shopify_sync_failed(*, client_id: str, connection_id: str, error_message: str) -> None:
    """Best-effort: grava last_error na conexão sem alterar status/derrubar
    a conexão — uma falha de sync nunca pode parecer "desconectado"."""
    if not connection_id:
        return
    try:
        await sb_update(
            "integration_connections",
            filters={"id": f"eq.{connection_id}", "client_id": f"eq.{client_id}"},
            patch={"last_error": error_message[:1000], "updated_at": datetime.now(timezone.utc).isoformat()},
            returning="minimal",
        )
    except Exception:
        pass


async def _safe_finish_job_run(job_run: Dict[str, Any] | None, **kwargs: Any) -> None:
    """finish_job_run é só observabilidade — nunca pode derrubar o resultado
    real do sync (nem quando o próprio job_run nunca chegou a ser criado)."""
    if not job_run or not job_run.get("id"):
        return
    try:
        await finish_job_run(job_run["id"], **kwargs)
    except Exception as exc:
        print(f"[shopify_sync] stage=job_finish_warning error_type={exc.__class__.__name__}")


async def sync_shopify_connection(
    *,
    client_id: str,
    connection_id: str,
    created_at_min: str | None = None,
) -> Dict[str, Any]:
    sync_started_at = time.perf_counter()
    print(f"[shopify_sync] stage=entry connection_id={connection_id} client_id={client_id}")
    # Sem lock, dois cliques (ou um clique coincidindo com uma chamada
    # automática) disparavam duas sincronizações Shopify em paralelo para a
    # mesma loja — chamadas duplicadas à API do Shopify e escritas
    # concorrentes de last_sync_at. Mesmo padrão de guarded_sync já usado em
    # Meta Ads/Instagram/GA4. A lock em si já é uma LEASE com TTL
    # (public.acquire_client_job_lock / cron_locks.locked_until) — um
    # processo morto/reiniciado nunca trava o próximo sync além do TTL,
    # porque a função SQL reclama automaticamente locks expirados. O peek
    # abaixo é só para log (nunca decide acquire/reject).
    lock_name = build_sync_lock_name("shopify", connection_id)
    existing_lock = await peek_sync_lock(client_id, lock_name)
    was_stale = is_sync_lock_stale(existing_lock)
    # TTL reduzido de 1800s para 900s agora que a persistência de clientes é
    # em lote (bem mais rápida) — janela de recuperação automática mais
    # curta em caso de crash/redeploy no meio de um sync.
    async with guarded_sync(
        client_id=client_id, provider="shopify", connection_id=connection_id,
        ttl_seconds=900,
    ):
        if was_stale and existing_lock:
            lock_age_seconds = None
            try:
                updated_at = datetime.fromisoformat(str(existing_lock.get("updated_at")).replace("Z", "+00:00"))
                lock_age_seconds = int((datetime.now(timezone.utc) - updated_at).total_seconds())
            except (ValueError, TypeError):
                lock_age_seconds = None
            print(
                "[shopify_sync] stage=lock_reclaimed "
                f"connection_id={connection_id} client_id={client_id} "
                f"lock_age_seconds={lock_age_seconds if lock_age_seconds is not None else '-'} "
                f"previous_locked_until={existing_lock.get('locked_until')}"
            )
        else:
            print(f"[shopify_sync] stage=lock_acquired connection_id={connection_id} client_id={client_id}")
        # Preenchido incrementalmente conforme cada estágio avança — usado
        # no payload_json do job_run tanto no sucesso quanto na falha, para
        # que /api/shopify/debug/sync-diagnostics sempre reflita até onde a
        # sincronização chegou, mesmo quando ela não termina.
        diagnostics: Dict[str, Any] = {"created_at_min": created_at_min}
        job_run: Dict[str, Any] | None = None
        shop_domain = "-"
        try:
            context = await resolve_shopify_connection_context(
                client_id,
                connection_id=connection_id,
                required_scopes=("read_orders", "read_customers", "read_products"),
            )
            shop_domain = context.shop_domain
            print(
                "[shopify_sync] stage=context_resolved "
                f"connection_id={connection_id} client_id={client_id} shop_domain={shop_domain}"
            )

            # Criar o job_run é só observabilidade — uma falha aqui (schema
            # incompatível, Supabase indisponível, etc.) NUNCA pode impedir
            # o sync real de rodar. Antes, esta chamada ficava fora de
            # qualquer try/except: se ela lançasse, a exceção escapava do
            # bloco inteiro sem nunca alcançar o tratamento de erro abaixo,
            # sem gravar last_error e sem virar uma resposta HTTP tratada —
            # daí o 500 opaco com last_sync permanecendo null.
            try:
                job_run = await start_job_run(
                    job_name="shopify_sync",
                    client_id=client_id,
                    connection_id=connection_id,
                    trigger_source="sync",
                    payload_json={"created_at_min": created_at_min},
                )
                print(f"[shopify_sync] stage=job_started connection_id={connection_id} client_id={client_id}")
            except Exception as job_exc:
                job_run = None
                print(
                    "[shopify_sync] stage=job_started "
                    f"connection_id={connection_id} client_id={client_id} status=warning "
                    f"error_type={job_exc.__class__.__name__}"
                )

            scope_report = await _check_shopify_scopes(context)
            diagnostics["scope_check"] = scope_report
            if not scope_report["read_orders"]:
                # read_orders é obrigatório para pedidos — nunca seguir em
                # frente e deixar isso parecer "0 pedidos" comercial.
                raise IntegrationError(
                    "A conexão Shopify não possui a permissão read_orders concedida pela loja. "
                    "Reconecte a integração para autorizar novamente.",
                    status_code=403,
                    code="SHOPIFY_MISSING_READ_ORDERS_SCOPE",
                    provider="shopify",
                )

            order_params: Dict[str, Any] = {"status": "any", "limit": 250}
            if str(created_at_min or "").strip():
                order_params["created_at_min"] = str(created_at_min).strip()
            print(
                "[shopify_sync] stage=orders_request "
                f"connection_id={connection_id} client_id={client_id} shop_domain={shop_domain}"
            )
            orders = await _fetch_shopify_collection(context, "orders.json", params=order_params)
            diagnostics["orders_received"] = len(orders)
            print(
                "[shopify_sync] stage=orders_response "
                f"connection_id={connection_id} client_id={client_id} shop_domain={shop_domain} "
                f"orders_received={len(orders)}"
            )
            customers = await _fetch_shopify_collection(context, "customers.json", params={"limit": 250})
            products = await _fetch_shopify_collection(context, "products.json", params={"limit": 250})

            from .shopify_webhooks import _handle_order_topic, upsert_customers_batch

            # ORDERS primeiro: o painel não pode depender de centenas de
            # writes individuais de clientes só para os pedidos aparecerem.
            # Um único pedido com payload inesperado nunca derruba o lote
            # inteiro — cada pedido é persistido de forma isolada, com
            # contagem exata de recebidos/tentados/persistidos/falhos.
            orders_received = len(orders)
            orders_parsed = sum(1 for order in orders if order.get("id") is not None)
            orders_upsert_attempted = orders_parsed
            orders_upserted = 0
            orders_failed = 0
            items_received = sum(
                len(order.get("line_items")) if isinstance(order.get("line_items"), list) else 0
                for order in orders
            )
            items_upserted = 0
            # O backfill inicial não busca refunds.json (fora do escopo desta
            # correção — refunds chegam via webhook refunds/create); mantido
            # aqui apenas para os campos de log solicitados nunca faltarem.
            refunds_received = 0
            refunds_upserted = 0
            first_order_error: Dict[str, Any] | None = None
            for order in orders:
                if order.get("id") is None:
                    orders_failed += 1
                    continue
                try:
                    result = await _handle_order_topic(
                        client_id=client_id,
                        shop_domain=shop_domain,
                        payload=order,
                    )
                    items_upserted += int(result.get("items_upserted") or 0)
                    orders_upserted += 1
                except Exception as exc:
                    orders_failed += 1
                    db_status = getattr(getattr(exc, "response", None), "status_code", None)
                    db_message = ""
                    response_obj = getattr(exc, "response", None)
                    if response_obj is not None:
                        try:
                            db_message = str(response_obj.text or "")[:300]
                        except Exception:
                            db_message = ""
                    if first_order_error is None:
                        # Só a PRIMEIRA exceção de persistência é capturada
                        # em detalhe — o suficiente para diagnosticar a causa
                        # raiz sem inundar o log com N repetições do mesmo erro.
                        first_order_error = {
                            "error_type": exc.__class__.__name__,
                            "error_code": str(db_status) if db_status is not None else None,
                            "db_message": db_message or None,
                        }
                        print(
                            "[shopify_sync] stage=order_persistence_error "
                            f"connection_id={connection_id} client_id={client_id} "
                            f"error_type={first_order_error['error_type']} "
                            f"error_code={first_order_error['error_code'] or '-'} "
                            f"db_message={first_order_error['db_message'] or '-'}"
                        )
                    else:
                        print(
                            "[shopify_sync] stage=orders_persistence "
                            f"connection_id={connection_id} client_id={client_id} "
                            f"order_upsert_error error_type={exc.__class__.__name__}"
                        )
            print(
                "[shopify_sync] stage=orders_persistence "
                f"connection_id={connection_id} client_id={client_id} shop_domain={shop_domain} "
                f"orders_received={orders_received} orders_parsed={orders_parsed} "
                f"orders_upsert_attempted={orders_upsert_attempted} orders_upserted={orders_upserted} "
                f"orders_failed={orders_failed} "
                f"items_received={items_received} items_upserted={items_upserted} "
                f"refunds_received={refunds_received} refunds_upserted={refunds_upserted}"
            )
            diagnostics.update({
                "orders_received": orders_received,
                "orders_parsed": orders_parsed,
                "orders_upsert_attempted": orders_upsert_attempted,
                "orders_upserted": orders_upserted,
                "orders_failed": orders_failed,
                "items_received": items_received,
                "items_upserted": items_upserted,
                "refunds_received": refunds_received,
                "refunds_upserted": refunds_upserted,
                "first_order_error": first_order_error,
            })

            # CUSTOMERS em lote: antes eram centenas de upserts individuais
            # (um POST por cliente, o gargalo real observado em produção) —
            # agora poucas chamadas em chunks de 100, com fallback para
            # upsert individual só dentro do chunk que falhar.
            customers_received = len(customers)
            customer_batch_result = await upsert_customers_batch(
                client_id=client_id, shop_domain=shop_domain, payloads=customers, chunk_size=100,
            )
            customers_upserted = customer_batch_result["upserted"]
            customers_failed = customer_batch_result["failed"]
            print(
                "[shopify_sync] stage=customers_persistence "
                f"connection_id={connection_id} client_id={client_id} shop_domain={shop_domain} "
                f"customers_received={customers_received} customers_upserted={customers_upserted} "
                f"customers_failed={customers_failed}"
            )
            diagnostics.update({
                "customers_received": customers_received,
                "customers_upserted": customers_upserted,
                "customers_failed": customers_failed,
            })

            if orders_received > 0 and orders_upserted == 0:
                # A Shopify devolveu pedidos, mas NENHUM foi persistido —
                # nunca reportar isso como sucesso silencioso (o report
                # ficaria com orders=0 sem nenhum sinal de que algo falhou).
                raise IntegrationError(
                    f"{orders_received} pedidos recebidos da Shopify, mas nenhum pôde ser persistido.",
                    status_code=502,
                    code="SHOPIFY_ORDERS_PERSISTENCE_FAILED",
                    provider="shopify",
                )

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
            duration_ms = int((time.perf_counter() - sync_started_at) * 1000)
            diagnostics["duration_ms"] = duration_ms
            await _safe_finish_job_run(
                job_run,
                status="success",
                rows_upserted=orders_upserted + customers_upserted,
                client_id=client_id,
                connection_id=connection_id,
                payload_json=diagnostics,
            )
            print(
                "[shopify_sync] stage=complete "
                f"connection_id={connection_id} client_id={client_id} shop_domain={shop_domain} "
                f"status=success duration_ms={duration_ms}"
            )
            return {
                "ok": True,
                "client_id": client_id,
                "connection_id": context.connection_id,
                "shop_domain": shop_domain,
                "synced": {
                    "orders_received": orders_received,
                    "orders_upserted": orders_upserted,
                    "orders_failed": orders_failed,
                    "customers_received": customers_received,
                    "customers_upserted": customers_upserted,
                    "customers_failed": customers_failed,
                    "products_checked": len(products),
                    "items_received": items_received,
                    "items_upserted": items_upserted,
                    "refunds_received": refunds_received,
                    "refunds_upserted": refunds_upserted,
                    # Compat: alguns chamadores ainda leem estas chaves.
                    "orders": orders_upserted,
                    "customers": customers_upserted,
                    "order_items": items_upserted,
                    "refunds": refunds_upserted,
                },
            }
        except IntegrationError as exc:
            # Erro operacional já conhecido/humanizado (scope ausente,
            # Shopify recusou a chamada, etc.) — a causa real já está no
            # próprio erro; só precisamos registrar e devolvê-lo como está.
            error_message = exc.public_message or str(exc)
            duration_ms = int((time.perf_counter() - sync_started_at) * 1000)
            print(
                "[shopify_sync] stage=failed "
                f"connection_id={connection_id} client_id={client_id} status=error "
                f"error_type={exc.__class__.__name__} error_code={exc.code} "
                f"http_status={exc.status_code} duration_ms={duration_ms}"
            )
            diagnostics["error_type"] = exc.__class__.__name__
            diagnostics["error_code"] = exc.code
            diagnostics["http_status"] = exc.status_code
            diagnostics["duration_ms"] = duration_ms
            await _safe_finish_job_run(
                job_run, status="error", error=error_message,
                client_id=client_id, connection_id=connection_id, payload_json=diagnostics,
            )
            await _mark_shopify_sync_failed(client_id=client_id, connection_id=connection_id, error_message=error_message)
            raise
        except Exception as exc:
            # Qualquer outra falha (inclusive na própria instrumentação —
            # ex.: job_run/Supabase incompatível, erro de rede inesperado):
            # a causa real nunca pode se perder. Fica completa no log e em
            # last_error; a exceção devolvida ao chamador (rota HTTP) é
            # convertida para um IntegrationError seguro, para nunca deixar
            # escapar um 500 opaco sem mensagem.
            error_message = str(exc)
            http_status = getattr(getattr(exc, "response", None), "status_code", None) or getattr(exc, "status_code", None)
            duration_ms = int((time.perf_counter() - sync_started_at) * 1000)
            print(
                "[shopify_sync] stage=failed "
                f"connection_id={connection_id} client_id={client_id} status=error "
                f"error_type={exc.__class__.__name__} "
                f"http_status={http_status if http_status is not None else '-'} duration_ms={duration_ms}"
            )
            diagnostics["error_type"] = exc.__class__.__name__
            diagnostics["http_status"] = http_status
            diagnostics["duration_ms"] = duration_ms
            await _safe_finish_job_run(
                job_run, status="error", error=error_message,
                client_id=client_id, connection_id=connection_id, payload_json=diagnostics,
            )
            await _mark_shopify_sync_failed(client_id=client_id, connection_id=connection_id, error_message=error_message)
            raise IntegrationError(
                "Não foi possível concluir a sincronização da Shopify agora. "
                "Os últimos dados persistidos continuam disponíveis.",
                status_code=502,
                code="SHOPIFY_SYNC_UNEXPECTED_ERROR",
                provider="shopify",
            ) from exc


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


async def list_active_shopify_connections() -> list[Dict[str, Any]]:
    """Conexões Shopify conectadas de TODOS os clientes — alimenta o cron de
    reconciliação periódica. Webhooks continuam sendo a fonte em tempo real;
    isto é só um resync leve de segurança, nunca o mecanismo principal."""
    return await sb_select(
        "integration_connections",
        select="id,client_id,external_key,status,metadata,last_sync_at,disconnected_at",
        filters={"provider": "eq.shopify", "status": "eq.connected"},
        order="updated_at.asc",
        limit=200,
    )


async def resolve_shopify_reconciliation_since(
    client_id: str, connection_id: str, *, fallback_days: int = 30
) -> str:
    """Início da janela de reconciliação: 1h antes do último sync bem-sucedido
    (margem de segurança contra updates perdidos por atraso de webhook), ou
    os últimos `fallback_days` dias quando ainda não houve sync registrado.
    """
    last_sync_at: str | None = None
    try:
        existing = await get_connection(client_id, connection_id)
        last_sync_at = str(existing.get("last_sync_at") or "").strip() or None
    except Exception:
        last_sync_at = None
    if last_sync_at:
        try:
            since = datetime.fromisoformat(last_sync_at.replace("Z", "+00:00")) - timedelta(hours=1)
            return since.isoformat()
        except ValueError:
            pass
    return (datetime.now(timezone.utc) - timedelta(days=fallback_days)).isoformat()


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
