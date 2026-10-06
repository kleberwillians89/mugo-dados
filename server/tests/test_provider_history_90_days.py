"""Contrato 90 dias com APIs, persistência e locks simulados; sem rede."""
import sys
import unittest
import io
import re
from contextlib import asynccontextmanager, redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import provider_history as history, provider_coverage as coverage
from services import ga4_sync, ga4_reporting, google_ads, ads_meta, ads_sync, meta_backfill, intelligence, ig_dashboard, ig_meta
from services.integration_errors import IntegrationError

CID = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
START, END = "2026-07-08", "2026-10-05"


def days(start=START, end=END):
    since, until = date.fromisoformat(start), date.fromisoformat(end)
    return [(since + timedelta(days=i)).isoformat() for i in range((until-since).days+1)]


@asynccontextmanager
async def lock(**kwargs):
    yield "fixture-lock"


class HistoryOperationTests(unittest.IsolatedAsyncioTestCase):
    async def execute(self, provider, sync=None, resume=False, checkpoints=None, client_id=CID):
        context = SimpleNamespace(client_id=client_id, connection_id="conn", customer_id="123", property_id="123")
        self.sync = sync or AsyncMock(return_value={"ok": True, "read_model_refreshed": True, "collection_complete": True, "rows_upserted": 7})
        self.started, self.finished = AsyncMock(return_value={"id":"job"}), AsyncMock()
        self.read = AsyncMock(return_value=checkpoints or [])
        with patch.object(history, "guarded_sync", lock), patch.object(history, "start_job_run", self.started), patch.object(history, "finish_job_run", self.finished), patch.object(history, "sb_select", self.read), patch.object(history, "resolve_google_ads_context", AsyncMock(return_value=context)), patch.object(history, "resolve_ga4_connection_context", AsyncMock(return_value=context)), patch.object(history, "get_google_access_token", AsyncMock(return_value="fixture-only")), patch.object(history, "sync_google_ads", self.sync), patch.object(history, "sync_ga4_for_period", self.sync):
            return await history.backfill_provider_history(client_id=client_id, provider=provider, start_date=START, end_date=END, resume=resume)

    async def test_google_90_days_uses_13_exact_chunks_and_one_tenant(self):
        result = await self.execute("google_ads")
        self.assertEqual(result["completed_slices"], 13)
        queried = []
        for call in self.sync.await_args_list:
            self.assertEqual(call.kwargs["client_id"], CID)
            queried.extend(days(call.kwargs["start"], call.kwargs["end"]))
        self.assertEqual(queried, days())
        self.assertTrue(all(c.kwargs["client_id"] == CID for c in self.finished.await_args_list))

    async def test_ga4_90_days_resolves_property_and_token_server_side(self):
        await self.execute("ga4")
        self.assertEqual(self.sync.await_count, 13)
        for call in self.sync.await_args_list:
            self.assertEqual(call.kwargs["property_id"], "123")
            self.assertEqual(call.kwargs["client_id"], CID)
            self.assertLessEqual(len(days(call.kwargs["since"], call.kwargs["until"])), 7)

    async def test_resume_only_skips_explicit_success_for_same_tenant_resource_and_window(self):
        result = await self.execute("ga4", resume=True, checkpoints=[{"id":"old"}])
        self.sync.assert_not_awaited()
        self.assertEqual(result["skipped_slices"], 13)
        for call in self.read.await_args_list:
            filters = call.kwargs["filters"]
            self.assertEqual(filters["client_id"], f"eq.{CID}")
            self.assertEqual(filters["payload_json->>resource_id"], "eq.123")
            self.assertEqual(filters["payload_json->>collection_complete"], "eq.true")

    async def test_partial_projection_never_creates_success_checkpoint(self):
        with self.assertRaises(RuntimeError):
            await self.execute("ga4", sync=AsyncMock(return_value={"ok":True,"read_model_refreshed":False}))
        self.assertEqual(self.finished.await_args.kwargs["status"], "error")
        self.assertEqual(self.sync.await_count, 1)

    async def test_unknown_or_partial_collection_never_creates_success_checkpoint(self):
        for complete in (None, False):
            with self.subTest(complete=complete), self.assertRaises(RuntimeError):
                await self.execute("ga4", sync=AsyncMock(return_value={"ok": True, "read_model_refreshed": True, "collection_complete": complete}))
            self.assertEqual(self.finished.await_args.kwargs["status"], "error")

    async def test_error_is_safe_and_resumable(self):
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(RuntimeError) as raised:
            await self.execute("google_ads", sync=AsyncMock(side_effect=RuntimeError("private@example.test fixture-secret")))
        self.assertNotIn("fixture-secret", out.getvalue()+str(raised.exception))
        self.assertEqual(self.finished.await_args.kwargs["status"], "error")

    async def test_foreign_connection_is_rejected_before_writing(self):
        context = SimpleNamespace(client_id=OTHER, connection_id="other", customer_id="123")
        write = AsyncMock()
        with patch.object(history,"resolve_google_ads_context",AsyncMock(return_value=context)), patch.object(history,"start_job_run",write), self.assertRaises(ValueError):
            await history.backfill_provider_history(client_id=CID,provider="google_ads",start_date=START,end_date=END)
        write.assert_not_awaited()

    async def test_meta_reuses_existing_queue_with_13_chunks_and_no_inline_sync(self):
        enqueue = AsyncMock(return_value={"backfill_job_id":"job","requested_since":START,"requested_until":END,"total_slices":13,"status":"queued"})
        with patch.object(history,"resolve_connection_for_scope",AsyncMock(return_value={"connection_id":"meta"})), patch.object(history,"enqueue_backfill",enqueue):
            result = await history.backfill_provider_history(client_id=CID,provider="meta_ads",start_date=START,end_date=END)
        self.assertTrue(result["queued"])
        self.assertEqual(enqueue.await_args.kwargs["client_id"], CID)
        self.assertIsNone(enqueue.await_args.kwargs["created_by"])
        self.assertEqual(len(meta_backfill.build_slices(START, END)), 13)

    async def test_meta_active_different_window_does_not_claim_requested_history(self):
        with patch.object(history,"resolve_connection_for_scope",AsyncMock(return_value={"connection_id":"meta"})), patch.object(history,"enqueue_backfill",AsyncMock(return_value={"requested_since":"2026-10-01","requested_until":END})), self.assertRaises(ValueError):
            await history.backfill_provider_history(client_id=CID,provider="meta_ads",start_date=START,end_date=END)

    def test_explicit_tenant_provider_and_maximum_90_are_required(self):
        for cid, provider, start, end in [("", "ga4",START,END),(CID,"shopify",START,END),(CID,"ga4","2026-07-07",END),(CID,"ga4",END,START)]:
            with self.subTest(provider=provider,cid=cid), self.assertRaises(ValueError):
                history.validate_history(cid,provider,start,end)


class DailyFactsTests(unittest.IsolatedAsyncioTestCase):
    async def test_ga4_real_ingestion_90_days_idempotent_and_short_reads(self):
        store = {}
        async def report(name, **kw):
            rows = [{"values":{"date":d.replace("-",""),"sessions":10,"engagedSessions":6,"screenPageViews":20,"eventCount":30,"keyEvents":4,"transactions":2,"purchaseRevenue":50,"activeUsers":5,"totalUsers":7}} for d in days(kw["start_date"],kw["end_date"])] if name == "daily" else []
            return {"rows":rows,"row_count":len(rows)}
        async def persist(*,table,rows,on_conflict):
            for row in rows: store[(table,row["client_id"],row["property_id"],row["stat_date"])] = row
        projection = AsyncMock(return_value={"ok":True})
        with patch.object(ga4_sync,"_run_named_report",report),patch.object(ga4_sync,"_upsert_with_compatibility",persist),patch.object(ga4_sync,"refresh_dashboard_read_model_safely",projection):
            for _ in range(2):
                result = await ga4_sync._sync_ga4_for_period(client_id=CID,property_id="123",since=START,until=END,access_token="fixture-only",record_job_run=False)
        self.assertEqual(len(store),90)
        self.assertTrue(result["read_model_refreshed"])
        self.assertEqual(projection.await_count,2)
        for length in (7,30,90):
            period = ga4_reporting.resolve_ga4_report_period(start=days()[-length],end=END)
            rows = ga4_reporting._build_daily_rows(period,list(store.values()))
            summary = ga4_reporting._build_summary(rows)
            self.assertEqual(summary["sessions"],10*length)
            self.assertEqual(summary["purchases"],2*length)
            self.assertEqual(summary["purchase_revenue"],50*length)
            self.assertEqual(summary["engaged_sessions"],6*length)
            self.assertEqual(summary["screen_page_views"],20*length)
            self.assertEqual(summary["key_events"],4*length)
            self.assertEqual(summary["user_count_semantics"],"sum_of_daily_users")

    async def test_ga4_failed_projection_is_not_success_even_with_persisted_facts(self):
        with patch.object(ga4_sync,"_run_named_report",AsyncMock(return_value={"rows":[],"row_count":0})),patch.object(ga4_sync,"refresh_dashboard_read_model_safely",AsyncMock(return_value={"ok":False})),self.assertRaises(IntegrationError) as raised:
            await ga4_sync._sync_ga4_for_period(client_id=CID,property_id="123",since=START,until=END,record_job_run=False)
        self.assertEqual(raised.exception.code,"GA4_PROJECTION_FAILED")

    async def test_google_real_ingestion_90_days_includes_removed_idempotent(self):
        context = google_ads.GoogleAdsContext(CID,"conn","123",None)
        store, queries = {}, []
        async def persist(table,rows,on_conflict):
            self.assertEqual(on_conflict,"client_id,connection_id,customer_id,campaign_id,stat_date")
            for row in rows: store[(row["client_id"],row["campaign_id"],row["stat_date"])] = row
        http = MagicMock()
        async def post(url,*,headers,json):
            queries.append(json["query"])
            since,until = re.findall(r"'([0-9-]+)'",json["query"])
            rows = [{"segments":{"date":d},"campaign":{"id":"removed","status":"REMOVED","name":"fixture"},"metrics":{"costMicros":"10000000","conversions":2,"conversionsValue":30}} for d in days(since,until)]
            return MagicMock(status_code=200,json=lambda:[{"results":rows[:45]},{"results":rows[45:]}])
        http.post=post;http.__aenter__=AsyncMock(return_value=http);http.__aexit__=AsyncMock(return_value=None)
        with patch.object(google_ads,"resolve_google_ads_context",AsyncMock(return_value=context)),patch.object(google_ads.os,"getenv",side_effect=lambda key:{"GOOGLE_ADS_DEVELOPER_TOKEN":"fixture","GOOGLE_ADS_API_VERSION":"v25"}.get(key)),patch.object(google_ads,"get_google_access_token",AsyncMock(return_value="fixture")),patch.object(google_ads.httpx,"AsyncClient",return_value=http),patch.object(google_ads,"sb_upsert",persist),patch.object(google_ads,"refresh_dashboard_read_model_safely",AsyncMock(return_value={"ok":True})):
            for _ in range(2):
                await google_ads._sync_google_ads(client_id=CID,connection_id="conn",start=START,end=END,days=90)
        self.assertEqual(len(store),90)
        self.assertFalse(any("campaign.status" in query for query in queries))
        for length in (7,30,90):
            selected=[r for r in store.values() if r["stat_date"] >= days()[-length]]
            self.assertEqual(sum(r["cost"] for r in selected),10*length)
            self.assertEqual(sum(r["conversion_value"] for r in selected),30*length)
        self.assertEqual({r["client_id"] for r in store.values()},{CID})

    async def test_meta_paginated_90_daily_facts_removed_reexecution_and_subsets(self):
        raw=[{"date_start":d,"campaign_id":"removed","campaign_status":"REMOVED","spend":"10","impressions":"100","reach":"50","frequency":"2","clicks":"5","actions":[{"action_type":"purchase","value":"2"}],"action_values":[{"action_type":"purchase","value":"30"}]} for d in days()]
        pages=[{"data":raw[:45],"paging":{"next":"https://graph.example/page2"}},{"data":raw[45:]}]
        store={}
        async def persist(table,rows,on_conflict):
            for row in rows:store[(row["client_id"],row["ad_account_id"],row["stat_date"])]=row
        for _ in range(2):
            with patch.object(ads_meta,"_meta_get",AsyncMock(side_effect=pages)) as get:
                fetched=await ads_meta.fetch_ad_account_insights(ad_account_id="123",access_token="fixture",since=START,until=END)
            self.assertNotIn("filtering",get.await_args_list[0].kwargs["params"])
            rows=ads_sync._to_upsert_ready_ad_account_rows(client_id=CID,connection_id="conn",meta_connection_id="conn",ad_account_id="act_123",ad_account_name="fixture",since=START,raw_rows=fetched)
            with patch.object(ads_sync,"sb_upsert",persist):
                await ads_sync._upsert_ad_account_daily_stats(rows)
        self.assertEqual(len(store),90)
        self.assertEqual(store[(CID,"act_123",START)]["raw_json"][0]["frequency"],"2")
        self.assertEqual(sum(r["revenue"] for r in store.values()),2700)
        self.assertEqual(sum(r["conversions"] for r in store.values()),180)
        for length in (7,30,90):
            self.assertEqual(sum(r["spend"] for r in store.values() if r["stat_date"]>=days()[-length]),10*length)


class IntelligenceWindowTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_7_30_90_and_custom_bound_real_queries_and_model_context(self):
        rows=[{"metric_date":d,"client_id":CID,"meta_spend":10,"ga4_sessions":5,"ga4_users":3,"shopify_net_revenue":30,"shopify_orders":2} for d in days("2026-04-01",END)]
        async def query(table,**kw):
            self.assertEqual(kw["client_id"],CID)
            return [r for r in rows if kw["start"].isoformat()<=r["metric_date"]<=kw["end"].isoformat()]
        for length,end in [(7,END),(30,END),(90,END),(12,"2026-08-19")]:
            until=date.fromisoformat(end);since=until-timedelta(days=length-1);previous_end=since-timedelta(days=1);previous_start=previous_end-timedelta(days=length-1)
            with patch.object(intelligence,"_query_period",query),patch.object(intelligence,"sb_select",AsyncMock(return_value=[])),patch.object(intelligence,"_query_timestamp_period",AsyncMock(return_value=[])) as media:
                result=await intelligence._read_model_executive_context(CID,since,until,previous_start,previous_end)
            self.assertEqual(result["meta"]["spend"],10*length)
            self.assertEqual(result["previous_period"]["meta"]["spend"],10*length)
            self.assertEqual(result["deltas"]["meta_spend"]["absolute"],0)
            self.assertIsNone(result["ga4"]["users"])
            self.assertEqual(media.await_args.kwargs["start"],since)
            self.assertEqual(media.await_args.kwargs["end"],until)
            self.assertEqual(result["meta"]["coverage"]["distinct_dates"],length)
            self.assertEqual(result["meta"]["coverage"]["completeness"],"unknown")

    async def test_partial_provider_does_not_claim_90_complete_dates(self):
        with patch.object(intelligence,"_query_period",AsyncMock(return_value=[{"metric_date":END,"meta_spend":10}])),patch.object(intelligence,"sb_select",AsyncMock(return_value=[])),patch.object(intelligence,"_query_timestamp_period",AsyncMock(return_value=[])):
            result=await intelligence._read_model_executive_context(CID,date.fromisoformat(START),date.fromisoformat(END),date(2026,4,9),date(2026,7,7))
        self.assertTrue(result["meta"]["coverage"]["is_partial"])
        self.assertEqual(result["meta"]["coverage"]["distinct_dates"],1)
        self.assertEqual(result["meta"]["coverage"]["completeness"],"unknown")


class CoverageTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, certified):
        async def read(table,**kw):
            self.assertEqual(kw["filters"]["client_id"],f"eq.{CID}")
            if table=="ga4_daily_stats":return [{"stat_date":d,"updated_at":"2026-10-05T15:00:00Z"} for d in days()]
            if table=="cron_job_runs":return [{"finished_at":"2026-10-05T15:01:00Z","payload_json":{"start_date":START,"end_date":END}}] if certified else []
            return [{"last_success_at":"2026-10-05T15:01:00Z"}]
        with patch.object(coverage,"resolve_ga4_connection_context",AsyncMock(return_value=SimpleNamespace(client_id=CID,connection_id="conn",property_id="123"))),patch.object(coverage,"sb_select",read):
            return await coverage.provider_coverage(client_id=CID,provider="ga4",start_date=START,end_date=END)

    async def test_90_dates_alone_do_not_certify_completeness(self):
        result=await self.collect(False)
        self.assertEqual(result["distinct_dates"],90)
        self.assertEqual(result["completeness"],"unknown")
        self.assertIsNone(result["last_sync_at"])

    async def test_successful_collection_checkpoints_certify_requested_window(self):
        result=await self.collect(True)
        self.assertEqual(result["completeness"],"complete")
        self.assertEqual(result["status"],"suficiente para 90 dias")


class InstagramHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_content_only_history_is_tenant_scoped_idempotent_and_preserves_insights(self):
        store={"existing":{"insights_json":{"reach":42}}}
        async def persist(table,rows,on_conflict):
            self.assertEqual(table,"ig_media")
            self.assertEqual(on_conflict,"client_id,media_id")
            for row in rows:
                self.assertEqual(row["client_id"],CID)
                self.assertNotIn("insights_json",row)
                store.setdefault(row["media_id"],{}).update(row)
        media=[{"id":"existing","timestamp":"2026-07-08T12:00:00+00:00","media_type":"IMAGE"},
               {"id":"reel","timestamp":"2026-08-10T12:00:00+00:00","media_product_type":"REELS"},
               {"id":"old","timestamp":"2026-01-01T12:00:00+00:00"},
               {"id":"story","timestamp":"2026-08-10T12:00:00+00:00","media_product_type":"STORY"}]
        context={"connection_id":"conn","row":{"ig_user_id":"ig"}}
        with patch.object(history,"guarded_sync",lock),patch.object(history,"ensure_valid_meta_token",AsyncMock(return_value="fixture")),patch.object(history,"fetch_media_list",AsyncMock(return_value=media)),patch.object(history,"sb_upsert",persist):
            for _ in range(2):result=await history._instagram_content(CID,context,START,END)
        self.assertEqual(len(store),2)
        self.assertEqual(store["existing"]["insights_json"]["reach"],42)
        self.assertFalse(result["snapshot_backfill"])
        self.assertEqual(result["completeness"],"unknown")

    async def test_failed_content_pagination_does_not_persist_truncated_history(self):
        persist=AsyncMock()
        with patch.object(history,"guarded_sync",lock),patch.object(history,"ensure_valid_meta_token",AsyncMock(return_value="fixture")),patch.object(history,"fetch_media_list",AsyncMock(side_effect=IntegrationError("incomplete",code="IG_MEDIA_HISTORY_INCOMPLETE",provider="instagram",status_code=502))),patch.object(history,"sb_upsert",persist),self.assertRaises(IntegrationError):
            await history._instagram_content(CID,{"connection_id":"conn","row":{"ig_user_id":"ig"}},START,END)
        persist.assert_not_awaited()

    async def test_lifetime_media_does_not_generate_historical_profile_snapshots(self):
        with patch.object(ig_dashboard,"_query_snapshot_rows",AsyncMock(return_value=[])),patch.object(ig_dashboard,"sb_select",AsyncMock(return_value=[{"timestamp":"2026-08-10T12:00:00Z","insights_json":{"reach":1000,"views":2000}}])):
            result=await ig_dashboard.get_dashboard(client_id=CID,start=START,end=END,resolved_connection={"connection_id":"conn","row":{}})
        self.assertEqual(result["daily"],[])
        self.assertFalse(result["data_available"])
        self.assertEqual(result["coverage"]["covered_days"],0)

    async def test_repeated_instagram_history_page_fails_without_exposing_url_token(self):
        next_url=ig_meta.META_BASE+"/ig/media?after=x&access_token=fixture-private"
        http=MagicMock();http.__aenter__=AsyncMock(return_value=http);http.__aexit__=AsyncMock(return_value=None)
        http.get=AsyncMock(return_value=MagicMock(status_code=200,json=lambda:{"data":[{"id":"2"}],"paging":{"next":next_url}}))
        with patch.object(ig_meta,"meta_get_json",AsyncMock(return_value={"data":[{"id":"1"}],"paging":{"next":next_url}})),patch.object(ig_meta.httpx,"AsyncClient",return_value=http),self.assertRaises(IntegrationError) as raised:
            await ig_meta.fetch_media_list("ig","fixture",history=True)
        self.assertEqual(raised.exception.code,"IG_MEDIA_HISTORY_INCOMPLETE")
        self.assertNotIn("fixture-private",str(raised.exception))
        self.assertEqual(http.get.await_count,1)


class Ga4PaginationTests(unittest.IsolatedAsyncioTestCase):
    async def run_report(self,pages):
        from services import ga4_client
        http=MagicMock();http.__aenter__=AsyncMock(return_value=http);http.__aexit__=AsyncMock(return_value=None)
        responses=[MagicMock(status_code=200,json=lambda value=page:value) for page in pages]
        http.post=AsyncMock(side_effect=responses)
        with patch.object(ga4_client.httpx,"AsyncClient",return_value=http):
            result=await ga4_client.run_ga4_report(property_id="123",access_token="fixture",start_date=START,end_date=END,dimensions=("date",),metrics=("sessions",),page_size=2)
        return result,http.post

    def page(self,day,count=3):
        return {"rowCount":count,"dimensionHeaders":[{"name":"date"}],"metricHeaders":[{"name":"sessions"}],"rows":[{"dimensionValues":[{"value":day}],"metricValues":[{"value":"10"}]}] if day else []}

    async def test_short_nonterminal_page_continues_until_row_count(self):
        result,post=await self.run_report([self.page("20260708"),self.page("20260709"),self.page("20260710")])
        self.assertEqual(len(result["rows"]),3)
        self.assertEqual([c.kwargs["json"]["offset"] for c in post.await_args_list],["0","1","2"])

    async def test_empty_page_before_row_count_rejects_incomplete_dataset(self):
        with self.assertRaises(IntegrationError) as raised:
            await self.run_report([self.page("20260708"),self.page(None)])
        self.assertEqual(raised.exception.code,"GA4_PAGINATION_INCOMPLETE")

    async def test_sampling_thresholds_and_truncation_do_not_certify_complete_collection(self):
        signals = ({"samplingMetadatas": [{"samplesReadCount": "1"}]},
                   {"subjectToThresholding": True}, {"dataLossFromOtherRow": True},
                   {"dataTruncationReasons": [{"dataTruncationType": "DATA_TRUNCATION_TYPE_PROPERTY"}]},
                   {"schemaRestrictionResponse": {"activeMetricRestrictions": [{"metricName": "purchaseRevenue"}]}})
        for metadata in signals:
            with self.subTest(metadata=metadata):
                first = self.page("20260708", count=2)
                first["metadata"] = metadata
                result, _ = await self.run_report([first, self.page("20260709", count=2)])
                self.assertFalse(result["collection_complete"])
        result, _ = await self.run_report([self.page("20260708", count=1)])
        self.assertTrue(result["collection_complete"])


class HistoryFailureTests(unittest.IsolatedAsyncioTestCase):
    execute = HistoryOperationTests.execute
    async def test_slice_timeout_is_error_not_success(self):
        import asyncio
        async def slow(**kwargs):await asyncio.sleep(.05)
        with patch.object(history,"SLICE_TIMEOUT_SECONDS",.005),self.assertRaises(RuntimeError):
            await self.execute("ga4",sync=AsyncMock(side_effect=slow))
        self.assertEqual(self.finished.await_args.kwargs["status"],"error")


class AdditionalHistoryContracts(unittest.IsolatedAsyncioTestCase):
    async def test_removed_meta_campaign_facts_survive_persistence_and_reexecution(self):
        raw=[{"campaign_id":"removed","campaign_status":"REMOVED","date_start":d,"spend":"10"} for d in days()]
        store={}
        async def upsert(table,rows,on_conflict):
            self.assertEqual(table,"campaign_daily_stats")
            for row in rows:store[(row["client_id"],row["campaign_id"],row["stat_date"])]=row
        for _ in range(2):
            rows=ads_sync._to_upsert_ready_campaign_rows(client_id=CID,connection_id="conn",ad_account_id="act_123",ad_account_name="fixture",since=START,raw_rows=raw)
            with patch.object(ads_sync,"sb_upsert",upsert):await ads_sync._upsert_campaign_daily_stats(rows)
        self.assertEqual(len(store),90)
        self.assertEqual({r["campaign_status"] for r in store.values()},{"REMOVED"})
        self.assertEqual(sum(r["spend"] for r in store.values()),900)

    async def test_missing_previous_period_never_becomes_zero_comparison(self):
        with patch.object(intelligence,"_query_period",AsyncMock(return_value=[{"metric_date":END,"meta_spend":10}])),patch.object(intelligence,"sb_select",AsyncMock(return_value=[])),patch.object(intelligence,"_query_timestamp_period",AsyncMock(return_value=[])):
            result=await intelligence._read_model_executive_context(CID,date.fromisoformat(START),date.fromisoformat(END),date(2026,4,9),date(2026,7,7))
        self.assertIsNone(result["previous_period"]["meta"]["spend"])
        self.assertIsNone(result["deltas"]["meta_spend"]["absolute"])
        self.assertIsNone(result["google_ads"]["spend"])

    async def test_comparison_and_selected_history_cross_calendar_year(self):
        rows=[{"metric_date":d,"meta_spend":10} for d in days("2026-10-24","2027-01-21")]
        with patch.object(intelligence,"_query_period",AsyncMock(return_value=rows)),patch.object(intelligence,"sb_select",AsyncMock(return_value=[])),patch.object(intelligence,"_query_timestamp_period",AsyncMock(return_value=[])):
            result=await intelligence._read_model_executive_context(CID,date(2026,10,24),date(2027,1,21),date(2026,7,26),date(2026,10,23))
        self.assertEqual(result["meta"]["spend"],900)
        self.assertEqual([r["month"] for r in result["historical_context"]["monthly_summary"]],["2026-10","2026-11","2026-12","2027-01"])

    async def test_concurrent_backfill_respects_existing_database_lock(self):
        from services import sync_locks
        context=SimpleNamespace(client_id=CID,connection_id="conn",property_id="123")
        sync=AsyncMock()
        with patch.object(history,"resolve_ga4_connection_context",AsyncMock(return_value=context)),patch.object(history,"sync_ga4_for_period",sync),patch.object(sync_locks,"acquire_sync_lock",AsyncMock(return_value=False)),self.assertRaises(IntegrationError) as raised:
            await history.backfill_provider_history(client_id=CID,provider="ga4",start_date=START,end_date=END)
        self.assertEqual(raised.exception.code,"SYNC_ALREADY_RUNNING")
        sync.assert_not_awaited()


class HistoryReadPaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_monthly_publications_read_all_persisted_pages_with_tenant_filters(self):
        from services import media
        pages=[[{"timestamp":"2026-08-01T12:00:00Z"}]*1000,[{"timestamp":"2026-08-02T12:00:00Z"}]]
        read=AsyncMock(side_effect=pages)
        with patch.object(media,"sb_select",read):
            rows=await media._read_monthly_pages("ig_media",select="timestamp",filters={"client_id":f"eq.{CID}"},order="timestamp.asc",limit=10000)
        self.assertEqual(len(rows),1001)
        self.assertEqual([c.kwargs["offset"] for c in read.await_args_list],[0,1000])
        self.assertTrue(all(c.kwargs["filters"]["client_id"]==f"eq.{CID}" for c in read.await_args_list))

    async def test_ga4_read_model_pagination_does_not_drop_rows_after_one_thousand(self):
        read=AsyncMock(side_effect=[[{"stat_date":START}]*1000,[{"stat_date":END}]])
        with patch.object(ga4_reporting,"sb_select",read):
            rows=await ga4_reporting._select_ga4_event_rows(client_id=CID,property_id="123",period=ga4_reporting.resolve_ga4_report_period(start=START,end=END))
        self.assertEqual(len(rows),1001)
        self.assertEqual([c.kwargs["offset"] for c in read.await_args_list],[0,1000])
        self.assertTrue(all(c.kwargs["filters"]["property_id"]=="eq.123" for c in read.await_args_list))
