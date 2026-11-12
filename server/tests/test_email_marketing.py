"""E-mail marketing: HTML seguro, públicos, descadastro, fila idempotente e webhook do Resend (Svix)."""
import base64
import hashlib
import hmac
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import email_builder as eb
from services import email_marketing as em
from services import email_resend as er

ENV = {"TOKEN_ENCRYPTION_KEY": "teste-chave", "API_PUBLIC_URL": "https://api.exemplo.com"}


class BuilderTests(unittest.TestCase):
    def test_text_is_escaped_and_variables_filled(self):
        design = {"blocks": [{"type": "titulo", "text": "Oi {{primeiro_nome}} <script>x</script>"},
                             {"type": "botao", "label": "Comprar", "href": "{{link_carrinho}}"}]}
        html, text = eb.render(design, {"from_name": "Roove"}, {"primeiro_nome": "Ana <b>", "link_carrinho": "https://loja.com/c?a=1&b=2"})
        self.assertIn("Oi Ana &lt;b&gt; &lt;script&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertIn('href="https://loja.com/c?a=1&amp;b=2"', html)
        self.assertIn("Comprar (https://loja.com/c?a=1&b=2)", text)

    def test_unsafe_links_and_unknown_blocks_are_dropped(self):
        design = {"blocks": [{"type": "botao", "label": "x", "href": "javascript:alert(1)"}, {"type": "html", "text": "<b>"},
                             {"type": "imagem", "url": "data:image/png;base64,xx"}]}
        html, _ = eb.render(design, {}, {})
        self.assertNotIn("javascript:", html)
        self.assertNotIn("data:image", html)
        self.assertEqual(eb.normalize_design(design)["blocks"][1:], [{"type": "imagem", "url": "data:image/png;base64,xx"}])

    def test_footer_always_has_unsubscribe_and_custom_html_is_cleaned(self):
        html, _ = eb.render({"blocks": []}, {"from_name": "Ruah"}, {"descadastro": "https://api.exemplo.com/u?t=1"})
        self.assertIn("Não quero mais receber", html)
        custom, _ = eb.render(None, {}, {"descadastro": "https://u", "primeiro_nome": "Bia"},
                              custom_html='<p onclick="x()">Oi {{primeiro_nome}}</p><script>alert(1)</script>')
        self.assertNotIn("onclick", custom)
        self.assertNotIn("<script", custom)
        self.assertIn("Oi Bia", custom)
        self.assertIn("Não quero mais receber", custom)

    def test_cart_items_render_with_brazilian_price(self):
        html, _ = eb.render({"blocks": [{"type": "produtos"}]}, {}, {}, items=[{"title": "Legging", "quantity": 2, "price": 1189.9}])
        self.assertIn("2 × R$ 1.189,90", html)


class CustomHtmlTests(unittest.TestCase):
    EXPORT = ('<!DOCTYPE html><html><head><style>.x{color:#111}</style></head><body><table><tr><td>'
              'Oi *|FNAME|* <a href="javascript:steal()">x</a><img src="https://cdn/x.png" onerror="y()">'
              '<form action="https://evil"><input></form>{{produtos}}</td></tr></table></body></html>')

    def test_full_export_keeps_head_and_gets_preheader_and_footer(self):
        html, text = eb.render(None, {"from_name": "Roove"}, {"primeiro_nome": "Ana", "descadastro": "https://u/1"},
                               preheader="Só hoje", custom_html=self.EXPORT, items=[{"title": "Legging", "quantity": 1, "price": 10}])
        self.assertIn("<style>.x{color:#111}</style>", html)
        self.assertIn("Oi Ana", html)
        self.assertRegex(html, r"<body><div style=\"display:none[^>]*>Só hoje</div>")
        self.assertIn('href="#"', html)
        for bad in ("javascript:", "onerror", "<form", "*|FNAME|*"):
            self.assertNotIn(bad, html)
        self.assertIn("Legging", html)
        self.assertLess(html.index("Não quero mais receber"), html.index("</body>"))
        self.assertNotIn(".x{color", text)

    def test_own_unsubscribe_link_is_respected(self):
        html, _ = eb.render(None, {}, {"descadastro": "https://u/1"}, custom_html='<p><a href="*|UNSUB|*">Sair</a></p>')
        self.assertIn('href="https://u/1">Sair', html)
        self.assertNotIn("Não quero mais receber", html)

    def test_report(self):
        report = eb.html_report(self.EXPORT)
        self.assertTrue(report["full_document"])
        self.assertTrue(report["removed_unsafe"])
        self.assertEqual(report["variables"], ["primeiro_nome", "produtos"])
        self.assertFalse(report["has_unsubscribe"])
        self.assertTrue(eb.html_report("<p>" + "a" * 110_000 + "</p>")["gmail_clip"])


def contact(h, consent=True, orders=1, last="2026-11-01T10:00:00Z"):
    return {"email": f"{h}@x.com", "hash": h * 32 if len(h) == 1 else h, "first_name": "A", "name": "A", "consent": consent,
            "orders": orders, "last_order_at": last}


class AudienceTests(unittest.TestCase):
    NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)

    def pick(self, audience, contacts, blocked=frozenset()):
        return [c["hash"][0] for c in em.select_audience(contacts, audience, blocked=set(blocked), now=self.NOW)]

    def test_consent_segment_skips_without_consent_and_blocked(self):
        cs = [contact("a"), contact("b", consent=False), contact("c", consent=None), contact("d")]
        self.assertEqual(self.pick({"segment": "consentimento"}, cs, {"d" * 32}), ["a"])

    def test_todos_without_consent_filter(self):
        cs = [contact("a"), contact("b", consent=False)]
        self.assertEqual(self.pick({"segment": "todos"}, cs), ["a", "b"])

    def test_bought_recently_inactive_and_repeat(self):
        cs = [contact("a", last="2026-11-01T00:00:00Z"), contact("b", last="2026-05-01T00:00:00Z"),
              contact("c", last=None), contact("d", orders=3, last="2026-01-01T00:00:00Z")]
        self.assertEqual(self.pick({"segment": "compraram", "days": 30}, cs), ["a"])
        self.assertEqual(self.pick({"segment": "sem_compra", "days": 90}, cs), ["b", "d"])
        self.assertEqual(self.pick({"segment": "recompra"}, cs), ["d"])

    def test_clean_audience_bounds(self):
        self.assertEqual(em.clean_audience({"segment": "xx", "days": 99999}), {"segment": "consentimento", "days": 730, "only_consent": True})
        self.assertFalse(em.clean_audience({"segment": "todos"})["only_consent"])


class UnsubscribeTests(unittest.TestCase):
    def test_token_round_trip_and_tamper(self):
        with patch.dict(os.environ, ENV):
            token = em.unsubscribe_token("roove", "a" * 32)
            self.assertEqual(em.parse_unsubscribe_token(token), ("roove", "a" * 32))
            forged = base64.urlsafe_b64encode(f"ruah|{'a' * 32}|{'0' * 24}".encode()).decode()
            self.assertIsNone(em.parse_unsubscribe_token(forged))
            self.assertIsNone(em.parse_unsubscribe_token("lixo"))
            self.assertTrue(em.unsubscribe_url("roove", "a" * 32).startswith("https://api.exemplo.com/api/email/unsubscribe?t="))

    def test_public_url_falls_back_to_shopify_webhook_origin(self):
        with patch.dict(os.environ, {"API_PUBLIC_URL": "", "SHOPIFY_WEBHOOK_URL": "https://api.dados.mugo.com/api/webhooks/shopify"}):
            self.assertEqual(er.public_api_url(), "https://api.dados.mugo.com")


class SettingsTests(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(em.clean_settings({"from_email": "Oi@Roove.com.br", "brand_color": "#112233"}),
                         {"from_email": "oi@roove.com.br", "brand_color": "#112233"})
        for bad in ({"from_email": "nada"}, {"brand_color": "azul"}, {"logo_url": "http://x"}):
            with self.assertRaises(em.EmailError):
                em.clean_settings(bad)

    def test_sender_requires_email_and_strips_header_chars(self):
        self.assertEqual(em.sender({"from_name": 'Roo<ve>"\n', "from_email": "oi@roove.com.br"}), "Roove <oi@roove.com.br>")
        with self.assertRaises(em.EmailError):
            em.sender({"from_name": "x"})


class StatsTests(unittest.TestCase):
    def test_summary_rates_use_delivered(self):
        rows = [{"status": "entregue", "opened_at": "t", "clicked_at": "t"}, {"status": "entregue", "opened_at": "t", "clicked_at": None},
                {"status": "entregue", "opened_at": None, "clicked_at": None}, {"status": "bounce", "opened_at": None, "clicked_at": None},
                {"status": "na_fila", "opened_at": None, "clicked_at": None}]
        s = em.summarize_sends(rows)
        self.assertEqual((s["sent"], s["delivered"], s["queued"], s["bounced"]), (4, 3, 1, 1))
        self.assertEqual((s["open_rate"], s["click_rate"]), (66.7, 33.3))


class WebhookTests(unittest.IsolatedAsyncioTestCase):
    def sign(self, body: bytes, secret_raw: bytes, ts: int):
        sig = base64.b64encode(hmac.new(secret_raw, f"msg_1.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
        return {"svix-id": "msg_1", "svix-timestamp": str(ts), "svix-signature": f"v1,xxx v1,{sig}"}

    def test_svix_signature(self):
        raw = b"segredo-de-teste"
        secret = "whsec_" + base64.b64encode(raw).decode()
        body = b'{"type":"email.opened"}'
        with patch.dict(os.environ, {"RESEND_WEBHOOK_SECRET": secret}):
            headers = self.sign(body, raw, 1_700_000_000)
            self.assertTrue(er.verify_webhook(body, headers, now=1_700_000_100))
            self.assertFalse(er.verify_webhook(body + b" ", headers, now=1_700_000_100))
            self.assertFalse(er.verify_webhook(body, headers, now=1_700_001_000))  # mais de 5 min

    async def test_bounce_updates_send_and_suppresses(self):
        update, upsert = AsyncMock(), AsyncMock()
        row = {"id": "s1", "client_id": "roove", "email_hash": "a" * 32, "status": "enviado", "opened_at": None, "clicked_at": None}
        with patch.object(em, "sb_select", AsyncMock(return_value=[row])), patch.object(em, "sb_update", update), patch.object(em, "sb_upsert", upsert):
            out = await em.handle_event({"type": "email.bounced", "data": {"email_id": "re_1", "bounce": {"type": "Permanent"}}})
        self.assertEqual(out["status"], "bounce")
        self.assertEqual(upsert.await_args.args[1][0]["reason"], "bounce")

    async def test_click_sets_open_and_click_once(self):
        update = AsyncMock()
        row = {"id": "s1", "client_id": "roove", "email_hash": "a" * 32, "status": "entregue", "opened_at": None, "clicked_at": None}
        with patch.object(em, "sb_select", AsyncMock(return_value=[row])), patch.object(em, "sb_update", update):
            await em.handle_event({"type": "email.clicked", "created_at": "2026-11-11T10:00:00Z", "data": {"email_id": "re_1"}})
        patch_sent = update.await_args.kwargs["patch"]
        self.assertEqual((patch_sent["opened_at"], patch_sent["clicked_at"]), ("2026-11-11T10:00:00Z", "2026-11-11T10:00:00Z"))
        self.assertNotIn("status", patch_sent)

    async def test_unknown_email_is_ignored(self):
        with patch.object(em, "sb_select", AsyncMock(return_value=[])):
            self.assertEqual(await em.handle_event({"type": "email.opened", "data": {"email_id": "x"}}), {"ignored": True})


class CampaignSendTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduled_campaign_queues_audience_sends_and_finishes(self):
        campaign = {"id": "c1", "client_id": "roove", "status": "agendada", "name": "Black", "subject": "Oi {{primeiro_nome}}", "preheader": "",
                    "design": {"blocks": [{"type": "texto", "text": "Promo"}]}, "custom_html": None, "audience": {"segment": "consentimento"}}
        contacts = [contact("a"), contact("b", consent=False), contact("c")]
        queued = []

        async def insert_ignore(rows):
            queued.extend(rows)

        sends_pending = [{"id": f"id{i}", "client_id": "roove", "kind": "campanha", "campaign_id": "c1", "email_hash": r["email_hash"],
                          "idem_key": r["idem_key"]} for i, r in enumerate([{"email_hash": "a" * 32, "idem_key": "k1"}, {"email_hash": "c" * 32, "idem_key": "k2"}])]
        select = AsyncMock(side_effect=[sends_pending, []])
        send_batch = AsyncMock(return_value=["re_1", "re_2"])
        upsert, update = AsyncMock(), AsyncMock()
        with patch.dict(os.environ, ENV), \
             patch.object(em, "get_settings", AsyncMock(return_value={"from_name": "Roove", "from_email": "oi@roove.com.br"})), \
             patch.object(em, "load_contacts", AsyncMock(return_value=("shopify", contacts))), \
             patch.object(em, "suppressed", AsyncMock(return_value=set())), patch.object(em, "_insert_ignore", side_effect=insert_ignore), \
             patch.object(em, "sb_select", select), patch.object(em, "sb_upsert", upsert), patch.object(em, "sb_update", update), \
             patch.object(em, "campaign_stats", AsyncMock(return_value={"sent": 2})), patch.object(er, "send_batch", send_batch):
            out = await em._process_campaign(campaign, "roove")
        self.assertEqual([r["idem_key"] for r in queued], [f"campanha/c1/{'a' * 32}", f"campanha/c1/{'c' * 32}"])
        self.assertEqual(out["sent"], 2)
        messages = send_batch.await_args.args[0]
        self.assertEqual(messages[0]["to"], ["a@x.com"])
        self.assertEqual(messages[0]["subject"], "Oi A")
        self.assertIn("List-Unsubscribe", messages[0]["headers"])
        self.assertEqual([r["status"] for r in upsert.await_args.args[1]], ["enviado", "enviado"])
        self.assertEqual(update.await_args_list[-1].kwargs["patch"]["status"], "enviada")

    async def test_retryable_error_keeps_queue_for_next_run(self):
        campaign = {"id": "c1", "client_id": "roove", "status": "enviando", "name": "x", "subject": "x", "design": {"blocks": []}, "audience": {}}
        pending = [{"id": "id1", "client_id": "roove", "kind": "campanha", "campaign_id": "c1", "email_hash": "a" * 32, "idem_key": "k"}]
        upsert, update = AsyncMock(), AsyncMock()
        with patch.dict(os.environ, ENV), \
             patch.object(em, "get_settings", AsyncMock(return_value={"from_email": "oi@roove.com.br"})), \
             patch.object(em, "load_contacts", AsyncMock(return_value=("shopify", [contact("a")]))), \
             patch.object(em, "suppressed", AsyncMock(return_value=set())), \
             patch.object(em, "sb_select", AsyncMock(side_effect=[pending, [{"id": "id1"}]])), patch.object(em, "sb_upsert", upsert), \
             patch.object(em, "sb_update", update), \
             patch.object(er, "send_batch", AsyncMock(side_effect=er.ResendError("HTTP_503", "x", retryable=True))):
            out = await em._process_campaign(campaign, "roove")
        self.assertEqual(out["sent"], 0)
        upsert.assert_not_awaited()
        update.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
