from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Dict, Optional

from .ig_supabase import sb_rpc, sb_select, sb_update
from .integration_errors import IntegrationError
from .memory_budget import operation_memory


def build_sync_lock_name(
    provider: str,
    connection_id: str,
    period_start: str = "",
    period_end: str = "",
) -> str:
    parts = ["sync", str(provider).strip(), str(connection_id).strip()]
    if str(period_start).strip() or str(period_end).strip():
        parts.extend([str(period_start).strip() or "-", str(period_end).strip() or "-"])
    return ":".join(parts)


async def peek_sync_lock(client_id: str, lock_name: str) -> Optional[Dict[str, Any]]:
    """Leitura read-only do lock — nunca decide acquire/reject (isso
    continua 100% na função SQL acquire_client_job_lock, já baseada em
    TTL/lease e compartilhada com Meta/GA4/Instagram). Usada só para logar
    reclaim de lock expirado (lock_age_seconds) sem tocar no schema."""
    rows = await sb_select(
        "cron_locks",
        select="locked_until,updated_at",
        filters={"client_id": f"eq.{client_id}", "job_name": f"eq.{lock_name}"},
        limit=1,
    )
    return rows[0] if rows else None


def is_sync_lock_stale(lock_row: Optional[Dict[str, Any]]) -> bool:
    if not lock_row:
        return False
    locked_until = str(lock_row.get("locked_until") or "")
    try:
        expires_at = datetime.fromisoformat(locked_until.replace("Z", "+00:00"))
    except ValueError:
        return False
    return expires_at < datetime.now(timezone.utc)


async def acquire_sync_lock(client_id: str, lock_name: str, ttl_seconds: int) -> bool:
    return bool(await sb_rpc("acquire_client_job_lock", {
        "p_client_id": str(client_id).strip(),
        "p_job_name": str(lock_name).strip(),
        "p_ttl_seconds": max(30, int(ttl_seconds)),
    }))


async def release_sync_lock(client_id: str, lock_name: str) -> None:
    await sb_rpc("release_client_job_lock", {
        "p_client_id": str(client_id).strip(),
        "p_job_name": str(lock_name).strip(),
    })


# Lease curta renovada enquanto o sync roda. Antes: 30 min fixos — se o
# processo morresse no meio (deploy, reinício, falta de memória no plano free),
# a tela ficava "atualizando" e o botão travado por até 30 min sem nada rodando.
# Agora, sem renovação, a trava expira sozinha em até LEASE_SECONDS.
LEASE_SECONDS = 90
HEARTBEAT_SECONDS = 30


async def _renew_lease(client_id: str, lock_name: str, token: str) -> Optional[str]:
    """Estende a trava só se ainda for nossa (mesmo updated_at). Devolve o novo token."""
    until = (datetime.now(timezone.utc) + timedelta(seconds=LEASE_SECONDS)).isoformat()
    rows = await sb_update(
        "cron_locks",
        filters={"client_id": f"eq.{client_id}", "job_name": f"eq.{lock_name}", "updated_at": f"eq.{token}"},
        patch={"locked_until": until},
    )
    if not rows:
        return None
    return str(rows[0].get("updated_at") or token)


async def _heartbeat(client_id: str, lock_name: str) -> None:
    try:
        row = await peek_sync_lock(client_id, lock_name)
        token = str((row or {}).get("updated_at") or "")
        while token:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            try:
                renewed = await _renew_lease(client_id, lock_name, token)
            except Exception as exc:  # noqa: BLE001 — tenta de novo na próxima batida
                print(f"[sync_lock][heartbeat] lock={lock_name} status=retry error={exc.__class__.__name__}")
                continue
            if renewed is None:
                print(f"[sync_lock][heartbeat] lock={lock_name} status=lost")
                return
            token = renewed
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"[sync_lock][heartbeat] lock={lock_name} status=stopped error={exc.__class__.__name__}")


@asynccontextmanager
async def guarded_sync(
    *, client_id: str, provider: str, connection_id: str,
    period_start: str = "", period_end: str = "", ttl_seconds: int = 1800,
) -> AsyncIterator[str]:
    # ttl_seconds fica por compatibilidade; a trava real é a lease renovada.
    lock_name = build_sync_lock_name(provider, connection_id, period_start, period_end)
    if not await acquire_sync_lock(client_id, lock_name, min(LEASE_SECONDS, max(30, int(ttl_seconds)))):
        raise IntegrationError(
            "Já existe uma sincronização equivalente em andamento.",
            status_code=409, code="SYNC_ALREADY_RUNNING", provider=provider, retryable=True,
        )
    beat = asyncio.create_task(_heartbeat(client_id, lock_name))
    try:
        # Orchestrators call the concrete syncs below; do not reserve twice.
        if provider in {"data_refresh", "provider_history"}:
            yield lock_name
        else:
            async with operation_memory(provider, limit=True):
                yield lock_name
    finally:
        beat.cancel()
        try:
            await beat
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        await release_sync_lock(client_id, lock_name)
