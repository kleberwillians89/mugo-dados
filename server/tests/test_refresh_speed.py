"""Atualização mais rápida: trava com lease renovada, token e empresa em cache curto."""

import asyncio
import base64
import json
import os
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import auth, sync_locks, tenant  # noqa: E402


def jwt(exp):
    body = base64.urlsafe_b64encode(json.dumps({"sub": "u1", "exp": exp}).encode()).decode().rstrip("=")
    return f"h.{body}.sig"


class LeaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_guarded_sync_takes_short_lease_renews_and_releases(self):
        acquire = AsyncMock(return_value=True)
        release = AsyncMock()
        renew = AsyncMock(side_effect=["t2", "t3", "t4", "t5"])
        with patch.object(sync_locks, "acquire_sync_lock", acquire), \
             patch.object(sync_locks, "release_sync_lock", release), \
             patch.object(sync_locks, "peek_sync_lock", AsyncMock(return_value={"updated_at": "t1"})), \
             patch.object(sync_locks, "_renew_lease", renew), \
             patch.object(sync_locks, "HEARTBEAT_SECONDS", 0.01):
            async with sync_locks.guarded_sync(client_id="c", provider="data_refresh", connection_id="meta"):
                await asyncio.sleep(0.035)
        self.assertEqual(acquire.await_args.args[2], sync_locks.LEASE_SECONDS)
        self.assertLessEqual(sync_locks.LEASE_SECONDS, 90)
        self.assertGreaterEqual(renew.await_count, 2)
        self.assertEqual(renew.await_args_list[0].args, ("c", "sync:data_refresh:meta", "t1"))
        self.assertEqual(renew.await_args_list[1].args[2], "t2")  # usa o token novo
        release.assert_awaited_once_with("c", "sync:data_refresh:meta")

    async def test_heartbeat_stops_when_lease_was_taken_over(self):
        renew = AsyncMock(return_value=None)
        with patch.object(sync_locks, "peek_sync_lock", AsyncMock(return_value={"updated_at": "t1"})), \
             patch.object(sync_locks, "_renew_lease", renew), patch.object(sync_locks, "HEARTBEAT_SECONDS", 0.001):
            await asyncio.wait_for(sync_locks._heartbeat("c", "sync:x"), 1)
        renew.assert_awaited_once()

    async def test_renew_only_matches_own_token(self):
        update = AsyncMock(return_value=[])
        with patch.object(sync_locks, "sb_update", update):
            self.assertIsNone(await sync_locks._renew_lease("c", "sync:x", "2026-10-27T18:00:00+00:00"))
        filters = update.await_args.kwargs["filters"]
        self.assertEqual(filters, {"client_id": "eq.c", "job_name": "eq.sync:x", "updated_at": "eq.2026-10-27T18:00:00+00:00"})
        self.assertEqual(set(update.await_args.kwargs["patch"]), {"locked_until"})

    async def test_sync_body_error_still_releases(self):
        release = AsyncMock()
        with patch.object(sync_locks, "acquire_sync_lock", AsyncMock(return_value=True)), \
             patch.object(sync_locks, "release_sync_lock", release), \
             patch.object(sync_locks, "peek_sync_lock", AsyncMock(return_value=None)):
            with self.assertRaises(RuntimeError):
                async with sync_locks.guarded_sync(client_id="c", provider="data_refresh", connection_id="meta"):
                    raise RuntimeError("boom")
        release.assert_awaited_once()


class TokenCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        auth._token_cache.clear()

    def client(self, calls):
        response = MagicMock(status_code=200)
        response.json.return_value = {"id": "u1"}

        async def get(*a, **k):
            calls.append(1)
            return response

        client = MagicMock()
        client.get = get
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        return client

    async def run_twice(self, token):
        calls = []
        env = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_ANON_KEY": "a" * 30}
        with patch.dict(os.environ, env), patch.object(auth.httpx, "AsyncClient", return_value=self.client(calls)):
            first = await auth.get_user_id_from_bearer.__wrapped__(f"Bearer {token}") if hasattr(auth.get_user_id_from_bearer, "__wrapped__") else await auth.get_user_id_from_bearer(f"Bearer {token}")
            second = await auth.get_user_id_from_bearer.__wrapped__(f"Bearer {token}") if hasattr(auth.get_user_id_from_bearer, "__wrapped__") else await auth.get_user_id_from_bearer(f"Bearer {token}")
        return first, second, len(calls)

    async def test_valid_token_is_checked_once_per_minute(self):
        token = jwt(time.time() + 3600)
        first, second, calls = await self.run_twice(token)
        self.assertEqual((first, second, calls), ("u1", "u1", 1))
        self.assertNotIn(token, json.dumps(list(auth._token_cache)))

    async def test_cache_never_outlives_token(self):
        first, second, calls = await self.run_twice(jwt(time.time() - 5))
        self.assertEqual(calls, 2)
        self.assertEqual(auth._token_cache, {})

    async def test_cache_entry_expires(self):
        token = jwt(time.time() + 3600)
        auth._remember_user_id(token, "u1")
        key = auth._token_cache_key(token)
        auth._token_cache[key] = ("u1", time.time() - 1)
        self.assertIsNone(auth._cached_user_id(token))


class ClientExistsCacheTests(unittest.TestCase):
    def test_company_existence_is_cached_briefly(self):
        tenant._known_clients.clear()
        self.assertFalse(tenant._client_known("c1"))
        tenant._remember_client("c1")
        self.assertTrue(tenant._client_known("c1"))
        tenant._known_clients["c1"] = time.monotonic() - 1
        self.assertFalse(tenant._client_known("c1"))


if __name__ == "__main__":
    unittest.main()


class ConnectionReuseTests(unittest.IsolatedAsyncioTestCase):
    async def test_supabase_requests_reuse_one_connection_pool(self):
        from services import ig_supabase

        created = []

        class FakeClient:
            def __init__(self, **kwargs):
                created.append(kwargs)
                self.is_closed = False

            async def request(self, method, url, **kwargs):
                response = MagicMock(status_code=200, text="[]")
                response.json.return_value = []
                return response

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return None

        ig_supabase._SHARED.clear()
        env = {"SUPABASE_URL": "https://fixture.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "k" * 40}
        with patch.dict(os.environ, env), patch.object(ig_supabase.httpx, "AsyncClient", FakeClient):
            for _ in range(3):
                await ig_supabase._request("GET", "/clients")
        ig_supabase._SHARED.clear()
        self.assertEqual(len(created), 1)
        self.assertIn("limits", created[0])
