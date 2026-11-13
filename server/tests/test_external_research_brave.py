"""Contratos do adaptador Brave sem rede nem credenciais reais."""
import os
import unittest
from unittest.mock import AsyncMock, patch

from services import external_research
from services import external_research_brave as brave


class BraveParsingTests(unittest.TestCase):
    def test_missing_credentials_disabled(self):
        with patch.dict(os.environ, {"EXTERNAL_RESEARCH_PROVIDER": "brave", "BRAVE_SEARCH_API_KEY": ""}):
            self.assertIsNone(brave.from_environment())

    def test_https_evidence_only(self):
        items = brave._results({"web": {"results": [
            {"title": "Fonte real", "description": "Resultado", "url": "https://exemplo.com/artigo"},
            {"title": "Inseguro", "url": "http://exemplo.com"},
            {"title": "Sem origem", "url": "javascript:alert(1)"},
            {"title": "", "url": "https://exemplo.com/sem-titulo"},
        ]}}, category="market")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source_url"], "https://exemplo.com/artigo")
        self.assertEqual(items[0]["kind"], external_research.CONTENT_REFERENCE)
        self.assertTrue(items[0]["researched_at"])

    def test_provider_selection(self):
        with patch.dict(os.environ, {"EXTERNAL_RESEARCH_PROVIDER": "brave", "BRAVE_SEARCH_API_KEY": "test-key"}):
            with patch.object(external_research, "_provider", None):
                self.assertTrue(external_research.provider_configured())
                self.assertEqual(external_research.get_provider().name, "brave")


class BraveProviderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        brave._cache.clear()

    async def test_no_brand_no_external_request(self):
        provider = brave.BraveSearchProvider("fake")
        with patch.object(brave, "_public_brand_name", new=AsyncMock(return_value="")):
            with patch.object(brave.httpx, "AsyncClient") as http:
                self.assertEqual(await provider.find_market_signals(client_id="company-a", query={}), [])
                http.assert_not_called()

    async def test_no_verified_creators_from_search(self):
        provider = brave.BraveSearchProvider("fake")
        self.assertEqual(await provider.find_creators(client_id="company-a", query={}), [])

    async def test_isolated_cache_by_company(self):
        provider = brave.BraveSearchProvider("fake")
        class Response:
            def raise_for_status(self): pass
            def json(self):
                return {"web": {"results": [{"title": "Fonte", "url": "https://exemplo.com"}]}}
        class Http:
            def __init__(self): self.calls = []
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return None
            async def get(self, url, **kw):
                self.calls.append(kw["params"]["q"])
                return Response()
        http = Http()
        async def brand(client_id):
            return {"company-a": "Marca A", "company-b": "Marca B"}[client_id]
        with patch.object(brave, "_public_brand_name", side_effect=brand), patch.object(brave.httpx, "AsyncClient", return_value=http):
            await provider.find_market_signals(client_id="company-a", query={})
            await provider.find_market_signals(client_id="company-a", query={})
            await provider.find_market_signals(client_id="company-b", query={})
        self.assertEqual(len(http.calls), 2)
        self.assertIn("Marca A", http.calls[0])
        self.assertIn("Marca B", http.calls[1])


if __name__ == "__main__":
    unittest.main()
