from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from services import media_briefing as mb
from services import media_strategy as ms
from test_media_strategy import daily

NOV = date(2026, 11, 1)
CHANNELS = {"meta": "Meta Ads", "google_ads": "Google Ads"}


class ValidationTests(unittest.TestCase):
    def test_only_existing_campaigns_valid_days_known_channels(self):
        raw = {"summary": "Lançamento da linha Âmbar dia 10", "budget_cap": 8000,
               "channel_emphasis": [{"channel": "google_ads", "emphasis": "mais"}, {"channel": "tiktok", "emphasis": "mais"}],
               "campaigns": [{"campaign": "Remarketing", "action": "escalar", "reason": "lançamento"},
                             {"campaign": "Inventada", "action": "pausar", "reason": "x"},
                             {"campaign": "PMax", "action": "deletar", "reason": "x"}],
               "dates": [{"day": 10, "label": "Lançamento Âmbar"}, {"day": 31, "label": "fora do mês"}, {"day": 10, "label": "duplicada"}]}
        out = mb.validate(raw, month=NOV, campaigns=["Remarketing", "PMax"], channels=CHANNELS)
        self.assertEqual(out["channel_emphasis"], {"google_ads": "mais"})
        self.assertEqual(out["campaigns"], {"Remarketing": {"action": "escalar", "reason": "lançamento"}})
        self.assertEqual(out["dates"], [{"date": "2026-11-10", "label": "Lançamento Âmbar"}])
        self.assertEqual(out["budget_cap"], 8000.0)
        self.assertIsNone(mb.validate({"budget_cap": -5}, month=NOV, campaigns=[], channels=CHANNELS)["budget_cap"])

    def test_campaign_override_is_marked_and_described(self):
        rows = [{"campaign": "Remarketing", "action": "manter", "why": "média"}, {"campaign": "PMax", "action": "escalar", "why": "x"}]
        changes = mb.apply_to_campaigns(rows, {"campaigns": {"Remarketing": {"action": "pausar", "reason": "estoque acabou"}}})
        self.assertEqual(rows[0]["action"], "pausar")
        self.assertTrue(rows[0]["briefing"])
        self.assertIn("Pedido no briefing: estoque acabou", rows[0]["why"])
        self.assertEqual(changes, ["Remarketing: pausar (era manter)"])
        text = mb.describe({"channel_emphasis": {"meta": "menos"}, "dates": [{"date": "2026-11-10", "label": "Lançamento"}], "budget_cap": 8000},
                           CHANNELS, changes, used_cap=True)
        self.assertEqual(text, ["Meta Ads: no máximo 20% da verba.", "Lançamento em 10/11: verba reforçada nos dias anteriores.",
                                "Campanha Remarketing: pausar (era manter).", "Verba do mês limitada a R$ 8.000 (teto do briefing)."])


class AppliedToNumbersTests(unittest.IsolatedAsyncioTestCase):
    async def run_build(self, directives, briefing="texto"):
        meta = {"daily": daily([1500, 1800, 2000, 2400, 2800, 3200, 2600, 2200, 1900, 2500, 3000, 2700, 2300], b=0.65),
                "campaigns": [{"campaign_name": "Remarketing", "spend": 3000, "conversions": 80, "revenue": 24000},
                              {"campaign_name": "Prospecção", "spend": 2500, "conversions": 50, "revenue": 10000}]}
        google = {"daily": daily([900, 950, 1000, 1100, 1000, 1200, 1150, 1050, 1000, 1250, 1300, 1200, 1100], roas=6.5, b=0.8), "campaigns": []}
        with patch.object(ms, "read_window", AsyncMock(return_value={"meta": meta, "google_ads": google})), \
             patch.object(ms, "_store_and_goal", AsyncMock(return_value=({"revenue": 90000, "investment": 9000}, None, []))), \
             patch.object(ms, "_calendar_context", AsyncMock(return_value=([], {}))), \
             patch.object(ms, "campaign_memory", AsyncMock(return_value={})), \
             patch("services.media_briefing.parse_briefing", AsyncMock(return_value={**mb.empty(), **directives})):
            return await ms.build_strategy("curavino", month="2026-11", objective="vendas", today=date(2026, 10, 29), briefing=briefing)

    async def test_briefing_changes_split_budget_dates_and_campaigns(self):
        base = await self.run_build({}, briefing="")
        s = await self.run_build({"channel_emphasis": {"meta": "menos"}, "budget_cap": 6000,
                                  "dates": [{"date": "2026-11-10", "label": "Lançamento Âmbar"}],
                                  "campaigns": {"Prospecção": {"action": "pausar", "reason": "trocar criativo"}}})
        self.assertIsNone(base["briefing"])
        chosen = next(sc for sc in s["scenarios"] if sc["key"] == s["selected"])
        self.assertEqual((s["selected"], chosen["budget"]), ("personalizado", 6000))   # teto do briefing vira a verba
        self.assertLessEqual(chosen["allocation"]["meta"], 6000 * 0.20 + 1)              # "menos Meta"
        self.assertTrue(any("Lançamento Âmbar" in w["dates"] for w in s["weeks"]))
        launch = next(w for w in s["weeks"] if "Lançamento Âmbar" in w["dates"])
        self.assertNotEqual(launch["phase"], "base")                                      # verba reforçada antes da data
        pros = next(c for c in s["campaigns"] if c["campaign"] == "Prospecção")
        self.assertEqual(pros["action"], "pausar")
        self.assertEqual(len(s["briefing"]["applied"]), 4)

    async def test_ai_failure_keeps_text_and_strategy(self):
        from services.studio_calendar import StudioError
        meta = {"daily": daily([1000] * 13), "campaigns": []}
        with patch.object(ms, "read_window", AsyncMock(return_value={"meta": meta, "google_ads": {"daily": [], "campaigns": []}})), \
             patch.object(ms, "_store_and_goal", AsyncMock(return_value=({}, None, []))), \
             patch.object(ms, "_calendar_context", AsyncMock(return_value=([], {}))), \
             patch.object(ms, "campaign_memory", AsyncMock(return_value={})), \
             patch("services.media_briefing.parse_briefing", AsyncMock(side_effect=StudioError("AI_PROVIDER_TIMEOUT"))):
            s = await ms.build_strategy("x", month="2026-11", objective="vendas", today=date(2026, 10, 29), briefing="foco em Google")
        self.assertEqual((s["briefing"]["text"], s["briefing"]["error"], s["briefing"]["applied"]), ("foco em Google", "AI_PROVIDER_TIMEOUT", []))
        self.assertTrue(s["scenarios"])


if __name__ == "__main__":
    unittest.main()


class TestSalesAndNewCampaignTests(unittest.IsolatedAsyncioTestCase):
    """Briefing real da Roove: 'gastei com mídia e não tive vendas, as vendas registradas foram teste, preciso de uma
    campanha agressiva para vender bem na Black Friday'."""

    def test_validate_new_fields(self):
        out = mb.validate({"conversions_unreliable": True,
                           "new_campaigns": [{"channel": "meta", "name": "Black Friday agressiva", "purpose": "vender na BF"},
                                             {"channel": "meta", "name": "black friday agressiva", "purpose": "dup"},
                                             {"channel": "tiktok", "name": "x", "purpose": "x"}]},
                          month=NOV, campaigns=[], channels=CHANNELS)
        self.assertTrue(out["conversions_unreliable"])
        self.assertEqual([c["name"] for c in out["new_campaigns"]], ["Black Friday agressiva"])
        self.assertFalse(mb.validate({}, month=NOV, campaigns=[], channels=CHANNELS)["conversions_unreliable"])

    async def test_fake_conversions_are_ignored_and_bf_campaign_gets_budget(self):
        meta = {"daily": daily([700] * 13, roas=9.0), "campaigns": [{"campaign_name": "Conversão site", "spend": 2000, "conversions": 40, "revenue": 18000},
                                                                     {"campaign_name": "Tráfego", "spend": 900, "conversions": 0, "revenue": 0}]}
        google = {"daily": daily([300] * 13, roas=8.0), "campaigns": [{"campaign_name": "PMax", "spend": 1200, "conversions": 30, "revenue": 9000}]}
        directives = {**mb.empty(), "conversions_unreliable": True, "summary": "Sem vendas reais; campanha agressiva para BF",
                      "new_campaigns": [{"channel": "meta", "name": "Black Friday agressiva", "purpose": "vender bem na Black Friday"}]}
        store = {"revenue": 40000, "orders": 200, "sessions": 16000, "investment": 3000}
        with patch.object(ms, "read_window", AsyncMock(return_value={"meta": meta, "google_ads": google})), \
             patch.object(ms, "_store_and_goal", AsyncMock(return_value=(store, None, []))), \
             patch.object(ms, "_calendar_context", AsyncMock(return_value=([], {}))), \
             patch.object(ms, "campaign_memory", AsyncMock(return_value={"Conversão site": {"month": "2026-10-01", "action": "escalar", "roas": 20}})), \
             patch("services.media_briefing.parse_briefing", AsyncMock(return_value=directives)):
            s = await ms.build_strategy("roove", month="2026-11", objective="vendas", today=date(2026, 10, 29),
                                        distribution="hiperfoco", custom_budget=2500, briefing="texto")
        chosen = next(sc for sc in s["scenarios"] if sc["key"] == s["selected"])
        self.assertEqual(chosen["budget"], 2500)
        # ROAS projetado vem da loja (ticket R$ 200, conversão do site), não do ROAS 9 inventado pelas vendas de teste
        self.assertLess(chosen["result"]["totals"]["roas"], 9.0)
        self.assertTrue(any(f["text"].startswith("Briefing: as conversões registradas") for f in s["findings"]))
        old = [c for c in s["campaigns"] if not c.get("briefing_new") and not c.get("boost")]
        self.assertTrue(all(c["action"] == "aprender" for c in old))        # não julga campanha por conversão falsa
        self.assertFalse(any(c.get("learning") for c in old))               # nem aprende com ela
        bf = next(c for c in s["campaigns"] if c["campaign"] == "Black Friday agressiva")
        meta_budget = chosen["allocation"]["meta"]
        self.assertAlmostEqual(bf["planned_budget"], meta_budget * mb.NEW_CAMPAIGN_SHARE, delta=2)
        self.assertAlmostEqual(sum(c["planned_budget"] for c in s["campaigns"] if c["channel"] == "meta"), meta_budget, delta=2)
        bf_week = next(w for w in s["weeks"] if "Black Friday" in w["dates"])
        self.assertEqual(bf_week["phase"], "pico")
        self.assertTrue(any("desconsideradas" in a for a in s["briefing"]["applied"]))
