"""Identidade do cliente FBITS: extração, persistência e Customer 360.

Os dados vêm do MESMO payload de `GET /pedidos` que o sync já lê — o objeto
`usuario` traz usuarioId, nome, email e telefoneCelular. Nenhuma requisição
externa nova, nenhum N+1.

O pedido continua sem PII: `fbits_orders` não ganha nome, e-mail nem telefone,
e `sanitize_order_raw` segue reduzindo `usuario` a usuarioId/tipoPessoa. CPF,
endereço e meio de pagamento não são lidos nem têm coluna.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import asynccontextmanager, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import httpx

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import customers, fbits_connections
from services.fbits_client import FbitsClient

MIGRATIONS = SERVER_DIR.parent / "supabase" / "migrations"
IDENTITY_MIGRATION = MIGRATIONS / "20261004_000040_fbits_customer_identity.sql"

CURAVINO = "curavino-test"
ROOVE = "roove-test"


@asynccontextmanager
async def no_lock(**_kwargs: Any):
    """O lock de sync é testado no seu próprio arquivo; aqui só estorva."""
    yield "lock"

# PII fictícia. Nome, e-mail e telefone entram em fbits_customers; CPF e
# endereço nunca, em lugar nenhum.
NAME = "Cliente Sigiloso"
EMAIL = "cliente@exemplo-curavino.com"
PHONE = "11999998888"
CPF = "12345678900"
ADDRESS = "Rua Sigilosa"


def order(
    *,
    order_id: int = 42,
    customer_id: Any = 555,
    name: str | None = NAME,
    email: str | None = EMAIL,
    phone: str | None = PHONE,
    with_cpf: bool = True,
    status_id: int = 1,
    total: float = 120.0,
    data: str = "2026-10-01T10:00:00Z",
) -> Dict[str, Any]:
    user: Dict[str, Any] = {"tipoPessoa": "Fisica"}
    if customer_id is not None:
        user["usuarioId"] = customer_id
    if name is not None:
        user["nome"] = name
    if email is not None:
        user["email"] = email
    if phone is not None:
        user["telefoneCelular"] = phone
    if with_cpf:
        user["cpf"] = CPF
    user["dataCriacao"] = "2026-01-05T08:00:00Z"
    user["dataAlteracao"] = "2026-09-30T08:00:00Z"
    return {
        "pedidoId": order_id,
        "situacaoPedidoId": status_id,
        "data": data,
        "dataPagamento": data,
        "dataUltimaAtualizacao": data,
        "valorTotalPedido": total,
        "valorSubTotalSemDescontos": total,
        "valorDesconto": 0.0,
        "valorFrete": 0.0,
        "valido": True,
        "primeiraCompra": True,
        "canalNome": "Loja",
        "usuario": user,
        "pedidoEndereco": [{"endereco": ADDRESS, "cep": "01000-000"}],
        "pagamento": [{"formaPagamentoId": 1, "cartaoCredito": [{"numeroCartao": "4111"}]}],
        "itens": [],
    }


class IdentityExtractionTests(unittest.TestCase):
    def test_the_identity_comes_from_the_order_payload(self):
        row = fbits_connections.normalize_customer(CURAVINO, order())
        self.assertEqual(row["client_id"], CURAVINO)
        self.assertEqual(row["fbits_customer_id"], "555")
        self.assertEqual(row["name"], NAME)
        self.assertEqual(row["email"], EMAIL)
        self.assertEqual(row["phone"], PHONE)

    def test_the_email_is_normalized_to_lowercase(self):
        row = fbits_connections.normalize_customer(CURAVINO, order(email="Cliente@Exemplo.COM"))
        self.assertEqual(row["email"], "cliente@exemplo.com")

    def test_only_the_declared_fields_are_persisted(self):
        row = fbits_connections.normalize_customer(CURAVINO, order())
        self.assertEqual(
            set(row),
            {
                "client_id", "fbits_customer_id", "name", "email", "phone",
                "created_at_provider", "updated_at_provider", "synced_at",
            },
        )

    def test_cpf_address_and_payment_are_never_extracted(self):
        row = fbits_connections.normalize_customer(CURAVINO, order())
        serialized = json.dumps(row, ensure_ascii=False)
        for secret in (CPF, ADDRESS, "01000-000", "4111"):
            self.assertNotIn(secret, serialized)

    def test_a_customer_without_email_keeps_it_null(self):
        row = fbits_connections.normalize_customer(CURAVINO, order(email=None))
        self.assertIsNone(row["email"])
        self.assertEqual(row["name"], NAME)

    def test_a_customer_without_phone_keeps_it_null(self):
        row = fbits_connections.normalize_customer(CURAVINO, order(phone=None))
        self.assertIsNone(row["phone"])

    def test_a_customer_without_name_keeps_it_null(self):
        row = fbits_connections.normalize_customer(CURAVINO, order(name=None))
        self.assertIsNone(row["name"])

    def test_an_order_without_customer_id_yields_no_identity(self):
        self.assertIsNone(fbits_connections.normalize_customer(CURAVINO, order(customer_id=None)))

    def test_an_order_without_a_user_object_yields_no_identity(self):
        self.assertIsNone(fbits_connections.normalize_customer(CURAVINO, {"pedidoId": 1}))

    def test_alternative_phone_fields_are_accepted(self):
        payload = order(phone=None)
        payload["usuario"]["telefone"] = "1133334444"
        self.assertEqual(
            fbits_connections.normalize_customer(CURAVINO, payload)["phone"], "1133334444",
        )

    def test_the_page_yields_one_row_per_customer(self):
        page = [
            order(order_id=1, customer_id=555),
            order(order_id=2, customer_id=555, name="Nome Atualizado"),
            order(order_id=3, customer_id=777),
            order(order_id=4, customer_id=None),
        ]
        rows = fbits_connections.normalize_customers(CURAVINO, page)
        self.assertEqual({row["fbits_customer_id"] for row in rows}, {"555", "777"})
        latest = next(row for row in rows if row["fbits_customer_id"] == "555")
        self.assertEqual(latest["name"], "Nome Atualizado")

    def test_the_identity_carries_the_tenant(self):
        for client_id in (CURAVINO, ROOVE):
            row = fbits_connections.normalize_customer(client_id, order())
            self.assertEqual(row["client_id"], client_id)


class OrdersStaySanitizedTests(unittest.TestCase):
    """A decisão anterior é preservada, não revertida."""

    def test_the_order_row_still_has_no_contact_data(self):
        row = fbits_connections.normalize_order(CURAVINO, order(), {})
        serialized = json.dumps(row, ensure_ascii=False)
        for secret in (NAME, EMAIL, PHONE, CPF, ADDRESS, "4111"):
            self.assertNotIn(secret, serialized)
        self.assertNotIn("customer_name", row)
        self.assertNotIn("customer_email", row)

    def test_the_raw_user_object_is_still_reduced(self):
        row = fbits_connections.normalize_order(CURAVINO, order(), {})
        self.assertEqual(row["raw"]["usuario"], {"usuarioId": 555, "tipoPessoa": "Fisica"})

    def test_the_order_keeps_only_the_external_customer_id(self):
        row = fbits_connections.normalize_order(CURAVINO, order(), {})
        self.assertEqual(row["customer_id"], "555")


class SyncPersistenceHarness(unittest.IsolatedAsyncioTestCase):
    """Sync real contra uma API falsa; só o banco é de mentira."""

    def setUp(self) -> None:
        self.upserts: Dict[str, List[List[Dict[str, Any]]]] = {}
        self.requests: List[httpx.Request] = []
        self.fail_customers = False
        self.connection = {
            "id": "conn-1", "client_id": CURAVINO, "provider": "fbits",
            "status": "connected", "disconnected_at": None,
            "metadata": {"revenue_status_ids": ["1"], "history_cursor": None},
            "external_key": "k", "updated_at": "2026-10-01T00:00:00Z",
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/situacoesPedido":
            return httpx.Response(200, json=[{"situacaoPedidoId": 1, "nome": "Pago"}])
        if request.url.path == "/pedidos":
            params = request.url.params
            if int(params["pagina"]) > 1:
                return httpx.Response(200, json=[])
            start = datetime.strptime(params["dataInicial"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            end = datetime.strptime(params["dataFinal"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            matching = [
                row for row in self.orders
                if start <= datetime.fromisoformat(row["data"].replace("Z", "+00:00")) < end
            ]
            return httpx.Response(200, json=matching)
        return httpx.Response(404, json={})

    async def upsert(self, table: str, rows: List[Dict[str, Any]], on_conflict: str) -> None:
        if table == "fbits_customers" and self.fail_customers:
            raise RuntimeError("relation \"fbits_customers\" does not exist")
        self.upserts.setdefault(table, []).append([dict(row) for row in rows])

    async def run_sync(self, orders: List[Dict[str, Any]]) -> tuple[Dict[str, Any], str]:
        self.orders = orders
        output = io.StringIO()
        with (
            redirect_stdout(output),
            patch.object(
                fbits_connections, "load_fbits_connection",
                AsyncMock(return_value=self.connection),
            ),
            patch.object(fbits_connections, "sb_upsert", AsyncMock(side_effect=self.upsert)),
            patch.object(fbits_connections, "sb_select", AsyncMock(return_value=[])),
            patch.object(fbits_connections, "sb_update", AsyncMock(return_value=None)),
            patch.object(
                fbits_connections, "get_connection",
                # `_token` é o JSON cifrado da conexão do tenant.
                AsyncMock(
                    return_value={
                        **self.connection,
                        "_token": json.dumps({"token": "token-do-tenant"}),
                    },
                ),
            ),
            patch.object(fbits_connections, "guarded_sync", no_lock),
            patch.object(fbits_connections, "_persist_state", AsyncMock(return_value=None)),
            patch.object(fbits_connections, "_refresh_daily_stats", AsyncMock(return_value=0)),
            patch.object(fbits_connections, "start_job_run", AsyncMock(return_value=None)),
            patch.object(fbits_connections, "finish_job_run", AsyncMock(return_value=None)),
            patch.object(fbits_connections, "invalidate_namespace", lambda *_a, **_k: None),
        ):
            payload = await fbits_connections.sync_fbits_connection(
                client_id=CURAVINO,
                client_factory=lambda token: FbitsClient(
                    token, transport=httpx.MockTransport(self.handler), sleep=AsyncMock(),
                ),
                record_job_run=False,
            )
        return payload, output.getvalue()

    def rows(self, table: str) -> List[Dict[str, Any]]:
        return [row for batch in self.upserts.get(table, []) for row in batch]


class SyncPersistenceTests(SyncPersistenceHarness):
    async def test_the_sync_persists_the_identity_alongside_the_orders(self):
        payload, _ = await self.run_sync([order(order_id=1, customer_id=555)])
        self.assertTrue(payload["ok"])
        identities = self.rows("fbits_customers")
        self.assertEqual(len(identities), 1)
        self.assertEqual(identities[0]["fbits_customer_id"], "555")
        self.assertEqual(identities[0]["name"], NAME)
        self.assertEqual(identities[0]["email"], EMAIL)
        self.assertEqual(identities[0]["phone"], PHONE)
        self.assertEqual(payload["customers_upserted"], 1)

    async def test_no_extra_external_request_is_made_for_customers(self):
        await self.run_sync([order(order_id=index, customer_id=500 + index) for index in range(1, 11)])
        paths = {request.url.path for request in self.requests}
        # Só os endpoints oficiais já usados: nada de lookup por cliente.
        self.assertTrue(paths <= {"/situacoesPedido", "/pedidos"}, paths)
        self.assertIn("/pedidos", paths)
        self.assertEqual(len(self.rows("fbits_customers")), 10)

    async def test_the_existing_rate_limiter_is_the_only_budget(self):
        orders = [order(order_id=index, customer_id=500 + index) for index in range(1, 21)]
        await self.run_sync(orders)
        pedidos_requests = len([r for r in self.requests if r.url.path == "/pedidos"])
        # 20 clientes, zero requisições adicionais: o custo é o das páginas de
        # pedidos que o sync já pagava.
        self.assertEqual(len(self.rows("fbits_customers")), 20)
        self.assertLessEqual(pedidos_requests, len(self.requests))
        self.assertEqual(
            len([r for r in self.requests if r.url.path not in {"/pedidos", "/situacoesPedido"}]),
            0,
        )

    async def test_the_order_rows_persisted_carry_no_contact_data(self):
        await self.run_sync([order(order_id=1, customer_id=555)])
        serialized = json.dumps(self.rows("fbits_orders"), ensure_ascii=False)
        for secret in (NAME, EMAIL, PHONE, CPF, ADDRESS):
            self.assertNotIn(secret, serialized)

    async def test_an_incremental_run_updates_the_existing_identity(self):
        await self.run_sync([order(order_id=1, customer_id=555)])
        self.connection["metadata"]["history_cursor"] = "2026-10-01T00:00:00+00:00"
        self.upserts.clear()
        await self.run_sync([
            order(order_id=2, customer_id=555, name="Nome Novo", email="novo@exemplo.com"),
        ])
        identities = self.rows("fbits_customers")
        self.assertEqual(len(identities), 1)
        self.assertEqual(identities[0]["name"], "Nome Novo")
        self.assertEqual(identities[0]["email"], "novo@exemplo.com")

    async def test_the_upsert_key_is_tenant_scoped(self):
        await self.run_sync([order(order_id=1, customer_id=555)])
        conflicts = [
            call for call in self.upserts.get("fbits_customers", [])
        ]
        self.assertTrue(conflicts)
        for row in self.rows("fbits_customers"):
            self.assertEqual(row["client_id"], CURAVINO)

    async def test_a_missing_table_does_not_break_the_order_sync(self):
        # Migration 040 pendente: pedidos continuam entrando.
        self.fail_customers = True
        payload, logged = await self.run_sync([order(order_id=1, customer_id=555)])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["customers_upserted"], 0)
        self.assertEqual(len(self.rows("fbits_orders")), 1)
        self.assertIn("status=unavailable", logged)
        self.assertIn("20261004_000040_fbits_customer_identity", logged)

    async def test_an_order_without_identity_persists_only_the_order(self):
        await self.run_sync([order(order_id=1, customer_id=None)])
        self.assertEqual(len(self.rows("fbits_orders")), 1)
        self.assertEqual(self.rows("fbits_customers"), [])


class SyncPrivacyInLogsTests(SyncPersistenceHarness):
    async def test_no_pii_reaches_the_sync_log(self):
        _, logged = await self.run_sync([order(order_id=1, customer_id=555)])
        for secret in (NAME, EMAIL, PHONE, CPF, ADDRESS):
            self.assertNotIn(secret, logged)

    async def test_the_sync_log_reports_only_the_customer_count(self):
        _, logged = await self.run_sync([
            order(order_id=1, customer_id=555), order(order_id=2, customer_id=777),
        ])
        line = next(item for item in logged.splitlines() if "status=ok" in item)
        self.assertIn("customers=2", line)

    async def test_no_pii_reaches_the_log_when_the_table_is_missing(self):
        self.fail_customers = True
        _, logged = await self.run_sync([order(order_id=1, customer_id=555)])
        for secret in (NAME, EMAIL, PHONE, CPF):
            self.assertNotIn(secret, logged)


class EnrichedCustomer360Tests(unittest.IsolatedAsyncioTestCase):
    """fbits_orders + fbits_customers → CustomerSummary completo."""

    def setUp(self) -> None:
        self.identities: List[Dict[str, Any]] = [
            {
                "client_id": CURAVINO, "fbits_customer_id": "555",
                "name": NAME, "email": EMAIL, "phone": PHONE,
                "updated_at_provider": "2026-09-30T08:00:00Z",
                "synced_at": "2026-10-04T08:00:00Z",
            },
        ]
        self.orders: List[Dict[str, Any]] = [
            {
                "client_id": CURAVINO, "order_id": "1", "order_code": "PED-1",
                "customer_id": "555", "customer_name": None, "customer_email": None,
                "status_id": "1", "status_name": "Pago",
                "order_date": "2026-09-01T10:00:00Z", "total_value": 300.0,
                "is_valid": True, "raw": {},
            },
            {
                "client_id": CURAVINO, "order_id": "2", "order_code": "PED-2",
                "customer_id": "555", "customer_name": None, "customer_email": None,
                "status_id": "1", "status_name": "Pago",
                "order_date": "2026-10-02T10:00:00Z", "total_value": 200.0,
                "is_valid": True, "raw": {},
            },
        ]

    async def listing(self, *, client_id: str = CURAVINO) -> Dict[str, Any]:
        async def select(table: str, **_kwargs: Any) -> List[Dict[str, Any]]:
            if table == "fbits_orders":
                return list(self.orders)
            if table == "fbits_customers":
                return list(self.identities)
            return []

        with (
            patch.object(customers, "sb_select", AsyncMock(side_effect=select)),
            patch.object(
                customers, "resolve_commerce_provider",
                AsyncMock(return_value={"provider": "fbits"}),
            ),
            patch(
                "services.fbits_reporting._tenant_revenue_context",
                AsyncMock(return_value=(True, {"1"}, {})),
            ),
            redirect_stdout(io.StringIO()),
        ):
            return await customers.list_customers(client_id=client_id)

    async def test_the_summary_is_enriched_with_name_email_and_phone(self):
        payload = await self.listing()
        customer = payload["customers"][0]
        self.assertEqual(customer["external_id"], "555")
        self.assertEqual(customer["name"], NAME)
        self.assertEqual(customer["email"], EMAIL)
        self.assertEqual(customer["phone"], PHONE)
        self.assertTrue(payload["contact_details_available"])

    async def test_the_purchase_behaviour_is_unchanged(self):
        customer = (await self.listing())["customers"][0]
        self.assertEqual(customer["orders_count"], 2)
        self.assertEqual(customer["total_revenue"], 500.0)
        self.assertEqual(customer["average_ticket"], 250.0)
        self.assertEqual(customer["status"], "recurring")
        self.assertEqual(customer["first_order_at"], "2026-09-01T10:00:00+00:00")
        self.assertEqual(customer["last_order_at"], "2026-10-02T10:00:00+00:00")

    async def test_a_customer_without_email_is_still_listed(self):
        self.identities[0]["email"] = None
        customer = (await self.listing())["customers"][0]
        self.assertEqual(customer["name"], NAME)
        self.assertIsNone(customer["email"])
        self.assertEqual(customer["phone"], PHONE)

    async def test_a_customer_without_phone_is_still_listed(self):
        self.identities[0]["phone"] = None
        customer = (await self.listing())["customers"][0]
        self.assertIsNone(customer["phone"])

    async def test_an_identity_removed_from_the_table_degrades_to_behaviour_only(self):
        # Direito de eliminação exercido: a identidade sai, o histórico fica.
        self.identities.clear()
        payload = await self.listing()
        customer = payload["customers"][0]
        self.assertIsNone(customer["name"])
        self.assertIsNone(customer["email"])
        self.assertIsNone(customer["phone"])
        self.assertEqual(customer["orders_count"], 2)
        self.assertFalse(payload["contact_details_available"])

    async def test_an_identity_without_a_matching_order_is_not_invented(self):
        self.identities.append({
            "client_id": CURAVINO, "fbits_customer_id": "999",
            "name": "Nunca Comprou", "email": "nunca@exemplo.com", "phone": None,
            "synced_at": "2026-10-04T08:00:00Z",
        })
        payload = await self.listing()
        self.assertEqual(payload["totals"]["customers"], 1)
        self.assertNotIn("Nunca Comprou", json.dumps(payload["customers"], ensure_ascii=False))

    async def test_an_unknown_customer_id_keeps_the_contact_empty(self):
        self.orders[0]["customer_id"] = "inexistente"
        self.orders[1]["customer_id"] = "inexistente"
        customer = (await self.listing())["customers"][0]
        self.assertEqual(customer["external_id"], "inexistente")
        self.assertIsNone(customer["name"])
        self.assertEqual(customer["orders_count"], 2)

    async def test_a_missing_table_degrades_without_breaking_the_page(self):
        async def select(table: str, **_kwargs: Any) -> List[Dict[str, Any]]:
            if table == "fbits_orders":
                return list(self.orders)
            raise RuntimeError('relation "fbits_customers" does not exist')

        output = io.StringIO()
        with (
            redirect_stdout(output),
            patch.object(customers, "sb_select", AsyncMock(side_effect=select)),
            patch.object(
                customers, "resolve_commerce_provider",
                AsyncMock(return_value={"provider": "fbits"}),
            ),
            patch(
                "services.fbits_reporting._tenant_revenue_context",
                AsyncMock(return_value=(True, {"1"}, {})),
            ),
        ):
            payload = await customers.list_customers(client_id=CURAVINO)
        self.assertEqual(payload["totals"]["customers"], 1)
        self.assertIsNone(payload["customers"][0]["name"])
        logged = output.getvalue()
        self.assertIn("status=identity_unavailable", logged)
        for secret in (NAME, EMAIL, PHONE):
            self.assertNotIn(secret, logged)

    async def test_the_detail_is_enriched_too(self):
        async def select(table: str, **_kwargs: Any) -> List[Dict[str, Any]]:
            if table == "fbits_orders":
                return list(self.orders)
            if table == "fbits_customers":
                return list(self.identities)
            return []

        key = customers.customer_key(CURAVINO, "external_id", "555")
        with (
            patch.object(customers, "sb_select", AsyncMock(side_effect=select)),
            patch.object(
                customers, "resolve_commerce_provider",
                AsyncMock(return_value={"provider": "fbits"}),
            ),
            patch(
                "services.fbits_reporting._tenant_revenue_context",
                AsyncMock(return_value=(True, {"1"}, {})),
            ),
        ):
            payload = await customers.get_customer(client_id=CURAVINO, customer_id=key)
        self.assertEqual(payload["customer"]["name"], NAME)
        self.assertEqual(len(payload["orders"]), 2)

    async def test_the_listing_still_makes_one_query_per_table(self):
        select = AsyncMock(side_effect=lambda table, **_k: (
            list(self.orders) if table == "fbits_orders"
            else list(self.identities) if table == "fbits_customers" else []
        ))
        with (
            patch.object(customers, "sb_select", select),
            patch.object(
                customers, "resolve_commerce_provider",
                AsyncMock(return_value={"provider": "fbits"}),
            ),
            patch(
                "services.fbits_reporting._tenant_revenue_context",
                AsyncMock(return_value=(True, {"1"}, {})),
            ),
        ):
            await customers.list_customers(client_id=CURAVINO)
        # pedidos + identidades: duas leituras, nenhuma por cliente.
        self.assertEqual(select.await_count, 2)


class IdentityTenantIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_identity_from_another_tenant_is_discarded(self):
        orders = [{
            "client_id": CURAVINO, "order_id": "1", "order_code": "PED-1",
            "customer_id": "555", "status_id": "1", "status_name": "Pago",
            "order_date": "2026-10-01T10:00:00Z", "total_value": 100.0,
            "is_valid": True, "raw": {},
        }]
        # A mesma chave externa existe no outro tenant com PII diferente.
        identities = [{
            "client_id": ROOVE, "fbits_customer_id": "555",
            "name": "Cliente Da Roove", "email": "roove@exemplo.com", "phone": "11777776666",
            "synced_at": "2026-10-04T08:00:00Z",
        }]

        async def select(table: str, **_kwargs: Any) -> List[Dict[str, Any]]:
            if table == "fbits_orders":
                return list(orders)
            if table == "fbits_customers":
                return list(identities)
            return []

        with (
            patch.object(customers, "sb_select", AsyncMock(side_effect=select)),
            patch.object(
                customers, "resolve_commerce_provider",
                AsyncMock(return_value={"provider": "fbits"}),
            ),
            patch(
                "services.fbits_reporting._tenant_revenue_context",
                AsyncMock(return_value=(True, {"1"}, {})),
            ),
        ):
            payload = await customers.list_customers(client_id=CURAVINO)
        customer = payload["customers"][0]
        self.assertIsNone(customer["name"])
        self.assertIsNone(customer["email"])
        self.assertNotIn(
            "Cliente Da Roove", json.dumps(payload, ensure_ascii=False),
        )

    async def test_the_identity_query_is_filtered_by_the_resolved_tenant(self):
        select = AsyncMock(return_value=[])
        with (
            patch.object(customers, "sb_select", select),
            patch.object(
                customers, "resolve_commerce_provider",
                AsyncMock(return_value={"provider": "fbits"}),
            ),
            patch(
                "services.fbits_reporting._tenant_revenue_context",
                AsyncMock(return_value=(True, {"1"}, {})),
            ),
        ):
            await customers.list_customers(client_id=CURAVINO)
        identity_call = next(
            call for call in select.await_args_list if call.args[0] == "fbits_customers"
        )
        self.assertEqual(identity_call.kwargs["filters"]["client_id"], f"eq.{CURAVINO}")

    async def test_a_cross_tenant_customer_lookup_is_not_found(self):
        orders = [{
            "client_id": CURAVINO, "order_id": "1", "customer_id": "555",
            "status_id": "1", "status_name": "Pago", "order_date": "2026-10-01T10:00:00Z",
            "total_value": 100.0, "is_valid": True, "raw": {},
        }]
        roove_key = customers.customer_key(ROOVE, "external_id", "555")
        with (
            patch.object(
                customers, "sb_select",
                AsyncMock(side_effect=lambda table, **_k: list(orders) if table == "fbits_orders" else []),
            ),
            patch.object(
                customers, "resolve_commerce_provider",
                AsyncMock(return_value={"provider": "fbits"}),
            ),
            patch(
                "services.fbits_reporting._tenant_revenue_context",
                AsyncMock(return_value=(True, {"1"}, {})),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "CUSTOMER_NOT_FOUND"):
                await customers.get_customer(client_id=CURAVINO, customer_id=roove_key)


class ShopifyDoesNotRegressTests(unittest.IsolatedAsyncioTestCase):
    async def test_shopify_never_reads_the_fbits_identity_table(self):
        tables: List[str] = []

        async def select(table: str, **_kwargs: Any) -> List[Dict[str, Any]]:
            tables.append(table)
            if table == "shopify_orders":
                return [{
                    "client_id": ROOVE, "shopify_order_id": "1001", "order_number": "1001",
                    "name": "#1001", "email": "ana@exemplo-roove.com", "customer_id": "s-1",
                    "financial_status": "paid", "total_price": 400.0, "cancelled_at": None,
                    "created_at_shopify": "2026-10-01T10:00:00Z",
                }]
            if table == "shopify_customers":
                return [{
                    "client_id": ROOVE, "shopify_customer_id": "s-1",
                    "email": "ana@exemplo-roove.com", "first_name": "Ana", "last_name": "Recorrente",
                    "phone": "5511988887777", "orders_count": 1, "total_spent": 400.0,
                    "updated_at_shopify": "2026-10-04T10:00:00Z",
                }]
            return []

        with (
            patch.object(customers, "sb_select", AsyncMock(side_effect=select)),
            patch.object(
                customers, "resolve_commerce_provider",
                AsyncMock(return_value={"provider": "shopify"}),
            ),
        ):
            payload = await customers.list_customers(client_id=ROOVE)
        self.assertNotIn("fbits_customers", tables)
        self.assertNotIn("fbits_orders", tables)
        customer = payload["customers"][0]
        self.assertEqual(customer["name"], "Ana Recorrente")
        self.assertEqual(customer["provider"], "shopify")


class DeletionAndRetentionTests(unittest.TestCase):
    """O direito de eliminação precisa estar amarrado no schema, não no texto."""

    def sql(self) -> str:
        return IDENTITY_MIGRATION.read_text(encoding="utf-8")

    def test_the_identity_migration_exists_and_is_not_applied_by_us(self):
        self.assertTrue(IDENTITY_MIGRATION.exists())
        self.assertIn("NÃO APLICADA", self.sql())

    def test_the_table_stores_only_the_declared_fields(self):
        sql = self.sql()
        head = sql[sql.index("create table if not exists public.fbits_customers"):]
        head = head[: head.index(");")]
        for column in ("fbits_customer_id", "name", "email", "phone", "synced_at"):
            self.assertIn(column, head)
        for forbidden in ("cpf", "endereco", "address", "token", "raw_payload", "document"):
            self.assertNotIn(forbidden, head.lower())

    def test_every_index_starts_with_the_tenant(self):
        for line in self.sql().splitlines():
            if "on public.fbits_customers (" in line:
                self.assertIn("(client_id", line.replace(" ", "").replace("(client_id", "(client_id"))

    def test_customer_data_deletion_is_covered(self):
        sql = self.sql()
        # Apagar a empresa apaga a identidade, por qualquer caminho.
        self.assertIn("after delete on public.clients", sql)
        self.assertIn("delete from public.fbits_customers where client_id = old.id", sql)
        # E existe exclusão pontual a pedido do titular.
        self.assertIn("forget_fbits_customer", sql)

    def test_the_purpose_is_declared_on_the_table(self):
        self.assertIn("comment on table public.fbits_customers", self.sql())

    def test_the_index_migration_is_separate(self):
        indexes = MIGRATIONS / "20261005_000041_customer_360_indexes.sql"
        self.assertTrue(indexes.exists())
        self.assertNotIn("create table", indexes.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
