from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from server.services import connection_resolver, meta_tokens
from server.services.integration_errors import IntegrationError


def operational(connection_id: str, *, platform: str, connection_type: str, status: str = "active"):
    return {
        "id": connection_id,
        "client_id": "amalie",
        "platform": platform,
        "connection_type": connection_type,
        "status": status,
        "requires_reauth": False,
        "is_active": True,
        "ad_account_id": "act_123" if platform == "meta_ads" else "",
        "last_sync_status": "error" if status == "error" else "success",
    }


class ProviderResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_generic_provider_resolves_unique_connection_without_browser_state(self):
        row = {
            "id": "ga4-1", "client_id": "amalie", "provider": "ga4",
            "status": "error", "requires_reauth": False,
        }
        select = AsyncMock(return_value=[row])
        resolved = await connection_resolver.resolve_generic_connection(
            client_id="amalie", provider="ga4", require_token=False, select_fn=select,
        )

        self.assertEqual(resolved["id"], "ga4-1")
        select.assert_awaited_once_with(
            "integration_connections",
            filters={"client_id": "eq.amalie", "provider": "eq.ga4"},
            limit=100,
        )

    async def test_generic_provider_ambiguity_is_explicit(self):
        rows = [
            {"id": "shop-1", "client_id": "amalie", "provider": "shopify", "status": "connected"},
            {"id": "shop-2", "client_id": "amalie", "provider": "shopify", "status": "connected"},
        ]
        with self.assertRaises(IntegrationError) as raised:
            await connection_resolver.resolve_generic_connection(
                client_id="amalie", provider="shopify", require_token=False,
                select_fn=AsyncMock(return_value=rows),
            )
        self.assertEqual(raised.exception.code, "CONNECTION_AMBIGUOUS")

    async def test_unique_paid_and_organic_connections_resolve_independently_without_browser_state(self):
        rows = [
            operational("organic-1", platform="instagram", connection_type="organic"),
            operational("paid-1", platform="meta_ads", connection_type="paid"),
        ]
        with patch.object(connection_resolver, "sb_select", AsyncMock(return_value=rows)):
            organic = await connection_resolver.resolve_connection_for_scope(
                client_id="amalie", platform="instagram", connection_type="organic",
            )
            paid = await connection_resolver.resolve_connection_for_scope(
                client_id="amalie", platform="meta_ads", connection_type="paid", require_ad_account=True,
            )

        self.assertEqual(organic["connection_id"], "organic-1")
        self.assertEqual(paid["connection_id"], "paid-1")
        self.assertEqual(organic["source"], "unique_scope")
        self.assertEqual(paid["source"], "unique_scope")

    async def test_sync_error_connection_remains_resolvable_and_connected(self):
        row = operational("paid-1", platform="meta_ads", connection_type="paid", status="error")
        with patch.object(connection_resolver, "sb_select", AsyncMock(return_value=[row])):
            resolved = await connection_resolver.resolve_connection_for_scope(
                client_id="amalie", platform="meta_ads", connection_type="paid", require_ad_account=True,
            )

        self.assertEqual(resolved["connection_id"], "paid-1")
        serialized = meta_tokens.serialize_connection_status(row)
        self.assertEqual(serialized["connection_state"], "connected")
        self.assertEqual(serialized["sync_state"], "error")

    async def test_real_ambiguity_is_not_silently_hidden(self):
        rows = [
            operational("paid-1", platform="meta_ads", connection_type="paid"),
            operational("paid-2", platform="meta_ads", connection_type="paid"),
        ]
        with patch.object(connection_resolver, "sb_select", AsyncMock(return_value=rows)):
            with self.assertRaises(IntegrationError) as raised:
                await connection_resolver.resolve_connection_for_scope(
                    client_id="amalie", platform="meta_ads", connection_type="paid", require_ad_account=True,
                )

        self.assertEqual(raised.exception.code, "CONNECTION_AMBIGUOUS")


class SyncStatePersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_error_does_not_mark_connection_disconnected(self):
        update = AsyncMock(return_value=[])
        with patch.object(meta_tokens, "sb_update", update):
            await meta_tokens.mark_connection_sync_error("paid-1", "upstream timeout", requires_reauth=False)

        patch_payload = update.await_args.kwargs["patch"]
        self.assertEqual(patch_payload["status"], "active")
        self.assertTrue(patch_payload["is_active"])
        self.assertFalse(patch_payload["requires_reauth"])
        self.assertEqual(patch_payload["last_sync_status"], "error")


if __name__ == "__main__":
    unittest.main()
