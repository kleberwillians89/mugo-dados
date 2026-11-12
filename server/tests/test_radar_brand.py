import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import radar_brand as rb  # noqa: E402

TRENDS = {"status": "ok", "items": [
    {"id": "t1", "topic": "Beaujolais Nouveau", "news_title": "Vinho chega às lojas"},
    {"id": "t2", "topic": "Final do campeonato", "news_title": None},
    {"id": "t3", "topic": "Black Friday", "news_title": "Descontos em vinhos importados"},
]}


class BrandTrendsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        rb._cache.clear()

    async def test_each_brand_gets_its_own_ai_pick(self):
        async def profile(cid):
            return (f"Marca: {cid}", [])
        picks = {"curavino": {"picks": [{"id": "t1", "why": "vinho", "idea": "post"}, {"id": "t1", "why": "dup", "idea": ""}]},
                 "roove": {"picks": []}}
        llm = AsyncMock(side_effect=lambda **kw: picks[kw["client_id"]])
        with patch.object(rb, "brand_profile", profile), patch("services.studio_llm.llm_json", llm):
            a = await rb.brand_trends("curavino", TRENDS)
            b = await rb.brand_trends("roove", TRENDS)
        self.assertEqual([i["topic"] for i in a["items"]], ["Beaujolais Nouveau"])
        self.assertEqual(b["items"], [])  # nada ligado à marca: nada de lista alheia
        self.assertEqual(a["method"], "ia")

    async def test_without_ai_only_topics_matching_brand_terms(self):
        with patch.object(rb, "brand_profile", AsyncMock(return_value=("Marca: Curavino", ["vinhos", "Curavino"]))), \
             patch("services.studio_llm.llm_json", AsyncMock(side_effect=RuntimeError("sem IA"))):
            out = await rb.brand_trends("curavino", TRENDS)
        self.assertEqual([i["id"] for i in out["items"]], ["t3"])
        self.assertEqual(out["method"], "termos")


if __name__ == "__main__":
    unittest.main()
