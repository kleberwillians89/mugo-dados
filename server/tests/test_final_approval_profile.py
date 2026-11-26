"""Perfil "Cliente — Aprovação Final": permissão própria, conferida no servidor, sem tirar nada de quem já tinha."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from services import team_access as ta
from services import tenant


class ProfileTests(unittest.TestCase):
    def test_preset_only_gives_final_approval(self):
        codes = ta.resolve_codes(status="active", preset="cliente_aprovacao", view_all=False, access_total=False)
        self.assertEqual(codes, {"final_approval.view", "final_approval.edit"})
        self.assertIn("Cliente — Aprovação Final", [p["label"] for p in ta.catalog_payload()["presets"]])

    def test_who_saw_calendar_keeps_approving(self):
        viewer = ta.resolve_codes(status="active", preset="visualizacao", view_all=True, access_total=False)
        self.assertTrue({"calendar.view", "final_approval.view", "final_approval.edit"} <= viewer)
        admin = ta.resolve_codes(status="active", preset="administrador", view_all=True, access_total=True)
        self.assertIn("final_approval.edit", admin)
        comercial = ta.resolve_codes(status="active", preset="comercial", view_all=False, access_total=False)
        self.assertNotIn("final_approval.view", comercial)
        self.assertEqual(ta.resolve_codes(status="inactive", preset="cliente_aprovacao", view_all=False, access_total=False), set())

    def test_routes_used_by_final_approval_are_checked(self):
        base = "/api/clients/roove/studio"
        self.assertEqual(ta.route_module("GET", f"{base}/approvals/pipeline"), ("final_approval", "final_approval.view"))
        self.assertEqual(ta.route_module("POST", f"{base}/calendar/items/abc/decision"), ("final_approval", "final_approval.edit"))
        self.assertEqual(ta.route_module("GET", f"{base}/calendar/items/abc/comments"), ("final_approval", "final_approval.view"))
        self.assertEqual(ta.route_module("POST", f"{base}/calendar/items/abc/comments"), ("final_approval", "final_approval.edit"))
        # O resto do Calendário continua exigindo o Calendário.
        self.assertEqual(ta.route_module("GET", f"{base}/calendar/items"), ("calendar", "calendar.view"))
        self.assertEqual(ta.route_module("POST", f"{base}/approvals"), ("calendar", "calendar.edit"))


class EnforcementTests(unittest.IsolatedAsyncioTestCase):
    async def check(self, codes, method, path):
        access = {"status": "active", "codes": codes}
        with patch("services.team_access.member_access", AsyncMock(return_value=access)), \
             patch("services.team_access.REQUEST_ROUTE") as route:
            route.get.return_value = (method, path)
            return await tenant._module_check("roove", "u1", role="viewer", member_route=True)

    async def test_approval_only_can_approve_but_not_open_calendar(self):
        only = {"final_approval.view", "final_approval.edit"}
        self.assertTrue(await self.check(only, "POST", "/api/clients/roove/studio/calendar/items/x/decision"))
        with self.assertRaises(HTTPException):
            await self.check(only, "GET", "/api/clients/roove/studio/calendar/items")

    async def test_view_without_edit_cannot_decide(self):
        with self.assertRaises(HTTPException) as caught:
            await self.check({"final_approval.view"}, "POST", "/api/clients/roove/studio/calendar/items/x/decision")
        self.assertIn("Aprovação Final", caught.exception.detail)


if __name__ == "__main__":
    unittest.main()
