"""Mensagens ao cliente sempre com base nos dados: sem travessão, sem número faltando, venda da Origem das vendas."""
from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import studio_messages as sm
from services.studio_calendar import StudioError

CONTACT = {"id": "c1", "name": "Nasser Alves", "phone": "5511971201557", "role": None, "receives": ["trafego", "resultados"], "is_primary": True}
# Caso real da Curavino: KPI oficial da loja indisponível, mas a página Origem das vendas tem os pedidos.
SNAP_NO_STORE = {"metrics": {"investment": {"value": 523.41}, "revenue": {"value": None}, "roas": {"value": None}},
                 "campaigns": [{"name": "curavino_shopping_geral", "spend": 523.41, "conversions": 12}]}
ORIGIN = {"status": "available", "totals": {"revenue": 4973.04, "orders": 13},
          "channels": [{"channel": "organic_search", "orders": 5, "revenue": 1854.93},
                       {"channel": "paid_search", "orders": 5, "revenue": 1818.07}],
          "campaigns": [{"campaign": "curavino_shopping_geral", "orders": 5, "revenue": 1818.07}]}


class SentenceTests(unittest.TestCase):
    def test_clean_sentence_removes_dashes_and_final_period(self):
        self.assertEqual(sm.clean_sentence("Investimos R$523,41 — seguimos monitorando.."), "Investimos R$523,41, seguimos monitorando")
        self.assertEqual(sm.clean_sentence("  ok!  "), "ok")


class TrafficFromSalesOriginTests(unittest.IsolatedAsyncioTestCase):
    async def build(self, origin, sentence="a campanha curavino_shopping_geral trouxe 5 pedidos e R$ 1.818,07."):
        ai = AsyncMock(return_value={"sentence": sentence})
        with patch.object(sm, "list_contacts", AsyncMock(return_value=[CONTACT])), \
             patch.object(sm, "_client_name", AsyncMock(return_value="Curavino")), \
             patch.object(sm, "_snapshot", AsyncMock(return_value=SNAP_NO_STORE)), \
             patch("services.sales_by_origin.build_sales_by_origin", AsyncMock(return_value=origin)), \
             patch("services.studio_llm.llm_json", ai), redirect_stdout(io.StringIO()):
            return await sm.build_message("cura", "trafego"), ai

    async def test_store_revenue_comes_from_sales_origin_when_official_kpi_is_missing(self):
        built, ai = await self.build(ORIGIN)
        self.assertEqual(built["params"]["receita"], "R$ 4.973,04")
        self.assertEqual(built["params"]["roas"], "R$ 9,50")
        self.assertNotIn("—", built["text"])
        self.assertNotIn("..", built["text"])
        self.assertIn("Destaque: a campanha curavino_shopping_geral trouxe 5 pedidos e R$ 1.818,07. Os detalhes", built["text"])
        self.assertIn("curavino_shopping_geral", str(ai.await_args.kwargs["prompt"]))

    async def test_generic_ai_sentence_without_numbers_falls_back_to_sales(self):
        built, _ = await self.build(ORIGIN, sentence="Seguimos monitorando para otimizar os resultados.")
        self.assertEqual(built["params"]["destaque"], "a campanha curavino_shopping_geral trouxe 5 pedido(s) e R$ 1.818,07 em vendas")

    async def test_without_any_store_revenue_the_message_is_not_built(self):
        with self.assertRaises(StudioError) as err:
            await self.build({"status": "not_connected", "totals": None, "channels": [], "campaigns": []})
        self.assertEqual(err.exception.code, "NO_STORE_DATA")


class NeverSendMissingDataTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_missing_variable_blocks_the_message(self):
        params = {"_template": "mugo_agenda_semana", "nome": "Ana", "marca": "Roove", "semana": "03/11 a 09/11", "quantidade": "", "destaque": "x"}
        with patch.object(sm, "list_contacts", AsyncMock(return_value=[{**CONTACT, "receives": ["conteudo"]}])), \
             patch.object(sm, "_client_name", AsyncMock(return_value="Roove")), \
             patch.object(sm, "_agenda_params", AsyncMock(return_value=params)):
            with self.assertRaises(StudioError) as err:
                await sm.build_message("roove", "agenda")
        self.assertEqual(err.exception.code, "DATA_MISSING")

    async def test_dashes_in_titles_become_commas(self):
        params = {"_template": "mugo_agenda_semana", "nome": "Ana", "marca": "Roove", "semana": "03/11 a 09/11", "quantidade": "2",
                  "destaque": "Reels — lançamento (05/11)"}
        with patch.object(sm, "list_contacts", AsyncMock(return_value=[{**CONTACT, "receives": ["conteudo"]}])), \
             patch.object(sm, "_client_name", AsyncMock(return_value="Roove")), \
             patch.object(sm, "_agenda_params", AsyncMock(return_value=params)):
            built = await sm.build_message("roove", "agenda")
        self.assertNotIn("—", built["text"])
        self.assertIn("Reels, lançamento (05/11)", built["text"])


if __name__ == "__main__":
    unittest.main()
