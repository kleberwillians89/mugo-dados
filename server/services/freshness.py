from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict


def freshness_hours(provider: str) -> int:
    key = f"{str(provider or '').strip().upper()}_FRESHNESS_HOURS"
    try:
        return max(1, int((os.getenv(key) or os.getenv("INTEGRATION_FRESHNESS_HOURS") or "6").strip()))
    except ValueError:
        return 6


def source_freshness(provider: str, last_sync_at: Any, *, data_available: bool) -> Dict[str, Any]:
    raw = str(last_sync_at or "").strip()
    age_hours = None
    if raw:
        try:
            synced = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            age_hours = max(0.0, (datetime.now(timezone.utc) - synced).total_seconds() / 3600)
        except ValueError:
            age_hours = None
    threshold = freshness_hours(provider)
    stale = bool(data_available and (age_hours is None or age_hours > threshold))
    return {
        "provider": provider,
        "data_available": bool(data_available),
        "last_sync_at": raw or None,
        "freshness_hours": threshold,
        "age_hours": round(age_hours, 2) if age_hours is not None else None,
        "stale": stale,
    }
