"""Leitura da IA das campanhas no ar: indicadores pelo objetivo, sinais e cache."""
import os
import sys
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import media_live_read as mlr  # noqa: E402

TRAFFIC = {"spend": 181.81, "impressions": 64000, "reach": 55956, "link_clicks": 1936, "results": 1936, "purchase_value": 0}
REACH = {"spend": 162.49, "impressions": 110000, "reach": 103904, "link_clicks": 126, "results": 103904, "purchase_value": 0}


class KpiTests(unittest.TestCase):
    def test_traffic_and_reach_have_no_roas(self):
        t = mlr.kpis("trafego", TRAFFIC)
        self.assertEqual(t["cpc_link"], 0.09)
        self.assertNotIn("roas", t)
        r = mlr.kpis("alcance", REACH)
        self.assertEqual(r["alcance"], 103904)
        self.assertAlmostEqual(r["cpm"], 1.48, places=2)
        self.assertNotIn("compras", r)

    def test_sales_kpis(self):
        v = mlr.kpis("vendas", {"spend": 200, "impressions": 20000, "reach": 15000, "link_clicks": 300, "results": 4, "purchase_value": 1200})
        self.assertEqual((v["compras"], v["custo_por_compra"], v["roas"]), (4, 50.0, 6.0))

    def test_flags(self):
        t = mlr.kpis("trafego", {**TRAFFIC, "impressions": 400000, "reach": 100000})
        f = mlr.flags("trafego", t, {"investido": 0}, days_running=1, days_left=2)
        text = " ".join(f)
        for piece in ("aprendizado", "frequência 4.0", "CTR do link 0.48%", "sem gasto nos últimos 7 dias", "termina em 2"):
            self.assertIn(piece, text)
        sales = mlr.kpis("vendas", {"spend": 150, "impressions": 5000, "reach": 4000, "link_clicks": 60, "results": 0, "purchase_value": 0})
        self.assertIn("nenhuma compra", " ".join(mlr.flags("vendas", sales, sales, days_running=10, days_left=None)))
        reach = mlr.kpis("alcance", REACH)
        self.assertNotIn("compra", " ".join(mlr.flags("alcance", reach, reach, days_running=10, days_left=None)))


class ReadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        mlr._CACHE.clear()

    async def test_read_uses_brain_strategy_and_maps_by_id_with_cache(self):
        campaigns = [{"id": "a", "campanha": "Tráfego", "objetivo": "Tráfego para o site", "objetivo_id": "trafego",
                      "desde_o_inicio": mlr.kpis("trafego", TRAFFIC), "ultimos_7_dias": {}, "sinais": []}]
        llm = AsyncMock(return_value={"resumo": "Clique a R$ 0,09.", "campanhas": [{"id": "a", "veredito": "escalar", "leitura": "ok", "acao": "subir"},
                                                                                {"id": "zzz", "veredito": "pausar", "leitura": "x", "acao": "y"}],
                                      "proximos_passos": ["remarketing"]})
        with patch.object(mlr, "collect", AsyncMock(return_value=campaigns)) as collect, patch("services.studio_llm.llm_json", llm):
            out = await mlr.read("ruah")
            again = await mlr.read("ruah")
            await mlr.read("ruah", refresh=True)
        self.assertEqual([c["id"] for c in out["campanhas"]], ["a"])  # id inventado pela IA é descartado
        self.assertEqual(out["campanhas"][0]["numeros"]["cpc_link"], 0.09)
        self.assertTrue(again["cached"])
        self.assertEqual(collect.await_count, 2)
        self.assertEqual(llm.await_args.kwargs["brand"], "estrategia")
        self.assertIn("PELO OBJETIVO DELA", llm.await_args.kwargs["instructions"])

    async def test_no_campaigns_no_ai(self):
        llm = AsyncMock()
        with patch.object(mlr, "collect", AsyncMock(return_value=[])), patch("services.studio_llm.llm_json", llm):
            out = await mlr.read("ruah")
        llm.assert_not_awaited()
        self.assertIn("Nenhuma campanha", out["message"])

    def test_days(self):
        self.assertEqual(mlr._days("2026-11-24", "2026-12-03", date(2026, 11, 24)), (0, 9))


if __name__ == "__main__":
    unittest.main()
