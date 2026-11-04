"""Agenda dos jobs (fonte única) e quais estão no horário desta janela de 5 minutos.

Por quê: o agendador do GitHub (on.schedule) descarta a maior parte dos disparos quando há muitos
horários (medido em 04/11: 20 execuções em 8 h, contra centenas previstas). Agora um único "relógio"
de 5 em 5 minutos (cron-job.org chamando o workflow_dispatch; o schedule do GitHub fica de reserva)
roda este script, que devolve os comandos cujo horário cai na janela [HH:MM, HH:MM+4].

Uso: python due_jobs.py [AAAA-MM-DDTHH:MM]  →  imprime {"slot": "...", "commands": [...]}
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Set, Tuple

# (cron UTC, comando). São Paulo = UTC-3. Mesmos horários de antes.
SCHEDULE: List[Tuple[str, str]] = [
    ("15 */6 * * *", "token-refresh"),
    ("10 6,12,18,23 * * *", "organic-sync --limit 60"),
    ("5 * * * *", "ads-sync-hourly --days 7"),
    ("20 */3 * * *", "ga4-sync-all --days 3"),
    ("35 */3 * * *", "google-ads-sync --days 7"),
    ("0,30 * * * *", "fbits-sync-all"),
    ("15,45 * * * *", "shopify-reconcile --fallback-days 30"),
    ("25 7 * * *", "shopify-historical-reconcile --days 14"),
    ("40 8 * * 0", "shopify-historical-reconcile --days 90"),
    ("45 2 * * *", "ads-sync-hourly --days 30"),
    ("*/10 * * * *", "ads-backfill-worker"),
    ("15 3 * * *", "ga4-sync-all --days 30"),
    ("45 3 * * *", "google-ads-sync --days 30"),
    ("20 9 * * 0", "organic-sync --limit 250 --skip-thumbnails"),
    ("10 5 * * *", "history-backfill-worker --budget-minutes 150"),
    ("15 13 * * 5", "studio-weekly-digest"),
    ("50 * * * *", "studio-team-retry"),
    ("*/5 * * * *", "automations-process"),
    ("*/15 * * * *", "calendar-sync"),
    ("2-59/5 * * * *", "ig-engagement-run"),
    ("4-59/5 * * * *", "ig-publish-due"),
    ("2 19 * * *", "ig-ai-replies"),
    ("40 10 * * *", "studio-clipping"),
    ("20 12 1 * *", "brand-profile-monthly"),
]
SLOT_MINUTES = 5


def _field(expr: str, low: int, high: int) -> Set[int]:
    values: Set[int] = set()
    for part in expr.split(","):
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            step = int(step_text)
        if part == "*":
            start, end = low, high
        elif "-" in part:
            start, end = (int(x) for x in part.split("-", 1))
        else:
            start = end = int(part)
        values.update(range(start, end + 1, step))
    return values


def matches(cron: str, moment: datetime) -> bool:
    minute, hour, day, month, weekday = cron.split()
    cron_weekday = (moment.weekday() + 1) % 7  # cron: domingo = 0
    return (moment.minute in _field(minute, 0, 59) and moment.hour in _field(hour, 0, 23)
            and moment.day in _field(day, 1, 31) and moment.month in _field(month, 1, 12)
            and cron_weekday in _field(weekday.replace("7", "0"), 0, 6))


def slot_start(now: datetime) -> datetime:
    now = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
    return now - timedelta(minutes=now.minute % SLOT_MINUTES)


def due(now: datetime) -> Tuple[datetime, List[str]]:
    start = slot_start(now)
    minutes = [start + timedelta(minutes=i) for i in range(SLOT_MINUTES)]
    commands = [cmd for cron, cmd in SCHEDULE if any(matches(cron, m) for m in minutes)]
    return start, list(dict.fromkeys(commands))


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    now = datetime.fromisoformat(arg).replace(tzinfo=timezone.utc) if arg else datetime.now(timezone.utc)
    start, commands = due(now)
    print(json.dumps({"slot": start.strftime("%Y-%m-%dT%H:%M:00Z"), "commands": commands}))
