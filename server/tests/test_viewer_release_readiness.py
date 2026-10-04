"""Liberação dos viewers reais: o que cada papel alcança, e o que não alcança.

Cobre as lacunas desta rodada. O isolamento por tenant em si já tem suíte
própria (test_tenant_isolation) e não é reimplementado aqui — o que falta é a
matriz viewer × rotas administrativas e o contrato de PII da API de clientes.

Empresas fictícias, nunca reais.
"""

from __future__ import annotations

import inspect
import io
import json
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

from routes import client_access as client_access_routes
from routes import connections as connections_routes
from routes import customers as customers_routes
from routes import fbits as fbits_routes
from routes import google as google_routes
from routes import integrations as integrations_routes
from routes import intelligence as intelligence_routes
from routes import platform_admin as platform_admin_routes
from services import customers
from services import tenant

CURAVINO = "curavino-test"
ROOVE = "roove-test"

DENIED_ROLE = HTTPException(status_code=403, detail="Papel sem permissão para esta ação.")
DENIED_TENANT = HTTPException(status_code=403, detail="Usuário sem acesso ao client_id solicitado.")


# ---------------------------------------------------------------------------
# Matriz viewer × rotas administrativas
# ---------------------------------------------------------------------------

class ViewerIsDeniedOnAdminRoutesTests(unittest.IsolatedAsyncioTestCase):
    """Toda rota de administração/mutação recusa viewer, mesmo chamada direta.

    O frontend esconde a navegação, mas a prova que importa é o backend: o
    viewer pode digitar a URL ou chamar a API na mão.
    """

    async def assert_denied(self, module: Any, handler: str, **kwargs: Any) -> None:
        """A rota recusa antes de executar qualquer trabalho."""
        guard = "require_client_role" if hasattr(module, "require_client_role") else None
        patches = []
        if guard:
            patches.append(patch.object(module, guard, AsyncMock(side_effect=DENIED_ROLE)))
        for name in ("require_platform_admin", "require_agency_admin", "require_client_manage"):
            if hasattr(module, name):
                patches.append(patch.object(module, name, AsyncMock(side_effect=DENIED_ROLE)))
        with redirect_stdout(io.StringIO()):
            for item in patches:
                item.start()
            try:
                with self.assertRaises(HTTPException) as raised:
                    await getattr(module, handler)(**kwargs)
            finally:
                for item in reversed(patches):
                    item.stop()
        self.assertEqual(raised.exception.status_code, 403)

    async def test_viewer_cannot_manage_integrations(self):
        await self.assert_denied(
            integrations_routes, "get_client_integrations",
            client_id=CURAVINO, authorization="Bearer viewer",
        )

    async def test_viewer_cannot_connect_fbits(self):
        await self.assert_denied(
            fbits_routes, "fbits_connect",
            client_id=CURAVINO, payload={"token": "x"}, background_tasks=None,
            authorization="Bearer viewer",
        )

    async def test_viewer_cannot_disconnect_fbits(self):
        await self.assert_denied(
            fbits_routes, "fbits_disconnect",
            client_id=CURAVINO, authorization="Bearer viewer",
        )

    async def test_viewer_cannot_trigger_a_fbits_sync(self):
        await self.assert_denied(
            fbits_routes, "fbits_tenant_sync",
            client_id=CURAVINO, background_tasks=None, authorization="Bearer viewer",
        )

    async def test_viewer_cannot_trigger_a_google_ads_sync(self):
        await self.assert_denied(
            google_routes, "google_ads_sync",
            client_id=CURAVINO, x_client_id=None, authorization="Bearer viewer",
        )

    async def test_viewer_cannot_write_the_business_context(self):
        await self.assert_denied(
            intelligence_routes, "intelligence_save_business_context",
            payload={"segment": "x"}, client_id=CURAVINO,
            x_client_id=None, authorization="Bearer viewer",
        )

    async def test_viewer_cannot_create_a_user_access(self):
        await self.assert_denied(
            client_access_routes, "access_create",
            payload={"email": "x@y.com", "role": "viewer"},
            client_id=CURAVINO, x_client_id=None, authorization="Bearer viewer",
        )

    async def test_viewer_cannot_delete_a_user_access(self):
        await self.assert_denied(
            client_access_routes, "access_remove",
            user_id="u-1", client_id=CURAVINO, x_client_id=None,
            authorization="Bearer viewer",
        )

    async def test_viewer_cannot_reset_a_user_password(self):
        await self.assert_denied(
            client_access_routes, "access_reset_password",
            user_id="u-1", payload={"password": "x"},
            client_id=CURAVINO, x_client_id=None, authorization="Bearer viewer",
        )

    async def test_viewer_cannot_reach_company_administration(self):
        for handler, kwargs in (
            ("platform_companies", {"authorization": "Bearer viewer"}),
            ("platform_company_delete", {"client_id": CURAVINO, "confirmation_name": "x", "authorization": "Bearer viewer"}),
        ):
            with self.subTest(handler=handler):
                if not hasattr(platform_admin_routes, handler):
                    self.skipTest(f"handler {handler} não existe")
                await self.assert_denied(platform_admin_routes, handler, **kwargs)


class EveryMutationRouteHasARoleGuardTests(unittest.TestCase):
    """Nenhuma rota de mutação pode depender só de membership.

    Varre os módulos de rota e exige, em cada handler que muda estado, um
    guarda de papel — não apenas `resolve_client_id`, que um viewer satisfaz.
    """

    # Helpers que encapsulam um guarda de papel contam como guarda: o que não
    # vale é a rota depender só de membership.
    ROLE_GUARDS = (
        "require_client_role", "require_client_manage",
        "require_platform_admin", "require_agency_admin",
        "_manage_context", "_mutation_context", "_require_cron_secret",
    )
    # Rotas de mutação sem guarda de papel, com motivo auditado.
    EXEMPT = {
        # Desativadas: respondem 410 sem tocar em nada.
        ("meta_legacy", "api_connect_meta"),
        # Webhook da Shopify: autenticado por HMAC do provider, não por usuário.
        ("shopify", "shopify_webhook"),
        # Retornos de OAuth: autenticados pelo state assinado.
        ("google_oauth", "google_oauth_callback"),
        ("shopify_oauth", "shopify_oauth_callback"),
        # Aceite de convite: a membership é derivada do convite, não de papel.
        ("invitations", "accept_invitation"),
        # Gerar a análise estruturada é permitido a qualquer MEMBRO desde esta
        # release. O custo da chamada de IA é contido no servidor — reuso por
        # fingerprint, lock de concorrência e cooldown por tenant/período —
        # e não por papel. `POST /ask` continua exigindo gestão.
        ("intelligence", "intelligence_generate"),
        # Delega para api_refresh_all, que chama require_client_role: o guarda
        # existe, só não no corpo deste handler.
        ("meta_legacy", "api_instagram_sync"),
    }

    def modules(self) -> Dict[str, Any]:
        from routes import (
            admin_health, client_access, connections, customers as customers_mod,
            fbits, google, google_oauth, integrations, intelligence, invitations,
            meta_legacy, platform_admin, shopify, shopify_oauth,
        )
        return {
            module.__name__.rsplit(".", 1)[-1]: module
            for module in (
                admin_health, client_access, connections, customers_mod, fbits,
                google, google_oauth, integrations, intelligence, invitations,
                meta_legacy, platform_admin, shopify, shopify_oauth,
            )
        }

    def test_no_mutation_route_lacks_a_role_guard(self):
        unguarded: List[str] = []
        for name, module in self.modules().items():
            source = Path(inspect.getfile(module)).read_text(encoding="utf-8")
            for route in source.split("\n@router.")[1:]:
                header, _, body = route.partition("\n")
                method = header.split("(")[0].lower()
                if method not in {"post", "put", "patch", "delete"}:
                    continue
                handler = ""
                for line in body.splitlines():
                    if line.startswith("async def ") or line.startswith("def "):
                        handler = line.split("def ", 1)[1].split("(")[0]
                        break
                if (name, handler) in self.EXEMPT:
                    continue
                if not any(guard in body for guard in self.ROLE_GUARDS):
                    unguarded.append(f"{name}.{handler} ({method.upper()})")
        self.assertEqual(unguarded, [], f"mutação sem guarda de papel: {unguarded}")


# ---------------------------------------------------------------------------
# O que o viewer PRECISA alcançar
# ---------------------------------------------------------------------------

class ViewerCanReadItsOwnTenantTests(unittest.IsolatedAsyncioTestCase):
    async def test_viewer_reads_the_customer_base_of_its_own_company(self):
        with (
            redirect_stdout(io.StringIO()),
            patch.object(customers_routes, "require_client_read", AsyncMock(return_value=CURAVINO)),
            patch.object(
                customers_routes, "list_customers",
                AsyncMock(return_value={"provider": "fbits", "total": 1}),
            ) as listing,
        ):
            await customers_routes.customers_list(
                search="", page=1, page_size=25,
                client_id=CURAVINO, x_client_id=None, authorization="Bearer viewer",
            )
        self.assertEqual(listing.await_args.kwargs["client_id"], CURAVINO)

    async def test_viewer_reads_the_intelligence_of_its_own_company(self):
        with (
            patch.object(intelligence_routes, "require_user_id", AsyncMock(return_value="viewer-1")),
            patch.object(intelligence_routes, "resolve_client_id", AsyncMock(return_value=CURAVINO)),
            patch.object(
                intelligence_routes, "latest_analysis",
                AsyncMock(return_value={"ok": True, "analysis": None}),
            ) as latest,
        ):
            await intelligence_routes.intelligence_latest(
                start=None, end=None, client_id=CURAVINO,
                x_client_id=None, authorization="Bearer viewer",
            )
        self.assertEqual(latest.await_args.args[0], CURAVINO)

    async def test_viewer_cannot_read_another_company(self):
        with (
            redirect_stdout(io.StringIO()),
            patch.object(
                customers_routes, "require_client_read",
                AsyncMock(side_effect=DENIED_TENANT),
            ),
            patch.object(customers_routes, "list_customers", AsyncMock()) as listing,
        ):
            with self.assertRaises(HTTPException) as raised:
                await customers_routes.customers_list(
                    search="", page=1, page_size=25,
                    client_id=ROOVE, x_client_id=ROOVE, authorization="Bearer viewer-curavino",
                )
        self.assertEqual(raised.exception.status_code, 403)
        listing.assert_not_awaited()

    async def test_the_customer_reader_accepts_viewer_by_design(self):
        # /api/customers usa require_client_read, que não exige papel de
        # mutação. É intencional: a base de clientes é leitura.
        source = Path(inspect.getfile(customers_routes)).read_text(encoding="utf-8")
        self.assertIn("require_client_read", source)
        self.assertNotIn("require_client_role", source)
        self.assertNotIn("require_client_manage", source)


class AgencyAdminStillWorksTests(unittest.IsolatedAsyncioTestCase):
    async def test_agency_admin_resolves_an_explicit_company_without_membership(self):
        with (
            redirect_stdout(io.StringIO()),
            patch.object(tenant, "require_user_id", AsyncMock(return_value="julia")),
            patch("services.platform_admin.is_platform_admin", AsyncMock(return_value=False)),
            patch.object(tenant, "_has_agency_admin_membership", AsyncMock(return_value=True)),
            patch("services.ig_supabase.sb_select", AsyncMock(return_value=[{"id": CURAVINO}])),
        ):
            resolved = await tenant.resolve_client_id(CURAVINO, "Bearer julia")
        self.assertEqual(resolved, CURAVINO)

    async def test_agency_admin_still_needs_an_explicit_company(self):
        with (
            redirect_stdout(io.StringIO()),
            patch.object(tenant, "require_user_id", AsyncMock(return_value="danilo")),
            patch("services.platform_admin.is_platform_admin", AsyncMock(return_value=False)),
            patch.object(tenant, "_has_agency_admin_membership", AsyncMock(return_value=True)),
        ):
            with self.assertRaises(HTTPException) as raised:
                await tenant.resolve_client_id(None, "Bearer danilo")
        self.assertEqual(raised.exception.status_code, 400)


# ---------------------------------------------------------------------------
# Contrato de PII da API de clientes
# ---------------------------------------------------------------------------

class CustomerApiExposesOnlyTheAllowedFieldsTests(unittest.IsolatedAsyncioTestCase):
    """Nome, telefone e e-mail podem sair. CPF, endereço, pagamento e payload
    bruto, nunca — mesmo estando no `raw` do pedido."""

    CPF = "12345678900"
    CEP = "01000-000"
    CARD = "4111"

    def orders(self) -> List[Dict[str, Any]]:
        return [{
            "client_id": CURAVINO, "order_id": "1", "order_code": "PED-1",
            "customer_id": "555", "customer_name": None, "customer_email": None,
            "status_id": "1", "status_name": "Pago",
            "order_date": "2026-10-01T10:00:00Z", "total_value": 100.0, "is_valid": True,
            "raw": {
                "usuario": {"usuarioId": 555, "cpf": self.CPF},
                "pedidoEndereco": [{"endereco": "Rua Sigilosa", "cep": self.CEP}],
                "pagamento": [{"cartaoCredito": [{"numeroCartao": self.CARD}]}],
            },
        }]

    def identities(self, **overrides: Any) -> List[Dict[str, Any]]:
        row = {
            "client_id": CURAVINO, "fbits_customer_id": "555",
            "name": "Ana Cliente", "email": "ana@exemplo.com", "phone": "11988887777",
            "updated_at_provider": None, "synced_at": "2026-10-04T08:00:00Z",
        }
        row.update(overrides)
        return [row]

    async def payload(self, **overrides: Any) -> str:
        orders, identities = self.orders(), self.identities(**overrides)

        async def select(table: str, **_kwargs: Any) -> List[Dict[str, Any]]:
            return orders if table == "fbits_orders" else identities if table == "fbits_customers" else []

        with (
            redirect_stdout(io.StringIO()),
            patch.object(customers, "sb_select", AsyncMock(side_effect=select)),
            patch.object(
                customers, "resolve_commerce_provider",
                AsyncMock(return_value={"provider": "fbits"}),
            ),
            patch("services.fbits_reporting._tenant_revenue_context",
                  AsyncMock(return_value=(True, {"1"}, {}))),
        ):
            listing = await customers.list_customers(client_id=CURAVINO)
            detail = await customers.get_customer(
                client_id=CURAVINO,
                customer_id=customers.customer_key(CURAVINO, "external_id", "555"),
            )
        return json.dumps({"list": listing, "detail": detail}, ensure_ascii=False)

    async def test_the_listing_carries_name_phone_and_email(self):
        blob = await self.payload()
        for allowed in ("Ana Cliente", "ana@exemplo.com", "11988887777"):
            self.assertIn(allowed, blob)

    async def test_no_cpf_address_payment_or_raw_payload_is_exposed(self):
        blob = await self.payload()
        for forbidden in (
            self.CPF, self.CEP, self.CARD, "Rua Sigilosa",
            "pedidoEndereco", "pagamento", "cartaoCredito", "usuarioId", '"raw"',
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, blob)

    async def test_the_summary_keys_are_exactly_the_contract(self):
        async def select(table: str, **_kwargs: Any) -> List[Dict[str, Any]]:
            return self.orders() if table == "fbits_orders" else self.identities() if table == "fbits_customers" else []

        with (
            redirect_stdout(io.StringIO()),
            patch.object(customers, "sb_select", AsyncMock(side_effect=select)),
            patch.object(
                customers, "resolve_commerce_provider",
                AsyncMock(return_value={"provider": "fbits"}),
            ),
            patch("services.fbits_reporting._tenant_revenue_context",
                  AsyncMock(return_value=(True, {"1"}, {}))),
        ):
            listing = await customers.list_customers(client_id=CURAVINO)
        self.assertEqual(
            set(listing["customers"][0]),
            {
                "id", "external_id", "client_id", "provider", "provider_label",
                "identity_kind", "name", "email", "phone", "orders_count",
                "total_revenue", "average_ticket", "first_order_at",
                "last_order_at", "status",
            },
        )

    async def test_the_order_history_keys_are_exactly_the_contract(self):
        blob = json.loads(await self.payload())
        self.assertEqual(
            set(blob["detail"]["orders"][0]),
            {"order_id", "reference", "happened_at", "value", "status", "counts_as_revenue"},
        )

    async def test_every_contact_field_may_be_null_without_breaking(self):
        blob = json.loads(await self.payload(name=None, email=None, phone=None))
        customer = blob["list"]["customers"][0]
        self.assertIsNone(customer["name"])
        self.assertIsNone(customer["email"])
        self.assertIsNone(customer["phone"])
        # O comportamento de compra continua inteiro.
        self.assertEqual(customer["orders_count"], 1)
        self.assertEqual(customer["total_revenue"], 100.0)
        self.assertFalse(blob["list"]["contact_details_available"])

    async def test_a_customer_with_no_identity_row_still_lists(self):
        async def select(table: str, **_kwargs: Any) -> List[Dict[str, Any]]:
            return self.orders() if table == "fbits_orders" else []

        with (
            redirect_stdout(io.StringIO()),
            patch.object(customers, "sb_select", AsyncMock(side_effect=select)),
            patch.object(
                customers, "resolve_commerce_provider",
                AsyncMock(return_value={"provider": "fbits"}),
            ),
            patch("services.fbits_reporting._tenant_revenue_context",
                  AsyncMock(return_value=(True, {"1"}, {}))),
        ):
            listing = await customers.list_customers(client_id=CURAVINO)
        self.assertEqual(listing["totals"]["customers"], 1)
        self.assertIsNone(listing["customers"][0]["name"])


class IntelligenceGenerationIsOpenToMembersTests(unittest.IsolatedAsyncioTestCase):
    """Gerar a análise estruturada passou a ser permitido a qualquer membro.

    A proteção de custo migrou do papel para o servidor: reuso por fingerprint
    e cooldown por tenant/período. `POST /ask` continua restrito a gestão.
    """

    async def test_generation_authorizes_by_membership(self):
        with (
            redirect_stdout(io.StringIO()),
            patch.object(intelligence_routes, "require_user_id", AsyncMock(return_value="nasser")),
            patch.object(intelligence_routes, "resolve_client_id", AsyncMock(return_value=CURAVINO)) as tenant,
            # Se a rota voltar a exigir papel, este mock derruba o teste.
            patch.object(
                intelligence_routes, "require_client_role", AsyncMock(side_effect=DENIED_ROLE),
            ),
            patch.object(
                intelligence_routes, "generate_analysis",
                AsyncMock(return_value={"ok": True, "status": "completed"}),
            ) as generate,
        ):
            result = await intelligence_routes.intelligence_generate(
                payload={"start": "2026-10-01", "end": "2026-10-04"},
                client_id=CURAVINO, x_client_id=None, authorization="Bearer viewer",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(tenant.await_args.args[0], CURAVINO)
        self.assertEqual(generate.await_args.kwargs["client_id"], CURAVINO)

    async def test_the_tenant_comes_from_the_backend_not_the_browser(self):
        with (
            redirect_stdout(io.StringIO()),
            patch.object(intelligence_routes, "require_user_id", AsyncMock(return_value="nasser")),
            patch.object(intelligence_routes, "resolve_client_id", AsyncMock(return_value=CURAVINO)),
            patch.object(
                intelligence_routes, "generate_analysis",
                AsyncMock(return_value={"ok": True}),
            ) as generate,
        ):
            await intelligence_routes.intelligence_generate(
                payload={}, client_id=ROOVE, x_client_id=ROOVE,
                authorization="Bearer viewer-curavino",
            )
        self.assertEqual(generate.await_args.kwargs["client_id"], CURAVINO)

    async def test_a_cross_tenant_generation_is_denied(self):
        with (
            redirect_stdout(io.StringIO()),
            patch.object(intelligence_routes, "require_user_id", AsyncMock(return_value="nasser")),
            patch.object(
                intelligence_routes, "resolve_client_id", AsyncMock(side_effect=DENIED_TENANT),
            ),
            patch.object(intelligence_routes, "generate_analysis", AsyncMock()) as generate,
        ):
            with self.assertRaises(HTTPException) as raised:
                await intelligence_routes.intelligence_generate(
                    payload={}, client_id=ROOVE, x_client_id=ROOVE,
                    authorization="Bearer viewer-curavino",
                )
        self.assertEqual(raised.exception.status_code, 403)
        generate.assert_not_awaited()

    async def test_ask_stays_closed_to_a_viewer(self):
        with (
            redirect_stdout(io.StringIO()),
            patch.object(
                intelligence_routes, "require_client_role", AsyncMock(side_effect=DENIED_ROLE),
            ),
            patch.object(intelligence_routes, "ask_intelligence", AsyncMock()) as ask,
        ):
            with self.assertRaises(HTTPException) as raised:
                await intelligence_routes.intelligence_ask(
                    payload={"question": "como foi o mês?"},
                    client_id=CURAVINO, x_client_id=None, authorization="Bearer viewer",
                )
        self.assertEqual(raised.exception.status_code, 403)
        ask.assert_not_awaited()

    async def test_the_cooldown_answers_429_with_retry_after(self):
        with (
            redirect_stdout(io.StringIO()),
            patch.object(intelligence_routes, "require_user_id", AsyncMock(return_value="nasser")),
            patch.object(intelligence_routes, "resolve_client_id", AsyncMock(return_value=CURAVINO)),
            patch.object(
                intelligence_routes, "generate_analysis",
                AsyncMock(side_effect=RuntimeError("AI_GENERATION_COOLDOWN:42")),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await intelligence_routes.intelligence_generate(
                    payload={}, client_id=CURAVINO, x_client_id=None, authorization="Bearer viewer",
                )
        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual((raised.exception.headers or {}).get("Retry-After"), "42")

    async def test_the_route_sources_are_explicit_about_the_split(self):
        source = Path(inspect.getfile(intelligence_routes)).read_text(encoding="utf-8")
        generate = source.split('@router.post("/analyses")')[1].split("@router.")[0]
        ask = source.split('@router.post("/ask")')[1].split("@router.")[0]
        self.assertIn("await _context(", generate)
        self.assertNotIn("_mutation_context(", generate)
        self.assertIn("_mutation_context(", ask)


class ViewerStillReadsIntelligenceTests(unittest.IsolatedAsyncioTestCase):
    """A correção não pode ter fechado a leitura."""

    READ_HANDLERS = (
        ("intelligence_context", {"start": None, "end": None, "days": 30}),
        ("intelligence_latest", {"start": None, "end": None}),
        ("intelligence_history", {"limit": 20}),
        ("intelligence_business_context", {}),
    )

    async def test_every_read_route_still_accepts_a_viewer(self):
        for handler, extra in self.READ_HANDLERS:
            with self.subTest(handler=handler):
                with (
                    redirect_stdout(io.StringIO()),
                    patch.object(intelligence_routes, "require_user_id", AsyncMock(return_value="viewer-1")),
                    patch.object(intelligence_routes, "resolve_client_id", AsyncMock(return_value=CURAVINO)),
                    # Se alguma leitura passar a exigir papel, este mock falha o teste.
                    patch.object(
                        intelligence_routes, "require_client_role",
                        AsyncMock(side_effect=DENIED_ROLE),
                    ),
                    patch.object(intelligence_routes, "calculate_intelligence_snapshot", AsyncMock(return_value={})),
                    patch.object(intelligence_routes, "latest_analysis", AsyncMock(return_value={"ok": True})),
                    patch.object(intelligence_routes, "analysis_history", AsyncMock(return_value={"ok": True})),
                    patch.object(intelligence_routes, "load_business_context", AsyncMock(return_value={})),
                ):
                    await getattr(intelligence_routes, handler)(
                        client_id=CURAVINO, x_client_id=None,
                        authorization="Bearer viewer", **extra,
                    )

    async def test_a_viewer_still_reads_conversation_messages(self):
        with (
            patch.object(intelligence_routes, "require_user_id", AsyncMock(return_value="viewer-1")),
            patch.object(intelligence_routes, "resolve_client_id", AsyncMock(return_value=CURAVINO)),
            patch.object(
                intelligence_routes, "require_client_role",
                AsyncMock(side_effect=DENIED_ROLE),
            ),
            patch.object(
                intelligence_routes, "conversation_messages",
                AsyncMock(return_value={"ok": True, "messages": []}),
            ),
        ):
            result = await intelligence_routes.intelligence_messages(
                conversation_id="conv-1", client_id=CURAVINO,
                x_client_id=None, authorization="Bearer viewer",
            )
        self.assertTrue(result["ok"])


class NasserViewerSessionTests(unittest.TestCase):
    """O caso real: viewer de Curavino abrindo a plataforma.

    O que quebrou em produção não foi autorização de leitura de dados — foi
    uma leitura de DADOS depender de um endpoint ADMINISTRATIVO. A resolução
    da loja ativa chamava `/api/clients/{id}/integrations` (403 para viewer) e
    a página de Ecommerce faz early return no erro.
    """

    FRONT = SERVER_DIR.parent / "src"

    def test_the_integrations_endpoint_stays_administrative(self):
        # A proteção é intencional e não foi revertida: o contrato expõe
        # ad_account_id, business_id e property_id.
        source = Path(inspect.getfile(integrations_routes)).read_text(encoding="utf-8")
        self.assertIn("require_client_role", source)
        self.assertIn('allowed_roles=("agency_admin", "client_admin")', source)

    def test_the_commerce_resolver_no_longer_depends_on_it(self):
        hook = (self.FRONT / "hooks" / "dashboard" / "useActiveEcommerceProvider.ts").read_text(encoding="utf-8")
        self.assertNotIn("getClientIntegrations", hook)
        self.assertIn("listGenericConnections", hook)

    def test_the_replacement_endpoint_accepts_any_member(self):
        source = Path(inspect.getfile(connections_routes)).read_text(encoding="utf-8")
        self.assertIn("require_client_read", source)
        self.assertNotIn("require_client_role", source)

    def test_no_page_blocks_rendering_on_the_administrative_hook(self):
        # Early return em erro de integrações foi o que deixou o viewer sem
        # tela. Nenhuma página pode voltar a fazer isso.
        for page in (self.FRONT / "pages").glob("*.tsx"):
            if ".test." in page.name:
                continue
            body = page.read_text(encoding="utf-8")
            if "useClientIntegrations" not in body:
                continue
            with self.subTest(page=page.name):
                for blocking in ("if (integrations.error)", "if (integrations.isLoading)"):
                    self.assertNotIn(blocking, body)

    def test_the_viewer_read_surface_uses_membership_guards(self):
        expected = {
            "customers": "require_client_read",
            "connections": "require_client_read",
        }
        for module, guard in expected.items():
            source = Path(inspect.getfile(__import__(f"routes.{module}", fromlist=["x"]))).read_text(encoding="utf-8")
            with self.subTest(module=module):
                self.assertIn(guard, source)

    def test_intelligence_reads_stay_open_and_ask_stays_closed(self):
        source = Path(inspect.getfile(intelligence_routes)).read_text(encoding="utf-8")
        # Leituras e geração da análise: membership. /ask: papel de gestão.
        for by_membership in ('@router.get("/context")', '@router.get("/latest")',
                              '@router.get("/history")', '@router.get("/business-context")',
                              '@router.post("/analyses")'):
            block = source.split(by_membership)[1].split("@router.")[0]
            with self.subTest(route=by_membership):
                self.assertIn("await _context(", block)
                self.assertNotIn("_mutation_context(", block)
        ask = source.split('@router.post("/ask")')[1].split("@router.")[0]
        self.assertIn("_mutation_context(", ask)


class RefreshIsRevalidationNotSyncTests(unittest.TestCase):
    """"Atualizar dados" do viewer relê o persistido; não sincroniza provider.

    O botão administrativo chama Meta, Google, FBITS e Shopify. A FBITS
    bloqueia o token da loja por uma hora depois de insistir no 429, então
    deixar qualquer membro disparar aquilo derrubaria a integração da empresa
    inteira. A ação do viewer é a releitura dos GETs que ele já pode fazer —
    nenhum endpoint novo, nenhum privilégio novo.
    """

    FRONT = SERVER_DIR.parent / "src"

    def refresh_helper(self) -> str:
        return (self.FRONT / "app" / "dataRefresh.ts").read_text(encoding="utf-8")

    def intelligence_page(self) -> str:
        return (self.FRONT / "pages" / "Intelligence.tsx").read_text(encoding="utf-8")

    def test_no_new_backend_endpoint_was_created_for_refresh(self):
        routes_dir = SERVER_DIR / "routes"
        for path in routes_dir.glob("*.py"):
            body = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotIn('@router.post("/refresh")', body)
                self.assertNotIn('"/api/refresh"', body)

    def test_the_sync_endpoints_keep_requiring_a_management_role(self):
        # Nenhum endpoint administrativo foi aberto para resolver a UX.
        for module, handler in (
            (fbits_routes, "fbits_tenant_sync"),
            (fbits_routes, "fbits_sync"),
            (google_routes, "google_ads_sync"),
            (google_routes, "ga4_sync"),
        ):
            source = Path(inspect.getfile(module)).read_text(encoding="utf-8")
            block = source.split(f"async def {handler}(")[1].split("@router.")[0]
            with self.subTest(handler=handler):
                self.assertIn("require_client_role", block)

    def test_the_refresh_action_never_calls_the_ai(self):
        page = self.intelligence_page()
        refresh = page.split("const refreshData = useCallback(")[1].split("}, [")[0]
        for forbidden in ("generateIntelligenceAnalysis", "askIntelligence", "generate_analysis"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, refresh)

    def test_the_refresh_action_never_triggers_a_provider_sync(self):
        page = self.intelligence_page()
        refresh = page.split("const refreshData = useCallback(")[1].split("}, [")[0]
        # "sync" casaria com "async": a verificação é pelos símbolos reais
        # que disparariam sincronização de provider.
        for forbidden in ("runExclusiveSync", "syncAds", "syncFbits", "syncShopify", "syncGa4"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, refresh)

    def test_a_cooldown_guards_against_spam(self):
        helper = self.refresh_helper()
        self.assertIn("REFRESH_COOLDOWN_MS", helper)
        self.assertIn("cooldownFrom", helper)
        self.assertIn("cooldownFrom(lastRefreshAt)", self.intelligence_page())

    def test_ask_stays_closed_to_a_viewer(self):
        # Gerar análise abriu nesta release; conversa livre com o modelo, não.
        source = Path(inspect.getfile(intelligence_routes)).read_text(encoding="utf-8")
        ask = source.split('@router.post("/ask")')[1].split("@router.")[0]
        self.assertIn("_mutation_context(", ask)

    def test_the_persisted_cache_is_scoped_per_tenant(self):
        # Reabrir a tela não pode mostrar o último estado de OUTRA empresa.
        page = self.intelligence_page()
        self.assertIn('buildDashboardCacheKey("intelligence-workspace", { clientId: key })', page)
        self.assertIn("const cacheKey = `${clientId}:${period.start}:${period.end}`", page)

    def test_the_customers_cache_is_scoped_per_tenant(self):
        page = (self.FRONT / "pages" / "Customers.tsx").read_text(encoding="utf-8")
        self.assertIn('buildDashboardCacheKey("customers-base", { clientId })', page)


class ClientAccessReadIsIntentionalForMembersTests(unittest.TestCase):
    """Achado documentado: a LEITURA de acessos aceita qualquer membro.

    Não é mutação e é escopada ao próprio tenant. Travado aqui para que, se
    algum dia virar mutação sem guarda de papel, o teste acuse.
    """

    def test_the_read_uses_membership_and_the_writes_use_role(self):
        source = Path(inspect.getfile(client_access_routes)).read_text(encoding="utf-8")
        read_block = source.split('@router.get("")')[1].split("@router.post")[0]
        self.assertIn("resolve_client_id", read_block)
        self.assertNotIn("require_client_role", read_block)
        for mutation in ('@router.post("")', '@router.post("/{user_id}/password")', '@router.delete("/{user_id}")'):
            block = source.split(mutation)[1][:400]
            self.assertIn("_manage_context", block, mutation)


if __name__ == "__main__":
    unittest.main()
