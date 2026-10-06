"""Medição e memoização estritamente limitadas a UMA requisição HTTP."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
import hashlib
import json
import time
from datetime import datetime, timezone


@dataclass
class RequestPerformance:
    request_id: str
    started: float = field(default_factory=time.perf_counter)
    phases: dict = field(default_factory=dict)
    memo: dict = field(default_factory=dict)
    round_trips: int = 0
    covered_ms: float = 0
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    scope: dict = field(default_factory=dict)


_CURRENT = ContextVar("request_performance", default=None)
_PHASE = ContextVar("request_performance_phase", default="unclassified")
_DEPTH = ContextVar("request_performance_depth", default=0)
_ACTIVE_TRANSPORT = 0


def begin(request_id: str):
    state = RequestPerformance(request_id)
    return state, _CURRENT.set(state)


def end(token):
    _CURRENT.reset(token)


def measured(phase: str, *, memo: bool = False):
    def decorate(function):
        @wraps(function)
        async def call(*args, **kwargs):
            state = _CURRENT.get()
            if state is None:
                return await function(*args, **kwargs)
            # Nenhum argumento, hash, identidade ou bearer entra nos logs.
            key = (function.__module__, function.__name__, hashlib.sha256(
                repr((args, sorted(kwargs.items()))).encode()).digest())
            if memo and key in state.memo:
                return await asyncio.shield(state.memo[key])

            async def invoke():
                start = time.perf_counter()
                depth = _DEPTH.get()
                depth_token = _DEPTH.set(depth + 1)
                phase_token = _PHASE.set(phase)
                try:
                    return await function(*args, **kwargs)
                finally:
                    elapsed = (time.perf_counter() - start) * 1000
                    data = state.phases.setdefault(phase, {"calls": 0, "duration_ms": 0})
                    data["calls"] += 1
                    data["duration_ms"] += elapsed
                    if depth == 0:
                        state.covered_ms += elapsed
                    _PHASE.reset(phase_token)
                    _DEPTH.reset(depth_token)
            if not memo:
                return await invoke()
            task = asyncio.create_task(invoke())
            state.memo[key] = task
            try:
                return await asyncio.shield(task)
            except BaseException:
                if task.done():
                    state.memo.pop(key, None)
                raise
        return call
    return decorate


def transport_started():
    global _ACTIVE_TRANSPORT
    _ACTIVE_TRANSPORT += 1
    state = _CURRENT.get()
    if state:
        state.round_trips += 1
    return time.perf_counter(), _ACTIVE_TRANSPORT


def transport_done(started, *, dependency: str, operation: str, status: str):
    global _ACTIVE_TRANSPORT
    start, concurrency = started
    _ACTIVE_TRANSPORT -= 1
    state = _CURRENT.get()
    if state:
        print("[performance][dependency] " + json.dumps({
            "request_id": state.request_id, "phase": _PHASE.get(),
            "dependency": dependency, "operation": operation,
            "status": status, "duration_ms": round((time.perf_counter() - start) * 1000, 2),
            "inflight_at_start": concurrency,
        }, separators=(",", ":")), flush=True)


def summary(state, status):
    elapsed = (time.perf_counter() - state.started) * 1000
    print("[performance][request] " + json.dumps({
        "request_id": state.request_id, "status": status,
        "started_at": state.started_at, **state.scope,
        "duration_ms": round(elapsed, 2), "supabase_round_trips": state.round_trips,
        "phases": {key: {**value, "duration_ms": round(value["duration_ms"], 2)}
                   for key, value in state.phases.items()},
        "unclassified_ms": round(max(0, elapsed - state.covered_ms), 2),
    }, separators=(",", ":")), flush=True)


def request_value(key, value=None, *, store=False):
    """Reuse de fatos já lidos: somente no contexto HTTP atual, nunca global."""
    state = _CURRENT.get()
    if state is None:
        return None
    scoped = ("validated_fact", key)
    if store:
        state.memo[scoped] = value
    return state.memo.get(scoped)


def current_request():
    state = _CURRENT.get()
    return {"request_id": state.request_id, "endpoint": state.scope.get("endpoint"), "method": state.scope.get("method")} if state else {}
