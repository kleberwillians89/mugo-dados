import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from server.services import tenant


class TenantIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_amalie_user_cannot_request_roove(self):
        async def membership_lookup(user_id, requested_client_id=None):
            self.assertEqual(user_id, "user-amalie")
            if requested_client_id != "amalie":
                raise PermissionError("Usuário sem acesso ao client_id informado")
            return "amalie"

        with (
            patch.object(tenant, "require_user_id", AsyncMock(return_value="user-amalie")),
            patch.object(tenant, "sb_get_client_id_for_user", membership_lookup),
        ):
            with self.assertRaises(HTTPException) as raised:
                await tenant.resolve_client_id("roove", "Bearer valid")

        self.assertEqual(raised.exception.status_code, 403)

    async def test_amalie_user_cannot_request_ruah(self):
        with (
            patch.object(tenant, "require_user_id", AsyncMock(return_value="user-amalie")),
            patch.object(
                tenant,
                "sb_get_client_id_for_user",
                AsyncMock(side_effect=PermissionError("Usuário sem acesso ao client_id informado")),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await tenant.resolve_client_id("ruah-parfums", "Bearer valid")

        self.assertEqual(raised.exception.status_code, 403)

    async def test_viewer_cannot_change_connection(self):
        memberships = [{"client_id": "amalie", "role": "viewer"}]
        with (
            patch.object(tenant, "require_user_id", AsyncMock(return_value="viewer-amalie")),
            patch.object(tenant, "resolve_client_id", AsyncMock(return_value="amalie")),
            patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=memberships)),
        ):
            with self.assertRaises(HTTPException) as raised:
                await tenant.require_client_role("amalie", "Bearer valid")

        self.assertEqual(raised.exception.status_code, 403)

    async def test_client_admin_can_change_own_connection(self):
        memberships = [{"client_id": "amalie", "role": "client_admin"}]
        with (
            patch.object(tenant, "require_user_id", AsyncMock(return_value="admin-amalie")),
            patch.object(tenant, "resolve_client_id", AsyncMock(return_value="amalie")),
            patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=memberships)),
        ):
            resolved = await tenant.require_client_role("amalie", "Bearer valid")

        self.assertEqual(resolved, "amalie")


if __name__ == "__main__":
    unittest.main()
