"""Cérebro da marca (módulos conversando) e trava de fidelidade."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import brand_guard as bg
from services import studio_intelligence as si


class GuardTests(unittest.TestCase):
    def test_invented_offer_and_urgency_are_flagged_but_briefed_offer_is_not(self):
        text = "Kit Oud com 20% e frete grátis. Só hoje! Ganhe brinde exclusivo."
        issues = bg.check(text, context='{"oferta": "20% no kit Oud"}')
        kinds = {(i["type"], i["text"].lower()) for i in issues}
        self.assertNotIn(("promessa_sem_dado", "20%"), kinds)          # está no briefing
        self.assertIn(("promessa_sem_dado", "frete grátis"), kinds)    # ninguém prometeu
        self.assertIn(("promessa_sem_dado", "brinde"), kinds)
        self.assertIn(("urgencia_inventada", "só hoje"), kinds)

    def test_forbidden_words_from_profile_and_cliches(self):
        issues = bg.check("Uma jornada barata e imperdível", avoid=["barata"])
        self.assertEqual({i["text"] for i in issues if i["type"] == "palavra_proibida"}, {"barata", "jornada", "imperdível"})

    def test_clean_text_passes(self):
        self.assertEqual(bg.check("O Oud que fica na pele o dia inteiro.", context=""), [])


class BrainTests(unittest.IsolatedAsyncioTestCase):
    async def test_package_carries_every_module(self):
        si.invalidate("ruah")
        fixed = {"_profile": {"tone_of_voice": "elegante"}, "_business": {}, "_snapshot": {}, "_posts": {}, "_timing": {},
                 "_goals": [], "_analysis": {}, "approval_learnings": {},
                 "_sales_origin": {"faturamento": 10000.0}, "_media_plan": {"objetivo": "vendas"},
                 "_active_campaigns": [{"campanha": "Black Friday"}], "_clipping": {"ultimos_14_dias": 3},
                 "_calendar_month": {"posts": 12}}
        patches = [patch.object(si, name, AsyncMock(return_value=value)) for name, value in fixed.items()]
        for p in patches:
            p.start()
        try:
            pkg = await si.build_content_intelligence("ruah", use_cache=False)
        finally:
            for p in patches:
                p.stop()
        for key in ("vendas_por_origem", "plano_de_midia", "campanhas_ativas", "clipping", "calendario_do_mes"):
            self.assertTrue(pkg[key], key)
        prompt = si.to_prompt(pkg)
        self.assertIn("Black Friday", prompt)
        self.assertLess(prompt.index("campanhas_ativas"), prompt.index("kpis") if "kpis" in prompt else 10**9)

    async def test_a_module_that_fails_becomes_a_gap_not_an_error(self):
        si.invalidate("ruah")
        with patch.object(si, "_media_plan", AsyncMock(side_effect=RuntimeError("fora"))), \
             patch.object(si, "_active_campaigns", AsyncMock(return_value=[])), patch.object(si, "_clipping", AsyncMock(return_value={})), \
             patch.object(si, "_calendar_month", AsyncMock(return_value={})), patch.object(si, "_sales_origin", AsyncMock(return_value={})), \
             patch.object(si, "_profile", AsyncMock(return_value={})), patch.object(si, "_business", AsyncMock(return_value={})), \
             patch.object(si, "_snapshot", AsyncMock(return_value={})), patch.object(si, "_posts", AsyncMock(return_value={})), \
             patch.object(si, "_timing", AsyncMock(return_value={})), patch.object(si, "_goals", AsyncMock(return_value=[])), \
             patch.object(si, "_analysis", AsyncMock(return_value={})), patch.object(si, "approval_learnings", AsyncMock(return_value={})):
            import io
            from contextlib import redirect_stdout
            with redirect_stdout(io.StringIO()):
                pkg = await si.build_content_intelligence("ruah", use_cache=False)
        self.assertIn("plano_de_midia", pkg["lacunas"])


if __name__ == "__main__":
    unittest.main()
