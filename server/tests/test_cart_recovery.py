"""Recuperação de carrinho: nada pessoal em claro, sequência com consentimento, quem comprou não recebe, receita
recuperada contada uma vez e só com contato dentro da janela."""
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import cart_recovery as cr
from services import email_marketing as em
from services import email_resend as er

ENV = {"TOKEN_ENCRYPTION_KEY": "teste-chave", "API_PUBLIC_URL": "https://api.exemplo.com"}
CHECKOUT = {
    "id": 9001, "token": "tok1", "cart_token": "cart1", "email": "Ana@Mail.com", "phone": "(11) 98888-7777",
    "buyer_accepts_marketing": True, "created_at": "2026-11-10T12:00:00Z", "updated_at": "2026-11-10T12:05:00Z",
    "completed_at": None, "total_price": "389.70", "currency": "BRL",
    "abandoned_checkout_url": "https://roove.com.br/checkouts/ac/tok1/recover?key=x",
    "customer": {"first_name": "Ana", "email": "ana@mail.com"},
    "shipping_address": {"first_name": "Ana", "address1": "Rua X, 10", "phone": "11988887777"},
    "line_items": [{"title": "Legging Move", "variant_title": "P / Preto", "quantity": 1, "price": "189.90", "product_id": 1},
                   {"title": "Top Essencial", "quantity": 2, "price": "99.90"}],
}
SETTINGS = {**cr.DEFAULTS, "enabled": True, "email_design": cr.email_builder.default_cart_design(), "whatsapp_template": "carrinho_v1"}


class MinimizeTests(unittest.TestCase):
    def test_no_personal_data_in_clear(self):
        with patch.dict(os.environ, ENV):
            data = cr.minimize(CHECKOUT)
            dumped = json.dumps(data)
            for secret in ("ana@mail.com", "Ana@Mail.com", "98888", "Rua X", '"Ana"'):
                self.assertNotIn(secret, dumped)
            self.assertEqual(len(data["email_hash"]), 32)
            self.assertEqual(len(data["phone_key"]), 32)
            self.assertEqual(cr._contact({"contact_enc": data["contact_enc"]}),
                             {"email": "ana@mail.com", "phone": "(11) 98888-7777", "first_name": "Ana"})
            self.assertEqual(data["line_items"][0], {"title": "Legging Move", "variant": "P / Preto", "quantity": 1, "price": 189.9, "product_id": "1"})
            self.assertEqual((data["total_price"], data["accepts_marketing"], data["id"]), (389.7, True, "9001"))

    def test_whatsapp_number_normalization(self):
        self.assertEqual(cr.whatsapp_to("(11) 98888-7777"), "5511988887777")
        self.assertEqual(cr.whatsapp_to("+351 912 345 678"), "351912345678")
        self.assertIsNone(cr.whatsapp_to("123"))


class SettingsTests(unittest.TestCase):
    def test_steps_validation(self):
        self.assertEqual(cr.clean_settings({"steps": [{"channel": "email", "delay_minutes": 60}, {"channel": "whatsapp", "delay_minutes": 1440}]})["steps"][1],
                         {"channel": "whatsapp", "delay_minutes": 1440})
        for steps in ([{"channel": "instagram", "delay_minutes": 60}], [{"channel": "email", "delay_minutes": 5}],
                      [{"channel": "email", "delay_minutes": 600}, {"channel": "email", "delay_minutes": 60}]):
            with self.assertRaises(cr.CartError):
                cr.clean_settings({"steps": steps})
        self.assertEqual(cr.clean_settings({"whatsapp_variables": ["nome", "senha", "link"]})["whatsapp_variables"], ["nome", "link"])

    def test_outcome_needs_contact_inside_window(self):
        at = datetime(2026, 11, 12, tzinfo=timezone.utc)
        touched = {"steps_done": 1, "last_touch_at": "2026-11-10T13:00:00Z"}
        self.assertEqual(cr.outcome(touched, at=at, attribution_days=7), "recuperado")
        self.assertEqual(cr.outcome(touched, at=at + timedelta(days=10), attribution_days=7), "comprou_sem_contato")
        self.assertEqual(cr.outcome({"steps_done": 0, "last_touch_at": None}, at=at, attribution_days=7), "comprou_sem_contato")

    def test_whatsapp_params_follow_template_order(self):
        cart = {"items": [{"title": "Legging"}, {"title": "Top"}], "value": 389.7, "recovery_url": "https://r"}
        self.assertEqual(cr.wa_params(["nome", "produto", "valor", "link"], first_name="Ana", cart=cart),
                         ["Ana", "Legging e mais 1", "R$ 389,70", "https://r"])


class UpsertTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_cart_schedules_first_step_from_creation(self):
        upsert = AsyncMock()
        with patch.dict(os.environ, ENV), patch.object(cr, "sb_select", AsyncMock(return_value=[])), patch.object(cr, "sb_upsert", upsert), \
             patch.object(cr, "get_settings", AsyncMock(return_value=SETTINGS)):
            out = await cr.upsert_checkout("roove", cr.minimize(CHECKOUT))
        row = upsert.await_args.args[1][0]
        self.assertEqual(out["status"], "aberto")
        self.assertEqual(row["next_step_at"], "2026-11-10T13:00:00+00:00")
        self.assertTrue(row["contact_enc"])

    async def test_update_never_resets_progress(self):
        update = AsyncMock()
        with patch.dict(os.environ, ENV), patch.object(cr, "sb_select", AsyncMock(return_value=[{"checkout_id": "9001", "status": "recuperado", "steps_done": 1}])), \
             patch.object(cr, "sb_update", update):
            await cr.upsert_checkout("roove", cr.minimize(CHECKOUT))
        patch_sent = update.await_args.kwargs["patch"]
        self.assertNotIn("status", patch_sent)
        self.assertNotIn("steps_done", patch_sent)
        self.assertNotIn("contact_enc", patch_sent)  # carrinho encerrado não volta a guardar contato

    async def test_checkout_without_contact_is_not_followed(self):
        upsert = AsyncMock()
        bare = {**CHECKOUT, "email": None, "phone": None, "customer": {}, "shipping_address": {}}
        with patch.dict(os.environ, ENV), patch.object(cr, "sb_select", AsyncMock(return_value=[])), patch.object(cr, "sb_upsert", upsert), \
             patch.object(cr, "get_settings", AsyncMock(return_value=SETTINGS)):
            out = await cr.upsert_checkout("roove", cr.minimize(bare))
        self.assertEqual(out["status"], "sem_contato")
        self.assertIsNone(upsert.await_args.args[1][0]["next_step_at"])

    async def test_order_with_same_checkout_closes_as_recovered_once(self):
        update = AsyncMock()
        cart = {"checkout_id": "9001", "status": "aberto", "steps_done": 1, "last_touch_at": "2026-11-10T13:00:00Z"}
        with patch.object(cr, "sb_select", AsyncMock(return_value=[cart])), patch.object(cr, "sb_update", update), \
             patch.object(cr, "get_settings", AsyncMock(return_value=SETTINGS)):
            out = await cr.on_order("roove", {"id": 555, "checkout_token": "tok1", "total_price": "389.70", "created_at": "2026-11-11T09:00:00Z"})
        self.assertEqual(out["status"], "recuperado")
        patch_sent = update.await_args.kwargs["patch"]
        self.assertEqual((patch_sent["recovered_value"], patch_sent["recovered_order_id"], patch_sent["contact_enc"]), (389.7, "555", None))
        with patch.object(cr, "sb_select", AsyncMock(return_value=[{**cart, "status": "recuperado"}])):
            self.assertEqual(await cr.on_order("roove", {"id": 556, "checkout_token": "tok1"}), {"ignored": True})


class AdvanceTests(unittest.IsolatedAsyncioTestCase):
    def cart(self, **extra):
        with patch.dict(os.environ, ENV):
            data = cr.minimize(CHECKOUT)
        created = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        return {"client_id": "roove", "checkout_id": "9001", "created_at_shop": created, "value": 389.7, "items": data["line_items"],
                "recovery_url": data["abandoned_checkout_url"], "email_hash": data["email_hash"], "phone_key": data["phone_key"],
                "contact_enc": data["contact_enc"], "accepts_marketing": True, "steps_done": 0, "last_touch_at": None, **extra}

    async def run_advance(self, cart, settings=SETTINGS, bought=None, send=("re_1",), talked=False):
        upsert, update = AsyncMock(), AsyncMock()
        send_batch = AsyncMock(return_value=list(send))
        with patch.dict(os.environ, ENV), patch.object(cr, "sb_upsert", upsert), patch.object(cr, "sb_update", update), \
             patch.object(cr, "_bought_since", AsyncMock(return_value=bought)), patch.object(cr, "_talked_on_whatsapp", AsyncMock(return_value=talked)), \
             patch.object(em, "get_settings", AsyncMock(return_value={"from_name": "Roove", "from_email": "oi@roove.com.br"})), \
             patch.object(em, "suppressed", AsyncMock(return_value=set())), patch.object(em, "_insert_ignore", AsyncMock()), \
             patch.object(er, "send_batch", send_batch):
            status = await cr._advance("roove", cart, settings)
        return status, upsert, update, send_batch

    async def test_first_step_sends_email_with_cart_link_and_schedules_next(self):
        status, upsert, update, send_batch = await self.run_advance(self.cart())
        self.assertEqual(status, "enviado")
        msg = send_batch.await_args.args[0][0]
        self.assertEqual(msg["to"], ["ana@mail.com"])
        self.assertIn("recover?key=x", msg["html"])
        self.assertIn("Legging Move", msg["html"])
        self.assertEqual(send_batch.await_args.kwargs["idem"], "carrinho/9001/0")
        touch = upsert.await_args.args[1][0]
        self.assertEqual((touch["channel"], touch["status"], touch["step"]), ("email", "enviado", 0))
        patch_sent = update.await_args.kwargs["patch"]
        self.assertEqual(patch_sent["steps_done"], 1)
        self.assertIn("last_touch_at", patch_sent)

    async def test_who_already_bought_gets_nothing(self):
        bought = {"shopify_order_id": "777", "total_price": "100", "created_at_shopify": datetime.now(timezone.utc).isoformat()}
        status, upsert, update, send_batch = await self.run_advance(self.cart(), bought=bought)
        self.assertEqual(status, "comprou_sem_contato")
        send_batch.assert_not_awaited()
        upsert.assert_not_awaited()

    async def test_whatsapp_without_consent_is_skipped_but_sequence_moves(self):
        settings = {**SETTINGS, "steps": [{"channel": "whatsapp", "delay_minutes": 60}]}
        status, upsert, update, _ = await self.run_advance(self.cart(accepts_marketing=False), settings=settings)
        self.assertEqual(status, "pulado")
        self.assertEqual(upsert.await_args.args[1][0]["reason"], "sem consentimento de marketing")
        self.assertNotIn("last_touch_at", update.await_args.kwargs["patch"])

    async def test_whatsapp_known_contact_rule_and_simulation(self):
        settings = {**SETTINGS, "steps": [{"channel": "whatsapp", "delay_minutes": 60}], "whatsapp_consent": "consentimento_ou_conversa"}
        with patch.dict(os.environ, {"WHATSAPP_MARKETING_SEND_ENABLED": ""}):
            status, upsert, _, _ = await self.run_advance(self.cart(accepts_marketing=False), settings=settings, talked=True)
        self.assertEqual(status, "simulado")

    async def test_email_only_with_consent_when_brand_chose_so(self):
        settings = {**SETTINGS, "email_consent": "consentimento"}
        status, _, _, send_batch = await self.run_advance(self.cart(accepts_marketing=False), settings=settings)
        self.assertEqual(status, "pulado")
        send_batch.assert_not_awaited()

    async def test_sequence_done_expires_and_wipes_contact(self):
        status, _, update, _ = await self.run_advance(self.cart(steps_done=2))
        self.assertEqual(status, "expirado")
        self.assertIsNone(update.await_args.kwargs["patch"]["contact_enc"])


class SummaryTests(unittest.TestCase):
    def test_recovered_value_counts_once_and_rate_uses_contacted(self):
        carts = [{"status": "recuperado", "value": 300, "steps_done": 1, "recovered_value": 280},
                 {"status": "aberto", "value": 100, "steps_done": 1},
                 {"status": "expirado", "value": 50, "steps_done": 2},
                 {"status": "comprou_sem_contato", "value": 70, "steps_done": 0}]
        touches = [{"channel": "email", "status": "enviado"}, {"channel": "whatsapp", "status": "pulado"}]
        s = cr.summarize(carts, touches)
        self.assertEqual((s["carts"], s["abandoned_value"], s["recovered"], s["recovered_value"], s["recovery_rate"]), (3, 450.0, 1, 280.0, 33.3))
        self.assertEqual(s["bought_without_contact"], 1)
        self.assertEqual(s["by_channel"]["whatsapp"]["pulado"], 1)


if __name__ == "__main__":
    unittest.main()
