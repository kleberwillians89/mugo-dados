import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from fastapi import HTTPException
from routes import ai_settings


class AiSettingsAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_denied_before_reading_or_writing_secret_state(self):
        guard = AsyncMock(side_effect=HTTPException(status_code=403, detail="forbidden"))
        read = AsyncMock()
        with patch.object(ai_settings, "require_client_role", guard), patch.object(ai_settings, "public_settings", read):
            with self.assertRaises(HTTPException) as raised:
                await ai_settings.get_settings("tenant-b", authorization="Bearer user-a")
        self.assertEqual(raised.exception.status_code, 403)
        read.assert_not_awaited()

    async def test_client_admin_is_scoped_to_authorized_tenant(self):
        guard = AsyncMock(return_value="tenant-a")
        read = AsyncMock(return_value={"client_id": "tenant-a", "has_credential": False})
        with patch.object(ai_settings, "require_client_role", guard), patch.object(ai_settings, "public_settings", read):
            result = await ai_settings.get_settings("tenant-a", authorization="Bearer admin")
        guard.assert_awaited_once_with("tenant-a", "Bearer admin", allowed_roles=ai_settings.ADMINS)
        self.assertEqual(result["settings"]["client_id"], "tenant-a")

    async def test_denied_update_never_reaches_credential_service(self):
        guard = AsyncMock(side_effect=HTTPException(status_code=403, detail="forbidden"))
        save = AsyncMock()
        body = ai_settings.SettingsInput(mode="byok", model="gpt-4.1-mini", api_key="sk-client-secret-value")
        with patch.object(ai_settings, "require_client_role", guard), patch.object(ai_settings, "save_settings", save):
            with self.assertRaises(HTTPException) as raised:
                await ai_settings.put_settings("tenant-b", body, authorization="Bearer tenant-admin")
        self.assertEqual(raised.exception.status_code, 403)
        save.assert_not_awaited()

    async def test_authorized_update_uses_guarded_tenant_and_authenticated_author(self):
        guard = AsyncMock(return_value="tenant-a")
        user = AsyncMock(return_value="user-a")
        save = AsyncMock(return_value={"client_id": "tenant-a", "mode": "byok", "has_credential": True})
        body = ai_settings.SettingsInput(mode="byok", model="gpt-4.1-mini", api_key="sk-client-secret-value")
        with patch.object(ai_settings, "require_client_role", guard), patch.object(ai_settings, "require_user_id", user), \
             patch.object(ai_settings, "save_settings", save):
            result = await ai_settings.put_settings("tenant-a", body, authorization="Bearer tenant-admin")
        save.assert_awaited_once_with(client_id="tenant-a", user_id="user-a", mode="byok",
                                      model="gpt-4.1-mini", api_key="sk-client-secret-value")
        self.assertNotIn("api_key", result["settings"])


if __name__ == "__main__":
    unittest.main()
