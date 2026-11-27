"""Clipping em cards: imagem e domínio do veículo saem do feed, da matéria (og:image) ou ficam com o ícone."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import AsyncMock, patch

from services import news_engine as ne
from services import studio_clipping as sc

GOOGLE = """<rss><channel><item><title>Live e-compras CNM - O GLOBO</title>
<link>https://news.google.com/rss/articles/CBMiXyz</link><pubDate>Wed, 19 Nov 2026 10:00:00 GMT</pubDate>
<source url="https://oglobo.globo.com">O GLOBO</source></item></channel></rss>"""
RSS = """<rss><channel><item><title>Track&amp;Field lança coleção</title><link>https://www.esportividade.com.br/x</link>
<media:content url="https://img.esportividade.com.br/capa.jpg" medium="image"/><description>texto</description></item></channel></rss>"""


class CardDataTests(unittest.IsolatedAsyncioTestCase):
    def test_feed_gives_domain_and_image(self):
        g = ne.parse_feed(GOOGLE)[0]
        self.assertEqual((g["source_domain"], g["image_url"]), ("oglobo.globo.com", None))
        r = ne.parse_feed(RSS)[0]
        self.assertEqual((r["source_domain"], r["image_url"]), ("esportividade.com.br", "https://img.esportividade.com.br/capa.jpg"))

    def test_og_image(self):
        page = '<meta property="og:image" content="https://cdn.site.com/a.jpg"><meta name="twitter:image" content="http://x/b.jpg">'
        self.assertEqual(ne.extract_og_image(page), "https://cdn.site.com/a.jpg")
        self.assertIsNone(ne.extract_og_image('<meta property="og:image" content="/rel.svg">'))

    async def test_fill_images_skips_google_and_marks_domain(self):
        updates = []
        with patch.object(sc, "sb_select", AsyncMock(return_value=[{"id": "1", "url": "https://www.site.com/m"}])), \
             patch.object(sc.news_engine, "fetch_article", AsyncMock(return_value={"text": "t", "image_url": "https://cdn/x.jpg"})), \
             patch.object(sc, "sb_update", AsyncMock(side_effect=lambda *a, **k: updates.append(k["patch"]))):
            self.assertEqual(await sc.fill_images("roove"), 1)
        self.assertEqual(updates[0], {"source_domain": "site.com", "image_url": "https://cdn/x.jpg"})


if __name__ == "__main__":
    unittest.main()
