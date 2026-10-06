"""Origem das chamadas Graph; sem IDs de mídia, tenant, token ou payload."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
from .request_performance import current_request

_ORIGIN = ContextVar("meta_live_origin", default=None)
TRIGGERS = {"navigation", "manual_refresh", "scheduled_sync", "reconciliation", "backfill", "onboarding", "unknown"}

@contextmanager
def live_scope(trigger_source, job_run_id=None):
    if trigger_source not in TRIGGERS:
        raise ValueError("Origem operacional inválida")
    token = _ORIGIN.set({"trigger_source": trigger_source, "job_run_id": job_run_id})
    try:
        yield
    finally:
        _ORIGIN.reset(token)


def trace_live_call(operation):
    request = current_request()
    origin = _ORIGIN.get()
    if origin is None:
        path = request.get("endpoint") or ""
        if request.get("method") == "GET": source = "navigation"
        elif "backfill" in path: source = "backfill"
        elif "reconcil" in path: source = "reconciliation"
        elif "cron" in path: source = "scheduled_sync"
        elif "refresh" in path or path == "/api/ig/sync": source = "manual_refresh"
        elif any(part in path for part in ("activate", "assets", "oauth")): source = "onboarding"
        else: source = "unknown"
        origin = {"trigger_source": source, "job_run_id": None}
    print("[meta][live_call] " + json.dumps({**origin, "request_id": request.get("request_id"), "operation": operation}, separators=(",", ":")), flush=True)
