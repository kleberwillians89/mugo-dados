"""Briefing da peça no fluxo do Atendimento do iAgência."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import studio_engines as se  # noqa: E402

ITEM = {"id": "i1", "client_id": "ruah", "format": "reels", "title": "Bastidor do split", "hook": "Você já viu?", "caption_draft": "",
        "scheduled_at": "2026-12-03T21:00:00Z", "pillar": "Curadoria", "signals": {"basis": {"hours": "18h-21h"}}}
AI = {"summary": "Reels de bastidor.", "objective": "Gerar comentários.", "key_message": "Split é o original fracionado.",
      "tone": "Próximo e informativo", "target_audience": "Quem ama perfume de nicho", "angle": "bastidor",
      "deliverables": ["Reels 9:16 de 20 a 30 s", "Capa"], "tech_requirements": ["Legendas na tela", "Áudio sem direitos"],
      "script": "Cena 1: frasco lacrado", "visual_idea": "Luz natural lateral"}


class BriefingTests(unittest.IsolatedAsyncioTestCase):
    async def run_generate(self, direction=None, ai=None, update=None):
        llm = AsyncMock(return_value=ai or AI)
        upd = update or AsyncMock(return_value=[{**ITEM, "updated": True}])
        with patch.object(se, "_load_item", AsyncMock(return_value=ITEM)), \
             patch.object(se, "build_content_intelligence", AsyncMock(return_value={"marca": {}})), \
             patch.object(se, "_post_references", AsyncMock(return_value=[])), \
             patch.object(se, "llm_json", llm), patch.object(se, "throttle", lambda cid: None), \
             patch("services.ig_supabase.sb_update", upd):
            result = await se.generate_briefing("ruah", "i1", direction)
        return result, llm, upd

    async def test_saves_briefing_script_and_art_on_the_item(self):
        result, llm, upd = await self.run_generate({"objective": "Levar ao link", "boldness": 5, "cta": "Comenta"})
        prompt = llm.await_args.kwargs["prompt"]
        self.assertIn("Objetivo: Levar ao link", prompt)
        self.assertIn("Ousadia: Disruptivo", prompt)
        self.assertIn("Cenas numeradas", prompt)  # roteiro no formato do Reels
        patch_sent = upd.await_args.kwargs["patch"]
        self.assertEqual(patch_sent["script"], "Cena 1: frasco lacrado")
        self.assertEqual(patch_sent["visual_idea"], "Luz natural lateral")
        self.assertEqual(patch_sent["signals"]["basis"], {"hours": "18h-21h"})  # mantém o que já existia
        self.assertEqual(patch_sent["signals"]["briefing"]["tech_requirements"], ["Legendas na tela", "Áudio sem direitos"])
        self.assertTrue(result["item"]["updated"])

    async def test_without_migration_saves_only_short_briefing(self):
        upd = AsyncMock(side_effect=[RuntimeError("column script does not exist"), [ITEM]])
        await self.run_generate(update=upd)
        self.assertEqual(set(upd.await_args_list[1].kwargs["patch"]), {"signals"})

    async def test_empty_answer_is_an_error(self):
        with self.assertRaises(se.StudioError):
            await self.run_generate(ai={"summary": "x"})

    def test_briefing_block_is_priority_context(self):
        block = se.briefing_block(se.clean_briefing(AI))
        self.assertTrue(block.startswith("=== BRIEFING DA PEÇA (PRIORIDADE MÁXIMA) ==="))
        self.assertIn("Mensagem-chave: Split é o original fracionado.", block)
        self.assertIn("Requisitos técnicos: Legendas na tela; Áudio sem direitos", block)
        self.assertEqual(se.briefing_block(None), "")

    def test_clean_briefing_limits_and_unknown_angle(self):
        cleaned = se.clean_briefing({**AI, "angle": "inventado", "deliverables": [f"d{i}" for i in range(10)]})
        self.assertNotIn("angle", cleaned)
        self.assertEqual(len(cleaned["deliverables"]), 6)


class AssistUsesBriefingTests(unittest.IsolatedAsyncioTestCase):
    async def test_assist_puts_briefing_first_in_prompt(self):
        llm = AsyncMock(return_value={"caption": "Legenda", "cta": "Comenta", "why": "x"})
        saved = {**ITEM, "signals": {"briefing": se.clean_briefing(AI)}}
        with patch.object(se, "_load_item", AsyncMock(return_value=saved)), \
             patch.object(se, "build_content_intelligence", AsyncMock(return_value={"marca": {}})), \
             patch.object(se, "_post_references", AsyncMock(return_value=[])), \
             patch.object(se, "llm_json", llm), patch.object(se, "throttle", lambda cid: None):
            await se.assist("ruah", "legenda", ITEM, item_id="i1")
        self.assertTrue(llm.await_args.kwargs["prompt"].startswith("=== BRIEFING DA PEÇA (PRIORIDADE MÁXIMA) ==="))


if __name__ == "__main__":
    unittest.main()
