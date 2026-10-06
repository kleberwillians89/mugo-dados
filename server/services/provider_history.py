"""Operação histórica limitada: reutiliza fila Meta e syncs Google/GA4.

Nenhum discovery global, segredo vindo da CLI ou tabela nova.
"""
from __future__ import annotations

from datetime import date, datetime
import asyncio
from uuid import UUID
from typing import Any

from .connection_resolver import resolve_connection_for_scope
from .ga4_connections import resolve_ga4_connection_context
from .ga4_sync import sync_ga4_for_period
from .google_ads import resolve_google_ads_context, sync_google_ads
from .google_oauth import get_google_access_token
from .ig_supabase import sb_select, sb_upsert
from .ig_meta import fetch_media_list
from .instagram_sync import _normalize_meta_ts
from .meta_tokens import ensure_valid_meta_token
from .periods import local_date
from .job_runs import start_job_run, finish_job_run
from .meta_backfill import build_slices, enqueue_backfill
from .sync_locks import guarded_sync

SLICE_TIMEOUT_SECONDS = 240

PROVIDERS = {"meta_ads", "google_ads", "ga4", "instagram_content"}


def validate_history(client_id: str, provider: str, start_date: str, end_date: str) -> None:
    UUID(client_id)  # ID obrigatório; não existe modo global/default.
    if provider not in PROVIDERS:
        raise ValueError("Provider histórico não suportado; snapshots Instagram não são reconstruíveis.")
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    if not 1 <= (end - start).days + 1 <= 90:
        raise ValueError("O histórico deve abranger de 1 a 90 dias inclusivos.")


async def _instagram_content(client_id: str, context: dict, start: str, end: str) -> dict:
    connection_id = str(context["connection_id"])
    ig_user_id = str((context.get("row") or {}).get("ig_user_id") or "")
    if not ig_user_id:
        raise ValueError("Selecione a conta Instagram para esta empresa.")
    async with asyncio.timeout(1500), guarded_sync(client_id=client_id, provider="instagram", connection_id=connection_id):
        token = await ensure_valid_meta_token(client_id, connection_id=connection_id,
                                             platform="instagram", connection_type="organic", persisted_only=True)
        # Enumeração completa ANTES de persistir; lifetime insights não entram.
        media = await fetch_media_list(ig_user_id, token, limit=100, history=True)
        rows = []
        for item in {str(item["id"]): item for item in media if item.get("id")}.values():
            timestamp = _normalize_meta_ts(item.get("timestamp"))
            if not item.get("id") or not timestamp or item.get("media_product_type") == "STORY":
                continue
            day = local_date(datetime.fromisoformat(timestamp.replace("Z", "+00:00"))).isoformat()
            if start <= day <= end:
                rows.append({"client_id": client_id, "connection_id": connection_id,
                             "media_id": str(item["id"]), "timestamp": timestamp,
                             "media_type": item.get("media_type"), "media_product_type": item.get("media_product_type"),
                             "permalink": item.get("permalink")})
        for offset in range(0, len(rows), 500):
            # Colunas ausentes não substituem insights/snapshots válidos.
            await sb_upsert("ig_media", rows[offset:offset + 500], on_conflict="client_id,media_id")
        return {"ok": True, "client_id": client_id, "provider": "instagram_content",
                "start_date": start, "end_date": end, "rows_upserted": len(rows),
                "completeness": "unknown", "snapshot_backfill": False}


async def backfill_provider_history(*, client_id: str, provider: str, start_date: str,
                                    end_date: str, connection_id: str | None = None,
                                    resume: bool = False) -> dict[str, Any]:
    validate_history(client_id, provider, start_date, end_date)
    if provider == "instagram_content":
        context = await resolve_connection_for_scope(client_id=client_id, platform="instagram",
                    connection_type="organic", requested_connection_id=connection_id)
        if not context.get("connection_id"):
            raise ValueError("Nenhuma conexão Instagram selecionada para esta empresa.")
        return await _instagram_content(client_id, context, start_date, end_date)
    if provider == "meta_ads":
        context = await resolve_connection_for_scope(
            client_id=client_id, platform="meta_ads", connection_type="paid",
            requested_connection_id=connection_id, require_ad_account=True,
        )
        connection = str(context.get("connection_id") or "")
        if not connection:
            raise ValueError("Nenhuma conexão Meta Ads paga selecionada para esta empresa.")
        # A fila existente possui claim atômico, tentativas e reconciliation.
        result = await enqueue_backfill(client_id=client_id, connection_id=connection,
                                        since=start_date, until=end_date, created_by=None)
        if result.get("requested_since") != start_date or result.get("requested_until") != end_date:
            raise ValueError("Existe um backfill ativo de outra janela nesta conexão.")
        return {"ok": True, "provider": provider, "client_id": client_id,
                "start_date": start_date, "end_date": end_date,
                "backfill_job_id": result["backfill_job_id"], "status": result.get("status"),
                "total_slices": result.get("total_slices"), "queued": True}

    context = (await resolve_google_ads_context(client_id, connection_id) if provider == "google_ads"
               else await resolve_ga4_connection_context(client_id, connection_id))
    if context.client_id != client_id or not context.connection_id:
        raise ValueError("A conexão não pertence à empresa selecionada.")
    connection = context.connection_id
    resource = context.customer_id if provider == "google_ads" else context.property_id
    job_name = f"provider_history_{provider}"
    completed = skipped = rows = 0
    # Lock operacional separado; os syncs mantêm seus locks canônicos.
    async with asyncio.timeout(3300), guarded_sync(client_id=client_id, provider="provider_history", connection_id=connection,
                            ttl_seconds=3600):
        for part in build_slices(start_date, end_date):
            checkpoint = {"provider": provider, "resource_id": resource,
                          "start_date": part["since"], "end_date": part["until"]}
            if resume:
                existing = await sb_select("cron_job_runs", filters={
                    "client_id": f"eq.{client_id}", "connection_id": f"eq.{connection}",
                    "job_name": f"eq.{job_name}", "status": "eq.success",
                    "payload_json->>resource_id": f"eq.{resource}",
                    "payload_json->>start_date": f"eq.{part['since']}",
                    "payload_json->>end_date": f"eq.{part['until']}",
                    "payload_json->>collection_complete": "eq.true",
                }, limit=1)
                if existing:
                    skipped += 1
                    continue
            job = await start_job_run(job_name=job_name, client_id=client_id, connection_id=connection,
                                      trigger_source="manual_cli", payload_json=checkpoint)
            job_id = str((job or {}).get("id") or "")
            if not job_id:
                raise RuntimeError("Não foi possível registrar o checkpoint histórico.")
            try:
                async with asyncio.timeout(SLICE_TIMEOUT_SECONDS):
                    if provider == "google_ads":
                        result = await sync_google_ads(client_id=client_id, connection_id=connection,
                                                       start=part["since"], end=part["until"])
                    else:
                        token = await get_google_access_token(client_id, connection)
                        result = await sync_ga4_for_period(
                            client_id=client_id, connection_id=connection, property_id=resource,
                            access_token=token, since=part["since"], until=part["until"],
                        )
                if (result.get("ok") is not True or result.get("skipped")
                        or result.get("read_model_refreshed") is not True
                        or result.get("collection_complete") is not True):
                    raise RuntimeError("Ingestão/projeção histórica não concluída.")
                count = result.get("rows_upserted", 0)
                count = int(count.get("total", 0) if isinstance(count, dict) else count)
                await finish_job_run(job_id, client_id=client_id, connection_id=connection,
                                     status="success", rows_upserted=count,
                                     payload_json={**checkpoint, "collection_complete": True,
                                                   "projection_success_at": result.get("projection_success_at")})
                completed += 1
                rows += count
                print(f"[provider_history] provider={provider} client_id={client_id} start={part['since']} end={part['until']} status=success rows={count}")
            except (Exception, asyncio.CancelledError) as exc:
                # Exceções de provider podem carregar URL/token; só código operacional.
                await finish_job_run(job_id, client_id=client_id, connection_id=connection, status="error",
                                     error="PROVIDER_HISTORY_SLICE_FAILED", payload_json=checkpoint)
                print(f"[provider_history] provider={provider} client_id={client_id} start={part['since']} end={part['until']} status=error")
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise RuntimeError("O bloco histórico falhou; use --resume após resolver a falha.") from None
    return {"ok": True, "client_id": client_id, "provider": provider,
            "start_date": start_date, "end_date": end_date, "completed_slices": completed,
            "skipped_slices": skipped, "rows_upserted": rows}
