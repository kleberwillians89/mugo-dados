import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import studio_intelligence as si


def media(i, reach, likes=0, saved=0, ts="2026-11-10T22:00:00+0000"):
    return {"media_id": f"1790000000{i:02d}", "media_type": "IMAGE", "media_product_type": "FEED", "timestamp": ts, "caption": f"post {i}",
            "insights_json": {"reach": reach, "likes": likes, "comments": 1, "saved": saved, "shares": 2}}


class PostsTests(unittest.IsolatedAsyncioTestCase):
    async def test_posts_trazem_curtidas_salvamentos_hora_e_a_pauta_que_gerou(self):
        rows = [media(i, 100 + i * 10, likes=i, saved=i * 2) for i in range(20)]
        pauta = [{"published_media_id": "179000000019", "title": "Como lavar a legging", "hook": "Você lava errado", "pillar": "Educação"}]

        async def select(table, **kw):
            return rows if table == "ig_media" else pauta
        with patch.object(si, "sb_select", AsyncMock(side_effect=select)):
            out = await si._posts("roove", 90)
        self.assertEqual(out["analisados"], 20)
        self.assertEqual((len(out["melhores"]), len(out["piores"])), (10, 5))
        top = out["melhores"][0]
        self.assertEqual((top["curtidas"], top["salvamentos"], top["compartilhamentos"]), (19, 38, 2))
        self.assertEqual(top["pauta_do_mugoverso"], {"pauta": "Como lavar a legging", "gancho": "Você lava errado", "pilar": "Educação"})
        self.assertEqual((top["dia"], top["hora"]), ("terça", 19))
        self.assertEqual(out["media_por_post"]["curtidas"], 9.5)
        self.assertEqual(out["ligados_a_pauta"], 1)
        self.assertFalse(set(m["legenda"] for m in out["melhores"]) & set(m["legenda"] for m in out["piores"]))

    async def test_poucos_posts_nao_repetem_entre_melhores_e_piores(self):
        with patch.object(si, "sb_select", AsyncMock(side_effect=lambda table, **kw: [media(i, 100 + i) for i in range(6)] if table == "ig_media" else [])):
            out = await si._posts("roove", 90)
        self.assertEqual((len(out["melhores"]), out["piores"]), (6, []))


class PaidCreativesTests(unittest.IsolatedAsyncioTestCase):
    async def test_anuncio_por_anuncio_com_texto_do_midia_on(self):
        stats = [
            {"ad_id": "1", "ad_name": "Legging A", "campaign_name": "BF", "stat_date": "2026-11-02", "spend": 50, "impressions": 1000, "clicks": 20, "conversions": 2, "revenue": 400},
            {"ad_id": "1", "ad_name": "Legging A", "campaign_name": "BF", "stat_date": "2026-03-10", "spend": 50, "impressions": 1000, "clicks": 20, "conversions": 1, "revenue": 200},
            {"ad_id": "2", "ad_name": "Top B", "campaign_name": "BF", "spend": 80, "impressions": 2000, "clicks": 10, "conversions": 1, "revenue": 90},
            {"ad_id": "3", "ad_name": "Teste", "campaign_name": "BF", "spend": 5, "impressions": 100, "clicks": 1, "conversions": 0, "revenue": 0},
        ]
        drafts = [{"meta_ids": {"ad_ids": ["1"]}, "payload": {"name": "BF", "objective": "vendas", "daily_budget": 50,
                   "ad": {"primary_text": "Sua legging favorita", "headline": "Compre já", "cta": "SHOP_NOW", "image_url": "https://x/a.jpg"}}}]

        async def select(table, **kw):
            return stats if table == "ad_daily_stats" else drafts
        with patch.object(si, "sb_select", AsyncMock(side_effect=select)):
            out = await si._paid_creatives("roove")
        self.assertEqual((out["comparado_por"], out["anuncios_com_gasto"]), ("roas", 2))
        best = out["melhores"][0]
        self.assertEqual((best["anuncio"], best["roas"], best["conversoes"], best["ctr_pct"]), ("Legging A", 6.0, 3, 2.0))
        self.assertEqual((best["rodou_de"], best["rodou_ate"]), ("2026-03-10", "2026-11-02"))
        self.assertEqual(out["periodo"], "últimos 365 dias")
        self.assertEqual(best["criado_no_mugoverso"]["texto"], "Sua legging favorita")
        self.assertEqual(best["criado_no_mugoverso"]["formato"], "imagem")
        self.assertNotIn("criado_no_mugoverso", out["melhores"][1])

    async def test_le_em_paginas_ate_acabar(self):
        page = [{"ad_id": str(i), "ad_name": f"Ad {i}", "stat_date": "2026-11-01", "spend": 30, "impressions": 100, "clicks": 1}
                for i in range(si.PAGE)]
        calls = []

        async def select(table, **kw):
            if table != "ad_daily_stats":
                return []
            calls.append(kw["offset"])
            return page if kw["offset"] == 0 else page[:10]
        with patch.object(si, "sb_select", AsyncMock(side_effect=select)):
            out = await si._paid_creatives("roove")
        self.assertEqual(calls, [0, si.PAGE])
        self.assertEqual(out["anuncios_com_gasto"], si.PAGE)

    async def test_sem_gasto_fica_vazio(self):
        with patch.object(si, "sb_select", AsyncMock(return_value=[])):
            self.assertEqual(await si._paid_creatives("roove"), {})
