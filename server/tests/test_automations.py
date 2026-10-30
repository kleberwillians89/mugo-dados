import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI

from services import automations as au

DEF = {"key": "ajuste_concluido", "template_name": "mugo_ajuste_concluido", "language": "pt_BR", "owner": "dados",
       "audience": "cliente", "expected_category": "UTILITY", "automation_enabled": True, "variable_map": ["nome", "marca", "titulo"],
       "recipients": {"receives": "conteudo"}}
TEMPLATE = {"name": "mugo_ajuste_concluido", "language": "pt_BR", "status": "APPROVED", "category": "UTILITY", "body_param_count": 3,
            "header_format": None, "button_url_dynamic": False,
            "components": [{"type": "BODY", "text": "Olá, {{1}}! Os ajustes da {{2}} em {{3}} estão prontos."}]}
ROW = {"id": "r1", "automation_key": "ajuste_concluido", "template_name": "mugo_ajuste_concluido", "language": "pt_BR",
       "client_id": "cura", "audience": "cliente", "recipient_phone": "5511999990000", "params": {"nome": "Ana", "marca": "Curavino", "titulo": "Reels"},
       "idempotency_key": "auto-abc", "attempts": 0, "button_suffix": None}
CONTACT = {"id": "k1", "client_id": "cura", "name": "Ana Souza", "phone": "5511999990000"}


class ParseTests(unittest.TestCase):
    def test_parse_meta_components(self):
        parsed = au.parse_template({"name": "mugo_convite_resumo", "language": "pt_BR", "status": "approved", "category": "UTILITY",
                                    "components": [{"type": "BODY", "text": "Olá, {{1}}! Resumo da {{2}} de {{3}}. {{1}}"},
                                                   {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Resumo semanal"},
                                                                                   {"type": "QUICK_REPLY", "text": "Agora não"},
                                                                                   {"type": "URL", "url": "https://x/aprovar/{{1}}"}]}]})
        self.assertEqual(parsed["status"], "APPROVED")
        self.assertEqual(parsed["body_param_count"], 3)
        self.assertTrue(parsed["button_url_dynamic"])
        self.assertEqual(parsed["quick_replies"], ["Resumo semanal", "Agora não"])

    def test_render_and_components(self):
        self.assertEqual(au.render_text(TEMPLATE, ["Ana", "Curavino", "Reels"]), "Olá, Ana! Os ajustes da Curavino em Reels estão prontos.")
        with self.assertRaises(au.AutomationError):
            au.build_components({**TEMPLATE, "button_url_dynamic": True}, ["a", "b", "c"], None)
        with self.assertRaises(au.AutomationError):
            au.build_components({**TEMPLATE, "header_format": "IMAGE"}, ["a", "b", "c"], None)


class ReadinessTests(unittest.TestCase):
    def state(self, definition=DEF, template=TEMPLATE, send=False, mugozap=True):
        with patch.dict(os.environ, {"AUTOMATIONS_SEND_ENABLED": "true" if send else ""}):
            return au.readiness(definition, template, mugozap_ready=mugozap, calendar_ready=True, catalog_ready=True)

    def test_four_states_are_separate(self):
        s = self.state()
        self.assertEqual((s["automation_enabled"], s["template_approved"], s["integration_configured"], s["operational"]), (True, True, True, False))
        self.assertTrue(s["simulated_only"])
        self.assertTrue(self.state(send=True)["operational"])

    def test_crm_owned_never_operational_here(self):
        s = self.state({**DEF, "owner": "crm"}, send=True)
        self.assertFalse(s["operational"])
        self.assertIn("CRM", s["problems"][0])

    def test_pending_template_and_variable_mismatch(self):
        self.assertFalse(self.state(template={**TEMPLATE, "status": "PENDING"}, send=True)["template_approved"])
        s = self.state(template={**TEMPLATE, "body_param_count": 2}, send=True)
        self.assertFalse(s["operational"])
        self.assertTrue(any("Variáveis" in p for p in s["problems"]))


class ValidateTests(unittest.IsolatedAsyncioTestCase):
    async def check(self, row=ROW, definition=DEF, template=TEMPLATE, prefs=None, team=()):
        async def select(table, **kwargs):
            return list(team) if table == au.TEAM else []
        with patch.object(au, "prefs_for", AsyncMock(return_value=prefs or {"opted_out": False, "marketing_opt_in": False})), \
             patch.object(au, "sb_select", AsyncMock(side_effect=select)):
            return await au.validate(row, definition, template)

    async def test_blocks(self):
        self.assertIsNone(await self.check())
        self.assertEqual(await self.check(template={**TEMPLATE, "status": "PENDING"}), "TEMPLATE_NOT_APPROVED")
        self.assertEqual(await self.check(template=None), "TEMPLATE_NOT_APPROVED")
        self.assertEqual(await self.check(definition={**DEF, "owner": "crm"}), "NOT_DADOS_OWNED")
        self.assertEqual(await self.check(definition={**DEF, "automation_enabled": False}), "AUTOMATION_DISABLED")
        self.assertEqual(await self.check(row={**ROW, "params": {**ROW["params"], "titulo": "—"}}), "DATA_MISSING")
        self.assertEqual(await self.check(prefs={"opted_out": True}), "RECIPIENT_OPTED_OUT")

    async def test_marketing_requires_opt_in(self):
        marketing = {**TEMPLATE, "category": "MARKETING"}
        self.assertEqual(await self.check(template=marketing), "MARKETING_CONSENT_REQUIRED")
        self.assertIsNone(await self.check(template=marketing, prefs={"opted_out": False, "marketing_opt_in": True}))

    async def test_team_only_messages_never_reach_non_team_phone(self):
        row = {**ROW, "audience": "equipe"}
        self.assertEqual(await self.check(row=row, definition={**DEF, "audience": "equipe"}), "TEAM_ONLY")
        self.assertIsNone(await self.check(row=row, definition={**DEF, "audience": "equipe"}, team=[{"phone": ROW["recipient_phone"]}]))


class EnqueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_event_same_key_and_tenant_guards(self):
        request = AsyncMock(return_value=[{"id": "o1"}])
        with patch.object(au, "_request", request):
            await au.enqueue(DEF, client_id="cura", recipient=CONTACT, params={"nome": "Ana", "marca": "C", "titulo": "R"},
                             source_type="calendar_item", source_id="i1", key_parts=("ajuste",))
            await au.enqueue(DEF, client_id="cura", recipient=CONTACT, params={"nome": "Ana", "marca": "C", "titulo": "Outro texto"},
                             source_type="calendar_item", source_id="i1", key_parts=("ajuste",))
        keys = [c.kwargs["json"][0]["idempotency_key"] for c in request.await_args_list]
        self.assertEqual(keys[0], keys[1])  # edição sem mudança relevante não gera outra mensagem
        self.assertIn("ignore-duplicates", request.await_args.kwargs["headers"]["Prefer"])
        with self.assertRaises(au.AutomationError) as ctx:
            await au.enqueue(DEF, client_id="outra", recipient=CONTACT, params={}, source_type="x", source_id="1")
        self.assertEqual(ctx.exception.code, "TENANT_MISMATCH")
        with self.assertRaises(au.AutomationError) as ctx:
            await au.enqueue({**DEF, "audience": "equipe"}, client_id="cura", recipient=CONTACT, params={}, source_type="x", source_id="1")
        self.assertEqual(ctx.exception.code, "TEAM_ONLY")
        with self.assertRaises(au.AutomationError):
            await au.enqueue({**DEF, "owner": "crm"}, client_id="cura", recipient=CONTACT, params={}, source_type="x", source_id="1")


class ProcessTests(unittest.IsolatedAsyncioTestCase):
    async def run_process(self, *, send, result=None, attempts=0):
        update = AsyncMock(return_value=[])
        mugozap = AsyncMock(return_value=result or {"ok": True, "provider_message_id": "wamid.X"})
        env = {"AUTOMATIONS_SEND_ENABLED": "true" if send else "", "MUGOZAP_FUNCTION_URL": "https://crm/f", "MUGOZAP_ANON_KEY": "a",
               "MUGOZAP_WORKER_KEY": "w", "MUGOZAP_TEAM_MEMBER_ID": "t"}
        with patch.dict(os.environ, env), patch.object(au, "sb_rpc", AsyncMock(return_value=[{**ROW, "attempts": attempts}])), \
             patch.object(au, "load_definitions", AsyncMock(return_value={"ajuste_concluido": DEF})), \
             patch.object(au, "load_catalog", AsyncMock(return_value={("mugo_ajuste_concluido", "pt_BR"): TEMPLATE})), \
             patch.object(au, "validate", AsyncMock(return_value=None)), patch.object(au, "sb_update", update), \
             patch("services.studio_messages.mugozap_send", mugozap):
            counts = await au.process_due()
        return counts, update, mugozap

    async def test_simulation_never_calls_whatsapp(self):
        counts, update, mugozap = await self.run_process(send=False)
        self.assertEqual(counts["simulado"], 1)
        mugozap.assert_not_awaited()
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "simulado")
        self.assertIn("claim_token", update.await_args.kwargs["filters"])  # só quem travou conclui

    async def test_real_send_uses_the_queue_key(self):
        counts, update, mugozap = await self.run_process(send=True)
        self.assertEqual(counts["enviado"], 1)
        self.assertEqual(mugozap.await_args.kwargs["idempotency_key"], "auto-abc")
        self.assertEqual(update.await_args.kwargs["patch"]["provider_message_id"], "wamid.X")

    async def test_transient_failure_retries_with_backoff_then_gives_up(self):
        counts, update, _ = await self.run_process(send=True, result={"ok": False, "code": "MUGOZAP_UNAVAILABLE"})
        self.assertEqual(counts["reagendado"], 1)
        self.assertEqual(update.await_args.kwargs["patch"]["status"], "agendado")
        self.assertIn("next_attempt_at", update.await_args.kwargs["patch"])
        counts, update, _ = await self.run_process(send=True, result={"ok": False, "code": "MUGOZAP_UNAVAILABLE"}, attempts=au.MAX_ATTEMPTS - 1)
        self.assertEqual(counts["falhou"], 1)

    async def test_definitive_failure_is_not_retried(self):
        counts, _, _ = await self.run_process(send=True, result={"ok": False, "code": "TEMPLATE_NOT_APPROVED"})
        self.assertEqual(counts["falhou"], 1)


class StatusTests(unittest.IsolatedAsyncioTestCase):
    async def apply(self, current, new):
        update = AsyncMock()
        with patch.object(au, "sb_select", AsyncMock(return_value=[{"id": "o1", "delivery_status": current}])), patch.object(au, "sb_update", update):
            result = await au.apply_status("wamid.X", new)
        return result, update

    async def test_status_never_regresses(self):
        result, update = await self.apply("read", "delivered")
        self.assertEqual(result["ignored"], "stale")
        update.assert_not_awaited()
        result, update = await self.apply("sent", "read")
        self.assertEqual(update.await_args.kwargs["patch"]["delivery_status"], "read")


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_mirrors_meta_and_removes_missing(self):
        page = {"data": [{"name": "mugo_ajuste_concluido", "language": "pt_BR", "status": "APPROVED", "category": "UTILITY",
                          "components": TEMPLATE["components"]}]}
        upsert, delete = AsyncMock(), AsyncMock()
        with patch.dict(os.environ, {"WHATSAPP_WABA_ID": "123", "WHATSAPP_TEMPLATES_TOKEN": "t"}), \
             patch.object(httpx.AsyncClient, "get", AsyncMock(return_value=httpx.Response(200, json=page))), \
             patch.object(au, "sb_upsert", upsert), patch.object(au, "sb_delete", delete):
            result = await au.sync_catalog()
        self.assertEqual(result["approved"], 1)
        self.assertEqual(upsert.await_args.args[1][0]["body_param_count"], 3)
        self.assertTrue(delete.await_args.kwargs["filters"]["synced_at"].startswith("lt."))

    async def test_sync_requires_config(self):
        with patch.dict(os.environ, {"WHATSAPP_WABA_ID": "", "WHATSAPP_TEMPLATES_TOKEN": ""}):
            with self.assertRaises(au.AutomationError):
                await au.sync_catalog()


class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from routes import automations as routes, hooks
        self.routes, self.hooks = routes, hooks
        app = FastAPI()
        app.include_router(routes.router)
        app.include_router(routes.client_router)
        app.include_router(hooks.router)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_central_is_agency_only(self):
        with patch.object(self.routes, "require_user_id", AsyncMock(return_value="u")), \
             patch.object(self.routes, "is_agency_user", AsyncMock(return_value=False)):
            for method, url in [("GET", "/api/automations"), ("GET", "/api/automations/outbox"), ("POST", "/api/automations/process")]:
                response = await self.client.request(method, url)
                self.assertEqual(response.status_code, 403, url)

    async def test_outbox_masks_phone(self):
        rows = [{**ROW, "recipient_phone": "5511999990000"}]
        with patch.object(self.routes, "require_user_id", AsyncMock(return_value="u")), \
             patch.object(self.routes, "is_agency_user", AsyncMock(return_value=True)), \
             patch.object(self.routes, "sb_select", AsyncMock(return_value=rows)):
            response = await self.client.get("/api/automations/outbox")
        self.assertNotIn("5511999990000", response.text)

    async def test_crm_owned_settings_cannot_be_changed_here(self):
        with patch.object(self.routes, "require_user_id", AsyncMock(return_value="u")), \
             patch.object(self.routes, "is_agency_user", AsyncMock(return_value=True)), \
             patch.object(au, "load_definitions", AsyncMock(return_value={"pagamento_confirmado": {**DEF, "owner": "crm"}})):
            response = await self.client.patch("/api/automations/pagamento_confirmado", json={"lead_minutes": 10})
        self.assertEqual(response.status_code, 409)

    async def test_client_meetings_are_scoped_to_the_company(self):
        meetings = AsyncMock(return_value=[])
        with patch.object(self.routes, "require_client_read", AsyncMock(return_value="cura")), \
             patch("services.google_calendar.meetings", meetings):
            response = await self.client.get("/api/clients/cura/meetings", params={"start": "2026-11-01", "end": "2026-11-30"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(meetings.await_args.kwargs["client_id"], "cura")

    async def test_status_hook_requires_key_and_updates(self):
        apply = AsyncMock(return_value={"ok": True, "status": "delivered"})
        body = {"type": "message_status", "status": {"provider_message_id": "wamid.X", "status": "delivered"}}
        with patch.dict(os.environ, {"CRM_OPS_API_KEY": "k"}), patch.object(self.hooks, "apply_status", apply):
            self.assertEqual((await self.client.post("/api/hooks/crm", json=body)).status_code, 401)
            response = await self.client.post("/api/hooks/crm", json=body, headers={"X-Dados-Ops-Key": "k"})
        self.assertEqual(response.json()["status"], "delivered")
        apply.assert_awaited_once_with("wamid.X", "delivered", None)


if __name__ == "__main__":
    with redirect_stdout(io.StringIO()):
        unittest.main()
