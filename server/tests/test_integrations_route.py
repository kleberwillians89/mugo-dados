from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from routes import integrations as routes
from services import tenant


async def _bypass_cache(*, namespace, key, ttl_seconds, loader):
    # Testes de rota não exercitam a camada de cache — cada teste deve
    # chamar o loader mockado diretamente, sem contaminação entre casos
    # que reutilizam a mesma chave (client_id="amalie").
    return await loader(), False


class ClientIntegrationsRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_agency_admin_accesses_amalie_without_per_client_membership(self):
        canonical = {"client_id": "amalie", "connections": []}
        memberships = [{"client_id": "outra-empresa", "role": "agency_admin"}]
        with (
            patch.object(tenant, "require_user_id", AsyncMock(return_value="agency-user")),
            patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=memberships)),
            patch.object(tenant, "sb_select", AsyncMock(return_value=[{"id": "amalie"}]), create=True),
            patch("services.ig_supabase.sb_select", AsyncMock(return_value=[{"id": "amalie"}])),
            patch("services.platform_admin.is_platform_admin", AsyncMock(return_value=False)),
            patch.object(routes, "get_client_connections", AsyncMock(return_value=canonical)),
            patch.object(routes, "get_cached_or_load", _bypass_cache),
        ):
            result = await routes.get_client_integrations("amalie", authorization="Bearer valid")

        self.assertTrue(result["ok"])
        self.assertEqual(result["client_id"], "amalie")

    async def test_unauthenticated_request_is_rejected(self):
        import os

        os.environ["ALLOW_NO_AUTH"] = "false"
        with patch.object(tenant, "get_user_id_from_bearer", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as raised:
                await routes.get_client_integrations("amalie", authorization=None)
        self.assertEqual(raised.exception.status_code, 401)

    async def test_viewer_cannot_read_technical_integrations(self):
        with (
            patch.object(tenant, "require_user_id", AsyncMock(return_value="viewer-amalie")),
            patch.object(tenant, "sb_get_client_id_for_user", AsyncMock(return_value="amalie")),
            patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=[{"client_id": "amalie", "role": "viewer"}])),
            patch("services.platform_admin.is_platform_admin", AsyncMock(return_value=False)),
        ):
            with self.assertRaises(HTTPException) as raised:
                await routes.get_client_integrations("amalie", authorization="Bearer valid")
        self.assertEqual(raised.exception.status_code, 403)

    async def test_viewer_cannot_read_a_different_company(self):
        with (
            patch.object(tenant, "require_user_id", AsyncMock(return_value="viewer-amalie")),
            patch.object(
                tenant,
                "sb_get_client_id_for_user",
                AsyncMock(side_effect=PermissionError("Usuário sem acesso ao client_id informado")),
            ),
            patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=[{"client_id": "amalie", "role": "viewer"}])),
            patch("services.platform_admin.is_platform_admin", AsyncMock(return_value=False)),
        ):
            with self.assertRaises(HTTPException) as raised:
                await routes.get_client_integrations("roove", authorization="Bearer valid")
        self.assertEqual(raised.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
