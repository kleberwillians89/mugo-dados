"""Briefing integrado, PR 1: uma pessoa = uma conta. Vincular nunca cria conta nem troca senha (caso Liliu na M2)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

from services import team_admin
from services.client_access import AccessError

LILIU = "aaaaaaaa-1111-2222-3333-444444444444"
CLIENT_USER = "bbbbbbbb-1111-2222-3333-444444444444"
TEAM = {"user_id": "admin-mugo", "team": True, "access_total": True, "codes": set()}
CLIENT_ADMIN = {"user_id": "admin-m2", "team": False, "access_total": True, "codes": set()}


class Harness(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.admin_calls = []
        self.inserts = []
        self.deletes = []
        self.members = {"m2": []}  # client_id -> rows
        self.internal = {LILIU}
        self.other_memberships = {LILIU: ["mugo"], CLIENT_USER: ["ruah"]}
        self.auth = {LILIU: {"id": LILIU, "email": "liliu@mugo.ag", "user_metadata": {"name": "Liliu"}},
                     CLIENT_USER: {"id": CLIENT_USER, "email": "ana@ruah.com", "user_metadata": {"name": "Ana"}}}

    async def admin_request(self, method, path, json=None, params=None):
        self.admin_calls.append({"method": method, "path": path, "json": json})
        if method == "GET" and path == "/users":
            return {"users": list(self.auth.values())}
        if method == "GET" and path.startswith("/users/"):
            uid = path.split("/")[-1]
            if uid not in self.auth:
                raise AccessError("ACCESS_ADMIN_API_FAILED", "x", status_code=404)
            return self.auth[uid]
        return {}

    async def act(self, coro_factory):
        async def members(client_id, user_id=None):
            rows = self.members.get(client_id, [])
            return [r for r in rows if not user_id or r["user_id"] == user_id]

        async def internal_ids(rows):
            return {r["user_id"] for r in rows if r["user_id"] in self.internal}

        async def membership(client_id, user_id):
            return next((r for r in self.members.get(client_id, []) if r["user_id"] == user_id), None)

        async def insert(table, row, **_):
            self.inserts.append((table, row))

        async def delete(table, filters=None, **_):
            self.deletes.append((table, filters))
            return [{}]

        async def shared(user_id, client_id):
            return any(c != client_id for c in self.other_memberships.get(user_id, []))

        with ExitStack() as stack:
            stack.enter_context(patch.object(team_admin, "_admin_request", self.admin_request))
            stack.enter_context(patch.object(team_admin, "_members", members))
            stack.enter_context(patch.object(team_admin, "_internal_team_user_ids", internal_ids))
            stack.enter_context(patch.object(team_admin, "_membership", membership))
            stack.enter_context(patch.object(team_admin, "sb_insert", insert))
            stack.enter_context(patch.object(team_admin, "sb_delete", delete))
            stack.enter_context(patch.object(team_admin, "sb_upsert", AsyncMock()))
            stack.enter_context(patch.object(team_admin, "sb_update", AsyncMock()))
            stack.enter_context(patch.object(team_admin, "is_shared_account", shared))
            stack.enter_context(patch.object(team_admin, "find_auth_user_by_email",
                                             AsyncMock(side_effect=lambda e: next((u for u in self.auth.values() if u["email"] == e), None))))
            stack.enter_context(patch.object(team_admin, "_holds_global_role", AsyncMock(side_effect=lambda u: u in self.internal)))
            stack.enter_context(patch.object(team_admin.ta, "invalidate", lambda *a: None))
            stack.enter_context(patch.object(team_admin.ta, "member_access", AsyncMock(return_value=None)))
            try:
                return await coro_factory(), None
            except AccessError as exc:
                return None, exc

    def auth_writes(self):
        return [c for c in self.admin_calls if c["method"] in ("POST", "PUT", "PATCH", "DELETE")]


class LinkExistingTests(Harness):
    async def test_liliu_is_linked_to_m2_without_touching_her_account(self):
        out, error = await self.act(lambda: team_admin.link_existing(client_id="m2", actor=TEAM, user_id=LILIU))
        self.assertIsNone(error)
        self.assertEqual(self.inserts, [("client_memberships", {"user_id": LILIU, "client_id": "m2", "status": "active",
                                                                 "role": "account_manager"})])
        self.assertEqual(self.auth_writes(), [])  # sem senha, sem nova conta, sem mexer no Auth
        self.assertTrue(out["team_member"])
        self.assertFalse(out["password_applied"])
        # Papel global e vínculo com a Mugô intocados: nada foi apagado nem atualizado.
        self.assertEqual(self.deletes, [])

    async def test_client_admin_cannot_search_or_link_existing_accounts(self):
        _out, error = await self.act(lambda: team_admin.search_linkable(client_id="m2", actor=CLIENT_ADMIN, query="li"))
        self.assertEqual(error.code, "TEAM_LINK_NOT_ALLOWED")
        _out, error = await self.act(lambda: team_admin.link_existing(client_id="m2", actor=CLIENT_ADMIN, user_id=LILIU))
        self.assertEqual(error.code, "TEAM_LINK_NOT_ALLOWED")
        self.assertEqual(self.inserts, [])
        self.assertFalse(any(c["path"] == "/users" for c in self.admin_calls))  # lista geral nunca consultada

    async def test_search_hides_current_members_and_marks_team(self):
        self.members["m2"] = [{"user_id": CLIENT_USER, "role": "viewer"}]
        out, error = await self.act(lambda: team_admin.search_linkable(client_id="m2", actor=TEAM, query="a"))
        self.assertIsNone(error)
        self.assertEqual(out["items"], [])  # termo curto demais
        out, _ = await self.act(lambda: team_admin.search_linkable(client_id="m2", actor=TEAM, query="mugo"))
        self.assertEqual([(i["user_id"], i["team"]) for i in out["items"]], [(LILIU, True)])
        self.assertNotIn("email_confirmed", str(out))

    async def test_already_member_or_unknown_account(self):
        self.members["m2"] = [{"user_id": LILIU, "role": "account_manager"}]
        _out, error = await self.act(lambda: team_admin.link_existing(client_id="m2", actor=TEAM, user_id=LILIU))
        self.assertEqual(error.status_code, 409)
        _out, error = await self.act(lambda: team_admin.link_existing(client_id="m2", actor=TEAM,
                                                                      user_id="cccccccc-1111-2222-3333-444444444444"))
        self.assertEqual(error.status_code, 404)
        self.assertEqual(self.inserts, [])

    async def test_external_account_gets_the_chosen_profile_not_a_team_role(self):
        out, error = await self.act(lambda: team_admin.link_existing(client_id="m2", actor=TEAM, user_id=CLIENT_USER,
                                                                     preset="visualizacao"))
        self.assertIsNone(error)
        row = self.inserts[0][1]
        self.assertEqual(row["role"], "viewer")
        self.assertFalse(out["team_member"])
        self.assertEqual(self.auth_writes(), [])

    async def test_unlinking_team_member_removes_only_this_company(self):
        self.members["m2"] = [{"user_id": LILIU, "role": "account_manager"}]
        out, error = await self.act(lambda: team_admin.remove_member(client_id="m2", actor=TEAM, user_id=LILIU))
        self.assertIsNone(error)
        self.assertTrue(out["account_preserved"])
        self.assertTrue(all(f["client_id"] == "eq.m2" for _t, f in self.deletes))
        self.assertEqual(self.auth_writes(), [])
        # Um agency_admin nunca é desvinculado por aqui.
        self.members["m2"] = [{"user_id": LILIU, "role": "agency_admin"}]
        self.deletes.clear()
        _out, error = await self.act(lambda: team_admin.remove_member(client_id="m2", actor=TEAM, user_id=LILIU))
        self.assertEqual(error.code, "ACCESS_ROLE_NOT_ALLOWED")
        self.assertEqual(self.deletes, [])


class CreateMemberNeverResetsPasswordTests(Harness):
    async def test_existing_email_is_linked_without_password_change(self):
        out, error = await self.act(lambda: team_admin.create_member(
            client_id="m2", actor=CLIENT_ADMIN, name="Ana", login="ana@ruah.com", password=None,
            preset="visualizacao", view_all=False, access_total=False, codes=None))
        self.assertIsNone(error)
        self.assertFalse(out["account_created"])
        self.assertFalse(out["password_applied"])
        self.assertEqual(self.auth_writes(), [])

    async def test_new_account_still_needs_a_password(self):
        _out, error = await self.act(lambda: team_admin.create_member(
            client_id="m2", actor=CLIENT_ADMIN, name="Novo", login="novo@m2.com", password=None,
            preset="visualizacao", view_all=False, access_total=False, codes=None))
        self.assertIsNotNone(error)
        self.assertEqual(self.inserts, [])

    async def test_tenant_admin_cannot_reset_password_of_shared_account(self):
        self.members["m2"] = [{"user_id": CLIENT_USER, "role": "viewer", "access_total": False}]
        _out, error = await self.act(lambda: team_admin.reset_password(client_id="m2", actor=CLIENT_ADMIN,
                                                                       user_id=CLIENT_USER, password="Senha-forte-123"))
        self.assertEqual(error.code, "ACCESS_SHARED_ACCOUNT")
        self.assertEqual(self.auth_writes(), [])


if __name__ == "__main__":
    unittest.main()
