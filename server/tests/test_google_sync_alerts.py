"""Google parado não fica mais em silêncio: o job falha (alerta no GitHub) e Integrações pede reconexão."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_jobs
from services import google_oauth as go


class JobExitTests(unittest.TestCase):
    def test_real_account_failure_fails_the_job(self):
        self.assertTrue(run_jobs.google_sync_failed({"results": [{"ok": True}, {"ok": False, "error": "GOOGLE_REAUTH_REQUIRED_INVALID_GRANT"}]}))

    def test_locked_or_unconfigured_accounts_do_not_alert(self):
        self.assertFalse(run_jobs.google_sync_failed({"results": [{"ok": True}, {"ok": False, "skipped": True, "reason": "property_required"}]}))
        self.assertFalse(run_jobs.google_sync_failed({"results": []}))
        self.assertFalse(run_jobs.google_sync_failed(None))

    def test_main_exits_1_for_google_failure(self):
        args = MagicMock(command="ga4-sync-all", days=3)
        with patch.object(run_jobs, "_build_parser") as parser, patch.object(run_jobs, "_run", AsyncMock(return_value={"results": [{"ok": False}]})), \
             patch.object(run_jobs, "_print_json"):
            parser.return_value.parse_args.return_value = args
            with self.assertRaises(SystemExit) as raised:
                run_jobs.main()
        self.assertEqual(raised.exception.code, 1)


class ReauthMarkTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_grant_is_written_on_the_connection(self):
        row = {"id": "c1", "provider": "ga4", "status": "connected"}
        token = {"access_token": "old", "refresh_token": "r", "expires_at": "2020-01-01T00:00:00+00:00"}
        response = MagicMock(status_code=400)
        response.json.return_value = {"error": "invalid_grant"}
        response.raise_for_status.side_effect = RuntimeError("400")
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.post = AsyncMock(return_value=response)
        with patch.object(go, "get_connection", AsyncMock(return_value=row)), patch.object(go, "_connection_token_payload", return_value=token), \
             patch.object(go, "settings", return_value={"client_id": "x", "client_secret": "y"}), patch.object(go.httpx, "AsyncClient", return_value=client), \
             patch.object(go, "sb_update", AsyncMock()) as upd:
            with self.assertRaises(Exception) as raised:
                await go.get_google_access_token("curavino", "c1")
        self.assertEqual(getattr(raised.exception, "code", ""), "GOOGLE_REAUTH_REQUIRED_INVALID_GRANT")
        patch_sent = upd.await_args.kwargs["patch"]
        self.assertEqual(patch_sent["last_error"], "GOOGLE_REAUTH_REQUIRED_INVALID_GRANT")
        self.assertNotIn("status", patch_sent)  # continua "connected": o job tenta de novo e volta sozinho após reconectar


if __name__ == "__main__":
    unittest.main()
