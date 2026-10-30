from __future__ import annotations

import math
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import media_plan as mp
from services import media_strategy as ms
from services.studio_calendar import StudioError

END = date(2026, 10, 28)


def daily(spend_by_week, roas=5.0, b=0.7, cpm=10.0, ctr=0.02, cr=0.02, days_active=7):
    """90 dias sintéticos em que receita = k·gasto^b por semana (b conhecido para o ajuste recuperar)."""
    rows = []
    for w, weekly_spend in enumerate(spend_by_week):
        weekly_rev = roas * 1000 * (weekly_spend / 1000) ** b if weekly_spend else 0
        for d in range(7):
            day = END - timedelta(days=(len(spend_by_week) - 1 - w) * 7 + (6 - d))
            s = weekly_spend / days_active if d < days_active else 0
            impressions = s / cpm * 1000 if s else 0
            clicks = impressions * ctr
            rows.append({"date": day.isoformat(), "spend": s, "impressions": impressions, "clicks": clicks,
                         "conversions": clicks * cr, "revenue": weekly_rev / days_active if d < days_active else 0})
    return rows


class CurveTests(unittest.TestCase):
    def test_fit_recovers_measured_elasticity_when_budget_varies(self):
        rows = daily([600, 800, 1000, 1400, 1800, 2400, 3000, 1200, 900, 2000, 2600, 1600, 1100], b=0.6)
        curve = ms.curves_for(ms.weekly(rows, END))["revenue"]
        self.assertEqual(curve["fit"], "medida")
        self.assertAlmostEqual(curve["b"], 0.6, delta=0.05)

    def test_flat_budget_falls_back_to_conservative_reference(self):
        curve = ms.curves_for(ms.weekly(daily([1000] * 13), END))["revenue"]
        self.assertEqual((curve["fit"], curve["b"]), ("estimada", ms.DEFAULT_B["revenue"]))
        # calibrada no resultado médio real: 1000/semana → ~5000/semana
        self.assertAlmostEqual(ms.project(curve, 1000 * 30 / 7, 30), 5000 * 30 / 7, delta=5)

    def test_diminishing_returns(self):
        curve = {"a": 10.0, "b": 0.7}
        self.assertLess(ms.project(curve, 20000, 30) / 20000, ms.project(curve, 10000, 30) / 10000)
        self.assertEqual(ms.project(curve, 0, 30), 0.0)


def diag(conf="boa", monthly=3000):
    return {"confidence": conf, "monthly_spend": monthly}


class OptimizerTests(unittest.TestCase):
    CURVES = {"meta": {m: {"a": 50.0, "b": 0.6} for m in ms.DEFAULT_B}, "google_ads": {m: {"a": 20.0, "b": 0.8} for m in ms.DEFAULT_B}}

    def test_allocation_sums_budget_and_respects_limits(self):
        alloc = ms.optimize(self.CURVES, {"meta": diag(), "google_ads": diag("baixa", 500)}, 6000, "revenue", 30)
        self.assertAlmostEqual(sum(alloc.values()), 6000, delta=1)
        self.assertGreaterEqual(alloc["google_ads"], 6000 * ms.MIN_ACTIVE_SHARE - 1)
        self.assertLessEqual(alloc["google_ads"], min(6000 * ms.LOW_CONFIDENCE_CAP, 500 * ms.MAX_GROWTH) + 1)

    def test_optimal_beats_even_split(self):
        d = {"meta": diag(monthly=4000), "google_ads": diag(monthly=4000)}
        alloc = ms.optimize(self.CURVES, d, 6000, "revenue", 30)
        best = ms.outcome(self.CURVES, alloc, 30)["totals"]["revenue"]
        even = ms.outcome(self.CURVES, {"meta": 3000, "google_ads": 3000}, 30)["totals"]["revenue"]
        self.assertGreaterEqual(best, even)

    def test_estimated_curve_grows_less(self):
        curves = {c: {m: {**v, "fit": "estimada" if c == "google_ads" else "medida"} for m, v in s.items()} for c, s in self.CURVES.items()}
        curves["google_ads"] = {m: {"a": 200.0, "b": 0.9, "fit": "estimada"} for m in ms.DEFAULT_B}  # google "parece" muito melhor
        alloc = ms.optimize(curves, {"meta": diag(monthly=3000), "google_ads": diag(monthly=1000)}, 6000, "revenue", 30)
        self.assertLessEqual(alloc["google_ads"], 1000 * ms.MAX_GROWTH_ESTIMATED + 1)

    def test_single_channel_takes_everything(self):
        alloc = ms.optimize(self.CURVES, {"meta": diag()}, 5000, "revenue", 30)
        self.assertEqual(alloc, {"meta": 5000.0})

    def test_efficiency_budget_stops_where_marginal_roas_drops(self):
        d = {"meta": diag(monthly=3000)}
        eff = ms.efficiency_budget(self.CURVES, d, 30, "revenue", 1.0, 3000)
        alloc = ms.optimize(self.CURVES, d, eff, "revenue", 30)
        self.assertGreaterEqual(ms.marginal_roas(self.CURVES, alloc, 30), 1.0)

    def test_goal_budget_uses_elasticity_and_caps_at_3x(self):
        store = {"revenue": 100000, "investment": 10000}
        g = ms.goal_budget(120000, store, 0.7)
        self.assertAlmostEqual(g["budget"], round(10000 * (1.2 ** (1 / 0.7)), -1), delta=10)
        self.assertFalse(g["capped"])
        self.assertTrue(ms.goal_budget(1000000, store, 0.7)["capped"])
        self.assertIsNone(ms.goal_budget(None, store, 0.7))


class CampaignAndCalendarTests(unittest.TestCase):
    def test_campaign_actions(self):
        channel = {"spend": 10000, "roas": 4.0, "cpa": 50.0}
        rows = [
            {"campaign_name": "Remarketing", "spend": 2000, "conversions": 60, "revenue": 12000},   # ROAS 6
            {"campaign_name": "Prospecção", "spend": 3000, "conversions": 50, "revenue": 9000},     # ROAS 3
            {"campaign_name": "Teste novo", "spend": 600, "conversions": 0, "revenue": 0},
            {"campaign_name": "Amostra", "spend": 300, "conversions": 2, "revenue": 900},
            {"campaign_name": "Média", "spend": 2500, "conversions": 50, "revenue": 10000},       # ROAS 4
            {"campaign_name": "Troco", "spend": 10, "conversions": 0, "revenue": 0},
        ]
        out = {r["campaign"]: r["action"] for r in ms.classify_campaigns("meta", rows, channel, "revenue")}
        self.assertEqual(out, {"Remarketing": "escalar", "Prospecção": "otimizar", "Teste novo": "pausar",
                               "Amostra": "aprender", "Média": "manter"})

    def test_weeks_weight_commercial_dates_and_sum_budget(self):
        weeks = ms.month_weeks(date(2026, 11, 1), 10000)
        self.assertAlmostEqual(sum(w["budget"] for w in weeks), 10000, delta=1)
        self.assertEqual((weeks[0]["start"], weeks[0]["end"]), ("2026-11-01", "2026-11-08"))  # domingo 1º junta com a semana seguinte
        self.assertEqual(weeks[-1]["end"], "2026-11-30")
        self.assertTrue(all((date.fromisoformat(w["end"]) - date.fromisoformat(w["start"])).days >= 2 for w in weeks))
        bf = next(w for w in weeks if "Black Friday" in w["dates"])
        before = weeks[weeks.index(bf) - 1]
        self.assertIn("Black Friday", before["prepares"])
        base = min(weeks, key=lambda w: w["daily"])
        self.assertEqual(bf["phase"], "pico")
        self.assertGreater(bf["daily"], base["daily"] * 1.4)

    def test_guardrails_respect_margin(self):
        result = {"channels": {"meta": {"spend": 3000, "cpa": 40.0, "roas": 3.0}}}
        g = ms.guardrails(result, 30, 0.4)[0]
        self.assertEqual((g["daily_budget"], g["max_cpa"], g["breakeven_roas"], g["min_roas"]), (100.0, 52.0, 2.5, 2.5))


class BoostPlanTests(unittest.TestCase):
    WEEKS = ms.month_weeks(date(2026, 11, 1), 10000)

    def item(self, i, day, fmt="reels", status="aprovado", seasonal=None):
        return {"id": i, "title": f"Post {i}", "format": fmt, "status": status, "signals": {"seasonal": seasonal} if seasonal else {},
                "scheduled_at": f"2026-11-{day:02d}T22:00:00+00:00"}

    def test_boosts_follow_calendar_dates_and_split_meta_pool(self):
        items = [self.item("a", 5, "imagem"), self.item("b", 24, "reels", seasonal="Black Friday"), self.item("c", 10, "carrossel"),
                 self.item("d", 12, "reels", status="rejeitado"), self.item("e", 3, "stories")]
        plan = ms.boost_plan(items, self.WEEKS, meta_budget=5000, meta_cpm=10.0,
                             format_reach={"reels": 3000, "carrossel": 2000, "imagem": 900}, today=date(2026, 11, 1))
        self.assertEqual(plan["pool"], 1000.0)
        ids = [p["item_id"] for p in plan["posts"]]
        self.assertNotIn("d", ids)   # rejeitada
        self.assertNotIn("e", ids)   # stories
        bf = next(p for p in plan["posts"] if p["item_id"] == "b")
        self.assertEqual(bf["start"], "2026-11-24")                 # semana de pico: começa no dia de publicar
        normal = next(p for p in plan["posts"] if p["item_id"] == "c")
        self.assertEqual(normal["start"], "2026-11-11")             # 24 h depois de publicar
        self.assertEqual(normal["end"], "2026-11-17")
        self.assertGreater(bf["budget"], normal["budget"])
        self.assertAlmostEqual(sum(p["budget"] for p in plan["posts"]), 1000, delta=1)
        self.assertEqual(bf["impressions"], int(bf["budget"] / 10 * 1000))

    def test_past_posts_and_empty_calendar(self):
        plan = ms.boost_plan([self.item("a", 2)], self.WEEKS, meta_budget=5000, meta_cpm=10, format_reach={}, today=date(2026, 11, 20))
        self.assertEqual(plan["posts"], [])
        empty = ms.boost_plan([], self.WEEKS, meta_budget=5000, meta_cpm=10, format_reach={}, today=date(2026, 11, 1))
        self.assertIn("Gere o calendário", empty["note"])


class BuildStrategyTests(unittest.IsolatedAsyncioTestCase):
    async def test_end_to_end_with_real_shaped_data(self):
        meta = {"daily": daily([1500, 1800, 2000, 2400, 2800, 3200, 2600, 2200, 1900, 2500, 3000, 2700, 2300], b=0.65),
                "campaigns": [{"campaign_name": "Remarketing", "spend": 3000, "conversions": 80, "revenue": 24000},
                              {"campaign_name": "Sem venda", "spend": 900, "conversions": 0, "revenue": 0}]}
        google = {"daily": [], "campaigns": [], "disconnected": True}
        items = [{"id": "x", "title": "Black Friday Oud", "format": "reels", "status": "aprovado", "signals": {"seasonal": "Black Friday"},
                  "scheduled_at": "2026-11-25T22:00:00+00:00"}]
        with patch.object(ms, "read_window", AsyncMock(return_value={"meta": meta, "google_ads": google})), \
             patch.object(ms, "_store_and_goal", AsyncMock(return_value=({"revenue": 90000, "investment": 9000}, 120000, []))), \
             patch.object(ms, "_calendar_context", AsyncMock(return_value=(items, {"reels": 3000}))), \
             patch.object(ms, "campaign_memory", AsyncMock(return_value={})):
            s = await ms.build_strategy("ruah", month="2026-11", objective="vendas", margin=0.4, today=date(2026, 10, 29))
        keys = [sc["key"] for sc in s["scenarios"]]
        self.assertIn("ritmo_atual", keys)
        self.assertIn("meta", keys)
        for sc in s["scenarios"]:
            self.assertAlmostEqual(sum(sc["allocation"].values()), sc["budget"], delta=1)
            # equilibrado: Google sem histórico entra como teste estimado (20% a 40% da verba)
            self.assertGreaterEqual(sc["allocation"]["google_ads"], sc["budget"] * ms.TEST_SHARE - 1)
            self.assertLessEqual(sc["allocation"]["google_ads"], sc["budget"] * ms.REFERENCE_CAP + 1)
        self.assertEqual(s["channel_kind"], {"meta": "dados", "google_ads": "referencia"})
        self.assertIsNone(s["reference_inputs"]["google_ads"]["ticket"])  # loja sem pedidos no mock: ticket não inventado
        chosen = next(sc for sc in s["scenarios"] if sc["key"] == s["selected"])
        for channel, budget in chosen["allocation"].items():
            planned = sum(c["planned_budget"] for c in s["campaigns"] if c["channel"] == channel)
            self.assertAlmostEqual(planned, budget, delta=2)  # verba das campanhas fecha com a do canal
        self.assertTrue(any(c.get("suggested") and c["channel"] == "google_ads" for c in s["campaigns"]))
        self.assertEqual(s["selected"], s["recommended"])
        self.assertTrue(any("sem conversão" in f["text"] for f in s["findings"]))
        self.assertEqual(s["campaigns"][0]["action"], "escalar")
        self.assertEqual(s["boosts"]["posts"][0]["item_id"], "x")
        self.assertAlmostEqual(sum(w["budget"] for w in s["weeks"]),
                               next(sc for sc in s["scenarios"] if sc["key"] == s["selected"])["budget"], delta=1)

    async def test_no_paid_data_and_validation(self):
        empty = {"daily": [], "campaigns": []}
        with patch.object(ms, "read_window", AsyncMock(return_value={"meta": empty, "google_ads": empty})):
            with self.assertRaises(StudioError) as err:
                await ms.build_strategy("ruah", month="2026-11", objective="vendas", today=date(2026, 10, 29))
        self.assertEqual(err.exception.code, "NO_PAID_HISTORY")
        with self.assertRaises(StudioError):
            await ms.build_strategy("ruah", month="2026-11", objective="vendas", margin=0.99)

    async def test_narrative_only_cites_listed_campaigns(self):
        strategy = {"objective": "vendas", "metric_label": "receita", "selected": "ritmo_atual", "findings": [], "weeks": [],
                    "diagnosis": [], "goal_revenue": None, "store": {}, "boosts": {"posts": []},
                    "campaigns": [{"channel": "meta", "campaign": "Remarketing", "action": "escalar", "why": "x", "spend": 1, "roas": 5, "cpa": 2}],
                    "scenarios": [{"key": "ritmo_atual", "label": "Ritmo atual", "budget": 1000, "allocation": {"meta": 1000},
                                   "result": {"totals": {}}, "marginal_roas": 2.0}]}
        llm = AsyncMock(return_value={"headline": "h", "thesis": "t", "channel_roles": [{"channel": "meta", "role": "r", "rationale": "x"}],
                                      "campaign_notes": [{"campaign": "Remarketing", "note": "escalar"}, {"campaign": "Inventada", "note": "x"}],
                                      "creative_guidance": [], "risks": [], "next_7_days": ["a"]})
        with patch("services.studio_engines.throttle"), patch("services.studio_intelligence.build_content_intelligence", AsyncMock(return_value={})), \
             patch("services.studio_llm.llm_json", llm):
            out = await ms.narrative("ruah", strategy)
        self.assertEqual([n["campaign"] for n in out["campaign_notes"]], ["Remarketing"])
        enum = llm.await_args.kwargs["schema"]["properties"]["campaign_notes"]["items"]["properties"]["campaign"]["enum"]
        self.assertEqual(enum, ["Remarketing"])


class PlanTests(unittest.IsolatedAsyncioTestCase):
    def test_allocation_must_match_budget(self):
        self.assertEqual(mp.clean_allocation({"meta": 600, "google_ads": 400, "x": 9}, 1000), {"meta": 600.0, "google_ads": 400.0})
        with self.assertRaises(StudioError):
            mp.clean_allocation({"meta": 500}, 1000)

    async def test_plan_vs_actual_uses_frozen_strategy_targets(self):
        plan = {"budget": 3000, "allocation": {"meta": 3000},
                "strategy": {"scenario": {"result": {"channels": {"meta": {"cpa": 40.0, "roas": 4.0}}}}}}
        actual = {"meta": {"spend": 1000, "conversions": 20, "revenue": 5000, "cpa": 50.0, "roas": 5.0},
                  "google_ads": {"spend": 0}}
        with patch.object(mp, "get_plan", AsyncMock(return_value=plan)), patch.object(mp, "_actual", AsyncMock(return_value=actual)), \
             patch.object(mp, "datetime") as dt:
            dt.now.return_value.date.return_value = date(2026, 11, 11)
            out = await mp.plan_vs_actual("ruah", "2026-11")
        row = out["channels"][0]
        self.assertEqual((out["elapsed_days"], row["expected_to_date"], row["projected_spend"]), (10, 1000.0, 3000.0))
        self.assertEqual((row["pace"], row["target_cpa"]), (1.0, 40.0))
        self.assertEqual(len(out["channels"]), 1)  # canal sem plano e sem gasto fica de fora


if __name__ == "__main__":
    unittest.main()


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    STRATEGY = {"month": "2026-11-01", "selected": "meta", "narrative": {"headline": "Manchete"},
                "scenarios": [{"key": "ritmo_atual", "budget": 1000}, {"key": "meta", "budget": 1500}]}

    @staticmethod
    def http_error(status, text=""):
        import httpx
        request = httpx.Request("POST", "https://sb/rest/v1/x")
        return httpx.HTTPStatusError("erro", request=request, response=httpx.Response(status, text=text, request=request))

    async def test_every_generation_is_recorded_with_summary(self):
        with patch.object(mp, "sb_insert", AsyncMock(return_value={"id": "s1", "created_at": "2026-10-30T10:00:00Z"})) as insert:
            out = await mp.record_strategy("ruah", self.STRATEGY, objective="vendas", margin=0.4, custom_budget=None, user_id="u1")
        row = insert.await_args.args[1]
        self.assertEqual((row["client_id"], row["month"], row["selected"], row["budget"], row["headline"]), ("ruah", "2026-11-01", "meta", 1500, "Manchete"))
        self.assertIs(row["strategy"], self.STRATEGY)
        self.assertEqual(out, {"saved": True, "id": "s1", "created_at": "2026-10-30T10:00:00Z"})

    async def test_missing_table_is_reported_not_raised(self):
        with patch.object(mp, "sb_insert", AsyncMock(side_effect=self.http_error(404))):
            out = await mp.record_strategy("ruah", self.STRATEGY, objective="vendas", margin=None, custom_budget=None, user_id="u1")
        self.assertEqual(out, {"saved": False, "reason": "MIGRATION_056_PENDING"})
        with patch.object(mp, "sb_select", AsyncMock(side_effect=self.http_error(404))):
            self.assertEqual(await mp.list_strategies("ruah", "2026-11"), [])

    async def test_history_lookup_is_scoped_to_company(self):
        row = {"id": "s1", "objective": "vendas", "margin": 0.4, "custom_budget": None, "strategy": {"month": "2026-11-01"}, "created_at": "t"}
        with patch.object(mp, "sb_select", AsyncMock(return_value=[row])) as select:
            out = await mp.get_strategy("ruah", "s1")
        self.assertEqual(select.await_args.kwargs["filters"], {"client_id": "eq.ruah", "id": "eq.s1"})
        self.assertEqual((out["strategy_id"], out["generated_at"], out["month"]), ("s1", "t", "2026-11-01"))
        with patch.object(mp, "sb_select", AsyncMock(return_value=[])):
            with self.assertRaises(StudioError):
                await mp.get_strategy("ruah", "outra")

    async def test_save_plan_names_the_missing_migration(self):
        data = {"objective": "vendas", "scenario": "meta", "budget": 1000, "allocation": {"meta": 1000}, "strategy": {}}
        for error, code in ((self.http_error(400, 'Could not find the "strategy" column'), "MIGRATION_055_PENDING"),
                            (self.http_error(404), "MIGRATION_054_PENDING")):
            with self.subTest(code=code), patch.object(mp, "get_plan", AsyncMock(return_value=None)), \
                 patch.object(mp, "sb_upsert", AsyncMock(side_effect=error)):
                with self.assertRaises(StudioError) as err:
                    await mp.save_plan("ruah", "2026-11", data, user_id="u1")
                self.assertEqual(err.exception.code, code)


class MinimumDailyTests(unittest.TestCase):
    WEEKS = ms.month_weeks(date(2026, 11, 1), 3000)

    def item(self, i, day, fmt="reels"):
        return {"id": i, "title": f"Post {i}", "format": fmt, "status": "aprovado", "signals": {}, "scheduled_at": f"2026-11-{day:02d}T22:00:00+00:00"}

    def test_boosts_never_below_10_per_day(self):
        items = [self.item(str(i), d) for i, d in enumerate([3, 6, 9, 12, 15, 18, 21, 24])]
        plan = ms.boost_plan(items, self.WEEKS, meta_budget=1500, meta_cpm=10.0, format_reach={}, today=date(2026, 11, 1))  # pool R$ 300
        self.assertTrue(plan["posts"])
        self.assertLess(len(plan["posts"]), 8)
        for p in plan["posts"]:
            self.assertGreaterEqual(p["daily"], ms.MIN_DAILY)
        self.assertAlmostEqual(sum(p["budget"] for p in plan["posts"]), 300, delta=1)

    def test_tiny_pool_shortens_or_skips(self):
        plan = ms.boost_plan([self.item("a", 5)], self.WEEKS, meta_budget=250, meta_cpm=10.0, format_reach={}, today=date(2026, 11, 1))  # R$ 50
        post = plan["posts"][0]
        self.assertGreaterEqual(post["daily"], ms.MIN_DAILY)
        self.assertEqual((date.fromisoformat(post["end"]) - date.fromisoformat(post["start"])).days + 1, 5)
        none = ms.boost_plan([self.item("a", 5)], self.WEEKS, meta_budget=100, meta_cpm=10.0, format_reach={}, today=date(2026, 11, 1))  # R$ 20
        self.assertEqual(none["posts"], [])
        self.assertIn("R$ 10/dia", none["note"])

    def test_channels_get_at_least_10_per_day_or_drop_out(self):
        curves = {"meta": {m: {"a": 50.0, "b": 0.6, "fit": "medida"} for m in ms.DEFAULT_B},
                  "google_ads": {m: {"a": 20.0, "b": 0.8, "fit": "medida"} for m in ms.DEFAULT_B}}
        d = {"meta": {"confidence": "boa", "monthly_spend": 3000, "recent": {"roas": 5}},
             "google_ads": {"confidence": "boa", "monthly_spend": 3000, "recent": {"roas": 3}}}
        alloc = ms.optimize(curves, d, 2000, "revenue", 30)
        self.assertTrue(all(v / 30 >= ms.MIN_DAILY - 0.01 for v in alloc.values()))
        small = ms.optimize(curves, d, 450, "revenue", 30)  # não paga R$ 10/dia nos dois canais
        self.assertEqual(small, {"meta": 450.0})


class ChannelsWithoutHistoryTests(unittest.IsolatedAsyncioTestCase):
    STORE = {"revenue": 60000, "orders": 300, "sessions": 20000, "investment": 0}

    def test_reference_curve_uses_store_conversion_and_ticket(self):
        curves, inputs = ms.reference_curves("meta", self.STORE, 600, 30)
        self.assertEqual(inputs["ticket"], 200.0)
        self.assertAlmostEqual(inputs["cvr"], 300 / 20000 * 0.8, places=4)
        self.assertEqual(curves["revenue"]["fit"], "referencia")
        conv = ms.project(curves["conversions"], 600, 30)
        expected = 600 / 18 * 1000 * 0.012 * inputs["cvr"]
        self.assertAlmostEqual(conv, expected, delta=expected * 0.01)
        self.assertAlmostEqual(ms.project(curves["revenue"], 600, 30), conv * 200, delta=conv * 2)

    async def run_build(self, data, **kw):
        with patch.object(ms, "read_window", AsyncMock(return_value=data)), \
             patch.object(ms, "_store_and_goal", AsyncMock(return_value=(self.STORE, None, []))), \
             patch.object(ms, "_calendar_context", AsyncMock(return_value=([], {}))), \
             patch.object(ms, "campaign_memory", AsyncMock(return_value={})):
            return await ms.build_strategy("origami", month="2026-11", today=date(2026, 10, 29), **kw)

    async def test_no_history_at_all_builds_plan_from_budget(self):
        empty = {"daily": [], "campaigns": []}
        s = await self.run_build({"meta": empty, "google_ads": empty}, objective="alcance", custom_budget=1000)
        self.assertEqual([sc["key"] for sc in s["scenarios"]], ["personalizado"])
        alloc = s["scenarios"][0]["allocation"]
        self.assertEqual(set(alloc), {"meta", "google_ads"})
        self.assertAlmostEqual(sum(alloc.values()), 1000, delta=1)
        self.assertEqual(s["metric"], "impressions")
        self.assertTrue(all(c.get("suggested") for c in s["campaigns"]))

    async def test_untested_channel_does_not_inflate_recommended_budget(self):
        google = {"daily": daily([900, 950, 1000, 1100, 1000, 1200, 1150, 1050, 1000, 1250, 1300, 1200, 1100], roas=6.5, b=0.8), "campaigns": []}
        s = await self.run_build({"meta": {"daily": [], "campaigns": []}, "google_ads": google}, objective="vendas")
        self.assertEqual(s["recommended"], "ritmo_atual")  # com canal em teste, não recomenda saltar de verba
        chosen = next(sc for sc in s["scenarios"] if sc["key"] == s["selected"])
        self.assertLessEqual(chosen["allocation"]["meta"], chosen["budget"] * ms.REFERENCE_CAP + 1)
        eff = next((sc for sc in s["scenarios"] if sc["key"] == "eficiencia"), None)
        if eff:
            self.assertLessEqual(eff["allocation"]["meta"], eff["budget"] * ms.REFERENCE_CAP + 1)

    async def test_hiperfoco_keeps_only_channels_with_data(self):
        meta = {"daily": daily([1000] * 13), "campaigns": []}
        s = await self.run_build({"meta": meta, "google_ads": {"daily": [], "campaigns": []}}, objective="vendas", distribution="hiperfoco")
        self.assertTrue(all(list(sc["allocation"]) == ["meta"] for sc in s["scenarios"]))
        self.assertEqual(s["channel_kind"], {"meta": "dados"})

    async def test_irrelevant_attributed_revenue_switches_to_conversions(self):
        meta = {"daily": [dict(d, revenue=d["revenue"] * 0.001) for d in daily([1000] * 13)], "campaigns": []}
        s = await self.run_build({"meta": meta, "google_ads": {"daily": [], "campaigns": []}}, objective="vendas")
        self.assertEqual(s["metric"], "conversions")
        self.assertTrue(any("irrisória" in f["text"] for f in s["findings"]))


class CampaignBudgetAndLearningTests(unittest.TestCase):
    ROWS = [{"channel": "meta", "campaign": "A", "action": "escalar", "why": "x", "spend": 3000, "conversions": 80, "revenue": 24000, "roas": 8.0, "cpa": 37.5},
            {"channel": "meta", "campaign": "B", "action": "manter", "why": "x", "spend": 2000, "conversions": 40, "revenue": 8000, "roas": 4.0, "cpa": 50.0},
            {"channel": "meta", "campaign": "C", "action": "pausar", "why": "x", "spend": 900, "conversions": 0, "revenue": 0, "roas": 0.0, "cpa": None},
            {"channel": "meta", "campaign": "D", "action": "aprender", "why": "x", "spend": 60, "conversions": 1, "revenue": 100, "roas": 1.6, "cpa": 60.0}]

    def test_budgets_follow_actions_close_with_channel_and_respect_minimum(self):
        rows = ms.plan_campaign_budgets([dict(r) for r in self.ROWS], {"meta": 6000, "google_ads": 1500}, 30, "vendas", boost_pool=600)
        meta = {r["campaign"]: r["planned_budget"] for r in rows if r["channel"] == "meta"}
        self.assertEqual(meta["C"], 0.0)                                   # pausar
        self.assertEqual(meta["D"], 0.0)                                   # abaixo de R$ 10/dia: concentrada
        self.assertGreater(meta["A"] / 3000, meta["B"] / 2000)            # escalar ganha mais que manter
        self.assertEqual(meta["Impulsionamento dos posts do calendário"], 600)
        self.assertAlmostEqual(sum(meta.values()), 6000, delta=1)
        google = [r for r in rows if r["channel"] == "google_ads"]
        self.assertTrue(all(r.get("suggested") and r["action"] == "testar" for r in google))
        self.assertAlmostEqual(sum(r["planned_budget"] for r in google), 1500, delta=1)

    def test_learning_adjusts_actions_from_previous_plans(self):
        rows = [dict(r) for r in self.ROWS]
        memory = {"A": {"month": "2026-10-01", "action": "escalar", "roas": 12.0, "planned_budget": 4000, "edited": True},
                  "B": {"month": "2026-10-01", "action": "otimizar", "roas": 3.0},
                  "C": {"month": "2026-10-01", "action": "pausar", "roas": 0.0}}
        learned = ms.learn_from_history(rows, memory, "revenue")
        by = {r["campaign"]: r for r in rows}
        self.assertEqual(learned, 3)
        self.assertEqual(by["A"]["action"], "manter")                       # escalada derrubou o ROAS (12 → 8)
        self.assertIn("A equipe definiu escalar com R$ 4.000 em out", by["A"]["learning"])
        self.assertEqual(by["B"]["action"], "manter")                       # otimização funcionou (3 → 4)
        self.assertIn("seguiu investindo", by["C"]["learning"])
        self.assertNotIn("learning", by["D"])
