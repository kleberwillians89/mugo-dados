"""Lê a agenda horário → comando de .github/scripts/due_jobs.py (fonte única do "Relógio dos jobs")."""
from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "due_jobs.py"
WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "jobs-tick.yml"


def _module():
    spec = importlib.util.spec_from_file_location("due_jobs", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scheduled_commands() -> dict[str, str]:
    mapping = dict(_module().SCHEDULE)
    assert len(mapping) == len(_module().SCHEDULE), "horário repetido na agenda"
    return mapping
