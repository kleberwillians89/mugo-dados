"""Criador igual ao Gerenciador: Campanha → Conjunto → Anúncio, com os campos e nomes da Meta."""
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
from services import meta_ads_options as options
from services import meta_structure as ms
from services.studio_calendar import StudioError

TODAY = date(2026, 11, 10)
BASE = {"name": "Black Ruah", "objective": "trafego", "daily_budget": 50, "start_date": "2026-11-20", "end_date": "2026-11-29",
        "audience": {"age_min": 25, "age_max": 45, "gender": "todos", "regions": [], "interests": [], "advantage": True},
        "ad": {"primary_text": "Perfume certo.", "headline": "Oud", "description": "", "cta": "SHOP_NOW",
               "link": "https://ruah.com.br", "image_url": "https://cdn/x.jpg"}}
CTX = {"token": "t", "act": "act_123", "page_id": "999", "ig_id": "1784"}


def with_meta(**meta):
    return {**BASE, "meta": {"objective": "OUTCOME_SALES", "conversion_location": "WEBSITE",
                             "performance_goal": "OFFSITE_CONVERSIONS", "budget": 50, **meta}}


class CatalogTests(unittest.TestCase):
    def test_six_official_objectives_in_meta_order(self):
        labels = [o["label"] for o in ms.catalog()["objectives"]]
        self.assertEqual(labels, ["Reconhecimento", "Tráfego", "Engajamento", "Cadastros", "Promoção do app", "Vendas"])

    def test_every_matrix_goal_has_a_label(self):
        for objective, locations in ms.MATRIX.items():
            self.assertIn(objective, ms.OBJECTIVES)
            for location, goals in locations.items():
                self.assertIn(location, ms.LOCATIONS)
                for goal in goals:
                    self.assertIn(goal, ms.GOALS)


class LegacyTests(unittest.TestCase):
    def test_old_drafts_keep_their_objective(self):
        for key in pub.OBJECTIVES:
            p = pub.clean_payload({**BASE, "objective": key}, today=TODAY)
            self.assertEqual(p["objective"], key)
            self.assertEqual(p["meta"]["objective"], pub.OBJECTIVES[key]["objective"])
            self.assertEqual(p["meta"]["budget_level"], "campaign")
            self.assertEqual(p["meta"]["budget"], 50)

    def test_new_structure_sets_equivalent_label(self):
        p = pub.clean_payload(with_meta(objective="OUTCOME_ENGAGEMENT", conversion_location="MESSAGING",
                                        messaging_apps=["WHATSAPP"], performance_goal="CONVERSATIONS"), today=TODAY)
        self.assertEqual(p["objective"], "whatsapp")
        self.assertEqual(p["ad"]["cta"], "WHATSAPP_MESSAGE")


class CleanTests(unittest.TestCase):
    def test_invalid_combination_falls_back_like_ads_manager(self):
        p = pub.clean_payload(with_meta(objective="OUTCOME_AWARENESS", conversion_location="WEBSITE",
                                        performance_goal="OFFSITE_CONVERSIONS", conversion_event="PURCHASE"), today=TODAY)
        m = p["meta"]
        self.assertEqual((m["conversion_location"], m["performance_goal"], m["conversion_event"]), ("NONE", "REACH", None))

    def test_value_goal_only_allows_value_bids(self):
        m = pub.clean_payload(with_meta(performance_goal="VALUE", bid_strategy="COST_CAP", bid_amount=20), today=TODAY)["meta"]
        self.assertEqual((m["bid_strategy"], m["bid_amount"], m["conversion_event"]), ("LOWEST_COST_WITHOUT_CAP", None, "PURCHASE"))

    def test_lifetime_budget_shows_daily_equivalent(self):
        p = pub.clean_payload(with_meta(budget_type="lifetime", budget=1000), today=TODAY)
        self.assertEqual(p["daily_budget"], 100.0)  # 10 dias
        self.assertTrue(p["meta"]["has_end_date"])

    def test_missing_items_per_level(self):
        cases = {
            "App da conta": with_meta(objective="OUTCOME_APP_PROMOTION", conversion_location="APP", performance_goal="APP_INSTALLS"),
            "Formulário instantâneo": with_meta(objective="OUTCOME_LEADS", conversion_location="ON_AD", performance_goal="LEAD_GENERATION"),
            "Número de telefone": with_meta(conversion_location="PHONE_CALL", performance_goal="QUALITY_CALL"),
            "Vídeo no anúncio": with_meta(objective="OUTCOME_AWARENESS", conversion_location="NONE", performance_goal="THRUPLAY"),
            "Meta de ROAS": with_meta(performance_goal="VALUE", bid_strategy="LOWEST_COST_WITH_MIN_ROAS"),
            "meta de custo": with_meta(bid_strategy="COST_CAP"),
            "Orçamento total": with_meta(budget_type="lifetime", budget=20),
        }
        for expected, data in cases.items():
            with self.subTest(expected=expected):
                self.assertIn(expected, " ".join(pub.readiness(pub.clean_payload(data, today=TODAY))))

    def test_existing_post_does_not_need_image_or_text(self):
        data = with_meta(use_existing_post=True)
        data["ad"] = {**data["ad"], "primary_text": "", "image_url": "", "instagram_post_id": "17900"}
        self.assertEqual(pub.readiness(pub.clean_payload(data, today=TODAY)), [])

    def test_destination_types(self):
        def dest(**kw):
            return ms.destination_type(pub.clean_payload(with_meta(**kw), today=TODAY)["meta"])
        self.assertEqual(dest(objective="OUTCOME_ENGAGEMENT", conversion_location="MESSAGING",
                              messaging_apps=["WHATSAPP", "INSTAGRAM_DIRECT"], performance_goal="CONVERSATIONS"),
                         "MESSAGING_INSTAGRAM_DIRECT_WHATSAPP")
        self.assertEqual(dest(objective="OUTCOME_ENGAGEMENT", conversion_location="ON_POST", performance_goal="THRUPLAY"), "ON_VIDEO")
        self.assertIsNone(dest(objective="OUTCOME_AWARENESS", conversion_location="NONE", performance_goal="REACH"))


class PublishTests(unittest.IsolatedAsyncioTestCase):
    async def publish(self, data):
        calls = []
        row = {"id": "d1", "client_id": "ruah", "status": "rascunho", "payload": data, "meta_ids": {}}

        async def graph(method, path, *, token, data=None, params=None):
            calls.append((method, path, data or {}))
            if path == "/act_123/adspixels":
                return {"data": [{"id": "555", "name": "Pixel", "last_fired_time": "2026-11-09"}]}
            return {"id": f"id{len(calls)}"}
        update = AsyncMock(return_value=[{**row, "status": "publicada"}])
        with patch.object(pub, "_draft", AsyncMock(return_value=row)), patch.object(pub, "_context", AsyncMock(return_value=CTX)), \
             patch.object(pub, "_graph", graph), patch.object(pub, "_image_hash", AsyncMock(return_value="h1")), \
             patch.object(pub, "sb_update", update), redirect_stdout(io.StringIO()):
            await pub.publish("ruah", "d1")
        posts = {p.rsplit("/", 1)[-1]: d for m, p, d in calls if m == "POST"}
        return posts["campaigns"], posts["adsets"], posts["adcreatives"]

    async def test_adset_budget_lifetime_with_bid_cap(self):
        campaign, adset, _ = await self.publish(with_meta(budget_level="adset", budget_type="lifetime", budget=900,
                                                          bid_strategy="LOWEST_COST_WITH_BID_CAP", bid_amount=12.5,
                                                          conversion_event="ADD_TO_CART"))
        self.assertNotIn("daily_budget", campaign)
        self.assertNotIn("lifetime_budget", campaign)
        self.assertEqual(campaign["is_adset_budget_sharing_enabled"], "false")
        self.assertEqual((adset["lifetime_budget"], adset["bid_strategy"], adset["bid_amount"]), ("90000", "LOWEST_COST_WITH_BID_CAP", "1250"))
        self.assertIn("end_time", adset)
        self.assertEqual(json.loads(adset["promoted_object"]), {"pixel_id": "555", "custom_event_type": "ADD_TO_CART"})
        self.assertTrue(all(d["status"] == "PAUSED" for d in (campaign, adset)))

    async def test_campaign_budget_cost_cap_special_category_no_end(self):
        campaign, adset, _ = await self.publish(with_meta(bid_strategy="COST_CAP", bid_amount=30, has_end_date=False,
                                                          special_ad_categories=["FINANCIAL_PRODUCTS_SERVICES"]))
        self.assertEqual((campaign["daily_budget"], campaign["bid_strategy"]), ("5000", "COST_CAP"))
        self.assertEqual(json.loads(campaign["special_ad_categories"]), ["FINANCIAL_PRODUCTS_SERVICES"])
        self.assertEqual(json.loads(campaign["special_ad_category_country"]), ["BR"])
        self.assertEqual(adset["bid_amount"], "3000")
        self.assertNotIn("end_time", adset)

    async def test_instant_form_leads(self):
        data = with_meta(objective="OUTCOME_LEADS", conversion_location="ON_AD", performance_goal="LEAD_GENERATION",
                         lead_form={"id": "777000", "name": "Black"})
        data["ad"] = {**data["ad"], "cta": "SIGN_UP"}
        _, adset, creative = await self.publish(data)
        self.assertEqual((adset["destination_type"], adset["optimization_goal"]), ("ON_AD", "LEAD_GENERATION"))
        self.assertEqual(json.loads(adset["promoted_object"]), {"page_id": "999"})
        link = json.loads(creative["object_story_spec"])["link_data"]
        self.assertEqual(link["call_to_action"], {"type": "SIGN_UP", "value": {"lead_gen_form_id": "777000"}})

    async def test_no_button_and_existing_post(self):
        data = with_meta(objective="OUTCOME_TRAFFIC", conversion_location="WEBSITE", performance_goal="LANDING_PAGE_VIEWS")
        data["ad"] = {**data["ad"], "cta": "NO_BUTTON"}
        _, adset, creative = await self.publish(data)
        self.assertEqual(adset["optimization_goal"], "LANDING_PAGE_VIEWS")
        self.assertNotIn("call_to_action", json.loads(creative["object_story_spec"])["link_data"])
        post = with_meta(use_existing_post=True)
        post["ad"] = {**post["ad"], "instagram_post_id": "17900"}
        _, _, creative = await self.publish(post)
        self.assertEqual((creative["source_instagram_media_id"], creative["object_id"]), ("17900", "999"))
        self.assertNotIn("object_story_spec", creative)

    async def test_meta_error_names_the_level(self):
        row = {"id": "d1", "client_id": "ruah", "status": "rascunho", "payload": with_meta(), "meta_ids": {}}

        async def graph(method, path, *, token, data=None, params=None):
            if path.endswith("/adsets"):
                raise pub.MetaAdError("AD_META_REJECTED", "Evento inválido")
            if path.endswith("/adspixels"):
                return {"data": [{"id": "555", "last_fired_time": "x"}]}
            return {"id": "c1"}
        update = AsyncMock(return_value=[row])
        with patch.object(pub, "_draft", AsyncMock(return_value=row)), patch.object(pub, "_context", AsyncMock(return_value=CTX)), \
             patch.object(pub, "_graph", graph), patch.object(pub, "sb_update", update), redirect_stdout(io.StringIO()):
            with self.assertRaises(StudioError) as caught:
                await pub.publish("ruah", "d1")
        self.assertEqual(str(caught.exception), "Conjunto de anúncios: Evento inválido")
        saved = update.await_args_list[-1].kwargs["patch"]
        self.assertEqual((saved["meta_ids"]["error_level"], saved["meta_ids"]["campaign_id"]), ("adset", "c1"))


class OptionsTests(unittest.IsolatedAsyncioTestCase):
    def test_preview_src_only_accepts_meta_iframe(self):
        good = '<iframe src="https://www.facebook.com/ads/api/preview_iframe.php?d=1&amp;t=2" width="1"></iframe>'
        self.assertEqual(options.preview_src(good), "https://www.facebook.com/ads/api/preview_iframe.php?d=1&t=2")
        self.assertIsNone(options.preview_src('<iframe src="https://evil.example/x"></iframe>'))

    async def test_official_preview_uses_generatepreviews_without_creating_ads(self):
        row = {"id": "d1", "payload": with_meta(), "meta_ids": {}}
        calls = []

        async def graph(method, path, *, token, data=None, params=None):
            calls.append((method, path, params or {}))
            return {"data": [{"body": '<iframe src="https://www.facebook.com/ads/api/preview_iframe.php?d=1"></iframe>'}]}
        with patch.object(pub, "_draft", AsyncMock(return_value=row)), patch.object(pub, "_context", AsyncMock(return_value=CTX)), \
             patch.object(pub, "_graph", graph), patch.object(pub, "_image_hash", AsyncMock(return_value="h1")):
            out = await options.official_preview("ruah", "d1", "INSTAGRAM_STORY")
        self.assertEqual(out["label"], "Stories do Instagram")
        self.assertEqual([(m, p) for m, p, _ in calls], [("GET", "/act_123/generatepreviews")])
        creative = json.loads(calls[0][2]["creative"])
        self.assertEqual(creative["object_story_spec"]["link_data"]["image_hash"], "h1")
        with self.assertRaises(StudioError):
            await options.official_preview("ruah", "d1", "TIKTOK")

    async def test_interest_search_uses_meta_list(self):
        async def graph(method, path, *, token, data=None, params=None):
            self.assertEqual((path, params["type"]), ("/search", "adinterest"))
            return {"data": [{"id": "6003", "name": "Perfume", "path": ["Compras", "Beleza", "Perfume"],
                              "audience_size_lower_bound": 1000000, "audience_size_upper_bound": 2000000}]}
        with patch.object(pub, "_ad_account", AsyncMock(return_value=CTX)), patch.object(pub, "_graph", graph):
            found = await options.search_interests("ruah", "perf")
        self.assertEqual((found[0]["id"], found[0]["path"]), ("6003", "Compras > Beleza"))
        self.assertEqual(await options.search_interests("ruah", "p"), [])


if __name__ == "__main__":
    unittest.main()


class TaskBriefTests(unittest.IsolatedAsyncioTestCase):
    async def test_ai_fills_official_objective_from_task_brief(self):
        from services import studio_calendar, studio_engines, studio_llm, brand_health, brand_knowledge
        seen = {}

        async def llm(**kw):
            seen.update(kw)
            return {"name": "Black Ruah WhatsApp", "primary_text": "Chama no Zap.", "headline": "Black", "description": "", "cta": "SHOP_NOW",
                    "age_min": 25, "age_max": 50, "gender": "mulheres", "regions": [], "interests": ["Perfume"],
                    "meta_objective": "OUTCOME_ENGAGEMENT", "conversion_location": "MESSAGING", "messaging_app": "WHATSAPP"}
        insert = AsyncMock(side_effect=lambda table, row: {**row, "id": "new"})
        with patch.object(studio_calendar, "load_profile", AsyncMock(return_value={"profile": {}})), \
             patch.object(studio_calendar, "language_rule", lambda p: ""), patch.object(studio_engines, "throttle", lambda c: None), \
             patch.object(studio_llm, "llm_json", llm), patch.object(brand_health, "audience_voice", AsyncMock(return_value="")), \
             patch.object(brand_knowledge, "knowledge_for_prompt", AsyncMock(return_value="")), \
             patch.object(pub, "sb_select", AsyncMock(return_value=[])), patch.object(pub, "sb_insert", insert):
            draft = await pub.generate_draft("ruah", user_id="u", month=None, objective="trafego", days_left=10,
                                             campaign={"task_brief": {"title": "Black no WhatsApp", "objective": "conversas", "x": "ignorado"}})
        self.assertIn("BRIEFING DA TAREFA", seen["prompt"])
        self.assertNotIn("ignorado", seen["prompt"])
        meta = draft["payload"]["meta"]
        self.assertEqual((meta["objective"], meta["conversion_location"], meta["messaging_apps"]), ("OUTCOME_ENGAGEMENT", "MESSAGING", ["WHATSAPP"]))
        self.assertEqual(draft["payload"]["objective"], "whatsapp")
        self.assertEqual(draft["source_campaign"], "Black no WhatsApp")


class FixtureSyncTests(unittest.TestCase):
    def test_frontend_fixture_matches_catalog(self):
        fixture = Path(__file__).resolve().parents[2] / "src/components/studio/__fixtures__/metaCatalog.json"
        self.assertEqual(json.loads(fixture.read_text(encoding="utf-8")), json.loads(json.dumps(ms.catalog())),
                         "Rode o comando do topo de MetaLevels.test.tsx para regenerar o catálogo da tela.")
