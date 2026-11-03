"""Perfil da marca com IA avançada: fontes, imagens, proteção do que é manual e sugestão mensal."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import unittest
from unittest.mock import AsyncMock, patch

from services import studio_brand_brain as bb
from services import studio_llm as sl


def post(likes=0, saved=0, shares=0, reach=100, kind="IMAGE", caption="legenda", url="https://cdn/x.jpg", ts="2026-10-01T10:00:00Z"):
    return {"media_type": kind, "media_product_type": "FEED", "timestamp": ts, "caption": caption, "media_url": url,
            "thumbnail_url": "https://cdn/thumb.jpg", "permalink": f"https://ig/{likes}-{saved}-{ts}",
            "insights_json": {"likes": likes, "saved": saved, "shares": shares, "reach": reach}}


class RankTests(unittest.TestCase):
    def test_top_by_likes_then_by_saves_without_repeating(self):
        rows = [post(likes=i, saved=0, ts=f"2026-10-{i+1:02d}T10:00:00Z") for i in range(20)]
        rows.append(post(likes=0, saved=50, shares=10, ts="2026-09-01T10:00:00Z"))
        ranked = bb.rank_posts(rows)
        self.assertEqual(ranked["mais_curtidos"][0]["curtidas"], 19)
        self.assertEqual(len(ranked["mais_curtidos"]), 12)
        self.assertEqual(ranked["mais_salvos_e_compartilhados"][0]["salvos"], 50)
        self.assertEqual(len(ranked["mais_fracos"]), 5)
        self.assertEqual(len(ranked["_images"]), 6)
        self.assertNotIn("_image", ranked["mais_curtidos"][0])

    def test_video_uses_cover_image(self):
        ranked = bb.rank_posts([post(likes=5, kind="VIDEO", url="https://cdn/video.mp4")])
        self.assertEqual(ranked["_images"], ["https://cdn/thumb.jpg"])


class ProtectTests(unittest.TestCase):
    def test_manual_avoid_and_restrictions_survive(self):
        current = {"keywords_avoid": ["barato"], "restrictions": "Nunca prometer frete grátis.",
                   "custom_dates": [{"date": "03-15", "label": "Aniversário"}]}
        suggested = {"tone_of_voice": "leve", "keywords_avoid": ["imperdível", "Barato"], "restrictions": "Evitar contagem regressiva.",
                     "pillars": [], "posts_per_week": 3, "formats_enabled": ["reels"]}
        out = bb.protect_manual(suggested, current)
        self.assertEqual(out["keywords_avoid"], ["barato", "imperdível"])
        self.assertIn("Nunca prometer frete grátis.", out["restrictions"])
        self.assertIn("Evitar contagem regressiva.", out["restrictions"])
        self.assertEqual(out["custom_dates"], current["custom_dates"])

    def test_same_restriction_not_duplicated(self):
        out = bb.protect_manual({"restrictions": "nunca prometer frete grátis."}, {"restrictions": "Nunca prometer frete grátis."})
        self.assertEqual(out["restrictions"], "Nunca prometer frete grátis.")


class SuggestTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_profile_model_images_and_returns_reasons(self):
        sources = {"intel": {}, "posts": {"analisados": 30}, "validations": {"aprovados": [{}], "textos_reescritos_pelo_cliente": [{}]},
                   "images": ["data:image/jpeg;base64,AA=="], "gaps": []}
        answer = {"tone_of_voice": "leve", "personality": "", "audience": "", "pillars": [], "keywords_use": [], "keywords_avoid": [],
                  "hashtags": [], "restrictions": "", "visual_identity": "Tons terrosos, produto ao centro.", "posts_per_week": 4,
                  "formats_enabled": ["reels"], "reasons": [{"campo": "Tom", "motivo": "9 dos 12 posts mais curtidos usam humor leve"}],
                  "notes": ["ok"]}
        llm = AsyncMock(return_value=answer)
        with patch.object(bb, "gather_sources", AsyncMock(return_value=sources)), \
             patch.object(bb, "load_profile", AsyncMock(return_value={"profile": {}})), patch.object(bb, "llm_json", llm), \
             patch.dict("os.environ", {"OPENAI_PROFILE_MODEL": "gpt-4.1"}):
            out = await bb.suggest("cura")
        self.assertEqual(llm.await_args.kwargs["model"], "gpt-4.1")
        self.assertEqual(llm.await_args.kwargs["images"], sources["images"])
        self.assertEqual(out["profile"]["visual_identity"], "Tons terrosos, produto ao centro.")
        self.assertEqual(out["reasons"][0]["campo"], "Tom")
        self.assertEqual(out["sources"]["imagens"], 1)
        self.assertEqual(out["sources"]["reescritas"], 1)


class LlmImagesTests(unittest.IsolatedAsyncioTestCase):
    async def _payload(self, **kwargs):
        class Resp:
            status_code = 200
            def json(self):
                return {"output_text": json.dumps({"a": "b"})}
        client = AsyncMock()
        client.post = AsyncMock(return_value=Resp())
        client.__aenter__.return_value = client
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}), patch.object(sl.httpx, "AsyncClient", return_value=client):
            await sl.llm_json(instructions="i", prompt="p", schema_name="s", schema=sl.obj({"a": sl.STR}), **kwargs)
        return client.post.await_args.kwargs["json"]

    async def test_images_go_with_text(self):
        payload = await self._payload(images=["data:image/png;base64,AA=="], model="gpt-4.1")
        content = payload["input"][0]["content"]
        self.assertEqual(content[0]["type"], "input_text")
        self.assertEqual(content[1]["type"], "input_image")
        self.assertIn("temperature", payload)

    async def test_reasoning_model_has_no_temperature(self):
        payload = await self._payload(model="gpt-5")
        self.assertNotIn("temperature", payload)
        self.assertEqual(payload["input"], "p")


class MonthlyTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_per_brand_per_month_and_failures_isolated(self):
        selects = AsyncMock(side_effect=[[{"id": "ja"}], [], []])
        insert = AsyncMock()
        suggest = AsyncMock(side_effect=[{"profile": {}}, RuntimeError("x")])
        with patch.object(bb, "_active_clients", AsyncMock(return_value=["a", "b", "c"])), patch.object(bb, "sb_select", selects), \
             patch.object(bb, "sb_insert", insert), patch.object(bb, "suggest", suggest):
            out = await bb.run_monthly()
        self.assertEqual((out["skipped"], out["created"], out["failed"]), (1, 1, 1))
        self.assertEqual(insert.await_args.args[1]["status"], "pendente")

    async def test_resolve_rejects_unknown_status(self):
        with self.assertRaises(bb.StudioError):
            await bb.resolve_suggestion("a", "id", "apagada", user_id="u")


if __name__ == "__main__":
    unittest.main()
