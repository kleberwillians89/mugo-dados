import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as backend
from routes import customers, goals, intelligence, fbits, google
from services import tenant


class FinalViewerTenantMatrixTests(unittest.IsolatedAsyncioTestCase):
    async def check(self, path, module, operation):
        async def membership(user, requested_client_id=None):
            if requested_client_id != "tenant-a":
                raise PermissionError("Usuário sem acesso ao client_id informado")
            return "tenant-a"

        with (
            patch.object(tenant, "get_user_id_from_bearer", AsyncMock(return_value="viewer-a")),
            patch.object(tenant, "sb_get_client_id_for_user", AsyncMock(side_effect=membership)),
            patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=[{"client_id": "tenant-a", "role": "viewer"}])),
            patch("services.platform_admin.is_platform_admin", AsyncMock(return_value=False)),
            patch.object(backend, "_validated_connection_id", AsyncMock(return_value=None)),
            patch.object(google, "resolve_google_ads_context", AsyncMock(return_value={})),
            patch.object(google, "resolve_ga4_connection_context", AsyncMock(return_value=SimpleNamespace(client_id="tenant-a", property_id="property-a", connection_id=None, auth_mode="oauth"))),
            patch.object(module, operation, AsyncMock(return_value={"ok": True})) as read,
            redirect_stdout(io.StringIO()),
        ):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app), base_url="http://test") as client:
                for cid, status in (("tenant-a", 200), ("tenant-b", 403)):
                    with self.subTest(client_id=cid):
                        read.reset_mock()
                        response = await client.get(path.replace("{cid}", cid), params={"client_id": cid}, headers={"Authorization": "Bearer test"})
                        self.assertEqual(response.status_code, status, response.text)
                        if status == 403:
                            read.assert_not_awaited()
                        else:
                            self.assertTrue(read.await_count)
                            call = read.await_args
                            self.assertEqual(call.kwargs.get("client_id") or call.args[0], "tenant-a")

    async def test_customers(self):
        await self.check("/api/customers", customers, "list_customers")

    async def test_goals(self):
        await self.check("/api/clients/{cid}/goals", goals, "list_goals")

    async def test_intelligence(self):
        await self.check("/api/intelligence/context", intelligence, "calculate_intelligence_snapshot")

    async def test_ecommerce(self):
        await self.check("/api/fbits/dashboard", fbits, "build_fbits_summary")

    async def test_meta(self):
        await self.check("/api/dashboard/organic", backend, "get_dashboard")

    async def test_google_ads(self):
        await self.check("/api/google/ads/report", google, "build_google_ads_report")

    async def test_google_analytics(self):
        await self.check("/api/google/ga4/report", google, "build_ga4_report")
