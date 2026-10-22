"""Diagnóstico de origem FBITS: só campos de origem, nunca dado pessoal."""

import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.fbits_client import FbitsApiError  # noqa: E402
from services.fbits_origin_probe import describe_order_origin, probe_fbits_order_origin  # noqa: E402

ORDER_WITH_UTM = {
    "pedidoId": 101, "data": "2026-10-20T10:00:00", "canalNome": "Loja", "canalOrigem": "Site",
    "origemPedido": {"id": 1, "nome": "Loja virtual", "subOrigem": {"id": 2, "nome": "Instagram"}},
    "usuario": {"usuarioId": 9, "nome": "Maria Silva", "email": "maria@exemplo.com", "cpf": "123.456.789-00",
                "telefoneCelular": "11999999999", "origemContato": "Google"},
    "metadados": [{"chave": "utm_source", "valor": "facebook"}, {"chave": "utm_medium", "valor": "cpc"},
                  {"chave": "utm_campaign", "valor": "dia_dos_pais"}, {"chave": "observacao_interna", "valor": "ligar para Maria"},
                  {"chave": "email_contato", "valor": "maria@exemplo.com"}],
    "pagamento": [{"nome": "Cartão", "numero": "4111"}],
    "enderecoEntrega": {"cep": "01000-000"},
}
ORDER_PLAIN = {"pedidoId": 102, "data": "2026-10-21T10:00:00", "canalNome": "Loja", "usuario": {"usuarioId": 10, "email": "joao@x.com"}}
PII = ("Maria Silva", "maria@exemplo.com", "123.456.789-00", "11999999999", "ligar para Maria", "4111", "01000-000", "joao@x.com")


class FakeClient:
    requests_made = 0

    def __init__(self, orders, fail=None):
        self.orders, self.fail = orders, fail

    async def iter_order_pages(self, **kwargs):
        if self.fail:
            raise self.fail
        self.requests_made += 1
        yield list(self.orders)

    async def get_order(self, order_id):
        self.requests_made += 1
        return next(order for order in self.orders if str(order["pedidoId"]) == str(order_id))


class ProbeTests(unittest.TestCase):
    def test_describe_shows_origin_and_hides_personal_data(self):
        view = describe_order_origin(ORDER_WITH_UTM)
        dump = json.dumps(view, ensure_ascii=False)
        for secret in PII:
            self.assertNotIn(secret, dump)
        self.assertEqual(view["metadados"]["campos_de_origem"]["utm_campaign"], "dia_dos_pais")
        self.assertIn("observacao_interna", view["metadados"]["outras_chaves_ocultas"])
        self.assertEqual(view["campos_de_origem_no_topo"]["origemPedido"]["subOrigem"]["nome"], "Instagram")
        self.assertEqual(view["usuario.origemContato"], "Google")
        self.assertEqual(view["origem_calculada_pelo_mugo"]["origin_channel"], "paid_social")

    def test_probe_summarizes_recent_orders_and_details(self):
        result = asyncio.run(probe_fbits_order_origin("curavino", client=FakeClient([ORDER_WITH_UTM, ORDER_PLAIN]), limit=10, detail_sample=1))
        self.assertTrue(result["ok"])
        self.assertEqual(result["resumo_lista"]["pedidos_analisados"], 2)
        self.assertEqual(result["resumo_lista"]["origem_por_tipo"]["utm"], 1)
        self.assertIn("1 de 2 pedidos têm UTM", result["resumo_lista"]["veredito"])
        self.assertEqual(len(result["pedidos_detalhe"]), 1)
        dump = json.dumps(result, ensure_ascii=False)
        for secret in PII:
            self.assertNotIn(secret, dump)

    def test_single_order(self):
        result = asyncio.run(probe_fbits_order_origin("curavino", order_id="101", client=FakeClient([ORDER_WITH_UTM])))
        self.assertIsNone(result["resumo_lista"])
        self.assertEqual(result["pedidos_detalhe"][0]["pedidoId"], 101)

    def test_no_utm_verdict(self):
        result = asyncio.run(probe_fbits_order_origin("curavino", client=FakeClient([ORDER_PLAIN]), detail_sample=0))
        self.assertIn("Nenhum pedido com UTM", result["resumo_lista"]["veredito"])

    def test_api_error_is_reported_without_raising(self):
        error = FbitsApiError("Limite de requisições.", code="FBITS_RATE_LIMITED", status_code=429)
        result = asyncio.run(probe_fbits_order_origin("curavino", client=FakeClient([], fail=error)))
        self.assertEqual(result, {"ok": False, "code": "FBITS_RATE_LIMITED", "message": "Limite de requisições."})


if __name__ == "__main__":
    unittest.main()
