from __future__ import annotations

import asyncio
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import runtime_cache as cache, memory_budget, sync_locks, instagram_sync
from services.integration_errors import IntegrationError


class CacheMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cache._CACHE.clear()
        cache._INFLIGHT.clear()

    async def asyncTearDown(self):
        if cache._EXPIRY_HANDLE:
            cache._EXPIRY_HANDLE.cancel()
        cache._CACHE.clear()

    async def test_many_tenant_period_keys_are_bounded_and_isolated(self):
        for index in range(100):
            value, _ = await cache.get_cached_or_load(namespace=f"tenant-{index}", key="period",
                ttl_seconds=60, loader=AsyncMock(return_value={"value": index}))
            self.assertEqual(value, {"value": index})
        self.assertEqual(len(cache._CACHE), cache._MAX_ENTRIES)
        self.assertNotIn("tenant-0:period", cache._CACHE)
        self.assertEqual(cache._CACHE["tenant-99:period"][1], {"value": 99})

    async def test_large_result_is_returned_but_never_retained(self):
        payload = "x" * (cache._MAX_ENTRY_BYTES + 1)
        loader = AsyncMock(return_value=payload)
        for _ in range(2):
            value, hit = await cache.get_cached_or_load(namespace="tenant", key="large", ttl_seconds=60, loader=loader)
            self.assertEqual(value, payload)
            self.assertFalse(hit)
        self.assertFalse(cache._CACHE)
        self.assertFalse(cache._INFLIGHT)
        self.assertEqual(loader.await_count, 2)

    async def test_idle_expired_entries_are_released_without_another_request(self):
        await cache.get_cached_or_load(namespace="tenant", key="short", ttl_seconds=1,
            loader=AsyncMock(return_value={"value": 1}))
        await asyncio.sleep(1.05)
        self.assertFalse(cache._CACHE)

    async def test_cancelled_waiter_does_not_leave_completed_task_retained(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def load():
            started.set()
            await release.wait()
            raise ValueError("fixture")
        waiter = asyncio.create_task(cache.get_cached_or_load(namespace="tenant", key="cancel", ttl_seconds=1, loader=load))
        await started.wait()
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        task = cache._INFLIGHT["tenant:cancel"]
        release.set()
        with self.assertRaises(ValueError):
            await task
        self.assertFalse(cache._INFLIGHT)

    async def test_concurrent_waiters_share_single_loader(self):
        async def load():
            await asyncio.sleep(0)
            return {"value": 1}
        loader = AsyncMock(side_effect=load)
        results = await asyncio.gather(*(cache.get_cached_or_load(namespace="tenant", key="same", ttl_seconds=5, loader=loader) for _ in range(10)))
        self.assertEqual(loader.await_count, 1)
        self.assertEqual(len(results), 10)
        self.assertFalse(cache._INFLIGHT)


class HeavyOperationTests(unittest.IsolatedAsyncioTestCase):
    async def test_busy_job_releases_distributed_lock_and_cancellation_releases_capacity(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def job():
            async with sync_locks.guarded_sync(client_id="tenant-a", provider="ga4", connection_id="a"):
                entered.set()
                await release.wait()
        with (patch.object(sync_locks, "acquire_sync_lock", AsyncMock(return_value=True)),
              patch.object(sync_locks, "release_sync_lock", AsyncMock()) as unlock):
            first = asyncio.create_task(job())
            await entered.wait()
            with self.assertRaises(IntegrationError) as raised:
                async with sync_locks.guarded_sync(client_id="tenant-b", provider="shopify", connection_id="b"):
                    self.fail("busy job entered")
            self.assertEqual(raised.exception.code, "PROCESS_MEMORY_BUSY")
            self.assertEqual(raised.exception.status_code, 503)
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            self.assertEqual(memory_budget._ACTIVE, 0)
            self.assertEqual(unlock.await_count, 2)
            async with sync_locks.guarded_sync(client_id="tenant-b", provider="shopify", connection_id="b"):
                pass

    async def test_navigation_and_startup_during_simulated_sync(self):
        import app
        import httpx
        with patch.object(app, "bootstrap_meta_from_env", AsyncMock(return_value=[])):
            await app.startup_bootstrap()
        async with memory_budget.operation_memory("simulated_sync", limit=True):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url="http://local") as client:
                response = await asyncio.wait_for(client.get("/health"), timeout=2)
                self.assertEqual(response.status_code, 200)
                version = await client.get("/api/version")
                self.assertEqual(version.status_code, 200)

    async def test_memory_log_contains_only_allowlisted_fields(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream), patch.object(memory_budget, "rss_bytes", side_effect=[100, 120]):
            async with memory_budget.operation_memory("fixture", limit=True):
                memory_budget.records_processed(200)
        payload = json.loads(stream.getvalue().split(" ", 1)[1])
        self.assertEqual(payload["rss_observed_peak_bytes"], 120)
        self.assertEqual(payload["records_processed"], 200)
        self.assertEqual(set(payload), {"operation", "origin", "request_id", "job_id", "rss_initial_bytes",
            "rss_observed_peak_bytes", "rss_final_bytes", "duration_ms", "records_processed", "heavy_concurrency"})


class InstagramBatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_200_media_comments_are_persisted_in_bounded_tenant_scoped_batches(self):
        sizes = []
        async def write(table, rows, **kwargs):
            if table == "ig_comments":
                sizes.append(len(rows))
                self.assertTrue(all(row["client_id"] == "tenant-a" for row in rows))
                self.assertTrue(all(row["connection_id"] == "conn-a" for row in rows))
        async def comments(media_id, *_args, **_kwargs):
            return [{"id": f"{media_id}-{i}", "text": "fixture"} for i in range(200)]
        with (patch.object(instagram_sync, "fetch_profile", AsyncMock(return_value={})),
              patch.object(instagram_sync, "fetch_media_list", AsyncMock(return_value=[{"id": str(i), "comments_count": 200} for i in range(200)])),
              patch.object(instagram_sync, "fetch_media_comments", comments),
              patch.object(instagram_sync, "fetch_media_insights", AsyncMock(return_value={"reach": 1})),
              patch.object(instagram_sync, "fetch_kpis_total_value", AsyncMock(return_value={"reach": 1})),
              patch.object(instagram_sync, "fetch_stories", AsyncMock(return_value=[])),
              patch.object(instagram_sync, "sb_upsert", write)):
            result = await instagram_sync._run_sync_for_client_and_ig(client_id="tenant-a", connection_id="conn-a", ig_user_id="ig-a", access_token="fixture", limit=200)
        self.assertEqual(max(sizes), 200)
        self.assertEqual(sum(sizes), 40000)
        self.assertEqual(result["comments_fetched"], 40000)
        self.assertEqual(result["comments_saved"], 40000)
        self.assertTrue(result["snapshot_saved"])


class ThumbnailMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_oversize_thumbnail_stops_stream_and_closes_resources(self):
        import httpx
        from services import ig_meta
        chunks = []
        class Body(httpx.AsyncByteStream):
            closed = False
            async def __aiter__(self):
                for _ in range(100):
                    chunks.append(1)
                    yield b'x' * 65536
            async def aclose(self):
                self.closed = True
        body = Body()
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=body)))
        with patch.object(ig_meta.httpx, "AsyncClient", return_value=client), patch.object(ig_meta, "MAX_THUMBNAIL_BYTES", 65536):
            with self.assertRaisesRegex(ValueError, "thumbnail_size_limit"):
                await ig_meta.download_image("https://fixture/thumbnail")
        self.assertTrue(body.closed)
        self.assertTrue(client.is_closed)
        self.assertEqual(len(chunks), 2)

    async def test_normal_thumbnail_is_preserved(self):
        import httpx
        from services import ig_meta
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"fixture-image", headers={"content-type": "image/png"})))
        with patch.object(ig_meta.httpx, "AsyncClient", return_value=client):
            self.assertEqual(await ig_meta.download_image("https://fixture/thumbnail"), (b"fixture-image", "image/png"))


class IntelligenceLockMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_idle_generation_locks_are_not_retained_and_active_lock_is_shared(self):
        from services import intelligence
        intelligence._GENERATION_LOCKS.clear()
        period = {"start": "2026-10-01", "end": "2026-10-19"}
        async with intelligence._generation_lock("tenant-a", period) as acquired:
            self.assertIsNone(acquired)
            self.assertEqual(len(intelligence._GENERATION_LOCKS), 1)
            active = intelligence._generation_lock("tenant-a", period)
            self.assertTrue(active.locked())
            self.assertIs(active, intelligence._generation_lock("tenant-a", period))
        del active
        import gc
        gc.collect()
        self.assertEqual(len(intelligence._GENERATION_LOCKS), 0)


class RefreshMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_orchestrator_serializes_sources_and_keeps_failure_isolation(self):
        from services import provider_refresh as refresh
        from fastapi import HTTPException
        events = []
        async def source(name, fail=False):
            async with sync_locks.guarded_sync(client_id="tenant-a", provider=name, connection_id=name):
                self.assertEqual(memory_budget._ACTIVE, 1)
                events.append(name)
                await asyncio.sleep(0)
                if fail:
                    raise RuntimeError("fixture failure")
                return {"ok": True}
        with (patch.object(sync_locks, "acquire_sync_lock", AsyncMock(return_value=True)),
              patch.object(sync_locks, "release_sync_lock", AsyncMock()),
              patch.object(refresh, "acquire_sync_lock", AsyncMock(return_value=True)),
              patch.object(refresh, "list_generic_connections", AsyncMock(return_value=[{"provider": "ga4"}, {"provider": "google_ads"}])),
              patch.object(refresh, "_refresh_ga4", new=lambda *args: source("ga4", True)),
              patch.object(refresh, "_refresh_google_ads", new=lambda *args: source("google_ads"))):
            with self.assertRaises(HTTPException) as error:
                await refresh.refresh_provider_data("tenant-a", "google", "2026-10-01", "2026-10-19")
        self.assertEqual(error.exception.status_code, 502)
        self.assertEqual(events, ["ga4", "google_ads"])
        self.assertEqual(memory_budget._ACTIVE, 0)


class RunnerMemoryTests(unittest.TestCase):
    def test_render_runner_pins_one_worker_even_with_web_concurrency_override(self):
        import os
        import run_api
        with patch.dict(os.environ, {"WEB_CONCURRENCY": "8"}), patch.object(run_api.uvicorn, "run") as run:
            run_api.main()
        self.assertEqual(run.call_args.kwargs["workers"], 1)
        self.assertFalse(run.call_args.kwargs["reload"])
