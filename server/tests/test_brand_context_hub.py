import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import AsyncMock, patch

from services import studio_intelligence as si


class HubTests(unittest.IsolatedAsyncioTestCase):
    async def test_modules_share_one_package_scoped_to_the_company(self):
        tables = []

        async def select(table, **kwargs):
            tables.append(table)
            self.assertEqual(kwargs["filters"]["client_id"], "eq.cura")  # nada de outra empresa entra no contexto
            return {
                "studio_campaigns": [{"name": "Black Friday", "briefing": {"objective": "vender tintos", "channels": ["reels"]}, "status": "pronta"}],
                "studio_media_plans": [{"objective": "receita", "budget": 5000, "notes": "foco em remarketing", "status": "ativo"}],
                "studio_campaign_learnings": [{"campaign_name": "Remarketing", "channel": "meta", "roas": 6.1, "recommended_action": "escalar"}],
                "studio_clippings": [{"title": "Curavino na Adega", "source": "Adega", "kind": "marca", "sentiment": "positivo", "relevant": True},
                                     {"title": "homônimo", "relevant": False}],
                "studio_calendar_items": [{"scheduled_at": "2026-11-10T19:00:00-03:00", "format": "reels", "title": "Kit BF", "status": "aprovado"}],
            }.get(table, [])

        with patch.object(si, "sb_select", AsyncMock(side_effect=select)):
            redacao, midia, clipping, agenda = (await si._redacao("cura"), await si._midia("cura"), await si._clipping("cura"), await si._agenda("cura"))
        self.assertEqual(redacao[0]["objetivo"], "vender tintos")
        self.assertEqual(midia["campanhas_em_veiculacao"][0]["recomendacao"], "escalar")
        self.assertEqual([c["manchete"] for c in clipping], ["Curavino na Adega"])  # irrelevante fica de fora
        self.assertEqual(agenda[0]["pauta"], "Kit BF")

    async def test_package_and_prompt_include_new_sections(self):
        empty = AsyncMock(return_value={})
        with patch.object(si, "_profile", AsyncMock(return_value={"tone_of_voice": "acolhedor"})), patch.object(si, "_business", empty), \
             patch.object(si, "_snapshot", empty), patch.object(si, "_posts", AsyncMock(return_value=[])), patch.object(si, "_timing", empty), \
             patch.object(si, "_goals", AsyncMock(return_value=[])), patch.object(si, "_analysis", empty), patch.object(si, "approval_learnings", empty), \
             patch.object(si, "_redacao", AsyncMock(return_value=[{"campanha": "BF"}])), patch.object(si, "_midia", AsyncMock(side_effect=RuntimeError)), \
             patch.object(si, "_clipping", AsyncMock(return_value=[{"manchete": "x"}])), patch.object(si, "_agenda", AsyncMock(return_value=[{"pauta": "Kit"}])):
            package = await si.build_content_intelligence("cura", use_cache=False)
        self.assertEqual(package["redacao"], [{"campanha": "BF"}])
        self.assertIn("midia_on", package["lacunas"])  # fonte fora do ar vira lacuna, não derruba o resto
        prompt = si.to_prompt(package)
        self.assertLess(prompt.index('"redacao"'), prompt.index('"clipping"'))
        self.assertIn("acolhedor", prompt)


if __name__ == "__main__":
    unittest.main()
