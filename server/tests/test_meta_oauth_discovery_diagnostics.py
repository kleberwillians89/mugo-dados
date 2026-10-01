import io
import os
import select
import subprocess
import sys
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services import meta_http, meta_oauth
from services.meta_http import MetaApiError

TOKEN = "provider-user-token-value"
APP_SECRET = "app-secret-value"
ENV = {"META_APP_ID": "app-1", "META_APP_SECRET": APP_SECRET}

PERMISSIONS = {"data": [
    {"permission": "public_profile", "status": "granted"},
    {"permission": "ads_read", "status": "granted"},
    {"permission": "pages_show_list", "status": "declined"},
    {"permission": "business_management", "status": "declined"},
]}
DEBUG_TOKEN = {"data": {
    "app_id": "app-1", "type": "USER", "is_valid": True, "user_id": "user-1",
    "granular_scopes": [
        {"scope": "ads_read", "target_ids": ["111", "222"]},
        {"scope": "instagram_basic", "target_ids": []},
        {"scope": "public_profile"},
    ],
}}


def graph_first_page(responses):
    async def fake(path, params):
        assert params.get("access_token") == TOKEN
        value = responses[path]
        if isinstance(value, Exception):
            raise value
        return value
    return fake


def graph_json(responses):
    async def fake(path_or_url, *, params=None, **_kwargs):
        value = responses[path_or_url]
        if isinstance(value, Exception):
            raise value
        return value
    return fake


class DiscoveryDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def run_discovery(self, first_page, json_responses):
        output = io.StringIO()
        with (
            patch.dict(os.environ, ENV, clear=False),
            patch.object(meta_oauth, "_meta_get", AsyncMock(side_effect=graph_first_page(first_page))),
            patch.object(meta_oauth, "meta_get_json", AsyncMock(side_effect=graph_json(json_responses))),
            redirect_stdout(output),
        ):
            try:
                result = await meta_oauth.discover_assets(TOKEN)
                error = None
            except Exception as exc:  # noqa: BLE001 - o teste inspeciona a exceção
                result, error = None, exc
        return result, error, output.getvalue()

    async def test_empty_pages_and_businesses_log_permissions_granular_scopes_and_counts(self):
        result, error, logs = await self.run_discovery(
            {
                "/me": {"id": "user-1", "name": "User"},
                "/me/accounts": {"data": []},
                "/me/adaccounts": {"data": [{"id": "act_111", "name": "A"}, {"id": "act_222", "name": "B"}]},
                "/me/permissions": PERMISSIONS,
                "/me/businesses": {"data": []},
            },
            {"/me/permissions": PERMISSIONS, "/debug_token": DEBUG_TOKEN},
        )

        self.assertIsNone(error)
        # Contrato do discovery inalterado.
        self.assertEqual(result["pages"], [])
        self.assertEqual(result["business_managers"], [])
        self.assertEqual([row["ad_account_id"] for row in result["ad_accounts"]], ["act_111", "act_222"])
        self.assertEqual(sorted(result["scopes"]), ["ads_read", "public_profile"])

        self.assertIn("stage=graph_calls me_accounts=ok me_adaccounts=ok me_businesses=ok", logs)
        self.assertIn("declined=business_management,pages_show_list", logs)
        self.assertIn("granted=ads_read,public_profile", logs)
        self.assertIn("requested_not_granted=pages_show_list,pages_read_engagement,instagram_basic", logs)
        self.assertIn("granular_scopes=ads_read:[111,222] instagram_basic:[none] public_profile:all", logs)
        self.assertIn("app_id_matches=1", logs)
        self.assertIn("business_count=0 business_ids=-", logs)
        self.assertIn("page_count=0 page_ids=-", logs)
        self.assertIn("instagram_count=0 instagram_ids=-", logs)
        self.assertIn("ad_account_count=2 ad_account_ids=act_111,act_222", logs)
        self.assertNotIn(TOKEN, logs)
        self.assertNotIn(APP_SECRET, logs)

    async def test_found_assets_are_logged_by_id(self):
        page = {"id": "page-9", "name": "Página", "instagram_business_account": {"id": "ig-9", "username": "marca"}}
        _result, error, logs = await self.run_discovery(
            {
                "/me": {"id": "user-1", "name": "User"},
                "/me/accounts": {"data": [page]},
                "/page-9": page,
                "/me/adaccounts": {"data": []},
                "/me/permissions": PERMISSIONS,
                "/me/businesses": {"data": [{"id": "biz-9", "name": "Portfólio"}]},
            },
            {"/me/permissions": PERMISSIONS, "/debug_token": DEBUG_TOKEN},
        )
        self.assertIsNone(error)
        self.assertIn("business_count=1 business_ids=biz-9", logs)
        self.assertIn("page_count=1 page_ids=page-9", logs)
        self.assertIn("instagram_count=1 instagram_ids=ig-9", logs)

    async def test_me_businesses_denied_keeps_direct_assets_and_is_logged_without_secrets(self):
        denied = MetaApiError(
            "Meta API error 403: (#200) Requires business_management permission",
            status_code=403, error_code=200,
        )
        result, error, logs = await self.run_discovery(
            {
                "/me": {"id": "user-1", "name": "User"},
                "/me/accounts": {"data": []},
                "/me/adaccounts": {"data": [{"id": "act_111", "name": "A"}]},
                "/me/permissions": PERMISSIONS,
                "/me/businesses": denied,
            },
            {"/me/permissions": PERMISSIONS, "/debug_token": DEBUG_TOKEN},
        )
        # /me/businesses deixou de ser fatal: seguem os ativos diretos + aviso seguro.
        self.assertIsNone(error)
        self.assertEqual([row["ad_account_id"] for row in result["ad_accounts"]], ["act_111"])
        self.assertEqual(result["business_managers"], [])
        self.assertEqual(result["discovery_warnings"][0]["status"], "permission_denied")
        self.assertIn("stage=graph_call_failed call=me_businesses http_status=403 graph_code=200", logs)
        self.assertIn("Requires business_management permission", logs)
        self.assertIn("me_businesses=403", logs)
        self.assertIn("stage=permissions http_status=200", logs)
        self.assertNotIn(TOKEN, logs)
        self.assertNotIn(APP_SECRET, logs)

    async def test_diagnostic_failures_never_break_discovery(self):
        result, error, logs = await self.run_discovery(
            {
                "/me": {"id": "user-1", "name": "User"},
                "/me/accounts": {"data": []},
                "/me/adaccounts": {"data": []},
                "/me/permissions": PERMISSIONS,
                "/me/businesses": {"data": []},
            },
            {
                "/me/permissions": MetaApiError("Meta API error 500: boom", status_code=500),
                "/debug_token": RuntimeError("unexpected"),
            },
        )
        self.assertIsNone(error)
        self.assertEqual(result["pages"], [])
        self.assertIn("stage=permissions_failed http_status=500", logs)
        self.assertIn("stage=debug_token_failed error_type=RuntimeError", logs)
        self.assertIn("stage=assets", logs)

    async def test_missing_app_credentials_skip_debug_token_only(self):
        output = io.StringIO()
        with (
            patch.object(meta_oauth, "get_meta_oauth_settings", side_effect=RuntimeError("missing")),
            patch.object(meta_oauth, "meta_get_json", AsyncMock(side_effect=graph_json({"/me/permissions": PERMISSIONS}))),
            redirect_stdout(output),
        ):
            await meta_oauth._log_discovery_diagnostics(
                TOKEN, calls=["me_accounts=ok"], identity={}, ad_accounts=[], business_managers=[],
            )
        logs = output.getvalue()
        self.assertIn("stage=debug_token_skipped reason=app_credentials_unavailable", logs)
        self.assertIn("stage=permissions http_status=200", logs)
        self.assertIn("stage=assets", logs)

    async def test_real_discover_assets_emits_graph_calls_and_assets_lines(self):
        first_page = {
            "/me": {"id": "user-1", "name": "User"},
            "/me/accounts": {"data": []},
            "/me/adaccounts": {"data": []},
            "/me/permissions": PERMISSIONS,
            "/me/businesses": {"data": []},
        }
        json_responses = {"/me/permissions": PERMISSIONS, "/debug_token": DEBUG_TOKEN}
        _result, error, logs = await self.run_discovery(first_page, json_responses)
        self.assertIsNone(error)
        self.assertIn("[meta_oauth][diag] stage=graph_calls", logs)
        self.assertIn("[meta_oauth][diag] stage=assets", logs)

        # Também no caminho de erro (o finally roda antes da exceção subir).
        # Só token inválido continua interrompendo a descoberta.
        first_page["/me/businesses"] = MetaApiError(
            "Meta API error 401: Error validating access token", status_code=401, error_code=190, invalid_oauth=True,
        )
        _result, error, logs = await self.run_discovery(first_page, json_responses)
        self.assertIsInstance(error, MetaApiError)
        self.assertIn("[meta_oauth][diag] stage=graph_calls", logs)
        self.assertIn("[meta_oauth][diag] stage=assets", logs)

    def test_debug_token_parameters_are_redacted_from_logged_urls(self):
        safe = meta_http._safe_url(
            f"https://graph.facebook.com/v25.0/debug_token?input_token={TOKEN}&access_token=app-1%7C{APP_SECRET}"
        )
        self.assertNotIn(TOKEN, safe)
        self.assertNotIn(APP_SECRET, safe)


class StdoutVisibilityTests(unittest.TestCase):
    def test_print_after_importing_app_is_visible_while_process_is_alive(self):
        # Reproduz o Render: stdout é um pipe e PYTHONUNBUFFERED não está
        # definido. Sem line buffering a linha só sairia no fim do processo.
        env = {key: value for key, value in os.environ.items() if key != "PYTHONUNBUFFERED"}
        code = (
            "import time, app; "
            "print('[meta_oauth][diag] stage=graph_calls probe'); "
            "time.sleep(20)"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", code], cwd=SERVER_DIR, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 15
            seen = ""
            while time.monotonic() < deadline and "stage=graph_calls" not in seen:
                ready, _, _ = select.select([process.stdout], [], [], 0.5)
                if ready:
                    seen += process.stdout.readline().decode("utf-8", "replace")
            self.assertIsNone(process.poll(), "o processo deveria continuar vivo")
            self.assertIn("[meta_oauth][diag] stage=graph_calls probe", seen)
        finally:
            process.kill()
            process.wait()
            process.stdout.close()


if __name__ == "__main__":
    unittest.main()
