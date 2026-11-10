"""Mídia On → Meta Ads: rascunho, prontidão, público e publicação pausada na ordem certa."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import date
from unittest.mock import AsyncMock, patch

from services import meta_ad_publisher as pub
from services.studio_calendar import StudioError

READY = {"name": "Black Friday", "objective": "trafego", "daily_budget": 50, "start_date": "2026-11-20", "end_date": "2026-11-30",
         "audience": {"age_min": 25, "age_max": 45, "gender": "mulheres", "regions": [], "interests": ["Perfume"], "advantage": True},
         "ad": {"primary_text": "Seu perfume certo.", "headline": "Oud", "description": "", "cta": "SHOP_NOW",
                "link": "https://roove.com.br", "image_url": "https://cdn/x.jpg"}}


class PayloadTests(unittest.TestCase):
    def test_clean_and_ready(self):
        p = pub.clean_payload(READY, today=date(2026, 11, 10))
        self.assertEqual(pub.readiness(p), [])
        self.assertEqual(p["audience"]["gender"], "mulheres")

    def test_missing_items_and_limits(self):
        p = pub.clean_payload({"objective": "trafego", "daily_budget": 2, "audience": {"age_min": 10, "age_max": 99}, "ad": {"cta": "X"}},
                              today=date(2026, 11, 10))
        self.assertEqual((p["audience"]["age_min"], p["audience"]["age_max"], p["ad"]["cta"]), (18, 65, "LEARN_MORE"))
        missing = " ".join(pub.readiness(p))
        for word in ("Orçamento", "Texto principal", "Imagem", "Link"):
            self.assertIn(word, missing)
        with self.assertRaises(StudioError):
            pub.clean_payload({"objective": "magia"})

    def test_targeting(self):
        p = pub.clean_payload(READY, today=date(2026, 11, 10))
        t = pub.targeting_for(p, [{"id": "1", "name": "Perfume"}], [])
        self.assertEqual(t["geo_locations"], {"countries": ["BR"]})
        self.assertEqual(t["genders"], [2])
        self.assertEqual(t["flexible_spec"][0]["interests"][0]["id"], "1")


class PublishTests(unittest.IsolatedAsyncioTestCase):
    ROW = {"id": "d1", "client_id": "roove", "status": "rascunho", "payload": READY, "meta_ids": {}}
    CTX = {"token": "t", "act": "act_123", "page_id": "999", "ig_id": "1784"}

    async def test_creates_everything_paused_in_order(self):
        calls = []

        async def graph(method, path, *, token, data=None, params=None):
            calls.append((method, path, data or {}))
            if path == "/search":
                return {"data": [{"id": "6003", "name": "Perfume"}]}
            return {"id": f"id{len(calls)}"}
        update = AsyncMock(return_value=[{**self.ROW, "status": "publicada"}])
        with patch.object(pub, "_draft", AsyncMock(return_value=self.ROW)), patch.object(pub, "_context", AsyncMock(return_value=self.CTX)), \
             patch.object(pub, "_graph", graph), patch.object(pub, "_image_hash", AsyncMock(return_value="h1")), \
             patch.object(pub, "sb_update", update), redirect_stdout(io.StringIO()):
            await pub.publish("roove", "d1")
        posts = [(p, d) for m, p, d in calls if m == "POST"]
        self.assertEqual([p for p, _ in posts], ["/act_123/campaigns", "/act_123/adsets", "/act_123/adcreatives", "/act_123/ads"])
        self.assertTrue(all(d.get("status", "PAUSED") == "PAUSED" for _, d in posts))
        self.assertEqual(posts[0][1]["daily_budget"], "5000")  # R$ 50 em centavos
        spec = json.loads(posts[2][1]["object_story_spec"])
        self.assertEqual((spec["page_id"], spec["instagram_user_id"], spec["link_data"]["image_hash"]), ("999", "1784", "h1"))
        final = update.await_args_list[-1].kwargs["patch"]
        self.assertEqual(final["status"], "publicada")
        self.assertEqual(final["meta_ids"]["ad_account_id"], "act_123")

    async def test_failure_keeps_created_ids_and_resumes(self):
        async def graph(method, path, *, token, data=None, params=None):
            if path.endswith("/adsets"):
                raise pub.MetaAdError("AD_META_REJECTED", "Público pequeno demais")
            return {"id": "camp1"} if path.endswith("/campaigns") else {"data": []}
        update = AsyncMock(return_value=[self.ROW])
        with patch.object(pub, "_draft", AsyncMock(return_value=self.ROW)), patch.object(pub, "_context", AsyncMock(return_value=self.CTX)), \
             patch.object(pub, "_graph", graph), patch.object(pub, "sb_update", update), redirect_stdout(io.StringIO()):
            with self.assertRaises(StudioError):
                await pub.publish("roove", "d1")
        saved = update.await_args_list[-1].kwargs["patch"]
        self.assertEqual((saved["status"], saved["meta_ids"]["campaign_id"]), ("erro", "camp1"))
        self.assertIn("Público pequeno", saved["error"])

    async def test_not_ready_is_refused_before_meta(self):
        row = {**self.ROW, "payload": {**READY, "ad": {**READY["ad"], "image_url": ""}}}
        ctx = AsyncMock()
        with patch.object(pub, "_draft", AsyncMock(return_value=row)), patch.object(pub, "_context", ctx):
            with self.assertRaises(StudioError) as raised:
                await pub.publish("roove", "d1")
        self.assertEqual(raised.exception.code, "AD_NOT_READY")
        ctx.assert_not_awaited()

    async def test_connection_without_ads_permission_is_refused(self):
        resolved = {"connection_id": "c1", "row": {"ad_account_id": "act_1", "scopes_json": ["ads_read"]}}
        with patch("services.connection_resolver.resolve_connection_for_scope", AsyncMock(return_value=resolved)):
            with self.assertRaises(StudioError) as raised:
                await pub._context("roove")
        self.assertEqual(raised.exception.code, "AD_PERMISSION_MISSING")



class AudienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_remarketing_uses_visitors_and_excludes_buyers(self):
        row = {"id": "d1", "client_id": "roove", "status": "rascunho", "meta_ids": {}, "payload": {**READY, "objective": "remarketing"}}
        posts = []

        async def graph(method, path, *, token, data=None, params=None):
            if method == "GET" and path.endswith("/adspixels"):
                return {"data": [{"id": "px1"}]}
            if method == "GET" and path.endswith("/customaudiences"):
                return {"data": [{"id": "aud-buy", "name": pub.AUDIENCES["compradores_180"]["name"]}]}
            if method == "GET":
                return {"data": []}
            posts.append((path, data or {}))
            return {"id": f"id{len(posts)}"}
        with patch.object(pub, "_draft", AsyncMock(return_value=row)), patch.object(pub, "_context", AsyncMock(return_value=PublishTests.CTX)), \
             patch.object(pub, "_graph", graph), patch.object(pub, "_image_hash", AsyncMock(return_value="h")), \
             patch.object(pub, "sb_update", AsyncMock(return_value=[row])), redirect_stdout(io.StringIO()):
            await pub.publish("roove", "d1")
        audience_posts = [d for p, d in posts if p.endswith("/customaudiences")]
        self.assertEqual(len(audience_posts), 1)  # visitantes criado; compradores reaproveitado pelo nome
        rule = json.loads(audience_posts[0]["rule"])
        self.assertEqual(rule["inclusions"]["rules"][0]["retention_seconds"], 30 * 86400)
        adset = next(d for p, d in posts if p.endswith("/adsets"))
        targeting = json.loads(adset["targeting"])
        self.assertEqual(targeting["excluded_custom_audiences"], [{"id": "aud-buy"}])
        self.assertEqual(targeting["targeting_automation"], {"advantage_audience": 0})
        self.assertNotIn("flexible_spec", targeting)
        self.assertEqual(json.loads(adset["promoted_object"])["pixel_id"], "px1")

    def test_buyers_rule_filters_purchase(self):
        rule = pub.audience_rule("px", 180, "Purchase")
        self.assertEqual(rule["inclusions"]["rules"][0]["filter"]["filters"][0]["value"], "Purchase")

if __name__ == "__main__":
    unittest.main()
