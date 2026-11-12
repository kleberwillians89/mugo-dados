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
        self.assertEqual(bhi.growth_score(100, 100), 60)   # estável
        self.assertEqual(bhi.growth_score(150, 100), 100)  # +50%
        self.assertEqual(bhi.growth_score(75, 100), 40)    # −25%
        self.assertEqual(bhi.growth_score(10, 100), 0)     # −90% (limitado)
        self.assertEqual(bhi.growth_score(5, 0), 80)       # saiu do zero
        self.assertIsNone(bhi.growth_score(0, 0))
        self.assertIsNone(bhi.growth_score(None, 10))

    def test_share_score(self):
        self.assertEqual(bhi.share_score(10, 30), (50, 25.0))
        self.assertEqual(bhi.share_score(30, 10), (100, 75.0))
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
        self.assertEqual(scores, {"conversa": 70, "reputacao": 90, "atencao": 68, "conversao": 60, "presenca": 50})
        # (70*30 + 60*25 + 68*20 + 50*15 + 90*10) / 100 = 66.1
        self.assertEqual(out["index"], 66)
        self.assertEqual(out["label"], "Atenção")
        self.assertEqual(out["coverage"], 100)
        rep = next(p for p in out["pillars"] if p["key"] == "reputacao")
        self.assertEqual(rep["detail"], "Há pontos em acompanhamento pela equipe")  # cliente não vê o detalhe

    def test_compute_without_store_or_instagram(self):
        with patch.object(bhi, "_conversation", AsyncMock(return_value={"net": 0, "analyzed": 10})), \
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
             patch.object(bhi, "_news_share", AsyncMock(return_value={"marca": 3, "concorrente": 9})), \
             patch.object(bhi, "_instagram_share", AsyncMock(return_value=40.0)):
            out = asyncio.run(bhi.compute("c1", start=date(2026, 11, 1), end=date(2026, 11, 10)))
        presence = next(p for p in out["pillars"] if p["key"] == "presenca")
        self.assertEqual(presence["score"], 65)  # notícias 25% → 50; Instagram 40% → 80
        self.assertIn("40% das interações no Instagram", presence["detail"])

    def test_instagram_only_still_scores(self):
        with patch.object(bhi, "_conversation", AsyncMock(return_value={"net": None, "analyzed": 0})), \
             patch.object(bhi.bh, "open_alerts", AsyncMock(return_value=[])), \
             patch.object(bhi, "get_weights", AsyncMock(return_value={"weights": dict(bhi.DEFAULT_WEIGHTS), "custom": False})), \
             patch.object(bhi, "_instagram_totals", AsyncMock(return_value=None)), \
             patch.object(bhi, "_sales_totals", AsyncMock(return_value=None)), \
             patch.object(bhi, "_news_share", AsyncMock(return_value={})), \
             patch.object(bhi, "_instagram_share", AsyncMock(return_value=30.0)):
            out = asyncio.run(bhi.compute("c1", start=date(2026, 11, 1), end=date(2026, 11, 10)))
        self.assertEqual(next(p for p in out["pillars"] if p["key"] == "presenca")["score"], 60)


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
