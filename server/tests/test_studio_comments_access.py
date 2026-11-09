"""Lançamento: comentários nos posts (qualquer membro) e Mídia On só leitura para o cliente."""
from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routes import studio as studio_routes
from services import studio_comments as sc
from services.studio_calendar import StudioError

FUTURE = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
APPROVED = {"id": "p1", "title": "Reels", "status": "aprovado", "scheduled_at": FUTURE}
DRAFT = {"id": "p2", "title": "Rascunho", "status": "rascunho", "scheduled_at": FUTURE}


class CommentTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_comment_is_saved_and_the_team_is_told(self):
        with patch.object(sc, "sb_select", AsyncMock(return_value=[APPROVED])), patch.object(sc, "open_request_item_ids", AsyncMock(return_value=set())), \
             patch.object(sc, "sb_insert", AsyncMock(side_effect=lambda t, row: row)) as insert, \
             patch.object(sc, "notify_team", AsyncMock()) as notify:
            row = await sc.add_comment("roove", "p1", "  Pode trocar a música?  ", agency=False, user_id="u1")
        self.assertEqual((row["author_side"], row["author_name"], row["body"]), ("cliente", "Cliente", "Pode trocar a música?"))
        self.assertEqual(notify.await_args.args[2], "comentario")
        self.assertEqual(notify.await_args.kwargs["comment"], "Pode trocar a música?")
        self.assertEqual(insert.await_args.args[0], "studio_item_comments")

    async def test_agency_reply_does_not_create_a_task(self):
        with patch.object(sc, "sb_select", AsyncMock(return_value=[DRAFT])), \
             patch.object(sc, "sb_insert", AsyncMock(side_effect=lambda t, row: row)), patch.object(sc, "notify_team", AsyncMock()) as notify:
            row = await sc.add_comment("roove", "p2", "Ajustado!", agency=True, user_id="u1")
        self.assertEqual(row["author_name"], "Equipe Mugô")
        notify.assert_not_awaited()

    async def test_client_cannot_comment_or_read_a_draft(self):
        with patch.object(sc, "sb_select", AsyncMock(return_value=[DRAFT])), patch.object(sc, "open_request_item_ids", AsyncMock(return_value=set())):
            with self.assertRaises(StudioError) as err:
                await sc.add_comment("roove", "p2", "oi", agency=False, user_id="u1")
        self.assertEqual(err.exception.code, "ITEM_NOT_FOUND")

    async def test_empty_comment_is_refused(self):
        with self.assertRaises(StudioError) as err:
            await sc.add_comment("roove", "p1", "   ", agency=False, user_id="u1")
        self.assertEqual(err.exception.code, "COMMENT_REQUIRED")


class RouteAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_viewer_can_comment(self):
        guard = AsyncMock(return_value="roove")
        with patch.object(studio_routes, "require_client_role", guard), \
             patch.object(studio_routes, "require_user_id", AsyncMock(return_value="u1")), \
             patch.object(studio_routes, "is_agency_user", AsyncMock(return_value=False)), \
             patch.object(studio_routes, "add_comment", AsyncMock(return_value={"body": "oi"})):
            await studio_routes.write_item_comment("roove", "11111111-1111-1111-1111-111111111111",
                                                   studio_routes.CommentInput(body="oi"), authorization="Bearer viewer")
        self.assertIn("viewer", guard.await_args.kwargs["allowed_roles"])

    async def test_client_cannot_generate_or_save_media_plan_or_read_drafts(self):
        not_agency = patch.object(studio_routes, "is_agency_user", AsyncMock(return_value=False))
        with not_agency, patch.object(studio_routes, "require_client_role", AsyncMock(return_value="roove")), \
             patch.object(studio_routes, "require_client_read", AsyncMock(return_value="roove")), redirect_stdout(io.StringIO()):
            for handler in ("write_media_plan", "run_media_strategy", "read_media_strategies"):
                src = getattr(studio_routes, handler)
                with self.subTest(handler=handler):
                    import inspect
                    self.assertIn("_agency_only(authorization)", inspect.getsource(src))
            with self.assertRaises(HTTPException) as raised:
                await studio_routes._agency_only("Bearer cliente")
        self.assertEqual(raised.exception.status_code, 403)


    def test_client_admin_manages_triggers(self):
        import inspect
        for handler in ("engagement_rules", "engagement_rule_create", "engagement_rule_update",
                        "engagement_rule_delete", "engagement_rules_run"):
            src = inspect.getsource(getattr(studio_routes, handler))
            with self.subTest(handler=handler):
                self.assertNotIn("_agency_only", src)
                self.assertIn("allowed_roles=WRITERS", src)
        self.assertNotIn("viewer", studio_routes.WRITERS)

    def test_rule_accepts_ai_greeting_alone(self):
        row = studio_routes._rule_row(studio_routes.EngagementRule(name="Oi", keywords=["quero"], ai_greeting=True))
        self.assertTrue(row["ai_greeting"])
        with self.assertRaises(HTTPException):
            studio_routes._rule_row(studio_routes.EngagementRule(name="Oi", keywords=["quero"]))

if __name__ == "__main__":
    unittest.main()
