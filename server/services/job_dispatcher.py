"""Despachante das sincronizações recorrentes (GitHub Actions).

Por quê: o GitHub descarta ou atrasa muitos disparos agendados (na prática,
bem menos da metade dos horários do workflow rodava). Com um horário fixo por
job, cada disparo perdido era uma atualização perdida — foi assim que o
Instagram orgânico (4 horários por dia) ficava horas ou dias sem atualizar.

Agora um único disparo frequente ("tick") roda, em ordem de prioridade, todo
job cujo horário mais recente da agenda ainda não foi atendido. Qualquer tick
que sobreviva recupera os horários perdidos. A agenda continua a mesma
(src/app/autoRefreshSchedule.ts mostra os mesmos horários na tela).

O último disparo de cada job fica em `cron_job_runs` (job_name
"dispatcher:<comando>", client_id nulo), o que torna o tick idempotente entre
execuções e visível no banco. Os locks por conexão (`cron_locks`) continuam
protegendo contra sobreposição com atualizações manuais.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .ig_supabase import sb_select
from .job_runs import finish_job_run, start_job_run

JOB_PREFIX = "dispatcher:"
# Quanto o tick olha para trás procurando um horário da agenda (cobre o semanal).
LOOKBACK = timedelta(days=8)


@dataclass(frozen=True)
class ScheduledJob:
    cron: str          # minuto hora dia-do-mês mês dia-da-semana, em UTC
    command: str       # argumentos de run_jobs.py
    timeout_minutes: int

    @property
    def key(self) -> str:
        return JOB_PREFIX + self.command

    @property
    def name(self) -> str:
        return self.command.split()[0]


# Ordem = prioridade dentro de um tick: token antes de tudo; incrementais
# rápidos antes das conferências longas de 30/90 dias.
SCHEDULE: tuple[ScheduledJob, ...] = (
    ScheduledJob("15 */6 * * *", "token-refresh", 10),
    ScheduledJob("0,30 * * * *", "fbits-sync-all", 15),
    ScheduledJob("15,45 * * * *", "shopify-reconcile --fallback-days 30", 15),
    ScheduledJob("5 * * * *", "ads-sync-hourly --days 7", 20),
    ScheduledJob("10 6,12,18,23 * * *", "organic-sync --limit 60", 25),
    ScheduledJob("20 */3 * * *", "ga4-sync-all --days 3", 20),
    ScheduledJob("35 */3 * * *", "google-ads-sync --days 7", 20),
    ScheduledJob("*/10 * * * *", "ads-backfill-worker", 10),
    ScheduledJob("25 7 * * *", "shopify-historical-reconcile --days 14", 30),
    ScheduledJob("45 2 * * *", "ads-sync-hourly --days 30", 30),
    ScheduledJob("15 3 * * *", "ga4-sync-all --days 30", 30),
    ScheduledJob("45 3 * * *", "google-ads-sync --days 30", 30),
    ScheduledJob("40 8 * * 0", "shopify-historical-reconcile --days 90", 45),
    ScheduledJob("20 9 * * 0", "organic-sync --limit 250 --skip-thumbnails", 45),
)


def _field(spec: str, low: int, high: int) -> frozenset[int]:
    values: set[int] = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, raw_step = part.split("/", 1)
            step = int(raw_step)
        if part == "*":
            start, end = low, high
        elif "-" in part:
            start, end = (int(v) for v in part.split("-", 1))
        else:
            start = end = int(part)
        if not (low <= start <= end <= high) or step < 1:
            raise ValueError(f"cron fora do intervalo: {spec}")
        values.update(range(start, end + 1, step))
    return frozenset(values)


def _matcher(cron: str) -> Callable[[datetime], bool]:
    minute, hour, dom, month, dow = cron.split()
    minutes, hours = _field(minute, 0, 59), _field(hour, 0, 23)
    days, months = _field(dom, 1, 31), _field(month, 1, 12)
    weekdays = frozenset(d % 7 for d in _field(dow, 0, 7))  # cron: 0 e 7 = domingo

    def matches(moment: datetime) -> bool:
        return (moment.minute in minutes and moment.hour in hours and moment.day in days
                and moment.month in months and (moment.isoweekday() % 7) in weekdays)

    return matches


def latest_slot(cron: str, now: datetime) -> Optional[datetime]:
    """Horário mais recente da agenda em ou antes de `now` (UTC), até LOOKBACK."""
    matches = _matcher(cron)
    cursor = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
    floor = cursor - LOOKBACK
    while cursor >= floor:
        if matches(cursor):
            return cursor
        cursor -= timedelta(minutes=1)
    return None


def _parse(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def last_dispatch(job: ScheduledJob) -> Optional[datetime]:
    rows = await sb_select("cron_job_runs", select="started_at", filters={"job_name": f"eq.{job.key}"},
                           order="started_at.desc", limit=1)
    return _parse(rows[0].get("started_at")) if rows else None


async def due_jobs(now: datetime) -> List[tuple[ScheduledJob, datetime]]:
    due = []
    for job in SCHEDULE:
        slot = latest_slot(job.cron, now)
        if slot is None:
            continue
        try:
            last = await last_dispatch(job)
        except Exception:
            # Sem como ler o histórico: roda (os locks por conexão evitam sobreposição).
            last = None
        if last is None or last < slot:
            due.append((job, slot))
    return due


def _summary(result: Any) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    keys = ("connections_total", "connections_ok", "connections_fail")
    return {key: result[key] for key in keys if isinstance(result.get(key), int)}


def public_line(job: ScheduledJob, status: str, seconds: int, summary: Dict[str, Any]) -> str:
    """Linha neutra para o log público: só comando, status, duração e contagens."""
    line = f"[tick] job={job.name} status={status} duracao_s={seconds}"
    if "connections_total" in summary and "connections_fail" in summary:
        line += f" falhas={summary['connections_fail']}/{summary['connections_total']}"
    return line


async def run_tick(
    runner: Callable[[str], Awaitable[Any]],
    *,
    budget_seconds: int,
    now: Optional[datetime] = None,
    emit: Callable[[str], None] = print,
) -> Dict[str, Any]:
    started = time.monotonic()
    pending = await due_jobs(now or datetime.now(timezone.utc))
    results: List[Dict[str, Any]] = []
    for job, slot in pending:
        if time.monotonic() - started >= budget_seconds:
            results.append({"command": job.command, "status": "adiado"})
            emit(f"[tick] job={job.name} status=adiado duracao_s=0")
            continue
        try:
            run = await start_job_run(job_name=job.key, trigger_source="dispatcher",
                                      payload_json={"command": job.command, "slot": slot.isoformat()})
        except Exception:
            run = None  # Sem registro o job ainda roda; o próximo tick o verá como pendente.
        job_started = time.monotonic()
        status, error, summary = "ok", None, {}
        try:
            result = await asyncio.wait_for(runner(job.command), timeout=job.timeout_minutes * 60)
            summary = _summary(result)
            if isinstance(result, dict) and result.get("ok") is False:
                status = "parcial"
        except asyncio.TimeoutError:
            status, error = "tempo_esgotado", f"Excedeu {job.timeout_minutes} min"
        except Exception as exc:
            status, error = "falhou", f"{exc.__class__.__name__}: {str(exc)[:500]}"
        seconds = round(time.monotonic() - job_started)
        try:
            if run and run.get("id"):
                await finish_job_run(run["id"], status={"ok": "success", "parcial": "partial"}.get(status, "error"),
                                     error=error, payload_json={"command": job.command, "slot": slot.isoformat(),
                                                                "duration_s": seconds, **summary})
        except Exception:
            pass
        emit(public_line(job, status, seconds, summary))
        results.append({"command": job.command, "status": status, **summary})
    return {
        "ok": all(r["status"] in {"ok", "parcial", "adiado"} for r in results),
        "job": "tick",
        "due": len(pending),
        "results": results,
    }
