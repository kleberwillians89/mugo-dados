"""Preços públicos: lê Shopify, JSON-LD e meta tag; recusa endereço não público; histórico mostra a mudança."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import benchmark_prices as bp

LD_PAGE = """<html><head><title>Legging X</title>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"WebSite"},
{"@type":"Product","name":"Legging Sculpt","image":["https://cdn/x.jpg"],
"offers":[{"@type":"Offer","price":"229.90","priceCurrency":"BRL","availability":"https://schema.org/InStock"},
{"@type":"Offer","price":"199,90","priceCurrency":"BRL","availability":"https://schema.org/OutOfStock"}]}]}</script></head></html>"""


class ParseTests(unittest.TestCase):
    def test_shopify_js_uses_cheapest_available_variant(self):
        out = bp.from_shopify_js({"title": "Top", "featured_image": "//cdn.shopify.com/a.jpg", "variants": [
            {"price": 15990, "compare_at_price": 19990, "available": False}, {"price": 17990, "compare_at_price": 21990, "available": True}]})
        self.assertEqual((out["price"], out["compare_at"], out["available"], out["image"]), (179.9, 219.9, True, "https://cdn.shopify.com/a.jpg"))

    def test_json_ld_graph_and_brazilian_number(self):
        out = bp.from_html(LD_PAGE)
        self.assertEqual((out["title"], out["price"], out["currency"], out["available"], out["source"]), ("Legging Sculpt", 199.9, "BRL", True, "json_ld"))

    def test_meta_tag_fallback_and_no_price(self):
        page = '<title>Kit</title><meta property="product:price:amount" content="1.299,00"><meta property="product:price:currency" content="BRL">'
        self.assertEqual(bp.from_html(page)["price"], 1299.0)
        with self.assertRaises(bp.PriceError):
            bp.from_html("<html><body>sem preço</body></html>")

    def test_numbers(self):
        self.assertEqual([bp._num(v) for v in ("1.299,90", "1,299.90", "89,9", "R$ 49", "", None)], [1299.9, 1299.9, 89.9, 49.0, None, None])

    def test_url_rules(self):
        self.assertEqual(bp.clean_url("https://Loja.com/products/x?variant=1#top"), "https://loja.com/products/x?variant=1")
        for bad in ("http://loja.com/p", "https://user:pw@loja.com/p", "https://loja.com:8080/p", "ftp://x"):
            with self.assertRaises(bp.PriceError):
                bp.clean_url(bad)

    def test_private_hosts_blocked(self):
        with patch("socket.getaddrinfo", return_value=[(0, 0, 0, "", ("10.0.0.5", 443))]):
            self.assertFalse(bp._public_host("intranet"))
        with patch("socket.getaddrinfo", return_value=[(0, 0, 0, "", ("169.254.169.254", 443))]):
            self.assertFalse(bp._public_host("metadata"))
        with patch("socket.getaddrinfo", return_value=[(0, 0, 0, "", ("104.18.2.3", 443))]):
            self.assertTrue(bp._public_host("loja.com"))

    def test_price_change(self):
        hist = [{"observed_on": "2026-11-01", "price": 229.9}, {"observed_on": "2026-11-05", "price": 229.9},
                {"observed_on": "2026-11-09", "price": 189.9}, {"observed_on": "2026-11-10", "price": 189.9}]
        self.assertEqual(bp.price_change(hist), {"on": "2026-11-09", "from": 229.9, "to": 189.9, "pct": -17.4})
        self.assertIsNone(bp.price_change(hist[:2]))

    def test_ad_library_link(self):
        self.assertIn("view_all_page_id=123456", bp.ad_library_url({"facebook_page": "https://www.facebook.com/123456"}))
        url = bp.ad_library_url({"name": "Live! Sportswear"})
        self.assertIn("country=BR", url)
        self.assertIn("q=Live%21%20Sportswear", url)


class FetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_redirect_to_private_is_blocked(self):
        first = MagicMock(status_code=302, headers={"location": "https://interno.local/x"}, content=b"")
        client = MagicMock()
        client.get = AsyncMock(return_value=first)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        hosts = {"loja.com": True, "interno.local": False}
        with patch.object(bp, "_public_host", side_effect=lambda h: hosts[h]), patch("httpx.AsyncClient", return_value=client):
            with self.assertRaises(bp.PriceError) as ctx:
                await bp._fetch("https://loja.com/p")
        self.assertEqual(ctx.exception.code, "BLOCKED_HOST")

    async def test_check_records_error_without_inventing_price(self):
        update, upsert = AsyncMock(), AsyncMock()
        product = {"id": "p1", "url": "https://loja.com/p", "price": 100}
        with patch.object(bp, "sb_select", AsyncMock(return_value=[product])), patch.object(bp, "sb_update", update), patch.object(bp, "sb_upsert", upsert), \
             patch.object(bp, "read_price", AsyncMock(side_effect=bp.PriceError("NO_PRICE", "sem preço"))):
            out = await bp.check_product("roove", "p1")
        self.assertEqual(out["error"], "sem preço")
        upsert.assert_not_awaited()
        self.assertNotIn("price", update.await_args.kwargs["patch"])


if __name__ == "__main__":
    unittest.main()
