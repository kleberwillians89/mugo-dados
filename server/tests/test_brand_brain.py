"""Cérebro da marca: um bloco só para todas as IAs, e nenhuma IA nova fica de fora."""
import ast
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import brand_brain  # noqa: E402

SERVICES = Path(__file__).resolve().parent.parent / "services"

# Toda IA que chama o modelo precisa estar aqui. "brand": recebe o cérebro via llm_json(brand=...).
# "propria": já monta o contexto completo da marca sozinha. "sem_marca": tarefa técnica que não escreve para a marca
# (extrair dados, OCR, manter a própria memória). IA nova fora da lista quebra o teste: decida em qual ela entra.
COVERAGE = {
    "creators": "brand", "social_report": "brand", "monthly_report": "brand", "ai_actions": "brand", "ai_summary": "brand",
    "studio_campaigns": "brand", "studio_documents": "brand", "studio_projects": "brand", "media_strategy": "brand",
    "studio_briefs": "brand", "studio_agents": "brand",
    "whatsapp_ai": "propria", "ig_engagement": "propria", "ig_direct": "propria", "mugo_ia": "propria",
    "brand_agent": "propria", "studio_calendar": "propria", "studio_matrix": "propria", "studio_engines": "propria",
    "meta_ad_publisher": "propria", "benchmark_auto": "propria", "studio_brand_brain": "propria", "brand_import": "propria",
    "business_brain": "propria", "radar_brand": "propria", "studio_clipping": "propria", "brand_health": "propria",
    "intelligence": "propria",
    "media_briefing": "sem_marca", "brand_ocr": "sem_marca", "brand_knowledge": "sem_marca", "brand_learning": "sem_marca",
    "studio_import": "sem_marca", "studio_messages": "sem_marca", "studio_llm": "sem_marca", "ai_runtime": "sem_marca", "brand_brain": "sem_marca", "web_research": "sem_marca",
}


def _calls_model(source: str) -> bool:
    return "llm_json(" in source or "api.openai.com" in source


class CoverageTests(unittest.TestCase):
    def test_every_ai_is_classified(self):
        missing = [p.stem for p in SERVICES.glob("*.py") if _calls_model(p.read_text()) and p.stem not in COVERAGE]
        self.assertEqual(missing, [], "IA nova sem decisão sobre o cérebro da marca: inclua em COVERAGE")

    def test_brand_modules_pass_brand_on_every_call(self):
        for name, kind in COVERAGE.items():
            if kind != "brand" or name == "ai_summary":
                continue
            tree = ast.parse((SERVICES / f"{name}.py").read_text())
            calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "llm_json"]
            self.assertTrue(calls, name)
            for call in calls:
                self.assertIn("brand", [k.arg for k in call.keywords], f"{name}:{call.lineno} sem brand=")
                value = next(k.value for k in call.keywords if k.arg == "brand")
                self.assertIn(getattr(value, "value", None), brand_brain.PURPOSES, f"{name}:{call.lineno}")


class RenderTests(unittest.TestCase):
    business = {"segment": "perfumaria nicho", "product_description": "perfumes autorais", "goals": "vender no BF"}
    profile = {"tone_of_voice": "sofisticado e próximo", "pillars": [{"name": "Pirâmide olfativa"}], "restrictions": "sem preço no feed"}

    def test_purpose_controls_what_goes_in(self):
        block = brand_brain.render("criadores", business=self.business, profile=self.profile, memory="Fundada em 2021.", voice="elogiam a fixação")
        for text in ("perfumaria nicho", "sofisticado", "Pirâmide olfativa", "Fundada em 2021", "elogiam a fixação", "nunca instruções"):
            self.assertIn(text, block)
        quick = brand_brain.render("atendimento", business=self.business, profile=self.profile, memory="", voice="elogiam")
        self.assertIn("sofisticado", quick)
        self.assertNotIn("Pilares", quick)
        self.assertNotIn("elogiam", quick)

    def test_performance_lessons_go_in_by_purpose(self):
        lessons = [{"tipo": "post", "resultado": "acima", "aprendizado": "Reels \"bastidor\", terça às 19h: 1,8x o alcance médio."},
                   {"tipo": "anúncio", "resultado": "abaixo", "aprendizado": "Carrossel de preço: CTR 0,4x a mediana."}]
        block = brand_brain.render("estrategia", business=self.business, profile={}, memory="", voice=None, lessons=lessons)
        self.assertIn("1,8x o alcance médio", block)
        self.assertIn("[anúncio, abaixo]", block)
        quick = brand_brain.render("atendimento", business=self.business, profile={}, memory="", voice=None, lessons=lessons)
        self.assertNotIn("alcance médio", quick)
        one = brand_brain.render("criadores", business={}, profile={}, memory="", voice=None, lessons=lessons * 3)
        self.assertEqual(one.count("· ["), 3)

    def test_empty_brand_gives_empty_block(self):
        self.assertEqual(brand_brain.render("estrategia", business={}, profile={}, memory="", voice=None), "")

    def test_size_cap(self):
        block = brand_brain.render("dados", business={k: "x" * 900 for k in brand_brain.LABELS}, profile={}, memory="m" * 5000, voice=None)
        self.assertLessEqual(len(block), brand_brain.PURPOSES["dados"]["chars"] + 200)


class LlmJsonTests(unittest.IsolatedAsyncioTestCase):
    async def test_brand_purpose_appends_block_to_instructions(self):
        from services import studio_llm
        once = AsyncMock(return_value={"ok": True})
        with patch.object(studio_llm, "_llm_json_once", once), \
             patch("services.brand_brain.brand_block", AsyncMock(return_value="CÉREBRO DA MARCA\n- Tom: leve")):
            await studio_llm.llm_json(instructions="Base.", prompt="p", schema_name="x", schema={}, client_id="c1",
                                      leak_check=False, brand="dados")
        self.assertIn("CÉREBRO DA MARCA", once.await_args.kwargs["instructions"])
        once.reset_mock()
        with patch.object(studio_llm, "_llm_json_once", once):
            await studio_llm.llm_json(instructions="Base.", prompt="p", schema_name="x", schema={}, client_id="c1", leak_check=False)
        self.assertEqual(once.await_args.kwargs["instructions"], "Base.")


if __name__ == "__main__":
    unittest.main()
