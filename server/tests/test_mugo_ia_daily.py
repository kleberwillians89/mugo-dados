"""Tira-dúvidas: "quanto vendi hoje", "ROAS dos últimos 10 dias" e resposta que veio cortada."""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import mugo_ia as mi
from services.studio_calendar import StudioError

TODAY = datetime.now(ZoneInfo("America/Sao_Paulo")).date()


def iso(back: int) -> str:
    return (TODAY - timedelta(days=back)).isoformat()


class DailySalesTests(unittest.IsolatedAsyncioTestCase):
    async def test_fbits_sales_with_spend_give_today_yesterday_and_roas(self):
        fbits = [{"stat_date": iso(b), "receita_oficial": 1000 + b, "pedidos": 4} for b in range(0, 12)]
        metrics = [{"metric_date": iso(b), "meta_spend": 50, "google_ads_spend": 50} for b in range(0, 12)]

        async def fake(table, **kwargs):
            return fbits if table == "fbits_order_daily_stats" else metrics
        with patch.object(mi, "sb_select", side_effect=fake):
            data = await mi.daily_sales("curavino")
        self.assertEqual(data["fonte_vendas"], "fbits")
        self.assertEqual(len(data["dias"]), mi.DAILY_DAYS)
        resumo = data["resumo"]
        self.assertEqual(resumo["hoje"]["receita"], 1000.0)
        self.assertTrue(resumo["hoje"]["parcial"])
        self.assertEqual(resumo["ontem"]["receita"], 1001.0)
        self.assertEqual(resumo["ultimos_10_dias"]["dias"], 10)      # hoje (parcial) fica fora das janelas
        self.assertEqual(resumo["ultimos_10_dias"]["investimento_midia"], 1000.0)
        self.assertAlmostEqual(resumo["ultimos_10_dias"]["roas"], round(sum(1000 + b for b in range(1, 11)) / 1000, 2))
        self.assertEqual(data["dias"][-1]["data"], TODAY.isoformat())

    async def test_shopify_fallback_and_nothing_returns_empty(self):
        metrics = [{"metric_date": iso(0), "shopify_net_revenue": 500, "shopify_orders": 2, "meta_spend": 100, "google_ads_spend": None}]

        async def fake(table, **kwargs):
            return [] if table == "fbits_order_daily_stats" else metrics
        with patch.object(mi, "sb_select", side_effect=fake):
            data = await mi.daily_sales("roove")
        self.assertEqual(data["fonte_vendas"], "shopify")
        self.assertEqual(data["resumo"]["hoje"]["roas"], 5.0)
        with patch.object(mi, "sb_select", AsyncMock(return_value=[])):
            self.assertEqual(await mi.daily_sales("vazio"), {})

    def test_prompt_tells_today_and_where_to_look(self):
        text = mi.build_prompt(context={"package": {}, "live": {"vendas_por_dia": {"hoje": "x"}}}, chunks=[], past=[], question="quanto vendi hoje?")
        self.assertIn(f"HOJE: {TODAY.isoformat()}", text)
        self.assertIn("vendas_por_dia", text)


class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def run_ask(self, llm):
        with patch.object(mi, "history", AsyncMock(return_value=[])), \
             patch.object(mi, "gather_context", AsyncMock(return_value={"package": {}, "live": {}, "gaps": []})), \
             patch("services.brand_knowledge.search_chunks", AsyncMock(return_value=[])), \
             patch.object(mi, "_client_name", AsyncMock(return_value="Curavino")), \
             patch("services.mugo_ia_web.research", AsyncMock(return_value={"status": "not_needed", "sources": []})), \
             patch("services.studio_engines.throttle"), patch("services.studio_llm.llm_json", llm), \
             patch.object(mi, "sb_insert", AsyncMock(return_value={"id": "m"})):
            return await mi.ask("curavino", "u1", "quanto eu vendi hoje e qual meu roas dos ultimos 10 dias", team=True)

    async def test_cut_answer_is_retried_with_more_room(self):
        ok = {"answer": "Hoje: R$ 1.000.", "on_topic": True, "sources": ["vendas_por_dia"], "used_chunks": [], "new_facts": [], "follow_ups": []}
        llm = AsyncMock(side_effect=[StudioError("AI_INVALID_OUTPUT"), ok])
        out = await self.run_ask(llm)
        self.assertEqual(out["answer"], "Hoje: R$ 1.000.")
        self.assertIn("Vendas por dia", out["sources"])
        self.assertEqual(llm.await_args_list[1].kwargs["max_output_tokens"], mi.RETRY_ANSWER_TOKENS)

    async def test_two_failures_give_a_clear_message_not_pautas(self):
        llm = AsyncMock(side_effect=[StudioError("AI_INVALID_OUTPUT"), {"answer": " "}])
        with self.assertRaises(StudioError) as raised:
            await self.run_ask(llm)
        self.assertIn("Pergunte de novo", str(raised.exception))
        self.assertNotIn("pauta", str(raised.exception).lower())

    async def test_other_errors_are_not_retried(self):
        llm = AsyncMock(side_effect=StudioError("AI_RATE_LIMIT"))
        with self.assertRaises(StudioError):
            await self.run_ask(llm)
        self.assertEqual(llm.await_count, 1)


if __name__ == "__main__":
    unittest.main()


class WisdomTests(unittest.TestCase):
    def test_own_sales_questions_do_not_go_to_the_web(self):
        from services.mugo_ia_web import category
        self.assertIsNone(category("quanto eu vendi hoje e qual meu roas dos ultimos 10 dias"))
        self.assertIsNone(category("como estão as vendas nesta semana?"))
        self.assertEqual(category("o que os concorrentes fizeram?"), "concorrentes")
        self.assertEqual(category("quais as tendências do mercado de vinho?"), "tendencias")

    def test_instructions_make_it_a_sector_specialist_without_inventing_numbers(self):
        text = mi.INSTRUCTIONS
        for part in ("ESPECIALISTA NO RAMO", "sazonalidade do setor", "concorrentes", "referência do mercado", "Nunca invente número"):
            self.assertIn(part, text)
