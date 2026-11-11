"""A IA de conteúdo lê tudo do cliente: saúde da marca, voz do público, concorrentes e produtos que vendem."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import studio_intelligence as si

BASE = {"_profile": {}, "_business": {}, "_snapshot": {}, "_posts": {}, "_timing": {}, "_goals": [], "_analysis": {},
        "approval_learnings": {}, "_sales_origin": {}, "_media_plan": {}, "_active_campaigns": [], "_clipping": {},
        "_calendar_month": {}, "_references": []}


async def _build(extra):
    si.invalidate("ruah")
    patches = [patch.object(si, n, AsyncMock(return_value=v)) for n, v in {**BASE, **extra}.items()]
    for p in patches:
        p.start()
    try:
        return await si.build_content_intelligence("ruah", use_cache=False)
    finally:
        for p in patches:
            p.stop()


class FullContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_package_carries_health_voice_competitors_and_products(self):
        pkg = await _build({
            "_health": {"indice": 82, "situacao": "saudável"},
            "_audience_voice": "Elogiam: fixação (12).",
            "_competitors": {"cadastrados": ["Marca X"], "noticias_30_dias": 2},
            "_top_products": [{"produto": "Oud Royal", "unidades": 40, "vendas": 12000.0}],
        })
        self.assertEqual(pkg["saude_da_marca"]["indice"], 82)
        self.assertIn("fixação", pkg["voz_do_publico"])
        self.assertEqual(pkg["concorrentes"]["cadastrados"], ["Marca X"])
        prompt = si.to_prompt(pkg)
        for text in ("Oud Royal", "Marca X", "fixação", "saude_da_marca"):
            self.assertIn(text, prompt)

    async def test_failed_new_source_is_a_gap(self):
        import io
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()):
            pkg = await _build({"_health": {}, "_audience_voice": "", "_top_products": [],
                                "_competitors": {}})
        self.assertNotIn("saude_da_marca", si.to_prompt(pkg))
        with patch.object(si, "_competitors", AsyncMock(side_effect=RuntimeError("fora"))), redirect_stdout(io.StringIO()):
            pkg = await _build({"_health": {}, "_audience_voice": "", "_top_products": []})
        self.assertIn("concorrentes", pkg["lacunas"])

    async def test_top_products_merge_shopify_and_fbits(self):
        async def fake_select(table, **kwargs):
            if table == "shopify_order_items":
                return [{"title": "Oud Royal", "quantity": 2, "price": 300, "total_discount": 0}]
            return [{"product_name": "oud royal", "quantity": 1, "total_value": 280},
                    {"product_name": "Ambar", "quantity": 1, "total_value": 100}]
        with patch.object(si, "sb_select", side_effect=fake_select):
            ranked = await si._top_products("ruah")
        self.assertEqual(ranked[0]["produto"], "Oud Royal")
        self.assertEqual(ranked[0]["unidades"], 3)
        self.assertEqual(ranked[0]["vendas"], 880.0)

    async def test_competitors_skip_irrelevant_news(self):
        async def fake_select(table, **kwargs):
            if table == "studio_clipping_settings":
                return [{"competitor_terms": ["Marca X"]}]
            return [{"title": "X lança perfume", "term": "Marca X", "relevant": True},
                    {"title": "Ruído", "term": "Marca X", "relevant": False}]
        with patch.object(si, "sb_select", side_effect=fake_select):
            data = await si._competitors("ruah")
        self.assertEqual(data["noticias_30_dias"], 1)
        self.assertEqual(data["noticias"][0]["manchete"], "X lança perfume")


if __name__ == "__main__":
    unittest.main()
