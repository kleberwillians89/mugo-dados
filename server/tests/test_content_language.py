"""Idioma de publicação por marca (ex.: Latinas publica em inglês para a Europa)."""
import asyncio
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from services import ig_engagement, studio_brand_brain, studio_engines
from services import studio_calendar as sc


def run(coro):
    return asyncio.run(coro)


EN = sc.normalize_profile({"content_language": "en", "tone_of_voice": "Warm, latin, confident"})
PT = sc.normalize_profile({"tone_of_voice": "Leve"})


class ProfileTests(unittest.TestCase):
    def test_default_and_invalid_fall_back_to_portuguese(self):
        self.assertEqual(PT["content_language"], "pt-BR")
        self.assertEqual(sc.normalize_profile({"content_language": "klingon"})["content_language"], "pt-BR")
        self.assertEqual(EN["content_language"], "en")

    def test_route_accepts_language(self):
        from routes.studio import ProfileInput
        self.assertEqual(ProfileInput(content_language="en").content_language, "en")
        self.assertEqual(ProfileInput().content_language, "pt-BR")
        with self.assertRaises(Exception):
            ProfileInput(content_language="fr")

    def test_ai_profile_suggestion_never_changes_language(self):
        suggested = {"tone_of_voice": "Novo tom", "keywords_avoid": [], "restrictions": ""}
        self.assertEqual(studio_brand_brain.protect_manual(suggested, EN)["content_language"], "en")


class PromptTests(unittest.TestCase):
    def test_rule_for_english_brand(self):
        rule = sc.language_rule(EN)
        self.assertIn("inglês (English)", rule)
        self.assertIn("legenda", rule)
        self.assertIn("continuam em português do Brasil", rule)  # pautas e notas da equipe
        self.assertEqual(sc.language_rule(PT), "- IDIOMA: português do Brasil.")

    def test_calendar_prompt_uses_brand_language(self):
        prompt = sc.build_prompt(slots=[], profile=EN, business={}, top=[], trends=[], seasonal=[], month=date(2026, 12, 1))
        self.assertIn("esta marca publica em inglês", prompt)
        self.assertNotIn("- IDIOMA: português do Brasil.", prompt)

    def test_assist_prompt_uses_brand_language(self):
        intel = {"marca": {"tone_of_voice": "Warm", "content_language": "en"}}
        llm = AsyncMock(return_value={"caption": "Feel the rhythm.", "cta": "Shop now", "why": "x"})
        with patch.object(studio_engines, "build_content_intelligence", AsyncMock(return_value=intel)), \
             patch.object(studio_engines, "_post_references", AsyncMock(return_value=[])), \
             patch.object(studio_engines, "throttle", lambda cid: None), \
             patch.object(studio_engines, "llm_json", llm):
            run(studio_engines.assist("latinas", "legenda", {"title": "Lançamento", "format": "imagem"}))
        self.assertIn("esta marca publica em inglês", llm.call_args.kwargs["prompt"])


class CommentReplyTests(unittest.TestCase):
    def test_english_brand_always_replies_in_english(self):
        rule = ig_engagement.reply_language_rule(EN)
        self.assertIn("SEMPRE em inglês", rule)
        self.assertNotIn("Comentário em outro idioma: needs_human=true", rule)

    def test_portuguese_brand_keeps_previous_behaviour(self):
        self.assertIn("Comentário em outro idioma: needs_human=true", ig_engagement.reply_language_rule(PT))

    def test_style_no_longer_blocks_every_foreign_comment(self):
        self.assertNotIn("outro idioma", ig_engagement.REPLY_STYLE)
        self.assertIn("Spam", ig_engagement.REPLY_STYLE)

    def test_reply_prompt_carries_the_rule(self):
        llm = AsyncMock(return_value={"reply": "Thank you so much! 💛", "needs_human": False, "reason": ""})
        with patch("services.studio_calendar.load_profile", AsyncMock(return_value={"profile": EN})), \
             patch.object(ig_engagement, "get_settings", AsyncMock(return_value={})), \
             patch.object(ig_engagement, "sb_select", AsyncMock(return_value=[])), \
             patch.object(ig_engagement, "_reply_examples", AsyncMock(return_value={"manual": [], "recent": []})), \
             patch.object(ig_engagement, "_brand_voice", AsyncMock(return_value=[])), \
             patch("services.brand_knowledge.knowledge_for_prompt", AsyncMock(return_value="")), \
             patch("services.studio_llm.llm_json", llm):
            out = run(ig_engagement._ai_answer("latinas", {"text": "Love this collection!", "username": "maria"}))
        self.assertIn("SEMPRE em inglês", llm.call_args.kwargs["prompt"])
        self.assertEqual(out["reply"], "Thank you so much! 💛")


if __name__ == "__main__":
    unittest.main()
