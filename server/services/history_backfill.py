"""Busca de histórico por empresa (ex.: desde 01/01/2026), em blocos e retomável.

Por que existe: cada integração trouxe só uma janela curta quando foi conectada
(FBITS, 90 dias). Esta operação baixa o passado UMA vez para o banco; depois
as telas, a Inteligência e o MCP leem só do banco.

Regras:
- Só preenche o passado que falta: o alvo de cada fonte é congelado no pedido
  (da data inicial até o dia anterior ao dado mais antigo já gravado).
- Reaproveita os syncs existentes (mesma normalização, mesma origem do pedido,
  upserts idempotentes). Nenhuma regra de receita muda; nada é apagado.
- Em blocos pequenos, um de cada vez, com pausa, dentro de um orçamento de
  tempo. Respeita os locks dos syncs recorrentes: se a fonte estiver
  sincronizando, o bloco fica para a próxima rodada.
- Retomável: cada bloco concluído vira um checkpoint em `cron_job_runs`.
- Sem segredo nem dado pessoal em log ou payload: só datas, contagens e códigos.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, time as dtime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from .ig_supabase import sb_select
from .job_runs import finish_job_run, start_job_run
from .sync_locks import guarded_sync

TZ = ZoneInfo("America/Sao_Paulo")
REQUEST_JOB = "history_backfill_request"
BLOCK_JOB = "history_backfill_block"
MAX_HISTORY_DAYS = 730
PAUSE_SECONDS = 2.0

# Ordem de execução: vendas primeiro (o que mais importa), mídia depois.
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "fbits": {"label": "FBITS/Wake · pedidos", "block_days": 7},
    "shopify": {"label": "Shopify · pedidos", "block_days": 30},
    "google_ads": {"label": "Google Ads", "block_days": 28},
    "ga4": {"label": "Google Analytics 4", "block_days": 28},
    # Cada bloco de até 90 dias é ENFILEIRADO na fila durável do Meta (worker
    # a cada 5 min, 7 dias por vez); "concluído" aqui = enviado à fila.
    "meta_ads": {"label": "Meta Ads", "block_days": 90},
}


class HistoryBackfillError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message


def _today() -> date:
    return datetime.now(TZ).date()


def validate_start(start: str, *, today: Optional[date] = None) -> date:
    try:
        value = date.fromisoformat(str(start or "").strip())
    except ValueError:
        raise HistoryBackfillError("Data inicial inválida. Use AAAA-MM-DD.", code="HISTORY_INVALID_START") from None
    today = today or _today()
    if value >= today:
        raise HistoryBackfillError("A data inicial precisa ser anterior a hoje.", code="HISTORY_INVALID_START")
    if (today - value).days > MAX_HISTORY_DAYS:
        raise HistoryBackfillError("O histórico pode voltar no máximo 2 anos.", code="HISTORY_TOO_OLD")
    return value


def build_blocks(start: date, end: date, block_days: int) -> List[Dict[str, str]]:
    if end < start:
        return []
    blocks: List[Dict[str, str]] = []
    cursor = start
    while cursor <= end:
        last = min(end, cursor + timedelta(days=block_days - 1))
        blocks.append({"start": cursor.isoformat(), "end": last.isoformat()})
        cursor = last + timedelta(days=1)
    return blocks


def _local_day(value: Any) -> Optional[date]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if len(raw) == 10:
            return date.fromisoformat(raw)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return (parsed.astimezone(TZ) if parsed.tzinfo else parsed).date()
    except ValueError:
        return None


async def _earliest(table: str, column: str, client_id: str) -> Optional[date]:
    rows = await sb_select(
        table, select=column,
        filters={"client_id": f"eq.{client_id}", column: "not.is.null"},
        order=f"{column}.asc", limit=1,
    )
    return _local_day(rows[0].get(column)) if rows else None


# ---------------------------------------------------------------------------
# Conexões (só leitura). Cada resolvedor devolve o id da conexão ou None.


async def _fbits_connection(client_id: str) -> Optional[str]:
    from .fbits_connections import load_fbits_connection

    row = await load_fbits_connection(client_id)
    if not row or row.get("disconnected_at") or str(row.get("status") or "").lower() in {"disconnected", "not_configured"}:
        return None
    return str(row.get("id") or "") or None


async def _shopify_connection(client_id: str) -> Optional[str]:
    rows = await sb_select(
        "integration_connections", select="id,client_id,status,disconnected_at",
        filters={"client_id": f"eq.{client_id}", "provider": "eq.shopify", "status": "eq.connected"},
        order="updated_at.desc", limit=1,
    )
    rows = [row for row in rows if str(row.get("client_id")) == client_id and not row.get("disconnected_at")]
    return str(rows[0]["id"]) if rows else None


async def _google_ads_connection(client_id: str) -> Optional[str]:
    from .google_ads import resolve_google_ads_context

    context = await resolve_google_ads_context(client_id, None)
    return context.connection_id if context.client_id == client_id and context.customer_id else None


async def _ga4_connection(client_id: str) -> Optional[str]:
    from .ga4_connections import resolve_ga4_connection_context

    context = await resolve_ga4_connection_context(client_id, None)
    return context.connection_id if context.client_id == client_id and context.property_id else None


async def _meta_connection(client_id: str) -> Optional[str]:
    from .connection_resolver import resolve_connection_for_scope

    context = await resolve_connection_for_scope(
        client_id=client_id, platform="meta_ads", connection_type="paid", require_ad_account=True,
    )
    return str(context.get("connection_id") or "") or None


CONNECTIONS: Dict[str, Callable[[str], Awaitable[Optional[str]]]] = {
    "fbits": _fbits_connection,
    "shopify": _shopify_connection,
    "google_ads": _google_ads_connection,
    "ga4": _ga4_connection,
    "meta_ads": _meta_connection,
}

EARLIEST: Dict[str, tuple[str, str]] = {
    "fbits": ("fbits_orders", "order_date"),
    "shopify": ("shopify_orders", "created_at_shopify"),
    "google_ads": ("google_ads_daily_stats", "stat_date"),
    "ga4": ("ga4_daily_stats", "stat_date"),
    "meta_ads": ("ad_account_daily_stats", "stat_date"),
}


async def _connection_or_none(provider: str, client_id: str) -> Optional[str]:
    try:
        return await CONNECTIONS[provider](client_id)
    except Exception:
        # Sem conexão, conexão ambígua ou incompleta: a fonte fica de fora,
        # nunca derruba o plano das outras.
        return None


# ---------------------------------------------------------------------------
# Pedido (congelado) e checkpoints


async def active_request(client_id: str) -> Optional[Dict[str, Any]]:
    rows = await sb_select(
        "cron_job_runs", select="id,client_id,started_at,status,payload_json",
        filters={"job_name": f"eq.{REQUEST_JOB}", "client_id": f"eq.{client_id}", "status": "eq.running"},
        order="started_at.desc", limit=1,
    )
    return rows[0] if rows else None


async def _done_blocks(client_id: str, request_id: str) -> Dict[str, set]:
    rows = await sb_select(
        "cron_job_runs", select="status,payload_json",
        filters={
            "job_name": f"eq.{BLOCK_JOB}", "client_id": f"eq.{client_id}", "status": "eq.success",
            "payload_json->>request_id": f"eq.{request_id}",
        },
        limit=5000,
    )
    done: Dict[str, set] = {}
    for row in rows:
        payload = row.get("payload_json") or {}
        done.setdefault(str(payload.get("provider")), set()).add((str(payload.get("start")), str(payload.get("end"))))
    return done


async def build_targets(client_id: str, start: date, *, today: Optional[date] = None) -> List[Dict[str, Any]]:
    """Para cada fonte: conectada?, dado mais antigo já gravado e o que falta."""
    yesterday = (today or _today()) - timedelta(days=1)
    targets: List[Dict[str, Any]] = []
    for provider, spec in PROVIDERS.items():
        connection_id = await _connection_or_none(provider, client_id)
        target: Dict[str, Any] = {"provider": provider, "label": spec["label"], "connected": bool(connection_id)}
        if connection_id:
            table, column = EARLIEST[provider]
            earliest = await _earliest(table, column, client_id)
            until = min(yesterday, earliest - timedelta(days=1)) if earliest else yesterday
            target.update({
                "earliest_in_database": earliest.isoformat() if earliest else None,
                "missing_start": start.isoformat() if until >= start else None,
                "missing_end": until.isoformat() if until >= start else None,
            })
        targets.append(target)
    return targets


async def history_plan(client_id: str, start: Optional[str] = None) -> Dict[str, Any]:
    """Somente leitura. Com pedido ativo, mostra o progresso; sem, simula."""
    request = await active_request(client_id)
    if request:
        payload = request.get("payload_json") or {}
        targets = list(payload.get("targets") or [])
        start_value = str(payload.get("start") or "")
        done = await _done_blocks(client_id, str(request["id"]))
    else:
        start_value = validate_start(start or "").isoformat()
        targets = await build_targets(client_id, date.fromisoformat(start_value))
        done = {}
    providers = []
    for target in targets:
        provider = target["provider"]
        blocks = (build_blocks(date.fromisoformat(target["missing_start"]), date.fromisoformat(target["missing_end"]),
                               PROVIDERS[provider]["block_days"]) if target.get("missing_start") else [])
        finished = len({(b["start"], b["end"]) for b in blocks} & done.get(provider, set()))
        if not target.get("connected"):
            state = "not_connected"
        elif not blocks or finished == len(blocks):
            state = "complete"
        else:
            state = "pending"
        providers.append({**target, "blocks_total": len(blocks), "blocks_done": finished, "state": state})
    return {
        "ok": True,
        "client_id": client_id,
        "start": start_value,
        "request": ({"id": request["id"], "requested_at": request.get("started_at")} if request else None),
        "providers": providers,
        "observacao": "Somente leitura. A busca só preenche o passado que falta; nada é apagado nem recalculado.",
    }


async def request_history(client_id: str, start: str, *, requested_by: str) -> Dict[str, Any]:
    if await active_request(client_id):
        raise HistoryBackfillError("Já existe uma busca de histórico em andamento para esta empresa.",
                                   code="HISTORY_ALREADY_REQUESTED")
    start_value = validate_start(start)
    targets = await build_targets(client_id, start_value)
    if not any(target.get("missing_start") for target in targets):
        raise HistoryBackfillError("Nada a buscar: o banco já tem os dados desde essa data.", code="HISTORY_NOTHING_TO_DO")
    row = await start_job_run(
        job_name=REQUEST_JOB, client_id=client_id, trigger_source="platform_admin",
        payload_json={"start": start_value.isoformat(), "targets": targets, "requested_by": requested_by},
    )
    if not (row or {}).get("id"):
        raise HistoryBackfillError("Não foi possível registrar o pedido.", code="HISTORY_REQUEST_FAILED")
    return await history_plan(client_id)


async def cancel_history(client_id: str) -> Dict[str, Any]:
    request = await active_request(client_id)
    if not request:
        raise HistoryBackfillError("Nenhuma busca em andamento para esta empresa.", code="HISTORY_NOT_FOUND")
    await finish_job_run(str(request["id"]), status="skipped", client_id=client_id,
                         payload_json={**(request.get("payload_json") or {}), "cancelled": True})
    return {"ok": True, "cancelled": True}


# ---------------------------------------------------------------------------
# Execução de um bloco por fonte


def _bounds(block: Dict[str, str]) -> tuple[datetime, datetime]:
    start = datetime.combine(date.fromisoformat(block["start"]), dtime.min, TZ)
    end = datetime.combine(date.fromisoformat(block["end"]) + timedelta(days=1), dtime.min, TZ)
    return start, end


async def _run_fbits(client_id: str, block: Dict[str, str]) -> int:
    from .fbits_connections import (
        HISTORICAL_DATE_FILTER, PROVIDER, _refresh_daily_stats, ingest_fbits_window,
        load_fbits_connection, require_fbits_not_in_cooldown,
    )
    from .fbits_origin_probe import _client_for

    row = await load_fbits_connection(client_id)
    if not row:
        raise HistoryBackfillError("Conexão FBITS não encontrada.", code="FBITS_CONNECTION_NOT_FOUND")
    require_fbits_not_in_cooldown(row)
    metadata = dict(row.get("metadata") or {})
    status_names = {str(item.get("id")): str(item.get("nome") or "")
                    for item in metadata.get("order_statuses") or [] if isinstance(item, dict)}
    revenue_status_ids = [str(value) for value in metadata.get("revenue_status_ids") or []]
    client = await _client_for(client_id)
    start, end = _bounds(block)
    affected: set = set()
    # Mesmo lock do sync recorrente: nunca rodam juntos.
    async with guarded_sync(client_id=client_id, provider=PROVIDER, connection_id=str(row["id"])):
        counts = await ingest_fbits_window(client, client_id=client_id, start=start, end=end,
                                           date_filter=HISTORICAL_DATE_FILTER, status_names=status_names,
                                           affected_days=affected)
        await _refresh_daily_stats(client_id, affected, revenue_status_ids)
    return counts["orders"]


async def _run_shopify(client_id: str, block: Dict[str, str]) -> int:
    from .shopify_oauth import sync_shopify_connection

    connection_id = await _shopify_connection(client_id)
    if not connection_id:
        raise HistoryBackfillError("Conexão Shopify não encontrada.", code="SHOPIFY_CONNECTION_NOT_FOUND")
    start, end = _bounds(block)
    # reconciliation_period ativa a checagem de read_all_orders: sem ela a
    # Shopify devolveria zero pedidos antigos em silêncio.
    result = await sync_shopify_connection(
        client_id=client_id, connection_id=connection_id,
        created_at_min=start.isoformat(), created_at_max=(end - timedelta(seconds=1)).isoformat(),
        reconciliation_period=(block["start"], block["end"]),
    )
    return int(((result.get("synced") or {}).get("orders_upserted")) or 0)


async def _run_google(provider: str, client_id: str, block: Dict[str, str]) -> int:
    from .provider_history import backfill_provider_history

    result = await backfill_provider_history(client_id=client_id, provider=provider,
                                             start_date=block["start"], end_date=block["end"], resume=True)
    return int(result.get("rows_upserted") or 0)


async def _run_meta(client_id: str, block: Dict[str, str]) -> int:
    from .provider_history import backfill_provider_history

    # Enfileira na fila durável do Meta (worker a cada 5 min, 7 dias por vez).
    result = await backfill_provider_history(client_id=client_id, provider="meta_ads",
                                             start_date=block["start"], end_date=block["end"])
    return int(result.get("total_slices") or 0)


RUNNERS: Dict[str, Callable[[str, Dict[str, str]], Awaitable[int]]] = {
    "fbits": _run_fbits,
    "shopify": _run_shopify,
    "google_ads": lambda client_id, block: _run_google("google_ads", client_id, block),
    "ga4": lambda client_id, block: _run_google("ga4", client_id, block),
    "meta_ads": _run_meta,
}


def _error_code(exc: BaseException) -> str:
    return str(getattr(exc, "code", "") or "HISTORY_BLOCK_FAILED")[:60]


async def run_history_step(client_id: str, *, budget_seconds: float = 240,
                           pause_seconds: float = PAUSE_SECONDS) -> Dict[str, Any]:
    """Processa blocos pendentes desta empresa até acabar o orçamento de tempo."""
    request = await active_request(client_id)
    if not request:
        return {"ok": True, "client_id": client_id, "processed": 0, "state": "idle"}
    request_id = str(request["id"])
    payload = request.get("payload_json") or {}
    deadline = time.monotonic() + max(10.0, budget_seconds)
    processed = 0
    blocked: Dict[str, str] = {}
    async with guarded_sync(client_id=client_id, provider="provider_history",
                            connection_id=f"historico-{client_id}", ttl_seconds=int(budget_seconds) + 900):
        done = await _done_blocks(client_id, request_id)
        for target in payload.get("targets") or []:
            provider = target.get("provider")
            if provider not in RUNNERS or not target.get("connected") or not target.get("missing_start"):
                continue
            blocks = build_blocks(date.fromisoformat(target["missing_start"]),
                                  date.fromisoformat(target["missing_end"]), PROVIDERS[provider]["block_days"])
            # Do mais recente para o mais antigo: o período mais útil chega primeiro.
            for block in reversed(blocks):
                if (block["start"], block["end"]) in done.get(provider, set()):
                    continue
                if time.monotonic() >= deadline:
                    break
                checkpoint = {"request_id": request_id, "provider": provider, **block}
                job = await start_job_run(job_name=BLOCK_JOB, client_id=client_id,
                                          trigger_source="history_backfill", payload_json=checkpoint)
                job_id = str((job or {}).get("id") or "")
                try:
                    rows = await RUNNERS[provider](client_id, block)
                except Exception as exc:  # noqa: BLE001 — só o código vai para o registro
                    code = _error_code(exc)
                    if job_id:
                        await finish_job_run(job_id, status="error", error=code, client_id=client_id,
                                             payload_json={**checkpoint, "error_code": code})
                    print(f"[history_backfill] client_id={client_id} provider={provider} "
                          f"block={block['start']}..{block['end']} status=error code={code}")
                    blocked[provider] = code
                    break  # esta fonte para nesta rodada; as outras seguem
                if job_id:
                    await finish_job_run(job_id, status="success", rows_upserted=rows, client_id=client_id,
                                         payload_json={**checkpoint, "rows": rows})
                processed += 1
                print(f"[history_backfill] client_id={client_id} provider={provider} "
                      f"block={block['start']}..{block['end']} status=success rows={rows}")
                await asyncio.sleep(pause_seconds)
    plan = await history_plan(client_id)
    if all(item["state"] in {"complete", "not_connected"} for item in plan["providers"]):
        await finish_job_run(request_id, status="success", client_id=client_id, payload_json=payload)
        plan["request"] = None
        state = "complete"
    else:
        state = "pending"
    return {"ok": True, "client_id": client_id, "processed": processed, "blocked": blocked,
            "state": state, "plan": plan}


async def run_history_worker(*, budget_seconds: float = 2400, client_id: Optional[str] = None) -> Dict[str, Any]:
    """Cron noturno: percorre as empresas com pedido ativo, uma de cada vez."""
    filters = {"job_name": f"eq.{REQUEST_JOB}", "status": "eq.running"}
    if client_id:
        filters["client_id"] = f"eq.{client_id}"
    requests = await sb_select("cron_job_runs", select="client_id", filters=filters,
                               order="started_at.asc", limit=50)
    deadline = time.monotonic() + budget_seconds
    results = []
    for client in dict.fromkeys(str(row.get("client_id")) for row in requests if row.get("client_id")):
        remaining = deadline - time.monotonic()
        if remaining < 60:
            break
        try:
            result = await run_history_step(client, budget_seconds=remaining)
            results.append({"client_id": client, "processed": result["processed"], "state": result["state"],
                            "blocked": result.get("blocked") or {}})
        except Exception as exc:  # noqa: BLE001
            results.append({"client_id": client, "state": "error", "code": _error_code(exc)})
    return {"ok": True, "companies": results}
