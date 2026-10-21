import unittest
from unittest.mock import AsyncMock, patch
import httpx
from fastapi import FastAPI, HTTPException
from services import intelligence_conversations as service
from services import intelligence
from routes import intelligence as routes


def row(identifier="thread", client="tenant-a", user="user-a"):
    return {"id": identifier, "client_id": client, "user_id": user, "title": "Conversa privada", "created_at": "2026-01-01", "updated_at": "2026-01-01"}


class ConversationPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_listing_is_projected_paginated_and_owner_scoped(self):
        rows = [row(str(i)) for i in range(26)]
        with patch.object(service, "sb_select", AsyncMock(return_value=rows)) as select:
            result = await service.list_conversations("tenant-a", "user-a", 999, 99999)
        self.assertEqual(len(result["items"]), 25); self.assertTrue(result["has_more"])
        self.assertEqual(select.await_args.kwargs["filters"], {"client_id": "eq.tenant-a", "user_id": "eq.user-a"})
        self.assertEqual(select.await_args.kwargs["limit"], 26); self.assertEqual(select.await_args.kwargs["offset"], 10000)
        self.assertNotIn("content", select.await_args.kwargs["select"])

    async def test_foreign_tenants_and_users_cannot_leak_from_results(self):
        with patch.object(service, "sb_select", AsyncMock(return_value=[row(), row(client="tenant-b"), row(user="user-b")])):
            result = await service.list_conversations("tenant-a", "user-a")
        self.assertEqual(result["items"], [row()])

    async def test_create_empty_conversation_persists_owner_without_model(self):
        with patch.object(service, "sb_insert", AsyncMock(return_value=row())) as insert:
            result = await service.create_conversation("tenant-a", "user-a")
        self.assertEqual(result["conversation"]["id"], "thread")
        self.assertEqual(insert.await_args.args[1], {"client_id": "tenant-a", "user_id": "user-a", "title": "Nova conversa"})

    async def test_rename_resume_delete_always_scope_target_owner(self):
        with patch.object(service, "sb_update", AsyncMock(return_value=[row()])) as update, \
             patch.object(service, "sb_delete", AsyncMock(return_value=[row()])) as delete:
            await service.rename_conversation("tenant-a", "user-a", "thread", "  Título corrigido  ")
            await service.resume_conversation("tenant-a", "user-a", "thread")
            await service.delete_conversation("tenant-a", "user-a", "thread")
        for call in [*update.await_args_list, delete.await_args]:
            self.assertEqual(call.kwargs["filters"], {"id": "eq.thread", "client_id": "eq.tenant-a", "user_id": "eq.user-a"})
        self.assertEqual(update.await_args_list[0].kwargs["patch"], {"title": "Título corrigido"})
        self.assertEqual(set(update.await_args_list[1].kwargs["patch"]), {"updated_at"})

    async def test_missing_or_foreign_target_does_not_report_success(self):
        for rows in [[], [row(client="tenant-b")], [row(user="user-b")]]:
            with patch.object(service, "sb_update", AsyncMock(return_value=rows)), patch.object(service, "sb_delete", AsyncMock(return_value=rows)):
                for method, extra in [(service.rename_conversation, ["Novo título"]), (service.resume_conversation, []), (service.delete_conversation, [])]:
                    with self.assertRaisesRegex(RuntimeError, "CONVERSATION_NOT_FOUND"):
                        await method("tenant-a", "user-a", "thread", *extra)

    async def test_missing_target_or_owner_never_causes_bulk_mutation(self):
        with patch.object(service, "sb_update", AsyncMock()) as update, patch.object(service, "sb_delete", AsyncMock()) as delete:
            for target in [None, "", " "]:
                for method, extra in [(service.rename_conversation, ["Novo título"]), (service.resume_conversation, []), (service.delete_conversation, [])]:
                    with self.assertRaisesRegex(RuntimeError, "CONVERSATION_NOT_FOUND"):
                        await method("tenant-a", "user-a", target, *extra)
            with self.assertRaisesRegex(RuntimeError, "CONVERSATION_NOT_FOUND"):
                await service.delete_conversation("tenant-a", "", "thread")
        update.assert_not_awaited(); delete.assert_not_awaited()

    async def test_invalid_title_is_rejected_before_writes(self):
        with patch.object(service, "sb_update", AsyncMock()) as update:
            for title in [" ", "x" * 121]:
                with self.assertRaisesRegex(RuntimeError, "CONVERSATION_TITLE_INVALID"):
                    await service.rename_conversation("tenant-a", "user-a", "thread", title)
        update.assert_not_awaited()

    async def test_restoration_returns_latest_hundred_in_chronological_order(self):
        newest_first = [{"id": str(i)} for i in range(100, 0, -1)]
        with patch.object(intelligence, "sb_select", AsyncMock(side_effect=[[row()], newest_first])) as select:
            result = await intelligence.conversation_messages("tenant-a", "user-a", "thread")
        self.assertEqual(result["messages"][0]["id"], "1"); self.assertEqual(result["messages"][-1]["id"], "100")
        self.assertEqual(select.await_args.kwargs["order"], "created_at.desc,id.desc")
        self.assertEqual(select.await_args.kwargs["limit"], 100)
        self.assertEqual(select.await_args.kwargs["filters"]["user_id"], "eq.user-a")


class ConversationRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_foreign_tenant_denied_before_read_or_mutation(self):
        app = FastAPI(); app.include_router(routes.router)
        with patch.object(routes, "require_user_id", AsyncMock(return_value="user-a")), \
             patch.object(routes, "resolve_client_id", AsyncMock(side_effect=HTTPException(status_code=403))), \
             patch.object(service, "sb_select", AsyncMock()) as select, \
             patch.object(service, "sb_update", AsyncMock()) as update, \
             patch.object(service, "sb_delete", AsyncMock()) as delete, \
             patch.object(service, "sb_insert", AsyncMock()) as insert:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
                for method, path, body in [("GET", "", None), ("POST", "", None), ("PATCH", "/thread", {"title": "Novo"}), ("DELETE", "/thread", None), ("POST", "/thread/resume", None)]:
                    response = await client.request(method, "/api/intelligence/conversations" + path, json=body, headers={"X-Client-Id": "foreign"})
                    self.assertEqual(response.status_code, 403)
        for mock in [select, update, delete, insert]: mock.assert_not_awaited()

    async def test_authenticated_identity_is_used_instead_of_body_claims(self):
        app = FastAPI(); app.include_router(routes.router)
        with patch.object(routes, "require_user_id", AsyncMock(return_value="user-a")), \
             patch.object(routes, "resolve_client_id", AsyncMock(return_value="tenant-a")), \
             patch.object(service, "sb_insert", AsyncMock(return_value=row())) as insert:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
                response = await client.post("/api/intelligence/conversations", json={"user_id": "user-b", "client_id": "tenant-b"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(insert.await_args.args[1]["user_id"], "user-a")
        self.assertEqual(insert.await_args.args[1]["client_id"], "tenant-a")


class EmptyConversationTitleTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_answer_titles_empty_default_thread_but_preserves_custom_title(self):
        for title, expected in [("Nova conversa", "Pergunta aberta válida"), ("Título escolhido", None)]:
            with self.subTest(title=title), \
                 patch.object(intelligence, "provider_configured", return_value=True), \
                 patch.object(intelligence, "conversation_messages", AsyncMock(return_value={"conversation": {**row(), "title": title}, "messages": []})), \
                 patch.object(intelligence, "_investigate_question", AsyncMock(return_value=({"direct_answer": "Leitura validada"}, {"sources": []}))), \
                 patch.object(intelligence, "sb_select", AsyncMock(return_value=[])), \
                 patch.object(intelligence, "sb_insert", AsyncMock(return_value={"id": "message"})), \
                 patch.object(intelligence, "sb_update", AsyncMock()) as update:
                await intelligence.ask_intelligence(client_id="tenant-a", user_id="user-a", question="Pergunta aberta válida", conversation_id="thread", start="2026-01-01", end="2026-01-07")
                self.assertEqual(update.await_args.kwargs["patch"].get("title"), expected)
                self.assertEqual(update.await_args.kwargs["filters"]["user_id"], "eq.user-a")
