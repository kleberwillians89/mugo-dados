"""Direitos comerciais por tenant, ainda separados das permissões e sem enforcement."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import commercial_modules as cm
from services import saas


class CatalogTests(unittest.TestCase):
    def test_basic_capabilities_are_always_included(self):
        rights = cm.resolve_from_subscription("tenant-a", {"plan": {"features": ["meta"]}})
        self.assertEqual(rights["basic_capabilities"], ["briefing", "tasks"])
        self.assertTrue({"briefing", "tasks", "meta"}.issubset(rights["capabilities"]))

    def test_social_media_includes_redacao_as_one_product(self):
        rights = cm.resolve_from_subscription("tenant-a", {"plan": {"features": ["social_media"]}})
        self.assertEqual(rights["commercial_modules"], ["social_media"])
        self.assertTrue({"social_media", "redacao"}.issubset(rights["capabilities"]))
        self.assertNotIn("redacao", cm.COMMERCIAL_MODULES)
        alias = cm.resolve_from_subscription("tenant-a", {"plan": {"features": ["redacao"]}})
        self.assertEqual(alias["commercial_modules"], ["social_media"])

    def test_optional_modules_combine_independently(self):
        selected = ["google", "ecommerce", "planning", "creators"]
        rights = cm.resolve_from_subscription("tenant-a", {"plan": {"features": selected}})
        self.assertEqual(rights["commercial_modules"], sorted(selected))
        self.assertNotIn("social_media", rights["capabilities"])
        self.assertTrue({"briefing", "tasks"}.issubset(rights["capabilities"]))

    def test_legacy_plans_and_missing_subscription_preserve_current_behavior(self):
        no_subscription = cm.resolve_from_subscription("tenant-a", None)
        legacy = cm.resolve_from_subscription("tenant-a", {"plan": {"features": ["Tudo do Essencial"]}})
        self.assertEqual(set(no_subscription["commercial_modules"]), set(cm.COMMERCIAL_MODULES))
        self.assertEqual(set(legacy["commercial_modules"]), set(cm.COMMERCIAL_MODULES))
        self.assertFalse(no_subscription["configured"])
        self.assertFalse(legacy["configured"])
        self.assertFalse(no_subscription["enforcement_enabled"])

    def test_invalid_subscription_does_not_grant_optional_modules(self):
        missing_plan = cm.resolve_from_subscription("tenant-a", {"plan_id": "missing", "plan": None})
        invalid_features = cm.resolve_from_subscription("tenant-a", {"plan": {"features": "social_media"}})
        unknown_feature = cm.resolve_from_subscription("tenant-a", {"plan": {"features": ["meta", "typo"]}})
        mixed_legacy = cm.resolve_from_subscription(
            "tenant-a", {"plan": {"features": ["meta", "Tudo do Essencial"]}}
        )
        self.assertEqual(missing_plan["commercial_modules"], [])
        self.assertEqual(invalid_features["commercial_modules"], [])
        self.assertEqual(unknown_feature["commercial_modules"], [])
        self.assertEqual(mixed_legacy["commercial_modules"], [])
        self.assertEqual(missing_plan["resolution_error"], "commercial_plan_unavailable")
        self.assertEqual(invalid_features["resolution_error"], "commercial_features_invalid")
        self.assertEqual(unknown_feature["resolution_error"], "commercial_features_unknown")
        self.assertEqual(mixed_legacy["resolution_error"], "commercial_features_unknown")

    def test_plan_cleaning_supports_the_whole_catalog(self):
        features = list(cm.COMMERCIAL_MODULES)
        self.assertGreater(len(features), 12)
        self.assertEqual(saas.clean_plan({"features": features})["features"], features)


class TenantResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolution_is_scoped_to_the_requested_tenant(self):
        get_subscription = AsyncMock(side_effect=[
            {"client_id": "tenant-a", "plan": {"features": ["meta"]}},
            {"client_id": "tenant-b", "plan": {"features": ["creators"]}},
            {"client_id": "tenant-a", "plan": {"features": ["meta"]}},
        ])
        with patch("services.tenant_commercial_config.get_configuration", AsyncMock(return_value={"configured": False})), \
             patch("services.saas.get_subscription", get_subscription):
            first = await cm.resolve_tenant_modules("tenant-a")
            second = await cm.resolve_tenant_modules("tenant-b")
            third = await cm.resolve_tenant_modules("tenant-a")
        self.assertEqual(first["commercial_modules"], ["meta"])
        self.assertEqual(second["commercial_modules"], ["creators"])
        self.assertEqual(third["commercial_modules"], ["meta"])
        self.assertEqual([call.args[0] for call in get_subscription.await_args_list], ["tenant-a", "tenant-b", "tenant-a"])

    async def test_resolution_error_grants_only_basic_capabilities(self):
        with patch("services.tenant_commercial_config.get_configuration", AsyncMock(return_value={"configured": False})), \
             patch("services.saas.get_subscription", AsyncMock(side_effect=RuntimeError("database unavailable"))):
            rights = await cm.resolve_tenant_modules("tenant-a")
        self.assertEqual(rights["commercial_modules"], [])
        self.assertEqual(rights["capabilities"], ["briefing", "tasks"])
        self.assertEqual(rights["resolution_error"], "commercial_modules_unavailable")
        self.assertFalse(rights["enforcement_enabled"])


if __name__ == "__main__":
    unittest.main()
