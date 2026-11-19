"""Atendente de IA do WhatsApp nativo: catálogo Shopify, cartões da Meta, botões, pausa da equipe e modos."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from services import whatsapp_ai as ai

NOW = datetime.now(timezone.utc)
RAW = [
    {"id": 111, "title": "Legging Twist", "handle": "legging-twist", "status": "active", "published_at": "2026-01-01",
     "product_type": "Legging", "tags": "skinwear, bf", "body_html": "<p>Tecido com <b>tecnologia</b> têxtil.</p>",
     "image": {"src": "https://cdn/twist.jpg"},
     "variants": [
         {"id": 1001, "title": "P", "price": "289.00", "compare_at_price": "349.00", "inventory_management": "shopify", "inventory_quantity": 3},
         {"id": 1002, "title": "M", "price": "289.00", "inventory_management": "shopify", "inventory_quantity": 0, "inventory_policy": "deny"},
     ]},
    {"id": 222, "title": "Capri", "handle": "capri", "status": "active", "published_at": "2026-01-01",
     "variants": [{"id": 2001, "title": "Default Title", "price": "199.90", "inventory_management": None}]},
    {"id": 333, "title": "Rascunho", "handle": "rascunho", "status": "active", "published_at": None,
     "variants": [{"id": 3001, "title": "U", "price": "10"}]},
]
SETTINGS = {**ai.DEFAULT_SETTINGS, "mode": "auto", "featured_products": ["Twist", "Capri"], "human_pause_minutes": 240}


def catalog():
    return {"domain": "roove.com.br", "products": ai.normalize_products(RAW, "roove.com.br")}


class CatalogTests(unittest.TestCase):
    def test_only_published_products_with_stock_by_size(self):
        products = catalog()["products"]
        self.assertEqual([p["handle"] for p in products], ["legging-twist", "capri"])
        twist = products[0]
        self.assertEqual(twist["url"], "https://roove.com.br/products/legging-twist")
        self.assertEqual([(v["title"], v["available"]) for v in twist["variants"]], [("P", True), ("M", False)])
        self.assertEqual(twist["compare_at"], 349.0)
        self.assertEqual(twist["description"], "Tecido com tecnologia têxtil.")
        self.assertTrue(products[1]["available"])  # estoque não controlado = disponível

    def test_prompt_block_lists_sizes_featured_and_prices(self):
        block = ai.catalog_block(catalog(), ["Twist"])
        self.assertIn("[legging-twist] Legging Twist ★ seleção em destaque · R$ 289,00 (de R$ 349,00) · disponível: P; esgotado: M", block)
        self.assertIn("indisponível agora", ai.catalog_block(None, []))

    def test_featured_matches_by_word(self):
        twist = catalog()["products"][0]
        self.assertTrue(ai.is_featured(twist, ["twist"]))
        self.assertFalse(ai.is_featured(twist, ["Full Zip"]))


class MetaCatalogTests(unittest.TestCase):
    def test_matches_shopify_retailer_ids_urls_and_names(self):
        items = [
            {"retailer_id": "shopify_BR_111_1002", "availability": "out of stock"},
            {"retailer_id": "shopify_BR_111_1001", "availability": "in stock"},
            {"retailer_id": "sku-capri", "url": "https://roove.com.br/products/capri?variant=2001"},
            {"retailer_id": "orfao", "name": "Outra coisa"},
        ]
        match = ai.match_meta_items(catalog()["products"], items)
        self.assertEqual(match["by_product"], {"111": "shopify_BR_111_1001", "222": "sku-capri"})
        self.assertEqual(match["by_retailer"]["shopify_BR_111_1002"], ("111", "1002"))
        self.assertNotIn("orfao", match["by_retailer"])

    def test_cart_link_from_catalog_order(self):
        items = [{"retailer_id": "shopify_BR_111_1001"}, {"retailer_id": "sku-capri", "url": "https://x/products/capri"}]
        match = ai.match_meta_items(catalog()["products"], items)
        order = ai.parse_catalog_order("[pedido pelo catálogo] 2x shopify_BR_111_1001; 1x sku-capri · tem P?")
        self.assertEqual(order, [("shopify_BR_111_1001", 2), ("sku-capri", 1)])
        self.assertEqual(ai.cart_link(order, catalog(), match), "https://roove.com.br/cart/1001:2,2001:1")
        self.assertIsNone(ai.cart_link([("desconhecido", 1)], catalog(), match))
        self.assertEqual(ai.parse_catalog_order("oi"), [])


class DecisionTests(unittest.TestCase):
    def test_keeps_only_real_available_products_and_short_buttons(self):
        raw = {"reply": "Separei duas opções — olha só.", "buttons": ["Para treinar", "Dia a dia e treino também", "Para treinar"],
               "products": ["legging-twist", "[capri]", "inventado"], "handoff": False, "handoff_reason": "",
               "insight": {"stage": "interessada", "interests": ["legging"], "objections": ["preco", "xpto"], "next_step": "",
                           "summary": "Quer legging, ligar 11 99999-0000"}}
        out = ai.clean_decision(raw, catalog())
        self.assertEqual(out["reply"], "Separei duas opções, olha só.")
        self.assertEqual(out["buttons"], ["Para treinar", "Dia a dia e treino"])
        self.assertEqual([p["handle"] for p in out["products"]], ["legging-twist", "capri"])
        self.assertEqual(out["insight"]["objections"], ["preco"])
        self.assertIn("[número]", out["insight"]["summary"])

    def test_handoff_drops_buttons_and_products(self):
        out = ai.clean_decision({"reply": "", "buttons": ["A"], "products": ["capri"], "handoff": False, "insight": {}}, catalog())
        self.assertTrue(out["handoff"])
        self.assertEqual((out["buttons"], out["products"]), ([], []))
        self.assertEqual(out["reply"], ai.HANDOFF_FALLBACK)


class PayloadTests(unittest.TestCase):
    def decision(self, **kw):
        products = catalog()["products"]
        return {"reply": "Olha essas", "buttons": [], "products": products, "handoff": False, **kw}

    def test_buttons_then_product_list_from_meta_catalog(self):
        meta = {"catalog_id": "999", "items": []}
        match = {"by_product": {"111": "r1", "222": "r2"}, "by_retailer": {}}
        out = ai.outgoing_payloads(self.decision(buttons=["Para treinar"]), meta=meta, match=match)
        self.assertEqual(out[0][0]["interactive"]["type"], "button")
        self.assertEqual(out[0][0]["interactive"]["action"]["buttons"][0]["reply"]["title"], "Para treinar")
        listing = out[1][0]["interactive"]
        self.assertEqual(listing["type"], "product_list")
        self.assertEqual([i["product_retailer_id"] for i in listing["action"]["sections"][0]["product_items"]], ["r1", "r2"])
        self.assertEqual(len(out), 2)

    def test_without_meta_catalog_sends_links(self):
        out = ai.outgoing_payloads(self.decision(), meta=None, match=None)
        self.assertEqual(out[0][0]["type"], "text")
        self.assertIn("https://roove.com.br/products/capri", out[1][1])
        self.assertIn("R$ 289,00 (de R$ 349,00)", out[1][1])

    def test_single_card_and_rest_as_links(self):
        meta = {"catalog_id": "999", "items": []}
        out = ai.outgoing_payloads(self.decision(), meta=meta, match={"by_product": {"111": "r1"}, "by_retailer": {}})
        self.assertEqual(out[1][0]["interactive"]["type"], "product")
        self.assertIn("capri", out[2][1])


class ShouldAnswerTests(unittest.TestCase):
    thread = {"last_inbound_at": (NOW - timedelta(minutes=2)).isoformat()}

    def msgs(self, *rows):
        return [{"direction": d, "by_ai": by_ai, "type": "text", "sent_at": (NOW - timedelta(minutes=m)).isoformat()} for d, by_ai, m in rows]

    def test_rules(self):
        last_in = self.msgs(("out", True, 5), ("in", False, 2))
        self.assertEqual(ai.should_answer(thread=self.thread, messages=last_in, settings=SETTINGS, now=NOW), "responder")
        self.assertEqual(ai.should_answer(thread=self.thread, messages=last_in, settings={**SETTINGS, "mode": "off"}, now=NOW), "desligada")
        paused = {**self.thread, "ai_paused_until": (NOW + timedelta(hours=1)).isoformat()}
        self.assertEqual(ai.should_answer(thread=paused, messages=last_in, settings=SETTINGS, now=NOW), "com_a_equipe")
        team = self.msgs(("out", False, 30), ("in", False, 2))
        self.assertEqual(ai.should_answer(thread=self.thread, messages=team, settings=SETTINGS, now=NOW), "equipe_respondendo")
        old = {"last_inbound_at": (NOW - timedelta(hours=25)).isoformat()}
        self.assertEqual(ai.should_answer(thread=old, messages=last_in, settings=SETTINGS, now=NOW), "fora_da_janela")
        self.assertEqual(ai.should_answer(thread=self.thread, messages=self.msgs(("in", False, 3), ("out", True, 1)),
                                          settings=SETTINGS, now=NOW), "nada_novo")


class ProcessThreadTests(unittest.IsolatedAsyncioTestCase):
    thread = {"id": "t1", "number_id": "n1", "wa_id": "5511999990000", "last_inbound_at": (NOW - timedelta(minutes=1)).isoformat()}
    messages = [{"direction": "in", "by_ai": False, "type": "text", "text": "quero uma legging", "sent_at": NOW.isoformat()}]

    async def run_thread(self, settings, decision):
        updates = []

        async def update(table, *, filters, patch, returning="representation"):
            updates.append((table, patch))
            return []
        with patch.object(ai, "_thread_messages", AsyncMock(return_value=self.messages)), \
             patch.object(ai, "_number", AsyncMock(return_value={"id": "n1", "phone_number_id": "pn", "access_token": "tok"})), \
             patch.object(ai, "_commerce", AsyncMock(return_value=(catalog(), None, None))), \
             patch.object(ai, "decide", AsyncMock(return_value=decision)), \
             patch.object(ai, "send_decision", AsyncMock(return_value=1)) as send, \
             patch.object(ai, "sb_update", side_effect=update):
            result = await ai.process_thread("roove", dict(self.thread), settings)
        return result, send, updates

    async def test_suggest_mode_never_sends(self):
        decision = ai.clean_decision({"reply": "Oi! Para treinar ou dia a dia?", "buttons": ["Para treinar"], "products": [],
                                      "handoff": False, "insight": {"stage": "novo", "interests": [], "objections": [],
                                                                     "next_step": "", "summary": ""}}, catalog())
        result, send, updates = await self.run_thread({**SETTINGS, "mode": "suggest"}, decision)
        self.assertEqual(result, "sugestao")
        send.assert_not_awaited()
        self.assertEqual(updates[-1][1]["ai_suggestion"]["buttons"], ["Para treinar"])

    async def test_auto_handoff_sends_and_pauses(self):
        decision = ai.clean_decision({"reply": "Vou encaminhar para a equipe.", "buttons": [], "products": [], "handoff": True,
                                      "handoff_reason": "troca", "insight": {}}, catalog())
        result, send, updates = await self.run_thread(SETTINGS, decision)
        self.assertEqual(result, "equipe")
        send.assert_awaited_once()
        self.assertEqual(updates[-1][1]["ai_handoff_reason"], "troca")
        self.assertIn("ai_paused_until", updates[-1][1])


class AdGroupAndClaudeTests(unittest.IsolatedAsyncioTestCase):
    async def test_group_link_only_for_ad_and_only_once(self):
        settings = {**SETTINGS, "ad_group_link": "https://chat.whatsapp.com/ABC", "ad_group_message": "Entra no grupo VIP: {link}"}
        calls = []

        async def select(table, **kw):
            calls.append(table)
            if table == "whatsapp_threads":
                return [{"ai_group_sent_at": None}]
            return [{"headline": "First Access Black Friday", "ad_id": "1"}]
        with patch.object(ai, "sb_select", side_effect=select):
            plan = await ai.ad_group_plan("roove", {"id": "t1"}, settings)
        self.assertEqual(plan["text"], "Entra no grupo VIP: https://chat.whatsapp.com/ABC")
        self.assertEqual(plan["headline"], "First Access Black Friday")

        async def already(table, **kw):
            return [{"ai_group_sent_at": "2026-11-19T10:00:00Z"}] if table == "whatsapp_threads" else [{"headline": ""}]
        with patch.object(ai, "sb_select", side_effect=already):
            self.assertIsNone(await ai.ad_group_plan("roove", {"id": "t1"}, settings))

        async def organic(table, **kw):
            return [{"ai_group_sent_at": None}] if table == "whatsapp_threads" else []
        with patch.object(ai, "sb_select", side_effect=organic):
            self.assertIsNone(await ai.ad_group_plan("roove", {"id": "t1"}, settings))
        self.assertIsNone(await ai.ad_group_plan("roove", {"id": "t1"}, SETTINGS))  # sem link configurado

    async def test_auto_sends_reply_then_group_invite_and_marks(self):
        decision = ai.clean_decision({"reply": "Oi! Que bom te ver.", "buttons": [], "products": [], "handoff": False, "insight": {}}, catalog())
        updates = []

        async def update(table, *, filters, patch, returning="representation"):
            updates.append(patch)
        with patch.object(ai, "_thread_messages", AsyncMock(return_value=ProcessThreadTests.messages)), \
             patch.object(ai, "_number", AsyncMock(return_value={"id": "n1", "phone_number_id": "pn", "access_token": "tok"})), \
             patch.object(ai, "_commerce", AsyncMock(return_value=(catalog(), None, None))), \
             patch.object(ai, "ad_group_plan", AsyncMock(return_value={"text": "Grupo: https://chat.whatsapp.com/ABC", "headline": "BF"})), \
             patch.object(ai, "decide", AsyncMock(return_value=decision)) as decide, \
             patch.object(ai, "send_decision", AsyncMock(return_value=1)) as send, \
             patch.object(ai, "sb_update", side_effect=update):
            await ai.process_thread("roove", dict(ProcessThreadTests.thread), SETTINGS)
        self.assertEqual(send.await_count, 2)
        self.assertEqual(send.await_args_list[1].args[3]["reply"], "Grupo: https://chat.whatsapp.com/ABC")
        self.assertIn("anúncio", decide.await_args.kwargs["origin_note"])
        self.assertIn("ai_group_sent_at", updates[-1])

    async def test_claude_answers_and_falls_back_to_platform(self):
        raw = {"reply": "Oi do Claude", "buttons": [], "products": [], "handoff": False, "handoff_reason": "", "insight": {}}
        settings = {**SETTINGS, "_claude_secret": "enc", "claude_model": "claude-sonnet-5-5"}
        with patch.object(ai, "_brand", AsyncMock(return_value="")), patch("services.crypto.decrypt_secret", return_value="sk-ant-x"), \
             patch.object(ai, "_claude", AsyncMock(return_value=raw)) as claude, \
             patch("services.studio_llm.llm_json", AsyncMock(return_value={**raw, "reply": "Oi da plataforma"})) as platform:
            out = await ai.decide("roove", settings=settings, catalog=catalog(), thread={}, messages=ProcessThreadTests.messages)
        self.assertEqual(out["reply"], "Oi do Claude")
        platform.assert_not_awaited()
        self.assertEqual(claude.await_args.kwargs["model"], "claude-sonnet-5-5")
        with patch.object(ai, "_brand", AsyncMock(return_value="")), patch("services.crypto.decrypt_secret", return_value="sk-ant-x"), \
             patch.object(ai, "_claude", AsyncMock(side_effect=ai.WhatsAppAiError("CLAUDE_FAILED", "sem crédito"))), \
             patch("services.studio_llm.llm_json", AsyncMock(return_value={**raw, "reply": "Oi da plataforma"})):
            out = await ai.decide("roove", settings=settings, catalog=catalog(), thread={}, messages=ProcessThreadTests.messages)
        self.assertEqual(out["reply"], "Oi da plataforma")

    async def test_rejects_key_that_is_not_claude(self):
        with self.assertRaises(ai.WhatsAppAiError) as caught:
            await ai.save_claude_key("roove", api_key="sk-openai-123456789012345", model="claude-sonnet-5-5", user_id="u")
        self.assertEqual(caught.exception.code, "INVALID_KEY")


if __name__ == "__main__":
    unittest.main()
