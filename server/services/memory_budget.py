"""Process-local admission and sampled RSS; never inspect operation arguments."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from functools import wraps
import json
import os
import sys
import time
import uuid

from .integration_errors import IntegrationError
from .request_performance import current_request

_ACTIVE = 0
_RECORDS = ContextVar("memory_records", default=None)


def records_processed(count):
    records = _RECORDS.get()
    if records is not None:
        records[0] += count


def rss_bytes():
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/self/statm", encoding="ascii") as stream:
                return int(stream.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
        if sys.platform == "darwin":
            import ctypes
            # sys/proc_info.h: proc_taskinfo = six uint64_t + twelve int32_t.
            info = (ctypes.c_uint64 * 12)()
            libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
            if libproc.proc_pidinfo(os.getpid(), 4, 0, ctypes.byref(info), ctypes.sizeof(info)) == ctypes.sizeof(info):
                return int(info[1])
    except (OSError, ValueError, IndexError, AttributeError):
        pass
    return None


def reject_if_memory_busy(operation):
    """Advisory preflight; operation_memory still owns atomic admission."""
    if _ACTIVE:
        raise IntegrationError(
            "Há um processamento em andamento. Tente novamente em instantes.",
            status_code=503, code="PROCESS_MEMORY_BUSY", provider=operation, retryable=True,
        )


@asynccontextmanager
async def operation_memory(operation, *, limit=False):
    global _ACTIVE
    if limit:
        reject_if_memory_busy(operation)
    if limit:
        _ACTIVE += 1
    request = current_request()
    initial = rss_bytes()
    peak = initial
    started = time.perf_counter()
    concurrency = _ACTIVE
    records = [0]
    records_token = _RECORDS.set(records)

    async def sample():
        nonlocal peak, concurrency
        while True:
            await asyncio.sleep(1)
            observed = rss_bytes()
            if observed is not None:
                peak = max(peak or 0, observed)
            concurrency = max(concurrency, _ACTIVE)

    task = asyncio.create_task(sample())
    try:
        yield records
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        _RECORDS.reset(records_token)
        final = rss_bytes()
        if limit:
            _ACTIVE -= 1
        print("[memory][operation] " + json.dumps({
            "operation": operation, "origin": "http" if request else "job",
            "request_id": request.get("request_id"),
            "job_id": None if request else uuid.uuid4().hex,
            "rss_initial_bytes": initial,
            "rss_observed_peak_bytes": max(peak or 0, final or 0) or None,
            "rss_final_bytes": final,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "records_processed": records[0], "heavy_concurrency": concurrency,
        }, separators=(",", ":")), flush=True)


def measured_operation(operation, *, limit=False):
    def decorate(function):
        @wraps(function)
        async def call(*args, **kwargs):
            async with operation_memory(operation, limit=limit) as records:
                result = await function(*args, **kwargs)
                if isinstance(result, dict):
                    count = result.get("rows_upserted")
                    if isinstance(count, int):
                        records[0] = count
                    elif isinstance(result.get("media"), list):
                        records[0] = len(result["media"]) + int(result.get("comments_saved") or 0)
                return result
        return call
    return decorate
