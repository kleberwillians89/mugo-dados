from __future__ import annotations
import sys
from pathlib import Path
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import data_health as health, commerce_context
from services.fbits_official_kpis import persisted_snapshot, OfficialKpisUnavailable

NOW = datetime(2026, 10, 19, 18, tzinfo=timezone.utc)
START, END = '2026-10-01', '2026-10-19'
STAMP = '2026-10-19T17:50:00+00:00'

def connection(provider='ga4'):
    return {'id': 'conn-a', 'client_id': 'tenant-a', 'provider': provider, 'status': 'connected', 'metadata': {'ga4_property_id': '123'}}

def job(status='success', stamp=STAMP, complete=True):
    return {'client_id': 'tenant-a', 'connection_id': 'conn-a', 'job_name': 'ga4_sync_manual',
            'status': status, 'started_at': stamp, 'finished_at': stamp,
            'payload_json': {'property_id': '123', 'collection_complete': complete,
                'read_model_refreshed': True, 'period': {'start': START, 'end': END}}}

def official_row():
    row = connection('fbits')
    row['metadata'] = {'official_kpi_snapshots': {'2026-10-01:2026-10-19:2026-09-12:2026-09-30': {
        'connection_id': 'conn-a', 'updated_at': STAMP, 'value': {'current': {'receita_oficial': 12.0, 'pedidos': 2, 'ticket_medio': 6.0}, 'previous': None}}}}
    return row

class FreshnessEvidenceTests(unittest.TestCase):
    def source(self, jobs=None, daily=None, row=None, locks=None, **kwargs):
        return health.compose_source('ga4', row or connection(), jobs or [], locks or [], daily or [], START, END, now=NOW, **kwargs)

    def test_recent_sync_with_old_facts_keeps_distinct_clocks(self):
        result = self.source(jobs=[job()], daily=[{'metric_date': START, 'ga4_sessions': 2}])
        self.assertEqual(result['last_successful_sync_at'], STAMP)
        self.assertEqual(result['last_data_at'], START)
        self.assertEqual(result['coverage_end'], END)

    def test_recent_facts_do_not_refresh_old_sync(self):
        result = self.source(jobs=[job(stamp='2026-10-15T12:00:00Z')], daily=[{'metric_date': END, 'ga4_sessions': 2}])
        self.assertEqual(result['state'], 'stale')
        self.assertEqual(result['last_data_at'], END)

    def test_failure_preserves_previous_success(self):
        result = self.source(jobs=[job('error'), job(stamp='2026-10-18T12:00:00Z')])
        self.assertEqual(result['last_successful_sync_at'], '2026-10-18T12:00:00Z')
        self.assertEqual(result['last_attempt_at'], STAMP)
        self.assertEqual(result['state'], 'attention')

    def test_partial_http_success_never_becomes_successful_sync(self):
        result = self.source(jobs=[job(complete=False)], daily=[{'metric_date': END, 'ga4_sessions': 2}])
        self.assertEqual(result['sync_status'], 'partial')
        self.assertIsNone(result['last_successful_sync_at'])
        self.assertIsNone(result['coverage_end'])

    def test_fact_dates_and_updated_at_never_invent_coverage_or_success(self):
        row = connection(); row['updated_at'] = STAMP
        result = self.source(row=row, daily=[{'metric_date': END, 'ga4_sessions': 0}])
        self.assertIsNone(result['coverage_end'])
        self.assertIsNone(result['last_successful_sync_at'])
        self.assertEqual(result['last_data_at'], END)

    def test_revoked_google_token_requires_reconnect(self):
        row = connection(); row['status'] = 'reauth_required'
        result = self.source(row=row, jobs=[job()])
        self.assertEqual(result['state'], 'reauth_required')
        self.assertEqual(result['error_code'], 'REAUTH_REQUIRED')

    def test_running_after_restart_requires_live_lease(self):
        self.assertEqual(self.source(jobs=[job('running')])['sync_status'], 'unknown')
        result = self.source(jobs=[job('running')], locks=[{'job_name': 'sync:ga4:property:123', 'locked_until': '2026-10-19T19:00:00Z'}])
        self.assertEqual(result['state'], 'updating')

    def test_other_connection_or_property_does_not_supply_success(self):
        wrong = job(); wrong['payload_json']['property_id'] = 'other'
        self.assertIsNone(self.source(jobs=[wrong])['last_successful_sync_at'])
        wrong = job(); wrong['connection_id'] = 'other'
        self.assertIsNone(self.source(jobs=[wrong])['last_successful_sync_at'])

    def test_token_validation_job_never_counts_as_data_sync(self):
        token = job(); token['job_name'] = 'meta_token_refresh'
        self.assertIsNone(self.source(jobs=[token])['last_successful_sync_at'])

    def test_fbits_official_clock_is_exact_period_snapshot_not_orders(self):
        row = official_row(); row['last_sync_at'] = '2026-10-19T17:59:00Z'
        result = health.official_source(row, START, END, now=NOW)
        self.assertEqual(result['last_successful_sync_at'], STAMP)
        self.assertIsNone(result['last_data_at'])
        self.assertEqual(result['coverage_end'], END)
        other = health.official_source(row, '2026-09-01', '2026-09-30', now=NOW)
        self.assertIsNone(other['last_successful_sync_at'])
        self.assertEqual(other['error_code'], 'FBITS_OFFICIAL_SNAPSHOT_MISSING')

    def test_fbits_invalid_snapshot_never_becomes_zero(self):
        row = official_row()
        for entry in row['metadata']['official_kpi_snapshots'].values(): entry['value']['current']['receita_oficial'] = float('nan')
        with self.assertRaises(OfficialKpisUnavailable):
            persisted_snapshot(row, START, END, '2026-09-12', '2026-09-30')

class HealthReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_is_bounded_tenant_scoped_and_never_calls_providers(self):
        async def read(table, **kwargs):
            self.assertEqual(kwargs['filters']['client_id'], 'eq.tenant-a')
            self.assertLessEqual(kwargs['limit'], 366)
            return [connection(), {'id': 'other', 'client_id': 'tenant-b', 'provider': 'shopify'}] if table == 'integration_connections' else []
        with patch.object(health, 'sb_select', side_effect=read) as query:
            result = await health.client_data_health('tenant-a', START, END)
        self.assertEqual(query.await_count, 7)
        self.assertEqual(result['client_id'], 'tenant-a')
        self.assertFalse(next(s for s in result['sources'] if s['provider']=='shopify')['connected'])
        self.assertNotIn('metadata', str(result))

    async def test_missing_table_is_attention_not_empty_success(self):
        with patch.object(health, 'sb_select', AsyncMock(side_effect=RuntimeError('fixture'))):
            result = await health.client_data_health('tenant-a', START, END)
        self.assertTrue(all(s['state'] == 'attention' for s in result['sources']))
        self.assertTrue(all(s['last_successful_sync_at'] is None for s in result['sources']))

    async def test_route_authorizes_before_read_and_rejects_other_tenant(self):
        from routes import integrations
        from fastapi import HTTPException
        from datetime import date
        with patch.object(integrations, 'require_client_read', AsyncMock(side_effect=HTTPException(403))), patch.object(health, 'client_data_health', AsyncMock()) as read:
            with self.assertRaises(HTTPException):
                await integrations.get_data_health('tenant-b', date(2026,10,1), date(2026,10,19), 'Bearer fixture')
            read.assert_not_awaited()

    async def test_light_fbits_context_reuses_official_snapshot_without_order_scan(self):
        with patch.object(commerce_context, 'sb_select', AsyncMock(return_value=[official_row()])) as read:
            result = await commerce_context.resolve_commerce_context(client_id='tenant-a', start=START, end=END, include_details=False)
        self.assertEqual(read.await_count, 1)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['metrics']['revenue']['value'], 12)
        self.assertEqual(result['last_success_at'], STAMP)

    async def test_light_fbits_missing_snapshot_has_safe_reason(self):
        with patch.object(commerce_context, 'sb_select', AsyncMock(return_value=[connection('fbits')])):
            result = await commerce_context.resolve_commerce_context(client_id='tenant-a', start=START, end=END, include_details=False)
        self.assertEqual(result['unavailable_reason'], 'FBITS_OFFICIAL_SNAPSHOT_MISSING')
        self.assertEqual(result['metrics'], {})

class PartialPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_instagram_preserves_full_success_clock(self):
        from services import instagram_sync
        with patch.object(instagram_sync, 'sb_update', AsyncMock()) as write, patch.object(instagram_sync, 'invalidate_namespace', AsyncMock()):
            await instagram_sync._mark_connection_success('conn-a', partial=True)
        values = write.await_args.kwargs['patch']
        self.assertEqual(values['last_sync_status'], 'partial')
        self.assertNotIn('last_synced_at', values)

    async def test_official_failure_preserves_stored_snapshot_and_success_timestamp(self):
        from services import fbits_official_kpis as official
        row = official_row()
        before = repr(row)
        with patch.object(official, 'load_fbits_connection', AsyncMock(return_value=row)), patch.object(official, 'fetch_official_kpis', AsyncMock(side_effect=OfficialKpisUnavailable('FBITS_RATE_LIMITED'))), patch.object(official, 'sb_update', AsyncMock()) as write:
            with self.assertRaises(OfficialKpisUnavailable):
                await official.refresh_persisted_official_kpis('tenant-a', START, END)
        write.assert_not_awaited()
        self.assertEqual(repr(row), before)

    async def test_empty_fbits_fallback_reports_unknown_not_proven_zero(self):
        from services import fbits_reporting as reporting
        with patch.object(reporting, '_tenant_revenue_context', AsyncMock(return_value=(True, set(), connection('fbits')))), patch.object(reporting, '_read_persisted_orders', AsyncMock(return_value=[])), patch.object(reporting, 'fetch_official_kpis', AsyncMock(side_effect=OfficialKpisUnavailable('FBITS_OFFICIAL_SNAPSHOT_MISSING'))):
            result = await reporting.build_fbits_summary(client_id='tenant-a', period=reporting.FbitsPeriod(START, END))
        self.assertFalse(result['data_available'])
        self.assertEqual(result['data_status'], 'unknown')
        self.assertNotIn('Não houve vendas', result['message'])

class AdditionalScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_token_refresh_lease_never_means_data_sync_running(self):
        row = connection()
        result = health.compose_source('ga4', row, [], [{'job_name':'token_refresh:conn-a', 'locked_until':'2026-10-19T19:00:00Z'}], [], START, END, now=NOW)
        self.assertNotEqual(result['state'], 'updating')

    async def test_content_timestamp_is_publication_not_last_sync(self):
        async def read(table, **kwargs):
            if table == 'meta_connections': return [{**connection(), 'platform':'instagram', 'last_sync_status':'success', 'last_synced_at':STAMP}]
            if table == 'ig_media': return [{'client_id':'tenant-a','timestamp':'2026-10-17T12:00:00Z'}]
            return []
        with patch.object(health, 'sb_select', side_effect=read):
            result = await health.client_data_health('tenant-a', START, END)
        content = next(s for s in result['sources'] if s['provider']=='instagram_content')
        self.assertEqual(content['last_data_at'], '2026-10-17T12:00:00Z')
        self.assertEqual(content['last_successful_sync_at'], STAMP)
        self.assertIsNone(content['coverage_end'])

    async def test_canonical_partial_and_no_data_are_not_sync_success(self):
        from services.connections_service import _sync_status_for
        self.assertEqual(_sync_status_for('partial'), 'sync_partial')
        self.assertEqual(_sync_status_for('skipped'), 'sync_no_data')

class SelectedAccountTests(unittest.TestCase):
    def test_same_connection_other_ads_account_does_not_supply_freshness(self):
        google = connection('google_ads'); google['metadata'] = {'google_ads_customer_id':'new', 'last_success_at':STAMP}
        old = job(); old['job_name'] = 'google_ads_sync'; old['payload_json']['customer_id'] = 'old'
        result = health.compose_source('google_ads',google,[old],[],[],START,END,now=NOW)
        self.assertIsNone(result['last_successful_sync_at'])
        meta = {**connection('meta_ads'), 'ad_account_id':'act_new', 'last_sync_status':'success','last_synced_at':STAMP}
        old['job_name']='meta_ads_sync';old['ad_account_id']='act_old'
        result = health.compose_source('meta_ads',meta,[old],[],[],START,END,now=NOW)
        self.assertIsNone(result['last_successful_sync_at'])

class MetaAdsProjectionTests(unittest.IsolatedAsyncioTestCase):
    def meta(self, account='act_123', tenant='tenant-a', conn='conn-a'):
        return {**connection('meta_ads'), 'client_id': tenant, 'id': conn,
                'platform': 'meta_ads', 'ad_account_id': account}

    def run_record(self, status='success', account='123', **overrides):
        return {**job(status), 'job_name': 'meta_ads_sync_manual',
                'ad_account_id': account, **overrides}

    def source(self, row, jobs, locks=None):
        return health.compose_source('meta_ads', row, jobs, locks or [], [], START, END, now=NOW)

    def test_selected_account_statuses_and_missing_identity(self):
        for status, expected in [('success', 'success'), ('partial', 'partial'), ('error', 'error'), ('skipped', 'unknown'), ('running', 'unknown')]:
            with self.subTest(status=status):
                result = self.source(self.meta(), [self.run_record(status)])
                self.assertEqual(result['sync_status'], expected)
                self.assertEqual(result['last_successful_sync_at'], STAMP if status == 'success' else None)
        for record in [self.run_record(account='999'), self.run_record(account=None),
                       self.run_record(connection_id='other'), self.run_record(client_id='tenant-b'),
                       self.run_record(job_name='instagram_sync')]:
            with self.subTest(record=record):
                result = self.source(self.meta(), [record])
                self.assertIsNone(result['last_successful_sync_at'])
                self.assertIsNone(result['last_attempt_at'])
        self.assertIsNone(self.source(self.meta(account=None), [self.run_record()])['last_successful_sync_at'])

    def test_multiple_accounts_and_running_are_isolated(self):
        records = [self.run_record(), self.run_record('error', '456', connection_id='conn-b')]
        self.assertEqual(self.source(self.meta(), records)['sync_status'], 'success')
        self.assertEqual(self.source(self.meta('act_456', conn='conn-b'), records)['sync_status'], 'error')
        locks = [{'job_name': 'sync:meta_ads:conn-a', 'locked_until': '2026-10-19T19:00:00Z'}]
        self.assertEqual(self.source(self.meta(), [self.run_record('running')], locks)['state'], 'updating')
        self.assertNotEqual(self.source(self.meta(conn='conn-b'), [], locks)['state'], 'updating')
        skipped = self.run_record('skipped'); skipped['payload_json']['sync_outcome'] = 'no_data'
        self.assertEqual(self.source(self.meta(), [skipped])['sync_status'], 'no_data')

    async def test_projection_contract_and_selected_account_end_to_end(self):
        required = {
            'integration_connections': {'id','client_id','provider','status','disconnected_at','last_sync_at','metadata'},
            'meta_connections': {'id','client_id','platform','ad_account_id','status','requires_reauth','last_synced_at','last_sync_at','last_sync_status'},
            'cron_job_runs': {'client_id','connection_id','ad_account_id','job_name','status','started_at','finished_at','payload_json'},
            'cron_locks': {'client_id','job_name','locked_until'},
            'dashboard_daily_metrics': {'client_id','metric_date', *health.FIELDS.values()},
            'fbits_orders': {'client_id','order_date'}, 'ig_media': {'client_id','timestamp'},
        }
        async def read(table, **kwargs):
            columns = set(kwargs['select'].split(','))
            self.assertTrue(required[table] <= columns, table)
            self.assertEqual(kwargs['filters']['client_id'], 'eq.tenant-a')
            self.assertLessEqual(kwargs['limit'], 366)
            rows = {'meta_connections': [self.meta()], 'cron_job_runs': [self.run_record()]}.get(table, [])
            # Model real PostgREST projection: absent selected columns cannot leak through mocks.
            return [{key: value for key, value in row.items() if key in columns} for row in rows]
        with patch.object(health, 'sb_select', side_effect=read) as query:
            result = await health.client_data_health('tenant-a', START, END)
        self.assertEqual(query.await_count, 7)
        source = next(s for s in result['sources'] if s['provider'] == 'meta_ads')
        self.assertEqual(source['last_successful_sync_at'], STAMP)
        self.assertEqual(source['sync_status'], 'success')

    async def test_client_switch_does_not_reuse_previous_jobs(self):
        async def read(table, **kwargs):
            if table == 'meta_connections':
                return [self.meta(tenant=kwargs['filters']['client_id'][3:])]
            if table == 'cron_job_runs': return [self.run_record()]
            return []
        with patch.object(health, 'sb_select', side_effect=read):
            first = await health.client_data_health('tenant-a', START, END)
            second = await health.client_data_health('tenant-b', START, END)
        self.assertEqual(next(s for s in first['sources'] if s['provider']=='meta_ads')['last_successful_sync_at'], STAMP)
        self.assertIsNone(next(s for s in second['sources'] if s['provider']=='meta_ads')['last_successful_sync_at'])
