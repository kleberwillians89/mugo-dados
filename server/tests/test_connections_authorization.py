import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from routes import connections


class ConnectionAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_connections_uses_read_permission(self):
        with (
            patch.object(connections, "require_client_read", AsyncMock(return_value="company-1")) as read,
            patch.object(
                connections,
                "list_generic_connections",
                AsyncMock(return_value=[{"id": "connection-1", "provider": "shopify"}]),
            ),
        ):
            result = await connections.list_connections(
                client_id="company-1",
                x_client_id=None,
                authorization="Bearer valid",
            )
        read.assert_awaited_once_with("company-1", "Bearer valid")
        self.assertEqual(result["client_id"], "company-1")
        self.assertEqual(result["connections"][0]["provider"], "shopify")

    async def test_connection_catalog_keeps_unavailable_platforms_truthful(self):
        with (
            patch.object(connections, "require_client_read", AsyncMock(return_value="company-1")),
            patch.object(connections, "list_generic_connections", AsyncMock(return_value=[])),
        ):
            result = await connections.list_connections(
                client_id="company-1",
                x_client_id=None,
                authorization="Bearer valid",
            )
        providers = {provider["id"]: provider for provider in result["providers"]}
        self.assertEqual(providers["tiktok"]["availability"], "platform_update_pending")
        self.assertEqual(providers["pinterest"]["availability"], "platform_update_pending")
