"""Etapa 2B.1 — isolamento, autorização e estados comerciais sem enforcement."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routes import saas as routes
from services import commercial_modules as cm
from services import tenant_commercial_config as cfg


class ValidationTests(unittest.TestCase):
    def test_empty_is_explicit_not_missing(self):
        self.assertEqual(cfg.as_state("a", None)["state"], "not_configured")
        self.assertIsNone(cfg.as_state("a", None)["module_keys"])
        empty = cfg.as_state("a", {"module_keys": [], "version": 1})
        self.assertEqual(empty["state"], "explicitly_empty")
        self.assertEqual(empty["module_keys"], [])
        self.assertTrue(empty["configured"])

    def test_module_validation_and_basic_rights(self):
        for bad in (["redacao"], ["meta", "invalid"], ["meta", "meta"], "meta", None, [123]):
            with self.subTest(bad=bad), self.assertRaises(cfg.CommercialConfigError):
                cfg.validate_selection(bad)
        self.assertEqual(cfg.validate_selection(["social_media", "meta"]), ["meta", "social_media"])
        self.assertEqual(cm.BASIC_CAPABILITIES, frozenset({"briefing", "tasks"}))
        self.assertEqual(cm.COMMERCIAL_MODULES["social_media"].capabilities,
                         frozenset({"social_media", "redacao"}))


class StorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_tenant_isolation_and_switch(self):
        async def load(table, **kwargs):
            client = kwargs["filters"]["client_id"][3:]
            return [{"client_id": client, "module_keys": keys, "version": 1}] if (
                keys := {"a": ["meta"], "b": ["social_media"]}.get(client)) else []
        with patch.object(cfg, "sb_select", side_effect=load) as select:
            a = await cfg.get_configuration("a")
            b = await cfg.get_configuration("b")
            a2 = await cfg.get_configuration("a")
        self.assertEqual((a["module_keys"], b["module_keys"], a2["module_keys"]),
                         (["meta"], ["social_media"], ["meta"]))
        self.assertEqual(select.await_count, 3)

    async def test_atomic_rpc_and_optimistic_version(self):
        saved = {"client_id": "a", "module_keys": [], "version": 2}
        with patch.object(cfg, "sb_rpc", AsyncMock(return_value=saved)) as rpc:
            result = await cfg.save_configuration("a", [], expected_version=1, actor_user_id="actor")
        self.assertEqual(result["state"], "explicitly_empty")
        rpc.assert_awaited_once_with("save_tenant_commercial_modules", {
            "p_client_id": "a", "p_module_keys": [],
            "p_expected_version": 1, "p_actor_user_id": "actor",
        })

    async def test_write_failure_does_not_report_success(self):
        with patch.object(cfg, "sb_rpc", AsyncMock(side_effect=RuntimeError("db unavailable"))):
            with self.assertRaises(RuntimeError):
                await cfg.save_configuration("a", ["meta"], expected_version=None, actor_user_id="actor")

    async def test_invalid_write_never_reaches_database(self):
        with patch.object(cfg, "sb_rpc", AsyncMock()) as rpc:
            with self.assertRaises(cfg.CommercialConfigError):
                await cfg.save_configuration("a", ["redacao"], expected_version=None, actor_user_id="actor")
            rpc.assert_not_awaited()


class ResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_empty_never_grants_all_modules(self):
        explicit = {"configured": True, "module_keys": []}
        with patch.object(cfg, "get_configuration", AsyncMock(return_value=explicit)), \
             patch("services.saas.get_subscription", AsyncMock()) as subscription:
            result = await cm.resolve_tenant_modules("a")
        self.assertEqual(result["commercial_modules"], [])
        self.assertEqual(result["capabilities"], ["briefing", "tasks"])
        subscription.assert_not_awaited()
        self.assertFalse(result["enforcement_enabled"])

    async def test_selected_is_tenant_scoped(self):
        async def get(client_id):
            return {"configured": True, "module_keys": {"a": ["meta"], "b": ["social_media"]}[client_id]}
        with patch.object(cfg, "get_configuration", side_effect=get):
            a = await cm.resolve_tenant_modules("a")
            b = await cm.resolve_tenant_modules("b")
            a2 = await cm.resolve_tenant_modules("a")
        self.assertEqual(a["commercial_modules"], ["meta"])
        self.assertEqual(b["commercial_modules"], ["social_media"])
        self.assertIn("redacao", b["capabilities"])
        self.assertEqual(a2["commercial_modules"], ["meta"])

    async def test_missing_configuration_preserves_legacy(self):
        with patch.object(cfg, "get_configuration", AsyncMock(return_value={"configured": False})), \
             patch("services.saas.get_subscription", AsyncMock(return_value=None)):
            resolved = await cm.resolve_tenant_modules("a")
        self.assertEqual(set(resolved["commercial_modules"]), set(cm.COMMERCIAL_MODULES))
        self.assertFalse(resolved["configured"])

    async def test_unavailable_is_not_missing_or_unrestricted(self):
        with patch.object(cfg, "get_configuration", AsyncMock(side_effect=RuntimeError("db unavailable"))), \
             patch("services.saas.get_subscription", AsyncMock()) as subscription:
            result = await cm.resolve_tenant_modules("a")
        self.assertEqual(result["source"], "unavailable")
        self.assertEqual(result["commercial_modules"], [])
        self.assertIsNotNone(result["resolution_error"])
        subscription.assert_not_awaited()


class AuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_platform_admin(self):
        with patch.object(routes, "require_user_id", AsyncMock(return_value="platform")), \
             patch.object(routes, "is_platform_admin", AsyncMock(return_value=True)):
            self.assertEqual(await routes._commercial_admin("token"), "platform")

    async def test_agency_admin(self):
        with patch.object(routes, "require_user_id", AsyncMock(return_value="agency")), \
             patch.object(routes, "is_platform_admin", AsyncMock(return_value=False)), \
             patch.object(routes, "sb_get_client_membership_roles", AsyncMock(return_value=[{"role": "agency_admin"}])):
            self.assertEqual(await routes._commercial_admin("token"), "agency")

    async def test_client_admin_cannot_modify(self):
        with patch.object(routes, "require_user_id", AsyncMock(return_value="client")), \
             patch.object(routes, "is_platform_admin", AsyncMock(return_value=False)), \
             patch.object(routes, "sb_get_client_membership_roles", AsyncMock(return_value=[{"role": "client_admin"}])):
            with self.assertRaises(HTTPException) as error:
                await routes.commercial_save("a", {"module_keys": ["meta"], "expected_version": None}, authorization="token")
        self.assertEqual(error.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
