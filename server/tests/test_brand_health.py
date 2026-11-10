"""Saúde da marca: períodos, índice, termos sensíveis, assuntos e o resumo montado a partir do banco."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from services import brand_health as bh


class PeriodTests(unittest.TestCase):
    def test_buckets_per_grain(self):
        self.assertEqual(bh.buckets_between(date(2026, 11, 4), date(2026, 11, 18), "week"),
                         [date(2026, 11, 2), date(2026, 11, 9), date(2026, 11, 16)])
        self.assertEqual(bh.buckets_between(date(2026, 2, 10), date(2026, 8, 1), "quarter"),
                         [date(2026, 1, 1), date(2026, 4, 1), date(2026, 7, 1)])
        self.assertEqual(bh.buckets_between(date(2025, 12, 31), date(2026, 1, 2), "year"), [date(2025, 1, 1), date(2026, 1, 1)])
        self.assertEqual(len(bh.buckets_between(date(2026, 1, 1), date(2026, 12, 31), "month")), 12)

    def test_invalid_periods(self):
        for start, end, grain in ((date(2026, 2, 1), date(2026, 1, 1), "week"), (date(2020, 1, 1), date(2026, 1, 1), "month"),
                                  (date(2024, 1, 1), date(2026, 1, 1), "day"), (date(2026, 1, 1), date(2026, 2, 1), "hour")):
            with self.assertRaises(bh.StudioError):
                bh.validate_period(start, end, grain)


class ScoreTests(unittest.TestCase):
    def test_net_and_index(self):
        split = {"positivo": 60, "neutro": 30, "misto": 0, "negativo": 10, "sem_analise": 50}
        self.assertEqual(bh.net_sentiment(split), 50)  # (60-10)/100
        self.assertEqual(bh.health_index(50, []), 80)  # 0.8*75 + 0.2*100
        self.assertEqual(bh.health_index(50, [{"severity": "alto"}, {"severity": "medio"}]), 73)  # 60 + 0.2*65
        self.assertIsNone(bh.net_sentiment({"sem_analise": 9}))
        self.assertEqual([bh.health_label(v) for v in (70, 69, 49, None)], ["Saudável", "Atenção", "Em risco", None])


class TermTests(unittest.TestCase):
    def test_accent_and_word_boundary(self):
        self.assertTrue(bh.term_hits("Meu pedido NAO CHEGOU ainda!", "não chegou"))
        self.assertTrue(bh.term_hits("caí num golpe?", "golpe"))
        self.assertFalse(bh.term_hits("golpeado de saudade", "golpe"))

    def test_findings_severity(self):
        mentions = ([{"source": "comments", "body": "não chegou meu pedido"}] * 5
                    + [{"source": "news", "body": "Perfumes falsificados apreendidos"}, {"source": "comments", "body": "procon nisso"}])
        found = {f["term"]: f for f in bh.term_findings(mentions, ["não chegou", "falsificado", "procon", "alergia"])}
        self.assertEqual(found["não chegou"]["severity"], "alto")
        self.assertNotIn("falsificado", found)  # "falsificados" não é a palavra inteira
        self.assertNotIn("procon", found)  # 1 comentário só não alerta
        found = {f["term"]: f for f in bh.term_findings(mentions, ["falsificados"])}
        self.assertEqual((found["falsificados"]["severity"], found["falsificados"]["sources"]), ("medio", ["news"]))

    def test_clean_terms(self):
        self.assertEqual(bh.clean_terms(["Golpe", "golpe ", "ok", "  Reclame   Aqui "]), ["Golpe", "Reclame Aqui"])


class SummaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_summary_fills_buckets_and_compares(self):
        cur = [{"bucket": "2026-11-02", "source": "comments", "sentiment": "positivo", "n": 8},
               {"bucket": "2026-11-02", "source": "comments", "sentiment": "negativo", "n": 2},
               {"bucket": "2026-11-09", "source": "news", "sentiment": "sem_analise", "n": 3}]
        prev = [{"bucket": "2026-01-01", "source": "comments", "sentiment": "positivo", "n": 5}]
        themes = [{"theme": "prazo de entrega", "sentiment": "negativo", "n": 2}]

        async def rpc(name, args):
            if name == "brand_health_themes":
                return themes if args["p_start"].startswith("2026-11-02") else []
            return cur if args["p_grain"] == "week" else prev
        with patch.object(bh, "sb_rpc", side_effect=rpc), patch.object(bh, "open_alerts", AsyncMock(return_value=[{"severity": "alto"}])):
            out = await bh.summary("ruah", start=date(2026, 11, 2), end=date(2026, 11, 15), grain="week", sources=["news", "comments", "x"])
        k = out["kpis"]
        self.assertEqual(out["sources"], ["news", "comments"])
        self.assertEqual((k["mentions"], k["mentions_previous"], k["mentions_change"], k["net"], k["unanalyzed"]), (13, 5, 160.0, 60, 3))
        self.assertEqual(k["index"], round(0.8 * 80 + 0.2 * 75))
        self.assertEqual([b["bucket"] for b in out["series"]], ["2026-11-02", "2026-11-09"])
        self.assertIsNone(out["series"][1]["net"])
        self.assertEqual(out["themes"][0], {"theme": "prazo de entrega", "mentions": 2, "previous": 0, "change": None, "tone": "negativo"})
        self.assertEqual(out["channels"][1]["mentions"], 10)

    async def test_client_view_hides_alerts(self):
        with patch.object(bh, "sb_rpc", AsyncMock(return_value=[])), patch.object(bh, "open_alerts", AsyncMock(return_value=[{"severity": "alto"}])):
            out = await bh.summary("ruah", start=date(2026, 11, 1), end=date(2026, 11, 10), grain="day", sources=[], with_alerts=False)
        self.assertEqual((out["alerts"], out["kpis"]["alerts_open"], out["kpis"]["index"]), ([], None, None))


class ScopeAndBackfillTests(unittest.IsolatedAsyncioTestCase):
    def test_view_counts_only_brand_news_and_not_own_comments(self):
        sql = (Path(__file__).resolve().parents[2] / "supabase/migrations/20261216_000095_brand_mentions_scope.sql").read_text(encoding="utf-8")
        self.assertIn("c.kind in ('marca', 'pessoa')", sql)
        self.assertIn("lower(mc.username) = lower(coalesce(m.username, ''))", sql)

    async def test_pending_news_get_analyzed_and_relevance_applied(self):
        from services import studio_clipping as sc
        pending = [{"id": f"c{i}", "url": f"https://n/{i}", "url_hash": "a" * 40, "title": f"Mugô {i}", "source": "G1",
                    "published_at": None, "kind": "marca", "term": "Mugô"} for i in range(3)]
        label = lambda rel: {"sentiment": "positivo", "summary": None, "main_theme": "agência", "entities": [], "relevance": rel,
                             "criticality": "baixa", "opportunities": [], "risks": [], "justification": None, "evidence": [], "analyzed_at": "x"}
        updates = []

        async def select(table, **kw):
            return pending if table == sc.CLIPPINGS else []
        async def update(table, *, filters, patch, returning="representation"):
            updates.append((filters["id"], patch))
        with patch.object(sc, "get_settings", AsyncMock(return_value={"saved": True, "min_relevance": 40, "ai_daily_limit": 60, "brand_terms": ["Mugô"]})), \
             patch.object(sc, "sb_select", side_effect=select), patch.object(sc, "sb_update", side_effect=update), \
             patch.object(sc, "_ai_budget", AsyncMock(return_value=2)), patch.object(sc, "_spend", AsyncMock()), \
             patch.object(sc, "_alert_team", AsyncMock(return_value=0)), \
             patch.object(sc, "_classify", AsyncMock(return_value={0: label(80), 1: label(10)})), \
             patch("services.studio_messages._client_name", AsyncMock(return_value="Mugô")):
            out = await sc.analyze_pending("mugo")
        self.assertEqual(out, {"news_analyzed": 2, "news_pending": 1})  # orçamento do dia = 2
        self.assertEqual([(i, p["relevant"]) for i, p in updates], [("eq.c0", True), ("eq.c1", False)])

    async def test_pending_stops_when_ai_down(self):
        from services import studio_clipping as sc
        with patch.object(sc, "get_settings", AsyncMock(return_value={"saved": True, "brand_terms": ["x"]})), \
             patch.object(sc, "sb_select", AsyncMock(return_value=[{"id": "c1", "url_hash": "b" * 40, "title": "t", "kind": "marca", "term": "x"}])), \
             patch.object(sc, "_classify", AsyncMock(return_value={})), patch.object(sc, "sb_update", AsyncMock()) as upd, \
             patch("services.studio_messages._client_name", AsyncMock(return_value="x")):
            out = await sc.analyze_pending("x", ignore_budget=True)
        self.assertEqual(out, {"news_analyzed": 0, "news_pending": 1})
        upd.assert_not_awaited()


class AudienceVoiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_summarizes_tone_and_themes_without_alerts(self):
        async def rpc(name, args):
            if name == "brand_health_themes":
                return [{"theme": "decant", "sentiment": "positivo", "n": 9}, {"theme": "prazo de entrega", "sentiment": "negativo", "n": 4},
                        {"theme": "tamanho", "sentiment": "neutro", "n": 3}]
            return [{"bucket": "2026-01-01", "source": "comments", "sentiment": "positivo", "n": 12},
                    {"bucket": "2026-01-01", "source": "comments", "sentiment": "negativo", "n": 4},
                    {"bucket": "2026-01-01", "source": "news", "sentiment": "sem_analise", "n": 50}]
        with patch.object(bh, "sb_rpc", side_effect=rpc):
            text = await bh.audience_voice("ruah")
        self.assertIn("16 menções analisadas", text)
        self.assertIn("sentimento líquido +50", text)
        self.assertIn("Elogiam: decant (9)", text)
        self.assertIn("Reclamam de: prazo de entrega (4)", text)
        self.assertIn("Perguntam sobre: tamanho (3)", text)
        self.assertNotIn("alerta", text.lower())

    async def test_none_without_analyzed_mentions_and_never_raises(self):
        with patch.object(bh, "sb_rpc", AsyncMock(return_value=[{"bucket": "2026-01-01", "source": "news", "sentiment": "sem_analise", "n": 5}])):
            self.assertIsNone(await bh.audience_voice("ruah"))
        with patch.object(bh, "sb_rpc", AsyncMock(side_effect=RuntimeError("db"))):
            self.assertIsNone(await bh.audience_voice("ruah"))
