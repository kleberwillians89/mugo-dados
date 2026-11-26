"""Índice de saúde MUGOVERSO: notas por pilar, pesos editáveis e redistribuição quando falta dado."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import asyncio
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from services import brand_health_index as bhi
from services.studio_calendar import StudioError


class ScoreTests(unittest.TestCase):
    def test_growth_score(self):
        self.assertEqual(bhi.growth_score(100, 100), 50)   # estável = meio da régua
        self.assertEqual(bhi.growth_score(150, 100), 90)   # +50%
        self.assertEqual(bhi.growth_score(50, 100), 10)    # −50%: queda pesa igual à alta
        self.assertEqual(bhi.growth_score(75, 100), 30)    # −25%
        self.assertEqual(bhi.growth_score(10, 100), 0)     # −90% (limitado)
        self.assertEqual(bhi.growth_score(5, 0), 60)       # saiu do zero: base pequena não é prova
        self.assertIsNone(bhi.growth_score(0, 0))
        self.assertIsNone(bhi.growth_score(None, 10))

    def test_share_score(self):
        self.assertEqual(bhi.share_score(10, 30), (25, 25.0))      # 1 concorrente: fatia justa 50%
        self.assertEqual(bhi.share_score(30, 10), (75, 75.0))
        self.assertEqual(bhi.share_score(10, 30, 3), (50, 25.0))   # 3 concorrentes: 25% é a fatia justa
        self.assertEqual(bhi.share_score(20, 20, 3), (100, 50.0))  # o dobro da fatia justa
        self.assertEqual(bhi.share_score(8, 0), (None, None))  # sem concorrente no radar

    def test_clean_weights(self):
        self.assertEqual(bhi.clean_weights(None), bhi.DEFAULT_WEIGHTS)
        w = bhi.clean_weights({"conversa": 150, "atencao": -3, "invasor": 9, "presenca": "x"})
        self.assertEqual(w["conversa"], 100)
        self.assertEqual(w["atencao"], 0)
        self.assertEqual(w["presenca"], bhi.DEFAULT_WEIGHTS["presenca"])
        self.assertNotIn("invasor", w)

    def test_compose_redistributes_missing_pillars(self):
        pillars = [{"key": "conversa", "score": 80}, {"key": "conversao", "score": None},
                   {"key": "atencao", "score": 50}, {"key": "presenca", "score": None}, {"key": "reputacao", "score": 100}]
        out = bhi.compose(pillars, dict(bhi.DEFAULT_WEIGHTS))
        # (80*30 + 50*20 + 100*10) / 60
        self.assertEqual(out["index"], 73)
        self.assertEqual(out["label"], "Saudável")
        self.assertEqual(out["coverage"], 60)
        self.assertEqual(pillars[0]["effective_weight"], 50.0)
        self.assertEqual(pillars[1]["effective_weight"], 0.0)

    def test_compose_respects_zero_weight_and_empty(self):
        pillars = [{"key": "conversa", "score": 20}, {"key": "atencao", "score": 100}]
        out = bhi.compose(pillars, {**bhi.DEFAULT_WEIGHTS, "conversa": 0})
        self.assertEqual(out["index"], 100)
        self.assertIsNone(bhi.compose([{"key": "conversa", "score": None}], dict(bhi.DEFAULT_WEIGHTS))["index"])


class ComputeTests(unittest.TestCase):
    def test_compute_links_all_pillars(self):
        async def ig(cid, start, end):
            return {"reach": 1200, "interactions": 300} if start.month == 11 else {"reach": 1000, "interactions": 300}

        async def sales(cid, start, end):
            return {"orders": 20, "revenue": 4000.0} if start.month == 11 else {"orders": 20, "revenue": 4000.0}

        with patch.object(bhi, "_conversation", AsyncMock(return_value={"net": 40, "analyzed": 50})), \
             patch.object(bhi.bh, "open_alerts", AsyncMock(return_value=[{"severity": "medio"}])), \
             patch.object(bhi, "get_weights", AsyncMock(return_value={"weights": dict(bhi.DEFAULT_WEIGHTS), "custom": False})), \
             patch.object(bhi, "_instagram_totals", side_effect=ig), \
             patch.object(bhi, "_sales_totals", side_effect=sales), \
             patch.object(bhi, "_news_share", AsyncMock(return_value={"marca": 3, "concorrente": 9})), \
             patch.object(bhi, "_instagram_share", AsyncMock(return_value=None)):
            out = asyncio.run(bhi.compute("c1", start=date(2026, 11, 1), end=date(2026, 11, 10)))
        scores = {p["key"]: p["score"] for p in out["pillars"]}
        self.assertEqual(scores, {"conversa": 70, "reputacao": 90, "atencao": 58, "conversao": 50, "presenca": 25})
        # (70*30 + 50*25 + 58*20 + 25*15 + 90*10) / 100 = 57.85
        self.assertEqual(out["index"], 58)
        self.assertEqual(out["label"], "Atenção")
        self.assertEqual(out["coverage"], 100)
        rep = next(p for p in out["pillars"] if p["key"] == "reputacao")
        self.assertEqual(rep["detail"], "Há pontos em acompanhamento pela equipe")  # cliente não vê o detalhe

    def test_compute_without_store_or_instagram(self):
        with patch.object(bhi, "_conversation", AsyncMock(return_value={"net": 0, "analyzed": 40})), \
             patch.object(bhi.bh, "open_alerts", AsyncMock(return_value=[])), \
             patch.object(bhi, "get_weights", AsyncMock(return_value={"weights": dict(bhi.DEFAULT_WEIGHTS), "custom": False})), \
             patch.object(bhi, "_instagram_totals", AsyncMock(return_value=None)), \
             patch.object(bhi, "_sales_totals", AsyncMock(return_value=None)), \
             patch.object(bhi, "_news_share", AsyncMock(side_effect=RuntimeError("rpc ausente"))):
            out = asyncio.run(bhi.compute("c1", start=date(2026, 11, 1), end=date(2026, 11, 10)))
        # (50*30 + 100*10) / 40
        self.assertEqual(out["index"], 63)
        missing = {p["key"]: p["reason"] for p in out["pillars"] if p["score"] is None}
        self.assertEqual(set(missing), {"conversao", "atencao", "presenca"})
        self.assertIn("Loja", missing["conversao"])


class PresenceTests(unittest.TestCase):
    def test_presence_blends_news_and_instagram_share(self):
        with patch.object(bhi, "_conversation", AsyncMock(return_value={"net": 0, "analyzed": 1})), \
             patch.object(bhi.bh, "open_alerts", AsyncMock(return_value=[])), \
             patch.object(bhi, "get_weights", AsyncMock(return_value={"weights": dict(bhi.DEFAULT_WEIGHTS), "custom": False})), \
             patch.object(bhi, "_instagram_totals", AsyncMock(return_value=None)), \
             patch.object(bhi, "_sales_totals", AsyncMock(return_value=None)), \
             patch.object(bhi, "_news_share", AsyncMock(return_value={"marca": 3, "concorrente": 9, "rivais": 3})), \
             patch.object(bhi, "_instagram_share", AsyncMock(return_value={"share": 40.0, "rivals": 3})):
            out = asyncio.run(bhi.compute("c1", start=date(2026, 11, 1), end=date(2026, 11, 10)))
        presence = next(p for p in out["pillars"] if p["key"] == "presenca")
        self.assertEqual(presence["score"], 65)  # 3 concorrentes (fatia justa 25%): notícias 25% → 50; Instagram 40% → 80
        self.assertIn("40% das interações no Instagram", presence["detail"])

    def test_instagram_only_still_scores(self):
        with patch.object(bhi, "_conversation", AsyncMock(return_value={"net": None, "analyzed": 0})), \
             patch.object(bhi.bh, "open_alerts", AsyncMock(return_value=[])), \
             patch.object(bhi, "get_weights", AsyncMock(return_value={"weights": dict(bhi.DEFAULT_WEIGHTS), "custom": False})), \
             patch.object(bhi, "_instagram_totals", AsyncMock(return_value=None)), \
             patch.object(bhi, "_sales_totals", AsyncMock(return_value=None)), \
             patch.object(bhi, "_news_share", AsyncMock(return_value={})), \
             patch.object(bhi, "_instagram_share", AsyncMock(return_value={"share": 30.0, "rivals": 1})):
            out = asyncio.run(bhi.compute("c1", start=date(2026, 11, 1), end=date(2026, 11, 10)))
        self.assertEqual(next(p for p in out["pillars"] if p["key"] == "presenca")["score"], 30)  # 1 concorrente: 30% contra fatia justa de 50%


class WeightsTests(unittest.TestCase):
    def test_all_zero_is_rejected(self):
        with self.assertRaises(StudioError):
            asyncio.run(bhi.save_weights("c1", {k: 0 for k in bhi.PILLARS}, user_id="u1"))

    def test_first_save_creates_row_with_alert_defaults(self):
        upsert = AsyncMock()
        settings = {"sensitive_terms": ["golpe"], "index_drop_points": 10, "negative_day_pct": 15, "saved": False}
        with patch.object(bhi.bh, "get_settings", AsyncMock(return_value=settings)), patch.object(bhi, "sb_upsert", upsert):
            out = asyncio.run(bhi.save_weights("c1", {"conversa": 50}, user_id="u1"))
        row = upsert.await_args.args[1][0]
        self.assertEqual(row["index_weights"]["conversa"], 50)
        self.assertEqual(row["sensitive_terms"], ["golpe"])
        self.assertTrue(out["custom"])


if __name__ == "__main__":
    unittest.main()



class AttentionPartialTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, prev):
        cur = {"reach": 3000, "interactions": 600, "days": 30}

        async def ig(cid, start, end):
            return cur if start.month == 11 or (start.month == 10 and start.day > 20) else prev
        with patch.object(bhi, "_conversation", AsyncMock(return_value=None)), \
             patch.object(bhi.bh, "open_alerts", AsyncMock(return_value=[])), \
             patch.object(bhi, "get_weights", AsyncMock(return_value={"weights": dict(bhi.DEFAULT_WEIGHTS), "custom": False})), \
             patch.object(bhi, "_instagram_totals", side_effect=ig), \
             patch.object(bhi, "_sales_totals", AsyncMock(return_value=None)), \
             patch.object(bhi, "_news_share", AsyncMock(return_value={})), \
             patch.object(bhi, "_instagram_share", AsyncMock(return_value=None)):
            out = await bhi.compute("roove", start=date(2026, 10, 21), end=date(2026, 11, 19))
        return next(p for p in out["pillars"] if p["key"] == "atencao")

    async def test_periodo_anterior_parcial_compara_pela_media_por_dia(self):
        pillar = await self._run({"reach": 2000, "interactions": 400, "days": 20})  # mesma média por dia
        self.assertEqual(pillar["score"], 50)
        self.assertIn("média por dia (20 de 30 dias", pillar["detail"])

    async def test_sem_historico_suficiente_explica_as_datas(self):
        pillar = await self._run({"reach": 1000, "interactions": 200, "days": 10})  # menos da metade dos dias
        self.assertIsNone(pillar["score"])
        self.assertIn("só 10 de 30 dias", pillar["reason"])
        self.assertIn("21/09 a 20/10", pillar["reason"])


class FairnessTests(unittest.TestCase):
    def test_weighted_net_shrinks_small_samples_and_halves_own_comments(self):
        self.assertEqual(bhi.weighted_net({"news": {"positivo": 5}}), 20)            # 5 elogios não viram +100
        self.assertEqual(bhi.weighted_net({"news": {"positivo": 300}}), 94)          # amostra grande quase não muda
        self.assertEqual(bhi.weighted_net({"comments": {"positivo": 40}}), 50)       # 40 comentários de fã = 20 de peso
        self.assertEqual(bhi.weighted_net({"news": {"negativo": 20, "positivo": 20}}), 0)
        self.assertIsNone(bhi.weighted_net({"news": {"sem_analise": 9}}))

    def _compute(self, conv, alerts):
        with patch.object(bhi, "_conversation", AsyncMock(return_value=conv)), \
             patch.object(bhi.bh, "open_alerts", AsyncMock(return_value=alerts)), \
             patch.object(bhi, "get_weights", AsyncMock(return_value={"weights": dict(bhi.DEFAULT_WEIGHTS), "custom": False})), \
             patch.object(bhi, "_instagram_totals", AsyncMock(return_value=None)), \
             patch.object(bhi, "_sales_totals", AsyncMock(return_value=None)), \
             patch.object(bhi, "_news_share", AsyncMock(return_value={})), \
             patch.object(bhi, "_instagram_share", AsyncMock(return_value=None)):
            out = asyncio.run(bhi.compute("c1", start=date(2026, 11, 1), end=date(2026, 11, 10)))
        return {p["key"]: p for p in out["pillars"]}

    def test_poucas_mencoes_ficam_fora_da_conta(self):
        p = self._compute({"net": 90, "analyzed": 12, "mentions": 15}, [])
        self.assertIsNone(p["conversa"]["score"])
        self.assertIn("só 12 menções analisadas", p["conversa"]["reason"])
        self.assertIsNone(p["reputacao"]["score"])  # sem alerta com 15 menções monitoradas não prova nada
        self.assertIn("15 menções monitoradas", p["reputacao"]["reason"])

    def test_alerta_conta_mesmo_com_pouca_mencao(self):
        p = self._compute({"net": 0, "analyzed": 5, "mentions": 5}, [{"severity": "alto"}])
        self.assertEqual(p["reputacao"]["score"], 75)


class CompareWithAvailableTests(unittest.IsolatedAsyncioTestCase):
    """Período anterior sem histórico: compara com o que existe, mesmo número de dias dos dois lados."""

    def _series(self, first: date, n: int, reach_from: int = 100, step: int = 0):
        from datetime import timedelta
        return [((first + timedelta(days=i)).isoformat(), reach_from + step * i, 10) for i in range(n)]

    def test_available_split_uses_equal_halves(self):
        series = self._series(date(2026, 7, 22), 40)
        out = bhi.available_split(series, 92)
        self.assertEqual(out["days"], 20)
        self.assertEqual((out["previous"]["from"], out["previous"]["to"]), ("2026-07-22", "2026-08-10"))
        self.assertEqual((out["current"]["from"], out["current"]["to"]), ("2026-08-11", "2026-08-30"))
        self.assertIsNone(bhi.available_split(series[:12], 92))  # 6 de cada lado: pouco para comparar

    async def test_compute_falls_back_to_available_history(self):
        cur_series = self._series(date(2026, 8, 21), 92, reach_from=100)
        prev_series = self._series(date(2026, 7, 22), 30, reach_from=100)

        async def ig(cid, start, end):
            series = cur_series if start.month == 8 and start.day == 21 else prev_series
            return {"reach": sum(x[1] for x in series), "interactions": sum(x[2] for x in series),
                    "days": len(series), "series": series}
        with patch.object(bhi, "_conversation", AsyncMock(return_value=None)), \
             patch.object(bhi.bh, "open_alerts", AsyncMock(return_value=[])), \
             patch.object(bhi, "get_weights", AsyncMock(return_value={"weights": dict(bhi.DEFAULT_WEIGHTS), "custom": False})), \
             patch.object(bhi, "_instagram_totals", side_effect=ig), \
             patch.object(bhi, "_sales_totals", AsyncMock(return_value=None)), \
             patch.object(bhi, "_news_share", AsyncMock(return_value={})), \
             patch.object(bhi, "_instagram_share", AsyncMock(return_value=None)):
            out = await bhi.compute("ruah", start=date(2026, 8, 21), end=date(2026, 11, 20))
        pillar = next(p for p in out["pillars"] if p["key"] == "atencao")
        self.assertEqual(pillar["score"], 50)  # mesmo alcance por dia nas duas metades = estável
        self.assertIn("comparado com o que existe: últimos 61 dias", pillar["detail"])
        self.assertNotIn("series", pillar["value"])


class MeasuredShareTests(unittest.TestCase):
    def test_concorrente_sem_dado_nao_vira_100_da_marca(self):
        rows = [{"is_brand": True, "interactions_in_period": 500}, {"is_brand": False, "interactions_in_period": 0}]
        self.assertEqual(bhi.share_against_measured(rows), {"share": None, "rivals": 0, "unmeasured": 1})
        rows.append({"is_brand": False, "interactions_in_period": 1500})
        self.assertEqual(bhi.share_against_measured(rows), {"share": 25.0, "rivals": 1})
