"""Mídia On enxuta: só campanhas ativas, resultado pelo objetivo e sinal por regra fixa (sem IA)."""
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import media_live_read as m  # noqa: E402


def camp(**extra):
    base = {"id": "meta:1", "canal": "Meta", "campanha": "Black Vendas", "objetivo": "Vendas", "objetivo_id": "vendas",
            "dias_no_ar": 12, "desde_o_inicio": {"investido": 900, "compras": 30, "custo_por_compra": 30, "roas": 4.2},
            "ultimos_7_dias": {"investido": 300, "compras": 10, "custo_por_compra": 30, "roas": 4.0}, "sinais": []}
    base.update(extra)
    return base


class VerdictTests(unittest.TestCase):
    def test_new_or_small_campaign_is_learning_not_judged(self):
        self.assertEqual(m.verdict(camp(dias_no_ar=1))["sinal"], "aprendendo")
        self.assertEqual(m.verdict(camp(desde_o_inicio={"investido": 20}))["sinal"], "aprendendo")

    def test_bad_signal_or_cost_rising_means_attention(self):
        v = m.verdict(camp(sinais=["frequência 4.1: o mesmo público está vendo várias vezes (risco de saturação)"]))
        self.assertEqual(v["sinal"], "atencao")
        self.assertTrue(v["motivo"].startswith("Frequência 4.1"))
        v = m.verdict(camp(ultimos_7_dias={"investido": 300, "compras": 5, "custo_por_compra": 60}))
        self.assertEqual(v["sinal"], "atencao")
        self.assertIn("100% acima da média", v["motivo"])

    def test_good_ctr_is_not_a_problem(self):
        self.assertEqual(m.verdict(camp(sinais=["CTR do link 2.10%: bom", "termina em 2 dia(s)"]))["sinal"], "bem")

    def test_result_follows_the_objective(self):
        self.assertEqual(m.headline("alcance", {"alcance": 5000, "cpm": 8})["label"], "pessoas alcançadas")
        self.assertEqual(m.headline("trafego", {"cliques_no_link": 300, "cpc_link": 0.5})["cost_label"], "custo por clique")
        self.assertEqual(m.headline("google", {"conversoes": 3, "custo_por_conversao": 40})["value"], 3)

    def test_recommendation_needs_enough_data(self):
        self.assertTrue(m.can_recommend(camp()))
        self.assertFalse(m.can_recommend(camp(dias_no_ar=4)))
        self.assertFalse(m.can_recommend(camp(desde_o_inicio={"investido": 60})))


class NowTests(unittest.IsolatedAsyncioTestCase):
    async def test_now_lists_only_what_collect_returns_as_active_with_no_ai(self):
        llm = AsyncMock()
        with patch.object(m, "collect", AsyncMock(return_value=[camp(), camp(id="google:9", canal="Google", objetivo="Google Ads",
                                                                       objetivo_id="google", dias_no_ar=None,
                                                                       desde_o_inicio={"investido": 400, "conversoes": 8, "custo_por_conversao": 50},
                                                                       ultimos_7_dias={"investido": 100, "conversoes": 2, "custo_por_conversao": 50})])), \
                patch("services.studio_llm.llm_json", llm):
            out = await m.now("roove")
        llm.assert_not_awaited()
        self.assertEqual([c["id"] for c in out["campaigns"]], ["meta:1", "google:9"])
        self.assertEqual(out["spend_7d"], 400)
        self.assertEqual(out["campaigns"][0]["resultado"]["label"], "compras")
        self.assertEqual(out["campaigns"][0]["sinal"], "bem")
        self.assertTrue(out["campaigns"][1]["recomendavel"])


if __name__ == "__main__":
    unittest.main()
