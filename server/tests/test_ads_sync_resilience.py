from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import ads_sync
from services.integration_errors import IntegrationError
from services.sync_locks import build_sync_lock_name


def _paid_connection(connection_id: str = "conn-1") -> dict:
    return {
        "id": connection_id,
        "_resolved_source": "explicit",
        "ad_account_id": "act_123",
        "ad_account_name": "Conta de Teste",
    }


def _empty_upsert() -> dict:
    return {"upserted": 0, "skipped": False}


def _empty_readback() -> dict:
    empty = {"count": 0, "mode": "unknown"}
    return {
        "ad_account_daily_stats": dict(empty),
        "campaign_daily_stats": dict(empty),
        "ad_daily_stats": dict(empty),
        "promoted_post_daily_stats": dict(empty),
    }


class _BaseAdsSyncTest(unittest.IsolatedAsyncioTestCase):
    """Isola sync_ads_for_client_period de todas as dependências externas
    (Supabase, Graph API) para exercitar apenas a lógica de finalização,
    lock e timeout adicionada nesta etapa."""

    def setUp(self):
        self.patchers = []
        self.finish_job_run_calls = []
        self.release_lock_calls = []
        self.mark_error_calls = []

        async def fake_start_job_run(**_kwargs):
            return {"id": "job-run-1"}

        async def fake_finish_job_run(job_run_id, **kwargs):
            self.finish_job_run_calls.append({"job_run_id": job_run_id, **kwargs})
            return {"id": job_run_id}

        async def fake_acquire_sync_lock(_client_id, _lock_name, _ttl):
            return True

        async def fake_release_sync_lock(client_id, lock_name):
            self.release_lock_calls.append((client_id, lock_name))

        async def fake_mark_connection_sync_error(connection_id, message, **kwargs):
            self.mark_error_calls.append((connection_id, message, kwargs))

        self._install(ads_sync, "start_job_run", fake_start_job_run)
        self._install(ads_sync, "finish_job_run", fake_finish_job_run)
        self._install(ads_sync, "acquire_sync_lock", fake_acquire_sync_lock)
        self._install(ads_sync, "release_sync_lock", fake_release_sync_lock)
        self._install(ads_sync, "mark_connection_sync_error", fake_mark_connection_sync_error)
        self._install(ads_sync, "mark_connection_sync_no_data", AsyncMock())
        self._install(ads_sync, "mark_connection_sync_partial", AsyncMock())
        self._install(ads_sync, "mark_connection_sync_success", AsyncMock())
        self._install(ads_sync, "refresh_dashboard_read_model_safely", AsyncMock(return_value={"ok": True}))
        self._install(ads_sync, "_pick_paid_connection", AsyncMock(return_value=_paid_connection()))
        self._install(ads_sync, "ensure_valid_meta_token", AsyncMock(return_value="token-abc"))
        self._install(ads_sync, "_fetch_boosted_insight_rows", AsyncMock(return_value=[]))
        self._install(ads_sync, "_upsert_ad_account_daily_stats", AsyncMock(return_value=_empty_upsert()))
        self._install(ads_sync, "_upsert_campaign_daily_stats", AsyncMock(return_value=_empty_upsert()))
        self._install(ads_sync, "_upsert_ad_daily_stats", AsyncMock(return_value=_empty_upsert()))
        self._install(ads_sync, "_upsert_promoted_post_daily_stats", AsyncMock(return_value=_empty_upsert()))
        self._install(ads_sync, "_readback_persisted_rows", AsyncMock(return_value=_empty_readback()))
        ads_sync._RECENT_SYNC_KEYS.clear()

    def _install(self, target_module, name, replacement):
        patcher = patch.object(target_module, name, replacement)
        patcher.start()
        self.patchers.append(patcher)

    def tearDown(self):
        for patcher in self.patchers:
            patcher.stop()
        ads_sync._RECENT_SYNC_KEYS.clear()


class CancellationTests(_BaseAdsSyncTest):
    async def test_cancelled_during_graph_call_finishes_job_marks_error_and_releases_lock(self):
        async def cancelling_fetch(**_kwargs):
            raise asyncio.CancelledError()

        self._install(ads_sync, "fetch_ad_account_insights", cancelling_fetch)

        with self.assertRaises(asyncio.CancelledError):
            await ads_sync.sync_ads_for_client_period(
                client_id="amalie", since="2026-07-01", until="2026-07-31",
                connection_id="conn-1",
            )

        self.assertEqual(len(self.finish_job_run_calls), 1)
        self.assertEqual(self.finish_job_run_calls[0]["status"], "error")
        self.assertIsNotNone(self.finish_job_run_calls[0].get("error"))
        self.assertEqual(len(self.mark_error_calls), 1)
        self.assertEqual(len(self.release_lock_calls), 1)


class TimeoutTests(_BaseAdsSyncTest):
    async def test_timeout_finishes_job_as_error_and_releases_lock(self):
        async def slow_fetch(**_kwargs):
            await asyncio.sleep(0.2)
            return []

        self._install(ads_sync, "fetch_ad_account_insights", slow_fetch)

        with patch.object(ads_sync, "_ADS_SYNC_TOTAL_TIMEOUT_SECONDS", 0.01):
            with self.assertRaises((asyncio.TimeoutError, TimeoutError)):
                await ads_sync.sync_ads_for_client_period(
                    client_id="amalie", since="2026-07-01", until="2026-07-31",
                    connection_id="conn-1",
                )

        self.assertEqual(len(self.finish_job_run_calls), 1)
        self.assertEqual(self.finish_job_run_calls[0]["status"], "error")
        self.assertTrue(self.finish_job_run_calls[0]["payload_json"].get("timeout"))
        self.assertEqual(len(self.release_lock_calls), 1)


class SuccessAndFailureFinalizationTests(_BaseAdsSyncTest):
    async def test_success_finishes_with_persisted_row_count_and_releases_lock(self):
        account = [{"date_start": "2026-05-01", "spend": "10"}]
        self._install(ads_sync, "fetch_ad_account_insights", AsyncMock(side_effect=[account, [], []]))
        ads_sync._upsert_ad_account_daily_stats.return_value = {"upserted": 1, "skipped": False}
        ads_sync._readback_persisted_rows.return_value = {
            **_empty_readback(), "ad_account_daily_stats": {"count": 1, "mode": "connection_scope"},
        }
        result = await ads_sync.sync_ads_for_client_period(
            client_id="amalie", since="2026-05-01", until="2026-05-01", connection_id="conn-1",
        )
        self.assertEqual(result["job_status"], "success")
        self.assertEqual(self.finish_job_run_calls[-1]["status"], "success")
        self.assertEqual(self.finish_job_run_calls[-1]["rows_upserted"], 1)
        self.assertEqual(len(self.release_lock_calls), 1)

    async def test_provider_exception_finishes_error_and_releases_lock(self):
        self._install(ads_sync, "fetch_ad_account_insights", AsyncMock(side_effect=RuntimeError("upstream")))
        with self.assertRaisesRegex(RuntimeError, "upstream"):
            await ads_sync.sync_ads_for_client_period(
                client_id="amalie", since="2026-05-01", until="2026-05-07", connection_id="conn-1",
            )
        self.assertEqual(self.finish_job_run_calls[-1]["status"], "error")
        self.assertEqual(len(self.release_lock_calls), 1)

    async def test_lock_denied_finishes_skipped_without_release_of_foreign_lock(self):
        self._install(ads_sync, "acquire_sync_lock", AsyncMock(return_value=False))
        with self.assertRaises(ads_sync.IntegrationError):
            await ads_sync.sync_ads_for_client_period(
                client_id="amalie", since="2026-05-01", until="2026-05-07", connection_id="conn-1",
            )
        self.assertEqual(self.finish_job_run_calls[-1]["status"], "skipped")
        self.assertEqual(self.release_lock_calls, [])

    async def test_connection_validation_after_job_start_is_terminal(self):
        self._install(ads_sync, "_pick_paid_connection", AsyncMock(return_value={"id": "conn-1"}))
        with self.assertRaisesRegex(RuntimeError, "ad_account_id"):
            await ads_sync.sync_ads_for_client_period(
                client_id="amalie", since="2026-05-01", until="2026-05-07", connection_id="conn-1",
            )
        self.assertEqual(self.finish_job_run_calls[-1]["status"], "error")


class NoDataPathTests(_BaseAdsSyncTest):
    async def test_no_account_rows_finishes_job_as_skipped_and_releases_lock(self):
        self._install(ads_sync, "fetch_ad_account_insights", AsyncMock(return_value=[]))

        result = await ads_sync.sync_ads_for_client_period(
            client_id="amalie", since="2026-07-01", until="2026-07-31",
            connection_id="conn-1",
        )

        self.assertEqual(result["sync_outcome"], "no_data")
        self.assertEqual(len(self.finish_job_run_calls), 1)
        self.assertEqual(self.finish_job_run_calls[0]["status"], "skipped")
        self.assertEqual(len(self.release_lock_calls), 1)


class DailyCheckpointTests(_BaseAdsSyncTest):
    async def test_daily_rows_are_saved_before_optional_boosted_failure(self):
        account = [{"date_start": f"2026-08-{day:02d}", "spend": "10"} for day in range(4, 11)]
        campaign = [{"date_start": "2026-08-04", "campaign_id": "c1", "spend": "10"}]
        ads = [{"date_start": "2026-08-04", "campaign_id": "c1", "adset_id": "s1", "ad_id": "a1", "spend": "10"}]
        fetch = AsyncMock(side_effect=[account, campaign, ads])
        self._install(ads_sync, "fetch_ad_account_insights", fetch)
        ads_sync._fetch_boosted_insight_rows.side_effect = RuntimeError("catalog unavailable")
        ads_sync._upsert_ad_account_daily_stats.return_value = {"upserted": 7, "skipped": False}
        ads_sync._upsert_campaign_daily_stats.return_value = {"upserted": 1, "skipped": False}
        ads_sync._upsert_ad_daily_stats.return_value = {"upserted": 1, "skipped": False}
        ads_sync._readback_persisted_rows.return_value = {
            **_empty_readback(), "ad_account_daily_stats": {"count": 7, "mode": "connection_scope"},
        }

        result = await ads_sync.sync_ads_for_client_period(
            client_id="amalie", since="2026-08-04", until="2026-08-10", connection_id="conn-1",
        )

        self.assertEqual(fetch.await_args_list[0].kwargs["time_increment"], 1)
        ads_sync._upsert_ad_account_daily_stats.assert_awaited_once()
        ads_sync._upsert_campaign_daily_stats.assert_awaited_once()
        ads_sync._upsert_ad_daily_stats.assert_awaited_once()
        self.assertEqual(result["saved"]["ad_account_daily_stats"], 7)


class LockIdentityTests(unittest.TestCase):
    def test_lock_name_ignores_since_and_until(self):
        with_period = build_sync_lock_name("meta_ads", "conn-1", "2026-07-01", "2026-07-31")
        without_period = build_sync_lock_name("meta_ads", "conn-1")
        self.assertEqual(without_period, "sync:meta_ads:conn-1")
        self.assertNotEqual(with_period, without_period)


class LockAcquisitionUsesConnectionOnlyIdentityTests(_BaseAdsSyncTest):
    async def test_two_different_periods_same_connection_use_identical_lock_name(self):
        captured_lock_names = []

        async def capturing_acquire(_client_id, lock_name, _ttl):
            captured_lock_names.append(lock_name)
            return True

        self._install(ads_sync, "acquire_sync_lock", capturing_acquire)
        self._install(ads_sync, "fetch_ad_account_insights", AsyncMock(return_value=[]))

        await ads_sync.sync_ads_for_client_period(
            client_id="amalie", since="2026-07-01", until="2026-07-31",
            connection_id="conn-1",
        )
        await ads_sync.sync_ads_for_client_period(
            client_id="amalie", since="2026-08-01", until="2026-08-31",
            connection_id="conn-1",
        )

        self.assertEqual(len(captured_lock_names), 2)
        self.assertEqual(captured_lock_names[0], captured_lock_names[1])
        self.assertNotIn("2026-07-01", captured_lock_names[0])
        self.assertNotIn("2026-08-01", captured_lock_names[1])


class PageCapTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_ad_account_insights_stops_at_max_pages(self):
        from services import ads_meta

        call_count = {"n": 0}

        async def infinite_pages(_url, params=None, request_context=None):
            call_count["n"] += 1
            return {
                "data": [{"date_start": "2026-07-01"}],
                "paging": {"next": f"https://graph.example/next-page?after={call_count['n']}"},
            }

        with patch.object(ads_meta, "_meta_get", infinite_pages):
            with self.assertRaises(IntegrationError) as raised:
                await ads_meta.fetch_ad_account_insights(
                    ad_account_id="act_123", access_token="token",
                    since="2026-07-01", until="2026-07-31", level="ad",
                )

        self.assertEqual(call_count["n"], ads_meta._MAX_INSIGHTS_PAGES)
        self.assertEqual(raised.exception.code, "META_ADS_PAGINATION_INCOMPLETE")
        self.assertEqual(raised.exception.diagnostics["reason"], "safety_limit_reached")


class IncompletePaginationSyncTests(_BaseAdsSyncTest):
    async def test_truncated_dataset_never_persists_or_marks_sync_success_and_releases_lock(self):
        from services import ads_meta
        self._install(ads_sync, 'fetch_ad_account_insights', ads_meta.fetch_ad_account_insights)
        get = AsyncMock(return_value={'data': [{'date_start': '2026-07-01', 'spend': '10'}], 'paging': {'next': 'https://graph.example/p?after=1'}})
        with patch.object(ads_meta, '_MAX_INSIGHTS_PAGES', 1), patch.object(ads_meta, '_meta_get', get):
            with self.assertRaises(IntegrationError) as raised:
                await ads_sync.sync_ads_for_client_period(client_id='amalie', since='2026-07-01', until='2026-07-31', connection_id='conn-1')
        self.assertEqual(raised.exception.code, 'META_ADS_PAGINATION_INCOMPLETE')
        ads_sync._upsert_ad_account_daily_stats.assert_not_awaited()
        ads_sync.mark_connection_sync_success.assert_not_awaited()
        self.assertEqual(self.finish_job_run_calls[0]['status'], 'error')
        self.assertEqual(len(self.release_lock_calls), 1)
        self.assertEqual(get.await_args.kwargs['request_context']['client_id'], 'amalie')


if __name__ == "__main__":
    unittest.main()


class ProjectionFreshnessTests(_BaseAdsSyncTest):
    async def test_projection_failure_never_marks_success(self):
        self._install(ads_sync, "fetch_ad_account_insights", AsyncMock(side_effect=[[{"date_start":"2026-05-01", "spend":"10"}], [], []]))
        ads_sync._upsert_ad_account_daily_stats.return_value = {"upserted":1, "skipped":False}
        ads_sync._readback_persisted_rows.return_value = {**_empty_readback(), "ad_account_daily_stats":{"count":1,"mode":"connection_scope"}}
        ads_sync.refresh_dashboard_read_model_safely.return_value = {"ok":False}
        from services.integration_errors import IntegrationError
        with self.assertRaises(IntegrationError) as error:
            await ads_sync.sync_ads_for_client_period(client_id="amalie", since="2026-05-01", until="2026-05-01", connection_id="conn-1", persisted_only=True)
        self.assertEqual(error.exception.code, "META_ADS_PROJECTION_FAILED")
        ads_sync.mark_connection_sync_success.assert_not_awaited()

    async def test_freshness_is_projected_before_connection_success(self):
        self._install(ads_sync, "fetch_ad_account_insights", AsyncMock(side_effect=[[{"date_start":"2026-05-01", "spend":"10"}], [], []]))
        ads_sync._upsert_ad_account_daily_stats.return_value = {"upserted":1, "skipped":False}
        ads_sync._readback_persisted_rows.return_value = {**_empty_readback(), "ad_account_daily_stats":{"count":1,"mode":"connection_scope"}}
        stages=[]
        async def projection(**kwargs):
            self.assertEqual(kwargs, {"client_id":"amalie","start":"2026-05-01","end":"2026-05-01","provider":"meta"})
            stages.append("freshness"); return {"ok":True}
        async def success(cid): stages.append("success")
        self._install(ads_sync,"refresh_dashboard_read_model_safely",projection)
        self._install(ads_sync,"mark_connection_sync_success",success)
        result=await ads_sync.sync_ads_for_client_period(client_id="amalie", since="2026-05-01", until="2026-05-01", connection_id="conn-1", persisted_only=True)
        self.assertEqual(result["sync_outcome"],"success")
        self.assertEqual(stages,["freshness","success"])

    async def test_graph_rate_limit_is_explicit_429(self):
        from services.meta_http import MetaApiError
        from services.integration_errors import IntegrationError
        self._install(ads_sync, "fetch_ad_account_insights", AsyncMock(side_effect=MetaApiError("sensitive upstream", status_code=429, error_code=4, rate_limited=True)))
        with self.assertRaises(IntegrationError) as error:
            await ads_sync.sync_ads_for_client_period(client_id="amalie", since="2026-05-01", until="2026-05-01", connection_id="conn-1", persisted_only=True)
        self.assertEqual(error.exception.status_code,429)
        self.assertEqual(error.exception.diagnostics["retry_after"],60)
        self.assertNotIn("sensitive",error.exception.public_message)
        ads_sync.mark_connection_sync_success.assert_not_awaited()


class ManualRefreshHttpFinalizationTests(_BaseAdsSyncTest):
    """Real Ads/facade/router/finally boundaries, synthetic provider and DB only."""
    async def request_refresh(self, *, organic=None, outer_release_error=False, finish_error=False, ads_release_error=False):
        import httpx
        from fastapi import FastAPI
        from routes import integrations
        from services import provider_refresh, sync_locks
        account = [{"date_start": "2026-05-01", "spend": "10"}]
        self._install(ads_sync, "fetch_ad_account_insights", AsyncMock(side_effect=[account, [], []]))
        ads_sync._upsert_ad_account_daily_stats.return_value = {"upserted": 1, "skipped": False}
        ads_sync._readback_persisted_rows.return_value = {
            **_empty_readback(), "ad_account_daily_stats": {"count": 1, "mode": "connection_scope"},
        }
        self.rpc_calls = []
        async def rpc(name, args):
            self.rpc_calls.append((name, args))
            if name == 'release_client_job_lock':
                print(f"[test][release] {args['p_job_name']}")
            if outer_release_error and name == 'release_client_job_lock' and args['p_job_name'] == 'sync:data_refresh:meta':
                raise RuntimeError('synthetic cleanup failure')
            if ads_release_error and name == 'release_client_job_lock' and args['p_job_name'] == 'sync:meta_ads:conn-1':
                raise OSError('synthetic Ads cleanup failure')
            return True
        async def resolve(**kwargs):
            return {"connection_id": ('organic' if organic is not None else None) if kwargs['platform']=='instagram' else 'conn-1',
                    "row": {"ig_user_id": "synthetic"}}
        self._install(sync_locks, 'sb_rpc', rpc)
        self._install(ads_sync, 'acquire_sync_lock', sync_locks.acquire_sync_lock)
        self._install(ads_sync, 'release_sync_lock', sync_locks.release_sync_lock)
        self._install(provider_refresh, 'acquire_sync_lock', sync_locks.acquire_sync_lock)
        self._install(provider_refresh, 'resolve_connection_for_scope', resolve)
        self._install(provider_refresh, 'invalidate_namespace', AsyncMock())
        self._install(provider_refresh, 'sync_instagram_for_client', AsyncMock(side_effect=organic) if isinstance(organic, Exception) else AsyncMock(return_value=organic))
        self._install(integrations, 'require_client_role', AsyncMock(return_value='amalie'))
        if finish_error:
            self._install(ads_sync, 'finish_job_run', AsyncMock(side_effect=RuntimeError('synthetic finish failure')))
        import io
        from contextlib import redirect_stdout
        from services import request_performance
        app = FastAPI()
        app.include_router(integrations.router)
        output = io.StringIO()
        _state, token = request_performance.begin('synthetic-refresh-request')
        try:
            with redirect_stdout(output):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test') as client:
                    response = await client.post('/api/clients/amalie/data-refresh/meta', json={'start':'2026-05-01','end':'2026-05-01'})
        finally:
            request_performance.end(token)
            self.output = output.getvalue()
        return response

    async def test_completed_ads_returns_http_success_after_job_finish_and_both_distinct_releases(self):
        response = await self.request_refresh()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'ok':True,'client_id':'amalie','provider':'meta','sources':{'Meta Ads':{'status':'success'}}})
        ads_sync._upsert_ad_account_daily_stats.assert_awaited_once()
        ads_sync.refresh_dashboard_read_model_safely.assert_awaited_once()
        ads_sync.mark_connection_sync_success.assert_awaited_once()
        self.assertEqual(self.finish_job_run_calls[-1]['status'], 'success')
        self.assertEqual(self.finish_job_run_calls[-1]['rows_upserted'], 1)
        released = [args['p_job_name'] for name, args in self.rpc_calls if name == 'release_client_job_lock']
        self.assertEqual(released, ['sync:meta_ads:conn-1','sync:data_refresh:meta'])
        self.assertNotIn('refresh_cooldown:meta', released)

    async def test_ads_release_failure_keeps_persisted_success_and_reports_unconfirmed_lock(self):
        response = await self.request_refresh(ads_release_error=True)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['sources']['Meta Ads']['status'], 'success')
        self.assertEqual(self.finish_job_run_calls[-1]['status'], 'success')
        self.assertEqual(self.finish_job_run_calls[-1]['rows_upserted'], 1)
        self.assertIn('lock_release_failed', self.output)
        self.assertIn('released=false', self.output)
        self.assertEqual(self.mark_error_calls, [])

    async def test_ads_success_does_not_mask_partial_instagram_http_502(self):
        response = await self.request_refresh(organic={'ok':True,'partial':True,'read_model_refreshed':True})
        self.assertEqual(response.status_code, 502)
        self.assertIn('Instagram', response.json()['detail'])
        self.assertNotIn('Meta Ads', response.json()['detail'])
        self.assertEqual(self.finish_job_run_calls[-1]['status'], 'success')
        self.assertEqual(len(self.mark_error_calls), 0)

    async def test_terminal_job_failure_after_body_success_is_not_forced_to_200(self):
        response = await self.request_refresh(finish_error=True)
        self.assertEqual(response.status_code, 502)
        self.assertIn('Meta Ads', response.json()['detail'])
        self.assertNotIn('synthetic', response.text)

    async def test_outer_release_exception_overrides_return_but_does_not_rewrite_ads_job(self):
        response = await self.request_refresh(outer_release_error=True)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.finish_job_run_calls[-1]['status'], 'success')
        self.assertEqual(len(self.mark_error_calls), 0)


    async def test_instagram_exception_reproduces_502_after_successful_ads_finalization(self):
        response = await self.request_refresh(organic=ValueError('synthetic-sensitive-provider-message'))
        self.assertEqual(response.status_code, 502)
        self.assertIn('Instagram', response.json()['detail'])
        self.assertNotIn('Meta Ads', response.json()['detail'])
        self.assertNotIn('synthetic-sensitive-provider-message', response.text)
        self.assertNotIn('synthetic-sensitive-provider-message', self.output)
        self.assertIn('source=Instagram stage=source_result', self.output)
        self.assertIn('error_type=ValueError error_origin=', self.output)
        self.assertIn('request_id=synthetic-refresh-request', self.output)
        markers = ['[meta_ads][manual_refresh_done] client_id=amalie status=success',
                   '[ads_sync][job_finish_complete]', '[test][release] sync:meta_ads:conn-1',
                   '[ads_sync][lock_release_complete] request_id=synthetic-refresh-request',
                   '[meta][manual_refresh_error]', '[test][release] sync:data_refresh:meta']
        positions = [self.output.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(len(self.finish_job_run_calls), 1)
        self.assertEqual(self.finish_job_run_calls[0]['status'], 'success')
        self.assertEqual(len(self.mark_error_calls), 0)
        ads_sync._upsert_ad_account_daily_stats.assert_awaited_once()
        ads_sync.refresh_dashboard_read_model_safely.assert_awaited_once()
        self.assertEqual([args['p_job_name'] for name, args in self.rpc_calls if name=='release_client_job_lock'],
                         ['sync:meta_ads:conn-1', 'sync:data_refresh:meta'])


class BusyAdsOutcomeTests(_BaseAdsSyncTest):
    async def test_capacity_refusal_is_skipped_without_marking_provider_failure(self):
        from services import memory_budget
        self._install(ads_sync,'fetch_ad_account_insights',AsyncMock())
        async with memory_budget.operation_memory('instagram',limit=True):
            with self.assertRaises(IntegrationError) as error:
                await ads_sync.sync_ads_for_client_period(client_id='roove',connection_id='conn-1',since='2026-05-01',until='2026-05-01')
        self.assertEqual(error.exception.code,'PROCESS_MEMORY_BUSY')
        self.assertEqual(self.mark_error_calls,[])
        self.assertEqual(self.finish_job_run_calls[-1]['status'],'skipped')
        self.assertEqual(self.finish_job_run_calls[-1]['payload_json']['error_code'],'PROCESS_MEMORY_BUSY')
        self.assertEqual(len(self.release_lock_calls),1)
        ads_sync.fetch_ad_account_insights.assert_not_awaited()


class ReleaseFailureRegressionTests(_BaseAdsSyncTest):
    async def test_cancelled_release_timeout_preserves_cancellation_and_drains_rpc(self):
        import io
        from contextlib import redirect_stdout
        entered = asyncio.Event()
        rpc_tasks = []

        async def blocked_release(*_args):
            rpc_tasks.append(asyncio.current_task())
            entered.set()
            await asyncio.Event().wait()

        output = io.StringIO()
        with patch.object(ads_sync, 'release_sync_lock', blocked_release), patch.object(ads_sync, '_ADS_CLEANUP_TIMEOUT_SECONDS', 0.01), redirect_stdout(output):
            task = asyncio.create_task(ads_sync._release_lock_reliably('amalie', 'synthetic-lock'))
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(all(rpc.done() for rpc in rpc_tasks))
        self.assertIn('lock_release_failed', output.getvalue())
        self.assertIn('error_type=TimeoutError', output.getvalue())

    async def test_original_provider_error_survives_release_error(self):
        original = RuntimeError('synthetic provider failure')
        self._install(ads_sync, 'fetch_ad_account_insights', AsyncMock(side_effect=original))
        self._install(ads_sync, 'release_sync_lock', AsyncMock(side_effect=OSError('synthetic cleanup failure')))
        with self.assertRaises(RuntimeError) as caught:
            await ads_sync.sync_ads_for_client_period(client_id='amalie', connection_id='conn-1', since='2026-05-01', until='2026-05-01')
        self.assertIs(caught.exception, original)
        self.assertEqual(self.finish_job_run_calls[-1]['status'], 'error')

    async def test_successful_release_is_confirmed(self):
        self.assertIs(await ads_sync._release_lock_reliably('amalie', 'synthetic-lock'), True)
        self.assertEqual(self.release_lock_calls, [('amalie', 'synthetic-lock')])

    async def test_successful_persistence_is_not_rewritten_when_release_fails(self):
        import io
        from contextlib import redirect_stdout
        self._install(ads_sync, 'fetch_ad_account_insights', AsyncMock(side_effect=[[{'date_start': '2026-05-01', 'spend': '10'}], [], []]))
        ads_sync._upsert_ad_account_daily_stats.return_value = {'upserted': 1, 'skipped': False}
        ads_sync._readback_persisted_rows.return_value = {**_empty_readback(), 'ad_account_daily_stats': {'count': 1, 'mode': 'connection_scope'}}
        self._install(ads_sync, 'release_sync_lock', AsyncMock(side_effect=OSError('synthetic cleanup failure')))
        output = io.StringIO()
        with redirect_stdout(output):
            result = await ads_sync.sync_ads_for_client_period(client_id='amalie', connection_id='conn-1', since='2026-05-01', until='2026-05-01')
        self.assertEqual(result['job_status'], 'success')
        self.assertEqual(self.finish_job_run_calls[-1]['status'], 'success')
        self.assertEqual(self.finish_job_run_calls[-1]['rows_upserted'], 1)
        self.assertIn('lock_release_failed', output.getvalue())
        self.assertIn('released=false', output.getvalue())
        self.assertNotIn('released=true', output.getvalue())
        self.assertEqual(self.mark_error_calls, [])

    async def test_release_failure_returns_false_instead_of_confirmation(self):
        self._install(ads_sync, 'release_sync_lock', AsyncMock(side_effect=OSError('synthetic cleanup failure')))
        self.assertIs(await ads_sync._release_lock_reliably('amalie', 'synthetic-lock'), False)
