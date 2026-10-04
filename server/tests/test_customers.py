"""Customer 360: agregação FBITS/Shopify, contrato único e isolamento.

Dois tenants fictícios, nunca reais: `curavino-test` (FBITS) e `roove-test`
(Shopify). Nenhum teste chama provider externo — tudo sai do que os syncs já
persistem.
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from routes import customers as routes
from services import customers

FBITS_CLIENT = "curavino-test"
SHOPIFY_CLIENT = "roove-test"

# PII fictícia, usada também para provar que não vaza em log.
ANA_EMAIL = "ana.recorrente@exemplo-roove.com"
ANA_PHONE = "+55 11 98888-7777"
BRUNO_EMAIL = "bruno.unico@exemplo-roove.com"


def fbits_order(
    *,
    order_id: str,
    customer_id: str | None,
    status_id: str = "6",
    total: float = 100.0,
    order_date: str = "2026-10-01T10:00:00Z",
    is_valid: bool | None = True,
    name: str | None = None,
    email: str | None = None,
    client_id: str = FBITS_CLIENT,
) -> Dict[str, Any]:
    return {
        "client_id": client_id,
        "order_id": order_id,
        "order_code": f"PED-{order_id}",
        "customer_id": customer_id,
        "customer_name": name,
        "customer_email": email,
        "status_id": status_id,
        "status_name": "Pago" if status_id == "6" else "Cancelado",
        "order_date": order_date,
        "total_value": total,
        "is_valid": is_valid,
        "raw": {},
    }


def shopify_order(
    *,
    order_id: str,
    customer_id: str | None,
    email: str | None = None,
    total: float = 100.0,
    financial_status: str = "paid",
    cancelled_at: str | None = None,
    created_at: str = "2026-10-01T10:00:00Z",
    client_id: str = SHOPIFY_CLIENT,
) -> Dict[str, Any]:
    return {
        "client_id": client_id,
        "shopify_order_id": order_id,
        "order_number": order_id,
        "name": f"#{order_id}",
        "email": email,
        "customer_id": customer_id,
        "financial_status": financial_status,
        "total_price": total,
        "cancelled_at": cancelled_at,
        "created_at_shopify": created_at,
    }


def shopify_customer(
    *,
    customer_id: str,
    email: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    phone: str | None = None,
    client_id: str = SHOPIFY_CLIENT,
) -> Dict[str, Any]:
    return {
        "client_id": client_id,
        "shopify_customer_id": customer_id,
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "phone": phone,
        "orders_count": 0,
        "total_spent": 0,
        "updated_at_shopify": "2026-10-04T10:00:00Z",
    }


class ProviderHarness(unittest.IsolatedAsyncioTestCase):
    """Substitui apenas as leituras de banco; a agregação é a real."""

    def tables(self) -> Dict[str, List[Dict[str, Any]]]:
        return {}

    def provider(self) -> str | None:
        return None

    def setUp(self) -> None:
        tables = self.tables()

        async def sb_select(table: str, **kwargs: Any) -> List[Dict[str, Any]]:
            return list(tables.get(table, []))

        self.select = AsyncMock(side_effect=sb_select)
        self.patches = [
            patch.object(customers, "sb_select", self.select),
            patch.object(
                customers, "resolve_commerce_provider",
                AsyncMock(return_value={"provider": self.provider()}),
            ),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])

    async def listing(self, **kwargs: Any) -> Dict[str, Any]:
        return await customers.list_customers(client_id=self.client_id, **kwargs)

    client_id = FBITS_CLIENT


class FbitsAggregationTests(ProviderHarness):
    client_id = FBITS_CLIENT

    def provider(self) -> str:
        return "fbits"

    def tables(self) -> Dict[str, List[Dict[str, Any]]]:
        return {
            "fbits_orders": [
                # Recorrente: três pedidos, um cancelado.
                fbits_order(order_id="1", customer_id="c-100", total=300.0, order_date="2026-09-01T10:00:00Z"),
                fbits_order(order_id="2", customer_id="c-100", total=200.0, order_date="2026-10-02T10:00:00Z"),
                fbits_order(order_id="3", customer_id="c-100", total=999.0, status_id="9", order_date="2026-10-03T10:00:00Z"),
                # Único pedido.
                fbits_order(order_id="4", customer_id="c-200", total=50.0, order_date="2026-09-20T10:00:00Z"),
                # Pedido sem identidade nenhuma: não é atribuído.
                fbits_order(order_id="5", customer_id=None, total=77.0),
            ],
        }

    def setUp(self) -> None:
        super().setUp()
        self.revenue = patch(
            "services.fbits_reporting._tenant_revenue_context",
            AsyncMock(return_value=(True, {"6"}, {})),
        )
        self.revenue.start()
        self.addCleanup(self.revenue.stop)

    async def test_the_provider_is_resolved_from_the_connection(self):
        payload = await self.listing()
        self.assertEqual(payload["provider"], "fbits")
        self.assertEqual(payload["provider_label"], "FBITS")
        self.assertTrue(payload["connected"])

    async def test_a_recurring_customer_is_aggregated_by_external_id(self):
        payload = await self.listing()
        recurring = next(item for item in payload["customers"] if item["external_id"] == "c-100")
        self.assertEqual(recurring["orders_count"], 2)
        self.assertEqual(recurring["total_revenue"], 500.0)
        self.assertEqual(recurring["average_ticket"], 250.0)
        self.assertEqual(recurring["status"], "recurring")
        self.assertEqual(recurring["first_order_at"], "2026-09-01T10:00:00+00:00")
        self.assertEqual(recurring["last_order_at"], "2026-10-02T10:00:00+00:00")

    async def test_a_cancelled_order_is_excluded_from_revenue_and_count(self):
        payload = await self.listing()
        recurring = next(item for item in payload["customers"] if item["external_id"] == "c-100")
        # O pedido de 999 em situação 9 não entra: não está na lista de receita.
        self.assertNotIn(999.0, [recurring["total_revenue"]])
        self.assertEqual(recurring["orders_count"], 2)

    async def test_an_order_marked_invalid_is_excluded(self):
        self.select.side_effect = AsyncMock(
            return_value=[
                fbits_order(order_id="1", customer_id="c-900", total=100.0),
                fbits_order(order_id="2", customer_id="c-900", total=400.0, is_valid=False),
            ],
        )
        payload = await self.listing()
        customer = next(item for item in payload["customers"] if item["external_id"] == "c-900")
        self.assertEqual(customer["orders_count"], 1)
        self.assertEqual(customer["total_revenue"], 100.0)

    async def test_a_single_order_customer_is_marked_as_such(self):
        payload = await self.listing()
        single = next(item for item in payload["customers"] if item["external_id"] == "c-200")
        self.assertEqual(single["orders_count"], 1)
        self.assertEqual(single["status"], "single")
        self.assertEqual(single["average_ticket"], 50.0)

    async def test_an_order_without_any_identity_is_not_attributed(self):
        payload = await self.listing()
        self.assertEqual(payload["totals"]["customers"], 2)
        self.assertEqual(payload["orders_unattributed"], 1)

    async def test_contact_details_are_absent_because_the_sync_does_not_store_them(self):
        payload = await self.listing()
        for item in payload["customers"]:
            self.assertIsNone(item["name"])
            self.assertIsNone(item["email"])
            self.assertIsNone(item["phone"])
        self.assertFalse(payload["contact_details_available"])

    async def test_legacy_rows_with_contact_are_used_when_present(self):
        self.select.side_effect = AsyncMock(
            return_value=[
                fbits_order(order_id="1", customer_id="c-700", name="Legado Silva", email="legado@exemplo.com"),
            ],
        )
        payload = await self.listing()
        customer = payload["customers"][0]
        self.assertEqual(customer["name"], "Legado Silva")
        self.assertEqual(customer["email"], "legado@exemplo.com")
        self.assertTrue(payload["contact_details_available"])

    async def test_the_base_totals_are_computed_over_every_customer(self):
        totals = (await self.listing())["totals"]
        self.assertEqual(totals["customers"], 2)
        self.assertEqual(totals["recurring_customers"], 1)
        self.assertEqual(totals["total_orders"], 3)
        self.assertEqual(totals["total_revenue"], 550.0)
        self.assertEqual(totals["average_ticket"], round(550.0 / 3, 2))


class IdentityRuleTests(unittest.TestCase):
    def test_the_external_id_has_priority(self):
        self.assertEqual(
            customers._identity(external_id="c-1", email="a@b.com", phone="11988887777"),
            ("external_id", "c-1"),
        )

    def test_the_email_is_the_second_choice_and_is_normalized(self):
        self.assertEqual(
            customers._identity(email="  Ana@Exemplo.COM  "), ("email", "ana@exemplo.com"),
        )

    def test_the_phone_is_the_third_choice_and_keeps_only_digits(self):
        self.assertEqual(
            customers._identity(phone="+55 (11) 98888-7777"), ("phone", "5511988887777"),
        )

    def test_a_short_phone_does_not_identify_anyone(self):
        self.assertEqual(customers._identity(phone="1234"), ("", ""))

    def test_a_malformed_email_does_not_identify_anyone(self):
        self.assertEqual(customers._identity(email="sem-arroba"), ("", ""))

    def test_people_are_never_merged_by_name(self):
        # Dois homônimos sem id e sem contato permanecem não atribuídos: o nome
        # jamais entra na identidade.
        self.assertEqual(customers._identity(), ("", ""))

    def test_the_public_key_is_scoped_to_the_tenant(self):
        same_person = ("email", "ana@exemplo.com")
        self.assertNotEqual(
            customers.customer_key(FBITS_CLIENT, *same_person),
            customers.customer_key(SHOPIFY_CLIENT, *same_person),
        )

    def test_the_public_key_is_stable_and_opaque(self):
        key = customers.customer_key(SHOPIFY_CLIENT, "email", ANA_EMAIL)
        self.assertEqual(key, customers.customer_key(SHOPIFY_CLIENT, "email", ANA_EMAIL))
        self.assertNotIn("@", key)
        self.assertNotIn("ana", key)


class ShopifyNormalizationTests(ProviderHarness):
    client_id = SHOPIFY_CLIENT

    def provider(self) -> str:
        return "shopify"

    def tables(self) -> Dict[str, List[Dict[str, Any]]]:
        return {
            "shopify_orders": [
                shopify_order(order_id="1001", customer_id="s-1", email=ANA_EMAIL, total=400.0, created_at="2026-09-02T10:00:00Z"),
                shopify_order(order_id="1002", customer_id="s-1", email=ANA_EMAIL, total=600.0, created_at="2026-10-01T10:00:00Z"),
                shopify_order(order_id="1003", customer_id="s-1", email=ANA_EMAIL, total=900.0, cancelled_at="2026-10-02T10:00:00Z", created_at="2026-10-02T10:00:00Z"),
                shopify_order(order_id="1004", customer_id="s-2", email=BRUNO_EMAIL, total=120.0, created_at="2026-08-15T10:00:00Z"),
                # Sem customer_id, mas com e-mail: identidade por e-mail.
                shopify_order(order_id="1005", customer_id=None, email="carla@exemplo-roove.com", total=80.0),
                # Sem identidade alguma.
                shopify_order(order_id="1006", customer_id=None, email=None, total=60.0),
            ],
            "shopify_customers": [
                shopify_customer(customer_id="s-1", email=ANA_EMAIL, first_name="Ana", last_name="Recorrente", phone=ANA_PHONE),
                shopify_customer(customer_id="s-2", email=BRUNO_EMAIL, first_name="Bruno", last_name="Único"),
            ],
        }

    async def test_the_contract_is_identical_to_the_fbits_one(self):
        payload = await self.listing()
        self.assertEqual(payload["provider"], "shopify")
        self.assertEqual(payload["provider_label"], "Shopify")
        expected = {
            "id", "external_id", "client_id", "provider", "provider_label", "identity_kind",
            "name", "email", "phone", "orders_count", "total_revenue", "average_ticket",
            "first_order_at", "last_order_at", "status",
        }
        for item in payload["customers"]:
            self.assertEqual(set(item), expected)

    async def test_a_recurring_customer_carries_name_email_and_phone(self):
        payload = await self.listing()
        ana = next(item for item in payload["customers"] if item["external_id"] == "s-1")
        self.assertEqual(ana["name"], "Ana Recorrente")
        self.assertEqual(ana["email"], ANA_EMAIL)
        self.assertEqual(ana["phone"], "5511988887777")
        self.assertEqual(ana["orders_count"], 2)
        self.assertEqual(ana["total_revenue"], 1000.0)
        self.assertEqual(ana["average_ticket"], 500.0)
        self.assertEqual(ana["status"], "recurring")

    async def test_a_cancelled_order_is_excluded_from_revenue(self):
        payload = await self.listing()
        ana = next(item for item in payload["customers"] if item["external_id"] == "s-1")
        self.assertEqual(ana["orders_count"], 2)
        self.assertNotEqual(ana["total_revenue"], 1900.0)

    async def test_a_customer_without_phone_is_not_invented(self):
        payload = await self.listing()
        bruno = next(item for item in payload["customers"] if item["external_id"] == "s-2")
        self.assertEqual(bruno["name"], "Bruno Único")
        self.assertIsNone(bruno["phone"])
        self.assertEqual(bruno["status"], "single")

    async def test_an_order_without_customer_id_falls_back_to_email(self):
        payload = await self.listing()
        carla = next(item for item in payload["customers"] if item["identity_kind"] == "email")
        self.assertIsNone(carla["external_id"])
        self.assertEqual(carla["email"], "carla@exemplo-roove.com")
        self.assertIsNone(carla["name"])

    async def test_an_order_without_any_identity_is_not_attributed(self):
        payload = await self.listing()
        self.assertEqual(payload["totals"]["customers"], 3)
        self.assertEqual(payload["orders_unattributed"], 1)

    async def test_contact_details_are_available_for_shopify(self):
        self.assertTrue((await self.listing())["contact_details_available"])


class SearchAndPaginationTests(ProviderHarness):
    client_id = SHOPIFY_CLIENT

    def provider(self) -> str:
        return "shopify"

    def tables(self) -> Dict[str, List[Dict[str, Any]]]:
        return {
            "shopify_orders": [
                shopify_order(order_id=str(1000 + index), customer_id=f"s-{index}",
                              email=f"cliente{index}@exemplo-roove.com", total=float(index * 10))
                for index in range(1, 61)
            ],
            "shopify_customers": [
                shopify_customer(customer_id=f"s-{index}", email=f"cliente{index}@exemplo-roove.com",
                                 first_name=f"Cliente{index}", phone=f"1198888{index:04d}")
                for index in range(1, 61)
            ],
        }

    async def test_the_default_page_is_bounded(self):
        payload = await self.listing()
        self.assertEqual(payload["total"], 60)
        self.assertEqual(len(payload["customers"]), customers.PAGE_SIZE_DEFAULT)
        self.assertEqual(payload["page"], 1)

    async def test_a_second_page_returns_different_customers(self):
        first = await self.listing(page=1, page_size=10)
        second = await self.listing(page=2, page_size=10)
        self.assertEqual(len(second["customers"]), 10)
        self.assertFalse(
            {item["id"] for item in first["customers"]}
            & {item["id"] for item in second["customers"]},
        )

    async def test_the_page_size_is_capped(self):
        payload = await self.listing(page_size=10_000)
        self.assertEqual(payload["page_size"], customers.PAGE_SIZE_MAX)

    async def test_the_highest_revenue_comes_first(self):
        payload = await self.listing()
        revenues = [item["total_revenue"] for item in payload["customers"]]
        self.assertEqual(revenues, sorted(revenues, reverse=True))

    async def test_search_by_name(self):
        payload = await self.listing(search="Cliente42")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["customers"][0]["name"], "Cliente42")

    async def test_search_by_email(self):
        payload = await self.listing(search="cliente7@exemplo-roove.com")
        self.assertEqual(payload["total"], 1)

    async def test_search_by_phone_ignores_formatting(self):
        payload = await self.listing(search="(11) 98888-0042")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["customers"][0]["name"], "Cliente42")

    async def test_search_does_not_change_the_base_totals(self):
        payload = await self.listing(search="Cliente42")
        self.assertEqual(payload["totals"]["customers"], 60)
        self.assertEqual(payload["total"], 1)

    async def test_a_search_without_match_is_empty_and_honest(self):
        payload = await self.listing(search="ninguem-com-esse-nome")
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["customers"], [])


class CustomerDetailTests(ProviderHarness):
    client_id = SHOPIFY_CLIENT

    def provider(self) -> str:
        return "shopify"

    def tables(self) -> Dict[str, List[Dict[str, Any]]]:
        return {
            "shopify_orders": [
                shopify_order(order_id="1001", customer_id="s-1", email=ANA_EMAIL, total=400.0, created_at="2026-09-02T10:00:00Z"),
                shopify_order(order_id="1002", customer_id="s-1", email=ANA_EMAIL, total=600.0, created_at="2026-10-01T10:00:00Z"),
                shopify_order(order_id="1003", customer_id="s-1", email=ANA_EMAIL, total=900.0, cancelled_at="2026-10-02T10:00:00Z", created_at="2026-10-02T10:00:00Z"),
            ],
            "shopify_customers": [
                shopify_customer(customer_id="s-1", email=ANA_EMAIL, first_name="Ana", last_name="Recorrente", phone=ANA_PHONE),
            ],
        }

    def key(self) -> str:
        return customers.customer_key(SHOPIFY_CLIENT, "external_id", "s-1")

    async def test_the_detail_carries_the_same_summary(self):
        payload = await customers.get_customer(client_id=SHOPIFY_CLIENT, customer_id=self.key())
        self.assertEqual(payload["customer"]["name"], "Ana Recorrente")
        self.assertEqual(payload["customer"]["orders_count"], 2)
        self.assertEqual(payload["customer"]["total_revenue"], 1000.0)

    async def test_the_history_shows_every_order_including_the_cancelled_one(self):
        payload = await customers.get_customer(client_id=SHOPIFY_CLIENT, customer_id=self.key())
        self.assertEqual(len(payload["orders"]), 3)
        cancelled = next(item for item in payload["orders"] if item["order_id"] == "1003")
        self.assertEqual(cancelled["status"], "Cancelado")
        self.assertFalse(cancelled["counts_as_revenue"])

    async def test_the_history_is_newest_first(self):
        payload = await customers.get_customer(client_id=SHOPIFY_CLIENT, customer_id=self.key())
        dates = [item["happened_at"] for item in payload["orders"]]
        self.assertEqual(dates, sorted(dates, reverse=True))

    async def test_each_history_entry_has_date_reference_value_and_status(self):
        payload = await customers.get_customer(client_id=SHOPIFY_CLIENT, customer_id=self.key())
        for order in payload["orders"]:
            self.assertTrue(order["happened_at"])
            self.assertTrue(order["reference"])
            self.assertIsInstance(order["value"], float)
            self.assertIsNotNone(order["status"])

    async def test_an_unknown_key_is_not_found(self):
        with self.assertRaisesRegex(RuntimeError, "CUSTOMER_NOT_FOUND"):
            await customers.get_customer(client_id=SHOPIFY_CLIENT, customer_id="chave-inexistente")


class NoEcommerceTests(ProviderHarness):
    client_id = "sem-ecommerce"

    def provider(self) -> None:
        return None

    async def test_the_empty_state_is_explicit(self):
        payload = await self.listing()
        self.assertIsNone(payload["provider"])
        self.assertFalse(payload["connected"])
        self.assertEqual(payload["customers"], [])
        self.assertEqual(payload["totals"]["customers"], 0)

    async def test_no_provider_is_queried(self):
        await self.listing()
        self.select.assert_not_awaited()


class TenantIsolationTests(unittest.IsolatedAsyncioTestCase):
    """O client_id do browser nunca fura membership."""

    async def test_the_listing_never_trusts_the_browser_client_id(self):
        denied = HTTPException(status_code=403, detail="sem acesso")
        with (
            patch.object(routes, "require_client_read", AsyncMock(side_effect=denied)),
            patch.object(routes, "list_customers", AsyncMock()) as listing,
        ):
            with self.assertRaises(HTTPException) as raised:
                await routes.customers_list(
                    search="", page=1, page_size=25,
                    client_id=SHOPIFY_CLIENT, x_client_id=None,
                    authorization="Bearer viewer-curavino",
                )
        self.assertEqual(raised.exception.status_code, 403)
        listing.assert_not_awaited()

    async def test_the_detail_never_trusts_the_browser_client_id(self):
        denied = HTTPException(status_code=403, detail="sem acesso")
        with (
            patch.object(routes, "require_client_read", AsyncMock(side_effect=denied)),
            patch.object(routes, "get_customer", AsyncMock()) as detail,
        ):
            with self.assertRaises(HTTPException):
                await routes.customers_detail(
                    customer_id="qualquer", client_id=FBITS_CLIENT, x_client_id=None,
                    authorization="Bearer viewer-roove",
                )
        detail.assert_not_awaited()

    async def test_only_the_resolved_tenant_reaches_the_service(self):
        with (
            patch.object(routes, "require_client_read", AsyncMock(return_value=FBITS_CLIENT)),
            patch.object(
                routes, "list_customers",
                AsyncMock(return_value={"provider": "fbits", "total": 0}),
            ) as listing,
            redirect_stdout(io.StringIO()),
        ):
            await routes.customers_list(
                search="", page=1, page_size=25,
                # O browser pediu outro tenant: o resolvido é que vale.
                client_id=SHOPIFY_CLIENT, x_client_id=SHOPIFY_CLIENT,
                authorization="Bearer nasser",
            )
        self.assertEqual(listing.await_args.kwargs["client_id"], FBITS_CLIENT)

    async def test_a_viewer_from_another_tenant_gets_a_safe_status(self):
        for status in (403, 404):
            with self.subTest(status=status):
                with (
                    patch.object(
                        routes, "require_client_read",
                        AsyncMock(side_effect=HTTPException(status_code=status, detail="negado")),
                    ),
                    redirect_stdout(io.StringIO()),
                ):
                    with self.assertRaises(HTTPException) as raised:
                        await routes.customers_detail(
                            customer_id="x", client_id=SHOPIFY_CLIENT,
                            x_client_id=None, authorization="Bearer viewer-curavino",
                        )
                self.assertEqual(raised.exception.status_code, status)

    async def test_a_key_from_another_tenant_is_not_found(self):
        # A chave carrega o tenant: a de Roove não existe em Curavino.
        other_tenant_key = customers.customer_key(SHOPIFY_CLIENT, "external_id", "s-1")
        with (
            patch.object(customers, "sb_select", AsyncMock(return_value=[
                fbits_order(order_id="1", customer_id="s-1"),
            ])),
            patch.object(
                customers, "resolve_commerce_provider",
                AsyncMock(return_value={"provider": "fbits"}),
            ),
            patch(
                "services.fbits_reporting._tenant_revenue_context",
                AsyncMock(return_value=(True, {"6"}, {})),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "CUSTOMER_NOT_FOUND"):
                await customers.get_customer(
                    client_id=FBITS_CLIENT, customer_id=other_tenant_key,
                )

    async def test_rows_from_another_tenant_are_discarded(self):
        # O backend usa service role e ignora RLS: a segunda barreira é esta.
        with (
            patch.object(customers, "sb_select", AsyncMock(return_value=[
                fbits_order(order_id="1", customer_id="c-1", client_id=FBITS_CLIENT),
                fbits_order(order_id="2", customer_id="c-vazado", client_id=SHOPIFY_CLIENT, total=5000.0),
            ])),
            patch.object(
                customers, "resolve_commerce_provider",
                AsyncMock(return_value={"provider": "fbits"}),
            ),
            patch(
                "services.fbits_reporting._tenant_revenue_context",
                AsyncMock(return_value=(True, {"6"}, {})),
            ),
        ):
            payload = await customers.list_customers(client_id=FBITS_CLIENT)
        self.assertEqual(payload["totals"]["customers"], 1)
        self.assertEqual(payload["customers"][0]["external_id"], "c-1")

    async def test_every_returned_customer_carries_the_resolved_tenant(self):
        with (
            patch.object(customers, "sb_select", AsyncMock(return_value=[
                fbits_order(order_id="1", customer_id="c-1"),
            ])),
            patch.object(
                customers, "resolve_commerce_provider",
                AsyncMock(return_value={"provider": "fbits"}),
            ),
            patch(
                "services.fbits_reporting._tenant_revenue_context",
                AsyncMock(return_value=(True, {"6"}, {})),
            ),
        ):
            payload = await customers.list_customers(client_id=FBITS_CLIENT)
        for item in payload["customers"]:
            self.assertEqual(item["client_id"], FBITS_CLIENT)


class PrivacyInLogsTests(unittest.IsolatedAsyncioTestCase):
    async def capture(self) -> str:
        output = io.StringIO()
        payload = {
            "provider": "shopify",
            "total": 3,
            "customers": [
                {
                    "name": "Ana Recorrente", "email": ANA_EMAIL,
                    "phone": "5511988887777", "total_revenue": 1000.0,
                },
            ],
        }
        with (
            redirect_stdout(output),
            patch.object(routes, "require_client_read", AsyncMock(return_value=SHOPIFY_CLIENT)),
            patch.object(routes, "list_customers", AsyncMock(return_value=payload)),
        ):
            await routes.customers_list(
                search=ANA_EMAIL, page=1, page_size=25,
                client_id=SHOPIFY_CLIENT, x_client_id=None, authorization="Bearer ana",
            )
        return output.getvalue()

    async def test_the_log_carries_only_non_identifying_fields(self):
        logged = await self.capture()
        line = next(item for item in logged.splitlines() if item.startswith("[customers] "))
        for field in ("endpoint=", "client_id=", "provider=", "status=", "count=", "duration_ms=", "request_id="):
            self.assertIn(field, line)

    async def test_no_pii_reaches_the_log(self):
        logged = await self.capture()
        for secret in (ANA_EMAIL, "Ana Recorrente", "5511988887777", "98888-7777", "Ana"):
            self.assertNotIn(secret, logged)

    async def test_the_search_term_is_never_logged(self):
        # A busca é digitada pelo usuário e pode ser um e-mail completo.
        self.assertNotIn("search=", await self.capture())

    async def test_an_error_logs_only_the_exception_type(self):
        output = io.StringIO()
        with (
            redirect_stdout(output),
            patch.object(routes, "require_client_read", AsyncMock(return_value=SHOPIFY_CLIENT)),
            patch.object(
                routes, "list_customers",
                AsyncMock(side_effect=RuntimeError(f"falhou lendo {ANA_EMAIL}")),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await routes.customers_list(
                    search="", page=1, page_size=25,
                    client_id=SHOPIFY_CLIENT, x_client_id=None, authorization="Bearer ana",
                )
        self.assertEqual(raised.exception.status_code, 502)
        self.assertNotIn(ANA_EMAIL, output.getvalue())
        self.assertIn("error_type=RuntimeError", output.getvalue())


class PerformanceShapeTests(ProviderHarness):
    client_id = SHOPIFY_CLIENT

    def provider(self) -> str:
        return "shopify"

    def tables(self) -> Dict[str, List[Dict[str, Any]]]:
        return {
            "shopify_orders": [
                shopify_order(order_id=str(index), customer_id=f"s-{index}",
                              email=f"c{index}@exemplo.com")
                for index in range(1, 201)
            ],
            "shopify_customers": [
                shopify_customer(customer_id=f"s-{index}", email=f"c{index}@exemplo.com")
                for index in range(1, 201)
            ],
        }

    async def test_the_listing_makes_one_query_per_table(self):
        await self.listing()
        # Sem N+1: duas leituras no total, nenhuma por cliente.
        self.assertEqual(self.select.await_count, 2)

    async def test_the_detail_makes_one_query_per_table(self):
        key = customers.customer_key(SHOPIFY_CLIENT, "external_id", "s-5")
        await customers.get_customer(client_id=SHOPIFY_CLIENT, customer_id=key)
        self.assertEqual(self.select.await_count, 2)

    async def test_the_scan_limit_is_reported_as_truncation(self):
        self.assertFalse((await self.listing())["truncated"])
        with patch.object(customers, "CUSTOMER_ORDER_SCAN_LIMIT", 200):
            self.assertTrue((await self.listing())["truncated"])


if __name__ == "__main__":
    unittest.main()
