"""Descoberta de ativos Meta via Business (owned/client) — merge, deduplicação,
estado de acesso, isolamento de falhas e gravação só no tenant do handoff.

Os IDs da RÜAH e da Mugô são apenas fixtures do caso real/regressão; o runtime
não conhece nenhum deles.
"""

import io
import os
import sys
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services import meta_http, meta_oauth
from services.integration_errors import IntegrationError
from services.meta_http import MetaApiError

TOKEN = "provider-user-token-value"
APP_SECRET = "app-secret-value"

# Caso real RÜAH (somente fixture/diagnóstico).
RUAH_BUSINESS = "2633867063339117"
RUAH_AD_ACCOUNT = "1391863696277834"
# Regressão Mugô (somente fixture).
MUGO_BUSINESS = "585767010886087"
MUGO_PAGE = "516985944838234"
MUGO_INSTAGRAM = "17841471880135733"
MUGO_AD_ACCOUNT = "8024076734300108"

PERMISSIONS = {"data": [
    {"permission": "ads_read", "status": "granted"},
    {"permission": "business_management", "status": "granted"},
    {"permission": "pages_show_list", "status": "granted"},
]}


def permission_denied(message="(#200) Requires business_management permission", code=200, subcode=None, status=403):
    # Reproduz o payload real do Graph: erros de permissao code=200 tambem
    # chegam com type=OAuthException. O parser nao pode confundi-los com o
    # token invalido code=190.
    response = httpx.Response(
        status,
        request=httpx.Request("GET", "https://graph.facebook.com/v25.0/business/owned_ad_accounts"),
        json={"error": {
            "message": message,
            "type": "OAuthException",
            "code": code,
            **({"error_subcode": subcode} if subcode is not None else {}),
            "fbtrace_id": "trace-abc",
        }},
    )
    return meta_http._http_error_from_response(response)


class FakeGraph:
    """Graph API simulada por caminho. Caminho não roteado = 404 da Meta."""

    def __init__(self, routes):
        self.routes = routes
        self.paths = []

    def _resolve(self, path):
        self.paths.append(path)
        value = self.routes.get(path)
        if value is None:
            raise MetaApiError("Meta API error 404: Unknown path", status_code=404, error_code=803)
        if isinstance(value, Exception):
            raise value
        return value

    async def meta_get(self, path, params):
        assert params.get("access_token") == TOKEN
        return self._resolve(path)

    async def meta_get_json(self, path_or_url, *, params=None, **_kwargs):
        return self._resolve(path_or_url)


def base_routes(**overrides):
    routes = {
        "/me": {"id": "meta-user-1", "name": "Pessoa Autorizada"},
        "/me/accounts": {"data": []},
        "/me/adaccounts": {"data": []},
        "/me/permissions": PERMISSIONS,
        "/me/businesses": {"data": []},
    }
    routes.update(overrides)
    return routes


class _DiscoveryCase(unittest.IsolatedAsyncioTestCase):
    async def discover(self, routes):
        graph = FakeGraph(routes)
        output = io.StringIO()
        with (
            patch.dict(os.environ, {"META_APP_ID": "app-1", "META_APP_SECRET": APP_SECRET}, clear=False),
            patch.object(meta_oauth, "get_meta_oauth_settings", side_effect=RuntimeError("sem credenciais no teste")),
            patch.object(meta_oauth, "_meta_get", AsyncMock(side_effect=graph.meta_get)),
            patch.object(meta_oauth, "meta_get_json", AsyncMock(side_effect=graph.meta_get_json)),
            patch.object(meta_oauth, "sb_insert", AsyncMock()) as insert,
            patch.object(meta_oauth, "sb_update", AsyncMock()) as update,
            redirect_stdout(output),
        ):
            result = await meta_oauth.discover_assets(TOKEN)
        # Descobrir nunca grava nada (nenhum ativo é atribuído a tenant).
        insert.assert_not_awaited()
        update.assert_not_awaited()
        logs = output.getvalue()
        self.assertNotIn(TOKEN, logs)
        self.assertNotIn(APP_SECRET, logs)
        return result, logs, graph

    @staticmethod
    def ads_by_id(result):
        return {row["ad_account_id"]: row for row in result["ad_accounts"]}


class AdAccountDiscoveryTests(_DiscoveryCase):
    async def test_1_account_found_by_me_adaccounts(self):
        result, _logs, graph = await self.discover(base_routes(**{
            "/me/adaccounts": {"data": [{"id": f"act_{MUGO_AD_ACCOUNT}", "name": "Mugô Ads"}]},
        }))
        account = self.ads_by_id(result)[f"act_{MUGO_AD_ACCOUNT}"]
        self.assertEqual(account["discovery_sources"], ["me_adaccounts"])
        self.assertEqual(account["access_status"], meta_oauth.ACCESS_ACCESSIBLE)
        # Conta direta não precisa de verificação extra.
        self.assertNotIn(f"/act_{MUGO_AD_ACCOUNT}", graph.paths)

    async def test_2_3_account_absent_from_me_found_by_business_owned(self):
        result, logs, _graph = await self.discover(base_routes(**{
            "/me/adaccounts": {"data": [{"id": "act_999", "name": "Outra"}]},
            "/me/businesses": {"data": [{"id": RUAH_BUSINESS, "name": "RÜAH"}]},
            f"/{RUAH_BUSINESS}/owned_ad_accounts": {"data": [{"id": f"act_{RUAH_AD_ACCOUNT}", "name": "RÜAH Ads"}]},
            f"/{RUAH_BUSINESS}/client_ad_accounts": {"data": []},
            f"/{RUAH_BUSINESS}/owned_pages": {"data": []},
            f"/{RUAH_BUSINESS}/client_pages": {"data": []},
            f"/act_{RUAH_AD_ACCOUNT}": {"id": f"act_{RUAH_AD_ACCOUNT}", "name": "RÜAH Ads"},
        }))
        account = self.ads_by_id(result)[f"act_{RUAH_AD_ACCOUNT}"]
        self.assertEqual(account["discovery_sources"], ["business_owned"])
        self.assertEqual(account["businesses"], [{"business_id": RUAH_BUSINESS, "business_name": "RÜAH", "relation": "owned"}])
        self.assertEqual(account["access_status"], meta_oauth.ACCESS_ACCESSIBLE)
        self.assertIn(f"ad_account_id=act_{RUAH_AD_ACCOUNT} sources=business_owned businesses={RUAH_BUSINESS}:owned", logs)

    async def test_4_client_ad_accounts(self):
        result, _logs, _graph = await self.discover(base_routes(**{
            "/me/businesses": {"data": [{"id": "biz-agency", "name": "Agência"}]},
            "/biz-agency/owned_ad_accounts": {"data": []},
            "/biz-agency/client_ad_accounts": {"data": [{"id": "act_777", "name": "Cliente da agência"}]},
            "/biz-agency/owned_pages": {"data": []},
            "/biz-agency/client_pages": {"data": []},
            "/act_777": {"id": "act_777"},
        }))
        account = self.ads_by_id(result)["act_777"]
        self.assertEqual(account["discovery_sources"], ["business_client"])
        self.assertEqual(account["businesses"][0]["relation"], "client")

    async def test_5_6_same_account_from_multiple_sources_appears_once_by_real_id(self):
        result, _logs, graph = await self.discover(base_routes(**{
            "/me/adaccounts": {"data": [{"id": "act_123", "name": "Conta"}]},
            "/me/businesses": {"data": [{"id": "biz-a", "name": "A"}, {"id": "biz-b", "name": "B"}]},
            # Mesma conta com e sem prefixo act_: o ID real é o mesmo.
            "/biz-a/owned_ad_accounts": {"data": [{"id": "act_123", "account_id": "123"}]},
            "/biz-a/client_ad_accounts": {"data": []},
            "/biz-b/owned_ad_accounts": {"data": []},
            "/biz-b/client_ad_accounts": {"data": [{"account_id": "123", "name": "Conta"}]},
            "/biz-a/owned_pages": {"data": []}, "/biz-a/client_pages": {"data": []},
            "/biz-b/owned_pages": {"data": []}, "/biz-b/client_pages": {"data": []},
        }))
        matches = [row for row in result["ad_accounts"] if row["ad_account_id"] == "act_123"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["discovery_sources"], ["me_adaccounts", "business_owned", "business_client"])
        self.assertEqual(
            [(ref["business_id"], ref["relation"]) for ref in matches[0]["businesses"]],
            [("biz-a", "owned"), ("biz-b", "client")],
        )
        self.assertNotIn("/act_123", graph.paths)

    async def test_7_business_without_accounts(self):
        result, logs, _graph = await self.discover(base_routes(**{
            "/me/businesses": {"data": [{"id": "biz-empty", "name": "Vazio"}]},
            "/biz-empty/owned_ad_accounts": {"data": []},
            "/biz-empty/client_ad_accounts": {"data": []},
            "/biz-empty/owned_pages": {"data": []},
            "/biz-empty/client_pages": {"data": []},
        }))
        self.assertEqual(result["ad_accounts"], [])
        business = result["business_managers"][0]
        self.assertEqual(business["discovery"]["owned_ad_accounts"], {"status": "ok", "count": 0})
        self.assertIn("stage=business_edge business_id=biz-empty edge=owned_ad_accounts", logs)

    async def test_8_business_permission_denied_is_reported_not_raised(self):
        result, logs, _graph = await self.discover(base_routes(**{
            "/me/businesses": {"data": [{"id": "biz-locked", "name": "Bloqueado"}]},
            "/biz-locked/owned_ad_accounts": permission_denied(),
            "/biz-locked/client_ad_accounts": permission_denied(),
            "/biz-locked/owned_pages": {"data": []},
            "/biz-locked/client_pages": {"data": []},
        }))
        discovery = result["business_managers"][0]["discovery"]
        self.assertEqual(discovery["owned_ad_accounts"], {"status": "permission_denied"})
        self.assertEqual(discovery["client_ad_accounts"], {"status": "permission_denied"})
        self.assertIn(
            "stage=business_edge_failed business_id=biz-locked edge=owned_ad_accounts asset_type=ad_account "
            "source=business_owned status=permission_denied http_status=403 graph_code=200",
            logs,
        )
        self.assertIn("trace_id=trace-abc", logs)

    async def test_9_one_failing_business_does_not_drop_the_others(self):
        result, logs, _graph = await self.discover(base_routes(**{
            "/me/businesses": {"data": [
                {"id": "biz-a", "name": "A"}, {"id": "biz-b", "name": "B"}, {"id": "biz-c", "name": "C"},
            ]},
            "/biz-a/owned_ad_accounts": {"data": [{"id": "act_a"}]},
            "/biz-a/client_ad_accounts": {"data": []},
            "/biz-b/owned_ad_accounts": permission_denied(),
            "/biz-b/client_ad_accounts": MetaApiError("Meta API error 500: boom", status_code=500),
            "/biz-c/owned_ad_accounts": {"data": [{"id": "act_c"}]},
            "/biz-c/client_ad_accounts": {"data": []},
            "/biz-a/owned_pages": {"data": []}, "/biz-a/client_pages": {"data": []},
            "/biz-b/owned_pages": permission_denied(), "/biz-b/client_pages": {"data": []},
            "/biz-c/owned_pages": {"data": []}, "/biz-c/client_pages": {"data": []},
            "/act_a": {"id": "act_a"},
            "/act_c": {"id": "act_c"},
        }))
        self.assertEqual(sorted(self.ads_by_id(result)), ["act_a", "act_c"])
        self.assertIn("edges_ok=9 edges_permission_denied=2 edges_failed=1", logs)

    async def test_14_identified_by_business_but_blocked_by_permission_is_restricted(self):
        result, logs, _graph = await self.discover(base_routes(**{
            "/me/businesses": {"data": [{"id": RUAH_BUSINESS, "name": "RÜAH"}]},
            f"/{RUAH_BUSINESS}/owned_ad_accounts": {"data": [{"id": f"act_{RUAH_AD_ACCOUNT}", "name": "RÜAH Ads"}]},
            f"/{RUAH_BUSINESS}/client_ad_accounts": {"data": []},
            f"/{RUAH_BUSINESS}/owned_pages": {"data": [{"id": "page-ruah", "name": "RÜAH"}]},
            f"/{RUAH_BUSINESS}/client_pages": {"data": []},
            f"/act_{RUAH_AD_ACCOUNT}": permission_denied(
                "Unsupported get request. Object does not exist, cannot be loaded due to missing permissions",
                code=100, subcode=33, status=400,
            ),
            "/page-ruah": permission_denied("(#10) Requires pages_read_engagement", code=10),
        }))
        account = self.ads_by_id(result)[f"act_{RUAH_AD_ACCOUNT}"]
        self.assertEqual(account["access_status"], meta_oauth.ACCESS_RESTRICTED)
        page = next(page for page in result["pages"] if page["page_id"] == "page-ruah")
        self.assertEqual(page["access_status"], meta_oauth.ACCESS_RESTRICTED)
        # Sem detalhe da Página não há vínculo Instagram conhecido.
        self.assertEqual(result["instagram_accounts"], [])
        self.assertIn(f"stage=ad_account_access ad_account_id=act_{RUAH_AD_ACCOUNT} access=restricted", logs)
        self.assertIn("restricted=1", logs)

    async def test_transient_check_failure_is_unverified_not_restricted(self):
        result, _logs, _graph = await self.discover(base_routes(**{
            "/me/businesses": {"data": [{"id": "biz-a", "name": "A"}]},
            "/biz-a/owned_ad_accounts": {"data": [{"id": "act_t"}]},
            "/biz-a/client_ad_accounts": {"data": []},
            "/biz-a/owned_pages": {"data": []}, "/biz-a/client_pages": {"data": []},
            "/act_t": MetaApiError("Meta API error 503: unavailable", status_code=503, retryable=True),
        }))
        self.assertEqual(self.ads_by_id(result)["act_t"]["access_status"], meta_oauth.ACCESS_UNVERIFIED)

    async def test_invalid_token_during_business_discovery_still_interrupts(self):
        invalid = MetaApiError("Meta API error 401: Error validating access token", status_code=401, error_code=190, invalid_oauth=True)
        with self.assertRaises(MetaApiError):
            await self.discover(base_routes(**{
                "/me/businesses": {"data": [{"id": "biz-a", "name": "A"}]},
                "/biz-a/owned_ad_accounts": invalid,
                "/biz-a/client_ad_accounts": {"data": []},
                "/biz-a/owned_pages": {"data": []}, "/biz-a/client_pages": {"data": []},
            }))


class BusinessListingFallbackTests(_DiscoveryCase):
    """/me/businesses complementa os ativos diretos: falha dele não derruba a descoberta."""

    WARNING_CODE = "META_BUSINESSES_UNAVAILABLE"

    def assert_safe_warning(self, result, status):
        self.assertEqual(result["business_managers"], [])
        self.assertEqual(len(result["discovery_warnings"]), 1)
        warning = result["discovery_warnings"][0]
        self.assertEqual((warning["code"], warning["status"]), (self.WARNING_CODE, status))
        # Texto fixo: nem a mensagem bruta da Meta nem token chegam ao usuário.
        self.assertNotIn("Requires business_management", warning["message"])
        self.assertNotIn("Meta API error", warning["message"])
        self.assertNotIn(TOKEN, warning["message"])

    async def test_me_businesses_denied_still_delivers_direct_ad_accounts(self):
        result, logs, graph = await self.discover(base_routes(**{
            "/me/adaccounts": {"data": [{"id": f"act_{MUGO_AD_ACCOUNT}", "name": "Mugô Ads"}]},
            "/me/businesses": permission_denied(),
        }))
        account = self.ads_by_id(result)[f"act_{MUGO_AD_ACCOUNT}"]
        self.assertEqual(account["discovery_sources"], ["me_adaccounts"])
        self.assertEqual(account["access_status"], meta_oauth.ACCESS_ACCESSIBLE)
        self.assert_safe_warning(result, "permission_denied")
        # Sem Businesses, nenhum edge é consultado.
        self.assertFalse([path for path in graph.paths if "owned_" in path or "client_" in path])
        self.assertIn("stage=graph_call_failed call=me_businesses http_status=403", logs)
        self.assertIn("stage=me_businesses_unavailable status=permission_denied", logs)
        self.assertIn("trace_id=trace-abc", logs)
        self.assertIn("fallback=direct_assets", logs)

    async def test_me_businesses_error_still_delivers_direct_pages_and_instagram(self):
        page = {"id": MUGO_PAGE, "name": "Mugô", "instagram_business_account": {"id": MUGO_INSTAGRAM, "username": "mugo"}}
        result, logs, _graph = await self.discover(base_routes(**{
            "/me/accounts": {"data": [page]},
            f"/{MUGO_PAGE}": page,
            "/me/businesses": MetaApiError("Meta API error 500: unknown", status_code=500, error_code=1),
        }))
        self.assertEqual([row["page_id"] for row in result["pages"]], [MUGO_PAGE])
        self.assertEqual(result["pages"][0]["access_status"], meta_oauth.ACCESS_ACCESSIBLE)
        self.assertEqual(
            [(ig["ig_user_id"], ig["business_id"]) for ig in result["instagram_accounts"]],
            [(MUGO_INSTAGRAM, MUGO_PAGE)],
        )
        self.assert_safe_warning(result, "error")
        self.assertIn("stage=assets", logs)

    async def test_me_businesses_working_keeps_full_expansion_without_warning(self):
        result, _logs, graph = await self.discover(base_routes(**{
            "/me/businesses": {"data": [{"id": "biz-a", "name": "A"}]},
            "/biz-a/owned_ad_accounts": {"data": [{"id": "act_owned"}]},
            "/biz-a/client_ad_accounts": {"data": [{"id": "act_client"}]},
            "/biz-a/owned_pages": {"data": []}, "/biz-a/client_pages": {"data": []},
            "/act_owned": {"id": "act_owned"}, "/act_client": {"id": "act_client"},
        }))
        self.assertEqual(result["discovery_warnings"], [])
        self.assertEqual(sorted(self.ads_by_id(result)), ["act_client", "act_owned"])
        for edge in ("owned_ad_accounts", "client_ad_accounts", "owned_pages", "client_pages"):
            self.assertIn(f"/biz-a/{edge}", graph.paths)

    async def test_me_businesses_with_invalid_token_is_still_fatal(self):
        invalid = MetaApiError("Meta API error 401: Error validating access token", status_code=401, error_code=190, invalid_oauth=True)
        with self.assertRaises(MetaApiError) as raised:
            await self.discover(base_routes(**{
                "/me/adaccounts": {"data": [{"id": "act_1"}]},
                "/me/businesses": invalid,
            }))
        self.assertIs(raised.exception, invalid)


class PaginationTests(_DiscoveryCase):
    async def test_business_edges_follow_paging(self):
        result, _logs, _graph = await self.discover(base_routes(**{
            "/me/businesses": {"data": [{"id": "biz-a", "name": "A"}]},
            "/biz-a/owned_ad_accounts": {"data": [{"id": "act_p1"}], "paging": {"next": "https://graph.example/biz-a/owned?after=1"}},
            "https://graph.example/biz-a/owned?after=1": {"data": [{"id": "act_p2"}]},
            "/biz-a/client_ad_accounts": {"data": []},
            "/biz-a/owned_pages": {"data": []}, "/biz-a/client_pages": {"data": []},
            "/act_p1": {"id": "act_p1"}, "/act_p2": {"id": "act_p2"},
        }))
        self.assertEqual([row["ad_account_id"] for row in result["ad_accounts"]], ["act_p1", "act_p2"])

    async def test_pagination_stops_at_the_limit_without_extra_request(self):
        graph = FakeGraph({
            "/biz/edge": {"data": [{"id": "1"}], "paging": {"next": "next-1"}},
            "next-1": {"data": [{"id": "2"}], "paging": {"next": "next-2"}},
            "next-2": {"data": [{"id": "3"}]},
        })
        with (
            patch.object(meta_oauth, "_BUSINESS_EDGE_MAX_PAGES", 2),
            patch.object(meta_oauth, "_meta_get", AsyncMock(side_effect=graph.meta_get)),
            patch.object(meta_oauth, "meta_get_json", AsyncMock(side_effect=graph.meta_get_json)),
            redirect_stdout(io.StringIO()),
        ):
            rows = await meta_oauth._graph_paged("/biz/edge", {"access_token": TOKEN}, resource="test")
        self.assertEqual([row["id"] for row in rows], ["1", "2"])
        self.assertNotIn("next-2", graph.paths)


class PageAndInstagramDiscoveryTests(_DiscoveryCase):
    async def test_10_page_discovered_directly(self):
        page = {"id": MUGO_PAGE, "name": "Mugô", "instagram_business_account": {"id": MUGO_INSTAGRAM, "username": "mugo"}}
        result, _logs, _graph = await self.discover(base_routes(**{
            "/me/accounts": {"data": [page]},
            f"/{MUGO_PAGE}": page,
        }))
        found = next(row for row in result["pages"] if row["page_id"] == MUGO_PAGE)
        self.assertEqual(found["discovery_sources"], ["me_accounts"])
        self.assertEqual(found["access_status"], meta_oauth.ACCESS_ACCESSIBLE)
        self.assertEqual(
            [(ig["ig_user_id"], ig["business_id"]) for ig in result["instagram_accounts"]],
            [(MUGO_INSTAGRAM, MUGO_PAGE)],
        )

    async def test_11_12_page_discovered_via_business_uses_real_page_link(self):
        page_detail = {
            "id": "page-biz", "name": "Página do Business",
            "connected_instagram_account": {"id": "ig-biz", "username": "marca_oficial"},
        }
        result, logs, _graph = await self.discover(base_routes(**{
            "/me/businesses": {"data": [{"id": "biz-a", "name": "A"}]},
            "/biz-a/owned_ad_accounts": {"data": []}, "/biz-a/client_ad_accounts": {"data": []},
            "/biz-a/owned_pages": {"data": [{"id": "page-biz", "name": "Página do Business"}]},
            "/biz-a/client_pages": {"data": []},
            "/page-biz": page_detail,
        }))
        page = next(row for row in result["pages"] if row["page_id"] == "page-biz")
        self.assertEqual(page["discovery_sources"], ["business_owned"])
        self.assertEqual(page["businesses"][0]["business_id"], "biz-a")
        self.assertEqual(page["access_status"], meta_oauth.ACCESS_ACCESSIBLE)
        ig = result["instagram_accounts"][0]
        self.assertEqual((ig["ig_user_id"], ig["business_id"]), ("ig-biz", "page-biz"))
        self.assertIn("stage=page_access page_id=page-biz access=accessible sources=business_owned instagram_id=ig-biz", logs)

    async def test_13_page_without_instagram_link_gets_no_instagram(self):
        # Nome/username parecidos não criam vínculo: só os campos da Página.
        result, _logs, _graph = await self.discover(base_routes(**{
            "/me/accounts": {"data": [{"id": "page-a", "name": "Marca", "instagram_business_account": {"id": "ig-a", "username": "marca"}}]},
            "/page-a": {"id": "page-a", "name": "Marca", "instagram_business_account": {"id": "ig-a", "username": "marca"}},
            "/me/businesses": {"data": [{"id": "biz-a", "name": "A"}]},
            "/biz-a/owned_ad_accounts": {"data": []}, "/biz-a/client_ad_accounts": {"data": []},
            "/biz-a/owned_pages": {"data": [{"id": "page-b", "name": "Marca"}]},
            "/biz-a/client_pages": {"data": []},
            "/page-b": {"id": "page-b", "name": "Marca"},
        }))
        self.assertEqual(
            [(ig["ig_user_id"], ig["business_id"]) for ig in result["instagram_accounts"]],
            [("ig-a", "page-a")],
        )
        page_b = next(row for row in result["pages"] if row["page_id"] == "page-b")
        self.assertEqual(page_b["access_status"], meta_oauth.ACCESS_ACCESSIBLE)

    async def test_page_seen_directly_and_by_business_appears_once(self):
        page = {"id": "page-a", "name": "Marca", "instagram_business_account": {"id": "ig-a", "username": "marca"}}
        result, _logs, graph = await self.discover(base_routes(**{
            "/me/accounts": {"data": [page]},
            "/page-a": page,
            "/me/businesses": {"data": [{"id": "biz-a", "name": "A"}]},
            "/biz-a/owned_ad_accounts": {"data": []}, "/biz-a/client_ad_accounts": {"data": []},
            "/biz-a/owned_pages": {"data": [{"id": "page-a", "name": "Marca"}]},
            "/biz-a/client_pages": {"data": [{"id": "page-a", "name": "Marca"}]},
        }))
        pages = [row for row in result["pages"] if row["page_id"] == "page-a"]
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["discovery_sources"], ["me_accounts", "business_owned", "business_client"])
        self.assertEqual(len(result["instagram_accounts"]), 1)
        # Página direta já tem detalhe: nenhuma verificação extra além da existente.
        self.assertEqual(graph.paths.count("/page-a"), 1)


class MugoRegressionTests(_DiscoveryCase):
    async def test_known_mugo_assets_keep_working(self):
        page = {"id": MUGO_PAGE, "name": "Mugô", "instagram_business_account": {"id": MUGO_INSTAGRAM, "username": "mugo"}}
        result, _logs, _graph = await self.discover(base_routes(**{
            "/me/accounts": {"data": [page]},
            f"/{MUGO_PAGE}": page,
            "/me/adaccounts": {"data": [{"id": f"act_{MUGO_AD_ACCOUNT}", "name": "Mugô Ads"}]},
            "/me/businesses": {"data": [{"id": MUGO_BUSINESS, "name": "Mugô"}]},
            f"/{MUGO_BUSINESS}/owned_ad_accounts": {"data": [{"id": f"act_{MUGO_AD_ACCOUNT}", "name": "Mugô Ads"}]},
            f"/{MUGO_BUSINESS}/client_ad_accounts": {"data": []},
            f"/{MUGO_BUSINESS}/owned_pages": {"data": [{"id": MUGO_PAGE, "name": "Mugô"}]},
            f"/{MUGO_BUSINESS}/client_pages": {"data": []},
        }))
        self.assertEqual([row["ad_account_id"] for row in result["ad_accounts"]], [f"act_{MUGO_AD_ACCOUNT}"])
        self.assertEqual(result["ad_accounts"][0]["access_status"], meta_oauth.ACCESS_ACCESSIBLE)
        self.assertEqual([row["page_id"] for row in result["pages"]], [MUGO_PAGE])
        self.assertEqual([ig["ig_user_id"] for ig in result["instagram_accounts"]], [MUGO_INSTAGRAM])
        self.assertEqual(result["instagram_accounts"][0]["business_id"], MUGO_PAGE)
        self.assertEqual(result["business_managers"][0]["business_id"], MUGO_BUSINESS)


def handoff_row(*, client_id="ruah", user_id="user-ruah", ad_accounts=None, pages=None, instagram=None):
    return {
        "handoff": "handoff-ruah", "user_id": user_id, "client_id": client_id,
        "encrypted_access_token": "encrypted", "expires_at": None,
        "meta_user_json": {"id": "meta-user-1", "name": "Pessoa Autorizada", "business_managers": [
            {"business_id": RUAH_BUSINESS, "business_name": "RÜAH", "discovery": {"owned_ad_accounts": {"status": "ok", "count": 1}}},
        ]},
        "pages_json": pages or [],
        "instagram_accounts_json": instagram or [],
        "ad_accounts_json": ad_accounts if ad_accounts is not None else [{
            "ad_account_id": f"act_{RUAH_AD_ACCOUNT}", "ad_account_name": "RÜAH Ads",
            "discovery_sources": ["business_owned"], "access_status": "accessible",
            "businesses": [{"business_id": RUAH_BUSINESS, "business_name": "RÜAH", "relation": "owned"}],
        }],
        "scopes_json": ["ads_read", "business_management"],
    }


class SelectionAndTenantTests(unittest.IsolatedAsyncioTestCase):
    def patch_db(self, stack, row):
        writes = []

        async def select(table, filters=None, **_kwargs):
            return []

        async def insert(table, data, **_kwargs):
            writes.append(("insert", table, dict(data)))
            return {"id": f"{table}-new", **data}

        async def update(table, filters=None, patch=None, **_kwargs):
            writes.append(("update", table, dict(filters or {}), dict(patch or {})))
            return [{"id": "updated"}]

        upsert = AsyncMock(return_value={"id": "generic-meta"})
        stack.enter_context(patch.object(meta_oauth, "_load_handoff_row", AsyncMock(return_value=row)))
        stack.enter_context(patch.object(meta_oauth, "decrypt_secret", return_value="decrypted-token"))
        stack.enter_context(patch.object(meta_oauth, "encrypt_secret", return_value="encrypted"))
        stack.enter_context(patch.object(meta_oauth, "sb_select", AsyncMock(side_effect=select)))
        stack.enter_context(patch.object(meta_oauth, "sb_insert", AsyncMock(side_effect=insert)))
        stack.enter_context(patch.object(meta_oauth, "sb_update", AsyncMock(side_effect=update)))
        stack.enter_context(patch.object(meta_oauth, "upsert_connection", upsert))
        stack.enter_context(patch.object(meta_oauth, "invalidate_namespace", AsyncMock()))
        return writes, upsert

    async def test_15_handoff_of_one_tenant_never_writes_in_another(self):
        with ExitStack() as stack:
            writes, upsert = self.patch_db(stack, handoff_row(client_id="ruah"))
            for other in ("curavino", "mugo", "origami", "roove"):
                with self.assertRaisesRegex(RuntimeError, "cliente"):
                    await meta_oauth.save_connections(
                        user_id="user-ruah", client_id=other, handoff="handoff-ruah",
                        page_ids=[], instagram_ig_user_ids=[], ad_account_ids=[f"act_{RUAH_AD_ACCOUNT}"],
                    )
        self.assertEqual(writes, [])
        upsert.assert_not_awaited()

    async def test_16_explicit_selection_is_required_before_persisting(self):
        with ExitStack() as stack:
            writes, upsert = self.patch_db(stack, handoff_row())
            with self.assertRaisesRegex(RuntimeError, "Selecione ao menos um ativo"):
                await meta_oauth.save_connections(
                    user_id="user-ruah", client_id="ruah", handoff="handoff-ruah",
                    page_ids=[], instagram_ig_user_ids=[], ad_account_ids=[],
                )
        self.assertEqual(writes, [])
        upsert.assert_not_awaited()

    async def test_17_selected_business_account_is_saved_only_in_current_tenant(self):
        with ExitStack() as stack:
            writes, upsert = self.patch_db(stack, handoff_row())
            result = await meta_oauth.save_connections(
                user_id="user-ruah", client_id="ruah", handoff="handoff-ruah",
                page_ids=[], instagram_ig_user_ids=[], ad_account_ids=[RUAH_AD_ACCOUNT],
            )
        inserts = [write for write in writes if write[0] == "insert"]
        self.assertEqual(len(inserts), 1)
        _kind, table, row = inserts[0]
        self.assertEqual(table, "meta_connections")
        self.assertEqual(row["client_id"], "ruah")
        self.assertEqual(row["ad_account_id"], f"act_{RUAH_AD_ACCOUNT}")
        for write in writes:
            if write[0] == "update" and write[1] != "meta_oauth_handoffs":
                self.assertEqual(write[2].get("client_id"), "eq.ruah")
        self.assertEqual(upsert.await_args.kwargs["client_id"], "ruah")
        metadata = upsert.await_args.kwargs["metadata"]
        self.assertEqual(metadata["selected_ad_account_id"], f"act_{RUAH_AD_ACCOUNT}")
        self.assertEqual(result["connections"][0]["ad_account_id"], f"act_{RUAH_AD_ACCOUNT}")

    async def test_restricted_account_is_not_saved(self):
        restricted = [{
            "ad_account_id": f"act_{RUAH_AD_ACCOUNT}", "ad_account_name": "RÜAH Ads",
            "discovery_sources": ["business_owned"], "access_status": "restricted",
        }, {"ad_account_id": "act_ok", "ad_account_name": "Ok", "access_status": "accessible"}]
        with ExitStack() as stack:
            writes, upsert = self.patch_db(stack, handoff_row(ad_accounts=restricted))
            with self.assertRaises(IntegrationError) as raised:
                await meta_oauth.save_connections(
                    user_id="user-ruah", client_id="ruah", handoff="handoff-ruah",
                    page_ids=[], instagram_ig_user_ids=[], ad_account_ids=[f"act_{RUAH_AD_ACCOUNT}"],
                )
        self.assertEqual(raised.exception.code, "META_ASSET_ACCESS_RESTRICTED")
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(writes, [])
        upsert.assert_not_awaited()

    async def test_restricted_accounts_are_not_listed_as_accessible(self):
        accounts = [
            {"ad_account_id": "act_ok", "ad_account_name": "Ok", "access_status": "accessible"},
            {"ad_account_id": "act_blocked", "ad_account_name": "Bloqueada", "access_status": "restricted"},
        ]
        with ExitStack() as stack:
            _writes, upsert = self.patch_db(stack, handoff_row(ad_accounts=accounts))
            await meta_oauth.save_connections(
                user_id="user-ruah", client_id="ruah", handoff="handoff-ruah",
                page_ids=[], instagram_ig_user_ids=[], ad_account_ids=["act_ok"],
            )
        listed = [row["ad_account_id"] for row in upsert.await_args.kwargs["metadata"]["accessible_ad_accounts"]]
        self.assertEqual(listed, ["act_ok"])

    async def test_handoff_read_keeps_origin_and_access_for_the_selector(self):
        row = handoff_row(pages=[{
            "page_id": "page-ruah", "page_name": "RÜAH", "discovery_sources": ["business_owned"],
            "businesses": [{"business_id": RUAH_BUSINESS, "business_name": "RÜAH", "relation": "owned"}],
            "access_status": "restricted",
        }])
        with patch.object(meta_oauth, "_load_handoff_row", AsyncMock(return_value=row)):
            result = await meta_oauth.read_discovery_handoff(handoff="handoff-ruah", user_id="user-ruah", client_id="ruah")
        page = result["pages"][0]
        self.assertEqual(page["access_status"], "restricted")
        self.assertEqual(page["businesses"][0]["business_id"], RUAH_BUSINESS)
        self.assertEqual(result["business_managers"][0]["discovery"]["owned_ad_accounts"]["status"], "ok")
        self.assertEqual(result["ad_accounts"][0]["discovery_sources"], ["business_owned"])
        with patch.object(meta_oauth, "_load_handoff_row", AsyncMock(return_value=row)):
            with self.assertRaisesRegex(RuntimeError, "cliente"):
                await meta_oauth.read_discovery_handoff(handoff="handoff-ruah", user_id="user-ruah", client_id="curavino")


class OrganicReconfigurationTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_connection_also_lists_business_pages_without_touching_ads(self):
        connection = {
            "provider": "meta", "status": "connected",
            "scopes": ["pages_show_list", "pages_read_engagement", "instagram_basic", "business_management"],
            "_token": '{"access_token": "%s"}' % TOKEN,
        }
        graph = FakeGraph(base_routes(**{
            "/me/businesses": {"data": [{"id": "biz-a", "name": "A"}]},
            "/biz-a/owned_pages": {"data": [{"id": "page-biz", "name": "Página"}]},
            "/biz-a/client_pages": {"data": []},
            "/page-biz": {"id": "page-biz", "name": "Página", "instagram_business_account": {"id": "ig-biz", "username": "marca"}},
        }))
        create = AsyncMock(return_value="handoff-x")
        output = io.StringIO()
        with (
            patch.object(meta_oauth, "get_connection", AsyncMock(return_value=connection)),
            patch.object(meta_oauth, "_meta_get", AsyncMock(side_effect=graph.meta_get)),
            patch.object(meta_oauth, "meta_get_json", AsyncMock(side_effect=graph.meta_get_json)),
            patch.object(meta_oauth, "create_discovery_handoff", create),
            patch.object(meta_oauth, "read_discovery_handoff", AsyncMock(return_value={"pages": [{"page_id": "page-biz"}], "instagram_accounts": [{"ig_user_id": "ig-biz"}]})),
            redirect_stdout(output),
        ):
            await meta_oauth.discover_existing_meta_organic_assets(user_id="u", client_id="ruah", connection_id="meta-1")
        discovered = create.await_args.kwargs["discovered"]
        self.assertEqual(discovered["ad_accounts"], [])
        self.assertNotIn("/biz-a/owned_ad_accounts", graph.paths)
        self.assertEqual([ig["ig_user_id"] for ig in discovered["instagram_accounts"]], ["ig-biz"])
        self.assertEqual(create.await_args.kwargs["client_id"], "ruah")
        self.assertNotIn(TOKEN, output.getvalue())

    async def test_existing_connection_without_me_businesses_keeps_direct_pages(self):
        connection = {
            "provider": "meta", "status": "connected",
            "scopes": ["pages_show_list", "pages_read_engagement", "instagram_basic"],
            "_token": '{"access_token": "%s"}' % TOKEN,
        }
        page = {"id": "page-direta", "name": "Marca", "instagram_business_account": {"id": "ig-direto", "username": "marca"}}
        graph = FakeGraph(base_routes(**{
            "/me/accounts": {"data": [page]},
            "/page-direta": page,
            "/me/businesses": permission_denied(),
        }))
        create = AsyncMock(return_value="handoff-x")
        output = io.StringIO()
        with (
            patch.object(meta_oauth, "get_connection", AsyncMock(return_value=connection)),
            patch.object(meta_oauth, "_meta_get", AsyncMock(side_effect=graph.meta_get)),
            patch.object(meta_oauth, "meta_get_json", AsyncMock(side_effect=graph.meta_get_json)),
            patch.object(meta_oauth, "create_discovery_handoff", create),
            patch.object(meta_oauth, "read_discovery_handoff", AsyncMock(return_value={"pages": [{"page_id": "page-direta"}], "instagram_accounts": [{"ig_user_id": "ig-direto"}]})),
            redirect_stdout(output),
        ):
            await meta_oauth.discover_existing_meta_organic_assets(user_id="u", client_id="ruah", connection_id="meta-1")
        discovered = create.await_args.kwargs["discovered"]
        self.assertEqual([row["page_id"] for row in discovered["pages"]], ["page-direta"])
        self.assertEqual([ig["ig_user_id"] for ig in discovered["instagram_accounts"]], ["ig-direto"])
        self.assertEqual(discovered["business_managers"], [])
        self.assertEqual(discovered["discovery_warnings"][0]["code"], "META_BUSINESSES_UNAVAILABLE")
        self.assertNotIn(TOKEN, output.getvalue())


class DiscoveryWarningHandoffTests(unittest.IsolatedAsyncioTestCase):
    async def test_safe_warning_travels_in_the_handoff_without_schema_change(self):
        warning = {"code": "META_BUSINESSES_UNAVAILABLE", "status": "permission_denied", "message": "Aviso seguro."}
        insert = AsyncMock()
        with (
            patch.object(meta_oauth, "_cleanup_handoffs", AsyncMock()),
            patch.object(meta_oauth, "encrypt_secret", return_value="encrypted"),
            patch.object(meta_oauth, "sb_insert", insert),
        ):
            await meta_oauth.create_discovery_handoff(
                user_id="user-ruah", client_id="ruah", access_token=TOKEN, expires_at=None,
                discovered={"meta_user": {"id": "meta-user-1"}, "ad_accounts": [{"ad_account_id": "act_1"}],
                            "business_managers": [], "discovery_warnings": [warning]},
            )
        row = insert.await_args.args[1]
        # Mesmas colunas de antes; o aviso vai no JSON já existente de meta_user.
        self.assertEqual(
            sorted(row),
            sorted(["handoff", "user_id", "client_id", "encrypted_access_token", "expires_at", "meta_user_json",
                    "instagram_accounts_json", "pages_json", "ad_accounts_json", "scopes_json"]),
        )
        self.assertEqual(row["meta_user_json"]["discovery_warnings"], [warning])
        self.assertNotIn(TOKEN, str(row))
        with patch.object(meta_oauth, "_load_handoff_row", AsyncMock(return_value=row)):
            result = await meta_oauth.read_discovery_handoff(handoff=row["handoff"], user_id="user-ruah", client_id="ruah")
        self.assertEqual(result["discovery_warnings"], [warning])

    async def test_handoff_without_warning_keeps_previous_row(self):
        insert = AsyncMock()
        with (
            patch.object(meta_oauth, "_cleanup_handoffs", AsyncMock()),
            patch.object(meta_oauth, "encrypt_secret", return_value="encrypted"),
            patch.object(meta_oauth, "sb_insert", insert),
        ):
            await meta_oauth.create_discovery_handoff(
                user_id="u", client_id="ruah", access_token=TOKEN, expires_at=None,
                discovered={"meta_user": {"id": "meta-user-1"}, "business_managers": [], "discovery_warnings": []},
            )
        row = insert.await_args.args[1]
        self.assertNotIn("discovery_warnings", row["meta_user_json"])
        with patch.object(meta_oauth, "_load_handoff_row", AsyncMock(return_value=row)):
            result = await meta_oauth.read_discovery_handoff(handoff=row["handoff"], user_id="u", client_id="ruah")
        self.assertEqual(result["discovery_warnings"], [])


def ruah_routes(**overrides):
    """Estrutura real da RÜAH (fixture): Business com a conta em client e a
    conta Mugô vindo direto; owned do Business negado por permissão."""
    return base_routes(**{
        "/me/adaccounts": {"data": [{"id": f"act_{MUGO_AD_ACCOUNT}", "name": "Mugô Ads"}]},
        "/me/businesses": {"data": [{"id": RUAH_BUSINESS, "name": "RŪAH"}]},
        f"/{RUAH_BUSINESS}/owned_ad_accounts": permission_denied(),
        f"/{RUAH_BUSINESS}/client_ad_accounts": {"data": [{"id": f"act_{RUAH_AD_ACCOUNT}", "name": "RŪAH Ads"}]},
        f"/{RUAH_BUSINESS}/owned_pages": {"data": []},
        f"/{RUAH_BUSINESS}/client_pages": {"data": []},
        f"/act_{RUAH_AD_ACCOUNT}": {"id": f"act_{RUAH_AD_ACCOUNT}", "name": "RŪAH Ads"},
        **overrides,
    })


class AdAccountDecisionLogTests(_DiscoveryCase):
    """Cada conta recebe uma linha final: origem, Business, restrita, selecionável e motivo."""

    async def test_direct_and_business_client_accounts_each_get_a_selectable_result(self):
        result, logs, _graph = await self.discover(ruah_routes())
        accounts = self.ads_by_id(result)
        # code=200 no owned não remove nem a conta direta nem a do client.
        self.assertEqual(sorted(accounts), sorted([f"act_{MUGO_AD_ACCOUNT}", f"act_{RUAH_AD_ACCOUNT}"]))
        self.assertIn(f"endpoint=me_adaccounts http_status=200 count=1 ids=act_{MUGO_AD_ACCOUNT}", logs)
        self.assertIn(
            f"stage=ad_account_result ad_account_id=act_{MUGO_AD_ACCOUNT} sources=me_adaccounts businesses=- "
            "account_status=None access=accessible restricted=false selectable=true reason=direct_access",
            logs,
        )
        self.assertIn(
            f"stage=ad_account_result ad_account_id=act_{RUAH_AD_ACCOUNT} sources=business_client "
            f"businesses={RUAH_BUSINESS}:client account_status=None access=accessible restricted=false "
            "selectable=true reason=business_detail_ok",
            logs,
        )
        self.assertIn(f"stage=business_edge_failed business_id={RUAH_BUSINESS} edge=owned_ad_accounts", logs)

    async def test_restricted_account_is_logged_as_not_selectable_with_reason(self):
        _result, logs, _graph = await self.discover(ruah_routes(**{
            f"/act_{RUAH_AD_ACCOUNT}": permission_denied(code=100, subcode=33, status=400),
        }))
        self.assertIn(
            f"ad_account_id=act_{RUAH_AD_ACCOUNT} sources=business_client businesses={RUAH_BUSINESS}:client "
            "account_status=None access=restricted restricted=true selectable=false "
            "reason=business_detail_permission_denied",
            logs,
        )

    async def test_dedupe_keeps_the_usable_direct_version_of_the_same_account(self):
        # A mesma conta vem direto (utilizável) e pelo Business; o detalhe
        # negado do Business não pode rebaixá-la para restrita.
        result, logs, graph = await self.discover(ruah_routes(**{
            "/me/adaccounts": {"data": [{"id": f"act_{RUAH_AD_ACCOUNT}", "name": "RŪAH Ads"}]},
            f"/act_{RUAH_AD_ACCOUNT}": permission_denied(code=100, subcode=33, status=400),
        }))
        account = self.ads_by_id(result)[f"act_{RUAH_AD_ACCOUNT}"]
        self.assertEqual(account["access_status"], meta_oauth.ACCESS_ACCESSIBLE)
        self.assertEqual(account["discovery_sources"], ["me_adaccounts", "business_client"])
        self.assertNotIn(f"/act_{RUAH_AD_ACCOUNT}", graph.paths)
        self.assertIn("reason=direct_access", logs)

    async def test_logs_carry_tenant_and_request_id_when_the_route_sets_them(self):
        meta_oauth.set_discovery_log_context(client_id="ruah", request_id="req-123")
        _result, logs, _graph = await self.discover(ruah_routes())
        self.assertIn(
            f"stage=ad_account_result client_id=ruah request_id=req-123 ad_account_id=act_{RUAH_AD_ACCOUNT}",
            logs,
        )
        self.assertIn("[meta_oauth][ad_accounts] client_id=ruah request_id=req-123 endpoint=me_adaccounts", logs)


class ExistingConnectionAdDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    """Conexão já salva (Instagram conectado, Meta Ads pendente): relistar as
    contas pela autorização atual, sem nova OAuth e sem gravar nada."""

    CONNECTION = {
        "provider": "meta", "status": "connected", "token_expires_at": None,
        "scopes": ["ads_read", "business_management", "pages_show_list"],
        "_token": '{"access_token": "%s"}' % TOKEN,
        "metadata": {"selected_instagram_id": "ig-ruah"},
    }

    async def rediscover(self, routes):
        graph = FakeGraph(routes)
        create = AsyncMock(return_value="handoff-novo")
        output = io.StringIO()
        with (
            patch.object(meta_oauth, "get_meta_oauth_settings", side_effect=RuntimeError("sem credenciais no teste")),
            patch.object(meta_oauth, "get_connection", AsyncMock(return_value=self.CONNECTION)),
            patch.object(meta_oauth, "_meta_get", AsyncMock(side_effect=graph.meta_get)),
            patch.object(meta_oauth, "meta_get_json", AsyncMock(side_effect=graph.meta_get_json)),
            patch.object(meta_oauth, "create_discovery_handoff", create),
            patch.object(meta_oauth, "read_discovery_handoff", AsyncMock(side_effect=lambda **kw: {
                "handoff": kw["handoff"], "client_id": kw["client_id"],
                "ad_accounts": create.await_args.kwargs["discovered"]["ad_accounts"],
            })),
            patch.object(meta_oauth, "sb_insert", AsyncMock()) as insert,
            patch.object(meta_oauth, "sb_update", AsyncMock()) as update,
            redirect_stdout(output),
        ):
            result = await meta_oauth.discover_existing_meta_ad_accounts(
                user_id="user-ruah", client_id="ruah", connection_id="meta-ruah",
            )
        insert.assert_not_awaited()
        update.assert_not_awaited()
        self.assertNotIn(TOKEN, output.getvalue())
        return result, create, output.getvalue(), graph

    async def test_lists_direct_owned_and_client_accounts_with_the_saved_authorization(self):
        result, create, logs, graph = await self.rediscover(ruah_routes(**{
            f"/{RUAH_BUSINESS}/owned_ad_accounts": {"data": [{"id": "act_owned", "name": "Owned"}]},
            "/act_owned": {"id": "act_owned"},
        }))
        ids = sorted(row["ad_account_id"] for row in result["ad_accounts"])
        self.assertEqual(ids, sorted([f"act_{MUGO_AD_ACCOUNT}", f"act_{RUAH_AD_ACCOUNT}", "act_owned"]))
        self.assertIn("/me/adaccounts", graph.paths)
        self.assertIn(f"/{RUAH_BUSINESS}/owned_ad_accounts", graph.paths)
        self.assertIn(f"/{RUAH_BUSINESS}/client_ad_accounts", graph.paths)
        # Handoff no tenant atual; nada gravado antes da seleção explícita.
        self.assertEqual(create.await_args.kwargs["client_id"], "ruah")
        self.assertEqual(result["client_id"], "ruah")
        self.assertIn("stage=existing_ad_discovery", logs)
        self.assertIn(f"act_{RUAH_AD_ACCOUNT}", logs)

    async def test_business_code_200_keeps_direct_account(self):
        result, _create, _logs, _graph = await self.rediscover(ruah_routes(**{
            f"/{RUAH_BUSINESS}/client_ad_accounts": permission_denied(),
        }))
        self.assertEqual([row["ad_account_id"] for row in result["ad_accounts"]], [f"act_{MUGO_AD_ACCOUNT}"])

    async def test_invalid_token_requires_reauthorization(self):
        invalid = MetaApiError("Meta API error 401: Error validating access token", status_code=401, error_code=190, invalid_oauth=True)
        with self.assertRaises(IntegrationError) as raised:
            await self.rediscover(ruah_routes(**{"/me/adaccounts": invalid}))
        self.assertEqual(raised.exception.code, "META_REAUTH_REQUIRED")
        self.assertEqual(raised.exception.status_code, 401)

    async def test_missing_ads_permission_is_reported_not_treated_as_invalid_token(self):
        with self.assertRaises(IntegrationError) as raised:
            await self.rediscover(ruah_routes(**{"/me/adaccounts": permission_denied("(#200) Requires ads_read")}))
        self.assertEqual(raised.exception.code, "META_PERMISSION_MISSING")
        self.assertEqual(raised.exception.status_code, 403)

    async def test_disconnected_connection_is_refused_before_calling_meta(self):
        graph = FakeGraph(ruah_routes())
        with (
            patch.object(meta_oauth, "get_connection", AsyncMock(return_value={**self.CONNECTION, "status": "disconnected"})),
            patch.object(meta_oauth, "_meta_get", AsyncMock(side_effect=graph.meta_get)),
        ):
            with self.assertRaises(IntegrationError) as raised:
                await meta_oauth.discover_existing_meta_ad_accounts(
                    user_id="user-ruah", client_id="ruah", connection_id="meta-ruah",
                )
        self.assertEqual(raised.exception.code, "META_CONNECTION_DISCONNECTED")
        self.assertEqual(graph.paths, [])


class AdsOnlySelectionTests(unittest.IsolatedAsyncioTestCase):
    """Selecionar só a conta de anúncios grava o ad_account_id e preserva o orgânico."""

    PREVIOUS_GENERIC = {
        "id": "generic-meta", "client_id": "ruah", "provider": "meta", "status": "connected",
        "metadata": {
            "page_ids": ["page-ruah"], "instagram_ig_user_ids": ["ig-ruah"],
            "selected_page_id": "page-ruah", "selected_page_name": "ruah.joias",
            "selected_instagram_id": "ig-ruah", "selected_instagram_username": "ruah_parfums",
            "organic_status": "connected", "organic_connection_id": "organic-1",
            "ads_status": "asset_required", "selected_ad_account_id": None,
        },
    }

    async def save(self, *, ad_account_ids, instagram_ids=(), page_ids=(), previous=None):
        writes = []

        async def select(table, filters=None, **_kwargs):
            if table == "integration_connections":
                return [previous or self.PREVIOUS_GENERIC]
            return []

        async def insert(table, data, **_kwargs):
            writes.append(("insert", table, dict(data)))
            return {"id": f"{table}-new", **data}

        async def update(table, filters=None, patch=None, **_kwargs):
            writes.append(("update", table, dict(filters or {}), dict(patch or {})))
            return [{"id": "updated"}]

        upsert = AsyncMock(return_value={"id": "generic-meta"})
        output = io.StringIO()
        instagram = [{"ig_user_id": "ig-ruah", "username": "ruah_parfums", "business_id": "page-ruah", "business_name": "ruah.joias"}]
        with (
            patch.object(meta_oauth, "_load_handoff_row", AsyncMock(return_value=handoff_row(
                instagram=instagram, pages=[{"page_id": "page-ruah", "page_name": "ruah.joias"}],
            ))),
            patch.object(meta_oauth, "decrypt_secret", return_value="decrypted-token"),
            patch.object(meta_oauth, "encrypt_secret", return_value="encrypted"),
            patch.object(meta_oauth, "sb_select", AsyncMock(side_effect=select)),
            patch.object(meta_oauth, "sb_insert", AsyncMock(side_effect=insert)),
            patch.object(meta_oauth, "sb_update", AsyncMock(side_effect=update)),
            patch.object(meta_oauth, "upsert_connection", upsert),
            patch.object(meta_oauth, "invalidate_namespace", AsyncMock()),
            redirect_stdout(output),
        ):
            await meta_oauth.save_connections(
                user_id="user-ruah", client_id="ruah", handoff="handoff-ruah",
                page_ids=list(page_ids), instagram_ig_user_ids=list(instagram_ids), ad_account_ids=list(ad_account_ids),
            )
        return writes, upsert.await_args.kwargs, output.getvalue()

    async def test_ads_only_selection_persists_the_account_and_keeps_instagram(self):
        writes, upsert_kwargs, logs = await self.save(ad_account_ids=[RUAH_AD_ACCOUNT])
        paid = [w for w in writes if w[0] == "insert" and w[1] == "meta_connections"]
        self.assertEqual(len(paid), 1)
        self.assertEqual(paid[0][2]["platform"], "meta_ads")
        self.assertEqual(paid[0][2]["ad_account_id"], f"act_{RUAH_AD_ACCOUNT}")
        self.assertEqual(paid[0][2]["client_id"], "ruah")
        metadata = upsert_kwargs["metadata"]
        self.assertEqual(metadata["selected_ad_account_id"], f"act_{RUAH_AD_ACCOUNT}")
        self.assertEqual(metadata["ads_status"], "connected")
        # O orgânico já configurado continua lá.
        self.assertEqual(metadata["selected_instagram_id"], "ig-ruah")
        self.assertEqual(metadata["selected_page_id"], "page-ruah")
        self.assertEqual(metadata["instagram_ig_user_ids"], ["ig-ruah"])
        self.assertEqual(metadata["organic_status"], "connected")
        self.assertEqual(metadata["coverage"], "full")
        self.assertEqual(upsert_kwargs["status"], "connected")
        # A projeção orgânica não é tocada.
        self.assertFalse(any(w[1] == "meta_connections" and w[0] == "update" for w in writes))
        self.assertIn(f"stage=selection_saved client_id=ruah ad_account_id=act_{RUAH_AD_ACCOUNT}", logs)
        self.assertIn("instagram_id=ig-ruah instagram_requested=- paid_rows=1", logs)

    async def test_selecting_instagram_still_replaces_the_organic_selection(self):
        _writes, upsert_kwargs, _logs = await self.save(
            ad_account_ids=[RUAH_AD_ACCOUNT], instagram_ids=["ig-ruah"], page_ids=["page-ruah"],
            previous={**self.PREVIOUS_GENERIC, "metadata": {"selected_instagram_id": "ig-antigo", "organic_status": "error"}},
        )
        metadata = upsert_kwargs["metadata"]
        self.assertEqual(metadata["selected_instagram_id"], "ig-ruah")
        self.assertEqual(metadata["selected_instagram_username"], "ruah_parfums")
        self.assertEqual(metadata["organic_status"], "connected")

    async def test_ads_only_selection_without_previous_organic_stays_partial(self):
        _writes, upsert_kwargs, _logs = await self.save(
            ad_account_ids=[RUAH_AD_ACCOUNT],
            previous={"id": "generic-meta", "metadata": {}},
        )
        metadata = upsert_kwargs["metadata"]
        self.assertEqual(metadata["organic_status"], "asset_required")
        self.assertEqual(metadata["coverage"], "partial")
        self.assertNotIn("selected_instagram_id", metadata)


if __name__ == "__main__":
    unittest.main()
