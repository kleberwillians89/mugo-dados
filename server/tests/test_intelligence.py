import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from routes import intelligence as routes
from services import intelligence


class IntelligenceAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_route_resolves_user_and_tenant_before_reading_context(self):
        snapshot = {"period": {"start": "2026-07-01", "end": "2026-07-30"}}
        with (
            patch.object(routes, "require_user_id", AsyncMock(return_value="user-1")),
            patch.object(routes, "resolve_client_id", AsyncMock(return_value="client-1")) as tenant,
            patch.object(
                routes,
                "calculate_intelligence_snapshot",
                AsyncMock(return_value=snapshot),
            ),
        ):
            result = await routes.intelligence_context(
                start="2026-07-01",
                end="2026-07-30",
                days=30,
                client_id="client-1",
                x_client_id=None,
                authorization="Bearer valid",
            )
        tenant.assert_awaited_once_with("client-1", "Bearer valid")
        self.assertEqual(result["snapshot"], snapshot)

    async def test_provider_pending_is_honest_and_persisted_as_new_version(self):
        snapshot = {
            "period": {"start": "2026-07-01", "end": "2026-07-30"},
            "sources": [],
            "quality": {"status": "limited"},
            "metrics": [],
        }
        insert = AsyncMock(return_value={"id": "analysis-1", "status": "configuration_pending"})
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False),
            patch.object(
                intelligence,
                "calculate_intelligence_snapshot",
                AsyncMock(return_value=snapshot),
            ),
            patch.object(intelligence, "sb_insert", insert),
        ):
            result = await intelligence.generate_analysis(
                client_id="client-1",
                user_id="user-1",
                start="2026-07-01",
                end="2026-07-30",
            )
        self.assertFalse(result["provider_configured"])
        self.assertEqual(insert.await_args.args[0], "ai_analyses")
        self.assertEqual(insert.await_args.args[1]["status"], "configuration_pending")

    async def test_conversation_read_filters_client_and_user(self):
        select = AsyncMock(
            side_effect=[
                [{"id": "conversation-1", "client_id": "client-1", "user_id": "user-1"}],
                [{"id": "message-1", "role": "assistant"}],
            ]
        )
        with patch.object(intelligence, "sb_select", select):
            result = await intelligence.conversation_messages(
                "client-1", "user-1", "conversation-1"
            )
        first_filters = select.await_args_list[0].kwargs["filters"]
        second_filters = select.await_args_list[1].kwargs["filters"]
        self.assertEqual(first_filters["client_id"], "eq.client-1")
        self.assertEqual(first_filters["user_id"], "eq.user-1")
        self.assertEqual(second_filters["client_id"], "eq.client-1")
        self.assertEqual(second_filters["user_id"], "eq.user-1")
        self.assertEqual(result["messages"][0]["id"], "message-1")

    async def test_foreign_conversation_is_not_exposed(self):
        with patch.object(intelligence, "sb_select", AsyncMock(return_value=[])):
            with self.assertRaisesRegex(RuntimeError, "CONVERSATION_NOT_FOUND"):
                await intelligence.conversation_messages(
                    "client-1", "user-1", "conversation-from-client-2"
                )

    def test_provider_error_maps_to_recoverable_http_error(self):
        with self.assertRaises(HTTPException) as raised:
            routes._raise_service_error(RuntimeError("AI_PROVIDER_ERROR_500"))
        self.assertEqual(raised.exception.status_code, 502)

    def test_ai_text_cannot_introduce_untrusted_numbers(self):
        intelligence._assert_no_untrusted_numeric_text(
            {"direct_answer": "A receita melhorou.", "metric_ids": ["revenue"]}
        )
        with self.assertRaisesRegex(RuntimeError, "AI_UNTRUSTED_NUMERIC_TEXT"):
            intelligence._assert_no_untrusted_numeric_text(
                {"direct_answer": "A receita aumentou 42 por cento.", "metric_ids": ["revenue"]}
            )


class IntelligenceMigrationTests(unittest.TestCase):
    def test_tables_have_no_authenticated_direct_access(self):
        sql = (
            Path(__file__).parents[2]
            / "supabase/migrations/20260802_000021_intelligence_workspace.sql"
        ).read_text().lower()
        self.assertIn("create table if not exists public.ai_analyses", sql)
        self.assertIn("create table if not exists public.ai_conversations", sql)
        self.assertIn("create table if not exists public.ai_messages", sql)
        self.assertIn("revoke all on public.ai_analyses from anon, authenticated", sql)
        self.assertNotIn("create policy", sql)


if __name__ == "__main__":
    unittest.main()
