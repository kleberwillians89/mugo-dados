import asyncio
import io
import sys
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from routes import meta_legacy
from services import ads_sync, meta_oauth, meta_tokens
from services.meta_http import MetaApiError


class MetaHandoffSingleUseTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_handoff_loads(self):
        row = {"handoff": "valid", "consumed_at": None, "finalized_at": None}
        with (
            patch.object(meta_oauth, "_cleanup_handoffs", AsyncMock()),
            patch.object(meta_oauth, "sb_select", AsyncMock(return_value=[row])),
        ):
            self.assertEqual(await meta_oauth._load_handoff_row(handoff="valid"), row)

    async def test_consumed_handoff_is_rejected(self):
        row = {"handoff": "used", "consumed_at": "2026-09-08T00:00:00Z", "finalized_at": None}
        with (
            patch.object(meta_oauth, "_cleanup_handoffs", AsyncMock()),
            patch.object(meta_oauth, "sb_select", AsyncMock(return_value=[row])),
        ):
            with self.assertRaisesRegex(RuntimeError, "já utilizada"):
                await meta_oauth._load_handoff_row(handoff="used")

    async def test_finalized_handoff_is_rejected(self):
        row = {"handoff": "done", "consumed_at": None, "finalized_at": "2026-09-08T00:00:00Z"}
        with (
            patch.object(meta_oauth, "_cleanup_handoffs", AsyncMock()),
            patch.object(meta_oauth, "sb_select", AsyncMock(return_value=[row])),
        ):
            with self.assertRaisesRegex(RuntimeError, "já utilizada"):
                await meta_oauth._load_handoff_row(handoff="done")

    async def test_replay_after_consumption_is_rejected(self):
        rows = [
            {"handoff": "once", "consumed_at": None, "finalized_at": None},
            {"handoff": "once", "consumed_at": "2026-09-08T00:00:00Z", "finalized_at": None},
        ]
        with (
            patch.object(meta_oauth, "_cleanup_handoffs", AsyncMock()),
            patch.object(meta_oauth, "sb_select", AsyncMock(side_effect=[[rows[0]], [rows[1]]])),
        ):
            await meta_oauth._load_handoff_row(handoff="once")
            with self.assertRaisesRegex(RuntimeError, "já utilizada"):
                await meta_oauth._load_handoff_row(handoff="once")

    async def test_concurrent_claim_allows_only_one_finalizer(self):
        claimed = False
        lock = asyncio.Lock()

        async def compare_and_set(_table, *, filters, patch, returning):
            nonlocal claimed
            self.assertEqual(filters["consumed_at"], "is.null")
            self.assertEqual(filters["finalized_at"], "is.null")
            self.assertEqual(returning, "representation")
            async with lock:
                if claimed:
                    return []
                claimed = True
                return [{"handoff": "once", **patch}]

        with patch.object(meta_oauth, "sb_update", side_effect=compare_and_set):
            results = await asyncio.gather(
                meta_oauth._claim_handoff_for_finalization(handoff="once", consumed_at="2026-09-08T00:00:00Z"),
                meta_oauth._claim_handoff_for_finalization(handoff="once", consumed_at="2026-09-08T00:00:01Z"),
                return_exceptions=True,
            )
        self.assertEqual(sum(result is None for result in results), 1)
        self.assertEqual(sum(isinstance(result, RuntimeError) for result in results), 1)


class MetaAtomicAssetValidationTests(unittest.IsolatedAsyncioTestCase):
    def test_known_instagram_set_is_accepted_integrally(self):
        meta_oauth._validate_requested_asset_ids(
            requested_ids={"known_1", "known_2"},
            discovered_ids={"known_1", "known_2", "known_3"},
            error_message="unknown",
        )

    def test_known_ads_set_is_accepted_integrally(self):
        meta_oauth._validate_requested_asset_ids(
            requested_ids={"act_known_1", "act_known_2"},
            discovered_ids={"act_known_1", "act_known_2", "act_known_3"},
            error_message="unknown",
        )

    async def _assert_rejected_without_writes(self, *, instagram_ids=None, ad_ids=None):
        row = {
            "handoff": "handoff-1", "user_id": "user-ruah", "client_id": "ruah",
            "encrypted_access_token": "ciphertext", "consumed_at": None, "finalized_at": None,
            "instagram_accounts_json": [{"ig_user_id": "known_1", "business_id": "page_1"}],
            "pages_json": [{"page_id": "page_1"}],
            "ad_accounts_json": [{"ad_account_id": "act_known_1"}],
            "meta_user_json": {}, "scopes_json": [],
        }
        claim = AsyncMock()
        decrypt = unittest.mock.Mock()
        with (
            patch.object(meta_oauth, "_load_handoff_row", AsyncMock(return_value=row)),
            patch.object(meta_oauth, "_claim_handoff_for_finalization", claim),
            patch.object(meta_oauth, "decrypt_secret", decrypt),
            patch.object(meta_oauth, "sb_insert", AsyncMock()) as insert,
            patch.object(meta_oauth, "sb_update", AsyncMock()) as update,
        ):
            with self.assertRaises(RuntimeError):
                await meta_oauth.save_connections(
                    user_id="user-ruah", client_id="ruah", handoff="handoff-1",
                    page_ids=["page_1"] if instagram_ids else [],
                    instagram_ig_user_ids=instagram_ids or [], ad_account_ids=ad_ids or [],
                )
        claim.assert_not_awaited()
        decrypt.assert_not_called()
        insert.assert_not_awaited()
        update.assert_not_awaited()

    async def test_instagram_known_and_unknown_rejects_entire_request(self):
        await self._assert_rejected_without_writes(instagram_ids=["known_1", "unknown_1"])

    async def test_instagram_unknown_only_rejects_entire_request(self):
        await self._assert_rejected_without_writes(instagram_ids=["unknown_1"])

    async def test_ads_known_and_unknown_rejects_entire_request(self):
        await self._assert_rejected_without_writes(ad_ids=["act_known_1", "act_unknown_1"])

    async def test_ads_unknown_only_rejects_entire_request(self):
        await self._assert_rejected_without_writes(ad_ids=["act_unknown_1"])

    def test_pages_known_and_unknown_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Página"):
            meta_oauth.validate_page_selection(
                discovered_instagram_accounts=[], discovered_pages=[{"page_id": "known_1"}],
                requested_page_ids={"known_1", "unknown_1"}, selected_instagram_accounts=[],
            )


class MetaTokenExchangeTests(unittest.IsolatedAsyncioTestCase):
    def _settings(self):
        return {"app_id": "app-id", "app_secret": "app-secret", "redirect_uri": "https://api.example/callback"}

    async def test_short_lived_is_exchanged_for_long_lived_with_correct_parameters(self):
        get = AsyncMock(side_effect=[
            {"access_token": "short-token", "expires_in": 3600},
            {"access_token": "long-token", "expires_in": 5_184_000},
        ])
        with (
            patch.object(meta_oauth, "get_meta_oauth_settings", return_value=self._settings()),
            patch.object(meta_oauth, "_meta_get", get),
        ):
            result = await meta_oauth.exchange_code_for_token(code="authorization-code", redirect_uri="https://api.example/callback")
        self.assertEqual(result["access_token"], "long-token")
        self.assertEqual(get.await_args_list[0].args[0], "/oauth/access_token")
        self.assertEqual(get.await_args_list[0].args[1]["code"], "authorization-code")
        self.assertEqual(get.await_args_list[1].args[1]["grant_type"], "fb_exchange_token")
        self.assertEqual(get.await_args_list[1].args[1]["fb_exchange_token"], "short-token")

    async def test_provider_error_during_initial_exchange_is_propagated(self):
        provider_error = MetaApiError("provider unavailable", status_code=503, retryable=True)
        with (
            patch.object(meta_oauth, "get_meta_oauth_settings", return_value=self._settings()),
            patch.object(meta_oauth, "_meta_get", AsyncMock(side_effect=provider_error)),
        ):
            with self.assertRaises(MetaApiError):
                await meta_oauth.exchange_code_for_token(code="authorization-code", redirect_uri="https://api.example/callback")

    async def test_incomplete_initial_response_is_rejected_without_leaking_code(self):
        output = io.StringIO()
        with (
            patch.object(meta_oauth, "get_meta_oauth_settings", return_value=self._settings()),
            patch.object(meta_oauth, "_meta_get", AsyncMock(return_value={"expires_in": 3600})),
            redirect_stdout(output),
        ):
            with self.assertRaisesRegex(RuntimeError, "Meta não retornou access_token") as raised:
                await meta_oauth.exchange_code_for_token(code="authorization-code", redirect_uri="https://api.example/callback")
        self.assertNotIn("authorization-code", str(raised.exception))
        self.assertNotIn("authorization-code", output.getvalue())

    def test_frontend_redirect_never_contains_provider_tokens(self):
        redirect = meta_oauth.build_frontend_callback_redirect(
            success=True, client_id="ruah", handoff="safe-handoff", error=None, connection_id="meta-1",
        )
        self.assertNotIn("access_token", redirect)
        self.assertNotIn("client_secret", redirect)
        self.assertNotIn("fb_exchange_token", redirect)


class MetaDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_ads_discovery_paginates_multiple_accounts(self):
        first = {"data": [{"id": "act_1", "name": "One"}], "paging": {"next": "https://graph.example/next"}}
        second = {"data": [{"id": "act_2", "name": "Two"}]}
        with (
            patch.object(meta_oauth, "_meta_get", AsyncMock(return_value=first)),
            patch.object(meta_oauth, "meta_get_json", AsyncMock(return_value=second)),
        ):
            result = await meta_oauth.fetch_ad_accounts("provider-token")
        self.assertEqual([row["ad_account_id"] for row in result], ["act_1", "act_2"])

    async def test_ads_discovery_accepts_zero_accounts(self):
        with patch.object(meta_oauth, "_meta_get", AsyncMock(return_value={"data": []})):
            self.assertEqual(await meta_oauth.fetch_ad_accounts("provider-token"), [])

    async def test_ads_discovery_propagates_provider_error(self):
        with patch.object(meta_oauth, "_meta_get", AsyncMock(side_effect=MetaApiError("denied", status_code=403))):
            with self.assertRaises(MetaApiError):
                await meta_oauth.fetch_ad_accounts("provider-token")

    async def test_business_discovery_paginates_multiple_businesses(self):
        first = {"data": [{"id": "business-1", "name": "One"}], "paging": {"next": "https://graph.example/businesses"}}
        second = {"data": [{"id": "business-2", "name": "Two"}]}
        with (
            patch.object(meta_oauth, "_meta_get", AsyncMock(return_value=first)),
            patch.object(meta_oauth, "meta_get_json", AsyncMock(return_value=second)),
        ):
            result = await meta_oauth._fetch_business_managers("provider-token")
        self.assertEqual([row["business_id"] for row in result], ["business-1", "business-2"])

    async def test_business_discovery_accepts_zero_businesses(self):
        with patch.object(meta_oauth, "_meta_get", AsyncMock(return_value={"data": []})):
            self.assertEqual(await meta_oauth._fetch_business_managers("provider-token"), [])

    async def test_business_discovery_propagates_provider_error(self):
        with patch.object(meta_oauth, "_meta_get", AsyncMock(side_effect=MetaApiError("denied", status_code=403))):
            with self.assertRaises(MetaApiError):
                await meta_oauth._fetch_business_managers("provider-token")


class MetaAdsInitialSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_ad_selection_starts_initial_sync_for_resolved_tenant(self):
        saved = {"ok": True, "connections": [{"id": "ruah-ads", "platform": "meta_ads"}]}
        sync = AsyncMock(return_value={"ok": True, "rows_upserted": 3})
        with (
            patch.object(meta_legacy, "require_user_id", AsyncMock(return_value="user-ruah")),
            patch.object(meta_legacy, "require_client_role", AsyncMock(return_value="ruah")),
            patch.object(meta_legacy, "save_connections", AsyncMock(return_value=saved)),
            patch.object(meta_legacy, "sync_ads_for_client_period", sync),
        ):
            result = await meta_legacy.api_link_assets(
                client_id="ruah", payload={"handoff": "h", "ad_account_ids": ["act_1"]}, authorization="Bearer valid",
            )
        self.assertTrue(result["meta_ads_initial_sync"]["ok"])
        self.assertEqual(sync.await_args.kwargs["client_id"], "ruah")
        self.assertEqual(sync.await_args.kwargs["connection_id"], "ruah-ads")
        self.assertEqual(sync.await_args.kwargs["job_name"], "meta_ads_initial_sync")

    async def test_provider_error_preserves_saved_oauth_connection_and_session(self):
        saved = {"ok": True, "connections": [{"id": "ruah-ads", "platform": "meta_ads"}]}
        with (
            patch.object(meta_legacy, "require_user_id", AsyncMock(return_value="user-ruah")),
            patch.object(meta_legacy, "require_client_role", AsyncMock(return_value="ruah")),
            patch.object(meta_legacy, "save_connections", AsyncMock(return_value=saved)),
            patch.object(meta_legacy, "sync_ads_for_client_period", AsyncMock(side_effect=MetaApiError("denied", status_code=503, retryable=True))),
        ):
            result = await meta_legacy.api_link_assets(
                client_id="ruah", payload={"handoff": "h", "ad_account_ids": ["act_1"]}, authorization="Bearer valid",
            )
        self.assertTrue(result["ok"])
        self.assertFalse(result["meta_ads_initial_sync"]["ok"])
        self.assertTrue(result["meta_ads_initial_sync"]["retryable"])

    async def test_recent_retry_is_deduplicated_before_provider_or_persistence(self):
        key = "ruah:ruah-ads:act_1:2026-09-01:2026-09-08"
        ads_sync._RECENT_SYNC_KEYS[key] = time.monotonic()
        try:
            with patch.object(ads_sync, "_pick_paid_connection", AsyncMock(return_value={
                "id": "ruah-ads", "client_id": "ruah", "ad_account_id": "act_1", "ad_account_name": "RUAH",
                "_resolved_source": "explicit",
            })):
                result = await ads_sync.sync_ads_for_client_period(
                    client_id="ruah", connection_id="ruah-ads", since="2026-09-01", until="2026-09-08",
                    record_job_run=False,
                )
            self.assertTrue(result["skipped"])
            self.assertEqual(result["reason"], "duplicate")
        finally:
            ads_sync._RECENT_SYNC_KEYS.pop(key, None)

    async def test_success_timestamp_is_written_only_by_success_marker(self):
        update = AsyncMock()
        with (
            patch.object(meta_tokens, "sb_update", update),
            patch.object(meta_tokens, "_log_event", AsyncMock()),
            patch.object(meta_tokens, "invalidate_namespace", AsyncMock()),
        ):
            await meta_tokens.mark_connection_sync_success("ruah-ads")
        payload = update.await_args.kwargs["patch"]
        self.assertEqual(payload["last_sync_status"], "success")
        self.assertTrue(payload["last_sync_at"])


class MetaSymmetricWriteIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def _write_and_assert_other_unchanged(self, actor_tenant, other_tenant):
        rows = {
            actor_tenant: {"id": f"{actor_tenant}-ads", "client_id": actor_tenant, "platform": "meta_ads", "connection_type": "paid", "ig_user_id": "", "ad_account_id": "act_1", "status": "old"},
            other_tenant: {"id": f"{other_tenant}-ads", "client_id": other_tenant, "platform": "meta_ads", "connection_type": "paid", "ig_user_id": "", "ad_account_id": "act_1", "status": "old"},
        }
        other_before = dict(rows[other_tenant])

        async def select(_table, *, filters, **_kwargs):
            return [row for row in rows.values() if all(
                str(row.get(key) or "") == str(value).removeprefix("eq.") for key, value in filters.items()
            )]

        async def update(_table, *, filters, patch, **_kwargs):
            for row in rows.values():
                if all(str(row.get(key) or "") == str(value).removeprefix("eq.") for key, value in filters.items()):
                    row.update(patch)
            return []

        replacement = {**rows[actor_tenant], "status": "active", "ad_account_name": actor_tenant.upper()}
        with (
            patch.object(meta_oauth, "sb_select", side_effect=select),
            patch.object(meta_oauth, "sb_update", side_effect=update),
        ):
            await meta_oauth._save_connection_row(replacement)
        self.assertEqual(rows[actor_tenant]["status"], "active")
        self.assertEqual(rows[other_tenant], other_before)

    async def test_ruah_write_does_not_change_roove(self):
        await self._write_and_assert_other_unchanged("ruah", "roove")

    async def test_roove_write_does_not_change_ruah(self):
        await self._write_and_assert_other_unchanged("roove", "ruah")


if __name__ == "__main__":
    unittest.main()
