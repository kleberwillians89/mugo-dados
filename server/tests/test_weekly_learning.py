from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import campaign_learning as cl
from services import media_strategy as ms
from services import studio_messages as sm
from services import weekly_digest as wd
from services.studio_calendar import StudioError

TODAY = date(2026, 10, 30)  # sexta
CONTACT = {"id": "c1", "name": "Ana Souza", "phone": "5511988887777", "receives": ["trafego"], "is_primary": True}
MUGOZAP = {"MUGOZAP_FUNCTION_URL": "https://crm.supabase.co/functions/v1/mugozap-api", "MUGOZAP_ANON_KEY": "a",
           "MUGOZAP_WORKER_KEY": "w", "MUGOZAP_TEAM_MEMBER_ID": "t"}


def campaign(name, spend, conv, rev, cid=None):
    return {"campaign_id": cid or name, "campaign_name": name, "spend": spend, "conversions": conv, "revenue": rev, "impressions": spend * 100, "clicks": spend * 2}


class SnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_week_snapshot_records_each_campaign_with_plan_and_notes(self):
        meta = {"daily": [{"date": "2026-10-25", "spend": 1000, "impressions": 100000, "clicks": 2000, "conversions": 40, "revenue": 6000}],
                "campaigns": [campaign("Remarketing", 600, 30, 4800), campaign("Catálogo nova", 300, 8, 1000), campaign("Troco", 5, 0, 0)]}
        previous = {("meta", "Remarketing"): {"first_seen": "2026-08-01", "spend": 400, "roas": 12.0, "cpa": 20}}
        plan = {"Remarketing": {"action": "escalar", "planned_budget": 2400}}
        with patch.dict(ms.READERS, {"meta": AsyncMock(return_value=meta), "google_ads": AsyncMock(side_effect=RuntimeError("sem conexão"))}), \
             patch.object(cl, "_planned", AsyncMock(return_value=plan)), patch.object(cl, "_previous", AsyncMock(return_value=previous)), \
             patch.object(cl, "sb_upsert", AsyncMock()) as upsert:
            out = await cl.snapshot_week("curavino", today=TODAY)
        rows = {r["campaign_name"]: r for r in upsert.await_args.args[1]}
        self.assertEqual(set(rows), {"Remarketing", "Catálogo nova"})          # Troco: gasto irrelevante e sem histórico
        self.assertEqual((rows["Remarketing"]["week_start"], rows["Remarketing"]["week_end"]), ("2026-10-23", "2026-10-29"))
        self.assertEqual((rows["Remarketing"]["planned_action"], rows["Remarketing"]["planned_budget"]), ("escalar", 2400))
        self.assertIn("saturação", rows["Remarketing"]["note"])                # verba +50% e ROAS 12 → 8
        self.assertEqual(rows["Catálogo nova"]["first_seen"], "2026-10-23")
        self.assertIn("Campanha nova", rows["Catálogo nova"]["note"])
        self.assertEqual(upsert.await_args.kwargs["on_conflict"], "client_id,channel,campaign_key,week_start")
        self.assertEqual(list(out["channels"]), ["meta"])
        self.assertEqual(len(out["new"]), 1)

    def test_trend_notes(self):
        h = lambda roas, ws: {"week_start": ws, "first_seen": "2026-07-01", "roas": roas, "cpa": None, "conversions": 10}
        self.assertEqual(cl.trend_note([h(3, "c"), h(4, "b"), h(5, "a")], "revenue", TODAY)["kind"], "queda")
        self.assertEqual(cl.trend_note([h(6, "c"), h(5, "b"), h(4, "a")], "revenue", TODAY)["kind"], "alta")
        self.assertIsNone(cl.trend_note([h(5, "c"), h(4, "b"), h(5, "a")], "revenue", TODAY))
        new = [{"week_start": "2026-10-23", "first_seen": "2026-10-16", "roas": 2, "cpa": None, "conversions": 4}]
        self.assertEqual(cl.trend_note(new, "revenue", TODAY)["kind"], "nova")

    def test_strategy_uses_timeline(self):
        rows = [{"campaign": "Nova", "action": "pausar", "spend": 300}, {"campaign": "Caindo", "action": "escalar", "spend": 900}]
        history = {"Nova": [{"week_start": "2026-10-23", "first_seen": "2026-10-16", "conversions": 1, "roas": 0.5, "cpa": 300}],
                   "Caindo": [{"week_start": w, "first_seen": "2026-06-01", "roas": r, "cpa": None, "conversions": 20}
                              for w, r in (("2026-10-23", 3.0), ("2026-10-16", 4.0), ("2026-10-09", 5.0))]}
        self.assertEqual(ms.apply_trends(rows, history, "revenue", TODAY), 2)
        self.assertEqual(rows[0]["action"], "aprender")   # campanha nova não é cortada antes do aprendizado
        self.assertEqual(rows[1]["action"], "manter")     # ROAS caindo há 3 semanas não é escalado
        self.assertIn("3 semanas", rows[1]["learning"])


class WeeklyMessageTests(unittest.IsolatedAsyncioTestCase):
    SNAP = {"metrics": {"investment": {"value": 1250}, "revenue": {"value": 9800}, "roas": {"value": 7.84}}, "campaigns": []}
    ROWS = [{"channel": "meta", "campaign_name": "Catálogo nova", "spend": 300, "conversions": 12, "roas": 4.0, "cpa": 25,
             "note": "Campanha nova (desde 23/10): 12 conversões na primeira semana.", "recommended_action": "escalar", "planned_action": None}]

    async def build(self, **overrides):
        with patch.object(sm, "list_contacts", AsyncMock(return_value=[CONTACT])), patch.object(sm, "_client_name", AsyncMock(return_value="Curavino")), \
             patch.object(sm, "_snapshot", AsyncMock(return_value=self.SNAP)), patch.object(sm, "sb_select", AsyncMock(return_value=self.ROWS)), \
             patch.object(sm, "_sentence", AsyncMock(side_effect=lambda task, data, fallback, preset=None: preset or fallback)):
            return await sm.build_message("curavino", "semanal", overrides=overrides)

    async def test_numbers_from_panel_learning_and_next_step_from_memory(self):
        built = await self.build()
        p = built["params"]
        self.assertEqual(built["template_name"], "mugo_resumo_semanal")
        self.assertEqual((p["investimento"], p["receita"], p["roas"]), ("R$ 1.250,00", "R$ 9.800,00", "R$ 7,84"))
        self.assertIn("Catálogo nova", p["destaque"])
        self.assertEqual(p["proximo"], "escalar Catálogo nova")
        self.assertEqual(built["editable"], ["destaque", "proximo"])
        self.assertEqual((await self.build(proximo="revisar criativos"))["params"]["proximo"], "revisar criativos")

    async def test_without_whatsapp_job_registers_waiting_and_sends_nothing(self):
        with patch.dict("os.environ", {k: "" for k in MUGOZAP}), patch.object(sm, "sb_select", AsyncMock(return_value=[])), \
             patch.object(sm, "sb_insert", AsyncMock()) as insert, patch.object(sm, "mugozap_send", AsyncMock()) as send:
            out = await sm.deliver("curavino", contact=CONTACT, template_name="mugo_resumo_semanal", params={}, button_suffix=None,
                                   header_image=None, request_id=None, user_id=wd.JOB_USER, key="dados-" + "e" * 40, automatic=True)
        self.assertEqual(out["status"], "aguardando")
        send.assert_not_awaited()
        self.assertEqual((insert.await_args.args[1]["status"], insert.await_args.args[1]["error_code"]), ("aguardando", "MUGOZAP_NOT_CONFIGURED"))

    async def test_weekly_key_ignores_ai_wording(self):
        keys = []
        async def fake_deliver(*a, **kw):
            keys.append(kw["key"])
            return {"status": "enviado", "channel": "mugozap", "text": ""}
        built = {"template_name": "mugo_resumo_semanal", "params": {"destaque": "frase 1"}, "_contact": CONTACT,
                 "_extra": {"key_parts": ["2026-10-23"], "button_suffix": None, "header_image": None, "request_id": None}}
        other = {**built, "params": {"destaque": "frase 2"}}
        with patch.object(sm, "build_message", AsyncMock(side_effect=[built, other])), patch.object(sm, "deliver", fake_deliver):
            await sm.send_message("curavino", "semanal", user_id="u", automatic=True)
            await sm.send_message("curavino", "semanal", user_id="u", automatic=True)
        self.assertEqual(keys[0], keys[1])  # job rodando duas vezes na mesma semana não manda duas mensagens


class DigestJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_learns_for_everyone_and_messages_only_who_has_contact(self):
        summaries = {"a": {"channels": {"meta": {}}, "campaigns": [{}, {}], "notes": ["x"], "new": []},
                     "b": {"channels": {"meta": {}}, "campaigns": [{}], "notes": [], "new": []},
                     "c": {"channels": {}, "campaigns": [], "notes": [], "new": []}}
        contacts = {"a": [CONTACT], "b": [{**CONTACT, "receives": ["conteudo"]}], "c": [CONTACT]}
        with patch.object(wd, "paid_clients", AsyncMock(return_value=["a", "b", "c"])), \
             patch("services.campaign_learning.snapshot_week", AsyncMock(side_effect=lambda cid: summaries[cid])), \
             patch("services.studio_messages.list_contacts", AsyncMock(side_effect=lambda cid: contacts[cid])), \
             patch("services.studio_messages.send_message", AsyncMock(return_value={"status": "aguardando"})) as send:
            out = await wd.run_weekly_digest()
        self.assertEqual(send.await_count, 1)                 # só "a" tem contato de tráfego e investimento na semana
        self.assertTrue(send.await_args.kwargs["automatic"])
        self.assertEqual((out["clients"], out["waiting"], out["sent"], out["learned_campaigns"]), (3, 1, 0, 3))
        self.assertEqual(set(out), {"ok", "clients", "sent", "waiting", "errors", "learned_campaigns"})  # log público: só contagens

    async def test_single_client_failure_does_not_stop_the_others(self):
        async def snap(cid):
            if cid == "x":
                raise RuntimeError("falhou")
            return {"channels": {}, "campaigns": [], "notes": [], "new": []}
        with patch.object(wd, "paid_clients", AsyncMock(return_value=["x", "y"])), patch("services.campaign_learning.snapshot_week", snap):
            out = await wd.run_weekly_digest()
        self.assertFalse(out["ok"])
        self.assertEqual((out["clients"], out["errors"]), (2, 1))


if __name__ == "__main__":
    unittest.main()
