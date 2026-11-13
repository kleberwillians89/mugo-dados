"""Web search in chat: safe topical routing and source provenance."""
import unittest
from unittest.mock import AsyncMock, patch

from services import mugo_ia_web as web


class WebResearchTests(unittest.IsolatedAsyncioTestCase):
    def test_does_not_search_private_kpi_question(self):
        self.assertIsNone(web.category("Quanto faturamos ontem?"))
        self.assertIsNone(web.category("Qual cliente comprou mais?"))

    def test_market_search_trigger(self):
        self.assertEqual(web.category("Quais tendências de mercado existem?"), "tendencias")
        self.assertEqual(web.category("Pesquise campanhas e referências atuais"), "conteudo")

    def test_only_https_sources(self):
        rows = [{"source_url": "https://example.com/a", "reason_relevant": "Título", "researched_at": "2026-11-12"},
                {"source_url": "http://example.com", "reason_relevant": "Ruim", "researched_at": "2026-11-12"},
                {"source_url": "https://user:pass@example.com", "reason_relevant": "Ruim", "researched_at": "2026-11-12"}]
        self.assertEqual([x["url"] for x in web.safe_sources(rows)], ["https://example.com/a"])

    async def test_no_search_without_trigger(self):
        with patch.object(web, "get_provider") as provider:
            result = await web.research("company-a", "Vendas do mês")
            self.assertEqual(result["status"], "not_needed")
            provider.assert_not_called()

    async def test_no_provider(self):
        with patch.object(web, "get_provider", return_value=None):
            self.assertEqual((await web.research("company-a", "Tendências de mercado"))["status"], "not_configured")

    async def test_tenant_is_forwarded_not_question(self):
        provider = type("Provider", (), {})()
        provider.find_market_signals = AsyncMock(return_value=[
            {"source_url": "https://example.com", "reason_relevant": "Tendência", "researched_at": "2026-11-12"}
        ])
        with patch.object(web, "get_provider", return_value=provider):
            result = await web.research("company-a", "Pesquisar tendências: relatório privado segredo 123")
        self.assertEqual(result["status"], "ok")
        provider.find_market_signals.assert_awaited_once_with(client_id="company-a", query={})

    async def test_errors_fail_closed(self):
        provider = type("Provider", (), {})()
        provider.find_market_signals = AsyncMock(side_effect=RuntimeError("upstream"))
        with patch.object(web, "get_provider", return_value=provider):
            result = await web.research("company-a", "mercado")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["sources"], [])


if __name__ == "__main__":
    unittest.main()
