"""Metas conectadas à operação: diagnóstico, recomendações com confirmação, tarefa sem duplicar e alertas."""
import os
import sys
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import goal_ops as go  # noqa: E402
from services.studio_calendar import StudioError  # noqa: E402

GOAL = {"id": "g1", "client_id": "ruah", "metric": "revenue", "label": "Faturamento", "target_value": 100000, "period_start": "2026-11-01",
        "period_end": "2026-11-30", "status": "ABAIXO_DO_RITMO"}
ok = lambda v: {"available": True, "actual": v}  # noqa: E731


class CompareExplainTests(unittest.TestCase):
    def test_compare_per_day_and_level(self):
        c = go.compare("orders", ok(100), ok(70), 10, 10)
        self.assertEqual((c["trend"], round(c["change_percent"])), ("caiu", -30))
        self.assertEqual(go.compare("average_ticket", ok(200), ok(204), 10, 10)["trend"], "estável")
        self.assertIsNone(go.compare("orders", ok(10), {"available": False}, 5, 5))

    def test_hypothesis_only_when_numbers_sustain(self):
        labels = {"orders": "Pedidos", "average_ticket": "Ticket médio"}
        out = go.explain("revenue", {"orders": go.compare("orders", ok(100), ok(70), 10, 10), "average_ticket": go.compare("average_ticket", ok(200), ok(204), 10, 10)}, labels)
        self.assertIn("pedidos (caiu)", out["hypothesis"])
        self.assertIn("não uma causa comprovada", out["hypothesis"])
        both = go.explain("revenue", {"orders": go.compare("orders", ok(100), ok(70), 10, 10), "average_ticket": go.compare("average_ticket", ok(200), ok(150), 10, 10)}, labels)
        self.assertIsNone(both["hypothesis"])  # dois componentes mexeram: sem hipótese única


class DiagnosisTests(unittest.IsolatedAsyncioTestCase):
    async def test_halves_and_facts(self):
        async def actual(cid, metric, start, end):
            first = start == "2026-11-01"
            return ok({"revenue": 50000 if first else 35000, "orders": 250 if first else 175, "average_ticket": 200 if first else 200}[metric])
        with patch.object(go, "resolve_goal_actual", actual):
            out = await go.diagnosis("ruah", GOAL, today=date(2026, 11, 21))
        self.assertTrue(out["available"])
        self.assertEqual(out["periods"], [["2026-11-01", "2026-11-10"], ["2026-11-11", "2026-11-20"]])
        self.assertTrue(out["facts"][0].startswith("Faturamento por dia: caiu"))
        self.assertIn("pedidos", out["hypothesis"])

    async def test_short_period(self):
        out = await go.diagnosis("ruah", GOAL, today=date(2026, 11, 4))
        self.assertFalse(out["available"])


class RecommendAndTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_recommend_records_and_never_creates_task(self):
        llm = AsyncMock(return_value={"leitura": "Pedidos caíram.", "itens": [{"titulo": "Revisar verba", "tipo": "recomendacao", "evidencia": "pedidos -30%",
                                                                             "justificativa": "x", "acao": "Mover R$ 20/dia"}]})
        insert = AsyncMock(return_value={"id": "r1"})
        with patch.object(go, "diagnosis", AsyncMock(return_value={"available": False})), patch.object(go, "_context", AsyncMock(return_value={"meta": {"label": "F"}})), \
             patch("services.studio_llm.llm_json", llm), patch.object(go, "sb_insert", insert), \
             patch("services.studio_tasks.create_task", AsyncMock()) as create:
            out = await go.recommend("ruah", GOAL, "sem aumentar verba", user_id="u1")
        create.assert_not_awaited()
        self.assertEqual(out["id"], "r1")
        self.assertIn("sem aumentar verba", llm.await_args.kwargs["prompt"])
        self.assertEqual(llm.await_args.kwargs["brand"], "estrategia")
        self.assertIsNone(insert.await_args.args[1]["items"][0]["task_id"])

    async def test_task_from_item_links_goal_and_does_not_duplicate(self):
        row = {"id": "r1", "client_id": "ruah", "goal_id": "g1", "items": [{"titulo": "Revisar verba", "acao": "Mover", "evidencia": "e", "justificativa": "j", "task_id": None}]}
        create = AsyncMock(return_value={"id": "t9"})
        update = AsyncMock()
        with patch.object(go, "sb_select", AsyncMock(return_value=[row])), patch.object(go, "sb_update", update), patch("services.studio_tasks.create_task", create):
            out = await go.to_task("ruah", GOAL, "r1", 0, assignee_user_ids=["u2"], due_date="2026-11-28", user_id="u1", client_view=False, only_user=None)
        self.assertEqual(out, {"task_id": "t9", "created": True})
        data = create.await_args.args[1]
        self.assertIn("[meta:g1]", data["notes"]); self.assertIn("Evidência: e", data["notes"])
        self.assertEqual((data["assignee_user_ids"], data["due_date"]), (["u2"], "2026-11-28"))
        self.assertEqual(update.await_args.kwargs["patch"]["items"][0]["task_id"], "t9")
        done = {**row, "items": [{**row["items"][0], "task_id": "t9"}]}
        create.reset_mock()
        with patch.object(go, "sb_select", AsyncMock(return_value=[done])), patch("services.studio_tasks.create_task", create):
            again = await go.to_task("ruah", GOAL, "r1", 0, assignee_user_ids=[], due_date=None, user_id="u1", client_view=False, only_user=None)
        self.assertEqual(again, {"task_id": "t9", "created": False})
        create.assert_not_awaited()

    async def test_other_tenant_recommendation_is_not_found(self):
        with patch.object(go, "sb_select", AsyncMock(return_value=[{"id": "r1", "client_id": "outra", "items": [{}]}])):
            with self.assertRaises(StudioError):
                await go.to_task("ruah", GOAL, "r1", 0, assignee_user_ids=[], due_date=None, user_id="u1", client_view=False, only_user=None)


class AlertTests(unittest.TestCase):
    def test_performance_and_data_failures_are_separate(self):
        out = go.alerts([{"id": "a", "label": "A", "status": "NO_RITMO"}, {"id": "b", "label": "B", "status": "INDISPONIVEL", "reason": "Sem Shopify"},
                         {"id": "c", "label": "C", "status": "ABAIXO_DO_RITMO", "pace_note": "38% abaixo"}, {"id": "d", "label": "D", "status": "META_ATINGIDA"}])
        self.assertEqual([(a["goal_id"], a["kind"]) for a in out], [("c", "desempenho"), ("b", "dado"), ("d", "atingida")])
        self.assertIn("Sem Shopify", out[1]["text"])


if __name__ == "__main__":
    unittest.main()
