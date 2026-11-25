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

    async def test_explanations_and_improvements_by_campaign(self):
        campaigns = [{"id": "google:9", "canal": "Google", "campanha": "PMax", "objetivo": "Google Ads", "objetivo_id": "google",
                      "desde_o_inicio": mlr.google_kpis({"cost": 300, "clicks": 200, "impressions": 9000, "conversions": 6, "conversion_value": 1800}),
                      "ultimos_7_dias": {}, "sinais": []}]
        llm = AsyncMock(return_value={"resumo": "r", "campanhas": [{"id": "google:9", "veredito": "manter", "leitura": "l", "acao": "a"}],
                                      "explicacoes": [{"id": "google:9", "texto": "CPC de R$ 1,50 com 3% de conversão"}, {"id": "x", "texto": "inventada"}],
                                      "melhorias": [{"id": "google:9", "texto": "negativar termos de busca sem venda"}], "proximos_passos": []})
        with patch.object(mlr, "collect", AsyncMock(return_value=campaigns)), patch("services.studio_llm.llm_json", llm):
            out = await mlr.read("roove")
        self.assertEqual([e["campanha"] for e in out["explicacoes"]], ["PMax"])
        self.assertEqual(out["melhorias"][0]["canal"], "Google")
        self.assertEqual(out["campanhas"][0]["canal"], "Google")
        self.assertIn("Google Ads", llm.await_args.kwargs["instructions"])

    def test_days(self):
        self.assertEqual(mlr._days("2026-11-24", "2026-12-03", date(2026, 11, 24)), (0, 9))


class ChannelTests(unittest.IsolatedAsyncioTestCase):
    def test_meta_totals_by_objective(self):
        line = {"spend": "50", "impressions": "10000", "reach": "8000", "inline_link_clicks": "120",
                "actions": [{"action_type": "onsite_conversion.messaging_conversation_started_7d", "value": "9"}]}
        self.assertEqual(mlr.meta_totals(line, "whatsapp")["results"], 9)
        self.assertEqual(mlr.meta_totals(line, "alcance")["results"], 8000)

    def test_google_only_active_campaigns_with_7_days(self):
        rows = [{"campaign_id": "1", "campaign_name": "Pesquisa marca", "stat_date": f"2026-11-{d:02d}", "cost": 20, "impressions": 1000,
                 "clicks": 40, "conversions": 1, "conversion_value": 150} for d in range(1, 24)]
        rows += [{"campaign_id": "2", "campaign_name": "Pausada", "stat_date": "2026-11-05", "cost": 80, "impressions": 3000, "clicks": 10,
                  "conversions": 0, "conversion_value": 0}]
        out = mlr.google_campaigns(rows, date(2026, 11, 24))
        self.assertEqual([c["campanha"] for c in out], ["Pesquisa marca"])
        self.assertEqual(out[0]["ultimos_7_dias"]["investido"], 140)
        self.assertEqual(out[0]["desde_o_inicio"]["roas"], 7.5)
        self.assertIn("sincronizados até 2026-11-23", out[0]["sinais"][0])

    async def test_collect_joins_channels_and_survives_one_failing(self):
        meta = [{"id": "meta:1", "ultimos_7_dias": {"investido": 10}}]
        google = [{"id": "google:1", "ultimos_7_dias": {"investido": 90}}]
        with patch.object(mlr, "_meta_campaigns", AsyncMock(return_value=meta)), patch.object(mlr, "_google_campaigns", AsyncMock(return_value=google)):
            self.assertEqual([c["id"] for c in await mlr.collect("x", date(2026, 11, 24))], ["google:1", "meta:1"])
        with patch.object(mlr, "_meta_campaigns", AsyncMock(side_effect=RuntimeError("sem conta"))), \
                patch.object(mlr, "_google_campaigns", AsyncMock(return_value=google)):
            self.assertEqual([c["id"] for c in await mlr.collect("x", date(2026, 11, 24))], ["google:1"])

    async def test_meta_reads_whole_account_and_uses_draft_objective(self):
        from services import meta_ad_publisher as pub

        async def paged(path, token, params, pages=4):
            if path.endswith("/campaigns"):
                return [{"id": "11", "name": "Feita no Gerenciador", "objective": "OUTCOME_TRAFFIC", "start_time": "2026-11-01"},
                        {"id": "22", "name": "Do Mugoverso", "objective": "OUTCOME_SALES", "daily_budget": "5000"}]
            line = {"spend": "100", "impressions": "20000", "reach": "15000", "inline_link_clicks": "300",
                    "actions": [{"action_type": "link_click", "value": "300"}, {"action_type": "purchase", "value": "3"}],
                    "action_values": [{"action_type": "purchase", "value": "900"}]}
            return [{**line, "campaign_id": "11"}, {**line, "campaign_id": "22"}]

        drafts = [{"meta_ids": {"campaign_id": "22"}, "payload": {"objective": "remarketing", "name": "Remarketing BF", "daily_budget": 40}}]
        with patch.object(pub, "_ad_account", AsyncMock(return_value={"act": "act_1", "token": "t"})), \
                patch.object(pub, "list_drafts", AsyncMock(return_value=drafts)), patch("services.meta_live_insights._paged", paged):
            out = await mlr._meta_campaigns("x", date(2026, 11, 24))
        by = {c["id"]: c for c in out}
        self.assertEqual(by["meta:11"]["objetivo_id"], "trafego")
        self.assertFalse(by["meta:11"]["criada_no_mugoverso"])
        self.assertEqual(by["meta:22"]["objetivo_id"], "remarketing")
        self.assertEqual((by["meta:22"]["verba_diaria"], by["meta:22"]["desde_o_inicio"]["roas"]), (40, 9.0))


if __name__ == "__main__":
    unittest.main()
