from __future__ import annotations

from datetime import date
import time
from typing import Any, Dict, Optional

from .periods import resolve_period


def _parse_date(value: str | None) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except Exception:
        return None


def _resolve_period(days: int, start: str | None, end: str | None) -> tuple[date, date]:
    period = resolve_period(start=start, end=end, days=days, max_days=3650)
    return period.start, period.end


def _story_in_range(story: Dict[str, Any], since: date, until: date) -> bool:
    ts = str(story.get("timestamp") or "").strip()
    if len(ts) < 10:
        return False
    try:
        d = date.fromisoformat(ts[:10])
    except Exception:
        return False
    return since <= d <= until


async def get_stories(
    client_id: str,
    connection_id: Optional[str] = None,
    limit: int = 25,
    days: int = 30,
    start: str | None = None,
    end: str | None = None,
) -> Dict[str, Any]:
    started = time.perf_counter()
    since, until = _resolve_period(days=days, start=start, end=end)
    print(
        "[stories] persisted_read "
        f"client_id={client_id} connection_id={str(connection_id or '').strip() or '-'} "
        f"start={since.isoformat()} end={until.isoformat()} rows=0 state=not_in_pilot "
        f"duration_ms={int((time.perf_counter() - started) * 1000)}"
    )
    return {
        "ok": True,
        "available": False,
        "state": "not_in_pilot",
        "client_id": client_id,
        "connection_id": str(connection_id or "").strip() or None,
        "message": "Stories não participam do piloto atual.",
        "stories": [],
        "warnings": [],
    }
