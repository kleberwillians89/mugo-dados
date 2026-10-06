"""Regressões locais: nenhuma rede, credencial ou banco de produção."""
from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import ads_meta, google_ads, ga4_reporting, executive_dashboard, intelligence
from services.integration_errors import IntegrationError
from datetime import date


class MetaPaginationCompletenessTests(unittest.IsolatedAsyncioTestCase):
    async def fetch(self, pages, cap=200, client_id='tenant-a'):
        get = AsyncMock(side_effect=pages)
        with patch.object(ads_meta, '_meta_get', get), patch.object(ads_meta, '_MAX_INSIGHTS_PAGES', cap):
            result = await ads_meta.fetch_ad_account_insights(
                ad_account_id='123', access_token='fixture-only', since='2026-07-08', until='2026-10-05',
                request_context={'client_id': client_id})
        return result, get

    async def test_one_page_without_next_is_complete(self):
        rows, get = await self.fetch([{'data': [{'id': '1'}]}])
        self.assertEqual(rows, [{'id': '1'}])
        self.assertEqual(get.await_count, 1)

    async def test_multiple_pages_finish_without_next_and_do_not_duplicate(self):
        rows, get = await self.fetch([
            {'data': [{'id': '1'}], 'paging': {'next': 'https://graph.example/p?after=1'}},
            {'data': [{'id': '2'}], 'paging': {'next': 'https://graph.example/p?after=2'}},
            {'data': [{'id': '3'}]}])
        self.assertEqual([r['id'] for r in rows], ['1', '2', '3'])
        self.assertEqual(get.await_count, 3)
        self.assertIsNone(get.await_args_list[1].kwargs['params'])

    async def test_last_page_at_safety_limit_without_next_is_complete(self):
        rows, _ = await self.fetch([{'data': [{'id': '1'}]}], cap=1)
        self.assertEqual(len(rows), 1)

    async def test_identical_rows_overlapping_pages_are_not_duplicated(self):
        rows, _ = await self.fetch([
            {'data': [{'id': '1'}], 'paging': {'next': 'https://graph.example/p'}},
            {'data': [{'id': '1'}, {'id': '2'}]}])
        self.assertEqual(rows, [{'id': '1'}, {'id': '2'}])

    async def test_pending_next_at_limit_raises_safe_incomplete_error(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(IntegrationError) as raised:
            await self.fetch([{'data': [{'id': '1'}], 'paging': {'next': 'https://graph.example/p?access_token=must-not-log'}}], cap=1)
        self.assertEqual(raised.exception.code, 'META_ADS_PAGINATION_INCOMPLETE')
        self.assertTrue(raised.exception.diagnostics['incomplete'])
        self.assertEqual(raised.exception.diagnostics['reason'], 'safety_limit_reached')
        self.assertNotIn('must-not-log', output.getvalue() + str(raised.exception))
        self.assertNotIn('https://', output.getvalue())

    async def test_repeated_next_url_is_rejected_before_refetching_it(self):
        get = AsyncMock(return_value={'data': [{'id': '1'}], 'paging': {'next': 'https://graph.example/p'}})
        with patch.object(ads_meta, '_meta_get', get), self.assertRaises(IntegrationError) as raised:
            await ads_meta.fetch_ad_account_insights(ad_account_id='123', access_token='fixture-only', since='2026-07-08', until='2026-10-05')
        self.assertEqual(get.await_count, 2)
        self.assertEqual(raised.exception.diagnostics['reason'], 'repeated_next_url')

    async def test_repeated_cursor_with_different_urls_is_rejected(self):
        with self.assertRaises(IntegrationError) as raised:
            await self.fetch([
                {'data': [{'id': '1'}], 'paging': {'next': 'https://graph.example/p?after=1', 'cursors': {'after': 'same'}}},
                {'data': [{'id': '2'}], 'paging': {'next': 'https://graph.example/p?after=2', 'cursors': {'after': 'same'}}}])
        self.assertEqual(raised.exception.diagnostics['reason'], 'repeated_cursor')

    async def test_intermediate_failure_does_not_return_partial_rows(self):
        with self.assertRaisesRegex(RuntimeError, 'fixture failure'):
            await self.fetch([{'data': [{'id': '1'}], 'paging': {'next': 'https://graph.example/p'}}, RuntimeError('fixture failure')])

    async def test_each_call_keeps_its_tenant_context_and_pagination_state(self):
        for tenant in ('tenant-a', 'tenant-b'):
            rows, get = await self.fetch([{'data': [{'id': tenant}]}], client_id=tenant)
            self.assertEqual(rows, [{'id': tenant}])
            self.assertEqual(get.await_args.kwargs['request_context']['client_id'], tenant)

    async def test_invalid_next_does_not_return_success(self):
        with self.assertRaises(IntegrationError) as raised:
            await self.fetch([{'data': [], 'paging': {'next': 'not-a-url'}}])
        self.assertEqual(raised.exception.diagnostics['reason'], 'invalid_next_url')


class GoogleAdsProjectionCompletenessTests(unittest.IsolatedAsyncioTestCase):
    async def run_inner(self, *, projection=None, ingestion_error=None, projection_error=None, removed=False, empty=False):
        context = google_ads.GoogleAdsContext('tenant-a', 'connection-a', '123', None)
        response = MagicMock(status_code=200)
        result = {'segments': {'date': '2026-07-08'}, 'campaign': {'id': '1', 'name': 'fixture', 'status': 'REMOVED' if removed else 'ENABLED'},
                  'metrics': {'costMicros': '10000000', 'conversions': '2', 'conversionsValue': '30'}}
        def respond(query):
            # Reproduz o filtro GAQL que eliminava fatos de campanhas removidas.
            excluded = removed and "campaign.status != 'REMOVED'" in query['query']
            return [{'results': [] if empty or excluded else [result]}]
        http = MagicMock()
        async def post(_url, *, headers, json):
            response.json.return_value = respond(json)
            return response
        http.post = AsyncMock(side_effect=post)
        http.__aenter__ = AsyncMock(return_value=http)
        http.__aexit__ = AsyncMock(return_value=None)
        self.upsert = AsyncMock(side_effect=ingestion_error)
        self.projection = AsyncMock(side_effect=projection_error, return_value=projection if projection is not None else {'ok': True})
        with patch.object(google_ads, 'resolve_google_ads_context', AsyncMock(return_value=context)), \
             patch.object(google_ads.os, 'getenv', side_effect=lambda k: {'GOOGLE_ADS_DEVELOPER_TOKEN': 'fixture-only', 'GOOGLE_ADS_API_VERSION': 'v25'}.get(k)), \
             patch.object(google_ads, 'get_google_access_token', AsyncMock(return_value='fixture-only')), \
             patch.object(google_ads.httpx, 'AsyncClient', return_value=http), \
             patch.object(google_ads, 'sb_upsert', self.upsert), \
             patch.object(google_ads, 'refresh_dashboard_read_model_safely', self.projection):
            return await google_ads._sync_google_ads(client_id='tenant-a', connection_id='connection-a', start='2026-07-08', end='2026-10-05', days=90)

    async def test_ingestion_and_projection_success(self):
        result = await self.run_inner()
        self.assertTrue(result['ok'])
        self.assertTrue(result['read_model_refreshed'])
        self.assertEqual(self.upsert.await_args.args[1][0]['client_id'], 'tenant-a')
        self.assertEqual(self.projection.await_args.kwargs['client_id'], 'tenant-a')

    async def test_projection_failure_keeps_ingested_facts_and_propagates_error(self):
        with self.assertRaises(IntegrationError) as raised:
            await self.run_inner(projection={'ok': False, 'preserved': True})
        self.assertEqual(raised.exception.code, 'GOOGLE_ADS_PROJECTION_FAILED')
        self.assertEqual(raised.exception.status_code, 502)
        self.upsert.assert_awaited_once()

    async def test_ingestion_failure_never_projects(self):
        with self.assertRaisesRegex(RuntimeError, 'ingestion'):
            await self.run_inner(ingestion_error=RuntimeError('ingestion'))
        self.projection.assert_not_awaited()

    async def test_projection_exception_is_controlled_and_does_not_expose_raw_error(self):
        with self.assertRaises(IntegrationError) as raised:
            await self.run_inner(projection_error=RuntimeError('must-not-expose'))
        self.assertEqual(raised.exception.code, 'GOOGLE_ADS_PROJECTION_FAILED')
        self.assertNotIn('must-not-expose', str(raised.exception))

    async def test_zero_rows_still_requires_projection_success(self):
        with self.assertRaises(IntegrationError):
            await self.run_inner(empty=True, projection={'ok': False})
        self.upsert.assert_not_awaited()
        self.projection.assert_awaited_once()

    async def test_removed_campaign_with_historical_spend_and_conversions_is_persisted(self):
        result = await self.run_inner(removed=True)
        self.assertEqual(result['rows_upserted'], 1)
        row = self.upsert.await_args.args[1][0]
        self.assertEqual((row['cost'], row['conversions'], row['conversion_value']), (10, 2, 30))


class Ga4UserSemanticsTests(unittest.IsolatedAsyncioTestCase):
    def test_daily_sums_are_explicit_and_do_not_claim_deduplication(self):
        summary = ga4_reporting._build_summary([{'active_users': 100, 'total_users': 100}, {'active_users': 100, 'total_users': 100}])
        self.assertEqual(summary['total_users'], 200)
        self.assertEqual(summary['user_count_semantics'], 'sum_of_daily_users')
        self.assertEqual(summary['average_daily_total_users'], 100)

    async def test_executive_context_unique_users_unavailable_with_explicit_sum(self):
        context = MagicMock(property_id='p1')
        report = {'summary': {'total_users': 200}, 'meta': {'data_available': True}}
        with patch.object(executive_dashboard, 'build_ga4_report', AsyncMock(return_value=report)):
            section = await executive_dashboard._build_ga4_section(client_id='tenant-a', connection_id='c1', since='2026-07-08', until='2026-07-09', context=context)
        self.assertIsNone(section['users'])
        self.assertEqual(section['daily_user_sum'], 200)
        self.assertEqual(section['users_status'], 'unavailable')

    async def test_intelligence_current_and_previous_period_use_explicit_sums(self):
        rows = [{'metric_date': d, 'ga4_sessions': 10, 'ga4_users': 100} for d in ('2026-07-06', '2026-07-07', '2026-07-08', '2026-07-09')]
        with patch.object(intelligence, '_query_period', AsyncMock(side_effect=[rows, []])), \
             patch.object(intelligence, 'sb_select', AsyncMock(return_value=[])):
            context = await intelligence._read_model_executive_context('tenant-a', date(2026, 7, 8), date(2026, 7, 9), date(2026, 7, 6), date(2026, 7, 7))
        for period in (context, context['previous_period']):
            self.assertIsNone(period['ga4']['users'])
            self.assertEqual(period['ga4']['daily_user_sum'], 200)
            self.assertEqual(period['ga4']['user_count_semantics'], 'sum_of_daily_active_users')
