import asyncio
import sys
import os
import json
import unittest
from unittest.mock import AsyncMock, patch

# Ensure server package importable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestMetaOrganicActivate(unittest.TestCase):
    def _dummy_request(self):
        class Dummy:
            state = type("s", (), {"request_id": "req-test"})

        return Dummy()

    def test_success_updates_meta_connections_and_persists(self):
        success_sync_result = {
            "ok": True,
            "rows_profile": 1,
            "rows_media": 1,
            "rows_comments": 1,
            "rows_upserted": 3,
        }

        with patch("server.routes.meta_legacy.require_user_id", new=AsyncMock(return_value="user-test")), \
            patch("server.routes.meta_legacy.require_client_role", new=AsyncMock(return_value="client-test")), \
            patch("server.routes.meta_legacy.activate_meta_organic_assets", new=AsyncMock(return_value={"organic_connection_id": "organic-1", "authorization_connection_id": "auth-1"})), \
            patch("server.routes.meta_legacy.sync_instagram_connection", new=AsyncMock(return_value=success_sync_result)) as sync_mock, \
            patch("server.routes.meta_legacy.finalize_meta_organic_activation", new=AsyncMock(return_value={"last_sync_at": "2026-08-05T15:00:00+00:00"})) as finalize_mock:
            import server.routes.meta_legacy as ml

            res = asyncio.run(
                ml.api_activate_meta_organic(
                    "auth-1", {"page_id": "p", "instagram_id": "ig-123"}, self._dummy_request(), client_id=None, x_client_id=None, authorization=None
                )
            )

            self.assertTrue(res.get("ok") is True)
            self.assertTrue(str(res.get("organic_connection_id") or "").strip())
            self.assertTrue((res.get("initial_sync") or {}).get("ok") is True)

            sync_mock.assert_awaited()
            finalize_mock.assert_awaited()

    def test_success_zero_media_records_still_success(self):
        success_sync_result = {"ok": True, "rows_profile": 1, "rows_media": 0, "rows_comments": 0, "rows_upserted": 1}

        with patch("server.routes.meta_legacy.require_user_id", new=AsyncMock(return_value="user-test")), \
            patch("server.routes.meta_legacy.require_client_role", new=AsyncMock(return_value="client-test")), \
            patch("server.routes.meta_legacy.activate_meta_organic_assets", new=AsyncMock(return_value={"organic_connection_id": "organic-1", "authorization_connection_id": "auth-1"})), \
            patch("server.routes.meta_legacy.sync_instagram_connection", new=AsyncMock(return_value=success_sync_result)) as sync_mock, \
            patch("server.routes.meta_legacy.finalize_meta_organic_activation", new=AsyncMock(return_value={"last_sync_at": "2026-08-05T15:00:00+00:00"})) as finalize_mock:
            import server.routes.meta_legacy as ml

            res = asyncio.run(
                ml.api_activate_meta_organic(
                    "auth-1", {"page_id": "p", "instagram_id": "ig-123"}, self._dummy_request(), client_id=None, x_client_id=None, authorization=None
                )
            )

            self.assertTrue(res.get("ok") is True)
            self.assertTrue((res.get("initial_sync") or {}).get("ok") is True)
            sync_mock.assert_awaited()
            finalize_mock.assert_awaited()

    def test_error_records_error_and_releases_lock(self):
        # sync raises at await time
        with patch("server.routes.meta_legacy.require_user_id", new=AsyncMock(return_value="user-test")), \
            patch("server.routes.meta_legacy.require_client_role", new=AsyncMock(return_value="client-test")), \
            patch("server.routes.meta_legacy.activate_meta_organic_assets", new=AsyncMock(return_value={"organic_connection_id": "organic-1", "authorization_connection_id": "auth-1"})), \
            patch("server.routes.meta_legacy.sync_instagram_connection", new=AsyncMock(side_effect=RuntimeError("simulated sync failure"))) as sync_mock, \
            patch("server.routes.meta_legacy.finalize_meta_organic_activation", new=AsyncMock(return_value=None)) as finalize_mock:
            import server.routes.meta_legacy as ml

            res = asyncio.run(
                ml.api_activate_meta_organic(
                    "auth-1", {"page_id": "p", "instagram_id": "ig-123"}, self._dummy_request(), client_id=None, x_client_id=None, authorization=None
                )
            )

            # on error initial_sync.ok should be False and finalize still awaited with None return
            self.assertTrue(res.get("ok") is False)
            self.assertTrue((res.get("initial_sync") or {}).get("ok") is False)
            sync_mock.assert_awaited()
            finalize_mock.assert_awaited()


if __name__ == "__main__":
    unittest.main()
