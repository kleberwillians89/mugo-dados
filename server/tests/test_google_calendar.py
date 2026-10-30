import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx

from services import automation_triggers as tr
from services import automations as au
from services import google_calendar as gc

TEAM = {"ana@mugo.com.br": {"id": "t1", "name": "Ana Lima", "email": "ana@mugo.com.br", "phone": "5511911110000", "receives_internal": True},
        "bia@mugo.com.br": {"id": "t2", "name": "Bia", "email": "bia@mugo.com.br", "phone": "5511922220000", "receives_internal": True}}
CONTACTS = {"nasser@curavino.com": {"id": "k1", "client_id": "cura", "name": "Nasser Silva", "phone": "5511933330000", "email": "nasser@curavino.com"},
            "joao@roove.com": {"id": "k2", "client_id": "roove", "name": "João", "phone": "5511944440000", "email": "joao@roove.com"}}
DEFS = {
    "reuniao_interna": {"key": "reuniao_interna", "template_name": "mugo_reuniao_interna", "owner": "dados", "audience": "equipe",
                        "automation_enabled": True, "lead_minutes": 1440, "variable_map": ["nome", "titulo", "data", "hora"]},
    "reuniao_lembrete": {"key": "reuniao_lembrete", "template_name": "mugo_reuniao_lembrete", "owner": "dados", "audience": "cliente",
                         "automation_enabled": True, "lead_minutes": 1440, "variable_map": ["nome", "marca", "titulo", "data", "hora"]},
    "agendamento_confirmado": {"key": "agendamento_confirmado", "template_name": "mugo_agendamento_confirmado", "owner": "dados",
                               "audience": "cliente", "automation_enabled": True, "variable_map": ["nome", "dia", "hora"]},
}


def attendee(email, response="needsAction"):
    return {"email": email, "response": response, "resource": False}


class ClassifyTests(unittest.TestCase):
    def test_internal_client_and_ambiguous(self):
        team = set(TEAM)
        self.assertEqual(gc.classify([attendee("ana@mugo.com.br"), attendee("bia@mugo.com.br")], team, CONTACTS), ("interna", None))
        self.assertEqual(gc.classify([attendee("ana@mugo.com.br"), attendee("nasser@curavino.com")], team, CONTACTS), ("cliente", "cura"))
        # contatos de duas empresas na mesma reunião: nenhuma recebe lembrete automático
        self.assertEqual(gc.classify([attendee("nasser@curavino.com"), attendee("joao@roove.com")], team, CONTACTS), ("outro", None))
        self.assertEqual(gc.classify([attendee("ana@mugo.com.br"), attendee("x@desconhecido.com")], team, CONTACTS), ("outro", None))

    def test_domain_counts_as_team(self):
        with patch.dict(os.environ, {"MUGO_EMAIL_DOMAIN": "mugo.com.br"}):
            self.assertEqual(gc.classify([attendee("ana@mugo.com.br"), attendee("novo@mugo.com.br")], {"ana@mugo.com.br"}, {}), ("interna", None))


class NormalizeTests(unittest.TestCase):
    def test_timezone_and_all_day(self):
        row = gc.normalize_event({"id": "e1", "status": "confirmed", "summary": "Kickoff",
                                  "start": {"dateTime": "2026-11-10T14:00:00-03:00", "timeZone": "America/Sao_Paulo"},
                                  "end": {"dateTime": "2026-11-10T15:00:00-03:00"},
                                  "attendees": [{"email": "Ana@Mugo.com.br", "responseStatus": "accepted"}]}, "cal")
        self.assertEqual(row["start_at"], "2026-11-10T17:00:00+00:00")
        self.assertEqual(row["attendees"][0]["email"], "ana@mugo.com.br")
        day = gc.normalize_event({"id": "e2", "start": {"date": "2026-11-11"}, "end": {"date": "2026-11-12"}}, "cal")
        self.assertTrue(day["all_day"])
        self.assertEqual(day["start_at"], "2026-11-11T03:00:00+00:00")


class ReminderTests(unittest.IsolatedAsyncioTestCase):
    async def schedule(self, event):
        enqueue = AsyncMock(return_value={"id": "o"})
        cancel = AsyncMock(return_value=0)
        with patch.object(au, "load_definitions", AsyncMock(return_value=DEFS)), patch.object(au, "enqueue", enqueue), \
             patch.object(au, "cancel_pending", cancel), patch.object(gc, "_client_brand", AsyncMock(return_value="Curavino")):
            result = await gc.schedule_reminders(event, CONTACTS, TEAM)
        return result, enqueue, cancel

    def event(self, kind, start, attendees, status="confirmed", client_id=None):
        return {"google_event_id": "e1", "status": status, "summary": "Planejamento", "start_at": start.isoformat(), "all_day": False,
                "kind": kind, "client_id": client_id, "attendees": attendees}

    async def test_internal_meeting_reminds_team_24h_before(self):
        start = datetime.now(timezone.utc) + timedelta(days=3)
        _, enqueue, cancel = await self.schedule(self.event("interna", start, [attendee("ana@mugo.com.br"), attendee("bia@mugo.com.br", "declined")]))
        self.assertEqual(enqueue.await_count, 1)  # quem recusou não recebe
        call = enqueue.await_args.kwargs
        self.assertTrue(call["recipient"]["team_member"])
        self.assertIsNone(call["client_id"])
        self.assertEqual(call["scheduled_for"], start - timedelta(minutes=1440))
        local = start.astimezone(gc.SAO_PAULO)
        self.assertEqual(call["params"]["hora"], local.strftime("%H:%M"))
        self.assertEqual(len(cancel.await_args.kwargs["keep_keys"]), 1)

    async def test_client_meeting_reminds_only_that_company_and_confirms_on_accept(self):
        start = datetime.now(timezone.utc) + timedelta(days=2)
        _, enqueue, _ = await self.schedule(self.event("cliente", start, [attendee("ana@mugo.com.br"), attendee("nasser@curavino.com", "accepted")],
                                                       client_id="cura"))
        keys = [c.kwargs["source_type"] for c in enqueue.await_args_list]
        self.assertEqual(sorted(keys), ["calendar_confirmation", "calendar_event"])
        for call in enqueue.await_args_list:
            self.assertEqual(call.kwargs["client_id"], "cura")
            self.assertEqual(call.kwargs["recipient"]["client_id"], "cura")

    async def test_reschedule_changes_key_and_cancels_old(self):
        start = datetime.now(timezone.utc) + timedelta(days=2)
        _, _, cancel_a = await self.schedule(self.event("interna", start, [attendee("ana@mugo.com.br"), attendee("bia@mugo.com.br")]))
        _, _, cancel_b = await self.schedule(self.event("interna", start + timedelta(hours=2), [attendee("ana@mugo.com.br"), attendee("bia@mugo.com.br")]))
        self.assertNotEqual(set(cancel_a.await_args.kwargs["keep_keys"]), set(cancel_b.await_args.kwargs["keep_keys"]))
        self.assertEqual(cancel_b.await_args.args, ("calendar_event", "e1"))

    async def test_cancelled_or_imminent_events(self):
        start = datetime.now(timezone.utc) + timedelta(days=2)
        _, enqueue, cancel = await self.schedule(self.event("interna", start, [attendee("ana@mugo.com.br")], status="cancelled"))
        enqueue.assert_not_awaited()
        self.assertEqual(cancel.await_args.kwargs["reason"], "evento cancelado")
        _, enqueue, _ = await self.schedule(self.event("interna", datetime.now(timezone.utc) + timedelta(minutes=30),
                                                       [attendee("ana@mugo.com.br"), attendee("bia@mugo.com.br")]))
        enqueue.assert_not_awaited()  # menos de 1h: sem lembrete

    async def test_late_booking_reminds_now(self):
        start = datetime.now(timezone.utc) + timedelta(hours=5)
        _, enqueue, _ = await self.schedule(self.event("interna", start, [attendee("ana@mugo.com.br"), attendee("bia@mugo.com.br")]))
        self.assertLess(enqueue.await_args.kwargs["scheduled_for"], start - timedelta(hours=4))


class SyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_expired_sync_token_triggers_full_resync(self):
        responses = [httpx.Response(410), httpx.Response(200, json={"items": [], "nextSyncToken": "novo"})]
        save = AsyncMock()
        conn = AsyncMock(side_effect=[{"calendar_id": "cal", "sync_token": "velho"}, {"calendar_id": "cal", "sync_token": None}])
        with patch.object(gc, "connection", conn), patch.object(gc, "_google", AsyncMock(side_effect=responses)) as google, \
             patch.object(gc, "_directory", AsyncMock(return_value=(set(), {}, {}))), patch.object(gc, "_save", save):
            result = await gc.sync()
        self.assertTrue(result["full"])
        self.assertIn("timeMin", google.await_args_list[1].kwargs["params"])
        self.assertEqual(save.await_args.args[0]["sync_token"], "novo")

    async def test_events_are_upserted_by_id(self):
        item = {"id": "e1", "status": "confirmed", "start": {"dateTime": "2030-01-01T10:00:00-03:00"}, "end": {"dateTime": "2030-01-01T11:00:00-03:00"}}
        upsert = AsyncMock()
        with patch.object(gc, "connection", AsyncMock(return_value={"calendar_id": "cal", "sync_token": "t"})), \
             patch.object(gc, "_google", AsyncMock(return_value=httpx.Response(200, json={"items": [item, item], "nextSyncToken": "t2"}))), \
             patch.object(gc, "_directory", AsyncMock(return_value=(set(), {}, {}))), patch.object(gc, "sb_upsert", upsert), \
             patch.object(gc, "schedule_reminders", AsyncMock()), patch.object(gc, "_save", AsyncMock()):
            await gc.sync()
        self.assertEqual(upsert.await_args.kwargs["on_conflict"], "calendar_id,google_event_id")

    async def test_revoked_token_asks_for_reauthorization(self):
        save = AsyncMock()
        conn = {"refresh_token_enc": "enc", "access_token_enc": None, "access_expires_at": None}
        with patch.dict(os.environ, {"GOOGLE_OAUTH_CLIENT_ID": "c", "GOOGLE_OAUTH_CLIENT_SECRET": "s", "GOOGLE_OAUTH_REDIRECT_URI": "https://x"}), \
             patch.object(gc, "connection", AsyncMock(return_value=conn)), patch.object(gc, "decrypt_secret", lambda v: "rt"), \
             patch.object(httpx.AsyncClient, "post", AsyncMock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))), \
             patch.object(gc, "_save", save):
            with self.assertRaises(gc.CalendarError) as ctx:
                await gc.access_token()
        self.assertEqual(ctx.exception.code, "REAUTH_REQUIRED")
        self.assertEqual(save.await_args.args[0]["status"], "reautorizar")


class WebhookTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_the_registered_channel_with_token_triggers_sync(self):
        conn = {"channel_id": "ch1", "channel_token_hash": gc._hash("segredo")}
        sync = AsyncMock(return_value={"changed": 1})
        with patch.object(gc, "connection", AsyncMock(return_value=conn)), patch.object(gc, "sync", sync):
            with self.assertRaises(gc.CalendarError):
                await gc.handle_webhook("ch1", "errado", "exists")
            with self.assertRaises(gc.CalendarError):
                await gc.handle_webhook("outro", "segredo", "exists")
            self.assertEqual((await gc.handle_webhook("ch1", "segredo", "sync"))["state"], "sync")
            sync.assert_not_awaited()
            await gc.handle_webhook("ch1", "segredo", "exists")
        sync.assert_awaited_once()


class MeetingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_sees_only_own_meetings_without_attendees(self):
        rows = [{"google_event_id": "e1", "summary": "Reunião", "client_id": "cura", "kind": "cliente", "attendees": [{"email": "x"}]},
                {"google_event_id": "e2", "summary": "Outra", "client_id": "roove", "kind": "cliente", "attendees": []}]
        select = AsyncMock(return_value=rows)
        with patch.object(gc, "sb_select", select):
            result = await gc.meetings("2026-11-01T00:00:00", "2026-12-01T00:00:00", client_id="cura")
        self.assertEqual(select.await_args.kwargs["filters"]["client_id"], "eq.cura")
        self.assertEqual([r["google_event_id"] for r in result], ["e1"])
        self.assertNotIn("attendees", result[0])


class TriggerTests(unittest.IsolatedAsyncioTestCase):
    async def test_adjustment_only_for_client_requested_changes(self):
        definition = {"key": "ajuste_concluido", "owner": "dados", "automation_enabled": True, "audience": "cliente", "variable_map": ["nome", "marca", "titulo"]}
        enqueue = AsyncMock(return_value={"id": "o"})
        with patch.object(au, "load_definitions", AsyncMock(return_value={"ajuste_concluido": definition})), patch.object(au, "enqueue", enqueue), \
             patch.object(au, "client_contacts", AsyncMock(return_value=[CONTACTS["nasser@curavino.com"]])), \
             patch.object(tr, "_brand", AsyncMock(return_value="Curavino")):
            self.assertEqual(await tr.on_item_status_change("cura", {"id": "i", "status": "rejeitado", "reviewed_by": "julia"}, {"id": "i", "status": "aprovado"}), 0)
            self.assertEqual(await tr.on_item_status_change("cura", {"id": "i", "status": "aprovado", "reviewed_by": "cliente:Ana"}, {"id": "i", "status": "publicado"}), 0)
            self.assertEqual(await tr.on_item_status_change("cura", {"id": "i", "status": "rejeitado", "reviewed_by": "cliente:Ana", "reviewed_at": "t"},
                                                            {"id": "i", "status": "em_revisao", "title": "Reels"}), 1)
        self.assertEqual(enqueue.await_args.kwargs["client_id"], "cura")

    async def test_publication_needs_instagram_confirmation(self):
        definition = {"key": "conteudo_publicado", "owner": "dados", "automation_enabled": True, "audience": "cliente", "variable_map": ["nome", "marca", "titulo", "link"]}
        now = datetime.now(timezone.utc)
        item = {"id": "i1", "client_id": "cura", "title": "Reels", "scheduled_at": now.isoformat(), "status": "publicado", "published_at": now.isoformat()}

        async def select(table, **kwargs):
            if table == "studio_calendar_items" or table == tr.ITEMS_TABLE:
                return [item]
            return self.media
        enqueue = AsyncMock(return_value={"id": "o"})
        with patch.object(au, "load_definitions", AsyncMock(return_value={"conteudo_publicado": definition})), \
             patch.object(tr, "sb_select", AsyncMock(side_effect=select)), patch.object(au, "enqueue", enqueue), \
             patch.object(au, "client_contacts", AsyncMock(return_value=[CONTACTS["nasser@curavino.com"]])), \
             patch.object(tr, "_brand", AsyncMock(return_value="Curavino")):
            self.media = []
            self.assertEqual((await tr.confirm_publications(now=now))["unconfirmed"], 1)
            enqueue.assert_not_awaited()
            self.media = [{"client_id": "roove", "permalink": "https://ig/p/outra", "timestamp": now.isoformat()}]
            self.assertEqual((await tr.confirm_publications(now=now))["unconfirmed"], 1)  # post de outra empresa não confirma
            self.media = [{"client_id": "cura", "permalink": "https://ig/p/1", "timestamp": now.isoformat()}]
            result = await tr.confirm_publications(now=now)
        self.assertEqual(result["queued"], 1)
        self.assertEqual(enqueue.await_args.kwargs["params"]["link"], "https://ig/p/1")

    async def test_campaign_alert_goes_only_to_team(self):
        definition = {"key": "alerta_campanha", "owner": "dados", "automation_enabled": True, "audience": "equipe",
                      "variable_map": ["nome", "marca", "campanha", "ocorrencia"], "recipients": {"team": "campaign_alerts"}}
        enqueue = AsyncMock(return_value={"id": "o"})
        contacts = AsyncMock()
        with patch.object(au, "load_definitions", AsyncMock(return_value={"alerta_campanha": definition})), patch.object(au, "enqueue", enqueue), \
             patch.object(au, "team_members", AsyncMock(return_value=[TEAM["ana@mugo.com.br"]])), patch.object(au, "client_contacts", contacts), \
             patch.object(tr, "_brand", AsyncMock(return_value="Curavino")):
            result = await tr.emit("alerta_campanha", client_id="cura", params={"campanha": "Remarketing", "ocorrencia": "anúncio reprovado"}, source_id="x1")
        self.assertEqual(result["queued"], 1)
        contacts.assert_not_awaited()
        self.assertTrue(enqueue.await_args.kwargs["recipient"]["team_member"])

    async def test_approval_reminder_respects_interval(self):
        definition = {"key": "lembrete_aprovacao", "owner": "dados", "automation_enabled": True, "audience": "cliente", "lead_minutes": 2880,
                      "variable_map": ["nome", "pendentes", "marca", "validade"]}
        now = datetime.now(timezone.utc)
        recent = {"id": "r1", "client_id": "cura", "created_at": (now - timedelta(days=5)).isoformat(), "last_reminded_at": (now - timedelta(hours=10)).isoformat()}
        old = {**recent, "id": "r2", "last_reminded_at": (now - timedelta(days=3)).isoformat()}
        enqueue = AsyncMock(return_value={"id": "o"})
        params = AsyncMock(return_value=({"nome": "Nasser", "pendentes": "2", "marca": "C", "validade": "10/11"}, {"button_suffix": "tok"}))
        with patch.object(au, "load_definitions", AsyncMock(return_value={"lembrete_aprovacao": definition})), \
             patch.object(tr, "sb_select", AsyncMock(return_value=[recent, old])), patch.object(au, "enqueue", enqueue), \
             patch.object(au, "client_contacts", AsyncMock(return_value=[CONTACTS["nasser@curavino.com"]])), \
             patch.object(tr, "_brand", AsyncMock(return_value="C")), patch.object(tr, "sb_update", AsyncMock()), \
             patch.object(tr, "encrypt_secret", lambda v: "cifrado"), patch("services.studio_messages._approval_params", params):
            result = await tr.approval_reminders(now=now)
        self.assertEqual(result["requests"], 1)
        self.assertEqual(enqueue.await_args.kwargs["source_id"], "r2")
        self.assertEqual(enqueue.await_args.kwargs["button_suffix"], "enc:cifrado")  # token do link nunca fica aberto na fila


if __name__ == "__main__":
    unittest.main()
