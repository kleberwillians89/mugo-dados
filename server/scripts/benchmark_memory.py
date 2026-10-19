"""Offline synthetic Instagram/cache RSS benchmark. No provider or database calls.

APP_ENV=production python server/scripts/benchmark_memory.py instagram
Use --baseline-dir with a local copy of the original service files for comparison.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.memory_budget import rss_bytes


def load_service(name, baseline):
    if baseline:
        spec = importlib.util.spec_from_file_location(f"services.benchmark_{name}", baseline / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    return __import__(f"services.{name}", fromlist=[name])


async def run(args):
    module = load_service("instagram_sync" if args.operation == "instagram" else "runtime_cache", args.baseline_dir)
    initial = rss_bytes()
    peak = initial
    largest_batch = 0
    count = 0
    def observe():
        nonlocal peak
        value = rss_bytes()
        if value is not None:
            peak = max(peak or 0, value)
    if args.operation == "instagram":
        async def comments(media_id, *_args, **_kwargs):
            return [{"id": f"{media_id}-{i}", "text": f"fixture-{media_id}-{i}:" + "x" * 512} for i in range(200)]
        async def upsert(table, rows, **_kwargs):
            nonlocal largest_batch, count
            if table == "ig_comments":
                largest_batch = max(largest_batch, len(rows))
                count += len(rows)
            # Model the HTTP JSON serialization while rows are still alive.
            encoded = json.dumps(rows).encode()
            observe()
            await asyncio.sleep(0)
            return {"ok": bool(encoded)}
        with (patch.object(module, "fetch_profile", AsyncMock(return_value={})),
              patch.object(module, "fetch_media_list", AsyncMock(return_value=[{"id": str(i), "comments_count": 200} for i in range(200)])),
              patch.object(module, "fetch_media_comments", comments),
              patch.object(module, "fetch_media_insights", AsyncMock(return_value={"reach": 1})),
              patch.object(module, "fetch_kpis_total_value", AsyncMock(return_value={"reach": 1})),
              patch.object(module, "fetch_stories", AsyncMock(return_value=[])),
              patch.object(module, "sb_upsert", upsert)):
            result = await module._run_sync_for_client_and_ig(client_id="fixture", connection_id="fixture",
                ig_user_id="fixture", access_token="fixture", limit=200)
            assert result["comments_saved"] == 40000
    else:
        for i in range(200):
            async def loader():
                return str(i) + "x" * (128 * 1024)
            await module.get_cached_or_load(namespace="fixture", key=str(i), ttl_seconds=60, loader=loader)
            observe()
        count = len(module._CACHE)
    final = rss_bytes()
    print(json.dumps({"operation": args.operation, "baseline": bool(args.baseline_dir),
        "rss_initial_bytes": initial, "rss_observed_peak_bytes": peak, "rss_final_bytes": final,
        "largest_comment_batch": largest_batch, "records_or_cache_entries": count}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["instagram", "cache"])
    parser.add_argument("--baseline-dir", type=Path)
    asyncio.run(run(parser.parse_args()))
