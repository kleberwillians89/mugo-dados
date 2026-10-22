"""Rota de diagnóstico de origem FBITS: só administrador, leitura, com intervalo."""

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from routes import platform_admin as routes  # noqa: E402
from services import fbits_origin_probe  # noqa: E402
from services.integration_errors import IntegrationError  # noqa: E402

RESULT = {"ok": True, "empresa": "c1", "resumo_lista": {"veredito": "x"}, "pedidos_lista": []}


class FbitsProbeRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        routes._fbits_probe_last_run.clear()

    async def call(self, **kwargs):
        params = {"days": 14, "limit": 40, "detail": 10, "order_id": None, "authorization": "Bearer t"}
        params.update(kwargs)
        return await routes.platform_fbits_origin_probe("c1", **params)

    async def test_requires_platform_admin(self):
        denied = AsyncMock(side_effect=HTTPException(status_code=403, detail="no"))
        probe = AsyncMock(return_value=RESULT)
        with patch.object(routes, "require_platform_admin", denied), \
                patch.object(fbits_origin_probe, "probe_fbits_order_origin", probe):
            with self.assertRaises(HTTPException) as raised:
                await self.call()
        self.assertEqual(raised.exception.status_code, 403)
        probe.assert_not_awaited()

    async def test_runs_probe_and_applies_cooldown(self):
        probe = AsyncMock(return_value=RESULT)
        with patch.object(routes, "require_platform_admin", AsyncMock(return_value="u1")), \
                patch.object(fbits_origin_probe, "probe_fbits_order_origin", probe):
            self.assertEqual(await self.call(order_id=" 123 "), RESULT)
            probe.assert_awaited_once_with("c1", order_id="123", days=14, limit=40, detail_sample=10)
            with self.assertRaises(HTTPException) as raised:
                await self.call()
        self.assertEqual(raised.exception.status_code, 429)

    async def test_rejects_non_numeric_order(self):
        with patch.object(routes, "require_platform_admin", AsyncMock(return_value="u1")):
            with self.assertRaises(HTTPException) as raised:
                await self.call(order_id="abc;drop")
        self.assertEqual(raised.exception.status_code, 422)

    async def test_missing_connection_is_readable(self):
        error = IntegrationError("Nenhuma conexão FBITS encontrada para esta empresa.", status_code=404,
                                 code="FBITS_CONNECTION_NOT_FOUND", provider="fbits")
        with patch.object(routes, "require_platform_admin", AsyncMock(return_value="u1")), \
                patch.object(fbits_origin_probe, "probe_fbits_order_origin", AsyncMock(side_effect=error)):
            out = await self.call()
        self.assertEqual(out["ok"], False)
        self.assertEqual(out["code"], "FBITS_CONNECTION_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
