"""Usuários e permissões por módulo (modelo CRM): cálculo, rota → módulo, guarda de tenant e regras de concessão."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from services import team_access as ta
from services import team_admin, tenant
from services.client_access import AccessError


class ResolveTests(unittest.TestCase):
    def test_order_inactive_total_viewall_overrides(self):
        self.assertEqual(ta.resolve_codes(status="inactive", preset="administrador", view_all=True, access_total=True), set())
        # Acesso total = tudo menos os módulos liberados pela Mugô (Social Media).
        self.assertEqual(ta.resolve_codes(status="active", preset="personalizado", view_all=False, access_total=True), ta.TOTAL_CODES)
        seen = ta.resolve_codes(status="active", preset="personalizado", view_all=True, access_total=False)
        self.assertIn("creators.view", seen)
        self.assertNotIn("team.view", seen)
        self.assertNotIn("creators.edit", seen)
        custom = ta.resolve_codes(status="active", preset="comercial", view_all=False, access_total=False,
                                  overrides=[("creators.view", True), ("tasks.edit", False)])
        self.assertIn("creators.view", custom)
        self.assertNotIn("tasks.edit", custom)

    def test_overrides_are_diff_from_preset(self):
        wanted = ta.base_codes("comercial") | {"creators.view"}
        wanted.discard("tasks.edit")
        self.assertEqual(ta.overrides_for("comercial", False, wanted), [("creators.view", True), ("tasks.edit", False)])

    def test_legacy_roles(self):
        self.assertTrue(ta.legacy_flags("client_admin")["access_total"])
        self.assertEqual(ta.legacy_flags("viewer"), {"preset": "visualizacao", "view_all": True, "access_total": False})
        self.assertEqual(ta.role_for(True), "client_admin")
        self.assertEqual(ta.role_for(False), "viewer")


class RouteModuleTests(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(ta.route_module("GET", "/api/clients/roove/creators"), ("creators", "creators.view"))
        self.assertEqual(ta.route_module("DELETE", "/api/clients/roove/creators/abc"), ("creators", "creators.edit"))
        self.assertEqual(ta.route_module("POST", "/api/clients/roove/studio/engagement/rules"), ("engagement", "engagement.edit"))
        self.assertEqual(ta.route_module("GET", "/api/team/members"), ("team", "team.view"))
        self.assertIsNone(ta.route_module("GET", "/api/team/me"))
        self.assertIsNone(ta.route_module("GET", "/api/clients/roove/studio/brand-profile"))  # leitura compartilhada
        self.assertEqual(ta.route_module("PUT", "/api/clients/roove/studio/brand-profile"), ("brand_ai", "brand_ai.edit"))
        self.assertIsNone(ta.route_module("GET", "/api/dashboard/summary"))

    def test_social_media_and_calendar_keep_independent_permissions(self):
        self.assertEqual(
            ta.route_module("GET", "/api/clients/roove/studio/matrix"),
            ("social_media", "social_media.view"),
        )
        self.assertEqual(
            ta.route_module("POST", "/api/clients/roove/studio/matrix"),
            ("social_media", "social_media.edit"),
        )
        self.assertEqual(
            ta.route_module("GET", "/api/clients/roove/studio/calendar"),
            ("calendar", "calendar.view"),
        )
        self.assertEqual(
            ta.route_module("POST", "/api/clients/roove/studio/calendar"),
            ("calendar", "calendar.edit"),
        )


def access(codes, *, status="active", total=False, role="viewer"):
    return {"role": role, "status": status, "preset": "personalizado", "view_all": False, "access_total": total,
            "overrides": [], "codes": set(codes)}


class TenantGuardTests(unittest.IsolatedAsyncioTestCase):
    def guards(self, member, role="viewer"):
        return [patch.object(tenant, "require_user_id", AsyncMock(return_value="u1")),
                patch.object(tenant, "resolve_client_id", AsyncMock(return_value="roove")),
                patch("services.platform_admin.is_platform_admin", AsyncMock(return_value=False)),
                patch.object(tenant, "_has_agency_admin_membership", AsyncMock(return_value=False)),
                patch.object(tenant, "_client_role", AsyncMock(return_value=role)),
                patch.object(ta, "_member_access", AsyncMock(return_value=member))]

    async def call(self, fn, member, route, role="viewer", **kw):
        from contextlib import ExitStack
        token = ta.REQUEST_ROUTE.set(route)
        try:
            with ExitStack() as stack:
                for p in self.guards(member, role):
                    stack.enter_context(p)
                return await fn("roove", "Bearer x", **kw)
        finally:
            ta.REQUEST_ROUTE.reset(token)

    async def test_viewer_with_module_edit_can_write_that_module(self):
        out = await self.call(tenant.require_client_role, access({"creators.view", "creators.edit"}),
                              ("DELETE", "/api/clients/roove/creators/x"), allowed_roles=("agency_admin", "client_admin"))
        self.assertEqual(out, "roove")

    async def test_module_edit_does_not_open_other_writes(self):
        with self.assertRaises(HTTPException) as raised:
            await self.call(tenant.require_client_role, access({"creators.edit"}),
                            ("POST", "/api/clients/roove/studio/engagement/rules"), allowed_roles=("agency_admin", "client_admin"))
        self.assertEqual(raised.exception.status_code, 403)
        with self.assertRaises(HTTPException):  # rota fora de módulo: vale o papel
            await self.call(tenant.require_client_role, access(ta.ALL_CODES), ("POST", "/api/ads/sync"),
                            allowed_roles=("agency_admin", "client_admin"))

    async def test_agency_only_route_stays_agency_only(self):
        with self.assertRaises(HTTPException):
            await self.call(tenant.require_client_role, access({"creators.edit"}), ("POST", "/api/clients/roove/creators/search"),
                            allowed_roles=("agency_admin",))

    async def test_read_requires_module_view(self):
        with self.assertRaises(HTTPException) as raised:
            await self.call(tenant.require_client_read, access({"meta.view"}), ("GET", "/api/clients/roove/creators"))
        self.assertIn("Criadores", raised.exception.detail)
        self.assertEqual(await self.call(tenant.require_client_read, access({"creators.view"}), ("GET", "/api/clients/roove/creators")), "roove")

    async def test_read_fails_closed_when_module_authorization_cannot_be_verified(self):
        with patch.object(tenant, "_module_check", AsyncMock(side_effect=RuntimeError("permissions unavailable"))):
            with self.assertRaises(HTTPException) as raised:
                await self.call(tenant.require_client_read, access({"creators.view"}),
                                ("GET", "/api/clients/roove/creators"))
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("verificar sua permissão", raised.exception.detail)

    async def test_inactive_is_blocked_everywhere(self):
        with self.assertRaises(HTTPException) as raised:
            await self.call(tenant.require_client_read, access(ta.ALL_CODES, status="inactive"), ("GET", "/api/dashboard/summary"))
        self.assertIn("desativado", raised.exception.detail)

    async def test_legacy_admin_keeps_access(self):
        out = await self.call(tenant.require_client_role, access(ta.ALL_CODES, total=True, role="client_admin"),
                              ("POST", "/api/ads/sync"), role="client_admin", allowed_roles=("agency_admin", "client_admin"))
        self.assertEqual(out, "roove")


class GrantRuleTests(unittest.IsolatedAsyncioTestCase):
    ACTOR = {"user_id": "boss", "team": False, "access_total": False, "codes": {"creators.view", "creators.edit", "team.view", "team.edit"}}

    def test_username_becomes_internal_login(self):
        self.assertEqual(team_admin.login_email("Joao.Vendas"), ("joao.vendas@acesso.mugo.ag", "joao.vendas"))
        self.assertEqual(team_admin.display_login("joao.vendas@acesso.mugo.ag", None), "joao.vendas")
        with self.assertRaises(AccessError):
            team_admin.login_email("a b")

    async def test_cannot_grant_what_actor_lacks(self):
        with self.assertRaises(AccessError) as raised:
            await team_admin.create_member(client_id="roove", actor=self.ACTOR, name="Ana", login="ana.roove",
                                           password="12345678", preset="personalizado", view_all=False,
                                           access_total=False, codes=["meta.view"])
        self.assertEqual(raised.exception.code, "TEAM_GRANT_NOT_ALLOWED")
        with self.assertRaises(AccessError):
            await team_admin.create_member(client_id="roove", actor=self.ACTOR, name="Ana", login="ana.roove",
                                           password="12345678", preset="administrador", view_all=True,
                                           access_total=True, codes=None)

    async def test_create_with_username_saves_membership_and_overrides(self):
        insert, upsert = AsyncMock(), AsyncMock()
        with patch.object(team_admin, "find_auth_user_by_email", AsyncMock(return_value=None)), \
             patch.object(team_admin, "_create_auth_user", AsyncMock(return_value={"id": "new"})) as create, \
             patch.object(team_admin, "sb_insert", insert), patch.object(team_admin, "sb_upsert", upsert), \
             patch.object(team_admin, "sb_delete", AsyncMock()), redirect_stdout(io.StringIO()):
            out = await team_admin.create_member(client_id="roove", actor=self.ACTOR, name="Ana", login="ana.roove",
                                                 password="12345678", preset="personalizado", view_all=False,
                                                 access_total=False, codes=["creators.view", "creators.edit"])
        self.assertEqual(out["login"], "ana.roove")
        self.assertEqual(create.await_args.kwargs["email"], "ana.roove@acesso.mugo.ag")
        row = insert.await_args.args[1]
        self.assertEqual((row["role"], row["permission_preset"], row["username"], row["status"]), ("viewer", "personalizado", "ana.roove", "active"))
        self.assertEqual({r["permission_code"] for r in upsert.await_args.args[1]}, {"creators.view", "creators.edit"})

    async def test_taken_username_is_rejected(self):
        with patch.object(team_admin, "find_auth_user_by_email", AsyncMock(return_value={"id": "x"})):
            with self.assertRaises(AccessError) as raised:
                await team_admin.create_member(client_id="roove", actor={**self.ACTOR, "team": True}, name="", login="ana.roove",
                                               password="12345678", preset="visualizacao", view_all=True, access_total=False, codes=None)
        self.assertEqual(raised.exception.code, "TEAM_USERNAME_TAKEN")

    async def test_cannot_edit_self_or_mugo_team(self):
        with self.assertRaises(AccessError) as raised:
            await team_admin.set_status(client_id="roove", actor=self.ACTOR, user_id="boss", status="inactive")
        self.assertEqual(raised.exception.code, "TEAM_SELF_EDIT")
        with patch.object(team_admin, "_members", AsyncMock(return_value=[{"role": "agency_admin"}])):
            with self.assertRaises(AccessError) as raised:
                await team_admin.set_status(client_id="roove", actor=self.ACTOR, user_id="mugo", status="inactive")
        self.assertEqual(raised.exception.code, "ACCESS_ROLE_NOT_ALLOWED")


if __name__ == "__main__":
    unittest.main()
