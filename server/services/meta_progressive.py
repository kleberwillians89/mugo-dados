"""Primeiro carregamento progressivo da Meta: primeiro o essencial, o resto em segundo plano.

Ao conectar, a requisição só espera o mínimo para a tela mostrar números:
- Instagram: perfil, KPIs e os posts mais recentes (QUICK_MEDIA), sem copiar miniaturas.
- Meta Ads: os últimos QUICK_DAYS dias.

Depois da resposta, no mesmo processo:
- Instagram: sync completo (40 posts, comentários, miniaturas).
- Meta Ads: 30 dias completos e a fila durável com o restante dos 90 dias.

Se o processo reiniciar no meio, nada se perde: os syncs recorrentes (organic-sync 4x/dia,
ads-sync-hourly) e a fila durável do Meta completam. Cada etapa usa os locks e registros de job
que já existem; o tenant é sempre o já validado pela rota.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, Awaitable, Callable, Dict, Set

QUICK_DAYS = 7
QUICK_MEDIA = 12
HISTORY_DAYS = 30
BACKFILL_DAYS = 90

_TASKS: Set[asyncio.Task] = set()


def schedule(name: str, client_id: str, factory: Callable[[], Awaitable[Any]]) -> None:
    """Roda depois da resposta. Falha fica no log (só tipo/código) e nunca chega ao usuário."""
    async def runner() -> None:
        print(f"[meta_progressive] stage=start job={name} client_id={client_id}")
        try:
            result = await factory()
            status = (result or {}).get("status") if isinstance(result, dict) else None
            print(f"[meta_progressive] stage=done job={name} client_id={client_id} status={status or 'ok'}")
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", "") or exc.__class__.__name__
            print(f"[meta_progressive] stage=error job={name} client_id={client_id} code={str(code)[:60]}")

    task = asyncio.ensure_future(runner())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


async def drain() -> None:
    """Espera o que foi agendado (testes)."""
    while _TASKS:
        await asyncio.gather(*list(_TASKS), return_exceptions=True)


async def organic_history(connection_id: str) -> Dict[str, Any]:
    from .instagram_sync import sync_instagram_connection
    return await sync_instagram_connection(connection_id)


async def paid_history(client_id: str, connection_id: str) -> Dict[str, Any]:
    """30 dias completos agora; o restante dos 90 dias entra na fila durável (worker a cada 5 min)."""
    from .ads_sync import sync_ads_for_client_period
    from .meta_backfill import enqueue_backfill
    from .periods import resolve_period

    p30 = resolve_period(days=HISTORY_DAYS, max_days=365)
    result = await sync_ads_for_client_period(
        client_id=client_id, connection_id=connection_id,
        since=p30.start.isoformat(), until=p30.end.isoformat(),
        job_name="meta_ads_history_30d", trigger_source="oauth_progressive", record_job_run=True,
    )
    p90 = resolve_period(days=BACKFILL_DAYS, max_days=365)
    try:
        queued = await enqueue_backfill(client_id=client_id, connection_id=connection_id,
                                        since=p90.start.isoformat(),
                                        until=(p30.start - timedelta(days=1)).isoformat(), created_by=None)
        result = {**(result or {}), "backfill_90d": queued.get("status")}
    except Exception as exc:  # noqa: BLE001 — fila ocupada/indisponível: o histórico de Empresas cobre depois
        result = {**(result or {}), "backfill_90d": f"skipped:{exc.__class__.__name__}"}
    return result


async def paid_first_read(client_id: str, connection_id: str, *, sync: Callable[..., Awaitable[Any]] | None = None) -> Dict[str, Any]:
    """Primeiros 7 dias na requisição (KPI) e, se a Meta respondeu, histórico em segundo plano.

    Falha aqui nunca desfaz a conexão: devolve o código para a tela e o sync de hora em hora tenta de novo.
    """
    from .ads_sync import sync_ads_for_client_period
    from .periods import resolve_period

    period = resolve_period(days=QUICK_DAYS, max_days=365)
    try:
        result = await (sync or sync_ads_for_client_period)(
            client_id=client_id, connection_id=connection_id,
            since=period.start.isoformat(), until=period.end.isoformat(),
            job_name="meta_ads_initial_sync", trigger_source="oauth_asset_selection", record_job_run=True,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "client_id": client_id, "connection_id": connection_id,
                "code": str(getattr(exc, "code", "META_ADS_INITIAL_SYNC_FAILED")),
                "retryable": bool(getattr(exc, "retryable", True))}
    schedule("meta_ads_history", client_id, lambda: paid_history(client_id, connection_id))
    return {**(result or {}), "ok": bool((result or {}).get("ok")), "client_id": client_id,
            "connection_id": connection_id, "days": QUICK_DAYS,
            "history_sync": {"status": "scheduled", "days": [HISTORY_DAYS, BACKFILL_DAYS]}}
