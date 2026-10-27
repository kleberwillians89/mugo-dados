import asyncio
import json
import os
import subprocess
import shutil
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

from fastapi import FastAPI
from starlette.testclient import TestClient
from mcp_readonly import oauth
from mcp_readonly.transport import install

CLIENT = "00000000-0000-4000-8000-000000000001"
USER = "00000000-0000-4000-8000-000000000002"
TOKEN_ID = "00000000-0000-4000-8000-000000000003"
CALLBACK = "https://claude.ai/api/mcp/auth_callback"
ENV = {"MCP_ENABLED": "true", "MCP_PUBLIC_URL": "https://api.test/mcp", "MCP_FRONTEND_URL": "https://frontend.test", "MCP_ALLOWED_REDIRECT_URIS": CALLBACK}
VERIFIER = "v" * 43
PARAMS = {"client_id": CLIENT, "redirect_uri": CALLBACK, "response_type": "code", "code_challenge_method": "S256",
          "code_challenge": oauth.challenge(VERIFIER), "state": "opaque-state", "resource": ENV["MCP_PUBLIC_URL"]}
ROW = {"id": CLIENT, "client_name": "Aplicativo de teste", "redirect_uris": [CALLBACK]}


class OAuthEndpointsTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, ENV, clear=True); self.environment.start()
        oauth.public_rates.clear()
        app = FastAPI(); install(app)
        self.client = TestClient(app, base_url="https://api.test"); self.client.__enter__()
        self.select = patch.object(oauth, "sb_select", AsyncMock(return_value=[ROW])); self.read = self.select.start()

    def tearDown(self):
        self.select.stop(); self.client.__exit__(None, None, None); self.environment.stop()

    def test_metadata_and_unauthenticated_mcp_challenge(self):
        metadata = self.client.get("/.well-known/oauth-protected-resource").json()
        self.assertEqual(metadata["resource"], ENV["MCP_PUBLIC_URL"])
        server = self.client.get("/.well-known/oauth-authorization-server").json()
        self.assertEqual(server["code_challenge_methods_supported"], ["S256"])
        response = self.client.post("/mcp", json={})
        self.assertEqual(response.status_code, 401)
        self.assertIn("resource_metadata=", response.headers["WWW-Authenticate"])

    def test_missing_pkce_state_wrong_redirect_and_resource_fail(self):
        for change in ({"code_challenge_method": "plain"}, {"code_challenge": ""}, {"state": ""},
                       {"redirect_uri": "https://evil.test/callback"}, {"resource": "https://other.test/mcp"}):
            with self.subTest(change=change):
                response = self.client.get("/oauth/authorize?" + urlencode({**PARAMS, **change}), follow_redirects=False)
                self.assertEqual(response.status_code, 400)
                self.assertNotIn("location", response.headers)
        valid = self.client.get("/oauth/authorize?" + urlencode(PARAMS), follow_redirects=False)
        self.assertEqual(valid.status_code, 303)
        self.assertTrue(valid.headers["location"].startswith("https://frontend.test/conectar-claude/autorizar?"))

    def test_registration_only_exact_allowlist_no_client_secret(self):
        with patch.object(oauth, "sb_insert", AsyncMock()) as write:
            denied = self.client.post("/oauth/register", json={"redirect_uris": [CALLBACK + "?other=1"]})
            self.assertEqual(denied.status_code, 400); write.assert_not_awaited()
            approved = self.client.post("/oauth/register", json={"redirect_uris": [CALLBACK]})
            self.assertEqual(approved.status_code, 201)
            self.assertNotIn("client_secret", approved.json())
            self.assertEqual(write.await_args.args[0], "mcp_oauth_clients")

    def test_consent_requires_verified_supabase_identity_and_omits_raw_code_from_store(self):
        with patch.object(oauth, "get_user_from_bearer", AsyncMock(return_value=None)), patch.object(oauth, "sb_insert", AsyncMock()) as write:
            self.assertEqual(self.client.post("/api/mcp/consent", json={**PARAMS, "approve": True}).status_code, 401)
            write.assert_not_awaited()
        with patch.object(oauth, "get_user_from_bearer", AsyncMock(return_value={"id": USER})), \
             patch.object(oauth, "dispatch", AsyncMock(return_value={"companies": []})), patch.object(oauth, "sb_insert", AsyncMock()) as write:
            denied = self.client.post("/api/mcp/consent", json={**PARAMS, "approve": False})
            self.assertIn("access_denied", denied.json()["redirect_url"]); write.assert_not_awaited()
            approved = self.client.post("/api/mcp/consent", json={**PARAMS, "approve": True})
            stored = write.await_args.args[1]
            self.assertEqual(len(stored["code_hash"]), 64)
            self.assertNotIn("code", stored)
            self.assertEqual(stored["user_id"], USER)
            self.assertIn("code=", approved.json()["redirect_url"])

    def test_token_exchange_uses_hashes_and_correct_pkce_without_retry(self):
        with patch.object(oauth, "sb_rpc", AsyncMock(return_value=True)) as rpc:
            response = self.client.post("/oauth/token", data={"grant_type": "authorization_code", "client_id": CLIENT,
                "resource": ENV["MCP_PUBLIC_URL"], "redirect_uri": CALLBACK, "code": "c" * 64, "code_verifier": VERIFIER})
            self.assertEqual(response.status_code, 200)
            payload = response.json(); stored = rpc.await_args.args[1]
            self.assertEqual(stored["p_access_hash"], oauth.digest(payload["access_token"]))
            self.assertEqual(stored["p_refresh_hash"], oauth.digest(payload["refresh_token"]))
            self.assertNotIn(payload["access_token"], json.dumps(stored))
            self.assertEqual(stored["p_challenge"], oauth.challenge(VERIFIER))
            self.assertEqual(rpc.await_count, 1)
        with patch.object(oauth, "sb_rpc", AsyncMock(return_value=False)):
            response = self.client.post("/oauth/token", data={"grant_type": "refresh_token", "client_id": CLIENT,
                "resource": ENV["MCP_PUBLIC_URL"], "refresh_token": "r" * 64})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error"], "invalid_grant")

    def test_owner_filter_on_connection_revocation(self):
        with patch.object(oauth, "get_user_from_bearer", AsyncMock(return_value={"id": USER})), patch.object(oauth, "sb_rpc", AsyncMock()) as rpc:
            self.read.return_value = []
            self.assertEqual(self.client.post("/api/mcp/connections/revoke", json={"id": TOKEN_ID}).status_code, 200)
            self.assertEqual(self.read.await_args.kwargs["filters"], {"id": f"eq.{TOKEN_ID}", "user_id": f"eq.{USER}"})
            rpc.assert_not_awaited()

    def test_disabled_all_oauth_routes_are_404(self):
        with patch.dict(os.environ, {"MCP_ENABLED": "false"}):
            for path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-authorization-server", "/oauth/authorize", "/api/mcp/connections"):
                self.assertEqual(self.client.get(path).status_code, 404)
            for path in ("/oauth/register", "/oauth/token", "/oauth/revoke", "/api/mcp/consent", "/api/mcp/connections/revoke"):
                self.assertEqual(self.client.post(path).status_code, 404)

    def test_sdk_tool_audits_once_without_free_arguments(self):
        with patch("mcp_readonly.transport.dispatch", AsyncMock(return_value={"metrics": [], "observacoes": []})), \
             patch.object(oauth, "authenticate", AsyncMock(return_value=(USER, "hash-only"))), \
             patch("services.ig_supabase.sb_insert", AsyncMock()) as audit:
            response = self.client.post("/mcp", headers={"Accept": "application/json, text/event-stream"}, json={
                "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_goals", "arguments": {"company_id": "company-a"}}})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()["result"].get("isError"), response.text)
            audit.assert_awaited_once()
            event = audit.await_args.args[1]
            self.assertEqual(set(event), {"user_id", "client_id", "tool", "period_start", "period_end", "status", "duration_ms"})
            self.assertEqual(event["user_id"], USER)
            self.assertNotIn("company-a", json.dumps(event))  # Mock não atestou autorização.

    def test_oversized_and_duplicate_token_arguments_fail(self):
        response = self.client.post("/oauth/token", content="a=" + "x" * 17000, headers={"content-type": "application/x-www-form-urlencoded"})
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/oauth/token", content="client_id=a&client_id=b", headers={"content-type": "application/x-www-form-urlencoded"})
        self.assertEqual(response.status_code, 400)


class TokenVerificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_revoked_expired_or_wrong_audience_tokens_denied(self):
        for change in ({"revoked_at": "2026-01-01T00:00:00Z"}, {"access_expires_at": "2020-01-01T00:00:00Z"}, {"resource": "https://other.test/mcp"}):
            row = {"id": TOKEN_ID, "user_id": USER, "resource": ENV["MCP_PUBLIC_URL"], "access_expires_at": (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(), **change}
            with self.subTest(change=change), patch.dict(os.environ, ENV, clear=True), patch.object(oauth, "sb_select", AsyncMock(return_value=[row])), patch.object(oauth, "sb_update", AsyncMock()) as update:
                self.assertIsNone(await oauth.authenticate("Bearer " + "t"*64))
                update.assert_not_awaited()


class PostgreSQLContractTests(unittest.TestCase):
    @unittest.skipUnless(os.getenv("MCP_TEST_PG_SOCKET") == "/tmp/mugo-mcp-pg/socket", "PostgreSQL descartável não configurado")
    def test_real_sql_codes_rotation_reuse_revocation_and_browser_denial(self):
        sql = Path(__file__).with_name("mcp_oauth_contract.sql")
        executable = shutil.which("psql")
        if not executable:
            self.skipTest("psql não disponível no ambiente de teste")
        process = subprocess.run([executable, "-X", "-h", os.environ["MCP_TEST_PG_SOCKET"], "-p", "55469", "-U", "mcp_test_owner", "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-f", str(sql)],
            capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "PGPASSFILE": "/tmp/mugo-mcp-pg/empty-passfile"})
        self.assertEqual(process.returncode, 0, process.stderr)


class AuthenticateSignatureTests(unittest.IsolatedAsyncioTestCase):
    async def test_authenticate_calls_real_sb_update_signature(self):
        # autospec: falha se a chamada não respeitar sb_update(table, *, filters, patch, returning).
        from datetime import datetime, timedelta, timezone
        row = {"id": "11111111-1111-1111-1111-111111111111", "user_id": "22222222-2222-2222-2222-222222222222",
               "resource": "https://api.test/mcp", "revoked_at": None,
               "access_expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()}
        env = {"MCP_ENABLED": "true", "MCP_PUBLIC_URL": "https://api.test/mcp", "MCP_FRONTEND_URL": "https://app.test"}
        with patch.dict(os.environ, env, clear=True), \
             patch.object(oauth, "sb_select", AsyncMock(return_value=[row])), \
             patch.object(oauth, "sb_update", autospec=True) as update:
            result = await oauth.authenticate("Bearer " + "a" * 40)
        self.assertEqual(result[0], row["user_id"])
        self.assertEqual(update.await_args.kwargs["filters"], {"id": f"eq.{row['id']}"})
        self.assertIn("last_used_at", update.await_args.kwargs["patch"])

    def test_resource_absent_or_trailing_slash_is_tolerated(self):
        self.assertEqual(oauth.requested_resource(None, "https://api.test/mcp"), "https://api.test/mcp")
        self.assertEqual(oauth.requested_resource("https://api.test/mcp/", "https://api.test/mcp"), "https://api.test/mcp")
        self.assertEqual(oauth.requested_resource("https://evil.test/mcp", "https://api.test/mcp"), "https://evil.test/mcp")
