import hashlib
import hmac
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from server.services import oauth_state
from server.services import google_oauth
from server.services.generic_connections import sanitize_connection
from server.services.invitations import invitation_is_usable
from server.services import shopify_oauth
from server.services.shopify_oauth import normalize_shop_domain, verify_callback_hmac
from server.services.meta_oauth import validate_page_selection


class OAuthStateTests(unittest.IsolatedAsyncioTestCase):
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


class GoogleAuthorizationTests(unittest.IsolatedAsyncioTestCase):
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
