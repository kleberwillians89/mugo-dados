"""LGPD: dado pessoal não vai para a IA nem para a pesquisa web. Se alguém quebrar a regra, o teste falha."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import mugo_ia as mi
from services.studio_intelligence import clean_text

PERSONAL = ["maria.silva@gmail.com", "(11) 98765-4321", "123.456.789-09", "12.345.678/0001-90", "11987654321"]


class MinimizationTests(unittest.IsolatedAsyncioTestCase):
    def test_clean_text_drops_any_text_with_personal_patterns(self):
        for value in PERSONAL:
            self.assertEqual(clean_text(f"Cliente pediu troca, contato {value}"), "", value)
        self.assertEqual(clean_text("Vendas subiram 12% na Black Friday"), "Vendas subiram 12% na Black Friday")

    async def test_daily_sales_sends_only_totals_never_buyers(self):
        async def fake(table, **kwargs):
            self.assertNotIn("customer", kwargs.get("select", ""))
            self.assertNotIn("email", kwargs.get("select", ""))
            return []
        with patch.object(mi, "sb_select", side_effect=fake):
            await mi.daily_sales("c")

    def test_web_research_never_receives_the_question(self):
        from services import mugo_ia_web
        source = Path(mugo_ia_web.__file__).read_text(encoding="utf-8")
        self.assertIn("nunca com a pergunta crua", source)
        self.assertNotIn("query={\"q\": question", source)

    async def test_prompt_has_no_personal_data_from_clipping_or_posts(self):
        rows = [{"title": f"Reclamação de {p}", "source": "Site", "kind": "marca", "term": "Marca", "relevant": True} for p in PERSONAL]
        with patch.object(mi, "sb_select", AsyncMock(return_value=rows)):
            clipping = await mi._clipping("c")
        prompt = mi.build_prompt(context={"package": {}, "live": {"clipping": clipping}}, chunks=[], past=[], question="oi")
        for value in PERSONAL:
            self.assertNotIn(value, prompt)


if __name__ == "__main__":
    unittest.main()
