import asyncio
import os
from unittest.mock import patch

import httpx

from services import ig_supabase


def test_same_loop_reuses_one_client_and_new_loop_gets_its_own():
    created = []

    def handler(request):
        return httpx.Response(200, json=[{"ok": True}])

    class Counting(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            created.append(self)
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    env = {"SUPABASE_URL": "https://exemplo.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "x" * 40}
    with patch.dict(os.environ, env), patch.object(ig_supabase, "_REAL_ASYNC_CLIENT", Counting), \
            patch.object(ig_supabase.httpx, "AsyncClient", Counting), patch.dict(ig_supabase._SHARED_CLIENTS, clear=True):
        async def three_reads():
            for _ in range(3):
                assert await ig_supabase.sb_select("clients", limit=1) == [{"ok": True}]

        asyncio.run(three_reads())
        assert len(created) == 1  # três consultas, uma conexão
        asyncio.run(three_reads())
        assert len(created) == 2  # outro event loop (ex.: outro job) tem o seu


def test_patched_client_keeps_old_behaviour():
    with patch.object(ig_supabase.httpx, "AsyncClient", object):
        assert ig_supabase._shared_client() is None
