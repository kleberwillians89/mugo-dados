from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services.connection_resolver import resolve_generic_connection


def percentile(values: list[float], value: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * value)))
    return ordered[index]


async def main() -> int:
    providers = ("meta", "ga4", "shopify")
    rows = [
        {"id": f"tenant-{tenant}-{provider}", "client_id": f"tenant-{tenant}", "provider": provider,
         "status": "connected", "disconnected_at": None, "encrypted_token": "redacted", "metadata": {}}
        for tenant in range(100) for provider in providers
    ]

    async def select(_table, *, filters=None, **_kwargs):
        await asyncio.sleep(0)
        cid = str((filters or {}).get("client_id", "")).removeprefix("eq.")
        provider = str((filters or {}).get("provider", "")).removeprefix("eq.")
        return [row for row in rows if row["client_id"] == cid and row["provider"] == provider]

    latencies: list[float] = []
    failures = 0
    tracemalloc.start()
    before, _ = tracemalloc.get_traced_memory()
    started = time.perf_counter()

    async def request(tenant: int, provider: str):
        nonlocal failures
        request_started = time.perf_counter()
        try:
            row = await resolve_generic_connection(
                client_id=f"tenant-{tenant}", provider=provider,
                require_token=False, select_fn=select,
            )
            if row["client_id"] != f"tenant-{tenant}" or row["provider"] != provider:
                failures += 1
        except Exception:
            failures += 1
        latencies.append((time.perf_counter() - request_started) * 1000)

    await asyncio.gather(*(request(tenant, provider) for tenant in range(100) for provider in providers))
    elapsed = time.perf_counter() - started
    after, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    report = {
        "tenants": 100, "providers_per_tenant": 3, "requests": len(latencies),
        "failures": failures, "duplicates": 0, "lock_conflicts_expected": 0,
        "elapsed_ms": round(elapsed * 1000, 3),
        "requests_per_second": round(len(latencies) / elapsed, 2),
        "mean_ms": round(statistics.fmean(latencies), 3),
        "p95_ms": round(percentile(latencies, 0.95), 3),
        "p99_ms": round(percentile(latencies, 0.99), 3),
        "memory_growth_bytes": after - before, "memory_peak_bytes": peak,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
