import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import channel_providers as api  # noqa: E402
from services import channels  # noqa: E402
from services.integration_errors import IntegrationError  # noqa: E402


class ParseTests(unittest.TestCase):
    def test_clarity_site_and_pages(self):
        payload = [{"metricName": "Traffic", "information": [{"totalSessionCount": "120", "distinctUserCount": "90", "Url": "https://loja/a"},
                                                             {"totalSessionCount": "300", "distinctUserCount": "200", "Url": "https://loja/b"}]},
                   {"metricName": "RageClickCount", "information": [{"sessionsWithMetricPercentage": 2.5, "Url": "https://loja/b"}]}]
        pages = api.parse_clarity(payload, "2026-11-11", by_url=True)
        self.assertEqual([p["entity_id"] for p in pages], ["https://loja/b", "https://loja/a"])
        self.assertEqual(pages[0]["metrics"]["RageClickCount.sessionsWithMetricPercentage"], 2.5)
        site = api.parse_clarity([{"metricName": "Traffic", "information": [{"totalSessionCount": "420"}]}], "2026-11-11")
        self.assertEqual(site[0]["level"], "account")
        self.assertEqual(site[0]["metrics"]["totalSessionCount"], 420.0)

    def test_summary_adds_paid_and_keeps_latest_organic_snapshot(self):
        rows = [
            {"provider": "tiktok_ads", "level": "campaign", "entity_id": "c1", "entity_name": "Natal", "metric_date": "2026-11-10", "spend": 50, "impressions": 1000, "clicks": 20, "conversions": 2, "metrics": {}},
            {"provider": "tiktok_ads", "level": "campaign", "entity_id": "c1", "entity_name": "Natal", "metric_date": "2026-11-11", "spend": 30.5, "impressions": 500, "clicks": 5, "conversions": 1, "metrics": {}},
            {"provider": "tiktok", "level": "account", "entity_id": "", "metric_date": "2026-11-10", "metrics": {"followers": 900}},
            {"provider": "tiktok", "level": "account", "entity_id": "", "metric_date": "2026-11-11", "metrics": {"followers": 950}},
            {"provider": "tiktok", "level": "content", "entity_id": "v1", "entity_name": "Rótulo", "metric_date": "2026-11-11", "impressions": 4000, "metrics": {}},
        ]
        out = channels.summarize(rows)
        self.assertEqual(out["tiktok_ads"]["spend"], 80.5)
        self.assertEqual(out["tiktok_ads"]["impressions"], 1500)
        self.assertEqual(out["tiktok_ads"]["top"][0]["value"], 80.5)
        self.assertEqual(out["tiktok"]["latest"]["followers"], 950)
        self.assertEqual(out["tiktok"]["top"][0]["name"], "Rótulo")
        pin = channels.summarize([{"provider": "pinterest", "level": "account", "entity_id": "", "metric_date": d, "impressions": 10, "clicks": 1,
                                   "metrics": {"saves": 2, "engagement": 3}} for d in ("2026-11-10", "2026-11-11")])
        self.assertEqual(pin["pinterest"]["sums"], {"saves": 4, "engagement": 6})


class CollectTests(unittest.IsolatedAsyncioTestCase):
    async def test_tiktok_ads_report_becomes_campaign_rows(self):
        body = {"code": 0, "data": {"page_info": {"total_page": 1}, "list": [
            {"dimensions": {"campaign_id": "77", "stat_time_day": "2026-11-11 00:00:00"},
             "metrics": {"campaign_name": "Black Friday", "spend": "12.30", "impressions": "900", "clicks": "14", "conversion": "2", "reach": "700", "video_play_actions": "300"}}]}}
        with patch.object(api, "_json", AsyncMock(return_value=body)):
            rows = await api.collect_tiktok_ads({"access_token": "t"}, {"advertiser_ids": ["a1"]}, 7)
        self.assertEqual(rows[0]["metric_date"], "2026-11-11")
        self.assertEqual(rows[0]["spend"], 12.3)
        self.assertEqual(rows[0]["entity_name"], "Black Friday")
        self.assertEqual(rows[0]["metrics"]["video_views"], 300)

    async def test_pinterest_organic_and_ads_with_one_login(self):
        organic = {"all": {"daily_metrics": [{"date": "2026-11-11", "data_status": "READY", "metrics": {"IMPRESSION": 500, "SAVE": 9, "OUTBOUND_CLICK": 4}},
                                             {"date": "2026-11-12", "data_status": "PROCESSING", "metrics": {}}]}}
        ads = {"data": [{"DATE": "2026-11-11", "SPEND_IN_DOLLAR": 20, "IMPRESSION_1": 1000, "CLICKTHROUGH_1": 10, "TOTAL_CONVERSIONS": 1}]}
        with patch.object(api, "_json", AsyncMock(side_effect=[organic, ads])):
            rows = await api.collect_pinterest({"access_token": "t"}, {"ad_account_ids": ["9"]}, 7)
        self.assertEqual([r["provider"] for r in rows], ["pinterest", "pinterest_ads"])  # dia em processamento fica de fora
        self.assertEqual(rows[0]["metrics"]["saves"], 9)
        self.assertEqual(rows[1]["spend"], 20.0)


class SyncTests(unittest.IsolatedAsyncioTestCase):
    CONN = {"id": "k1", "client_id": "c1", "provider": "tiktok_ads", "metadata": {"advertiser_ids": ["a1"]}, "encrypted_token": "x"}

    async def test_sync_stores_rows_with_the_company_id_and_marks_success(self):
        upsert, update = AsyncMock(), AsyncMock()
        collector = AsyncMock(return_value=[{"level": "campaign", "metric_date": "2026-11-11", "account_id": "a1", "entity_id": "77", "spend": 1}])
        with patch.object(channels, "_connection", AsyncMock(return_value=self.CONN)), \
             patch.object(channels, "_token", lambda row: {"access_token": "t"}), \
             patch.dict(api.COLLECTORS, {"tiktok_ads": collector}), \
             patch.object(channels, "sb_upsert", upsert), patch.object(channels, "sb_update", update):
            out = await channels.sync("c1", "tiktok_ads")
        self.assertEqual(out, {"status": "ok", "rows": 1})
        row = upsert.await_args.args[1][0]
        self.assertEqual((row["client_id"], row["provider"]), ("c1", "tiktok_ads"))
        self.assertEqual(collector.await_args.args[2], 30)  # primeira coleta: 30 dias
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "connected")
        self.assertEqual(update.await_args.kwargs["filters"]["client_id"], "eq.c1")

    async def test_revoked_access_marks_reconnect_and_keeps_history(self):
        update = AsyncMock()
        boom = AsyncMock(side_effect=IntegrationError("recusou", status_code=401, code="CHANNEL_REAUTH_REQUIRED", provider="tiktok_ads"))
        with patch.object(channels, "_connection", AsyncMock(return_value=self.CONN)), patch.object(channels, "_token", lambda row: {}), \
             patch.dict(api.COLLECTORS, {"tiktok_ads": boom}), patch.object(channels, "sb_update", update), \
             patch.object(channels, "sb_upsert", AsyncMock()) as upsert:
            out = await channels.sync("c1", "tiktok_ads")
        self.assertEqual(out["code"], "CHANNEL_REAUTH_REQUIRED")
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "reauth_required")
        upsert.assert_not_awaited()

    async def test_recent_sync_is_skipped_unless_forced(self):
        conn = {**self.CONN, "metadata": {"last_success_at": channels._now().isoformat()}}
        with patch.object(channels, "_connection", AsyncMock(return_value=conn)):
            self.assertEqual((await channels.sync("c1", "tiktok_ads"))["status"], "recent")

    async def test_start_without_app_credentials_says_so(self):
        with patch.dict(os.environ, {"TIKTOK_ADS_APP_ID": "", "TIKTOK_ADS_APP_SECRET": ""}):
            with self.assertRaises(IntegrationError) as raised:
                await channels.start("tiktok_ads", client_id="c1", user_id="u1")
        self.assertEqual(raised.exception.code, "CHANNEL_APP_UNCONFIGURED")

    async def test_run_all_isolates_companies(self):
        rows = [{"client_id": "c1", "provider": "clarity"}, {"client_id": "c2", "provider": "pinterest"}]
        sync = AsyncMock(side_effect=[RuntimeError("boom"), {"status": "ok", "rows": 3}])
        with patch.object(channels, "sb_select", AsyncMock(return_value=rows)), patch.object(channels, "sync", sync):
            out = await channels.run_all()
        self.assertEqual(out, {"connections": 2, "error": 1, "ok": 1})

    async def test_clarity_token_is_validated_before_saving(self):
        with patch.object(api, "collect_clarity", AsyncMock(side_effect=IntegrationError("recusou", status_code=401, code="CHANNEL_REAUTH_REQUIRED", provider="clarity"))), \
             patch.object(channels, "upsert_connection", AsyncMock()) as save:
            with self.assertRaises(IntegrationError):
                await channels.connect_clarity("c1", user_id="u1", token="x" * 40, project_name="Loja")
        save.assert_not_awaited()

    def test_token_payload_round_trip(self):
        with patch.object(channels, "decrypt_secret", lambda raw: json.dumps({"access_token": "abc"})):
            self.assertEqual(channels._token({"encrypted_token": "zzz"})["access_token"], "abc")


if __name__ == "__main__":
    unittest.main()


class LinkedInTests(unittest.IsolatedAsyncioTestCase):
    async def test_ads_and_page_with_one_login(self):
        ads = {"elements": [{"costInLocalCurrency": "45.10", "impressions": 2000, "clicks": 30, "externalWebsiteConversions": 2,
                             "dateRange": {"start": {"year": 2026, "month": 11, "day": 11}}, "pivotValues": ["urn:li:sponsoredCampaign:555"]}]}
        page = {"elements": [{"timeRange": {"start": 1762819200000}, "totalShareStatistics": {"impressionCount": 800, "clickCount": 12, "likeCount": 5}}]}
        size = {"firstDegreeSize": 1234}
        calls = AsyncMock(side_effect=[ads, page, size])
        with patch.object(api, "_json", calls):
            rows = await api.collect_linkedin({"access_token": "t"}, {"ad_account_ids": ["9"], "organization_ids": ["77"]}, 7)
        self.assertEqual([r["provider"] for r in rows], ["linkedin_ads", "linkedin", "linkedin"])
        self.assertEqual((rows[0]["metric_date"], rows[0]["spend"], rows[0]["entity_id"]), ("2026-11-11", 45.1, "555"))
        self.assertIn("urn%3Ali%3AsponsoredAccount%3A9", calls.await_args_list[0].args[2])
        self.assertEqual(rows[2]["metrics"]["followers"], 1234)
        self.assertEqual(channels.summarize(rows)["linkedin"]["latest"]["followers"], 1234)
