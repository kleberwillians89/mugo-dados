import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from routes import platform_admin as routes
from routes import meta_legacy
from services import platform_admin, tenant


class PlatformAdminAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_unauthenticated_platform_request_returns_401(self):
        os.environ["ALLOW_NO_AUTH"] = "false"
        with patch.object(tenant, "get_user_id_from_bearer", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as raised:
                await platform_admin.require_platform_admin(None)
        self.assertEqual(raised.exception.status_code, 401)

    async def test_common_user_returns_403(self):
        with (
            patch.object(platform_admin, "require_user_id", AsyncMock(return_value="common")),
            patch.object(platform_admin, "is_platform_admin", AsyncMock(return_value=False)),
        ):
            with self.assertRaises(HTTPException) as raised:
                await platform_admin.require_platform_admin("Bearer token")
        self.assertEqual(raised.exception.status_code, 403)

    async def test_master_user_is_authorized_without_membership(self):
        with (
            patch.object(platform_admin, "require_user_id", AsyncMock(return_value="master")),
            patch.object(platform_admin, "is_platform_admin", AsyncMock(return_value=True)),
        ):
            self.assertEqual(
                await platform_admin.require_platform_admin("Bearer token"), "master"
            )

    async def test_platform_me_does_not_depend_on_email_or_metadata(self):
        with (
            patch.object(routes, "require_user_id", AsyncMock(return_value="uid")),
            patch.object(routes, "is_platform_admin", AsyncMock(return_value=True)),
        ):
            result = await routes.platform_me("Bearer token")
        self.assertTrue(result["is_platform_admin"])


class PlatformCompanyTests(unittest.IsolatedAsyncioTestCase):
    async def test_creation_uses_atomic_database_rpc_then_invites_owner(self):
        created = {
            "client": {"id": "company-1", "name": "Acme"},
            "invitation": {"id": "invite-1", "role": "owner"},
        }
        rpc = AsyncMock(return_value=created)
        invite = AsyncMock(return_value=None)
        with (
            patch.object(platform_admin, "sb_rpc", rpc),
            patch.object(platform_admin, "send_supabase_invite", invite),
        ):
            result = await platform_admin.create_platform_company(
                "master", {"name": "Acme", "responsible_email": "owner@acme.test"}
            )
        self.assertTrue(result["ok"])
        self.assertEqual(rpc.await_args.args[0], "create_platform_company")
        self.assertEqual(invite.await_args.kwargs["role"], "owner")

    async def test_invite_failure_compensates_without_orphan_company(self):
        rpc = AsyncMock(
            side_effect=[
                {"client": {"id": "company-1"}, "invitation": {"id": "invite-1"}},
                True,
            ]
        )
        with (
            patch.object(platform_admin, "sb_rpc", rpc),
            patch.object(
                platform_admin,
                "send_supabase_invite",
                AsyncMock(side_effect=RuntimeError("invite failed")),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "invite failed"):
                await platform_admin.create_platform_company(
                    "master", {"name": "Acme", "responsible_email": "owner@acme.test"}
                )
        self.assertEqual(rpc.await_args_list[1].args[0], "rollback_platform_company_creation")

    async def test_common_user_cannot_use_legacy_post_clients(self):
        with patch(
            "services.platform_admin.require_platform_admin",
            AsyncMock(side_effect=HTTPException(status_code=403, detail="denied")),
        ):
            with self.assertRaises(HTTPException) as raised:
                await meta_legacy.api_create_client(
                    {"name": "Acme", "responsible_email": "a@b.test"}, "Bearer token"
                )
        self.assertEqual(raised.exception.status_code, 403)

    async def test_company_list_is_global_only_after_route_guard(self):
        with (
            patch.object(routes, "require_platform_admin", AsyncMock(return_value="master")),
            patch.object(
                routes,
                "list_platform_companies",
                AsyncMock(return_value={"ok": True, "companies": [{"id": "a"}, {"id": "b"}]}),
            ),
        ):
            result = await routes.platform_companies("Bearer token")
        self.assertEqual(len(result["companies"]), 2)

    async def test_support_access_is_explicit_and_audited(self):
        rpc = AsyncMock(return_value=True)
        with (
            patch.object(routes, "require_platform_admin", AsyncMock(return_value="master")),
            patch.object(routes, "sb_select", AsyncMock(return_value=[{"id": "company-1"}])),
            patch.object(routes, "sb_rpc", rpc),
        ):
            result = await routes.platform_open_company("company-1", "Bearer token")
        self.assertTrue(result["ok"])
        self.assertEqual(rpc.await_args.args[0], "audit_platform_company_access")

    async def test_platform_admin_updates_company_with_audit(self):
        with (
            patch.object(
                platform_admin,
                "sb_update",
                AsyncMock(return_value=[{"id": "company-1", "status": "inactive"}]),
            ),
            patch.object(platform_admin, "sb_insert", AsyncMock(return_value={"ok": True})) as audit,
        ):
            result = await platform_admin.update_platform_company(
                "master", "company-1", {"status": "inactive"}
            )
        self.assertEqual(result["company"]["status"], "inactive")
        self.assertEqual(audit.await_args.args[0], "platform_audit_events")


class PlatformMigrationContractTests(unittest.TestCase):
    def setUp(self):
        self.sql = (
            Path(__file__).parents[2]
            / "supabase/migrations/20260801_000020_platform_admin_companies.sql"
        ).read_text()

    def test_migration_does_not_hardcode_an_administrator_identity(self):
        lowered = self.sql.lower()
        self.assertNotIn("insert into public.platform_admins", lowered)
        self.assertIn("concedido explicitamente", lowered)

    def test_rls_has_no_self_elevation_write_policy(self):
        lowered = self.sql.lower()
        self.assertIn("enable row level security", lowered)
        self.assertNotIn("platform_admins_insert", lowered)
        self.assertIn("revoke all on public.platform_admins", lowered)

    def test_creation_and_rollback_are_service_role_only(self):
        lowered = self.sql.lower()
        self.assertIn("create_platform_company", lowered)
        self.assertIn("rollback_platform_company_creation", lowered)
        self.assertIn("grant execute", lowered)
        self.assertIn("to service_role", lowered)


if __name__ == "__main__":
    unittest.main()
