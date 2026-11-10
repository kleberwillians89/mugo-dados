"""WhatsApp da marca: chave de telefone, ligação conversa → pedido e números da tela."""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import whatsapp_insights as wi  # noqa: E402


def lead(key, seen, **origin):
    return {"phone_key": key, "first_seen_at": seen, "origin": origin}


def order(phone, at, value, name="#1"):
    return {"phone": phone, "created_at_shopify": at, "value": value, "name": name}


class PhoneKeyTests(unittest.TestCase):
    def test_same_key_as_crm(self):
        # Mesmo valor que o CRM calcula (crmmugo tests/whatsapp-origin.test.mjs).
        self.assertEqual(wi.phone_key("5511993161161"), "8da0ce4f7795d49d1331629bcee13398")

    def test_ninth_digit_and_formatting(self):
        key = wi.phone_key("5511993161161")
        self.assertEqual(wi.phone_key("+55 (11) 9316-1161"), key)
        self.assertEqual(wi.phone_key("(11) 99316-1161"), key)
        self.assertIsNone(wi.phone_key("123"))

    def test_area_code_55_without_country_code(self):
        # Mesmo valor que o CRM calcula para o wa_id 5555991234567.
        self.assertEqual(wi.phone_key("(55) 99123-4567"), "2ef2c81a863aa44f0c8e8a7a85cac5c3")

    def test_order_phone_fields(self):
        keys = wi.order_phone_keys({"phone": None, "billing_phone": "11 99316-1161", "shipping_phone": "+5511993161161"})
        self.assertEqual(keys, [wi.phone_key("5511993161161")])


class MatchTests(unittest.TestCase):
    def test_order_within_window_counts_once(self):
        k = wi.phone_key("5511993161161")
        leads = [lead(k, "2026-11-01T12:00:00Z", source="META_ADS_WHATSAPP", ad_id="1")]
        orders = [order("11993161161", "2026-11-03T10:00:00Z", 389.0), order("11993161161", "2026-11-20T10:00:00Z", 100.0)]
        matched = wi.match_orders(leads, orders)
        self.assertEqual(len(matched[0]), 1)  # o de 19 dias depois fica fora da janela de 7 dias

    def test_order_before_first_contact_does_not_count(self):
        k = wi.phone_key("5511993161161")
        matched = wi.match_orders([lead(k, "2026-11-05T12:00:00Z")], [order("11993161161", "2026-11-04T10:00:00Z", 50.0)])
        self.assertEqual(matched, {})

    def test_order_without_phone_is_never_distributed(self):
        k = wi.phone_key("5511993161161")
        matched = wi.match_orders([lead(k, "2026-11-01T12:00:00Z")], [{"created_at_shopify": "2026-11-02T10:00:00Z", "value": 10}])
        self.assertEqual(matched, {})

    def test_goes_to_latest_contact_before_purchase(self):
        k = wi.phone_key("5511993161161")
        leads = [lead(k, "2026-11-01T12:00:00Z"), lead(k, "2026-11-03T12:00:00Z")]
        matched = wi.match_orders(leads, [order("11993161161", "2026-11-04T10:00:00Z", 10.0)])
        self.assertEqual(list(matched), [1])


class AggregateTests(unittest.TestCase):
    def test_numbers_for_screen(self):
        a, b, c = (wi.phone_key(f"55119931611{i:02d}") for i in range(3))
        leads = [
            lead(a, "2026-11-01T12:00:00Z", source="META_ADS_WHATSAPP", ad_id="111", ad_headline="Kit BF"),
            lead(b, "2026-11-02T12:00:00Z", source="META_ADS_WHATSAPP", ad_id="222", ad_headline="Unboxing"),
            lead(c, "2026-11-02T12:00:00Z", source="ENTRY_CODE", entry_code="loja-qr"),
        ]
        orders = [order("5511993161100", "2026-11-01T13:00:00Z", 400.0), order("5511993161102", "2026-11-03T13:00:00Z", 100.0)]
        stats = {"111": {"spend": 100.0, "ad_name": "Reels Kit BF"}, "222": {"spend": 300.0, "ad_name": "Unboxing"}}
        out = wi.aggregate(leads, orders, orders, stats)
        t = out["totals"]
        self.assertEqual(t["conversations"], 3)
        self.assertEqual(t["converted_conversations"], 2)
        self.assertEqual(t["revenue"], 500.0)
        self.assertEqual(t["share_of_store_revenue"], 100.0)
        # Venda na janela de 7 dias DEPOIS do período não infla a participação na receita da loja.
        late = wi.aggregate(leads, orders, orders[:1], stats)["totals"]
        self.assertEqual(late["share_of_store_revenue"], 100.0)
        self.assertEqual(late["revenue"], 500.0)
        self.assertEqual(t["ad_spend"], 400.0)
        self.assertEqual(t["cost_per_conversation"], 200.0)
        self.assertEqual(t["cost_per_sale"], 400.0)
        self.assertEqual(t["ads_roas"], 1.0)
        self.assertEqual([o["key"] for o in out["origins"]], ["ad", "link"])
        ads = {row["ad_id"]: row for row in out["ads"]}
        self.assertEqual(ads["111"]["roas"], 4.0)
        self.assertEqual(ads["111"]["verdict"], None)  # gasto abaixo do mínimo para julgar
        self.assertEqual(ads["222"]["verdict"]["code"], "weak")
        self.assertEqual(out["links"][0]["code"], "loja-qr")
        self.assertIn("R$ 300,00", out["alerts"][0]["text"])

    def test_labels(self):
        self.assertEqual(wi.origin_label({"source": "META_ADS_WHATSAPP", "ad_headline": "Kit BF"}), "Anúncio · Kit BF")
        self.assertEqual(wi.origin_label({"entry_code": "loja-qr"}), "Link · loja-qr")
        self.assertEqual(wi.origin_label({}), "Direto")


class BuildTests(unittest.TestCase):
    def test_no_brand_number(self):
        with patch.object(wi.whatsapp_sources, "brand_leads", AsyncMock(return_value={"available": True, "connected": False})):
            out = asyncio.run(wi.build_whatsapp_insights("ruah", start="2026-11-01", end="2026-11-07"))
        self.assertEqual(out["status"], "no_brand_number")

    def test_inbox_hides_phone_key_and_marks_purchase(self):
        k = wi.phone_key("5511993161161")
        conv = {"id": "c1", "contact": {"name": "Mariana", "phone_masked": "•••• 1161", "phone_key": k, "first_seen_at": "2026-11-01T12:00:00Z"},
                "origin": {"source": "META_ADS_WHATSAPP", "ad_headline": "Kit BF"}}
        with patch.object(wi.whatsapp_sources, "brand_conversations", AsyncMock(return_value={"available": True, "connected": True, "conversations": [conv]})), \
             patch.object(wi, "resolve_commerce_provider", AsyncMock(return_value={"provider": "shopify"})), \
             patch.object(wi.whatsapp_sources, "brand_sales", AsyncMock(return_value=[])), \
             patch.object(wi, "_recent_shopify_orders", AsyncMock(return_value=[
                 order("11993161161", "2026-11-01T13:00:00Z", 389.0, "#4417"),
                 order("11993161161", "2026-10-20T13:00:00Z", 999.0, "#4000"),  # antes do 1º contato: não conta
             ])):
            out = asyncio.run(wi.build_whatsapp_inbox("ruah"))
        row = out["conversations"][0]
        self.assertNotIn("phone_key", row["contact"])
        self.assertEqual(row["purchase"]["last_order"], "#4417")
        self.assertEqual(row["purchase"]["orders"], 1)
        self.assertEqual(row["origin"]["label"], "Anúncio · Kit BF")


    def test_crm_sales_count_for_brand_with_own_crm(self):
        # Ruah: sem Shopify; a venda vem do CRM dela com a chave pronta e só a data.
        k = wi.phone_key("5511993161161")
        leads = {"available": True, "connected": True, "truncated": False,
                 "leads": [{"phone_key": k, "first_seen_at": "2026-11-03T15:00:00Z", "origin": {"source": "META_ADS_WHATSAPP", "ad_id": "111"}}]}
        sale = {"name": "Venda CRM 2026-11-03", "created_at_shopify": "2026-11-03T23:59:00-03:00", "value": 389.0,
                "phone_keys": [k], "source": "crm"}
        with patch.object(wi.whatsapp_sources, "brand_leads", AsyncMock(return_value=leads)), \
             patch.object(wi.whatsapp_sources, "brand_sales", AsyncMock(return_value=[sale])), \
             patch.object(wi, "resolve_commerce_provider", AsyncMock(return_value={"provider": None})), \
             patch.object(wi, "_ad_stats", AsyncMock(return_value={"111": {"spend": 50.0, "ad_name": "Kit"}})):
            out = asyncio.run(wi.build_whatsapp_insights("ruah", start="2026-11-01", end="2026-11-07"))
        self.assertEqual(out["totals"]["converted_conversations"], 1)
        self.assertEqual(out["totals"]["revenue"], 389.0)
        self.assertEqual(out["ads"][0]["roas"], 7.78)


class SourcesTests(unittest.TestCase):
    def test_bridge_config_from_env(self):
        from services import whatsapp_sources as ws
        cid = "b1281853-ab59-4fd2-b824-df88ebddabb6"
        env = '{"%s": {"url": "https://x.supabase.co/functions/v1/mugoverso-bridge", "key": "k"}, "roove": {"url": "https://y.supabase.co/x", "key": "r"}, "../x": {"url": "https://z", "key": "k"}, "sem-https": {"url": "http://z", "key": "k"}}' % cid
        with patch.dict(os.environ, {"WHATSAPP_BRAND_BRIDGES": env}):
            self.assertEqual(ws.bridge_for(cid.upper())["key"], "k")
            self.assertEqual(ws.bridge_for("roove")["key"], "r")
            self.assertIsNone(ws.bridge_for("../x"))
            self.assertIsNone(ws.bridge_for("sem-https"))
        with patch.dict(os.environ, {"WHATSAPP_BRAND_BRIDGES": "{quebrado"}):
            self.assertIsNone(ws.bridge_for(cid))

    def test_crm_sales_shape_and_failure(self):
        from services import whatsapp_sources as ws
        k = wi.phone_key("5511993161161")
        cfg = {"url": "https://x", "key": "k"}
        with patch.object(ws, "bridge_for", return_value=cfg), \
             patch.object(ws, "_bridge_call", AsyncMock(return_value={"available": True, "sales": [
                 {"phone_keys": [k, "nao-hash"], "sale_date": "2026-11-03", "value": 120.5}, {"phone_keys": [], "sale_date": "2026-11-03", "value": 1}]})):
            sales = asyncio.run(ws.brand_sales("ruah", "2026-11-01", "2026-11-07"))
        self.assertEqual(len(sales), 1)
        self.assertEqual(sales[0]["phone_keys"], [k])
        self.assertEqual(sales[0]["created_at_shopify"], "2026-11-03T23:59:00-03:00")
        with patch.object(ws, "bridge_for", return_value=cfg), \
             patch.object(ws, "_bridge_call", AsyncMock(side_effect=ws.StudioError("CRM_UNREACHABLE"))):
            self.assertEqual(asyncio.run(ws.brand_sales("ruah", "2026-11-01", "2026-11-07")), [])

    def test_without_bridge_falls_back_to_crm_mugo(self):
        from services import whatsapp_sources as ws
        with patch.object(ws, "bridge_for", return_value=None), \
             patch.object(ws.crm_bridge, "brand_leads", AsyncMock(return_value={"available": True, "connected": False})) as mugo:
            out = asyncio.run(ws.brand_leads("roove", "2026-11-01", "2026-11-07"))
        mugo.assert_awaited_once()
        self.assertFalse(out["connected"])


if __name__ == "__main__":
    unittest.main()


class AiStageFunnelTests(unittest.TestCase):
    """Ficha da IA de atendimento do CRM: funil por fase e o que trava a venda."""

    def test_funnel_and_objections(self):
        leads = [
            {**lead("k1", "2026-11-01T12:00:00Z", source="ad", ad_id="111"), "stage": "negociando", "objections": ["frete", "frete"]},
            {**lead("k2", "2026-11-01T12:00:00Z", source="ad", ad_id="111"), "stage": "interessada", "objections": ["preco"]},
            {**lead("k3", "2026-11-01T12:00:00Z"), "stage": "quase", "objections": ["xpto"]},
            {**lead("k4", "2026-11-01T12:00:00Z", source="ad", ad_id="111"), "stage": "novo", "objections": ["frete"]},
        ]
        crm_sale = {"name": "Venda CRM", "created_at_shopify": "2026-11-02T23:59:00-03:00", "value": 100.0, "phone_keys": ["k2"]}
        data = wi.aggregate(leads, [crm_sale], [crm_sale], {})
        stages = {row["key"]: row["count"] for row in data["stages"]}
        # Venda registrada vence a leitura da IA; fase inválida não entra.
        self.assertEqual(stages, {"negociando": 1, "comprou": 1, "novo": 1})
        self.assertEqual(data["interpreted_conversations"], 3)
        self.assertEqual(data["objections"][0], {"key": "frete", "label": "Frete", "count": 2})
        ad = data["ads"][0]
        self.assertEqual(ad["advanced"], 2)
        self.assertEqual(ad["top_objection"]["key"], "frete")

    def test_without_ai_data_lists_are_empty(self):
        data = wi.aggregate([lead("k1", "2026-11-01T12:00:00Z")], [], [], {})
        self.assertEqual(data["stages"], [])
        self.assertEqual(data["objections"], [])
        self.assertEqual(data["interpreted_conversations"], 0)
