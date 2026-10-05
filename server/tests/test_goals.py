import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch
import httpx
from fastapi import FastAPI
from services import goals, tenant, ig_supabase
from routes import goals as routes

CID="tenant-a"
GID="00000000-0000-0000-0000-000000000001"
BODY={"metric":"revenue","label":"Faturamento","target_value":50000,"period_start":"2026-09-01","period_end":"2026-09-30"}
class RuleTests(unittest.TestCase):
    def test_elapsed_pace_and_projection(self):
        goal={**BODY,"metric":"revenue","target_value":100,"period_start":"2026-10-01","period_end":"2026-10-31"}
        result=goals.evaluate_goal(goal,goals.value(50,"test",True),date(2026,10,20))
        self.assertAlmostEqual(result["elapsed_percent"],20/31*100)
        self.assertEqual(result["progress_percent"],50)
        self.assertAlmostEqual(result["pace_delta"],50-20/31*100)
        self.assertEqual(result["status"],"ATENCAO")
        self.assertAlmostEqual(result["projected_value"],77.5)
    def test_status_thresholds_and_achieved(self):
        for actual,status in [(110,"META_ATINGIDA"),(65,"NO_RITMO"),(55,"ATENCAO"),(20,"ABAIXO_DO_RITMO")]:
            result=goals.evaluate_goal({**BODY,"target_value":100},goals.value(actual,"test",True),date(2026,9,20))
            self.assertEqual(result["status"],status)
    def test_future_missing_zero_and_non_additive_have_no_projection(self):
        self.assertEqual(goals.evaluate_goal(BODY,goals.unavailable("future"),date(2026,8,1))["status"],"FUTURA")
        for goal,actual in [({**BODY,"target_value":0},goals.value(1,"test",True)), (BODY,goals.unavailable("missing")), ({**BODY,"metric":"followers"},goals.value(1,"test",True)), (BODY,goals.value(1,"partial"))]:
            self.assertIsNone(goals.evaluate_goal(goal,actual,date(2026,9,15))["projected_value"])
    def test_very_early_period_has_no_projection(self):
        self.assertIsNone(goals.evaluate_goal(BODY,goals.value(1,"test",True),date(2026,9,1))["projected_value"])
    def test_backend_input_validation(self):
        from pydantic import ValidationError
        for patching in [{"client_id":"other"},{"target_value":0},{"target_value":float("nan")},{"metric":"token"},{"label":"   "},{"period_end":"2026-08-01"}]:
            with self.assertRaises(ValidationError): routes.GoalInput(**{**BODY,**patching})

class ActualTests(unittest.IsolatedAsyncioTestCase):
    async def setup_rows(self,metric,rows):
        async def select(table,**kwargs):
            self.assertEqual(kwargs["filters"]["client_id"],f"eq.{CID}")
            return rows.get(table,[])[kwargs.get("offset",0):]
        with patch.object(goals,"sb_select",AsyncMock(side_effect=select)), patch.object(httpx.AsyncClient,"send",AsyncMock(side_effect=AssertionError("HTTP externo proibido"))) as send:
            result = await goals.resolve_goal_actual(CID,metric,"2026-09-01","2026-09-01")
            send.assert_not_awaited()
            return result
    async def test_fbits_revenue_orders_ticket_follow_existing_persisted_rule(self):
        rows={"integration_connections":[{"client_id":CID,"provider":"fbits","status":"connected","metadata":{"revenue_status_ids":["1"]}}],"fbits_orders":[{"client_id":CID,"order_date":"2026-09-01T12:00:00Z","status_id":"1","is_valid":True,"total_value":120}, {"client_id":CID,"order_date":"2026-09-01T12:00:00Z","status_id":"3","total_value":900}, {"client_id":"other","order_date":"2026-09-01T12:00:00Z","status_id":"1","total_value":9999}]}
        for metric,actual in [("revenue",120),("orders",1),("average_ticket",120)]:
            result=await self.setup_rows(metric,rows)
            self.assertEqual(result["actual"],actual)
            self.assertIn("não é o KPI oficial",result["origin"])
    async def test_shopify_revenue_orders_ticket(self):
        rows={"integration_connections":[{"client_id":CID,"provider":"shopify","status":"connected"}],"dashboard_daily_metrics":[{"client_id":CID,"metric_date":"2026-09-01","shopify_net_revenue":300,"shopify_orders":2}]}
        for metric,actual in [("revenue",300),("orders",2),("average_ticket",150)]: self.assertEqual((await self.setup_rows(metric,rows))["actual"],actual)
    async def test_social_and_ads_persisted_with_correct_period(self):
        rows={"dashboard_daily_metrics":[{"client_id":CID,"metric_date":"2026-09-01","instagram_followers":100,"instagram_reach":80,"instagram_impressions":150,"instagram_interactions":10,"meta_spend":20,"google_ads_spend":30,"meta_purchases":3}, {"client_id":CID,"metric_date":"2026-08-31","meta_spend":9999}]}
        for metric,actual in [("followers",100),("reach",80),("impressions",150),("engagement",10),("ad_spend",50),("conversions",3)]: self.assertEqual((await self.setup_rows(metric,rows))["actual"],actual)
    async def test_missing_provider_data_and_zero_ticket_are_unavailable(self):
        self.assertFalse((await self.setup_rows("revenue",{}))["available"])
        self.assertFalse((await self.setup_rows("followers",{}))["available"])
        self.assertFalse((await self.setup_rows("roas",{}))["available"])
        rows={"integration_connections":[{"client_id":CID,"provider":"shopify","status":"connected"}],"dashboard_daily_metrics":[{"client_id":CID,"metric_date":"2026-09-01","shopify_net_revenue":0,"shopify_orders":0}]}
        self.assertFalse((await self.setup_rows("average_ticket",rows))["available"])
    async def test_commerce_reporting_reuses_existing_fbits_precedence(self):
        rows={"integration_connections":[{"client_id":CID,"provider":p,"status":"connected","metadata":{"revenue_status_ids":["1"]}} for p in ["shopify","fbits"]], "fbits_orders":[{"client_id":CID,"order_date":"2026-09-01T12:00:00Z","status_id":"1","is_valid":True,"total_value":120}], "dashboard_daily_metrics":[{"client_id":CID,"metric_date":"2026-09-01","shopify_net_revenue":999,"shopify_orders":2}]}
        self.assertEqual((await self.setup_rows("revenue",rows))["actual"],120)
    async def test_persisted_read_failure_marks_goal_unavailable(self):
        # Uma falha de leitura não vira realizado zero.
        with patch.object(goals,"sb_select",AsyncMock(side_effect=[[{**BODY,"id":GID,"client_id":CID}],[]])), patch.object(goals,"resolve_goal_actual",AsyncMock(side_effect=RuntimeError("offline"))):
            result=await goals.list_goals(CID)
        self.assertEqual(result["goals"][0]["status"],"INDISPONIVEL")

class AuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app=FastAPI(); app.include_router(routes.router)
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)
        self.role="client_admin"
        async def membership(uid,requested_client_id=None):
            if requested_client_id!=CID: raise PermissionError("other")
            return CID
        for target,name,value in [(ig_supabase,"sb_select",AsyncMock(return_value=[{"id":CID}])),(tenant,"require_user_id",AsyncMock(return_value="user")),(tenant,"sb_get_client_memberships",AsyncMock(side_effect=lambda uid:[{"client_id":CID,"role":self.role}])),(tenant,"sb_get_client_id_for_user",AsyncMock(side_effect=membership)),(routes,"require_user_id",AsyncMock(return_value="user")),(routes,"list_goals",AsyncMock(return_value={"client_id":CID,"goals":[]})),(routes,"sb_insert",AsyncMock(return_value={**BODY,"client_id":CID,"id":GID})),(routes,"sb_update",AsyncMock(return_value=[{**BODY,"client_id":CID,"id":GID}])),(routes,"sb_delete",AsyncMock(return_value=[{"id":GID}]))]:
            item=patch.object(target,name,value);item.start();self.addCleanup(item.stop)
        item=patch("services.platform_admin.is_platform_admin",AsyncMock(return_value=False));item.start();self.addCleanup(item.stop)
    async def call(self,method,path="",cid=CID,body=None):
        return await self.client.request(method,f"/api/clients/{cid}/goals{path}",headers={"Authorization":"Bearer test"},**({"json":body} if body else {}))
    async def test_create_edit_delete_and_scoped_filters(self):
        self.assertEqual((await self.call("POST",body=BODY)).status_code,201)
        self.assertEqual(routes.sb_insert.await_args.args[1]["created_by"],"user")
        self.assertEqual(routes.sb_insert.await_args.args[1]["client_id"],CID)
        self.assertEqual((await self.call("PUT",f"/{GID}",body=BODY)).status_code,200)
        self.assertEqual((await self.call("DELETE",f"/{GID}")).status_code,200)
        self.assertEqual(routes.sb_delete.await_args.kwargs["filters"],{"client_id":f"eq.{CID}","id":f"eq.{GID}"})
    async def test_viewer_crud_is_scoped_to_own_tenant(self):
        self.role="viewer"
        self.assertEqual((await self.call("GET")).status_code,200)
        await self.test_create_edit_delete_and_scoped_filters()
    async def test_viewer_cannot_create_edit_or_delete_cross_tenant(self):
        self.role="viewer"
        for method,path in [("POST",""),("PUT",f"/{GID}"),("DELETE",f"/{GID}")]:
            self.assertEqual((await self.call(method,path,cid="other",body=BODY if method!="DELETE" else None)).status_code,403)
        routes.sb_insert.assert_not_awaited(); routes.sb_update.assert_not_awaited();routes.sb_delete.assert_not_awaited()
    async def test_cross_tenant_forbidden_and_payload_cannot_override(self):
        for method in ["GET","POST","PUT","DELETE"]:
            self.assertEqual((await self.call(method,f"/{GID}" if method in {"PUT","DELETE"} else "",cid="other",body=BODY if method in {"PUT","POST"} else None)).status_code,403)
        self.assertEqual((await self.call("POST",body={**BODY,"client_id":"other"})).status_code,422)
    async def test_agency_admin_uses_existing_scope_authorization(self):
        self.role="agency_admin"
        self.assertEqual((await self.call("POST",body=BODY)).status_code,201)

class MigrationTests(unittest.TestCase):
    def test_additive_table_is_tenant_scoped_and_browser_read_only(self):
        sql=(Path(__file__).resolve().parents[2]/"supabase/migrations/20261007_000043_client_goals.sql").read_text()
        self.assertIn("references public.clients(id) on delete cascade",sql)
        self.assertIn("enable row level security",sql)
        self.assertIn("public.is_client_member(client_id)",sql)
        self.assertIn("revoke all on public.client_goals from anon, authenticated",sql)
        self.assertIn("grant select on public.client_goals to authenticated",sql)
        self.assertNotIn("grant insert",sql)
        self.assertNotIn("alter table public.meta",sql)

class ConditionalMetricTests(unittest.IsolatedAsyncioTestCase):
    setup_rows = ActualTests.setup_rows
    async def test_roas_single_source_only_and_zero_safe(self):
        daily={"client_id":CID,"metric_date":"2026-09-01","meta_spend":10,"meta_attributed_revenue":40}
        result=await self.setup_rows("roas",{"dashboard_daily_metrics":[daily]})
        self.assertEqual(result["actual"],4)
        self.assertFalse((await self.setup_rows("roas",{"dashboard_daily_metrics":[{**daily,"google_ads_spend":20,"google_ads_conversion_value":50}]}))["available"])
        self.assertFalse((await self.setup_rows("roas",{"dashboard_daily_metrics":[{**daily,"meta_spend":0}]}))["available"])
    async def test_multi_day_reach_is_not_summed(self):
        result=await goals.resolve_goal_actual(CID,"reach","2026-09-01","2026-09-30")
        self.assertFalse(result["available"])
    async def test_disconnected_provider_is_unavailable(self):
        self.assertFalse((await self.setup_rows("orders",{"integration_connections":[{"client_id":CID,"provider":"fbits","status":"disconnected","metadata":{"revenue_status_ids":["1"]}}]}))["available"])

    async def test_persisted_resolution_never_sends_external_http(self):
        with patch.object(httpx.AsyncClient,"send",AsyncMock(side_effect=AssertionError("HTTP externo proibido"))) as send:
            for metric in goals.METRICS:
                await self.setup_rows(metric,{})
            send.assert_not_awaited()

    async def test_partial_daily_coverage_disables_projection(self):
        with patch.object(goals,"sb_select",AsyncMock(side_effect=[[{"client_id":CID,"metric_date":"2026-09-01","meta_spend":10}],[]])):
            result=await goals.resolve_goal_actual(CID,"ad_spend","2026-09-01","2026-09-02")
        self.assertEqual(result["actual"],10)
        self.assertFalse(result["projection_ready"])

    async def test_each_paid_source_needs_coverage_for_projection(self):
        rows=[{"client_id":CID,"metric_date":"2026-09-01","meta_spend":10}, {"client_id":CID,"metric_date":"2026-09-02","google_ads_spend":20}]
        with patch.object(goals,"sb_select",AsyncMock(side_effect=[rows,[]])):
            result=await goals.resolve_goal_actual(CID,"ad_spend","2026-09-01","2026-09-02")
        self.assertEqual(result["actual"],30)
        self.assertFalse(result["projection_ready"])

    async def test_short_pages_are_read_until_empty_without_truncating_actual(self):
        pages=[[{"client_id":CID,"metric_date":"2026-09-01","meta_spend":10}], [{"client_id":CID,"metric_date":"2026-09-02","meta_spend":20}], []]
        with patch.object(goals,"sb_select",AsyncMock(side_effect=pages)) as select:
            result=await goals.resolve_goal_actual(CID,"ad_spend","2026-09-01","2026-09-02")
        self.assertEqual(result["actual"],30)
        self.assertTrue(result["projection_ready"])
        self.assertEqual([call.kwargs["offset"] for call in select.await_args_list],[0,1,2])
