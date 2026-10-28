"""Agenda efetiva: horário → comando.

O workflow (.github/workflows/sync-jobs.yml) só dispara o tick e o histórico;
a agenda de cada job mora em services/job_dispatcher.SCHEDULE.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "sync-jobs.yml"
_CASE = re.compile(r'^\s*"([^"]+)"\)\s+cmd="([^"]+)"\s*;;\s*$')
_CRON = re.compile(r'^\s*- cron: "([^"]+)"')


def workflow_commands() -> dict[str, str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    crons = {m.group(1) for line in text.splitlines() if (m := _CRON.match(line))}
    mapping = {m.group(1): m.group(2) for line in text.splitlines() if (m := _CASE.match(line))}
    # Todo horário agendado precisa de comando e vice-versa.
    assert crons == set(mapping), (sorted(crons ^ set(mapping)))
    return mapping


def scheduled_commands() -> dict[str, str]:
    if str(ROOT / "server") not in sys.path:
        sys.path.insert(0, str(ROOT / "server"))
    from services.job_dispatcher import SCHEDULE

    mapping = {job.cron: job.command for job in SCHEDULE}
    assert len(mapping) == len(SCHEDULE), "horários duplicados na agenda"
    workflow = workflow_commands()
    assert workflow.get("*/5 * * * *", "").startswith("tick "), "workflow precisa disparar o tick"
    return {**mapping, **{cron: cmd for cron, cmd in workflow.items() if not cmd.startswith("tick ")}}
