import hashlib
import hmac
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock, patch

from server.services import oauth_state
from server.services import google_oauth
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
    "email",
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


class ShopifySecurityTests(unittest.TestCase):
    def test_invalid_domains_are_rejected(self):
        for value in ("evil.com", "https://shop.myshopify.com/path", "shop.myshopify.com.evil.com", ""):
            with self.assertRaises(RuntimeError):
                normalize_shop_domain(value)
        self.assertEqual(normalize_shop_domain("Minha-Loja.myshopify.com"), "minha-loja.myshopify.com")

    def test_callback_hmac(self):
        os.environ["SHOPIFY_CLIENT_ID"] = "client"
        os.environ["SHOPIFY_CLIENT_SECRET"] = "shopify-secret"
        os.environ["SHOPIFY_OAUTH_REDIRECT_URI"] = "http://localhost/callback"
        params = {"code": "code", "shop": "loja.myshopify.com", "state": "state", "timestamp": "1"}
        message = "&".join(f"{key}={value}" for key, value in sorted(params.items()))
        params["hmac"] = hmac.new(
            b"shopify-secret", message.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        self.assertTrue(verify_callback_hmac(params))
        params["hmac"] = "invalid"
        self.assertFalse(verify_callback_hmac(params))


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
                }
            ],
            "ad_accounts_json": [],
            "scopes_json": ["instagram_basic", "instagram_manage_insights"],
        }
        insert = AsyncMock(return_value={"id": "meta-connection-1"})
        with (
            patch.object(meta_oauth, "_load_handoff_row", AsyncMock(return_value=handoff_row)),
            patch.object(meta_oauth, "decrypt_secret", return_value="provider-token"),
            patch.object(meta_oauth, "encrypt_secret", return_value="encrypted-provider-token"),
            patch.object(meta_oauth, "sb_select", AsyncMock(return_value=[])),
            patch.object(meta_oauth, "sb_insert", insert),
            patch.object(meta_oauth, "sb_update", AsyncMock()),
            patch.object(meta_oauth, "sb_delete", AsyncMock()) as delete,
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
        self.assertEqual(inserted_row["encrypted_access_token"], "encrypted-provider-token")
        self.assertIsNone(inserted_row["access_token"])
        delete.assert_awaited_once()

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
    async def test_reauthorization_preserves_existing_refresh_token_and_selection(self):
        existing = {
            "id": "connection-1",
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
            )

        token_payload = upsert.await_args.kwargs["token_payload"]
        self.assertIn("preserved-refresh", token_payload)
        self.assertEqual(
            upsert.await_args.kwargs["metadata"]["ga4_property_id"],
            "123456",
        )

    async def test_second_active_google_identity_is_rejected(self):
        with patch.object(
            google_oauth,
            "sb_select",
            AsyncMock(
                return_value=[
                    {"external_key": "google-user-a", "status": "connected"}
                ]
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "já possui uma autorização Google"):
                await google_oauth.save_google_authorization(
                    client_id="amalie",
                    user_id="user-amalie",
                    token={
                        "access_token": "access",
                        "refresh_token": "refresh",
                        "expires_in": 3600,
                    },
                    identity={"sub": "google-user-b", "email": "b@example.com"},
                )

    async def test_missing_developer_token_has_clear_pending_status(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GOOGLE_ADS_DEVELOPER_TOKEN", None)
            result = await google_oauth.list_google_ads_accounts("amalie", "connection-1")
        self.assertFalse(result["available"])
        self.assertEqual(result["accounts"], [])
        self.assertIn("Developer Token do Google Ads pendente", result["reason"])


if __name__ == "__main__":
    unittest.main()
