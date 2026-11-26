import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from services import ai_runtime
from services import ai_usage


class TenantAiRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_row_preserves_platform_managed_for_existing_clients(self):
        with patch.object(ai_runtime, "_row", AsyncMock(return_value=None)), patch.dict(
            os.environ, {"OPENAI_API_KEY": "platform-secret", "OPENAI_MODEL": "gpt-4.1-mini"}, clear=False
        ):
            runtime = await ai_runtime.resolve("tenant-a")
        self.assertEqual(runtime.mode, "platform_managed")
        self.assertEqual(runtime.api_key, "platform-secret")

    async def test_byok_never_falls_back_to_platform_key(self):
        row = {"mode": "byok", "model": "gpt-4.1-mini", "encrypted_api_key": None}
        with patch.object(ai_runtime, "_row", AsyncMock(return_value=row)), patch.dict(
            os.environ, {"OPENAI_API_KEY": "must-not-be-used"}, clear=False
        ):
            with self.assertRaises(ai_runtime.AiRuntimeError) as raised:
                await ai_runtime.resolve("tenant-a")
        self.assertEqual(raised.exception.code, "AI_BYOK_CREDENTIAL_MISSING")

    async def test_credentials_are_resolved_only_from_requested_tenant(self):
        async def row(client_id):
            return {"mode": "byok", "model": "gpt-4.1-mini", "encrypted_api_key": f"enc-{client_id}"}
        with patch.object(ai_runtime, "_row", AsyncMock(side_effect=row)), patch.object(
            ai_runtime, "decrypt_secret", side_effect=lambda value: value.replace("enc-", "key-")
        ):
            first = await ai_runtime.resolve("tenant-a")
            second = await ai_runtime.resolve("tenant-b")
            again = await ai_runtime.resolve("tenant-a")
        self.assertEqual((first.api_key, second.api_key, again.api_key), ("key-tenant-a", "key-tenant-b", "key-tenant-a"))

    async def test_byok_uses_tenant_selected_model_not_global_override(self):
        row = {"mode": "byok", "model": "gpt-4o-mini", "encrypted_api_key": "cipher"}
        with patch.object(ai_runtime, "_row", AsyncMock(return_value=row)), patch.object(ai_runtime, "decrypt_secret", return_value="key"):
            runtime = await ai_runtime.resolve("tenant-a", requested_model="gpt-4.1")
        self.assertEqual(runtime.model, "gpt-4o-mini")

    async def test_missing_explicit_tenant_uses_authorized_request_context(self):
        from services.tenant import _REQUEST_CLIENT
        token = _REQUEST_CLIENT.set("tenant-context")
        try:
            with patch.object(ai_runtime, "_row", AsyncMock(return_value=None)), patch.dict(
                os.environ, {"OPENAI_API_KEY": "platform-secret"}, clear=False
            ):
                runtime = await ai_runtime.resolve(None)
        finally:
            _REQUEST_CLIENT.reset(token)
        self.assertEqual(runtime.client_id, "tenant-context")

    async def test_save_encrypts_and_never_returns_secret(self):
        inserted = AsyncMock(return_value={"ok": True})
        public = {"client_id": "tenant-a", "mode": "byok", "model": "gpt-4.1-mini", "has_credential": True}
        with patch.object(ai_runtime, "_row", AsyncMock(side_effect=[None, {"mode": "byok", "encrypted_api_key": "cipher", "model": "gpt-4.1-mini"}])), \
             patch.object(ai_runtime, "validate_openai_key", AsyncMock()), \
             patch.object(ai_runtime, "encrypt_secret", return_value="cipher"), \
             patch.object(ai_runtime, "sb_insert", inserted), \
             patch.object(ai_runtime, "public_settings", AsyncMock(return_value=public)):
            result = await ai_runtime.save_settings(client_id="tenant-a", user_id="user-a", mode="byok", model="gpt-4.1-mini", api_key="sk-client-secret")
        payload = inserted.await_args.args[1]
        self.assertEqual(payload["encrypted_api_key"], "cipher")
        self.assertNotIn("sk-client-secret", str(result))

    def test_limits_and_model_allowlist(self):
        self.assertEqual(ai_runtime.bounded_output_tokens("chat", 9000, "gpt-4.1-mini"), 4096)
        with self.assertRaises(ai_runtime.AiRuntimeError):
            ai_runtime.validate_model("unapproved-model")

    def test_byok_usage_is_not_counted_as_platform_cost(self):
        row = ai_usage.build_row(feature="x", model="gpt-4.1-mini", client_id="tenant-a",
                                 credential_mode="byok", body={"usage": {"input_tokens": 1000, "output_tokens": 1000}})
        self.assertEqual(row["credential_mode"], "byok")
        self.assertIsNone(row["cost_usd"])

    def test_usage_report_separates_byok_from_platform_consumption(self):
        rows = [
            ai_usage.build_row(feature="chat", model="gpt-4.1-mini", client_id="tenant-a",
                               credential_mode="byok", body={"usage": {"input_tokens": 40, "output_tokens": 10}}),
            ai_usage.build_row(feature="chat", model="gpt-4.1-mini", client_id="tenant-b",
                               credential_mode="platform_managed", body={"usage": {"input_tokens": 20, "output_tokens": 5}}),
        ]
        report = ai_usage.aggregate(rows, {"tenant-a": "A", "tenant-b": "B"})
        self.assertEqual(report["credential_modes"]["byok"]["total_tokens"], 50)
        self.assertEqual(report["credential_modes"]["platform_managed"]["total_tokens"], 25)
        self.assertEqual(report["totals"]["cost_usd"], rows[1]["cost_usd"])


if __name__ == "__main__":
    unittest.main()
