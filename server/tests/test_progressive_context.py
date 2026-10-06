import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import intelligence, commerce_context, business_context, request_performance
from routes import intelligence as routes

class ProgressiveContextTests(unittest.IsolatedAsyncioTestCase):
    async def snapshot(self, rows, *, detailed=False, recurrence=None, start="2026-10-06"):
        async def select(table, **kwargs):
            self.assertEqual(kwargs['filters']['client_id'], 'eq.tenant-fixture')
            if table == 'dashboard_daily_metrics': return rows
            if table == 'integration_connections': return [{'id':'shop', 'client_id':'tenant-fixture', 'provider':'shopify', 'status':'connected'}]
            if table == 'dashboard_source_snapshots': return [{'provider':'shopify', 'last_success_at':'2026-10-06'}]
            if table == 'client_business_context': return []
            if table == 'ig_media' and detailed: return []
            self.fail('Leitura pesada inesperada: '+table)
        query = AsyncMock(side_effect=select)
        with patch.object(intelligence,'sb_select',query), patch.object(commerce_context,'sb_select',query), patch.object(business_context,'sb_select',query), patch.object(intelligence,'external_research_context',AsyncMock(side_effect=AssertionError('no provider live'))), patch.object(intelligence,'recurring_customers_in_period',AsyncMock(return_value=recurrence) if detailed else AsyncMock(side_effect=AssertionError('no Customer360 scan on first paint'))):
            result = await intelligence.calculate_intelligence_snapshot(client_id='tenant-fixture',start=start,end='2026-10-06',include_commerce_details=detailed,include_external_research=False)
        self.assertEqual(sum(call.args[0]=='integration_connections' for call in query.await_args_list),1)
        self.assertEqual(query.await_count,5 if detailed else 4)
        return {metric['id']:metric for metric in result['metrics']}

    async def test_complete_coverage_without_orders_is_zero_but_ticket_not_applicable(self):
        result = await self.snapshot([{'metric_date':'2026-10-06','shopify_net_revenue':0,'shopify_orders':0,'shopify_customers':0}])
        for key in ('revenue','orders','new_customers','repeat_customers'): self.assertEqual(result[key]['value'],0)
        self.assertIsNone(result['average_ticket']['value'])

    async def test_absent_coverage_is_unavailable_including_recurrence(self):
        result = await self.snapshot([])
        for key in ('revenue','orders','new_customers','repeat_customers','average_ticket'): self.assertIsNone(result[key]['value'])

    async def test_orders_are_visible_without_fabricating_recurrence(self):
        result = await self.snapshot([{'metric_date':'2026-10-06','shopify_net_revenue':100,'shopify_orders':2,'shopify_customers':1}])
        self.assertEqual(result['orders']['value'],2)
        self.assertEqual(result['revenue']['value'],100)
        self.assertEqual(result['average_ticket']['value'],50)
        self.assertIsNone(result['repeat_customers']['value'])

    async def test_provider_resolution_is_single_flight_per_request_and_revalidated_next_request(self):
        query=AsyncMock(return_value=[{'id':'shop','client_id':'tenant-fixture','provider':'shopify','status':'connected'}])
        with patch.object(commerce_context,'sb_select',query):
            for _ in range(2):
                _,token=request_performance.begin('fixture')
                try: await asyncio.gather(commerce_context.resolve_commerce_provider('tenant-fixture'),commerce_context.resolve_commerce_provider('tenant-fixture'))
                finally: request_performance.end(token)
        self.assertEqual(query.await_count,2)

    async def test_http_context_always_disables_external_provider(self):
        calculate=AsyncMock(return_value={})
        with patch.object(routes,'_context',AsyncMock(return_value=('tenant-fixture','user'))), patch.object(routes,'calculate_intelligence_snapshot',calculate):
            await routes.intelligence_context(start='2026-10-06',end='2026-10-06',days=1,include_commerce_details=False,client_id='tenant-fixture',x_client_id=None,authorization='fixture')
        self.assertFalse(calculate.await_args.kwargs['include_external_research'])
        self.assertFalse(calculate.await_args.kwargs['include_commerce_details'])

    async def test_complete_orders_allow_calculable_zero_or_positive_recurrence(self):
        rows=[{'metric_date':'2026-10-06','shopify_net_revenue':100,'shopify_orders':2,'shopify_customers':1}]
        for recurrence in (0,1):
            result=await self.snapshot(rows,detailed=True,recurrence=recurrence)
            self.assertEqual(result['repeat_customers']['value'],recurrence)

    async def test_uncovered_period_does_not_turn_known_historical_customers_into_zero(self):
        result=await self.snapshot([],detailed=True,recurrence=0)
        self.assertIsNone(result['repeat_customers']['value'])

    async def test_partial_daily_coverage_does_not_claim_zero_for_the_whole_period(self):
        result=await self.snapshot([{'metric_date':'2026-10-06','shopify_net_revenue':0,'shopify_orders':0,'shopify_customers':0}],start='2026-10-05')
        for key in ('revenue','orders','new_customers','repeat_customers','average_ticket'):
            self.assertIsNone(result[key]['value'])
