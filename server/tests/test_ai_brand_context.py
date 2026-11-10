"""A IA sempre conhece a marca: memória + contexto do negócio na Inteligência, reprocessamento e teto."""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import brand_knowledge as bk  # noqa: E402
from services import business_context as bc  # noqa: E402
from services import intelligence as intel  # noqa: E402

CTX = {"available": True, "context": {"segment": "Perfumaria de nicho", "audience": "Mulheres 25-45", "goals": None}}


class BrandContextTests(unittest.TestCase):
    def test_memory_joins_business_context(self):
        with patch.object(intel, "load_business_context", AsyncMock(return_value=CTX)), \
             patch.object(intel, "_brand_memory", AsyncMock(return_value="- Frasco de # ml, tom elegante")):
            out = asyncio.run(intel._business_context_with_memory("ruah"))
        self.assertEqual(out["context"]["brand_memory"], "- Frasco de # ml, tom elegante")
        self.assertEqual(out["context"]["segment"], "Perfumaria de nicho")
        self.assertTrue(out["brand_memory_available"])

    def test_memory_goes_without_numbers(self):
        # Número no contexto faria a validação da Inteligência recusar a resposta.
        with patch("services.brand_knowledge.knowledge_for_prompt", AsyncMock(return_value="Kit 50 ml: R$ 1.389,90 em 2026")):
            text = asyncio.run(intel._brand_memory("ruah"))
        self.assertEqual(text, "Kit # ml: R$ # em #")
        self.assertIsNone(intel._NUMBER_IN_TEXT.search(text) if hasattr(intel, "_NUMBER_IN_TEXT") else None)

    def test_without_memory_context_is_unchanged(self):
        # Sem memória, a impressão digital da análise não muda: nada é regenerado à toa.
        with patch.object(intel, "load_business_context", AsyncMock(return_value=CTX)), \
             patch.object(intel, "_brand_memory", AsyncMock(return_value="")):
            out = asyncio.run(intel._business_context_with_memory("ruah"))
        self.assertIs(out, CTX)
        self.assertNotIn("brand_memory", out["context"])

    def test_compact_context_is_short_and_skips_empty(self):
        compact = bc.compact_brand_context({"segment": "x" * 900, "goals": None, "brand_memory": "m" * 5000})
        self.assertEqual(len(compact["segment"]), bc.COMPACT_FIELD_CHARS)
        self.assertEqual(len(compact["brand_memory"]), bc.COMPACT_MEMORY_CHARS)
        self.assertNotIn("goals", compact)
        self.assertIsNone(bc.compact_brand_context({"segment": None}))

    def test_chat_payload_gets_context_only_if_it_fits(self):
        from services.intelligence_tools import MAX_INPUT_CHARS
        small = intel._with_brand_context({"question": "Como foram as vendas?"}, {"segment": "Perfumaria"})
        self.assertEqual(small["brand_context"], {"segment": "Perfumaria"})
        big = {"question": "q", "evidence": "e" * (MAX_INPUT_CHARS - 200)}
        out = intel._with_brand_context(big, {"brand_memory": "m" * 1400})
        self.assertNotIn("brand_context", out)  # não cabe: a resposta sai só com as evidências, sem quebrar
        self.assertEqual(intel._with_brand_context({"q": 1}, None), {"q": 1})


class RetryTests(unittest.TestCase):
    def docs(self, *items):
        return [{"id": f"d{i}", "client_id": "ruah", "name": f"doc{i}", "kind": "produto", "status": s, "error": e}
                for i, (s, e) in enumerate(items)]

    def test_retries_until_two_failures_in_a_row(self):
        rows = self.docs(("falhou", "AI_PROVIDER_ERROR"), ("falhou", "AI_PROVIDER_ERROR"),
                         ("falhou", "AI_PROVIDER_ERROR"), ("pendente", None))
        results = iter([{"document": {"status": "aprendido"}}, {"document": {"status": "falhou"}},
                        {"document": {"status": "falhou"}}, {"document": {"status": "aprendido"}}])
        with patch.object(bk, "sb_select", AsyncMock(return_value=rows)), \
             patch.object(bk, "source_text", AsyncMock(return_value="texto do material")), \
             patch.object(bk, "_process", AsyncMock(side_effect=lambda *a, **k: next(results))) as proc:
            out = asyncio.run(bk.retry_failed())
        self.assertEqual((out["learned"], out["failed"]), (1, 2))
        self.assertEqual(proc.await_count, 3)  # parou depois de duas falhas seguidas

    def test_skips_tenant_leak_and_empty_text(self):
        rows = self.docs(("falhou", "AI_TENANT_LEAK"), ("falhou", "AI_PROVIDER_TIMEOUT"))
        with patch.object(bk, "sb_select", AsyncMock(return_value=rows)), \
             patch.object(bk, "source_text", AsyncMock(return_value="  ")), \
             patch.object(bk, "_process", AsyncMock()) as proc:
            out = asyncio.run(bk.retry_failed())
        proc.assert_not_awaited()
        self.assertEqual(out["skipped"], 2)

    def test_filter_scoped_to_company_when_given(self):
        with patch.object(bk, "sb_select", AsyncMock(return_value=[])) as sel:
            asyncio.run(bk.retry_failed("ruah"))
        filters = sel.await_args.kwargs["filters"]
        self.assertEqual(filters["client_id"], "eq.ruah")
        self.assertIn("status.eq.falhou", filters["or"])


class ThrottleTests(unittest.TestCase):
    def test_ai_routes_answer_429_when_over_limit(self):
        from fastapi import HTTPException
        from routes import intelligence as route
        from services import studio_engines
        studio_engines._calls.pop("teto-teste", None)
        for _ in range(studio_engines.AI_CALLS_PER_MINUTE):
            route._ai_throttle("teto-teste")
        with self.assertRaises(HTTPException) as ctx:
            route._ai_throttle("teto-teste")
        self.assertEqual(ctx.exception.status_code, 429)
        route._ai_throttle("outra-empresa")  # o teto é por empresa


if __name__ == "__main__":
    unittest.main()


class McpMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_business_context_carries_memory_without_personal_data(self):
        from mcp_readonly import tools
        memory = "Produtos e preços:\n- Kit 50 ml: R$ 389\n- Atendimento: (11) 99316-1161\n- Tom: elegante, sem gírias"
        with patch.object(tools, "require_user_client_access", AsyncMock()), \
             patch("services.business_context.load_business_context", AsyncMock(return_value={"available": False, "context": {}})), \
             patch("services.brand_knowledge.knowledge_for_prompt", AsyncMock(return_value=memory)):
            ctx = await tools.dispatch("u", "get_business_context", "a", start="2026-10-01", end="2026-10-31")
        self.assertTrue(ctx["available"])
        self.assertIn("Kit 50 ml: R$ 389", ctx["brand_memory"])
        self.assertIn("Tom: elegante, sem gírias", ctx["brand_memory"])
        self.assertFalse(any("99316" in line for line in ctx["brand_memory"]))  # linha com telefone sai inteira
