import hashlib
import hmac
import io
import os
import unittest
import httpx
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock, patch

from server.services import oauth_state
from server.services import google_oauth
from server.services import generic_connections
from server.services import ads_sync
from server.services import meta_tokens
from server.services import meta_config
from server.services import meta_http
from server.services import meta_oauth
from server.services.generic_connections import sanitize_connection
from server.services.invitations import invitation_is_usable
from server.services import shopify_oauth
from server.services.shopify_oauth import normalize_shop_domain, verify_callback_hmac
from server.services.meta_oauth import validate_page_selection


ROOT = Path(__file__).resolve().parents[2]
META_REDIRECT_URI = "https://api.dados.mugoagencia.com.br/api/oauth/meta/callback"
EXPECTED_META_SCOPES = [
    "public_profile",
    "pages_show_list",
    "pages_read_engagement",
    "instagram_basic",
    "instagram_manage_insights",
    "ads_read",
    "business_management",
]

# Scopes que o Analytics V1 exige e que NÃO podem sumir do OAuth.
REQUIRED_META_V1_SCOPES = [
    "public_profile",
    "pages_show_list",
    "pages_read_engagement",
    "instagram_basic",
    "instagram_manage_insights",
    "ads_read",
    "business_management",
]


class MetaOAuthConfigurationTests(unittest.TestCase):
    def _build_url(self):
        with patch.dict(
            os.environ,
            {
                "META_APP_ID": "meta-app-id",
                "META_OAUTH_STATE_SECRET": "s" * 48,
            },
            clear=False,
        ):
            return meta_oauth.build_oauth_url(
                client_id="amalie",
                user_id="user-amalie",
                redirect_uri=META_REDIRECT_URI,
            )

    def test_default_graph_version_and_urls_use_v25(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("META_GRAPH_VERSION", None)
            self.assertEqual(meta_config.resolve_meta_graph_version(), "v25.0")
        self.assertEqual(meta_config.META_GRAPH_VERSION, "v25.0")
        self.assertEqual(
            meta_http.META_BASE,
            "https://graph.facebook.com/v25.0",
        )
        self.assertEqual(
            meta_oauth.META_DIALOG,
            "https://www.facebook.com/v25.0/dialog/oauth",
        )

    def test_repository_has_no_legacy_v19_meta_url(self):
        legacy_version = "v" + "19.0"
        legacy_urls = (
            f"graph.facebook.com/{legacy_version}",
            f"facebook.com/{legacy_version}",
        )
        matches = []
        for path in ROOT.rglob("*"):
            if (
                not path.is_file()
                or any(
                    part
                    in {
                        ".git",
                        ".pytest_cache",
                        ".venv",
                        ".vite",
                        "__pycache__",
                        "dist",
                        "node_modules",
                        "venv",
                    }
                    for part in path.parts
                )
            ):
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if any(url in content for url in legacy_urls):
                matches.append(str(path.relative_to(ROOT)))
        self.assertEqual(matches, [])

    def test_redirect_uri_remains_exact(self):
        with patch.dict(
            os.environ,
            {"META_OAUTH_REDIRECT_URI": META_REDIRECT_URI},
            clear=False,
        ):
            self.assertEqual(
                meta_oauth.resolve_meta_redirect_uri("https://mugo-dados.onrender.com"),
                META_REDIRECT_URI,
            )
            result = self._build_url()
            query = parse_qs(urlparse(result["url"]).query)
            self.assertEqual(query["redirect_uri"], [META_REDIRECT_URI])

    def test_meta_state_is_signed_and_validated(self):
        with patch.dict(
            os.environ,
            {"META_OAUTH_STATE_SECRET": "s" * 48},
            clear=False,
        ):
            result = self._build_url()
            payload = meta_oauth.verify_state(
                result["state"],
                expected_user_id="user-amalie",
            )
            self.assertEqual(payload["client_id"], "amalie")
            with self.assertRaisesRegex(RuntimeError, "state OAuth inválido"):
                meta_oauth.verify_state(f"{result['state']}tampered")

    def test_facebook_login_scopes_are_canonical(self):
        with patch.dict(
            os.environ,
            {"META_OAUTH_SCOPES": "instagram_manage_comments,pages_manage_posts"},
            clear=False,
        ):
            result = self._build_url()
        query = parse_qs(urlparse(result["url"]).query)
        scopes = query["scope"][0].split(",")
        self.assertEqual(scopes, EXPECTED_META_SCOPES)
        self.assertNotIn("instagram_manage_comments", scopes)
        self.assertNotIn("pages_manage_posts", scopes)
        self.assertFalse(
            any(scope.startswith("instagram_business_") for scope in scopes)
        )

    def test_email_scope_is_not_requested(self):
        """Analytics V1 não usa `email` da Meta (autenticação é via Supabase).

        Pedir um scope sem uso — e ausente da Login Configuration
        "Mugô Dados Production" — só amplia a superfície de App Review.
        """
        query = parse_qs(urlparse(self._build_url()["url"]).query)
        scopes = query["scope"][0].split(",")
        self.assertNotIn("email", scopes)
        for required in REQUIRED_META_V1_SCOPES:
            self.assertIn(required, scopes)

    def test_login_for_business_configuration_is_forwarded_without_access_type(self):
        with patch.dict(os.environ, {"META_LOGIN_CONFIG_ID": "business-login-config"}, clear=False):
            query = parse_qs(urlparse(self._build_url()["url"]).query)
        self.assertEqual(query["config_id"], ["business-login-config"])
        self.assertEqual(query["override_default_response_type"], ["true"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertNotIn("access_type", query)

    def test_login_for_business_config_is_required_by_runtime_start(self):
        with patch.dict(os.environ, {
            "META_APP_ID": "meta-app-id", "META_APP_SECRET": "meta-secret",
            "META_OAUTH_REDIRECT_URI": META_REDIRECT_URI,
        }, clear=False):
            os.environ.pop("META_LOGIN_CONFIG_ID", None)
            with self.assertRaisesRegex(RuntimeError, "META_LOGIN_CONFIG_ID"):
                meta_oauth.get_meta_oauth_settings(
                    require_redirect_uri=True, require_login_config_id=True, debug=False,
                )

    def test_meta_http_redacts_oauth_secrets_from_urls(self):
        safe = meta_http._safe_url(
            "https://graph.facebook.com/next?access_token=secret&code=authorization-code&after=cursor"
        )
        self.assertNotIn("secret", safe)
        self.assertNotIn("authorization-code", safe)
        self.assertIn("after=cursor", safe)

    def test_meta_permission_oauth_exception_is_not_an_invalid_token(self):
        response = httpx.Response(
            403,
            request=httpx.Request("GET", "https://graph.facebook.com/v25.0/business/owned_ad_accounts"),
            json={"error": {
                "message": "(#200) Requires business_management permission",
                "type": "OAuthException",
                "code": 200,
                "fbtrace_id": "trace-permission",
            }},
        )
        error = meta_http._http_error_from_response(response)
        self.assertFalse(error.invalid_oauth)
        self.assertEqual(error.error_code, 200)
        self.assertEqual(error.trace_id, "trace-permission")

    def test_meta_code_190_remains_an_invalid_token(self):
        response = httpx.Response(
            401,
            request=httpx.Request("GET", "https://graph.facebook.com/v25.0/me"),
            json={"error": {
                "message": "Error validating access token",
                "type": "OAuthException",
                "code": 190,
            }},
        )
        self.assertTrue(meta_http._http_error_from_response(response).invalid_oauth)


class OAuthStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_meta_state_signature_is_validated(self):
        os.environ["OAUTH_STATE_SECRET"] = "s" * 48

        with patch.object(oauth_state, "sb_insert", AsyncMock(return_value={"ok": True})):
            state = await oauth_state.create_oauth_state(
                provider="meta",
                user_id="user-1",
                client_id="amalie",
                redirect_uri=META_REDIRECT_URI,
            )

        with self.assertRaisesRegex(RuntimeError, "State OAuth inválido"):
            await oauth_state.consume_oauth_state(
                f"{state}tampered",
                provider="meta",
            )

    async def test_state_is_single_use(self):
        os.environ["OAUTH_STATE_SECRET"] = "s" * 48
        inserted = {}

        async def insert(_table, row, returning="minimal"):
            inserted.update(row)
            inserted["id"] = "session-1"
            return {"ok": True}

        with patch.object(oauth_state, "sb_insert", insert):
            state = await oauth_state.create_oauth_state(
                provider="google",
                user_id="user-1",
                client_id="amalie",
                redirect_uri="http://localhost/callback",
            )

        row = {
            **inserted,
            "id": "session-1",
            "consumed_at": None,
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        }
        select = AsyncMock(return_value=[row])
        update = AsyncMock(return_value=[{**row, "consumed_at": datetime.now(timezone.utc).isoformat()}])
        with (
            patch.object(oauth_state, "sb_select", select),
            patch.object(oauth_state, "sb_update", update),
        ):
            consumed = await oauth_state.consume_oauth_state(state, provider="google")
        self.assertEqual(consumed["client_id"], "amalie")

        with patch.object(oauth_state, "sb_select", AsyncMock(return_value=[{**row, "consumed_at": "used"}])):
            with self.assertRaisesRegex(RuntimeError, "já utilizado"):
                await oauth_state.consume_oauth_state(state, provider="google")

    async def test_expired_state_is_rejected(self):
        os.environ["OAUTH_STATE_SECRET"] = "s" * 48
        captured = {}

        async def insert(_table, row, returning="minimal"):
            captured.update(row)
            return {"ok": True}

        with patch.object(oauth_state, "sb_insert", insert):
            state = await oauth_state.create_oauth_state(
                provider="shopify",
                user_id="user-1",
                client_id="amalie",
                redirect_uri="http://localhost/callback",
            )
        expired = {
            **captured,
            "id": "expired",
            "consumed_at": None,
            "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        }
        with patch.object(oauth_state, "sb_select", AsyncMock(return_value=[expired])):
            with self.assertRaisesRegex(RuntimeError, "expirado"):
                await oauth_state.consume_oauth_state(state, provider="shopify")


class ShopifySecurityTests(unittest.IsolatedAsyncioTestCase):
    def test_invalid_domains_are_rejected(self):
        for value in ("evil.com", "https://shop.myshopify.com/path", "shop.myshopify.com.evil.com", ""):
            with self.assertRaises(RuntimeError):
                normalize_shop_domain(value)
        self.assertEqual(normalize_shop_domain("Minha-Loja.myshopify.com"), "minha-loja.myshopify.com")

    def test_callback_hmac(self):
        with patch.dict(
            os.environ,
            {
                "SHOPIFY_CLIENT_ID": "client",
                "SHOPIFY_CLIENT_SECRET": "shopify-secret",
                "SHOPIFY_OAUTH_REDIRECT_URI": "http://localhost:8000/api/oauth/shopify/callback",
                "APP_ENV": "development",
                "RENDER": "false",
            },
            clear=False,
        ):
            params = {"code": "code", "shop": "loja.myshopify.com", "state": "state", "timestamp": "1"}
            message = "&".join(f"{key}={value}" for key, value in sorted(params.items()))
            params["hmac"] = hmac.new(
                b"shopify-secret", message.encode("utf-8"), hashlib.sha256
            ).hexdigest()
            self.assertTrue(verify_callback_hmac(params))
            params["hmac"] = "invalid"
            self.assertFalse(verify_callback_hmac(params))

    def test_production_callback_is_exact_https_url(self):
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "SHOPIFY_CLIENT_ID": "shopify-client-id",
                "SHOPIFY_CLIENT_SECRET": "secret",
                "SHOPIFY_OAUTH_REDIRECT_URI": shopify_oauth.SHOPIFY_PRODUCTION_REDIRECT_URI,
            },
            clear=False,
        ):
            config = shopify_oauth.settings()
        parsed = urlparse(config["redirect_uri"])
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "api.dados.mugoagencia.com.br")
        self.assertEqual(parsed.path, "/api/oauth/shopify/callback")
        self.assertFalse(config["redirect_uri"].endswith("/"))

    def test_incorrect_production_callback_fails_clearly(self):
        invalid_values = (
            "http://api.dados.mugoagencia.com.br/api/oauth/shopify/callback",
            "https://dados.mugoagencia.com.br/api/oauth/shopify/callback",
            "https://mugo-dados.onrender.com/api/oauth/shopify/callback",
            "https://api.dados.mugoagencia.com.br/api/oauth/shopify/callback/",
        )
        for value in invalid_values:
            with self.subTest(value=value), patch.dict(
                os.environ,
                {
                    "APP_ENV": "production",
                    "SHOPIFY_CLIENT_ID": "shopify-client-id",
                    "SHOPIFY_CLIENT_SECRET": "secret",
                    "SHOPIFY_OAUTH_REDIRECT_URI": value,
                },
                clear=False,
            ):
                with self.assertRaisesRegex(RuntimeError, "SHOPIFY_OAUTH_REDIRECT_URI"):
                    shopify_oauth.settings()

    async def test_redirect_uri_is_encoded_once(self):
        with (
            patch.dict(
                os.environ,
                {
                    "APP_ENV": "production",
                    "SHOPIFY_CLIENT_ID": "shopify-client-id",
                    "SHOPIFY_CLIENT_SECRET": "secret",
                    "SHOPIFY_OAUTH_REDIRECT_URI": shopify_oauth.SHOPIFY_PRODUCTION_REDIRECT_URI,
                },
                clear=False,
            ),
            patch.object(shopify_oauth, "create_oauth_state", AsyncMock(return_value="signed-state")),
        ):
            value = await shopify_oauth.authorization_url(
                user_id="user-roove",
                client_id="roove",
                shop_domain="loja.myshopify.com",
            )
        query = parse_qs(urlparse(value).query)
        self.assertEqual(query["redirect_uri"], [shopify_oauth.SHOPIFY_PRODUCTION_REDIRECT_URI])
        requested_scopes = set(query["scope"][0].split(","))
        self.assertIn("read_orders", requested_scopes)
        self.assertIn("read_all_orders", requested_scopes)
        self.assertNotIn("%25", value)


class ShopifyTenantTests(unittest.IsolatedAsyncioTestCase):
    async def test_store_cannot_be_silently_moved_to_another_client(self):
        with patch.object(
            shopify_oauth,
            "sb_select",
            AsyncMock(return_value=[{"id": "store-1", "client_id": "amalie"}]),
        ):
            with self.assertRaisesRegex(RuntimeError, "outra empresa"):
                await shopify_oauth.save_shopify_connection(
                    client_id="roove",
                    user_id="user-roove",
                    shop_domain="loja.myshopify.com",
                    token={"access_token": "token", "scope": "read_orders"},
                    shop={"id": 1, "name": "Loja"},
                )

    async def test_two_domains_resolve_to_distinct_clients(self):
        async def select(_table, *, filters, limit=1, **_kwargs):
            domain = filters["shop_domain"].removeprefix("eq.")
            mapping = {
                "amalie.myshopify.com": "amalie",
                "roove.myshopify.com": "roove",
            }
            return [{"shop_domain": domain, "client_id": mapping[domain]}] if domain in mapping else []

        with patch.object(shopify_oauth, "sb_select", select):
            amalie = await shopify_oauth.resolve_store_by_domain("amalie.myshopify.com")
            roove = await shopify_oauth.resolve_store_by_domain("roove.myshopify.com")
        self.assertEqual(amalie["client_id"], "amalie")
        self.assertEqual(roove["client_id"], "roove")


class TokenExposureAndInvitationTests(unittest.TestCase):
    def test_sanitized_connection_never_exposes_tokens(self):
        sanitized = sanitize_connection(
            {
                "id": "1",
                "client_id": "amalie",
                "provider": "ga4",
                "encrypted_token": "ciphertext",
                "encrypted_access_token": "ciphertext",
                "refresh_token": "secret",
            }
        )
        self.assertNotIn("encrypted_token", sanitized)
        self.assertNotIn("encrypted_access_token", sanitized)
        self.assertNotIn("refresh_token", sanitized)

    def test_expired_or_used_invitation_is_rejected(self):
        now = datetime.now(timezone.utc)
        self.assertFalse(invitation_is_usable({"expires_at": (now - timedelta(seconds=1)).isoformat()}, now=now))
        self.assertFalse(
            invitation_is_usable(
                {"expires_at": (now + timedelta(hours=1)).isoformat(), "accepted_at": now.isoformat()},
                now=now,
            )
        )
        self.assertTrue(invitation_is_usable({"expires_at": (now + timedelta(hours=1)).isoformat()}, now=now))


class MetaAssetSelectionTests(unittest.TestCase):
    def test_instagram_requires_its_discovered_page(self):
        instagram = [{"ig_user_id": "ig-1", "business_id": "page-1"}]
        with self.assertRaisesRegex(RuntimeError, "Página do Facebook associada"):
            validate_page_selection(
                discovered_instagram_accounts=instagram,
                requested_page_ids=set(),
                selected_instagram_accounts=instagram,
            )

    def test_unknown_page_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "não pertence"):
            validate_page_selection(
                discovered_instagram_accounts=[{"ig_user_id": "ig-1", "business_id": "page-1"}],
                requested_page_ids={"page-other"},
                selected_instagram_accounts=[],
            )

    def test_matching_page_and_instagram_are_accepted(self):
        instagram = [{"ig_user_id": "ig-1", "business_id": "page-1"}]
        validate_page_selection(
            discovered_instagram_accounts=instagram,
            requested_page_ids={"page-1"},
            selected_instagram_accounts=instagram,
        )


class MetaConnectionPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_meta_disconnect_removes_local_token_and_disconnects_base_when_last_asset(self):
        legacy_update = AsyncMock(return_value=[{"id": "meta-asset", "status": "disconnected", "platform": "meta_ads"}])
        generic_disconnect = AsyncMock(return_value={"status": "disconnected"})
        with (
            patch.object(meta_oauth, "sb_update", legacy_update),
            patch.object(
                meta_oauth,
                "sb_select",
                AsyncMock(side_effect=[[], [{"id": "meta-base", "status": "connected"}]]),
            ),
            patch.object(meta_oauth, "disconnect_generic_connection", generic_disconnect),
            patch.object(meta_oauth, "audit_connection", AsyncMock()) as audit,
            patch.object(meta_oauth, "invalidate_namespace", AsyncMock()),
        ):
            result = await meta_oauth.disconnect_connection("amalie", "meta-asset", "user-amalie")
        patch_payload = legacy_update.await_args.kwargs["patch"]
        self.assertEqual(patch_payload["status"], "disconnected")
        self.assertIsNone(patch_payload["encrypted_access_token"])
        self.assertIsNone(patch_payload["access_token"])
        generic_disconnect.assert_awaited_once_with("amalie", "meta-base", "user-amalie")
        self.assertEqual(audit.await_args.kwargs["details"]["external_revocation"], "not_supported")
        self.assertTrue(result["disconnect_result"]["local_token_removed"])

    async def test_finalize_persists_selected_connection_and_consumes_handoff(self):
        handoff_row = {
            "handoff": "handoff-1",
            "user_id": "user-amalie",
            "client_id": "amalie",
            "encrypted_access_token": "encrypted-token",
            "expires_at": "2026-09-01T00:00:00Z",
            "meta_user_json": {"id": "meta-user-1", "name": "Meta User"},
            "instagram_accounts_json": [
                {
                    "ig_user_id": "ig-1",
                    "username": "amalie",
                    "business_id": "page-1",
                    "business_name": "Amalie",
                },
                {
                    "ig_user_id": "ig-roove",
                    "username": "roove",
                    "business_id": "page-roove",
                    "business_name": "Roove",
                },
            ],
            "pages_json": [
                {"page_id": "page-1", "page_name": "Amalie"},
                {"page_id": "page-roove", "page_name": "Roove"},
            ],
            "ad_accounts_json": [
                {"ad_account_id": "act_amalie", "ad_account_name": "Ads Amalie"},
                {"ad_account_id": "act_roove", "ad_account_name": "Ads Roove"},
            ],
            "scopes_json": ["instagram_basic", "instagram_manage_insights"],
        }
        insert = AsyncMock(return_value={"id": "meta-connection-1"})
        update = AsyncMock()
        with (
            patch.object(meta_oauth, "_load_handoff_row", AsyncMock(return_value=handoff_row)),
            patch.object(meta_oauth, "decrypt_secret", return_value="provider-token"),
            patch.object(meta_oauth, "encrypt_secret", return_value="encrypted-provider-token"),
            patch.object(meta_oauth, "sb_select", AsyncMock(return_value=[])),
            patch.object(meta_oauth, "sb_insert", insert),
            patch.object(meta_oauth, "sb_update", update),
            patch.object(
                meta_oauth,
                "upsert_connection",
                AsyncMock(return_value={"id": "generic-meta-1", "provider": "meta"}),
            ) as generic_upsert,
            patch.object(meta_oauth, "invalidate_namespace", AsyncMock()),
        ):
            result = await meta_oauth.save_connections(
                user_id="user-amalie",
                client_id="amalie",
                handoff="handoff-1",
                page_ids=["page-1"],
                instagram_ig_user_ids=["ig-1"],
                ad_account_ids=[],
            )

        self.assertEqual(result["saved_count"], 1)
        inserted_row = insert.await_args.args[1]
        self.assertEqual(inserted_row["client_id"], "amalie")
        self.assertEqual(inserted_row["ig_user_id"], "ig-1")
        self.assertNotEqual(inserted_row["ig_user_id"], "ig-roove")
        self.assertEqual(inserted_row["encrypted_access_token"], "encrypted-provider-token")
        self.assertIsNone(inserted_row["access_token"])
        handoff_update = next(
            call for call in update.await_args_list
            if call.args and call.args[0] == "meta_oauth_handoffs" and "finalized_at" in call.kwargs["patch"]
        )
        self.assertIn("finalized_at", handoff_update.kwargs["patch"])
        self.assertEqual(handoff_update.kwargs["filters"]["finalized_at"], "is.null")
        self.assertEqual(generic_upsert.await_args.kwargs["client_id"], "amalie")
        self.assertEqual(generic_upsert.await_args.kwargs["provider"], "meta")
        self.assertEqual(generic_upsert.await_args.kwargs["external_key"], "meta:amalie")
        self.assertEqual(generic_upsert.await_args.kwargs["status"], "connected")
        self.assertEqual(generic_upsert.await_args.kwargs["metadata"]["meta_user_id"], "meta-user-1")

    async def test_discover_assets_does_not_consume_or_delete_handoff(self):
        with (
            patch.object(
                meta_oauth,
                "_load_handoff_row",
                AsyncMock(
                    return_value={
                        "handoff": "handoff-1",
                        "user_id": "user-amalie",
                        "client_id": "amalie",
                        "instagram_accounts_json": [],
                        "ad_accounts_json": [],
                        "scopes_json": [],
                    }
                ),
            ),
            patch.object(meta_oauth, "sb_update", AsyncMock()) as update,
            patch.object(meta_oauth, "sb_delete", AsyncMock()) as delete,
        ):
            result = await meta_oauth.read_discovery_handoff(
                handoff="handoff-1", user_id="user-amalie", client_id="amalie"
            )
        self.assertEqual(result["handoff"], "handoff-1")
        update.assert_not_awaited()
        delete.assert_not_awaited()

    async def test_repeated_connection_row_finalize_updates_instead_of_inserting(self):
        row = {
            "client_id": "amalie",
            "platform": "instagram",
            "connection_type": "organic",
            "ig_user_id": "ig-1",
            "ad_account_id": "",
        }
        with (
            patch.object(
                meta_oauth,
                "sb_select",
                AsyncMock(side_effect=[[{"id": "existing-1"}], [{"id": "existing-1", **row}]]),
            ),
            patch.object(meta_oauth, "sb_update", AsyncMock()) as update,
            patch.object(meta_oauth, "sb_insert", AsyncMock()) as insert,
        ):
            saved = await meta_oauth._save_connection_row(row)

        self.assertEqual(saved["id"], "existing-1")
        update.assert_awaited_once()
        insert.assert_not_awaited()


class GoogleAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    def test_google_403_diagnostic_contains_no_request_or_token_data(self):
        response = httpx.Response(
            403,
            json={
                "error": {
                    "status": "PERMISSION_DENIED",
                    "message": "Analytics Admin API has not been used",
                    "details": [{"reason": "SERVICE_DISABLED"}],
                }
            },
        )
        diagnostic = google_oauth._sanitized_google_error(response)
        self.assertEqual(diagnostic["http_status"], 403)
        self.assertEqual(diagnostic["reasons"], ["SERVICE_DISABLED"])
        self.assertNotIn("headers", diagnostic)
        self.assertNotIn("access_token", str(diagnostic))

    async def test_disconnected_google_connection_cannot_reuse_local_token(self):
        with patch.object(
            google_oauth,
            "get_connection",
            AsyncMock(
                return_value={
                    "id": "ga4-connection",
                    "provider": "ga4",
                    "status": "disconnected",
                    "_token": '{"access_token":"must-not-be-used"}',
                }
            ),
        ):
            with self.assertRaises(google_oauth.IntegrationError) as raised:
                await google_oauth.get_google_access_token("amalie", "ga4-connection")
        self.assertEqual(raised.exception.code, "GOOGLE_CONNECTION_DISCONNECTED")

    async def test_product_oauth_requests_only_the_required_scope(self):
        with (
            patch.object(
                google_oauth,
                "settings",
                return_value={
                    "client_id": "google-client",
                    "client_secret": "secret",
                    "redirect_uri": "https://api.example.com/api/oauth/google/callback",
                },
            ),
            patch.object(
                google_oauth,
                "create_oauth_state",
                AsyncMock(return_value="signed-state"),
            ) as create_state,
        ):
            ga4_url = await google_oauth.authorization_url(
                user_id="user-amalie", client_id="amalie", product="ga4"
            )
            ads_url = await google_oauth.authorization_url(
                user_id="user-amalie", client_id="amalie", product="ads"
            )

        ga4_scope = parse_qs(urlparse(ga4_url).query)["scope"][0]
        ads_scope = parse_qs(urlparse(ads_url).query)["scope"][0]
        self.assertIn("analytics.readonly", ga4_scope)
        self.assertNotIn("adwords", ga4_scope)
        self.assertIn("adwords", ads_scope)
        self.assertNotIn("analytics.readonly", ads_scope)
        self.assertEqual(create_state.await_args_list[0].kwargs["context"], {"integration_product": "ga4"})
        self.assertEqual(create_state.await_args_list[1].kwargs["context"], {"integration_product": "google_ads"})

    async def test_reauthorization_preserves_existing_refresh_token_and_selection(self):
        existing = {
            "id": "connection-1",
            "provider": "ga4",
            "external_key": "google-user-a",
            "status": "connected",
            "encrypted_token": "encrypted-existing-token",
            "metadata": {"ga4_property_id": "123456"},
        }
        with (
            patch.object(google_oauth, "sb_select", AsyncMock(return_value=[existing])),
            patch.object(
                google_oauth,
                "decrypt_secret",
                return_value='{"refresh_token":"preserved-refresh"}',
            ),
            patch.object(
                google_oauth,
                "upsert_connection",
                AsyncMock(return_value={"id": "connection-1"}),
            ) as upsert,
        ):
            await google_oauth.save_google_authorization(
                client_id="amalie",
                user_id="user-amalie",
                token={"access_token": "new-access", "expires_in": 3600},
                identity={"sub": "google-user-a", "email": "a@example.com"},
                product="ga4",
            )

        token_payload = upsert.await_args.kwargs["token_payload"]
        self.assertIn("preserved-refresh", token_payload)
        self.assertEqual(
            upsert.await_args.kwargs["metadata"]["ga4_property_id"],
            "123456",
        )

    async def test_second_active_google_identity_replaces_old_product_credential(self):
        update = AsyncMock()
        with (
            patch.object(
                google_oauth,
                "sb_select",
                AsyncMock(
                    return_value=[
                        {"id": "old-ga4", "provider": "ga4", "external_key": "google-user-a", "status": "connected"}
                    ]
                ),
            ),
            patch.object(google_oauth, "sb_update", update),
            patch.object(google_oauth, "upsert_connection", AsyncMock(return_value={"id": "new-ga4"})),
        ):
            await google_oauth.save_google_authorization(
                    client_id="amalie",
                    user_id="user-amalie",
                    token={
                        "access_token": "access",
                        "refresh_token": "refresh",
                        "expires_in": 3600,
                    },
                    identity={"sub": "google-user-b", "email": "b@example.com"},
                    product="ga4",
                )
        self.assertEqual(update.await_args.kwargs["filters"]["id"], "eq.old-ga4")
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "disconnected")

    async def test_ga4_never_reuses_google_ads_refresh_token(self):
        existing_ads = {
            "id": "ads-connection",
            "provider": "google_ads",
            "external_key": "google-user-a",
            "status": "connected",
            "encrypted_token": "encrypted-ads-token",
        }
        with (
            patch.object(google_oauth, "sb_select", AsyncMock(return_value=[existing_ads])),
            patch.object(google_oauth, "decrypt_secret") as decrypt,
        ):
            with self.assertRaisesRegex(RuntimeError, "refresh_token"):
                await google_oauth.save_google_authorization(
                    client_id="amalie",
                    user_id="user-amalie",
                    token={"access_token": "ga4-access", "expires_in": 3600},
                    identity={"sub": "google-user-a", "email": "a@example.com"},
                    product="ga4",
                )
        decrypt.assert_not_called()

    async def test_missing_developer_token_has_clear_pending_status(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GOOGLE_ADS_DEVELOPER_TOKEN", None)
            with self.assertRaises(google_oauth.IntegrationError) as raised:
                await google_oauth.list_google_ads_accounts("amalie", "connection-1")
        self.assertEqual(raised.exception.code, "GOOGLE_ADS_SETUP_REQUIRED")
        self.assertEqual(raised.exception.status_code, 409)

    async def test_ads_accounts_uses_supported_version_without_customer_headers(self):
        response = httpx.Response(
            200,
            request=httpx.Request("GET", "https://googleads.googleapis.com/v25/customers:listAccessibleCustomers"),
            headers={"request-id": "google-req-1"},
            json={"resourceNames": ["customers/1234567890"]},
        )

        class FakeClient:
            def __init__(self): self.url = ""; self.headers = {}
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return None
            async def get(self, url, *, headers):
                self.url, self.headers = url, headers
                return response

        fake = FakeClient()
        with (
            patch.dict(os.environ, {"GOOGLE_ADS_DEVELOPER_TOKEN": "developer-safe", "GOOGLE_ADS_API_VERSION": "v25"}),
            patch.object(google_oauth, "_access_token", AsyncMock(return_value="access-secret")),
            patch.object(google_oauth.httpx, "AsyncClient", return_value=fake),
        ):
            result = await google_oauth.list_google_ads_accounts("amalie", "ads-1", request_id="req-local")
        self.assertEqual(fake.url, "https://googleads.googleapis.com/v25/customers:listAccessibleCustomers")
        self.assertNotIn("login-customer-id", fake.headers)
        self.assertEqual(result["accounts"][0]["customer_id"], "1234567890")
        self.assertEqual(result["google_request_id"], "google-req-1")

    async def test_ads_accounts_maps_sunset_endpoint_404_without_exposing_credentials(self):
        response = httpx.Response(
            404,
            request=httpx.Request("GET", "https://googleads.googleapis.com/v19/customers:listAccessibleCustomers"),
            headers={"request-id": "google-req-404"},
            json={"error": {"status": "NOT_FOUND", "message": "Requested entity was not found."}},
        )

        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return None
            async def get(self, *args, **kwargs): return response

        output = io.StringIO()
        with (
            patch.dict(os.environ, {"GOOGLE_ADS_DEVELOPER_TOKEN": "developer-secret", "GOOGLE_ADS_API_VERSION": "v19"}),
            patch.object(google_oauth, "_access_token", AsyncMock(return_value="access-secret")),
            patch.object(google_oauth.httpx, "AsyncClient", return_value=FakeClient()),
            redirect_stdout(output),
        ):
            with self.assertRaises(google_oauth.IntegrationError) as raised:
                await google_oauth.list_google_ads_accounts("amalie", "ads-1", request_id="req-local")
        self.assertEqual(raised.exception.code, "GOOGLE_ADS_API_VERSION_UNAVAILABLE")
        self.assertNotIn("developer-secret", output.getvalue())
        self.assertNotIn("access-secret", output.getvalue())


class GenericDisconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_clears_token_and_records_one_complete_audit(self):
        current = {
            "id": "connection-1",
            "client_id": "amalie",
            "provider": "ga4",
            "status": "connected",
            "encrypted_token": "ciphertext",
            "external_key": "google-user",
            "scopes": ["analytics.readonly"],
            "metadata": {"ga4_property_id": "123"},
        }
        update = AsyncMock(return_value=[{**current, "status": "disconnected", "encrypted_token": ""}])
        audit = AsyncMock()
        with (
            patch.object(generic_connections, "get_connection", AsyncMock(return_value=current)),
            patch.object(generic_connections, "sb_update", update),
            patch.object(generic_connections, "audit_connection", audit),
            patch.object(generic_connections, "invalidate_namespace", AsyncMock()),
        ):
            result = await generic_connections.disconnect_generic_connection(
                "amalie", "connection-1", "user-amalie"
            )
        payload = update.await_args.kwargs["patch"]
        self.assertEqual(payload["encrypted_token"], "")
        self.assertIsNone(payload["token_expires_at"])
        self.assertNotIn("metadata", payload)
        self.assertNotIn("external_key", payload)
        self.assertNotIn("scopes", payload)
        self.assertEqual(audit.await_args.kwargs["details"]["external_revocation"], "not_supported")
        self.assertTrue(result["disconnect_result"]["local_token_removed"])

    async def test_repeated_disconnect_is_idempotent_without_patch_or_audit(self):
        disconnected = {
            "id": "connection-1",
            "client_id": "amalie",
            "provider": "ga4",
            "status": "disconnected",
            "encrypted_token": "",
        }
        with (
            patch.object(generic_connections, "get_connection", AsyncMock(return_value=disconnected)),
            patch.object(generic_connections, "sb_update", AsyncMock()) as update,
            patch.object(generic_connections, "audit_connection", AsyncMock()) as audit,
        ):
            result = await generic_connections.disconnect_generic_connection(
                "amalie", "connection-1", "user-amalie"
            )
        update.assert_not_awaited()
        audit.assert_not_awaited()
        self.assertEqual(result["disconnect_result"]["local_status"], "already_disconnected")


class MetaAdsSyncOutcomeTests(unittest.IsolatedAsyncioTestCase):
    def test_zero_account_aggregates_are_no_data_not_success(self):
        self.assertEqual(
            ads_sync._classify_sync_outcome(
                account_rows=[], persisted_account_rows=0, upserts=[{"upserted": 0}]
            ),
            "no_data",
        )

    def test_persisted_account_aggregate_can_be_partial_or_success(self):
        account = [{"spend": "10.00", "impressions": "100"}]
        self.assertEqual(
            ads_sync._classify_sync_outcome(
                account_rows=account,
                persisted_account_rows=1,
                upserts=[{"upserted": 1}, {"skipped": True}],
            ),
            "partial",
        )
        self.assertEqual(
            ads_sync._classify_sync_outcome(
                account_rows=account,
                persisted_account_rows=1,
                upserts=[{"upserted": 1}],
            ),
            "success",
        )

    async def test_no_data_does_not_advance_last_success_timestamp(self):
        with patch.object(meta_tokens, "_patch_connection", AsyncMock()) as patch_connection:
            await meta_tokens.mark_connection_sync_no_data("meta-connection", "zero aggregates")
        payload = patch_connection.await_args.args[1]
        self.assertEqual(payload["last_sync_status"], "skipped")
        self.assertNotIn("last_sync_at", payload)
        self.assertNotIn("last_synced_at", payload)


if __name__ == "__main__":
    unittest.main()
