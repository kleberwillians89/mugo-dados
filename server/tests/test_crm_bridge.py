"""Ponte somente leitura Dados -> CRM (tarefas e atendimento). Empresas fictícias."""
from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routes import crm as crm_routes
from services import crm_bridge as cb
from services.studio_calendar import StudioError

ENV = {"CRM_OPS_API_URL": "https://crm.example/functions/v1/dados-ops-api/", "CRM_OPS_API_KEY": "k-test"}
CONV = "11111111-1111-1111-1111-111111111111"


def fake_crm(status: int, body: dict, seen: list):
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    return lambda **kw: real(transport=httpx.MockTransport(handler), **kw)


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, status, body, fn, *args, **kw):
        seen: list = []
        with patch.dict(os.environ, ENV), patch.object(cb.httpx, "AsyncClient", fake_crm(status, body, seen)), \
             redirect_stdout(io.StringIO()):
            result = await fn(*args, **kw)
        return result, seen

    async def test_without_configuration_it_says_so_instead_of_failing(self):
        with patch.dict(os.environ, {"CRM_OPS_API_URL": "", "CRM_OPS_API_KEY": ""}):
            self.assertEqual(await cb.list_tasks("curavino-test"), {"available": False, "reason": "not_configured"})

    async def test_sends_only_the_dados_company_id_and_the_key_header(self):
        result, seen = await self.call(200, {"ok": True, "data": {"tasks": [{"id": "t1"}]}}, cb.list_tasks, "curavino-test", limit=999)
        self.assertEqual(result, {"available": True, "tasks": [{"id": "t1"}]})
        req = seen[0]
        self.assertEqual(str(req.url.copy_with(query=None)), "https://crm.example/functions/v1/dados-ops-api/tasks")
        self.assertEqual(req.headers["X-Dados-Ops-Key"], "k-test")
        self.assertEqual(dict(req.url.params), {"external_client_id": "curavino-test", "limit": "200"})
        self.assertNotIn("organization_id", str(req.url))

    async def test_company_not_linked_in_the_crm_is_a_clear_state(self):
        result, _ = await self.call(403, {"ok": False, "code": "UNKNOWN_EXTERNAL_CLIENT"}, cb.list_conversations, "roove-test")
        self.assertEqual(result, {"available": False, "reason": "not_linked"})

    async def test_wrong_key_is_reported_as_auth_failed(self):
        result, _ = await self.call(401, {"ok": False, "code": "UNAUTHORIZED"}, cb.list_conversations, "roove-test")
        self.assertEqual(result["reason"], "auth_failed")

    async def test_conversation_of_another_client_is_404(self):
        with self.assertRaises(StudioError) as err:
            await self.call(404, {"ok": False, "code": "CONVERSATION_NOT_FOUND"}, cb.list_messages, "roove-test", CONV)
        self.assertEqual(err.exception.code, "CONVERSATION_NOT_FOUND")

    async def test_bad_conversation_id_never_reaches_the_crm(self):
        with self.assertRaises(StudioError):
            await self.call(200, {"ok": True}, cb.list_messages, "roove-test", "../tasks")

    async def test_invalid_status_is_refused(self):
        with self.assertRaises(StudioError) as err:
            await cb.list_tasks("roove-test", status="drop")
        self.assertEqual(err.exception.code, "STATUS_INVALID")

    async def test_network_error_becomes_crm_unreachable(self):
        real = httpx.AsyncClient
        with patch.dict(os.environ, ENV), patch.object(cb.httpx, "AsyncClient", lambda **kw: real(
                transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down"))), **kw)), \
             redirect_stdout(io.StringIO()):
            with self.assertRaises(StudioError) as err:
                await cb.list_tasks("roove-test")
        self.assertEqual(err.exception.code, "CRM_UNREACHABLE")


class ClientAudienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_view_strips_anything_internal_even_if_the_crm_sent_it(self):
        crm = {"ok": True, "data": {"tasks": [
            {"id": "t1", "title": "Gravar reels", "status": "pending", "due_date": "2026-11-05", "updated_at": "x",
             "notes": "interno", "assignee": {"name": "Julia"}, "tags": ["cliente"]},
            {"id": "t2", "title": "Cancelada", "status": "cancelled", "due_date": None, "updated_at": "x"},
        ]}}
        seen: list = []
        with patch.dict(os.environ, ENV), patch.object(cb.httpx, "AsyncClient", fake_crm(200, crm, seen)), redirect_stdout(io.StringIO()):
            result = await cb.list_client_tasks("roove-test")
        self.assertEqual(seen[0].url.params["audience"], "client")
        self.assertEqual(result, {"available": True, "tasks": [
            {"id": "t1", "title": "Gravar reels", "status": "pending", "due_date": "2026-11-05", "updated_at": "x"}]})

    async def test_missing_function_is_a_clear_state(self):
        seen: list = []
        with patch.dict(os.environ, ENV), patch.object(cb.httpx, "AsyncClient", fake_crm(404, {"code": "NOT_FOUND", "message": "Requested function was not found"}, seen)), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(await cb.list_client_tasks("roove-test"), {"available": False, "reason": "function_missing"})


class AgencyOnlyRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_agency_crm_route_is_agency_only(self):
        guard = AsyncMock(return_value="roove-test")
        with patch.object(crm_routes, "require_client_role", guard), \
             patch.object(crm_routes, "list_contacts", AsyncMock(return_value=[])), \
             patch.object(crm_routes, "list_tasks", AsyncMock(return_value={})), \
             patch.object(crm_routes, "list_conversations", AsyncMock(return_value={})), \
             patch.object(crm_routes, "list_messages", AsyncMock(return_value={})):
            await crm_routes.crm_tasks("roove-test", authorization="Bearer x")
            await crm_routes.crm_conversations("roove-test", authorization="Bearer x")
            await crm_routes.crm_messages("roove-test", CONV, authorization="Bearer x")
        self.assertEqual(guard.await_count, 3)
        for call in guard.await_args_list:
            self.assertEqual(call.kwargs["allowed_roles"], ("agency_admin",))

    async def test_conversation_phones_come_from_the_server_side_contacts(self):
        convs = AsyncMock(return_value={"available": True, "conversations": []})
        with patch.object(crm_routes, "require_client_role", AsyncMock(return_value="roove-test")), \
             patch.object(crm_routes, "list_contacts", AsyncMock(return_value=[{"phone": "5511999990000"}, {"phone": "34600000000"}])) as contacts, \
             patch.object(crm_routes, "list_conversations", convs):
            await crm_routes.crm_conversations("roove-test", authorization="Bearer x")
        contacts.assert_awaited_once_with("roove-test")
        self.assertEqual(convs.await_args.kwargs["phones"], ["5511999990000", "34600000000"])

    async def test_client_tasks_accept_any_member_and_never_use_the_agency_reader(self):
        read = AsyncMock(return_value="roove-test")
        role = AsyncMock()
        agency = AsyncMock()
        with patch.object(crm_routes, "require_client_read", read), patch.object(crm_routes, "require_client_role", role), \
             patch.object(crm_routes, "list_tasks", agency), \
             patch.object(crm_routes, "list_client_tasks", AsyncMock(return_value={"available": True, "tasks": []})):
            await crm_routes.crm_client_tasks("roove-test", authorization="Bearer viewer")
        read.assert_awaited_once()
        role.assert_not_awaited()
        agency.assert_not_awaited()

    async def test_client_viewer_is_denied_before_any_crm_call(self):
        denied = HTTPException(status_code=403, detail="Papel sem permissão para esta ação.")
        crm = AsyncMock()
        with patch.object(crm_routes, "require_client_role", AsyncMock(side_effect=denied)), \
             patch.object(crm_routes, "list_conversations", crm):
            with self.assertRaises(HTTPException) as raised:
                await crm_routes.crm_conversations("roove-test", authorization="Bearer viewer")
        self.assertEqual(raised.exception.status_code, 403)
        crm.assert_not_awaited()

    async def test_errors_map_to_friendly_http(self):
        with patch.object(crm_routes, "require_client_role", AsyncMock(return_value="roove-test")), \
             patch.object(crm_routes, "list_messages", AsyncMock(side_effect=StudioError("CONVERSATION_NOT_FOUND"))):
            with self.assertRaises(HTTPException) as raised:
                await crm_routes.crm_messages("roove-test", CONV, authorization="Bearer x")
        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
