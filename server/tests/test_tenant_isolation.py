import unittest
import os
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from server.services import tenant


class TenantIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_unauthenticated_user_is_rejected(self):
        os.environ["ALLOW_NO_AUTH"] = "false"
        with patch.object(tenant, "get_user_id_from_bearer", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as raised:
                await tenant.require_user_id(None)
        self.assertEqual(raised.exception.status_code, 401)

    async def test_amalie_user_cannot_request_roove(self):
        async def membership_lookup(user_id, requested_client_id=None):
            self.assertEqual(user_id, "user-amalie")
            if requested_client_id != "amalie":
                raise PermissionError("Usuário sem acesso ao client_id informado")
            return "amalie"

        with (
            patch.object(tenant, "require_user_id", AsyncMock(return_value="user-amalie")),
            patch.object(tenant, "sb_get_client_id_for_user", membership_lookup),
            patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=[{"client_id": "amalie", "role": "client_admin"}])),
            patch("server.services.platform_admin.is_platform_admin", AsyncMock(return_value=False)),
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
            patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=[{"client_id": "amalie", "role": "client_admin"}])),
            patch("server.services.platform_admin.is_platform_admin", AsyncMock(return_value=False)),
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
            patch("server.services.platform_admin.is_platform_admin", AsyncMock(return_value=False)),
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
            patch("server.services.platform_admin.is_platform_admin", AsyncMock(return_value=False)),
        ):
            resolved = await tenant.require_client_role("amalie", "Bearer valid")

        self.assertEqual(resolved, "amalie")

    async def test_owner_can_manage_own_company(self):
        memberships = [{"client_id": "amalie", "role": "owner"}]
        with (
            patch.object(tenant, "require_user_id", AsyncMock(return_value="owner-amalie")),
            patch.object(tenant, "resolve_client_id", AsyncMock(return_value="amalie")),
            patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=memberships)),
            patch("server.services.platform_admin.is_platform_admin", AsyncMock(return_value=False)),
        ):
            resolved = await tenant.require_client_manage("amalie", "Bearer valid")
        self.assertEqual(resolved, "amalie")

    async def test_platform_admin_can_manage_explicit_company_without_membership(self):
        with (
            patch.object(tenant, "require_user_id", AsyncMock(return_value="platform-user")),
            patch.object(tenant, "resolve_client_id", AsyncMock(return_value="roove")),
            patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=[])),
            patch("server.services.platform_admin.is_platform_admin", AsyncMock(return_value=True)),
        ):
            resolved = await tenant.require_client_manage("roove", "Bearer valid")
        self.assertEqual(resolved, "roove")

    async def test_platform_admin_oauth_state_can_access_explicit_company(self):
        with (
            patch(
                "server.services.platform_admin.is_platform_admin",
                AsyncMock(return_value=True),
            ),
            patch.object(
                tenant,
                "sb_select",
                AsyncMock(return_value=[{"id": "roove"}]),
                create=True,
            ),
            patch(
                "server.services.ig_supabase.sb_select",
                AsyncMock(return_value=[{"id": "roove"}]),
            ),
        ):
            resolved = await tenant.require_user_client_access(
                "platform-user",
                "roove",
            )
        self.assertEqual(resolved, "roove")

    async def test_platform_admin_requires_explicit_tenant(self):
        with (
            patch.object(tenant, "require_user_id", AsyncMock(return_value="platform-user")),
            patch("server.services.platform_admin.is_platform_admin", AsyncMock(return_value=True)),
        ):
            with self.assertRaises(HTTPException) as raised:
                await tenant.resolve_client_id(None, "Bearer valid")
        self.assertEqual(raised.exception.status_code, 400)

    async def test_read_permission_does_not_require_mutation_role(self):
        with patch.object(tenant, "resolve_client_id", AsyncMock(return_value="amalie")):
            resolved = await tenant.require_client_read("amalie", "Bearer valid")
        self.assertEqual(resolved, "amalie")

    async def test_agency_admin_can_resolve_explicit_company_without_per_client_membership(self):
        # Papel agency_admin em QUALQUER empresa (não necessariamente a
        # solicitada) deve bastar — equipe da agência não deve precisar de
        # membership por cliente para acessar empresas autorizadas.
        memberships = [{"client_id": "outra-empresa", "role": "agency_admin"}]
        with (
            patch.object(tenant, "require_user_id", AsyncMock(return_value="agency-user")),
            patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=memberships)),
            patch.object(tenant, "sb_select", AsyncMock(return_value=[{"id": "amalie"}]), create=True),
            patch("server.services.ig_supabase.sb_select", AsyncMock(return_value=[{"id": "amalie"}])),
            patch("server.services.platform_admin.is_platform_admin", AsyncMock(return_value=False)),
        ):
            resolved = await tenant.resolve_client_id("amalie", "Bearer valid")
        self.assertEqual(resolved, "amalie")

    async def test_agency_admin_still_requires_explicit_client_id(self):
        memberships = [{"client_id": "outra-empresa", "role": "agency_admin"}]
        with (
            patch.object(tenant, "require_user_id", AsyncMock(return_value="agency-user")),
            patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=memberships)),
            patch("server.services.platform_admin.is_platform_admin", AsyncMock(return_value=False)),
        ):
            with self.assertRaises(HTTPException) as raised:
                await tenant.resolve_client_id(None, "Bearer valid")
        self.assertEqual(raised.exception.status_code, 400)

    async def test_agency_admin_can_manage_company_without_per_client_membership(self):
        memberships = [{"client_id": "outra-empresa", "role": "agency_admin"}]
        with (
            patch.object(tenant, "require_user_id", AsyncMock(return_value="agency-user")),
            patch.object(tenant, "resolve_client_id", AsyncMock(return_value="amalie")),
            patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=memberships)),
            patch("server.services.platform_admin.is_platform_admin", AsyncMock(return_value=False)),
        ):
            resolved = await tenant.require_client_manage("amalie", "Bearer valid")
        self.assertEqual(resolved, "amalie")

    async def test_plain_client_admin_membership_does_not_grant_cross_tenant_access(self):
        # Sem papel agency_admin em nenhuma empresa, o isolamento permanece.
        memberships = [{"client_id": "amalie", "role": "client_admin"}]
        with (
            patch.object(tenant, "require_user_id", AsyncMock(return_value="user-amalie")),
            patch.object(
                tenant,
                "sb_get_client_id_for_user",
                AsyncMock(side_effect=PermissionError("Usuário sem acesso ao client_id informado")),
            ),
            patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=memberships)),
            patch("server.services.platform_admin.is_platform_admin", AsyncMock(return_value=False)),
        ):
            with self.assertRaises(HTTPException) as raised:
                await tenant.resolve_client_id("roove", "Bearer valid")
        self.assertEqual(raised.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
