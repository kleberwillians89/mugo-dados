"""Tarefas com aprovação interna e do cliente (fluxo do iAgência)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import AsyncMock, patch

from services import studio_tasks as st
from services.studio_calendar import StudioError

T = "11111111-2222-3333-4444-555555555555"


def task(status, visible=True, needs=True, rnd=0):
    return {"id": T, "client_id": "ruah", "title": "Arte BF", "status": status, "visible_to_client": visible,
            "needs_client_approval": needs, "approval_round": rnd}


class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def run_action(self, current, action, *, agency=True, comment=None, internal=False):
        target = st.next_status(action, current)
        updated = {**current, **({"status": target} if target else {})}
        if action == "submit":
            updated["approval_round"] = int(current.get("approval_round") or 0) + 1
        result = {"task": updated, "outbox": {"id": "o1", "client_id": "ruah", "kind": "crm_notification",
                                                "payload": {}, "status": "pending", "attempts": 0}
                  if action.startswith("client_") else None}
        rpc = AsyncMock(return_value=result)
        with patch.object(st, "_owned", AsyncMock(return_value=current)), patch.object(st, "sb_rpc", rpc), \
             patch.object(st, "list_events", AsyncMock(return_value=[])), \
             patch("services.studio_chat.post_decision", AsyncMock()), \
             patch("services.task_sync_outbox.deliver", AsyncMock()):
            out = await st.approval_action("ruah", T, action, comment=comment, user_id="u1", actor_name="kleber",
                                           is_agency=agency, internal_comment=internal)
        return out, rpc.await_args.args[1]

    async def test_submit_goes_to_internal_review_and_counts_round(self):
        out, payload = await self.run_action(task("in_progress", rnd=1), "submit")
        self.assertEqual(out["task"]["status"], "internal_review")
        self.assertEqual(out["task"]["approval_round"], 2)
        self.assertEqual((payload["p_expected_status"], payload["p_action"], payload["p_internal"]),
                         ("in_progress", "submit", True))

    async def test_internal_approve_sends_to_client_or_finishes(self):
        out, _ = await self.run_action(task("internal_review"), "internal_approve")
        self.assertEqual(out["task"]["status"], "client_review")
        for t in (task("internal_review", visible=False), task("internal_review", needs=False)):
            out, _ = await self.run_action(t, "internal_approve")
            self.assertEqual(out["task"]["status"], "completed")

    async def test_client_approves_or_asks_changes_with_comment(self):
        out, payload = await self.run_action(task("client_review"), "client_approve", agency=False)
        self.assertEqual(out["task"]["status"], "completed")
        self.assertEqual((payload["p_actor_side"], payload["p_internal"]), ("cliente", False))
        with self.assertRaises(StudioError) as err:
            await self.run_action(task("client_review"), "client_changes", agency=False, comment="  ")
        self.assertEqual(err.exception.code, "COMMENT_REQUIRED")
        out, payload = await self.run_action(task("client_review"), "client_changes", agency=False, comment="Trocar a foto")
        self.assertEqual((out["task"]["status"], payload["p_comment"]), ("changes", "Trocar a foto"))

    async def test_client_cannot_do_internal_steps_nor_skip_stages(self):
        for action in ("submit", "internal_approve", "internal_changes"):
            with self.assertRaises(StudioError) as err:
                await self.run_action(task("internal_review"), action, agency=False, comment="x")
            self.assertEqual(err.exception.code, "FORBIDDEN")
        with self.assertRaises(StudioError) as err:
            await self.run_action(task("in_progress"), "client_approve", agency=False)
        self.assertEqual(err.exception.code, "STAGE_INVALID")

    async def test_comments_internal_only_for_team(self):
        _, payload = await self.run_action(task("in_progress"), "comment", comment="briefing interno", internal=True)
        self.assertTrue(payload["p_internal"])
        _, payload = await self.run_action(task("client_review"), "comment", agency=False, comment="gostei", internal=True)
        self.assertFalse(payload["p_internal"])

    def test_client_never_sees_internal_stage(self):
        self.assertEqual(st.task_view(task("internal_review"), client_view=True)["status"], "in_progress")
        self.assertEqual(st.task_view(task("internal_review"))["status"], "internal_review")


class PerPersonTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_filters_by_assignee_or_creator(self):
        from services import studio_tasks as stk
        select = AsyncMock(return_value=[])
        with patch.object(stk, "sb_select", select):
            await stk.list_tasks("roove", only_user="u1")
        self.assertEqual(select.await_args.kwargs["filters"]["or"], "(assignee_user_ids.cs.{u1},assignee_user_id.eq.u1,created_by.eq.u1)")

    async def test_someone_elses_task_is_not_found(self):
        from services import studio_tasks as stk
        other = {"id": "t1", "status": "pending", "assignee_user_id": "u2", "created_by": "u3", "visible_to_client": False}
        with patch.object(stk, "sb_select", AsyncMock(return_value=[other])):
            with self.assertRaises(stk.StudioError):
                await stk.update_task("roove", "t1", {"title": "x"}, client_view=False, only_user="u1")

    async def test_assignee_submits_but_does_not_approve_without_permission(self):
        from services import studio_tasks as stk
        mine = {"id": "t1", "title": "Arte BF", "status": "in_progress", "assignee_user_id": "u1", "created_by": "u9", "visible_to_client": False}
        with patch.object(stk, "sb_select", AsyncMock(return_value=[mine])), \
             patch.object(stk, "sb_rpc", AsyncMock(return_value={"task": {**mine, "status": "internal_review"}, "outbox": None})), \
             patch.object(stk, "list_events", AsyncMock(return_value=[])):
            out = await stk.approval_action("roove", "t1", "submit", comment=None, user_id="u1", actor_name="liliu",
                                            is_agency=False, only_user="u1")
        self.assertEqual(out["task"]["status"], "internal_review")
        with self.assertRaises(stk.StudioError):
            await stk.approval_action("roove", "t1", "internal_approve", comment=None, user_id="u1", actor_name="liliu",
                                      is_agency=False, only_user="u1")

    async def test_new_task_from_restricted_member_is_assigned_to_them(self):
        from services import studio_tasks as stk
        insert = AsyncMock(return_value={"id": "t1", "title": "Minha", "status": "pending"})
        with patch.object(stk, "sb_insert", insert):
            await stk.create_task("roove", {"title": "Minha"}, user_id="u1", client_view=False, only_user="u1")
        self.assertEqual(insert.await_args.args[1]["assignee_user_id"], "u1")
