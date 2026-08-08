from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, Optional

from .ig_supabase import sb_rpc, sb_select
from .integration_errors import IntegrationError


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


@asynccontextmanager
async def guarded_sync(
    *, client_id: str, provider: str, connection_id: str,
    period_start: str = "", period_end: str = "", ttl_seconds: int = 1800,
) -> AsyncIterator[str]:
    lock_name = build_sync_lock_name(provider, connection_id, period_start, period_end)
    if not await acquire_sync_lock(client_id, lock_name, ttl_seconds):
        raise IntegrationError(
            "Já existe uma sincronização equivalente em andamento.",
            status_code=409, code="SYNC_ALREADY_RUNNING", provider=provider, retryable=True,
        )
    try:
        yield lock_name
    finally:
        await release_sync_lock(client_id, lock_name)
