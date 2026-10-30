from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import studio_engines as se
from services import studio_intelligence as si
from services import studio_llm as sl
from services.studio_calendar import StudioError

INTEL = {
    "marca": {"tone_of_voice": "elegante", "keywords_avoid": ["barato"], "pillars": [{"name": "Produto", "weight": 100}],
              "custom_dates": [{"date": "03-15", "label": "Aniversário"}]},
    "negocio": {"segment": "perfumaria"},
    "aprendizados": {"aprovados": [{"pauta": "Ritual noturno com Oud", "pelo_cliente": True}],
                     "ajustes_pedidos": [{"pauta": "Promo relâmpago", "comentario": "não falar de desconto"}]},
    "posts": {"analisados": 40, "melhores": [{"formato": "reels", "legenda": "Bastidores do frasco"}]},
    "kpis": [{"id": "revenue", "valor": 1000}], "campanhas_que_mais_venderam": [{"campanha": "Remarketing Oud"}],
    "metas_do_mes": [], "lacunas": ["sem_metas_no_mes"],
}


class IntelligenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        si._CACHE.clear()

    def test_personal_data_never_enters_the_package(self):
        self.assertEqual(si.clean_text("fale com ana@ex.com"), "")
        self.assertEqual(si.clean_text("ligue (11) 98888-7777"), "")
        self.assertEqual(si.clean_text("CPF 123.456.789-09"), "")
        self.assertEqual(si.clean_text("  Ritual   noturno "), "Ritual noturno")

    async def test_failing_source_becomes_a_gap_and_package_survives(self):
        async def boom(*a, **k):
            raise RuntimeError("fora do ar")
        with patch.object(si, "_profile", AsyncMock(return_value={"tone_of_voice": "x"})), \
             patch.object(si, "_business", AsyncMock(return_value={"segment": "moda"})), \
             patch.object(si, "_snapshot", boom), \
             patch.object(si, "_posts", AsyncMock(return_value={"analisados": 10, "melhores": [], "piores": []})), \
             patch.object(si, "_timing", AsyncMock(return_value={})), \
             patch.object(si, "_goals", AsyncMock(return_value=[])), \
             patch.object(si, "_analysis", AsyncMock(return_value={})), \
             patch.object(si, "approval_learnings", AsyncMock(return_value={"aprovados": [], "ajustes_pedidos": []})):
            package = await si.build_content_intelligence("roove")
            again = await si.build_content_intelligence("roove")
        self.assertIn("kpis_e_campanhas", package["lacunas"])
        self.assertIn("sem_metas_no_mes", package["lacunas"])
        self.assertEqual(package["negocio"], {"segment": "moda"})
        self.assertIs(package, again)  # cache por 10 min

    async def test_learnings_put_client_approvals_first_and_keep_adjustments(self):
        approved = [{"title": "Equipe", "reviewed_by": "u1"}, {"title": "Cliente", "reviewed_by": "cliente:Ana"}]
        adjusted = [{"title": "Promo", "review_note": "sem desconto"}, {"title": "Sem nota", "review_note": ""}]
        with patch.object(si, "sb_select", AsyncMock(side_effect=[approved, adjusted])) as select:
            out = await si.approval_learnings("roove")
        self.assertEqual(out["aprovados"][0]["pauta"], "Cliente")
        self.assertTrue(out["aprovados"][0]["pelo_cliente"])
        self.assertEqual([a["comentario"] for a in out["ajustes_pedidos"]], ["sem desconto"])
        self.assertEqual(select.await_args_list[0].kwargs["filters"]["client_id"], "eq.roove")

    def test_prompt_is_bounded_and_drops_least_important_sections_first(self):
        big = {**INTEL, "horarios": {"x": "y" * 20000}}
        text = si.to_prompt(big, limit=3000)
        self.assertLessEqual(len(text), 3000)
        self.assertIn("Ritual noturno", text)  # aprendizados ficam

    def test_coverage_summary(self):
        cov = si.coverage(INTEL)
        self.assertEqual((cov["posts_analisados"], cov["aprovados"], cov["ajustes"]), (40, 1, 1))


class AssistTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        se._calls.clear()

    async def run_assist(self, action, output, **kw):
        llm = AsyncMock(return_value=output)
        with patch.object(se, "build_content_intelligence", AsyncMock(return_value=INTEL)), patch.object(se, "llm_json", llm):
            result = await se.assist("roove", action, {"title": "Lançamento Oud", "format": "reels", "caption_draft": "texto"}, **kw)
        return result, llm

    async def test_caption_prompt_carries_data_and_learnings(self):
        result, llm = await self.run_assist("legenda", {"caption": "Nova fragrância. Imperdível!", "cta": "Link na bio", "why": "x"},
                                            instruction="mais curto")
        prompt = llm.await_args.kwargs["prompt"]
        for fragment in ("Ritual noturno com Oud", "não falar de desconto", "Remarketing Oud", "mais curto", "Lançamento Oud"):
            self.assertIn(fragment, prompt)
        self.assertEqual(result["flags"], ["imperdível"])
        self.assertEqual(result["based_on"]["aprovados"], 1)

    async def test_outputs_are_trimmed_and_normalized(self):
        result, _ = await self.run_assist("hashtags", {"hashtags": ["oud", "#Oud", "# perfume!", "#a"] + [f"t{i}" for i in range(20)], "why": "x"})
        tags = result["result"]["hashtags"]
        self.assertEqual(tags[:2], ["#oud", "#perfume"])
        self.assertLessEqual(len(tags), 15)
        result, _ = await self.run_assist("variacoes", {"variations": [{"angle": "a", "caption": "c"}] * 5, "recommended_index": 9, "why": "x"})
        self.assertEqual(len(result["result"]["variations"]), 3)
        self.assertEqual(result["result"]["recommended_index"], 0)

    async def test_empty_ai_output_is_an_error(self):
        with self.assertRaises(StudioError):
            await self.run_assist("ganchos", {"hooks": [{"hook": " ", "angle": "x"}]})

    async def test_banned_words_from_profile_are_flagged(self):
        result, _ = await self.run_assist("revisar", {"issues": [], "improved_caption": "Perfume barato e bom"})
        self.assertIn("barato", result["flags"])

    async def test_validation_and_throttle(self):
        with self.assertRaises(StudioError) as err:
            await se.assist("roove", "poema", {"title": "x"})
        self.assertEqual(err.exception.code, "ACTION_INVALID")
        with self.assertRaises(StudioError) as err:
            await se.assist("roove", "legenda", {"title": "  "})
        self.assertEqual(err.exception.code, "ITEM_TITLE_REQUIRED")
        for _ in range(se.AI_CALLS_PER_MINUTE):
            se.throttle("roove")
        with self.assertRaises(StudioError) as err:
            se.throttle("roove")
        self.assertEqual(err.exception.code, "AI_RATE_LIMIT")
        se.throttle("outra")  # o teto é por empresa


class StrategyAndBrandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        se._calls.clear()

    async def test_chat_uses_month_calendar_and_requires_user_turn(self):
        llm = AsyncMock(return_value={"reply": "Faltam Reels na semana 2.", "suggested_actions": ["a", "b", "c", "d"]})
        items = [{"scheduled_at": "2026-11-03T22:00:00+00:00", "format": "carrossel", "pillar": "Produto", "title": "Guia de notas", "status": "aprovado"}]
        with patch.object(se, "build_content_intelligence", AsyncMock(return_value=INTEL)), \
             patch.object(se, "list_items", AsyncMock(return_value=items)), patch.object(se, "llm_json", llm):
            out = await se.strategy_chat("roove", "2026-11", [{"role": "user", "content": "O que falta?"}])
            with self.assertRaises(StudioError):
                await se.strategy_chat("roove", "2026-11", [{"role": "assistant", "content": "oi"}])
        self.assertIn("Guia de notas", llm.await_args.kwargs["prompt"])
        self.assertEqual(len(out["suggested_actions"]), 3)

    async def test_profile_suggestion_is_normalized_and_keeps_custom_dates(self):
        suggestion = {"tone_of_voice": "sofisticado", "personality": "", "audience": "mulheres 30+",
                      "pillars": [{"name": "Produto", "weight": 60, "description": "d"}, {"name": "Ritual", "weight": 40, "description": "d"}],
                      "keywords_use": ["oud"], "keywords_avoid": [], "hashtags": ["#ruah"], "restrictions": "",
                      "posts_per_week": 40, "formats_enabled": ["reels", "carrossel"], "notes": ["n1"]}
        with patch.object(se, "build_content_intelligence", AsyncMock(return_value=INTEL)), \
             patch.object(se, "llm_json", AsyncMock(return_value=suggestion)):
            out = await se.suggest_profile("roove")
        self.assertEqual(out["profile"]["posts_per_week"], 14)  # normalizado
        self.assertEqual(out["profile"]["custom_dates"], [{"date": "03-15", "label": "Aniversário"}])
        self.assertEqual(out["notes"], ["n1"])

class LlmTests(unittest.IsolatedAsyncioTestCase):
    async def test_guidance_and_strict_schema_are_sent(self):
        class Resp:
            status_code = 200
            def json(self):
                return {"output_text": json.dumps({"caption": "ok"})}
        client = AsyncMock()
        client.post = AsyncMock(return_value=Resp())
        client.__aenter__.return_value = client
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}), patch.object(sl.httpx, "AsyncClient", return_value=client):
            out = await sl.llm_json(instructions="papel", prompt="p", schema_name="s", schema=sl.obj({"caption": sl.STR}))
        payload = client.post.await_args.kwargs["json"]
        self.assertIn("Proibido clichê", payload["instructions"])
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertEqual(payload["text"]["format"]["schema"]["required"], ["caption"])
        self.assertEqual(out, {"caption": "ok"})

    async def test_missing_key_is_a_clear_error(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            with self.assertRaises(StudioError) as err:
                await sl.llm_json(instructions="", prompt="", schema_name="s", schema={})
        self.assertEqual(err.exception.code, "AI_PROVIDER_NOT_CONFIGURED")


if __name__ == "__main__":
    unittest.main()
