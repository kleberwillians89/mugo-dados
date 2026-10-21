"""Startup safety and normal Meta connection regression; all IO is mocked."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import app
from services import ads_sync

# Capture the real target at discovery: older resilience tests leave a nested
# mock on the module attribute when their patchers stop in insertion order.
_PICK_PAID_CONNECTION = ads_sync._pick_paid_connection


class StartupMetaBootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def test_production_startup_never_invokes_bootstrap_with_valid_seed_configuration(self):
        # Synthetic values only. The real bootstrap function is never executed.
        seed = {"META_BOOTSTRAP_PREFIXES": "FIXTURE", "FIXTURE_CLIENT_ID": "tenant-fixture",
                "FIXTURE_ACCESS_TOKEN": "test-only-bootstrap-value", "FIXTURE_IG_USER_ID": "fixture-account"}
        environments = [
            {"APP_ENV": "production"}, {"APP_ENV": " PROD "},
            {"ENVIRONMENT": "production"}, {"PYTHON_ENV": "prod"},
            {"RENDER": "true"}, {"RENDER": "true", "APP_ENV": "development"},
            {"APP_ENV": "production", "ENVIRONMENT": "development"},
            {"PYTHON_ENV": "production", "ENVIRONMENT": "development", "APP_ENV": "development"},
        ]
        for environment in environments:
            with self.subTest(environment=environment), patch.dict(os.environ, {**seed, **environment}, clear=True), \
                 patch.object(app, "bootstrap_meta_from_env", AsyncMock(side_effect=AssertionError("bootstrap must not run"))) as bootstrap:
                async with app.app.router.lifespan_context(app.app):
                    pass
                bootstrap.assert_not_called()

    async def test_local_startup_preserves_the_existing_mocked_hook(self):
        with patch.dict(os.environ, {"APP_ENV": "development"}, clear=True), \
             patch.object(app, "bootstrap_meta_from_env", AsyncMock(return_value=[])) as bootstrap:
            async with app.app.router.lifespan_context(app.app):
                pass
            bootstrap.assert_awaited_once_with()

    async def test_existing_paid_connection_resolves_without_bootstrap_in_production(self):
        connection = {"id": "connection-fixture", "client_id": "tenant-fixture", "ad_account_id": "act_fixture"}
        with patch.dict(os.environ, {"APP_ENV": "production"}, clear=True), \
             patch.object(app, "bootstrap_meta_from_env", AsyncMock(side_effect=AssertionError("startup bootstrap must not run"))) as startup_bootstrap, \
             patch.object(ads_sync, "bootstrap_meta_from_env", AsyncMock(side_effect=AssertionError("existing connection must not bootstrap"))) as ads_bootstrap, \
             patch.object(ads_sync, "resolve_connection_for_scope", AsyncMock(return_value={"row": connection})) as resolve:
            async with app.app.router.lifespan_context(app.app):
                pass
            result = await _PICK_PAID_CONNECTION("tenant-fixture", preferred_connection_id="connection-fixture")
            self.assertEqual(result["id"], connection["id"])
            self.assertEqual(result["ad_account_id"], connection["ad_account_id"])
            resolve.assert_awaited_once_with(client_id="tenant-fixture", platform="meta_ads", connection_type="paid",
                                           requested_connection_id="connection-fixture", require_ad_account=True)
            startup_bootstrap.assert_not_called()
            ads_bootstrap.assert_not_called()

    async def test_production_startup_preserves_explicit_oauth_and_asset_linking(self):
        from routes import meta_legacy
        settings = {"app_id": "fixture-app", "redirect_uri": "https://fixture.invalid/callback", "login_config_id": "fixture-config"}
        with (
            patch.dict(os.environ, {"APP_ENV": "production"}, clear=True),
            patch.object(app, "bootstrap_meta_from_env", AsyncMock(side_effect=AssertionError("bootstrap must not run"))) as bootstrap,
            patch.object(meta_legacy, "require_user_id", AsyncMock(return_value="user-fixture")),
            patch.object(meta_legacy, "require_client_role", AsyncMock(return_value="tenant-fixture")),
            patch.object(meta_legacy, "get_meta_oauth_settings", return_value=settings),
            patch.object(meta_legacy, "create_oauth_state", AsyncMock(return_value="fixture-state")) as create_state,
            patch.object(meta_legacy, "build_oauth_url", return_value={"url": "https://fixture.invalid/authorize"}),
            patch.object(meta_legacy, "save_connections", AsyncMock(return_value={"ok": True, "saved_count": 1})) as save,
        ):
            async with app.app.router.lifespan_context(app.app):
                pass
            result = await meta_legacy.api_oauth_meta_start(
                request=SimpleNamespace(state=SimpleNamespace(request_id="fixture-request")),
                client_id="tenant-fixture", x_client_id=None, authorization="Bearer fixture")
            self.assertEqual(result["authorization_url"], "https://fixture.invalid/authorize")
            create_state.assert_awaited_once_with(provider="meta", user_id="user-fixture", client_id="tenant-fixture",
                                                 redirect_uri=settings["redirect_uri"])
            linked = await meta_legacy.api_link_assets(client_id="tenant-fixture",
                payload={"handoff": "fixture-handoff", "instagram_ig_user_ids": ["fixture-account"], "page_ids": [], "ad_account_ids": []},
                authorization="Bearer fixture")
            self.assertTrue(linked["ok"])
            self.assertEqual(save.await_args.kwargs["client_id"], "tenant-fixture")
            bootstrap.assert_not_called()
