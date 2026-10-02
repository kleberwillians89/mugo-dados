from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import connections_service as svc


def _integration_row(**overrides):
    row = {
        "id": "auth-meta-1",
        "client_id": "amalie",
        "provider": "meta",
        "status": "connected",
        "account_id": "act_1",
        "account_name": "Amalie",
        "last_error": None,
        "metadata": {},
        "disconnected_at": None,
        "updated_at": "2026-08-05T12:00:00+00:00",
    }
    row.update(overrides)
    return row


def _meta_operational_row(**overrides):
    row = {
        "id": "op-1",
        "client_id": "amalie",
        "platform": "meta_ads",
        "connection_type": "paid",
        "ad_account_id": "act_673785144083881",
        "ad_account_name": "Amalie",
        "ig_user_id": "",
        "username": "",
        "last_sync_at": "2026-08-05T10:00:00+00:00",
        "last_sync_status": "success",
        "last_error": None,
        "updated_at": "2026-08-05T10:00:00+00:00",
    }
    row.update(overrides)
    return row


class ConnectionsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_meta_row_from_meta_connections_is_merged_into_canonical_entry(self):
        integration_rows = [_integration_row()]
        operational_rows = [
            _meta_operational_row(),
            _meta_operational_row(
                id="op-2", platform="instagram", connection_type="organic",
                ad_account_id="", ad_account_name="", ig_user_id="17841439891244293",
                username="amalie_online", last_sync_at="2026-08-05T09:00:00+00:00",
            ),
        ]
        with (
            patch.object(svc, "_load_integration_rows", AsyncMock(return_value=integration_rows)),
            patch.object(svc, "_load_meta_operational_rows", AsyncMock(return_value=operational_rows)),
        ):
            result = await svc.get_client_connections("amalie")

        self.assertEqual(result["client_id"], "amalie")
        entries = [c for c in result["connections"] if c["provider"] == "meta"]
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["assets"]["ad_account_id"], "act_673785144083881")
        self.assertEqual(entry["assets"]["instagram_account_id"], "17841439891244293")
        self.assertEqual(entry["assets"]["instagram_account_name"], "amalie_online")
        self.assertEqual(entry["sync_status"], "sync_success")
        self.assertIsNotNone(entry["last_successful_sync_at"])

    async def test_ga4_row_from_integration_connections_appears_with_selected_property(self):
        integration_rows = [
            _integration_row(
                id="auth-ga4-1", provider="ga4", account_name="Amalie GA4",
                metadata={"ga4_property_id": "333564548", "ga4_property_name": "Amalie - GA4"},
            )
        ]
        with (
            patch.object(svc, "_load_integration_rows", AsyncMock(return_value=integration_rows)),
            patch.object(svc, "_load_meta_operational_rows", AsyncMock(return_value=[])),
        ):
            result = await svc.get_client_connections("amalie")

        ga4_entries = [c for c in result["connections"] if c["provider"] == "ga4"]
        self.assertEqual(len(ga4_entries), 1)
        self.assertEqual(ga4_entries[0]["assets"]["property_id"], "333564548")
        self.assertEqual(ga4_entries[0]["assets"]["property_name"], "Amalie - GA4")
        self.assertEqual(ga4_entries[0]["status"], "connected")

    async def test_no_duplication_one_entry_per_provider_even_with_multiple_operational_rows(self):
        integration_rows = [_integration_row()]
        operational_rows = [
            _meta_operational_row(id="op-1"),
            _meta_operational_row(id="op-2", platform="instagram", connection_type="organic"),
        ]
        with (
            patch.object(svc, "_load_integration_rows", AsyncMock(return_value=integration_rows)),
            patch.object(svc, "_load_meta_operational_rows", AsyncMock(return_value=operational_rows)),
        ):
            result = await svc.get_client_connections("amalie")

        meta_entries = [c for c in result["connections"] if c["provider"] == "meta"]
        self.assertEqual(len(meta_entries), 1, "duas linhas operacionais não podem virar duas entradas meta")

    async def test_sync_error_does_not_erase_connection_or_selected_assets(self):
        integration_rows = [_integration_row()]
        operational_rows = [
            _meta_operational_row(
                last_sync_status="error", last_error="Meta retornou 500",
                last_sync_at="2026-08-05T11:00:00+00:00",
            )
        ]
        with (
            patch.object(svc, "_load_integration_rows", AsyncMock(return_value=integration_rows)),
            patch.object(svc, "_load_meta_operational_rows", AsyncMock(return_value=operational_rows)),
        ):
            result = await svc.get_client_connections("amalie")

        entry = next(c for c in result["connections"] if c["provider"] == "meta")
        self.assertEqual(entry["sync_status"], "sync_error")
        self.assertEqual(entry["last_error"], "Meta retornou 500")
        # A conexão e a conta selecionada continuam visíveis apesar do erro.
        self.assertEqual(entry["status"], "connected")
        self.assertEqual(entry["assets"]["ad_account_id"], "act_673785144083881")
        # Não houve sucesso nesta tentativa: não inventamos last_successful_sync_at.
        self.assertIsNone(entry["last_successful_sync_at"])

    async def test_token_expired_preserves_historical_assets(self):
        integration_rows = [_integration_row(status="token_expired")]
        operational_rows = [_meta_operational_row()]
        with (
            patch.object(svc, "_load_integration_rows", AsyncMock(return_value=integration_rows)),
            patch.object(svc, "_load_meta_operational_rows", AsyncMock(return_value=operational_rows)),
        ):
            result = await svc.get_client_connections("amalie")

        entry = next(c for c in result["connections"] if c["provider"] == "meta")
        self.assertEqual(entry["status"], "token_expired")
        # Token expirado não apaga dados históricos de sync nem a conta selecionada.
        self.assertEqual(entry["assets"]["ad_account_id"], "act_673785144083881")
        self.assertEqual(entry["last_sync_at"], "2026-08-05T10:00:00+00:00")

    async def test_disconnected_at_wins_over_everything_else(self):
        integration_rows = [_integration_row(status="connected", disconnected_at="2026-08-01T00:00:00+00:00")]
        with (
            patch.object(svc, "_load_integration_rows", AsyncMock(return_value=integration_rows)),
            patch.object(svc, "_load_meta_operational_rows", AsyncMock(return_value=[])),
        ):
            result = await svc.get_client_connections("amalie")
        entry = next(c for c in result["connections"] if c["provider"] == "meta")
        self.assertEqual(entry["status"], "disconnected")

    async def test_meta_authorized_without_selected_assets_needs_configuration(self):
        integration_rows = [_integration_row(metadata={})]
        with (
            patch.object(svc, "_load_integration_rows", AsyncMock(return_value=integration_rows)),
            patch.object(svc, "_load_meta_operational_rows", AsyncMock(return_value=[])),
        ):
            result = await svc.get_client_connections("amalie")
        entry = next(c for c in result["connections"] if c["provider"] == "meta")
        self.assertEqual(entry["status"], "needs_configuration")

    async def test_meta_business_only_is_connected_without_fake_operational_assets(self):
        integration_rows = [_integration_row(
            account_id=None,
            account_name=None,
            metadata={
                "selected_business_id": "1162363888929790",
                "selected_business_name": "origami_investimentos",
                "coverage": "organization_only",
            },
        )]
        with (
            patch.object(svc, "_load_integration_rows", AsyncMock(return_value=integration_rows)),
            patch.object(svc, "_load_meta_operational_rows", AsyncMock(return_value=[])),
        ):
            result = await svc.get_client_connections("origami")
        entry = next(c for c in result["connections"] if c["provider"] == "meta")
        self.assertEqual(entry["status"], "connected")
        self.assertEqual(entry["assets"]["business_id"], "1162363888929790")
        self.assertEqual(entry["assets"]["business_name"], "origami_investimentos")
        self.assertIsNone(entry["assets"]["ad_account_id"])
        self.assertIsNone(entry["assets"]["instagram_account_id"])
        self.assertIsNone(entry["sync_status"])

    async def test_no_tokens_leak_in_canonical_response(self):
        integration_rows = [
            _integration_row(
                encrypted_access_token="secret-cipher",
                encrypted_refresh_token="secret-cipher-2",
            )
        ]
        with (
            patch.object(svc, "_load_integration_rows", AsyncMock(return_value=integration_rows)),
            patch.object(svc, "_load_meta_operational_rows", AsyncMock(return_value=[])),
        ):
            result = await svc.get_client_connections("amalie")
        dumped = str(result)
        self.assertNotIn("secret-cipher", dumped)

    async def test_shopify_and_google_ads_entries_use_real_fields_not_placeholders(self):
        integration_rows = [
            _integration_row(
                id="auth-shopify-1", provider="shopify", account_name="Amalie",
                metadata={"shop_domain": "amalie.myshopify.com"},
            ),
            _integration_row(
                id="auth-ads-1", provider="google_ads", account_name=None,
                metadata={"google_ads_customer_id": "1234567890"},
            ),
        ]
        with (
            patch.object(svc, "_load_integration_rows", AsyncMock(return_value=integration_rows)),
            patch.object(svc, "_load_meta_operational_rows", AsyncMock(return_value=[])),
        ):
            result = await svc.get_client_connections("amalie")

        shopify_entry = next(c for c in result["connections"] if c["provider"] == "shopify")
        self.assertEqual(shopify_entry["account"]["domain"], "amalie.myshopify.com")

        ads_entry = next(c for c in result["connections"] if c["provider"] == "google_ads")
        self.assertEqual(ads_entry["assets"]["customer_id"], "1234567890")
        # Sem nome descritivo disponível na API atual: não inventamos um rótulo.
        self.assertIsNone(ads_entry["account"]["name"])


if __name__ == "__main__":
    unittest.main()
