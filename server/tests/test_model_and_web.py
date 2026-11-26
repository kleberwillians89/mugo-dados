"""Modelo por tarefa e pesquisa na web."""
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import studio_llm, web_research  # noqa: E402


class TaskModelTests(unittest.TestCase):
    def test_strategic_tasks_use_strong_model(self):
        with patch.dict(os.environ, {"OPENAI_STRATEGY_MODEL": "gpt-4.1"}):
            self.assertEqual(studio_llm.task_model(None, brand="estrategia"), "gpt-4.1")
            self.assertEqual(studio_llm.task_model(None, brand="criadores"), "gpt-4.1")
            self.assertEqual(studio_llm.task_model(None, tier="forte"), "gpt-4.1")
            self.assertIsNone(studio_llm.task_model(None, brand="atendimento"))
            self.assertIsNone(studio_llm.task_model(None, brand="estrategia", tier="leve"))
            self.assertEqual(studio_llm.task_model("gpt-4o", brand="estrategia"), "gpt-4o")


class LlmJsonModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_llm_json_passes_strong_model(self):
        once = AsyncMock(return_value={"ok": True})
        with patch.object(studio_llm, "_llm_json_once", once), patch("services.brand_brain.brand_block", AsyncMock(return_value="")), \
             patch.dict(os.environ, {"OPENAI_STRATEGY_MODEL": "gpt-4.1"}):
            await studio_llm.llm_json(instructions="x", prompt="p", schema_name="s", schema={}, client_id="c", leak_check=False, brand="estrategia")
            self.assertEqual(once.await_args.kwargs["model"], "gpt-4.1")
            await studio_llm.llm_json(instructions="x", prompt="p", schema_name="s", schema={}, client_id="c", leak_check=False, brand="atendimento")
            self.assertIsNone(once.await_args.kwargs["model"])


class WebResearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        web_research._CACHE.clear()

    async def test_disabled_returns_empty(self):
        with patch.dict(os.environ, {"AI_WEB_SEARCH": "off"}):
            self.assertEqual(await web_research.research("c", "quem?", feature="t"), "")

    async def test_search_once_then_cache_and_errors_are_silent(self):
        from services import ai_runtime
        runtime = ai_runtime.AiRuntime("c", "platform_managed", "openai", "gpt-4.1", "k")
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"output": [{"type": "web_search_call"}, {"type": "message", "content": [{"type": "output_text", "text": "@perfumista.br https://x"}]}]}
        post = AsyncMock(return_value=ok)
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=MagicMock(post=post))
        client.__aexit__ = AsyncMock(return_value=False)
        with patch.object(ai_runtime, "resolve", AsyncMock(return_value=runtime)), \
             patch.object(web_research.httpx, "AsyncClient", return_value=client), \
             patch("services.ai_usage.track_response"), patch.dict(os.environ, {"AI_WEB_SEARCH": "on"}):
            first = await web_research.research("c", "quem?", feature="t")
            second = await web_research.research("c", "quem?", feature="t")
        self.assertEqual(first, "@perfumista.br https://x")
        self.assertEqual(second, first)
        self.assertEqual(post.await_count, 1)
        self.assertEqual(post.await_args.kwargs["json"]["tools"][0]["type"], "web_search")
        web_research._CACHE.clear()
        bad = MagicMock(status_code=500)
        client.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=bad)))
        with patch.object(ai_runtime, "resolve", AsyncMock(return_value=runtime)), \
             patch.object(web_research.httpx, "AsyncClient", return_value=client), \
             patch("services.ai_usage.track_response"), patch.dict(os.environ, {"AI_WEB_SEARCH": "on"}):
            self.assertEqual(await web_research.research("c", "quem?", feature="t"), "")


if __name__ == "__main__":
    unittest.main()
