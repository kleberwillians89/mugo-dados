"""Offline regressions for operational safety; no provider/network access."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from contextlib import asynccontextmanager
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import provider_refresh, memory_budget
from services.integration_errors import IntegrationError

@asynccontextmanager
async def no_lock(**kwargs):
    yield 'synthetic'

class BusyAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_busy_shopify_never_consumes_cooldown_or_runs_provider(self):
        with patch.object(provider_refresh,'acquire_sync_lock',AsyncMock()) as cooldown, patch.object(provider_refresh,'sync_shopify_connection',AsyncMock()) as sync:
            async with memory_budget.operation_memory('instagram',limit=True):
                with self.assertRaises(IntegrationError) as error:
                    await provider_refresh.refresh_provider_data('roove','shopify','2026-10-01','2026-10-19')
                self.assertEqual(error.exception.code,'PROCESS_MEMORY_BUSY')
                self.assertEqual(error.exception.status_code,503)
                cooldown.assert_not_awaited(); sync.assert_not_awaited()
        self.assertEqual(memory_budget._ACTIVE,0)

    async def test_busy_after_preflight_remains_503_instead_of_provider_502(self):
        async def resolve(**kwargs):
            return {'connection_id': 'paid' if kwargs['platform']=='meta_ads' else None, 'row':{}}
        busy = IntegrationError('ocupado',status_code=503,code='PROCESS_MEMORY_BUSY',provider='meta_ads')
        with patch.object(provider_refresh,'guarded_sync',no_lock), patch.object(provider_refresh,'acquire_sync_lock',AsyncMock(return_value=True)), patch.object(provider_refresh,'resolve_connection_for_scope',resolve), patch.object(provider_refresh,'sync_ads_for_client_period',AsyncMock(side_effect=busy)) as sync:
            with self.assertRaises(IntegrationError) as error:
                await provider_refresh.refresh_provider_data('roove','meta','2026-10-01','2026-10-19')
        self.assertIs(error.exception,busy)
        sync.assert_awaited_once()

class CompanyLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_inactive_missing_and_other_tenant_company_never_authorize_connections(self):
        from services import client_lifecycle as lifecycle
        rows = [{'id':'roove','status':'active'}, {'id':'amalie','status':'inactive'}, {'id':'other','status':'active'}]
        conns = [{'client_id': cid, 'id': cid+'-conn'} for cid in ['roove','amalie','missing']]
        with patch.object(lifecycle,'sb_select',AsyncMock(return_value=rows)) as read:
            result = await lifecycle.operational_connections(conns)
        self.assertEqual(result,[conns[0]])
        self.assertEqual(read.await_args.kwargs['select'],'id,status')
        self.assertEqual(read.await_args.kwargs['limit'],3)

    async def test_company_read_failure_fails_closed_before_any_provider(self):
        from services import cron_jobs, client_lifecycle
        with patch.object(cron_jobs,'sb_get_active_meta_connections',AsyncMock(return_value=[{'client_id':'roove','id':'c'}])), patch.object(client_lifecycle,'sb_select',AsyncMock(side_effect=RuntimeError('offline'))), patch.object(cron_jobs,'sync_instagram_connection',AsyncMock()) as sync:
            with self.assertRaises(RuntimeError): await cron_jobs.run_daily_instagram_sync()
        sync.assert_not_awaited()

    async def test_all_scheduled_discovery_paths_skip_inactive_companies(self):
        from services import cron_jobs, client_lifecycle
        connections = [{'id':'c','client_id':'amalie','metadata':{'ga4_property_id':'1'}}]
        with patch.object(client_lifecycle,'sb_select',AsyncMock(return_value=[{'id':'amalie','status':'inactive'}])), patch.object(cron_jobs,'sb_get_active_meta_connections',AsyncMock(return_value=connections)), patch.object(cron_jobs,'sb_select',AsyncMock(return_value=connections)), patch.object(cron_jobs,'list_active_shopify_connections',AsyncMock(return_value=connections)), patch.object(cron_jobs,'_acquire_lock',AsyncMock()) as lock:
            for operation in [cron_jobs.run_token_refresh_job,cron_jobs.run_daily_instagram_sync,cron_jobs.run_hourly_ads_sync,cron_jobs.run_ga4_sync_all,cron_jobs.run_google_ads_sync_all,cron_jobs.run_fbits_sync_all,cron_jobs.run_shopify_incremental,cron_jobs.run_shopify_historical_reconciliation]:
                result = await operation()
                self.assertEqual(result.get('connections_total',0),0,operation.__name__)
            lock.assert_not_awaited()

    async def test_inactive_amalia_membership_not_listed_and_history_not_written(self):
        from services import clients
        with patch.object(clients,'sb_select',AsyncMock(return_value=[{'id':'amalie','name':'Amalie','status':'inactive'},{'id':'roove','name':'Roove','status':'active'}])), patch("services.platform_admin.is_platform_admin", AsyncMock(return_value=False)), patch.object(clients,'sb_get_client_memberships',AsyncMock(return_value=[{'client_id':'amalie','role':'viewer','clients':{'id':'amalie','name':'Amalie','status':'inactive'}},{'client_id':'roove','role':'viewer','clients':{'id':'roove','name':'Roove','status':'active'}}])), patch.object(clients,'sb_update',AsyncMock()) as write:
            result = await clients.list_clients_for_user('user')
        self.assertEqual([r['client_id'] for r in result['clients']],['roove'])
        write.assert_not_awaited()

    async def test_claimed_backfill_for_inactive_company_never_calls_provider(self):
        from services import meta_backfill, client_lifecycle
        item = {'id':'slice','backfill_job_id':'job','slice_since':'2026-01-01','slice_until':'2026-01-07'}
        job = {'id':'job','client_id':'amalie','connection_id':'conn'}
        with patch.object(client_lifecycle,'sb_select',AsyncMock(return_value=[{'id':'amalie','status':'inactive'}])), patch.object(meta_backfill,'sb_rpc',AsyncMock(return_value=[item])), patch.object(meta_backfill,'sb_select',AsyncMock(return_value=[job])), patch.object(meta_backfill,'sb_update',AsyncMock()) as update, patch.object(meta_backfill,'_update_job',AsyncMock()), patch.object(meta_backfill,'sync_ads_for_client_period',AsyncMock()) as sync:
            result = await meta_backfill.process_next_slice()
        self.assertEqual(result['reason'],'client_inactive')
        sync.assert_not_awaited()
        self.assertEqual(update.await_args.kwargs['patch']['status'],'skipped')

class CleanupLifetimeTests(unittest.IsolatedAsyncioTestCase):
    async def check_cleanup(self, finish):
        import asyncio
        from services import ads_sync
        tasks = []
        async def hang(*args, **kwargs):
            tasks.append(asyncio.current_task())
            await asyncio.Event().wait()
        name = 'finish_job_run' if finish else 'release_sync_lock'
        try:
            with patch.object(ads_sync,name,hang), patch.object(ads_sync,'_ADS_CLEANUP_TIMEOUT_SECONDS',0.001):
                if finish:
                    with self.assertRaises(RuntimeError):
                        await ads_sync._finish_job_run_reliably('synthetic-job',status='success')
                else:
                    await ads_sync._release_lock_reliably('roove','synthetic-lock')
            self.assertTrue(tasks)
            self.assertTrue(all(task.done() for task in tasks),'cleanup tasks outlived helper timeout')
        finally:
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)

    async def test_release_timeout_leaves_no_background_rpc(self):
        await self.check_cleanup(False)

    async def test_finish_timeout_drains_previous_attempt_before_retry(self):
        await self.check_cleanup(True)

class CronAggregateTests(unittest.TestCase):
    def test_failed_source_never_becomes_aggregate_success(self):
        from services.cron_jobs import _provider_job_summary
        result = _provider_job_summary('fixture',[{},{}],[{'ok':True},{'ok':False}],1)
        self.assertFalse(result['ok'])
        self.assertEqual(result['connections_ok'],1)
        self.assertEqual(result['connections_fail'],1)

class CompanyBatchingTests(unittest.IsolatedAsyncioTestCase):
    async def test_large_membership_list_reads_company_status_in_bounded_batches(self):
        import json
        from services import clients
        memberships = [{'client_id':f'tenant-{i}','role':'viewer'} for i in range(250)]
        async def read(table,**kwargs):
            self.assertEqual(table,'clients')
            ids=json.loads('['+kwargs['filters']['id'][4:-1]+']')
            self.assertLessEqual(kwargs['limit'],100)
            return [{'id':cid,'status':'active','name':cid} for cid in ids]
        with patch.object(clients,'sb_get_client_memberships',AsyncMock(return_value=memberships)) as members, patch('services.platform_admin.is_platform_admin',AsyncMock(return_value=False)), patch.object(clients,'sb_select',AsyncMock(side_effect=read)) as query:
            result = await clients.list_clients_for_user('user')
        members.assert_awaited_once_with('user',include_clients=False)
        self.assertEqual(len(result['clients']),250)
        self.assertEqual(query.await_count,3)
