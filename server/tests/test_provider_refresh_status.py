import sys
import time
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI, HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import provider_refresh_status as status, tenant
from routes import integrations


class RefreshStatusTests(unittest.IsolatedAsyncioTestCase):
    async def read(self, rows, provider="meta"):
        with patch.object(status, "sb_select", AsyncMock(return_value=rows)) as read, patch.dict(status.ads_sync._RECENT_SYNC_KEYS, {}, clear=True):
            result = await status.refresh_status("tenant-a", provider, "2026-10-01", "2026-10-19")
        self.assertEqual(read.await_args.kwargs["select"], "client_id,job_name,locked_until")
        self.assertEqual(read.await_args.kwargs["filters"]["client_id"], "eq.tenant-a")
        self.assertEqual(read.await_args.kwargs["limit"], 101)
        return result

    def lock(self, name, seconds=60, client="tenant-a"):
        return {"client_id": client, "job_name": name,
                "locked_until": (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()}

    async def test_existing_facade_and_source_locks_keep_background_work_blocked(self):
        for provider, key in [("meta", "sync:data_refresh:meta"), ("meta", "sync:meta_ads:conn"),
                              ("meta", "sync:meta_organic:conn"), ("google", "sync:ga4:property:1"),
                              ("google", "sync:google_ads:conn"), ("shopify", "sync:shopify:conn"),
                              ("fbits", "sync:fbits:conn"), ("fbits", "sync:data_refresh:fbits")]:
            with self.subTest(key=key):
                self.assertTrue((await self.read([self.lock(key)], provider))["running"])

    async def test_commerce_status_ignores_other_provider_tenant_and_expired_lease(self):
        for provider, foreign in [("shopify", "fbits"), ("fbits", "shopify")]:
            result = await self.read([self.lock(f"sync:{foreign}:conn"),
                self.lock(f"sync:{provider}:conn", client="tenant-b"),
                self.lock(f"sync:{provider}:conn", -1)], provider)
            self.assertFalse(result["running"])
            self.assertEqual(result["cooldown_seconds"], 0)

    async def test_cooldown_and_expired_or_foreign_locks_do_not_invent_running_work(self):
        result = await self.read([self.lock("refresh_cooldown:meta"), self.lock("sync:meta_ads:c", -1),
                                  self.lock("sync:meta_ads:c", client="tenant-b"), self.lock("sync:google_ads:c")])
        self.assertFalse(result["running"])
        self.assertGreater(result["cooldown_seconds"], 0)
        result = await self.read([])
        self.assertFalse(result["running"])
        self.assertEqual(result["cooldown_seconds"], 0)

    async def test_ads_existing_dedup_window_survives_browser_reload_without_cross_tenant_or_period(self):
        keys = {"tenant-a:conn:act_1:2026-10-01:2026-10-19": time.monotonic(),
                "tenant-b:conn:act_1:2026-10-01:2026-10-19": time.monotonic()}
        with patch.object(status, "sb_select", AsyncMock(return_value=[])), patch.dict(status.ads_sync._RECENT_SYNC_KEYS, keys, clear=True):
            result = await status.refresh_status("tenant-a", "meta", "2026-10-01", "2026-10-19")
            self.assertGreater(result["cooldown_seconds"], 290)
            other_period = await status.refresh_status("tenant-a", "meta", "2026-09-01", "2026-09-19")
            self.assertEqual(other_period["cooldown_seconds"], 0)
            other_client = await status.refresh_status("tenant-c", "meta", "2026-10-01", "2026-10-19")
            self.assertEqual(other_client["cooldown_seconds"], 0)

    async def test_unreadable_or_truncated_locks_never_certify_idle(self):
        for rows in [[self.lock("sync:meta_ads:c")] * 101, [{"client_id": "tenant-a", "job_name": "sync:meta_ads:c", "locked_until": "invalid"}]]:
            with self.assertRaises(HTTPException):
                await self.read(rows)
        with patch.object(status, "sb_select", AsyncMock(side_effect=RuntimeError("offline"))):
            with self.assertRaises(RuntimeError):
                await status.refresh_status("tenant-a", "meta", "2026-10-01", "2026-10-19")


class RefreshStatusAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_and_post_require_admin_and_the_same_tenant_before_work(self):
        app = FastAPI(); app.include_router(integrations.router)
        role = "viewer"
        async def membership(_uid, requested_client_id=None):
            if requested_client_id != "tenant-a": raise PermissionError("other tenant")
            return "tenant-a"
        with patch.object(tenant, "require_user_id", AsyncMock(return_value="user")), \
             patch.object(tenant, "sb_get_client_id_for_user", AsyncMock(side_effect=membership)), \
             patch.object(tenant, "sb_get_client_memberships", AsyncMock(side_effect=lambda _uid: [{"client_id": "tenant-a", "role": role}])), \
             patch("services.platform_admin.is_platform_admin", AsyncMock(return_value=False)), \
             patch.object(status, "refresh_status", AsyncMock(return_value={"running": False})) as read, \
             patch.object(integrations, "refresh_provider_data", AsyncMock(return_value={"ok": True})) as sync:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline") as client:
                period = {"start": "2026-10-01", "end": "2026-10-19"}
                for provider in ["meta", "google", "shopify", "fbits"]:
                    base = f"/api/clients/tenant-a/data-refresh/{provider}"
                    self.assertEqual((await client.get(base + "/status", params=period)).status_code, 403)
                    self.assertEqual((await client.post(base, json=period)).status_code, 403)
                read.assert_not_awaited(); sync.assert_not_awaited()
                role = "client_admin"
                self.assertEqual((await client.get("/api/clients/tenant-b/data-refresh/meta/status", params=period)).status_code, 403)
                self.assertEqual((await client.post("/api/clients/tenant-b/data-refresh/meta", json=period)).status_code, 403)
                read.assert_not_awaited(); sync.assert_not_awaited()
                self.assertEqual((await client.get("/api/clients/tenant-a/data-refresh/meta/status", params=period)).status_code, 200)
                sync.assert_not_awaited()
                self.assertEqual((await client.post("/api/clients/tenant-a/data-refresh/meta", json=period)).status_code, 200)
