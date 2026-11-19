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


CARDS = [{"image_url": f"https://cdn/{n}.jpg", "headline": f"Peça {n}"} for n in range(1, 5)]


class MultiCreativeTests(unittest.IsolatedAsyncioTestCase):
    def _row(self, fmt, ids=None):
        return {"id": "d2", "client_id": "roove", "status": "rascunho", "meta_ids": ids or {},
                "payload": {**READY, "ad": {**READY["ad"], "image_url": "", "format": fmt, "cards": CARDS}}}

    def test_cards_are_cleaned_and_required(self):
        p = pub.clean_payload({**READY, "ad": {**READY["ad"], "format": "carousel",
                                               "cards": [{"image_url": "http://x"}, CARDS[0], CARDS[0]] + CARDS * 4}}, today=date(2026, 11, 10))
        self.assertEqual(len(p["ad"]["cards"]), 4)  # sem http, sem repetidos
        one = pub.clean_payload({**READY, "ad": {**READY["ad"], "format": "multi", "cards": CARDS[:1]}}, today=date(2026, 11, 10))
        self.assertIn("Pelo menos 2 imagens", " ".join(pub.readiness(one)))
        self.assertEqual(pub.clean_payload({**READY, "ad": {**READY["ad"], "format": "x"}}, today=date(2026, 11, 10))["ad"]["format"], "single")

    async def _publish(self, row):
        calls = []

        async def graph(method, path, *, token, data=None, params=None):
            calls.append((method, path, data or {}))
            if path == "/search":
                return {"data": [{"id": "6003", "name": "Perfume"}]}
            return {"id": f"id{len(calls)}"}
        hashes = AsyncMock(side_effect=lambda act, url, token: "h-" + url.rsplit("/", 1)[-1])
        update = AsyncMock(return_value=[{**row, "status": "publicada"}])
        with patch.object(pub, "_draft", AsyncMock(return_value=row)), patch.object(pub, "_context", AsyncMock(return_value=PublishTests.CTX)), \
             patch.object(pub, "_graph", graph), patch.object(pub, "_image_hash", hashes), \
             patch.object(pub, "sb_update", update), redirect_stdout(io.StringIO()):
            await pub.publish("roove", "d2")
        return [(p, d) for m, p, d in calls if m == "POST"], update.await_args_list[-1].kwargs["patch"]

    async def test_carousel_is_one_ad_with_cards_in_order(self):
        posts, final = await self._publish(self._row("carousel"))
        self.assertEqual([p for p, _ in posts][-2:], ["/act_123/adcreatives", "/act_123/ads"])
        children = json.loads(posts[-2][1]["object_story_spec"])["link_data"]["child_attachments"]
        self.assertEqual([c["image_hash"] for c in children], ["h-1.jpg", "h-2.jpg", "h-3.jpg", "h-4.jpg"])
        self.assertEqual(children[1]["name"], "Peça 2")
        self.assertEqual(final["status"], "publicada")

    async def test_multi_makes_one_paused_ad_per_image_and_resumes(self):
        posts, final = await self._publish(self._row("multi"))
        self.assertEqual(sum(p.endswith("/ads") for p, _ in posts), 4)
        self.assertTrue(all(d["status"] == "PAUSED" for p, d in posts if p.endswith("/ads")))
        self.assertEqual(len(final["meta_ids"]["ad_ids"]), 4)
        # retomada: 2 já criados → só cria os outros 2
        done = {"campaign_id": "c", "adset_id": "s", "creative_ids": ["k1", "k2"], "ad_ids": ["a1", "a2"]}
        posts, final = await self._publish(self._row("multi", done))
        self.assertEqual(sum(p.endswith("/ads") for p, _ in posts), 2)
        self.assertEqual(final["meta_ids"]["ad_ids"][:2], ["a1", "a2"])


class SameCampaignTests(unittest.IsolatedAsyncioTestCase):
    PUBLISHED = {"id": "d1", "client_id": "roove", "status": "publicada", "payload": READY, "month": "2026-11",
                 "meta_ids": {"ad_account_id": "act_123", "campaign_id": "c9", "adset_id": "s9", "creative_id": "k9", "ad_id": "a9"}}

    async def test_new_ad_reuses_campaign_and_adset_only(self):
        insert = AsyncMock(side_effect=lambda table, row: {**row, "id": "d3"})
        with patch.object(pub, "_draft", AsyncMock(return_value=self.PUBLISHED)), patch.object(pub, "sb_insert", insert):
            view = await pub.duplicate_draft("roove", "d1", "u1", into_campaign=True)
        ids = insert.await_args.args[1]["meta_ids"]
        self.assertEqual((ids["campaign_id"], ids["adset_id"], ids.get("ad_id"), ids.get("creative_id")), ("c9", "s9", None, None))
        self.assertTrue(view["joined"])
        self.assertIn("novo anúncio", view["payload"]["name"])

    async def test_new_ad_needs_a_published_campaign(self):
        with patch.object(pub, "_draft", AsyncMock(return_value={**self.PUBLISHED, "status": "rascunho", "meta_ids": {}})):
            with self.assertRaises(StudioError) as caught:
                await pub.duplicate_draft("roove", "d1", "u1", into_campaign=True)
        self.assertEqual(caught.exception.code, "AD_NOT_PUBLISHED_YET")

    async def test_publish_joined_creates_only_creative_and_ad(self):
        row = {"id": "d3", "client_id": "roove", "status": "rascunho", "payload": READY,
               "meta_ids": {"ad_account_id": "act_123", "campaign_id": "c9", "adset_id": "s9", "joined": True}}
        calls = []

        async def graph(method, path, *, token, data=None, params=None):
            calls.append((method, path, data or {}))
            return {"id": f"id{len(calls)}"}
        with patch.object(pub, "_draft", AsyncMock(return_value=row)), patch.object(pub, "_context", AsyncMock(return_value=PublishTests.CTX)), \
             patch.object(pub, "_graph", graph), patch.object(pub, "_image_hash", AsyncMock(return_value="h")), \
             patch.object(pub, "sb_update", AsyncMock(return_value=[row])), redirect_stdout(io.StringIO()):
            await pub.publish("roove", "d3")
        posts = [(p, d) for m, p, d in calls if m == "POST"]
        self.assertEqual([p for p, _ in posts], ["/act_123/adcreatives", "/act_123/ads"])
        self.assertEqual(posts[1][1]["adset_id"], "s9")
        moved = {**row, "meta_ids": {**row["meta_ids"], "ad_account_id": "act_999"}}
        with patch.object(pub, "_draft", AsyncMock(return_value=moved)), patch.object(pub, "_context", AsyncMock(return_value=PublishTests.CTX)):
            with self.assertRaises(StudioError):
                await pub.publish("roove", "d3")


class AdsWithOwnFormatTests(unittest.IsolatedAsyncioTestCase):
    async def test_carousel_plus_single_image_ad_in_same_adset(self):
        ad = {**READY["ad"], "image_url": "", "format": "carousel", "cards": CARDS[:3],
              "extra_ads": [{"format": "single", "image_url": "https://cdn/solo.jpg"}, {"format": "carousel", "cards": CARDS[:1]}]}
        p = pub.clean_payload({**READY, "ad": ad}, today=date(2026, 11, 10))
        self.assertEqual(pub.readiness(p), ["Anúncio 3: pelo menos 2 imagens no carrossel"])
        ad["extra_ads"] = ad["extra_ads"][:1]
        row = {"id": "d4", "client_id": "roove", "status": "rascunho", "meta_ids": {}, "payload": {**READY, "ad": ad}}
        posts, final = await MultiCreativeTests._publish(self, row)
        creatives = [json.loads(d["object_story_spec"]) for p_, d in posts if p_.endswith("/adcreatives")]
        self.assertEqual(len(creatives[0]["link_data"]["child_attachments"]), 3)
        self.assertEqual(creatives[1]["link_data"]["image_hash"], "h-solo.jpg")
        ads = [d for p_, d in posts if p_.endswith("/ads")]
        self.assertEqual([d["name"] for d in ads], ["Black Friday · anúncio 1", "Black Friday · anúncio 2"])
        self.assertEqual(len(final["meta_ids"]["ad_ids"]), 2)


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    ROW = {"id": "d1", "client_id": "roove", "status": "publicada", "payload": READY,
           "meta_ids": {"ad_account_id": "act_123", "campaign_id": "c9", "adset_id": "s9", "ad_id": "a1", "ad_ids": ["a1", "a2"]}}
    ACCOUNT = {"token": "t", "act": "act_123"}

    async def _run(self, row, **kw):
        calls = []

        async def graph(method, path, *, token, data=None, params=None):
            calls.append((method, path, data or params or {}))
            if method == "GET" and path.endswith("/insights"):
                return {"data": [{"spend": "42.5", "impressions": "1000", "reach": "800", "clicks": "50", "inline_link_clicks": "30",
                                  "actions": [{"action_type": "link_click", "value": "30"}, {"action_type": "offsite_conversion.fb_pixel_lead", "value": "5"}]}]}
            return {"id": path.strip("/"), "status": "ACTIVE", "effective_status": "ACTIVE", "account_id": "123"}
        update = AsyncMock(return_value=[row])
        with patch.object(pub, "_draft", AsyncMock(return_value=row)), patch.object(pub, "_ad_account", AsyncMock(return_value=self.ACCOUNT)), \
             patch.object(pub, "_graph", graph), patch.object(pub, "sb_update", update), redirect_stdout(io.StringIO()):
            out = await (pub.live_results("roove", "d1") if kw.pop("results", False) else pub.set_delivery("roove", "d1", **kw))
        return out, [(m, p, d) for m, p, d in calls if m == "POST"], update

    async def test_activate_needs_budget_confirmation(self):
        with self.assertRaises(StudioError) as caught:
            await self._run(self.ROW, active=True, user_name="K", confirm_daily_budget=500)
        self.assertEqual(caught.exception.code, "AD_CONFIRM_BUDGET")

    async def test_activate_turns_on_ads_then_adset_then_campaign(self):
        out, posts, update = await self._run(self.ROW, active=True, user_name="Kleber", confirm_daily_budget=50)
        self.assertEqual([p for _, p, _ in posts], ["/a1", "/a2", "/s9", "/c9"])
        self.assertTrue(all(d == {"status": "ACTIVE"} for _, _, d in posts))
        self.assertEqual(update.await_args.kwargs["patch"]["meta_ids"]["delivery"]["state"], "ativa")
        self.assertIn("ad_2", out["objects"])

    async def test_pause_stops_campaign_only(self):
        _, posts, _ = await self._run(self.ROW, active=False, user_name="K")
        self.assertEqual(posts, [("POST", "/c9", {"status": "PAUSED"})])

    async def test_joined_ad_toggles_only_its_ads(self):
        row = {**self.ROW, "meta_ids": {**self.ROW["meta_ids"], "joined": True, "ad_ids": ["a7"], "ad_id": "a7"}}
        _, posts, _ = await self._run(row, active=True, user_name="K")
        self.assertEqual([p for _, p, _ in posts], ["/a7"])

    async def test_results_count_leads_and_cost(self):
        r, _, _ = await self._run({**self.ROW, "payload": {**READY, "objective": "leads"}}, results=True)
        self.assertEqual((r["spend"], r["results"], r["result_label"], r["cost_per_result"], r["ctr"]), (42.5, 5, "Cadastros", 8.5, 5.0))


class PixelAndVideoFixTests(unittest.IsolatedAsyncioTestCase):
    def test_uses_dataset_receiving_events_not_the_first(self):
        pixels = [{"id": "1", "name": "https://roove.com.br"}, {"id": "2", "name": "Roove Web Official", "last_fired_time": "2026-11-19T12:00:00+0000"},
                  {"id": "3", "name": "Antigo", "last_fired_time": "2025-01-01T00:00:00+0000"}, {"id": "4", "is_unavailable": True, "last_fired_time": "2026-12-01"}]
        self.assertEqual(pub.best_pixel(pixels)["id"], "2")
        self.assertEqual(pub.best_pixel([{"id": "9"}])["id"], "9")
        self.assertIsNone(pub.best_pixel([]))

    async def test_removing_failed_ad_finishes_and_keeps_created_ones(self):
        ad = {**READY["ad"], "image_url": "https://cdn/1.jpg", "extra_ads": [{"format": "single", "image_url": "https://cdn/2.jpg"}]}
        # já criados pelo código anterior (por posição): anúncios 1 e 2; o 3 (vídeo) falhou e foi tirado
        ids = {"campaign_id": "c", "adset_id": "s", "creative_ids": ["k1", "k2"], "ad_ids": ["a1", "a2"], "creative_id": "k1", "ad_id": "a1"}
        row = {"id": "d5", "client_id": "roove", "status": "erro", "meta_ids": ids, "payload": {**READY, "ad": ad}}
        posts, final = await MultiCreativeTests._publish(self, row)
        self.assertEqual(posts, [])
        self.assertEqual((final["status"], final["meta_ids"]["ad_ids"]), ("publicada", ["a1", "a2"]))

    async def test_video_error_names_the_ad(self):
        ad = {**READY["ad"], "image_url": "https://cdn/1.jpg",
              "extra_ads": [{"format": "single", "media_type": "video", "video_url": "https://ig/v.mp4", "image_url": "https://ig/capa.jpg"}]}
        row = {"id": "d6", "client_id": "roove", "status": "rascunho", "meta_ids": {"campaign_id": "c", "adset_id": "s"}, "payload": {**READY, "ad": ad}}

        async def graph(method, path, *, token, data=None, params=None):
            if path.endswith("/advideos"):
                raise pub.MetaAdError("AD_META_REJECTED", "Não foi possível buscar o arquivo de vídeo da URL.")
            return {"id": "x"}

        class Down:
            def __init__(self, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url): return type("R", (), {"status_code": 403, "content": b""})()
        with patch.object(pub, "_draft", AsyncMock(return_value=row)), patch.object(pub, "_context", AsyncMock(return_value=PublishTests.CTX)), \
             patch.object(pub, "_graph", graph), patch.object(pub, "_image_hash", AsyncMock(return_value="h")), \
             patch.object(pub.httpx, "AsyncClient", Down), patch.object(pub, "sb_update", AsyncMock(return_value=[row])), redirect_stdout(io.StringIO()):
            with self.assertRaises(StudioError) as caught:
                await pub.publish("roove", "d6")
        self.assertIn("Anúncio 2:", str(caught.exception))
        self.assertIn("link do Instagram", str(caught.exception))
