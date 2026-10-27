"""Lê o mapeamento horário → comando de .github/workflows/sync-jobs.yml."""
from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "sync-jobs.yml"
_CASE = re.compile(r'^\s*"([^"]+)"\)\s+cmd="([^"]+)"\s*;;\s*$')
_CRON = re.compile(r'^\s*- cron: "([^"]+)"')


def scheduled_commands() -> dict[str, str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    crons = {m.group(1) for line in text.splitlines() if (m := _CRON.match(line))}
    mapping = {m.group(1): m.group(2) for line in text.splitlines() if (m := _CASE.match(line))}
    # Todo horário agendado precisa de comando e vice-versa.
    assert crons == set(mapping), (sorted(crons ^ set(mapping)))
    return mapping
