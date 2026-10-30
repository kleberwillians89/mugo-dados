"""Calendário do cliente: o que ele vê, o que pode mudar e o aviso ao time. Empresas fictícias."""
from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routes import studio as studio_routes
from services import studio_client as sc
from services import studio_team as st
from services.studio_calendar import StudioError

FUTURE = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
ITEMS = [
    {"id": "r1", "status": "rascunho", "title": "Rascunho"},
    {"id": "e1", "status": "em_revisao", "title": "Revisão interna"},
    {"id": "e2", "status": "em_revisao", "title": "Com o cliente"},
    {"id": "a1", "status": "aprovado", "title": "Aprovado"},
    {"id": "j1", "status": "rejeitado", "title": "Ajuste"},
    {"id": "p1", "status": "publicado", "title": "Publicado"},
]
POST = {"id": "e2", "client_id": "roove", "status": "em_revisao", "title": "Reels do lançamento", "hook": "Olha isso",
        "caption_draft": "Legenda", "scheduled_at": "2026-11-05T22:00:00+00:00", "client_edited_fields": []}


class VisibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_sees_only_what_is_with_him_approved_adjust_or_published(self):
        with patch.object(sc, "sb_select", AsyncMock(return_value=[{"item_ids": ["e2"], "expires_at": FUTURE}])):
            visible = await sc.client_items("roove", ITEMS)
        self.assertEqual([i["id"] for i in visible], ["e2", "a1", "j1", "p1"])


class ClientEditTests(unittest.IsolatedAsyncioTestCase):
    async def edit(self, patch_body, current=POST):
        reads = AsyncMock(side_effect=[[current], [{"item_ids": ["e2"], "expires_at": FUTURE}]])
        updated = {**current, **patch_body}
        with patch.object(sc, "sb_select", reads), patch.object(sc, "update_item", AsyncMock(return_value=updated)) as upd, \
             patch.object(sc, "sb_update", AsyncMock(return_value=[{**updated, "client_edited_fields": ["caption_draft"]}])) as mark, \
             patch.object(sc, "notify_team", AsyncMock()) as notify:
            item = await sc.client_edit("roove", "e2", patch_body, user_id="u1", actor_name="O cliente pelo painel")
        return item, upd, mark, notify

    async def test_text_edit_is_saved_marked_and_the_team_is_told(self):
        _, upd, mark, notify = await self.edit({"caption_draft": "Legenda nova", "title": "Reels do lançamento"})
        self.assertEqual(upd.await_args.args[2], {"caption_draft": "Legenda nova"})  # só o que mudou de verdade
        self.assertEqual(mark.await_args.kwargs["patch"]["client_edited_fields"], ["caption_draft"])
        self.assertEqual(notify.await_args.args[2], "editado_pelo_cliente")
        self.assertEqual(notify.await_args.kwargs["changes"], ["caption_draft"])

    async def test_approve_and_adjust_notify_the_team(self):
        _, _, _, notify = await self.edit({"status": "aprovado"})
        self.assertEqual(notify.await_args.args[2], "aprovado")
        _, upd, _, notify = await self.edit({"status": "rejeitado", "review_note": "Trocar a música"})
        self.assertEqual(upd.await_args.args[2]["review_note"], "Cliente (O cliente pelo painel): Trocar a música")
        self.assertEqual(notify.await_args.kwargs["comment"], "Trocar a música")

    async def test_client_cannot_publish_reopen_change_format_or_adjust_without_comment(self):
        for body, code in (({"status": "publicado"}, "CLIENT_STATUS_NOT_ALLOWED"), ({"status": "rascunho"}, "CLIENT_STATUS_NOT_ALLOWED"),
                           ({"format": "carrossel"}, "CLIENT_FIELD_NOT_ALLOWED"), ({"status": "rejeitado"}, "COMMENT_REQUIRED")):
            with self.subTest(body=body), self.assertRaises(StudioError) as err:
                await self.edit(body)
            self.assertEqual(err.exception.code, code)

    async def test_client_cannot_touch_a_draft(self):
        with self.assertRaises(StudioError) as err:
            await self.edit({"title": "x"}, current={**POST, "id": "r1", "status": "rascunho"})
        self.assertEqual(err.exception.code, "ITEM_NOT_FOUND")


class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_create_and_delete_are_agency_only(self):
        with patch.object(studio_routes, "require_client_role", AsyncMock(return_value="roove")), \
             patch.object(studio_routes, "is_agency_user", AsyncMock(return_value=False)), \
             patch.object(studio_routes, "delete_item", AsyncMock()) as delete:
            with self.assertRaises(HTTPException) as raised:
                await studio_routes.remove_item("roove", "11111111-1111-1111-1111-111111111111", authorization="Bearer cliente")
        self.assertEqual(raised.exception.status_code, 403)
        delete.assert_not_awaited()

    async def test_client_patch_goes_through_client_rules(self):
        body = studio_routes.ItemPatch(caption_draft="Nova")
        with patch.object(studio_routes, "require_client_role", AsyncMock(return_value="roove")), \
             patch.object(studio_routes, "require_user_id", AsyncMock(return_value="u1")), \
             patch.object(studio_routes, "is_agency_user", AsyncMock(return_value=False)), \
             patch.object(studio_routes, "client_edit", AsyncMock(return_value=POST)) as edit, \
             patch.object(studio_routes, "update_item", AsyncMock()) as agency_update:
            await studio_routes.edit_item("roove", "11111111-1111-1111-1111-111111111111", body, authorization="Bearer cliente")
        edit.assert_awaited_once()
        agency_update.assert_not_awaited()


class TeamEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_event_is_recorded_before_the_crm_and_survives_a_crm_outage(self):
        with patch.object(st, "sb_insert", AsyncMock()) as insert, patch.object(st, "sb_update", AsyncMock()) as update, \
             patch.object(st, "post_event", AsyncMock(return_value={"ok": False, "code": "network"})), redirect_stdout(io.StringIO()):
            event_id = await st.notify_team("roove", POST, "ajuste_solicitado", actor_name="Ana", comment="Trocar")
        self.assertTrue(event_id)
        self.assertEqual(insert.await_args.args[1]["status"], "pendente")
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "pendente")  # fica para o job reenviar

    async def test_client_not_linked_in_crm_stops_retrying(self):
        with patch.object(st, "sb_insert", AsyncMock()), patch.object(st, "sb_update", AsyncMock()) as update, \
             patch.object(st, "post_event", AsyncMock(return_value={"ok": False, "code": "UNKNOWN_EXTERNAL_CLIENT"})):
            await st.notify_team("roove", POST, "aprovado", actor_name="Ana")
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "ignorado")

    async def test_a_failure_never_breaks_the_client_action(self):
        with patch.object(st, "sb_insert", AsyncMock(side_effect=RuntimeError("db fora"))), redirect_stdout(io.StringIO()):
            self.assertIsNone(await st.notify_team("roove", POST, "aprovado", actor_name="Ana"))

    async def test_payload_sent_to_crm_has_only_the_event(self):
        sent = AsyncMock(return_value={"ok": True, "task_id": "t1"})
        with patch.object(st, "sb_insert", AsyncMock()), patch.object(st, "sb_update", AsyncMock()), patch.object(st, "post_event", sent), \
             patch.dict(os.environ, {"FRONTEND_URL": "https://dados.example"}):
            await st.notify_team("roove", POST, "editado_pelo_cliente", actor_name="Ana", changes=["caption_draft", "scheduled_at"])
        event = sent.await_args.args[2]
        self.assertEqual(set(event), {"event_id", "action", "actor_name", "title", "comment", "changes", "scheduled_at", "link"})
        self.assertEqual(event["changes"], ["legenda", "data"])
        self.assertEqual(event["link"], "https://dados.example/aprovacao")


if __name__ == "__main__":
    unittest.main()
