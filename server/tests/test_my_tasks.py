"""Spec do Danilo (PR 2): Minhas Tarefas — só as tarefas da pessoa logada, só nas empresas que ela pode ver."""
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import my_tasks as mt  # noqa: E402
from services import clients as clients_service  # noqa: E402
from services import team_access  # noqa: E402

ME, OTHER = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"


def row(tid, client, **extra):
    base = {"id": tid, "client_id": client, "title": f"Tarefa {tid}", "status": "pending", "assignee_user_ids": [ME],
            "assignee_names": ["Eu"], "visible_to_client": False, "due_date": None}
    return {**base, **extra}


class MyTasksTests(unittest.IsolatedAsyncioTestCase):
    async def run_list(self, clients, rows, access=None, **kwargs):
        select = AsyncMock(return_value=rows)
        member = AsyncMock(side_effect=lambda cid, uid, role=None: (access or {}).get(cid))
        with patch.object(clients_service, "list_clients_for_user", AsyncMock(return_value={"clients": clients})), \
                patch.object(team_access, "member_access", member), patch.object(mt, "sb_select", select):
            out = await mt.list_my_tasks(ME, **kwargs)
        return out, select

    async def test_matches_only_the_session_user_as_assignee(self):
        out, select = await self.run_list([{"client_id": "roove", "role": "agency_admin", "name": "Roove"}],
                                          [row("t1", "roove"), row("t2", "roove", assignee_user_ids=[OTHER], created_by=ME)])
        self.assertEqual([t["id"] for t in out["tasks"]], ["t1"])  # criada por mim mas de outra pessoa: fora
        filters = select.await_args.kwargs["filters"]
        self.assertEqual(filters["or"], f"(assignee_user_ids.cs.{{{ME}}},assignee_user_id.eq.{ME})")
        self.assertNotIn("created_by", filters["or"])
        self.assertEqual(filters["client_id"], 'in.("roove")')
        self.assertEqual(out["tasks"][0]["client_name"], "Roove")

    async def test_tenant_isolation_never_reads_or_returns_other_companies(self):
        clients = [{"client_id": "roove", "role": "viewer", "name": "Roove"}, {"client_id": "ruah", "role": "viewer", "name": "Ruah"}]
        access = {"roove": {"status": "active", "codes": ["tasks.view"]},
                  "ruah": {"status": "active", "codes": ["central.view"]}}  # sem o módulo Tarefas
        out, select = await self.run_list(clients, [row("t1", "roove"), row("t9", "ruah"), row("t8", "origami")], access)
        self.assertEqual(select.await_args.kwargs["filters"]["client_id"], 'in.("roove")')
        self.assertEqual([t["id"] for t in out["tasks"]], ["t1"])
        self.assertEqual([c["client_id"] for c in out["clients"]], ["roove"])
        # Pedir uma empresa sem acesso: lista vazia, sem consultar o banco.
        out, select = await self.run_list(clients, [row("t9", "ruah")], access, client_id="ruah")
        self.assertEqual(out["tasks"], [])
        select.assert_not_awaited()

    async def test_inactive_member_and_client_view_follow_the_board(self):
        clients = [{"client_id": "roove", "role": "viewer", "name": "Roove"}, {"client_id": "ruah", "role": "viewer", "name": "Ruah"}]
        access = {"roove": {"status": "active", "codes": ["tasks.view", "tasks.all"]},
                  "ruah": {"status": "inactive", "codes": ["tasks.view"]}}
        out, _ = await self.run_list(clients, [row("t1", "roove"), row("t2", "roove", visible_to_client=True, status="internal_review")], access)
        self.assertEqual([t["id"] for t in out["tasks"]], ["t2"])  # quem vê como cliente: só as visíveis
        self.assertEqual(out["tasks"][0]["status"], "in_progress")  # etapa interna não aparece

    async def test_filters_status_search_and_bad_input(self):
        clients = [{"client_id": "roove", "role": "agency_admin", "name": "Roove"}]
        _, select = await self.run_list(clients, [], status="completed", q="capa*)(,or")
        filters = select.await_args.kwargs["filters"]
        self.assertEqual(filters["status"], "eq.completed")
        self.assertEqual(filters["title"], "ilike.*capa or*")
        _, select = await self.run_list(clients, [])
        self.assertTrue(select.await_args.kwargs["filters"]["status"].startswith("in.(pending"))
        with self.assertRaises(mt.StudioError):
            await mt.list_my_tasks(ME, status="xyz")
        with self.assertRaises(mt.StudioError):
            await mt.list_my_tasks("nao-e-uuid")

    async def test_read_error_raises_instead_of_empty(self):
        select = AsyncMock(side_effect=RuntimeError("down"))
        with patch.object(clients_service, "list_clients_for_user", AsyncMock(return_value={"clients": [{"client_id": "roove", "role": "agency_admin"}]})), \
                patch.object(mt, "sb_select", select):
            with self.assertRaises(RuntimeError):
                await mt.list_my_tasks(ME)


class MeRouteTests(unittest.TestCase):
    def test_route_uses_session_and_hides_failures_as_503(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from routes import me
        app = FastAPI(); app.include_router(me.router)
        client = TestClient(app)
        with patch.object(me, "require_user_id", AsyncMock(return_value=ME)), \
                patch.object(me.my_tasks, "list_my_tasks", AsyncMock(side_effect=RuntimeError("x"))):
            r = client.get("/api/me/tasks", headers={"Authorization": "Bearer t"})
        self.assertEqual(r.status_code, 503)
        lister = AsyncMock(return_value={"ok": True, "tasks": [], "clients": []})
        with patch.object(me, "require_user_id", AsyncMock(return_value=ME)), patch.object(me.my_tasks, "list_my_tasks", lister):
            r = client.get("/api/me/tasks?client_id=roove&user_id=" + OTHER, headers={"Authorization": "Bearer t"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(lister.await_args.args[0], ME)  # nunca a pessoa do parâmetro


if __name__ == "__main__":
    unittest.main()
