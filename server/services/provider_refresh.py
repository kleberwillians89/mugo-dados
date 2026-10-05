"""Refresh de dados por membership; nenhuma configuração vem do browser."""
from __future__ import annotations

import asyncio
import os
from typing import Literal

from fastapi import HTTPException

from .integration_errors import IntegrationError
from .connection_resolver import resolve_connection_for_scope, resolve_generic_connection
from .fbits_connections import sync_fbits_connection
from .fbits_official_kpis import invalidate_official_kpis
from .ga4_connections import resolve_ga4_connection_context
from .ga4_sync import sync_ga4_for_period
from .generic_connections import list_generic_connections
from .google_ads import resolve_google_ads_context, sync_google_ads
from .google_oauth import get_google_access_token
from .instagram_sync import sync_instagram_for_client
from .ads_sync import sync_ads_for_client_period
from .shopify_oauth import resolve_shopify_reconciliation_since, sync_shopify_connection
from .sync_locks import acquire_sync_lock, guarded_sync
from .runtime_cache import invalidate_namespace

RefreshProvider = Literal["fbits", "shopify", "meta", "google"]


async def _refresh_ga4(client_id: str, start: str, end: str) -> dict:
    context = await resolve_ga4_connection_context(client_id)
    token = await get_google_access_token(client_id, context.connection_id)
    return await sync_ga4_for_period(
        client_id=client_id, connection_id=context.connection_id,
        property_id=context.property_id, access_token=token,
        since=start, until=end, days=30, job_name="ga4_sync_manual",
        trigger_source="manual_api", record_job_run=True,
    )


async def _refresh_google_ads(client_id: str, start: str, end: str) -> dict:
    context = await resolve_google_ads_context(client_id)
    return await sync_google_ads(
        client_id=client_id, connection_id=context.connection_id,
        start=start, end=end, days=30,
    )


async def refresh_provider_data(client_id: str, provider: RefreshProvider, start: str, end: str) -> dict:
    if provider in {"fbits", "meta"}:
        print(f"[{provider}][manual_refresh_start] pid={os.getpid()} client_id={client_id} start={start} end={end}")
    # Lease compartilhada entre processos. O cooldown NÃO é liberado no fim:
    # expira naturalmente, inclusive quando a tentativa falha.
    async with guarded_sync(client_id=client_id, provider="data_refresh", connection_id=provider):
        if not await acquire_sync_lock(client_id, f"refresh_cooldown:{provider}", 60):
            if provider in {"fbits", "meta"}:
                print(f"[{provider}][manual_refresh_cooldown] retry_after=60")
            raise HTTPException(429, "Aguarde um minuto para atualizar novamente.", headers={"Retry-After": "60"})
        tasks = []
        if provider in {"fbits", "shopify"}:
            rows = await list_generic_connections(client_id)
            active = {row["provider"] for row in rows if row.get("provider") in {"fbits", "shopify"} and row.get("status") != "disconnected" and not row.get("disconnected_at")}
            if provider not in active:
                raise HTTPException(409, "O provider não está ativo nesta empresa.")
            # Havendo duas plataformas, a aba escolhe somente o provider; todos
            # os IDs e credenciais continuam resolvidos no servidor.
            if provider == "fbits":
                await sync_fbits_connection(client_id=client_id)
                await invalidate_official_kpis(client_id)
                print(f"[fbits][cache_invalidated] client_id={client_id}")
            else:
                row = await resolve_generic_connection(client_id=client_id, provider="shopify", prefer_metadata_flag="selected_for_reporting", require_token=False)
                since = await resolve_shopify_reconciliation_since(client_id, row["id"], fallback_days=60)
                await sync_shopify_connection(client_id=client_id, connection_id=row["id"], updated_at_min=since)
        elif provider == "meta":
            organic = await resolve_connection_for_scope(client_id=client_id, platform="instagram", connection_type="organic")
            paid = await resolve_connection_for_scope(client_id=client_id, platform="meta_ads", connection_type="paid", require_ad_account=True)
            if organic["connection_id"] and not str((organic.get("row") or {}).get("ig_user_id") or "").strip():
                raise HTTPException(409, "Selecione a conta Instagram antes de atualizar os dados.")
            if organic["connection_id"]:
                tasks.append(sync_instagram_for_client(client_id, limit=200, preferred_connection_id=organic["connection_id"], persisted_only=True))
            if paid["connection_id"]:
                tasks.append(sync_ads_for_client_period(client_id=client_id, connection_id=paid["connection_id"], since=start, until=end, persisted_only=True))
        elif provider == "google":
            rows = await list_generic_connections(client_id)
            providers = {row["provider"] for row in rows if row.get("status") != "disconnected" and not row.get("disconnected_at")}
            # Cada fonte resolve sua conexão dentro da tarefa: falha de
            # autorização/token de uma não impede a outra de sincronizar.
            if "ga4" in providers:
                tasks.append(_refresh_ga4(client_id, start, end))
            if "google_ads" in providers:
                tasks.append(_refresh_google_ads(client_id, start, end))
        else:
            raise HTTPException(400, "Provider não permitido.")
        if provider in {"meta", "google"}:
            if not tasks:
                raise HTTPException(409, "Nenhuma fonte configurada para atualização.")
            results = await asyncio.gather(*tasks, return_exceptions=True)
            if provider == "meta":
                for result in results:
                    seconds = None
                    if isinstance(result, IntegrationError) and result.status_code == 429:
                        seconds = max(1, int(result.diagnostics.get("retry_after") or 60))
                    elif isinstance(result, dict) and result.get("skipped") and result.get("reason") == "duplicate":
                        seconds = max(1, int(result.get("retry_after") or 300))
                    if seconds:
                        print(f"[meta][manual_refresh_cooldown] client_id={client_id} retry_after={seconds}")
                        raise HTTPException(429, "Aguarde antes de atualizar novamente.", headers={"Retry-After": str(seconds)})
            # Nunca devolver payloads dos providers ou texto de exceções cruas.
            if any(isinstance(result, BaseException) or (isinstance(result, dict) and (result.get("ok") is False or result.get("partial") is True or result.get("sync_outcome") == "partial" or result.get("read_model_refreshed") is False)) for result in results):
                if provider == "meta":
                    print(f"[meta][manual_refresh_error] client_id={client_id} stage=sync_or_projection status=502")
                raise HTTPException(502, "Uma fonte não pôde ser atualizada. Mantendo a última leitura disponível.")
        await invalidate_namespace("integration_connections")
        await invalidate_namespace("client_integrations")
        if provider in {"fbits", "meta"}:
            print(f"[{provider}][manual_refresh_done] client_id={client_id} status=success")
        return {"ok": True, "client_id": client_id, "provider": provider}
