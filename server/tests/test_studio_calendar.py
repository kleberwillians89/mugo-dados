from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import studio_calendar as sc
from services.studio_dates import black_friday, custom_dates, dates_for_month, easter, national_dates
from services.studio_trends import parse_trends_rss

BEST = {
    "posts_analyzed": 40,
    "by_weekday": [
        {"weekday": "terça", "posts": 6, "reach_index": 1.4},
        {"weekday": "quinta", "posts": 5, "reach_index": 1.2},
        {"weekday": "domingo", "posts": 1, "reach_index": 3.0},  # amostra pequena: ignorado
        {"weekday": "segunda", "posts": 4, "reach_index": 0.8},
    ],
    "best_slots": [{"weekday": "terça", "hours": "18h-21h", "reach_index": 1.5, "confidence": "boa"}],
    "by_hours": [{"hours": "12h-15h", "posts": 5, "reach_index": 1.3}],
    "format_median_reach": {"reels": 3000, "carrossel": 1200, "imagem": 800},
    "online_followers": {"by_hour": [{"hour": "18h", "followers_online": 50}, {"hour": "20h", "followers_online": 90}]},
}
PROFILE = sc.normalize_profile({"pillars": [{"name": "Ciência", "weight": 40}, {"name": "Estilo de vida", "weight": 60}],
                                "keywords_avoid": ["milagre"], "posts_per_week": 2})


class DatesTests(unittest.TestCase):
    def test_movable_dates_2026(self):
        self.assertEqual(easter(2026), date(2026, 4, 5))
        self.assertEqual(black_friday(2026), date(2026, 11, 27))
        labels = {d["label"]: d["date"] for d in national_dates(2026)}
        self.assertEqual(labels["Carnaval"], "2026-02-17")
        self.assertEqual(labels["Dia das Mães"], "2026-05-10")
        self.assertEqual(labels["Dia dos Pais"], "2026-08-09")
        self.assertEqual(labels["Cyber Monday"], "2026-11-30")

    def test_month_filter_and_custom_dates(self):
        nov = dates_for_month(date(2026, 11, 1), [{"date": "11-03", "label": "Aniversário da marca"},
                                                 {"date": "2027-11-05", "label": "Outro ano"}, {"date": "xx", "label": "ruim"}])
        self.assertEqual([d["label"] for d in nov][:2], ["Aniversário da marca", "Dia da Consciência Negra"])
        self.assertNotIn("Outro ano", [d["label"] for d in nov])
        self.assertEqual(custom_dates([{"date": "02-30", "label": "inválida"}], 2026), [])


class TrendsTests(unittest.TestCase):
    XML = """<?xml version="1.0"?><rss xmlns:ht="https://trends.google.com/trending/rss" version="2.0"><channel>
      <item><title>Show de Verão</title><ht:approx_traffic>50000+</ht:approx_traffic>
        <ht:news_item><ht:news_item_title>Ingressos esgotam</ht:news_item_title>
        <ht:news_item_url>https://news.example/show</ht:news_item_url><ht:news_item_source>G</ht:news_item_source></ht:news_item></item>
      <item><title>Sem notícia</title></item>
      <item><title>show de verão</title></item>
    </channel></rss>"""

    def test_every_trend_has_verifiable_source_and_no_duplicates(self):
        items = parse_trends_rss(self.XML, researched_at="2026-10-29T00:00:00Z")
        self.assertEqual([i["topic"] for i in items], ["Show de Verão", "Sem notícia"])
        self.assertEqual(items[0]["source_url"], "https://news.example/show")
        self.assertTrue(items[1]["source_url"].startswith("https://trends.google.com/trends/explore?geo=BR&q="))
        self.assertTrue(all(i["researched_at"] for i in items))

    def test_broken_xml_returns_nothing(self):
        self.assertEqual(parse_trends_rss("<rss><item>"), [])


class PlanSlotsTests(unittest.TestCase):
    def test_uses_best_weekdays_hour_with_online_peak_and_seasonal(self):
        seasonal = dates_for_month(date(2026, 11, 1))
        slots = sc.plan_slots(date(2026, 11, 1), BEST, PROFILE, today=date(2026, 10, 29), seasonal=seasonal)
        weekdays = {s["weekday"] for s in slots if s["basis"]["reason"] == "melhor_dia"}
        self.assertEqual(weekdays, {"terça", "quinta"})  # 2 por semana, domingo ignorado por amostra
        tuesday = next(s for s in slots if s["weekday"] == "terça")
        self.assertEqual((tuesday["time"], tuesday["basis"]["hours"]), ("20:00", "18h-21h"))  # pico online
        self.assertTrue(tuesday["scheduled_at"].endswith("-03:00"))
        bf = next(s for s in slots if s["date"] == "2026-11-27")
        self.assertEqual(bf["seasonal"], "Black Friday")
        self.assertNotIn("2026-11-20", [s["date"] for s in slots if s["seasonal"] == "Dia da Consciência Negra"])

    def test_skips_past_days_and_busy_days(self):
        slots = sc.plan_slots(date(2026, 11, 1), BEST, PROFILE, today=date(2026, 11, 10), seasonal=[],
                              busy_days={"2026-11-12"})
        self.assertTrue(all(s["date"] > "2026-11-10" for s in slots))
        self.assertNotIn("2026-11-12", [s["date"] for s in slots])

    def test_no_history_falls_back_to_default_order(self):
        slots = sc.plan_slots(date(2026, 11, 1), {}, PROFILE, today=date(2026, 10, 1), seasonal=[])
        self.assertEqual({s["weekday"] for s in slots}, {"terça", "quinta"})
        self.assertEqual(slots[0]["time"], "19:00")

    def test_past_month_rejected(self):
        with self.assertRaises(sc.StudioError):
            sc.plan_slots(date(2026, 9, 1), BEST, PROFILE, today=date(2026, 10, 1), seasonal=[])

    def test_format_rotation_follows_real_reach(self):
        seq = sc.format_rotation(BEST, ["imagem", "carrossel", "reels"])
        self.assertEqual(seq[:3], ["reels", "carrossel", "imagem"])
        self.assertEqual((seq.count("reels"), seq.count("carrossel"), seq.count("imagem")), (5, 3, 2))


class ValidateItemsTests(unittest.TestCase):
    def setUp(self):
        self.slots = sc.plan_slots(date(2026, 11, 1), BEST, PROFILE, today=date(2026, 10, 29), seasonal=[])[:3]
        self.trends = [{"id": "t1", "topic": "X", "source_url": "https://n/x", "researched_at": "r"}]

    def item(self, slot_id, **kw):
        return {"slot_id": slot_id, "pillar": "Ciência", "title": "Pauta", "hook": "h", "caption_draft": "c",
                "rationale": "r", "trend_id": None, **kw}

    def test_drops_unknown_duplicate_and_off_profile_values(self):
        raw = {"items": [self.item("s1", trend_id="t1"), self.item("s1"), self.item("zz"),
                         self.item("s2", pillar="Inventado", trend_id="t9"),
                         self.item("s3", caption_draft="Resultado milagre garantido")]}
        items, warnings = sc.validate_items(raw, slots=self.slots, profile=PROFILE, trends=self.trends)
        self.assertEqual([i["slot"]["slot_id"] for i in items], ["s1", "s2", "s3"])
        self.assertEqual(items[0]["signals"]["trend"]["source_url"], "https://n/x")
        self.assertIsNone(items[1]["pillar"])
        self.assertNotIn("trend", items[1]["signals"])
        self.assertEqual(items[2]["signals"]["palavras_evitar_encontradas"], ["milagre"])
        self.assertTrue(any("pilar fora do perfil" in w for w in warnings))

    def test_missing_slots_are_reported(self):
        items, warnings = sc.validate_items({"items": [self.item("s1")]}, slots=self.slots, profile=PROFILE, trends=[])
        self.assertEqual(len(items), 1)
        self.assertTrue(any("sem pauta válida" in w for w in warnings))


class GenerateMonthTests(unittest.IsolatedAsyncioTestCase):
    def patches(self, *, llm, existing=None, recent=False):
        return [
            patch.object(sc, "_recent_generation", AsyncMock(return_value=recent)),
            patch.object(sc, "load_profile", AsyncMock(return_value={"profile": PROFILE})),
            patch.object(sc, "build_posting_times", AsyncMock(return_value=BEST)),
            patch.object(sc, "list_items", AsyncMock(return_value=existing or [])),
            patch.object(sc, "load_business_context", AsyncMock(return_value={"context": {"segment": "moda"}})),
            patch.object(sc, "top_posts", AsyncMock(return_value=[])),
            patch.object(sc, "fetch_trends_br", AsyncMock(return_value={"items": []})),
            patch.object(sc, "call_llm", llm),
            patch.object(sc, "sb_delete", AsyncMock()),
            patch.object(sc, "sb_insert_many", AsyncMock()),
            patch.object(sc, "content_signals", AsyncMock(return_value={"aprendizados": {"aprovados": [{"pauta": "Pauta aprovada X"}]}})),
        ]

    async def run_with(self, patches, month="2026-11"):
        started = [p.start() for p in patches]
        try:
            return await sc.generate_month("roove", month, user_id="u1", today=date(2026, 10, 29)), started
        finally:
            for p in patches:
                p.stop()

    async def test_ai_failure_keeps_previous_drafts(self):
        ps = self.patches(llm=AsyncMock(side_effect=sc.StudioError("AI_PROVIDER_TIMEOUT")))
        mocks = [p.start() for p in ps]
        try:
            with self.assertRaises(sc.StudioError):
                await sc.generate_month("roove", "2026-11", user_id="u1", today=date(2026, 10, 29))
        finally:
            for p in ps:
                p.stop()
        mocks[8].assert_not_awaited()  # nada apagado
        mocks[9].assert_not_awaited()  # nada gravado

    async def test_success_replaces_only_ai_drafts_and_respects_team_items(self):
        existing = [{"origin": "manual", "status": "rascunho", "scheduled_at": "2026-11-03T22:00:00+00:00"},
                    {"origin": "ia", "status": "aprovado", "scheduled_at": "2026-11-05T22:00:00+00:00"},
                    {"origin": "ia", "status": "rascunho", "scheduled_at": "2026-11-10T22:00:00+00:00"}]
        llm = AsyncMock(side_effect=lambda prompt: {"items": [
            {"slot_id": f"s{i}", "pillar": "Ciência", "title": f"P{i}", "hook": "", "caption_draft": "", "rationale": "", "trend_id": None}
            for i in range(1, 40)]})
        ps = self.patches(llm=llm, existing=existing)
        result, mocks = await self.run_with(ps)
        delete, insert = mocks[8], mocks[9]
        self.assertEqual(delete.await_args.kwargs["filters"]["origin"], "eq.ia")
        self.assertEqual(delete.await_args.kwargs["filters"]["status"], "eq.rascunho")
        rows = insert.await_args.args[1]
        days = {r["scheduled_at"][:10] for r in rows}
        self.assertNotIn("2026-11-03", days)  # dia de item manual
        self.assertNotIn("2026-11-05", days)  # dia de item aprovado
        self.assertTrue(all(r["status"] == "rascunho" and r["origin"] == "ia" and r["client_id"] == "roove" for r in rows))
        self.assertEqual(result["kept"], 2)
        self.assertIn("Pauta aprovada X", llm.await_args.args[0])  # aprendizado do cliente vai para o prompt

    async def test_cooldown_and_range(self):
        with self.assertRaises(sc.StudioError) as err:
            await self.run_with(self.patches(llm=AsyncMock(), recent=True))
        self.assertEqual(err.exception.code, "AI_GENERATION_COOLDOWN")
        with self.assertRaises(sc.StudioError) as err:
            await self.run_with(self.patches(llm=AsyncMock()), month="2027-06")
        self.assertEqual(err.exception.code, "MONTH_OUT_OF_RANGE")


class UpdateItemTests(unittest.IsolatedAsyncioTestCase):
    async def test_approval_records_reviewer_and_scopes_by_client(self):
        with patch.object(sc, "sb_update", AsyncMock(return_value=[{"id": "i"}])) as update:
            await sc.update_item("roove", "i", {"status": "aprovado", "client_id": "outra"}, user_id="julia")
        patch_body = update.await_args.kwargs["patch"]
        self.assertEqual(update.await_args.kwargs["filters"], {"client_id": "eq.roove", "id": "eq.i"})
        self.assertEqual(patch_body["reviewed_by"], "julia")
        self.assertNotIn("client_id", patch_body)

    async def test_reschedule_moves_month(self):
        with patch.object(sc, "sb_update", AsyncMock(return_value=[{"id": "i"}])) as update:
            await sc.update_item("roove", "i", {"scheduled_at": "2026-12-01T01:00:00+00:00"}, user_id="u")
        self.assertEqual(update.await_args.kwargs["patch"]["month"], "2026-11-01")  # 22h do dia 30/11 em SP


if __name__ == "__main__":
    unittest.main()
