"""Aprovação e pedido de ajuste do cliente também viram mensagem na Conversa da marca (além do WhatsApp)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import studio_chat as sc
from services import studio_tasks as stk
from services import studio_team as st


class DecisionMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_adjust_goes_to_the_client_channel_with_the_comment(self):
        with patch.object(sc, "sb_insert", AsyncMock()) as insert:
            await sc.post_decision("roove", "ajuste_solicitado", title="Reels Black Friday", actor_name="Gabi",
                                   comment="Trocar a cor", item_id="i1", user_id="u1")
        row = insert.await_args.args[1]
        self.assertEqual((row["channel"], row["author_side"], row["author_name"], row["item_id"], row["author_id"]),
                         ("cliente", "cliente", "Gabi", "i1", "u1"))
        self.assertEqual(row["body"], "✎ Pediu ajuste em: Reels Black Friday\n“Trocar a cor”")

    async def test_approve_message_and_failure_never_raises(self):
        with patch.object(sc, "sb_insert", AsyncMock(side_effect=RuntimeError("down"))):
            await sc.post_decision("roove", "aprovado", title="Post", actor_name="Gabi")  # não levanta
        with patch.object(sc, "sb_insert", AsyncMock()) as insert:
            await sc.post_decision("roove", "comentario", title="Post", actor_name="Gabi")
        insert.assert_not_awaited()  # comentário já tem o próprio caminho

    async def test_notify_team_posts_the_decision_in_the_conversation(self):
        with patch.object(sc, "post_decision", AsyncMock()) as post, patch.object(st, "sb_insert", AsyncMock()), \
             patch.object(st, "_send", AsyncMock()), patch("services.studio_history.record", AsyncMock()):
            await st.notify_team("roove", {"id": "i1", "title": "Reels"}, "aprovado", actor_name="Gabi", user_id="u1")
        self.assertEqual(post.await_args.kwargs["item_id"], "i1")
        self.assertEqual(post.await_args.kwargs["user_id"], "u1")


class TaskDecisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_adjust_on_a_task_tells_the_team(self):
        task = {"id": "t1", "title": "Landing BF", "status": "client_review", "visible_to_client": True}
        with patch.object(stk, "_owned", AsyncMock(return_value=task)), \
             patch.object(stk, "sb_update", AsyncMock(return_value=[{**task, "status": "changes"}])), \
             patch.object(stk, "sb_insert", AsyncMock()), patch.object(stk, "list_events", AsyncMock(return_value=[])), \
             patch.object(stk, "task_view", lambda row, client_view: row), \
             patch.object(st, "notify_team", AsyncMock()) as notify:
            await stk.approval_action("roove", "t1", "client_changes", comment="Trocar o banner", user_id="u1",
                                      actor_name="gabi", is_agency=False)
        args, kwargs = notify.await_args
        self.assertEqual(args[1]["title"], "Tarefa: Landing BF")
        self.assertEqual(args[2], "ajuste_solicitado")
        self.assertEqual(kwargs["comment"], "Trocar o banner")

    async def test_team_actions_do_not_notify(self):
        task = {"id": "t1", "title": "Landing BF", "status": "internal_review", "visible_to_client": False}
        with patch.object(stk, "_owned", AsyncMock(return_value=task)), \
             patch.object(stk, "sb_update", AsyncMock(return_value=[{**task, "status": "completed"}])), \
             patch.object(stk, "sb_insert", AsyncMock()), patch.object(stk, "list_events", AsyncMock(return_value=[])), \
             patch.object(stk, "task_view", lambda row, client_view: row), \
             patch.object(st, "notify_team", AsyncMock()) as notify:
            await stk.approval_action("roove", "t1", "internal_approve", comment=None, user_id="u1", actor_name="kleber", is_agency=True)
        notify.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
