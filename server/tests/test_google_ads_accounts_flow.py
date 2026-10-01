from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Callable, Dict, List
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from routes import google_oauth as google_routes
from services import google_ads, google_oauth
from services.google_ads_ids import format_google_ads_customer_id, normalize_google_ads_customer_id
from services.integration_errors import IntegrationError

ACCESS_TOKEN = "fake-access-token-not-real"
DEVELOPER_TOKEN = "dev-token-secret"
SECRETS = (ACCESS_TOKEN, DEVELOPER_TOKEN, "Bearer ")

MCC = "5550001111"
CURAVINO = "1234567890"
SUB_MCC = "7770001111"
OTHER = "9990001111"


def _json(status: int, body: Any, headers: Dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status, json=body, headers=headers or {},
        request=httpx.Request("POST", "https://googleads.googleapis.com/"),
    )


def _ads_error(
    status: int, error_code: Dict[str, str], message: str = "Google Ads error", request_id: str = "google-req-err",
) -> httpx.Response:
    return _json(status, {
        "error": {
            "code": status,
            "status": "PERMISSION_DENIED" if status == 403 else "INVALID_ARGUMENT",
            "message": message,
            "details": [{
                "@type": "type.googleapis.com/google.ads.googleads.v25.errors.GoogleAdsFailure",
                "errors": [{"errorCode": error_code, "message": message}],
                "requestId": request_id,
            }],
        }
    }, headers={"request-id": request_id})


class FakeAdsHttp:
    """httpx.AsyncClient falso: registra chamadas e responde por handler."""

    def __init__(self, handler: Callable[[str, str, Dict[str, str], Dict[str, Any] | None], httpx.Response]):
        self.handler = handler
        self.calls: List[Dict[str, Any]] = []

    def factory(self, **_kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, *, headers):
        self.calls.append({"method": "GET", "url": url, "headers": dict(headers), "json": None})
        return self.handler("GET", url, dict(headers), None)

    async def post(self, url, *, headers, json):
        self.calls.append({"method": "POST", "url": url, "headers": dict(headers), "json": json})
        return self.handler("POST", url, dict(headers), json)


def _customer_info(customer_id: str, name: str, *, manager: bool = False, status: str = "ENABLED") -> httpx.Response:
    return _json(200, {"results": [{"customer": {
        "id": customer_id, "descriptiveName": name, "currencyCode": "BRL",
        "timeZone": "America/Sao_Paulo", "manager": manager, "testAccount": False, "status": status,
    }}]})


def _customer_clients(rows: List[Dict[str, Any]]) -> httpx.Response:
    return _json(200, {"results": [{"customerClient": row} for row in rows]})


class CustomerIdNormalizationTests(unittest.TestCase):
    def test_canonical_customer_id_forms(self):
        for value in ("1234567890", "123-456-7890", "customers/1234567890", " 123-456-7890 ", 1234567890):
            self.assertEqual(normalize_google_ads_customer_id(value), "1234567890", value)

    def test_invalid_forms_are_rejected_never_repaired(self):
        for value in ("customers/customers/1234567890", "12345", "abc", "", None, "customers/123-456-789", "12345678901"):
            self.assertIsNone(normalize_google_ads_customer_id(value), value)

    def test_display_format(self):
        self.assertEqual(format_google_ads_customer_id("1234567890"), "123-456-7890")


class GoogleAdsListingTests(unittest.IsolatedAsyncioTestCase):
    async def _list(self, handler, *, env: Dict[str, str] | None = None):
        fake = FakeAdsHttp(handler)
        persist = AsyncMock()
        output = io.StringIO()
        environment = {"GOOGLE_ADS_DEVELOPER_TOKEN": DEVELOPER_TOKEN, "GOOGLE_ADS_API_VERSION": "v25"}
        if env is not None:
            environment = env
        with (
            patch.dict(os.environ, environment, clear=False),
            patch.object(google_oauth, "_access_token", AsyncMock(return_value=ACCESS_TOKEN)),
            patch.object(google_oauth, "_persist_google_ads_accounts_cache", persist),
            patch.object(google_oauth.httpx, "AsyncClient", fake.factory),
            redirect_stdout(output),
        ):
            try:
                result = await google_oauth.list_google_ads_accounts("vinhos", "ads-vinhos", request_id="req-1")
                error = None
            except IntegrationError as exc:
                result, error = None, exc
        log = output.getvalue()
        for secret in SECRETS:
            self.assertNotIn(secret, log)
        return result, error, fake, persist, log

    async def test_lists_direct_accounts_with_canonical_ids_and_no_login_header(self):
        def handler(method, url, headers, body):
            if url.endswith("customers:listAccessibleCustomers"):
                return _json(200, {"resourceNames": [f"customers/{CURAVINO}", f"customers/{CURAVINO}", "customers/bad"]})
            if url.endswith(f"customers/{CURAVINO}/googleAds:search"):
                return _customer_info(CURAVINO, "Curavino")
            raise AssertionError(url)

        result, error, fake, persist, log = await self._list(handler)
        self.assertIsNone(error)
        accounts = result["accounts"]
        self.assertEqual(len(accounts), 1)
        account = accounts[0]
        self.assertEqual(account["customer_id"], CURAVINO)
        self.assertEqual(account["resource_name"], f"customers/{CURAVINO}")
        self.assertEqual(account["descriptive_name"], "Curavino")
        self.assertEqual(account["currency_code"], "BRL")
        self.assertEqual(account["time_zone"], "America/Sao_Paulo")
        self.assertEqual(account["status"], "ENABLED")
        self.assertFalse(account["is_manager"])
        self.assertEqual(account["access"], "direct")
        self.assertIsNone(account["login_customer_id"])
        for call in fake.calls:
            self.assertNotIn("login-customer-id", call["headers"])
            self.assertNotIn("customers/customers", call["url"])
        persist.assert_awaited_once()
        self.assertEqual(persist.await_args.kwargs["client_id"], "vinhos")
        self.assertIn("stage=list_accessible_customers", log)
        self.assertIn("customers_count=1", log)
        self.assertIn(f"customer_id={CURAVINO} manager=false status=ENABLED", log)

    async def test_mcc_children_are_listed_with_login_customer_id(self):
        def handler(method, url, headers, body):
            if url.endswith("customers:listAccessibleCustomers"):
                return _json(200, {"resourceNames": [f"customers/{MCC}"]})
            if url.endswith(f"customers/{MCC}/googleAds:search") and "FROM customer_client" in body["query"]:
                return _customer_clients([
                    {"id": MCC, "descriptiveName": "Mugô MCC", "manager": True, "status": "ENABLED", "level": "0"},
                    {"id": CURAVINO, "descriptiveName": "Curavino", "manager": False, "status": "ENABLED",
                     "currencyCode": "BRL", "timeZone": "America/Sao_Paulo", "level": "1"},
                    {"id": SUB_MCC, "descriptiveName": "Sub MCC", "manager": True, "status": "ENABLED", "level": "1"},
                ])
            if url.endswith(f"customers/{SUB_MCC}/googleAds:search") and "FROM customer_client" in body["query"]:
                return _customer_clients([
                    {"id": SUB_MCC, "descriptiveName": "Sub MCC", "manager": True, "level": "0"},
                    {"id": OTHER, "descriptiveName": "Filha da Sub", "manager": False, "status": "ENABLED", "level": "1"},
                ])
            if url.endswith(f"customers/{MCC}/googleAds:search"):
                return _customer_info(MCC, "Mugô MCC", manager=True)
            raise AssertionError(url)

        result, error, fake, _persist, log = await self._list(handler)
        self.assertIsNone(error)
        by_id = {account["customer_id"]: account for account in result["accounts"]}
        self.assertEqual(set(by_id), {MCC, CURAVINO, SUB_MCC, OTHER})
        self.assertTrue(by_id[MCC]["is_manager"])
        self.assertEqual(by_id[MCC]["access"], "direct")
        self.assertIsNone(by_id[MCC]["login_customer_id"])
        self.assertFalse(by_id[CURAVINO]["is_manager"])
        self.assertEqual(by_id[CURAVINO]["access"], "manager")
        self.assertEqual(by_id[CURAVINO]["login_customer_id"], MCC)
        self.assertEqual(by_id[CURAVINO]["manager_customer_id"], MCC)
        self.assertTrue(by_id[SUB_MCC]["is_manager"])
        # Sub-MCC expandida com o login-customer-id da raiz acessível.
        self.assertEqual(by_id[OTHER]["manager_customer_id"], SUB_MCC)
        self.assertEqual(by_id[OTHER]["login_customer_id"], MCC)
        self.assertEqual(by_id[OTHER]["level"], 2)
        hierarchy_calls = [call for call in fake.calls if call["json"] and "FROM customer_client" in call["json"]["query"]]
        self.assertEqual([call["url"].split("/")[-2] for call in hierarchy_calls], [MCC, SUB_MCC])
        for call in hierarchy_calls:
            self.assertEqual(call["headers"]["login-customer-id"], MCC)
            self.assertIn("customer_client.client_customer", call["json"]["query"])
            self.assertIn("customer_client.level <= 1", call["json"]["query"])
        self.assertIn(f"customer_id={CURAVINO} manager=false status=ENABLED access=manager login_customer_id={MCC}", log)

    async def test_direct_access_wins_over_mcc_path(self):
        def handler(method, url, headers, body):
            if url.endswith("customers:listAccessibleCustomers"):
                return _json(200, {"resourceNames": [f"customers/{MCC}", f"customers/{CURAVINO}"]})
            if url.endswith(f"customers/{MCC}/googleAds:search") and "customer_client" in body["query"]:
                return _customer_clients([{"id": CURAVINO, "descriptiveName": "Curavino", "manager": False, "level": "1"}])
            if url.endswith(f"customers/{MCC}/googleAds:search"):
                return _customer_info(MCC, "Mugô MCC", manager=True)
            if url.endswith(f"customers/{CURAVINO}/googleAds:search"):
                return _customer_info(CURAVINO, "Curavino")
            raise AssertionError(url)

        result, _error, _fake, _persist, _log = await self._list(handler)
        curavino = [account for account in result["accounts"] if account["customer_id"] == CURAVINO]
        self.assertEqual(len(curavino), 1)
        self.assertEqual(curavino[0]["access"], "direct")
        self.assertIsNone(curavino[0]["login_customer_id"])

    async def test_mcc_expansion_failure_is_flagged_not_dropped(self):
        def handler(method, url, headers, body):
            if url.endswith("customers:listAccessibleCustomers"):
                return _json(200, {"resourceNames": [f"customers/{MCC}"]})
            if "customer_client" in (body or {}).get("query", ""):
                return _ads_error(403, {"authorizationError": "USER_PERMISSION_DENIED"})
            return _customer_info(MCC, "Mugô MCC", manager=True)

        result, error, _fake, _persist, log = await self._list(handler)
        self.assertIsNone(error)
        self.assertEqual(len(result["accounts"]), 1)
        self.assertEqual(result["accounts"][0]["hierarchy_error"], "USER_PERMISSION_DENIED")
        self.assertEqual(result["accounts"][0]["links_error"], "USER_PERMISSION_DENIED")
        self.assertIn("USER_PERMISSION_DENIED", result["reason"])
        self.assertIn("stage=manager_children", log)
        self.assertIn("stage=manager_links", log)
        self.assertIn("error_code=USER_PERMISSION_DENIED", log)

    async def test_detail_lookup_error_keeps_account_and_reports_code(self):
        def handler(method, url, headers, body):
            if url.endswith("customers:listAccessibleCustomers"):
                return _json(200, {"resourceNames": [f"customers/{CURAVINO}"]})
            return _ads_error(403, {"authorizationError": "DEVELOPER_TOKEN_NOT_APPROVED"})

        result, error, _fake, _persist, log = await self._list(handler)
        self.assertIsNone(error)
        self.assertEqual(result["accounts"][0]["customer_id"], CURAVINO)
        self.assertEqual(result["accounts"][0]["details_error"], "DEVELOPER_TOKEN_NOT_APPROVED")
        self.assertIn("Detalhes da conta 123-456-7890 não puderam ser lidos (HTTP 403, código DEVELOPER_TOKEN_NOT_APPROVED", result["reason"])
        # Erro de detalhe não impede a tentativa de hierarquia (tipo da conta desconhecido).
        self.assertEqual(result["accounts"][0]["hierarchy_error"], "DEVELOPER_TOKEN_NOT_APPROVED")
        self.assertIn("google_request_id=google-req-err", log)

    async def test_empty_listing_is_success_not_error(self):
        result, error, _fake, persist, _log = await self._list(
            lambda method, url, headers, body: _json(200, {})
        )
        self.assertIsNone(error)
        self.assertEqual(result["accounts"], [])
        self.assertIsNone(result["reason"])
        persist.assert_awaited_once()

    async def test_http_errors_raise_sanitized_errors_and_never_become_empty_list(self):
        cases = {
            400: "GOOGLE_BAD_REQUEST",
            401: "GOOGLE_REAUTH_REQUIRED",
            403: "GOOGLE_INSUFFICIENT_SCOPE",
            429: "GOOGLE_RATE_LIMITED",
            500: "GOOGLE_UPSTREAM_ERROR",
            503: "GOOGLE_UNAVAILABLE",
        }
        for status, code in cases.items():
            with self.subTest(status=status):
                result, error, _fake, persist, log = await self._list(
                    lambda method, url, headers, body, status=status: _json(
                        status, {"error": {"code": status, "status": "X", "message": f"falha {status}"}},
                        headers={"request-id": f"google-req-{status}"},
                    )
                )
                self.assertIsNone(result)
                self.assertIsInstance(error, IntegrationError)
                self.assertEqual(error.code, code)
                self.assertEqual(error.diagnostics["upstream_status"], status)
                self.assertEqual(error.diagnostics["google_request_id"], f"google-req-{status}")
                persist.assert_not_awaited()
                self.assertIn(f"http_status={status}", log)
                self.assertIn(f"message=falha {status}", log)

    async def test_developer_token_not_approved_is_explicit(self):
        _result, error, _fake, _persist, _log = await self._list(
            lambda method, url, headers, body: _ads_error(403, {"authorizationError": "DEVELOPER_TOKEN_NOT_APPROVED"})
        )
        self.assertEqual(error.code, "GOOGLE_ADS_DEVELOPER_TOKEN_NOT_APPROVED")
        self.assertEqual(error.status_code, 403)

    async def test_google_ads_api_disabled_in_cloud_project_is_explicit(self):
        response = _json(403, {"error": {
            "code": 403, "status": "PERMISSION_DENIED",
            "message": "Google Ads API has not been used in project 123 before or it is disabled.",
            "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "SERVICE_DISABLED"}],
        }})
        _result, error, _fake, _persist, _log = await self._list(lambda *args: response)
        self.assertEqual(error.code, "GOOGLE_ADS_API_DISABLED")

    async def test_missing_developer_token_blocks_before_any_google_call(self):
        result, error, fake, _persist, log = await self._list(
            lambda *args: _json(200, {}), env={"GOOGLE_ADS_DEVELOPER_TOKEN": "", "GOOGLE_ADS_API_VERSION": "v25"},
        )
        self.assertIsNone(result)
        self.assertEqual(error.code, "GOOGLE_ADS_SETUP_REQUIRED")
        self.assertEqual(error.status_code, 409)
        self.assertEqual(fake.calls, [])
        self.assertIn("developer_token=missing", log)


def _ads_row(*, scopes=None, metadata=None, client_id="vinhos", connection_id="ads-vinhos") -> Dict[str, Any]:
    return {
        "id": connection_id, "client_id": client_id, "provider": "google_ads", "status": "selection_required",
        "scopes": scopes if scopes is not None else ["https://www.googleapis.com/auth/adwords"],
        "metadata": {"ads_developer_token_configured": True, **(metadata or {})},
    }


CACHE = [
    {"customer_id": MCC, "descriptive_name": "Mugô MCC", "is_manager": True, "access": "direct", "login_customer_id": None},
    {"customer_id": CURAVINO, "descriptive_name": "Curavino", "is_manager": False, "access": "manager", "login_customer_id": MCC},
    {"customer_id": OTHER, "descriptive_name": "Outra direta", "is_manager": False, "access": "direct", "login_customer_id": None},
]


class GoogleAdsRouteTests(unittest.IsolatedAsyncioTestCase):
    async def _select(self, payload, *, row=None):
        update = AsyncMock(return_value={"id": "ads-vinhos", "status": "connected"})
        output = io.StringIO()
        with (
            patch.object(google_routes, "require_client_role", AsyncMock(return_value="vinhos")) as role,
            patch.object(google_routes, "require_user_id", AsyncMock(return_value="user-1")),
            patch.object(google_routes, "get_connection", AsyncMock(return_value=row or _ads_row(metadata={"google_ads_accounts_cache": CACHE}))) as get_conn,
            patch.object(google_routes, "update_connection_selection", update),
            redirect_stdout(output),
        ):
            try:
                result = await google_routes.select_ads(
                    "ads-vinhos", payload, client_id=None, x_client_id="vinhos", authorization="Bearer user-jwt",
                )
                error = None
            except (IntegrationError, HTTPException) as exc:
                result, error = None, exc
        return result, error, update, role, get_conn, output.getvalue()

    async def test_ads_accounts_route_requires_ads_scope(self):
        listing = AsyncMock()
        with (
            patch.object(google_routes, "require_client_read", AsyncMock(return_value="vinhos")),
            patch.object(google_routes, "get_connection", AsyncMock(return_value=_ads_row(scopes=["https://www.googleapis.com/auth/analytics.readonly"]))),
            patch.object(google_routes, "list_google_ads_accounts", listing),
        ):
            with self.assertRaises(IntegrationError) as raised:
                await google_routes.ads_accounts("ads-vinhos", client_id=None, x_client_id="vinhos", authorization="Bearer x")
        self.assertEqual(raised.exception.code, "GOOGLE_SCOPE_INSUFFICIENT")
        self.assertEqual(raised.exception.status_code, 403)
        listing.assert_not_awaited()

    async def test_ads_accounts_route_lists_for_active_tenant_connection(self):
        listing = AsyncMock(return_value={"available": True, "accounts": []})
        get_conn = AsyncMock(return_value=_ads_row())
        with (
            patch.object(google_routes, "require_client_read", AsyncMock(return_value="vinhos")),
            patch.object(google_routes, "get_connection", get_conn),
            patch.object(google_routes, "list_google_ads_accounts", listing),
        ):
            result = await google_routes.ads_accounts("ads-vinhos", client_id=None, x_client_id="vinhos", authorization="Bearer x")
        self.assertTrue(result["ok"])
        get_conn.assert_awaited_once_with("vinhos", "ads-vinhos")
        self.assertEqual(listing.await_args.args, ("vinhos", "ads-vinhos"))

    async def test_select_child_account_persists_customer_login_and_name_in_tenant(self):
        result, error, update, role, get_conn, log = await self._select({"customer_id": "123-456-7890"})
        self.assertIsNone(error)
        self.assertTrue(result["ok"])
        role.assert_awaited_once_with("vinhos", "Bearer user-jwt")
        get_conn.assert_awaited_once_with("vinhos", "ads-vinhos")
        kwargs = update.await_args.kwargs
        self.assertEqual(kwargs["client_id"], "vinhos")
        self.assertEqual(kwargs["connection_id"], "ads-vinhos")
        self.assertEqual(kwargs["metadata_patch"], {
            "google_ads_customer_id": CURAVINO,
            "google_ads_login_customer_id": MCC,
            "google_ads_customer_name": "Curavino",
        })
        self.assertIn(f"stage=select_customer client_id=vinhos connection_id=ads-vinhos customer_id={CURAVINO} login_customer_id={MCC}", log)

    async def test_select_direct_account_has_no_login_customer_id(self):
        _result, error, update, *_ = await self._select({"customer_id": OTHER, "login_customer_id": MCC})
        self.assertIsNone(error)
        # O login-customer-id vem da listagem, não do cliente.
        self.assertIsNone(update.await_args.kwargs["metadata_patch"]["google_ads_login_customer_id"])

    async def test_select_rejects_manager_account(self):
        _result, error, update, *_ = await self._select({"customer_id": MCC})
        self.assertEqual(error.code, "GOOGLE_ADS_MANAGER_ACCOUNT_NOT_SUPPORTED")
        update.assert_not_awaited()

    async def test_select_rejects_account_not_listed_for_this_connection(self):
        _result, error, update, *_ = await self._select({"customer_id": "1112223333"})
        self.assertEqual(error.code, "GOOGLE_ADS_ACCOUNT_NOT_LISTED")
        update.assert_not_awaited()

    async def test_select_rejects_invalid_customer_id(self):
        for value in ("customers/customers/1234567890", "abc", ""):
            with self.subTest(value=value):
                _result, error, update, *_ = await self._select({"customer_id": value})
                self.assertIsInstance(error, HTTPException)
                self.assertEqual(error.status_code, 400)
                update.assert_not_awaited()

    async def test_select_without_listing_cache_is_rejected_and_browser_login_ignored(self):
        _result, error, update, *_ = await self._select(
            {"customer_id": CURAVINO, "login_customer_id": "555-000-1111"}, row=_ads_row(),
        )
        self.assertEqual(error.code, "GOOGLE_ADS_ACCOUNTS_NOT_LISTED")
        update.assert_not_awaited()

    async def test_select_requires_ads_scope(self):
        _result, error, update, *_ = await self._select(
            {"customer_id": CURAVINO}, row=_ads_row(scopes=["https://www.googleapis.com/auth/analytics.readonly"]),
        )
        self.assertEqual(error.code, "GOOGLE_SCOPE_INSUFFICIENT")
        update.assert_not_awaited()


class GoogleAdsDashboardContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_uses_persisted_customer_and_login_for_tenant(self):
        resolver = AsyncMock(return_value={"id": "ads-vinhos", "metadata": {
            "google_ads_customer_id": "123-456-7890", "google_ads_login_customer_id": "555-000-1111",
        }})
        with patch.object(google_ads, "resolve_generic_connection", resolver):
            context = await google_ads.resolve_google_ads_context("vinhos")
        self.assertEqual(context.client_id, "vinhos")
        self.assertEqual(context.customer_id, CURAVINO)
        self.assertEqual(context.login_customer_id, MCC)
        self.assertEqual(resolver.await_args.kwargs["client_id"], "vinhos")
        self.assertEqual(resolver.await_args.kwargs["provider"], "google_ads")

    async def test_context_without_valid_selection_requires_selection(self):
        for metadata in ({}, {"google_ads_customer_id": "customers/customers/1234567890"}):
            with self.subTest(metadata=metadata):
                with patch.object(google_ads, "resolve_generic_connection", AsyncMock(return_value={"id": "ads-vinhos", "metadata": metadata})):
                    with self.assertRaises(IntegrationError) as raised:
                        await google_ads.resolve_google_ads_context("vinhos")
                self.assertEqual(raised.exception.code, "GOOGLE_ADS_ACCOUNT_SELECTION_REQUIRED")

    async def _sync(self, metadata, response: httpx.Response):
        fake = FakeAdsHttp(lambda method, url, headers, body: response)
        upsert = AsyncMock()
        output = io.StringIO()
        with (
            patch.dict(os.environ, {"GOOGLE_ADS_DEVELOPER_TOKEN": DEVELOPER_TOKEN, "GOOGLE_ADS_API_VERSION": "v25"}),
            patch.object(google_ads, "resolve_generic_connection", AsyncMock(return_value={"id": "ads-vinhos", "metadata": metadata})),
            patch.object(google_ads, "get_google_access_token", AsyncMock(return_value=ACCESS_TOKEN)),
            patch.object(google_ads, "sb_upsert", upsert),
            patch.object(google_ads, "refresh_dashboard_read_model_safely", AsyncMock()),
            patch.object(google_ads.httpx, "AsyncClient", fake.factory),
            redirect_stdout(output),
        ):
            try:
                result = await google_ads._sync_google_ads(
                    client_id="vinhos", connection_id="ads-vinhos", start=None, end=None, days=7,
                )
                error = None
            except IntegrationError as exc:
                result, error = None, exc
        log = output.getvalue()
        for secret in SECRETS:
            self.assertNotIn(secret, log)
        return result, error, fake, upsert, log

    async def test_sync_queries_selected_child_with_login_customer_id(self):
        rows = _json(200, [{"results": [{
            "segments": {"date": "2026-09-29"}, "campaign": {"id": "1", "name": "Vinhos"},
            "metrics": {"costMicros": "1500000", "clicks": "3", "impressions": "100"},
        }]}])
        result, error, fake, upsert, log = await self._sync(
            {"google_ads_customer_id": CURAVINO, "google_ads_login_customer_id": MCC}, rows,
        )
        self.assertIsNone(error)
        call = fake.calls[0]
        self.assertEqual(call["url"], f"https://googleads.googleapis.com/v25/customers/{CURAVINO}/googleAds:searchStream")
        self.assertEqual(call["headers"]["login-customer-id"], MCC)
        self.assertEqual(result["customer_id"], CURAVINO)
        saved = upsert.await_args.args[1][0]
        self.assertEqual((saved["client_id"], saved["customer_id"]), ("vinhos", CURAVINO))
        self.assertIn(f"stage=sync client_id=vinhos connection_id=ads-vinhos customer_id={CURAVINO} login_customer_id={MCC}", log)

    async def test_sync_direct_account_sends_no_login_customer_id(self):
        _result, error, fake, *_ = await self._sync({"google_ads_customer_id": OTHER}, _json(200, []))
        self.assertIsNone(error)
        self.assertNotIn("login-customer-id", fake.calls[0]["headers"])

    async def test_sync_manager_account_error_is_explicit(self):
        response = _ads_error(400, {"queryError": "REQUESTED_METRICS_FOR_MANAGER"})
        _result, error, _fake, upsert, log = await self._sync({"google_ads_customer_id": MCC}, response)
        self.assertEqual(error.code, "GOOGLE_ADS_MANAGER_ACCOUNT_NOT_SUPPORTED")
        self.assertEqual(error.diagnostics["upstream_reason"], "queryError:REQUESTED_METRICS_FOR_MANAGER")
        upsert.assert_not_awaited()
        self.assertIn("error_code=REQUESTED_METRICS_FOR_MANAGER", log)

    async def test_sync_unknown_error_keeps_query_failed_contract(self):
        response = _json(500, {"error": {"code": 500, "status": "INTERNAL", "message": "boom"}})
        _result, error, *_ = await self._sync({"google_ads_customer_id": CURAVINO}, response)
        self.assertEqual(error.code, "GOOGLE_ADS_QUERY_FAILED")
        self.assertEqual(error.diagnostics["upstream_status"], 500)

    async def test_report_reads_only_selected_customer(self):
        select = AsyncMock(return_value=[])
        context = google_ads.GoogleAdsContext("vinhos", "ads-vinhos", CURAVINO, MCC)
        with patch.object(google_ads, "sb_select", select):
            await google_ads.build_google_ads_report(client_id="vinhos", context=context, start="2026-09-01", end="2026-09-30")
        filters = select.await_args.kwargs["filters"]
        self.assertEqual(filters["client_id"], "eq.vinhos")
        self.assertEqual(filters["connection_id"], "eq.ads-vinhos")
        self.assertEqual(filters["customer_id"], f"eq.{CURAVINO}")


# ---------------------------------------------------------------------------
# Regressão com a evidência real de produção (tenant vinhos, deploy 610074a):
# MCC Mugô Agência 590-356-2384 com as contas CURAVINO 592-799-3611 e
# Mugô 827-780-1207. A conta de mídia da vinhos é a CURAVINO.
# ---------------------------------------------------------------------------
MCC_REAL = "5903562384"
CURAVINO_REAL = "5927993611"
MUGO_REAL = "8277801207"
NOT_ENABLED = {"authorizationError": "CUSTOMER_NOT_ENABLED"}
NOT_ENABLED_MESSAGE = "The customer account can't be accessed because it is not yet enabled or has been deactivated."


def _real_hierarchy() -> httpx.Response:
    return _customer_clients([
        {"clientCustomer": f"customers/{MCC_REAL}", "id": MCC_REAL, "descriptiveName": "Mugô Agência",
         "manager": True, "status": "ENABLED", "level": "0"},
        {"clientCustomer": f"customers/{CURAVINO_REAL}", "id": CURAVINO_REAL, "descriptiveName": "CURAVINO",
         "manager": False, "status": "ENABLED", "currencyCode": "BRL", "timeZone": "America/Sao_Paulo", "level": "1"},
        {"clientCustomer": f"customers/{MUGO_REAL}", "id": MUGO_REAL, "descriptiveName": "Mugô",
         "manager": False, "status": "ENABLED", "level": "1"},
    ])


def _real_links() -> httpx.Response:
    return _json(200, {"results": [
        {"customerClientLink": {"clientCustomer": f"customers/{CURAVINO_REAL}", "status": "ACTIVE"}},
        {"customerClientLink": {"clientCustomer": f"customers/{MUGO_REAL}", "status": "ACTIVE"}},
    ]})


def _query(body) -> str:
    return str((body or {}).get("query") or "")


async def _run_listing(test: unittest.TestCase, handler):
    fake = FakeAdsHttp(handler)
    persist = AsyncMock()
    output = io.StringIO()
    with (
        patch.dict(os.environ, {"GOOGLE_ADS_DEVELOPER_TOKEN": DEVELOPER_TOKEN, "GOOGLE_ADS_API_VERSION": "v25"}),
        patch.object(google_oauth, "_access_token", AsyncMock(return_value=ACCESS_TOKEN)),
        patch.object(google_oauth, "_persist_google_ads_accounts_cache", persist),
        patch.object(google_oauth.httpx, "AsyncClient", fake.factory),
        redirect_stdout(output),
    ):
        result = await google_oauth.list_google_ads_accounts("vinhos", "ads-vinhos", request_id="req-vinhos")
    log = output.getvalue()
    for secret in SECRETS:
        test.assertNotIn(secret, log)
    return result, fake, persist, log


class CuravinoMccRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcc_details_not_enabled_still_discovers_curavino_and_mugo(self):
        def handler(method, url, headers, body):
            if url.endswith("customers:listAccessibleCustomers"):
                return _json(200, {"resourceNames": [f"customers/{MCC_REAL}"]})
            if url.endswith(f"customers/{MCC_REAL}/googleAds:search") and "FROM customer_client" in _query(body):
                return _real_hierarchy()
            if url.endswith(f"customers/{MCC_REAL}/googleAds:search"):
                return _ads_error(403, NOT_ENABLED, NOT_ENABLED_MESSAGE, request_id="req-detail")
            raise AssertionError(url)

        result, fake, _persist, log = await _run_listing(self, handler)
        by_id = {account["customer_id"]: account for account in result["accounts"]}
        self.assertEqual(set(by_id), {MCC_REAL, CURAVINO_REAL, MUGO_REAL})
        # Detalhe falhou, mas a hierarquia foi tentada e preencheu a MCC (linha level 0).
        self.assertEqual(by_id[MCC_REAL]["details_error"], "CUSTOMER_NOT_ENABLED")
        self.assertTrue(by_id[MCC_REAL]["is_manager"])
        self.assertEqual(by_id[MCC_REAL]["descriptive_name"], "Mugô Agência")
        self.assertNotIn("hierarchy_error", by_id[MCC_REAL])
        curavino = by_id[CURAVINO_REAL]
        self.assertEqual(curavino["descriptive_name"], "CURAVINO")
        self.assertFalse(curavino["is_manager"])
        self.assertEqual(curavino["status"], "ENABLED")
        self.assertEqual(curavino["access"], "manager")
        self.assertEqual(curavino["login_customer_id"], MCC_REAL)
        self.assertEqual(curavino["manager_customer_id"], MCC_REAL)
        self.assertEqual(curavino["manager_name"], "Mugô Agência")
        self.assertEqual(by_id[MUGO_REAL]["login_customer_id"], MCC_REAL)
        hierarchy = next(call for call in fake.calls if "FROM customer_client" in _query(call["json"]))
        self.assertEqual(hierarchy["url"], f"https://googleads.googleapis.com/v25/customers/{MCC_REAL}/googleAds:search")
        self.assertEqual(hierarchy["headers"]["login-customer-id"], MCC_REAL)
        self.assertIn("Detalhes da conta 590-356-2384 não puderam ser lidos (HTTP 403, código CUSTOMER_NOT_ENABLED, request ID req-detail).", result["reason"])
        self.assertNotIn("não puderam ser listadas", result["reason"])
        self.assertIn(
            f"stage=manager_children request_id=req-vinhos client_id=vinhos connection_id=ads-vinhos "
            f"manager_customer_id={MCC_REAL} login_customer_id={MCC_REAL}", log,
        )
        self.assertIn("http_status=200 google_request_id=- error_code=- message=- children_count=2", log)
        self.assertIn(f"customer_id={CURAVINO_REAL} manager=false status=ENABLED access=manager login_customer_id={MCC_REAL}", log)

    async def test_customer_client_refused_falls_back_to_active_links(self):
        def handler(method, url, headers, body):
            query = _query(body)
            if url.endswith("customers:listAccessibleCustomers"):
                return _json(200, {"resourceNames": [f"customers/{MCC_REAL}"]})
            if url.endswith(f"customers/{MCC_REAL}/googleAds:search") and "FROM customer_client_link" in query:
                return _real_links()
            if url.endswith(f"customers/{MCC_REAL}/googleAds:search") and "FROM customer_client" in query:
                return _ads_error(403, NOT_ENABLED, NOT_ENABLED_MESSAGE, request_id="req-cc")
            if url.endswith(f"customers/{MCC_REAL}/googleAds:search"):
                return _customer_info(MCC_REAL, "Mugô Agência", manager=True)
            if url.endswith(f"customers/{CURAVINO_REAL}/googleAds:search"):
                return _customer_info(CURAVINO_REAL, "CURAVINO")
            if url.endswith(f"customers/{MUGO_REAL}/googleAds:search"):
                return _ads_error(403, NOT_ENABLED, NOT_ENABLED_MESSAGE, request_id="req-mugo")
            raise AssertionError(url)

        result, fake, _persist, log = await _run_listing(self, handler)
        by_id = {account["customer_id"]: account for account in result["accounts"]}
        self.assertEqual(set(by_id), {MCC_REAL, CURAVINO_REAL, MUGO_REAL})
        self.assertEqual(by_id[MCC_REAL]["hierarchy_error"], "CUSTOMER_NOT_ENABLED")
        self.assertNotIn("links_error", by_id[MCC_REAL])
        self.assertEqual(by_id[CURAVINO_REAL]["descriptive_name"], "CURAVINO")
        self.assertEqual(by_id[CURAVINO_REAL]["login_customer_id"], MCC_REAL)
        self.assertEqual(by_id[CURAVINO_REAL]["source"], "customer_client_link")
        self.assertNotIn("details_error", by_id[CURAVINO_REAL])
        self.assertEqual(by_id[MUGO_REAL]["details_error"], "CUSTOMER_NOT_ENABLED")
        for child in (CURAVINO_REAL, MUGO_REAL):
            call = next(item for item in fake.calls if item["url"].endswith(f"customers/{child}/googleAds:search"))
            self.assertEqual(call["headers"]["login-customer-id"], MCC_REAL)
        endpoint = f"POST /v25/customers/{MCC_REAL}/googleAds:search"
        self.assertEqual(result["diagnostics"][0], {
            "stage": "manager_children", "customer_id": MCC_REAL, "login_customer_id": MCC_REAL,
            "endpoint": endpoint, "http_status": 403, "error_code": "CUSTOMER_NOT_ENABLED",
            "google_request_id": "req-cc", "message": NOT_ENABLED_MESSAGE,
        })
        self.assertEqual(result["diagnostics"][1]["stage"], "manager_links")
        self.assertEqual(result["diagnostics"][1]["http_status"], 200)
        self.assertEqual(result["diagnostics"][1]["children_count"], 2)
        self.assertEqual(result["diagnostics"][2]["customer_id"], MUGO_REAL)
        self.assertEqual(result["diagnostics"][2]["login_customer_id"], MCC_REAL)
        self.assertEqual(result["diagnostics"][2]["google_request_id"], "req-mugo")
        self.assertIn(
            "As contas vinculadas à conta administradora 590-356-2384 não puderam ser listadas via customer_client "
            "(HTTP 403, código CUSTOMER_NOT_ENABLED, request ID req-cc).", result["reason"],
        )
        self.assertIn("obtidas pelos vínculos ativos (customer_client_link): 2.", result["reason"])
        self.assertIn("Detalhes da conta 827-780-1207 não puderam ser lidos (HTTP 403, código CUSTOMER_NOT_ENABLED, request ID req-mugo).", result["reason"])
        self.assertIn(
            f"stage=manager_children request_id=req-vinhos client_id=vinhos connection_id=ads-vinhos "
            f"manager_customer_id={MCC_REAL} login_customer_id={MCC_REAL} endpoint={endpoint} "
            f"http_status=403 google_request_id=req-cc error_code=CUSTOMER_NOT_ENABLED", log,
        )
        self.assertIn("stage=manager_links", log)
        self.assertIn("children_count=2", log)

    async def test_hierarchy_and_links_refused_reports_exact_external_failure(self):
        def handler(method, url, headers, body):
            query = _query(body)
            if url.endswith("customers:listAccessibleCustomers"):
                return _json(200, {"resourceNames": [f"customers/{MCC_REAL}"]})
            if "FROM customer_client_link" in query:
                return _ads_error(403, NOT_ENABLED, NOT_ENABLED_MESSAGE, request_id="req-link")
            if "FROM customer_client" in query:
                return _ads_error(403, NOT_ENABLED, NOT_ENABLED_MESSAGE, request_id="req-cc")
            return _customer_info(MCC_REAL, "Mugô Agência", manager=True)

        result, _fake, _persist, _log = await _run_listing(self, handler)
        self.assertEqual([account["customer_id"] for account in result["accounts"]], [MCC_REAL])
        self.assertEqual(result["accounts"][0]["hierarchy_error"], "CUSTOMER_NOT_ENABLED")
        self.assertEqual(result["accounts"][0]["links_error"], "CUSTOMER_NOT_ENABLED")
        endpoint = f"POST /v25/customers/{MCC_REAL}/googleAds:search"
        self.assertEqual(
            [(d["stage"], d["endpoint"], d["customer_id"], d["login_customer_id"], d["http_status"], d["error_code"], d["google_request_id"])
             for d in result["diagnostics"]],
            [
                ("manager_children", endpoint, MCC_REAL, MCC_REAL, 403, "CUSTOMER_NOT_ENABLED", "req-cc"),
                ("manager_links", endpoint, MCC_REAL, MCC_REAL, 403, "CUSTOMER_NOT_ENABLED", "req-link"),
            ],
        )
        self.assertIn("request ID req-cc", result["reason"])
        self.assertIn("também foram recusados (HTTP 403, código CUSTOMER_NOT_ENABLED, request ID req-link)", result["reason"])

    async def test_vinhos_selects_curavino_with_mcc_login_resolved_server_side(self):
        def handler(method, url, headers, body):
            if url.endswith("customers:listAccessibleCustomers"):
                return _json(200, {"resourceNames": [f"customers/{MCC_REAL}"]})
            if "FROM customer_client" in _query(body):
                return _real_hierarchy()
            return _ads_error(403, NOT_ENABLED, NOT_ENABLED_MESSAGE)

        _result, _fake, persist, _log = await _run_listing(self, handler)
        cache = persist.await_args.kwargs["accounts"]
        self.assertEqual(persist.await_args.kwargs["client_id"], "vinhos")
        row = _ads_row(metadata={"google_ads_accounts_cache": cache})

        async def select(payload):
            update = AsyncMock(return_value={"id": "ads-vinhos", "status": "connected"})
            with (
                patch.object(google_routes, "require_client_role", AsyncMock(return_value="vinhos")),
                patch.object(google_routes, "require_user_id", AsyncMock(return_value="user-1")),
                patch.object(google_routes, "get_connection", AsyncMock(return_value=row)) as get_conn,
                patch.object(google_routes, "update_connection_selection", update),
                redirect_stdout(io.StringIO()),
            ):
                try:
                    await google_routes.select_ads("ads-vinhos", payload, client_id=None, x_client_id="vinhos", authorization="Bearer jwt")
                    return update, None, get_conn
                except IntegrationError as exc:
                    return update, exc, get_conn

        # Login enviado pelo navegador é ignorado: vem da hierarquia descoberta.
        update, error, get_conn = await select({"customer_id": "592-799-3611", "login_customer_id": "1112223333"})
        self.assertIsNone(error)
        get_conn.assert_awaited_once_with("vinhos", "ads-vinhos")
        self.assertEqual(update.await_args.kwargs["client_id"], "vinhos")
        self.assertEqual(update.await_args.kwargs["metadata_patch"], {
            "google_ads_customer_id": CURAVINO_REAL,
            "google_ads_login_customer_id": MCC_REAL,
            "google_ads_customer_name": "CURAVINO",
        })
        update, error, _ = await select({"customer_id": MCC_REAL})
        self.assertEqual(error.code, "GOOGLE_ADS_MANAGER_ACCOUNT_NOT_SUPPORTED")
        update.assert_not_awaited()

    async def test_inactive_linked_account_is_not_selectable(self):
        def handler(method, url, headers, body):
            query = _query(body)
            if url.endswith("customers:listAccessibleCustomers"):
                return _json(200, {"resourceNames": [f"customers/{MCC_REAL}"]})
            if "FROM customer_client_link" in query:
                return _real_links()
            if "FROM customer_client" in query:
                return _ads_error(403, NOT_ENABLED)
            if url.endswith(f"customers/{MCC_REAL}/googleAds:search"):
                return _customer_info(MCC_REAL, "Mugô Agência", manager=True)
            if url.endswith(f"customers/{CURAVINO_REAL}/googleAds:search"):
                return _customer_info(CURAVINO_REAL, "CURAVINO")
            return _ads_error(403, NOT_ENABLED)

        _result, _fake, persist, _log = await _run_listing(self, handler)
        row = _ads_row(metadata={"google_ads_accounts_cache": persist.await_args.kwargs["accounts"]})
        update = AsyncMock()
        with (
            patch.object(google_routes, "require_client_role", AsyncMock(return_value="vinhos")),
            patch.object(google_routes, "require_user_id", AsyncMock(return_value="user-1")),
            patch.object(google_routes, "get_connection", AsyncMock(return_value=row)),
            patch.object(google_routes, "update_connection_selection", update),
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(IntegrationError) as raised:
                await google_routes.select_ads("ads-vinhos", {"customer_id": MUGO_REAL}, client_id=None, x_client_id="vinhos", authorization="Bearer jwt")
        self.assertEqual(raised.exception.code, "GOOGLE_ADS_CUSTOMER_NOT_ENABLED")
        update.assert_not_awaited()

    async def test_curavino_sync_uses_child_customer_and_mcc_login_header(self):
        fake = FakeAdsHttp(lambda method, url, headers, body: _json(200, []))
        output = io.StringIO()
        with (
            patch.dict(os.environ, {"GOOGLE_ADS_DEVELOPER_TOKEN": DEVELOPER_TOKEN, "GOOGLE_ADS_API_VERSION": "v25"}),
            patch.object(google_ads, "resolve_generic_connection", AsyncMock(return_value={"id": "ads-vinhos", "metadata": {
                "google_ads_customer_id": CURAVINO_REAL, "google_ads_login_customer_id": MCC_REAL,
                "google_ads_customer_name": "CURAVINO",
            }})) as resolver,
            patch.object(google_ads, "get_google_access_token", AsyncMock(return_value=ACCESS_TOKEN)),
            patch.object(google_ads, "sb_upsert", AsyncMock()),
            patch.object(google_ads, "refresh_dashboard_read_model_safely", AsyncMock()),
            patch.object(google_ads.httpx, "AsyncClient", fake.factory),
            redirect_stdout(output),
        ):
            result = await google_ads._sync_google_ads(
                client_id="vinhos", connection_id="ads-vinhos", start=None, end=None, days=7,
            )
        self.assertEqual(resolver.await_args.kwargs["client_id"], "vinhos")
        self.assertEqual(len(fake.calls), 1)
        call = fake.calls[0]
        self.assertEqual(call["url"], f"https://googleads.googleapis.com/v25/customers/{CURAVINO_REAL}/googleAds:searchStream")
        self.assertNotIn(MCC_REAL, call["url"])
        self.assertEqual(call["headers"]["login-customer-id"], MCC_REAL)
        self.assertEqual(result["customer_id"], CURAVINO_REAL)
        self.assertIn(f"stage=sync client_id=vinhos connection_id=ads-vinhos customer_id={CURAVINO_REAL} login_customer_id={MCC_REAL}", output.getvalue())
        for secret in SECRETS:
            self.assertNotIn(secret, output.getvalue())


if __name__ == "__main__":
    unittest.main()
