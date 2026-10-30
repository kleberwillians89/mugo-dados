from __future__ import annotations

import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import studio_approvals as sa
from services import studio_messages as sm
from services.studio_calendar import StudioError

DOCS = Path(__file__).resolve().parents[2] / "docs" / "WHATSAPP_TEMPLATES.md"
CONTACT = {"id": "c1", "name": "Ana Souza", "phone": "5511988887777", "role": "Marketing", "receives": ["conteudo", "trafego"], "is_primary": True}
MUGOZAP_ENV = {"MUGOZAP_FUNCTION_URL": "https://crm.supabase.co/functions/v1/mugozap-api", "MUGOZAP_ANON_KEY": "anon",
               "MUGOZAP_WORKER_KEY": "wk", "MUGOZAP_TEAM_MEMBER_ID": "tm1"}
FUTURE = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()


class TemplateContractTests(unittest.TestCase):
    def test_every_template_is_documented_verbatim_for_meta(self):
        doc = DOCS.read_text(encoding="utf-8")
        for name, template in sm.TEMPLATES.items():
            with self.subTest(template=name):
                self.assertIn(f"`{name}`", doc)
                self.assertIn(template["body"], doc)

    def test_meta_rules_variables_numbered_not_at_edges_not_adjacent(self):
        for name, template in sm.TEMPLATES.items():
            with self.subTest(template=name):
                body = template["body"]
                numbers = [int(n) for n in re.findall(r"\{\{(\d+)\}\}", body)]
                self.assertEqual(numbers, list(range(1, len(template["params"]) + 1)))
                self.assertFalse(body.startswith("{{") or body.rstrip(".?!").endswith("}}"))
                self.assertNotRegex(body, r"\}\}\s*\{\{")

    def test_params_are_meta_safe(self):
        self.assertEqual(sm.param("a\n\tb    c"), "a b c")
        self.assertEqual(sm.param(""), "—")
        self.assertEqual(sm.brl(1234.5), "R$ 1.234,50")
        self.assertEqual(sm.pct(12.345), "+12,3%")
        self.assertEqual(sm.mask_phone("5511988887777"), "5511…7777")

    def test_components_follow_crm_contract(self):
        params = {k: "x" for k in sm.TEMPLATES["mugo_conteudo_aprovacao_arte"]["params"]}
        comps = sm.components_for("mugo_conteudo_aprovacao_arte", params, button_suffix="tok", header_image="https://sb/a.png")
        self.assertEqual([c["type"] for c in comps], ["header", "body", "button"])
        self.assertEqual(comps[0]["parameters"][0], {"type": "image", "image": {"link": "https://sb/a.png"}})
        self.assertEqual(comps[2], {"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": "tok"}]})
        with self.assertRaises(StudioError):
            sm.components_for("mugo_conteudo_aprovacao_arte", params, button_suffix="tok", header_image=None)


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_without_mugozap_it_refuses_instead_of_opening_wa_link(self):
        # Número da Mugô é só API: sem MugôZap configurado, recusa e diz o que falta (nada é registrado como enviado).
        params = {"nome": "Ana", "marca": "Ruah", "semana": "10/11 a 16/11", "quantidade": "4", "destaque": "Reels"}
        with patch.dict("os.environ", {**{k: "" for k in MUGOZAP_ENV}, "MUGOZAP_ALLOW_WA_LINK": ""}), patch.object(sm, "sb_insert", AsyncMock()) as insert:
            with self.assertRaises(sm.StudioError) as err:
                await sm.deliver("roove", contact=CONTACT, template_name="mugo_agenda_semana", params=params, button_suffix=None,
                                 header_image=None, request_id=None, user_id="u1", key="dados-" + "a" * 40)
        self.assertEqual(err.exception.code, "MUGOZAP_NOT_CONFIGURED")
        insert.assert_not_awaited()
        with patch.dict("os.environ", {k: "" for k in MUGOZAP_ENV}):
            self.assertEqual(sm.mugozap_missing(), list(sm.MUGOZAP_ENV))
            self.assertEqual(sm.whatsapp_channel(), "nao_configurado")

    async def test_wa_link_only_when_explicitly_allowed(self):
        params = {"nome": "Ana", "marca": "Ruah", "semana": "10/11 a 16/11", "quantidade": "4", "destaque": "Reels"}
        with patch.dict("os.environ", {**{k: "" for k in MUGOZAP_ENV}, "MUGOZAP_ALLOW_WA_LINK": "true"}), patch.object(sm, "sb_insert", AsyncMock()) as insert:
            out = await sm.deliver("roove", contact=CONTACT, template_name="mugo_agenda_semana", params=params, button_suffix=None,
                                   header_image=None, request_id=None, user_id="u1", key="dados-" + "a" * 40)
        self.assertEqual(out["status"], "link_gerado")
        self.assertTrue(out["whatsapp_url"].startswith("https://wa.me/5511988887777?text=Ol%C3%A1%2C%20Ana"))
        row = insert.await_args.args[1]
        self.assertEqual((row["channel"], row["status"], row["phone_masked"]), ("wa_link", "link_gerado", "5511…7777"))
        self.assertNotIn("5511988887777", str(row))

    async def test_mugozap_call_uses_internal_worker_path(self):
        class Resp:
            status_code = 200
            content = b"{}"
            def json(self):
                return {"ok": True, "data": {"provider_message_id": "wamid.1"}}
        client = AsyncMock()
        client.post = AsyncMock(return_value=Resp())
        client.__aenter__.return_value = client
        params = {k: "v" for k in sm.TEMPLATES["mugo_lembrete_aprovacao"]["params"]}
        with patch.dict("os.environ", MUGOZAP_ENV), patch.object(sm.httpx, "AsyncClient", return_value=client), \
             patch.object(sm, "sb_select", AsyncMock(return_value=[])), patch.object(sm, "sb_insert", AsyncMock()) as insert:
            out = await sm.deliver("roove", contact=CONTACT, template_name="mugo_lembrete_aprovacao", params=params,
                                   button_suffix="tok", header_image=None, request_id="r1", user_id="u1", key="dados-" + "b" * 40)
        call = client.post.await_args
        self.assertEqual(call.kwargs["headers"]["X-Task-Command-Worker-Key"], "wk")
        body = call.kwargs["json"]
        self.assertEqual(body["operation"], "send_template_message")
        self.assertEqual(body["payload"]["team_member_id"], "tm1")
        self.assertEqual(body["payload"]["language"], "pt_BR")
        self.assertEqual(body["payload"]["idempotency_key"], "dados-" + "b" * 40)
        self.assertEqual(out["status"], "enviado")
        self.assertEqual(insert.await_args.args[1]["provider_message_id"], "wamid.1")

    async def test_already_sent_is_never_resent(self):
        with patch.dict("os.environ", MUGOZAP_ENV), patch.object(sm, "sb_select", AsyncMock(return_value=[{"status": "enviado"}])), \
             patch.object(sm, "mugozap_send", AsyncMock()) as send:
            out = await sm.deliver("roove", contact=CONTACT, template_name="mugo_agenda_semana", params={}, button_suffix=None,
                                   header_image=None, request_id=None, user_id="u1", key="dados-" + "c" * 40)
        send.assert_not_awaited()
        self.assertTrue(out["already_sent"])

    async def test_crm_refusal_is_logged_and_translated(self):
        with patch.dict("os.environ", MUGOZAP_ENV), patch.object(sm, "sb_select", AsyncMock(return_value=[])), \
             patch.object(sm, "mugozap_send", AsyncMock(return_value={"ok": False, "code": "RECIPIENT_NOT_IN_CRM"})), \
             patch.object(sm, "sb_insert", AsyncMock()) as insert:
            with self.assertRaises(StudioError) as err:
                await sm.deliver("roove", contact=CONTACT, template_name="mugo_agenda_semana", params={}, button_suffix=None,
                                 header_image=None, request_id=None, user_id="u1", key="dados-" + "d" * 40)
        self.assertEqual(err.exception.code, "RECIPIENT_NOT_IN_CRM")
        self.assertEqual(insert.await_args.args[1]["status"], "falhou")


class BuildMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_reminder_reuses_same_link_and_counts_pending(self):
        from services import crypto
        crypto._fernet.cache_clear()
        with patch.dict("os.environ", {"TOKEN_ENCRYPTION_KEY": "chave-de-teste-" + "k" * 32}):
            cipher = crypto.encrypt_secret("TOKEN" * 8)
            request = {"id": "r1", "month": "2026-11-01", "item_ids": ["i1", "i2", "i3"], "expires_at": FUTURE, "token_ciphertext": cipher}
            reads = AsyncMock(side_effect=[[request], [{"item_id": "i1"}]])
            with patch.object(sm, "list_contacts", AsyncMock(return_value=[CONTACT])), \
                 patch.object(sm, "_client_name", AsyncMock(return_value="Ruah")), patch.object(sm, "sb_select", reads):
                built = await sm.build_message("roove", "lembrete")
        self.assertEqual(built["template_name"], "mugo_lembrete_aprovacao")
        self.assertEqual(built["params"]["pendentes"], "2")
        self.assertEqual(built["_extra"]["button_suffix"], "TOKEN" * 8)
        self.assertNotIn("TOKEN", str(sm.public_preview(built)))
        crypto._fernet.cache_clear()

    async def test_traffic_numbers_come_from_data_and_ai_only_writes_the_highlight(self):
        snap = {"metrics": {"investment": {"value": 2350, "variation_percent": 10}, "revenue": {"value": 14820}, "roas": {"value": 6.306}},
                "campaigns": [{"name": "Remarketing Oud", "spend": 500, "revenue": 5000, "conversions": 20}]}
        sentence = AsyncMock(return_value="Remarketing Oud teve o melhor retorno")
        with patch.object(sm, "list_contacts", AsyncMock(return_value=[CONTACT])), \
             patch.object(sm, "_client_name", AsyncMock(return_value="Ruah")), \
             patch.object(sm, "_snapshot", AsyncMock(return_value=snap)), patch.object(sm, "_sentence", sentence):
            built = await sm.build_message("roove", "trafego", overrides={"destaque": "Texto editado pela equipe", "investimento": "R$ 1"})
        self.assertEqual(built["params"]["investimento"], "R$ 2.350,00")  # número não é editável
        self.assertEqual(built["params"]["receita"], "R$ 14.820,00")
        self.assertEqual(built["params"]["roas"], "R$ 6,31")
        self.assertEqual(built["params"]["destaque"], "Texto editado pela equipe")
        self.assertIn("Remarketing Oud", str(sentence.await_args.args[1]))

    async def test_contact_must_receive_that_kind(self):
        with patch.object(sm, "list_contacts", AsyncMock(return_value=[{**CONTACT, "receives": ["conteudo"]}])), \
             patch.object(sm, "_client_name", AsyncMock(return_value="Ruah")):
            with self.assertRaises(StudioError) as err:
                await sm.build_message("roove", "resultados")
        self.assertEqual(err.exception.code, "CONTACT_REQUIRED")


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_stages(self):
        items = [{"id": "a", "status": "rascunho"}, {"id": "b", "status": "em_revisao"}, {"id": "c", "status": "em_revisao"},
                 {"id": "d", "status": "rejeitado"}, {"id": "e", "status": "aprovado"}, {"id": "f", "status": "publicado"}]
        requests = [{"id": "r1", "item_ids": ["c"], "contact_name": "Ana", "status": "aberto", "expires_at": FUTURE,
                     "created_at": "2026-11-01", "last_reminded_at": None}]
        with patch("services.studio_calendar.list_items", AsyncMock(return_value=items)), \
             patch.object(sa, "sb_select", AsyncMock(side_effect=[requests, [{"item_id": "d", "action": "ajuste_solicitado", "comment": "trocar foto"}]])):
            out = await sa.pipeline("roove", "2026-11")
        stages = {i["id"]: i["stage"] for i in out["items"]}
        self.assertEqual(stages, {"a": "rascunho", "b": "revisao_interna", "c": "com_cliente", "d": "ajuste", "e": "aprovado", "f": "publicado"})
        self.assertEqual(out["items"][2]["request"]["request_id"], "r1")
        self.assertEqual(out["items"][3]["client_feedback"]["comment"], "trocar foto")
        self.assertEqual(sum(out["counts"].values()), 6)


if __name__ == "__main__":
    unittest.main()
