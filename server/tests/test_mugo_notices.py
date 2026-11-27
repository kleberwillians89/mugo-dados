"""“A Mugô IA notou”: regras fixas, gravação pelo job, WhatsApp só do urgente, quem vê o quê e dispensar."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import io
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from services import mugo_notices as mn

NOW = datetime(2026, 11, 26, 15, 0, tzinfo=timezone.utc)  # quinta, 12h em São Paulo
TODAY = date(2026, 11, 26)


def day(n):
    return (TODAY - timedelta(days=n)).isoformat()


def stats(costs_last3, prior_cost=40.0, spend=60.0, status="ACTIVE", objective="OUTCOME_SALES"):
    rows = [{"stat_date": day(n), "campaign_id": "c1", "campaign_name": "Black Roove – Vendas", "campaign_status": status,
             "objective": objective, "spend": spend, "conversions": spend / prior_cost} for n in range(4, 18)]
    for n, cost in zip((3, 2, 1), costs_last3):
        rows.append({"stat_date": day(n), "campaign_id": "c1", "campaign_name": "Black Roove – Vendas", "campaign_status": status,
                     "objective": objective, "spend": spend, "conversions": spend / cost})
    return rows


def build(**kw):
    base = dict(now=NOW, stats=[], requests=[], review_items=[], failed=[], soon_posts=[], soon_emails=[], connections=[], account=None)
    return mn.build("roove", **{**base, **kw})


class RuleTests(unittest.TestCase):
    def test_cost_rising_three_days_and_twenty_percent(self):
        found = mn.cost_rising(stats([42, 50, 61]), TODAY)
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found[0]["from"], 42)
        self.assertAlmostEqual(found[0]["to"], 61)
        out = build(stats=stats([42, 50, 61]))
        self.assertEqual(out[0]["kind"], "custo_subindo")
        self.assertIn("(R$ 42,00 → R$ 61,00)", out[0]["message"])
        self.assertIn("desde segunda", out[0]["message"])

    def test_cost_not_alerted_when_not_rising_every_day_small_spend_paused_or_close_to_average(self):
        self.assertEqual(mn.cost_rising(stats([42, 61, 50]), TODAY), [])         # não subiu 3 dias seguidos
        self.assertEqual(mn.cost_rising(stats([42, 44, 46]), TODAY), [])         # menos de 20% acima da média (40)
        self.assertEqual(mn.cost_rising(stats([42, 50, 61], spend=10), TODAY), [])  # gasto pequeno
        self.assertEqual(mn.cost_rising(stats([42, 50, 61], status="PAUSED"), TODAY), [])

    def test_approval_waiting_only_after_48h_and_only_items_still_waiting(self):
        requests = [{"id": "r1", "item_ids": ["a", "b", "c", "d", "e"], "created_at": (NOW - timedelta(hours=50)).isoformat(),
                     "expires_at": (NOW + timedelta(days=10)).isoformat(), "contact_id": "k1"},
                    {"id": "r2", "item_ids": ["z"], "created_at": (NOW - timedelta(hours=5)).isoformat(),
                     "expires_at": (NOW + timedelta(days=10)).isoformat()}]
        items = [{"id": i, "status": "em_revisao", "scheduled_at": f"2026-11-{n + 27}T22:00:00+00:00"} for n, i in enumerate("abc")]
        items.append({"id": "d", "status": "em_revisao", "scheduled_at": "2026-12-01T22:00:00+00:00"})
        items += [{"id": "e", "status": "aprovado"}, {"id": "z", "status": "em_revisao", "scheduled_at": "2026-11-27T10:00:00+00:00"}]
        out = build(requests=requests, review_items=items)
        self.assertEqual(len(out), 1)
        n = out[0]
        self.assertEqual(n["message"], "4 posts esperam aprovação do cliente há mais de 48h. O primeiro sai sexta (27/11) às 19h.")
        self.assertTrue(n["client_visible"])
        remind = [a for a in n["actions"] if a.get("kind") == "remind"][0]
        self.assertEqual((remind["request_id"], remind["contact_id"], remind["team_only"]), ("r1", "k1", True))

    def test_failed_post_drafts_connections_and_account(self):
        out = build(failed=[{"id": "p1", "title": "Reels Black", "scheduled_at": "2026-11-25T22:00:00+00:00", "publish_error": "Mídia inválida"}],
                    soon_posts=[{"id": "x", "scheduled_at": "2026-11-27T22:00:00+00:00"}],
                    soon_emails=[{"id": "e1", "name": "Black começa", "scheduled_at": "2026-12-01T12:00:00+00:00"}],
                    connections=[{"provider": "meta_ads", "status": "needs_reauth", "label": "precisa reconectar"}],
                    account={"account_status": 3})
        kinds = [n["kind"] for n in sorted(out, key=lambda n: -n["urgency"])]
        self.assertEqual(kinds, ["publicacao_falhou", "conta_sem_saldo", "integracao_caida", "data_com_rascunho", "data_com_rascunho"])
        text = " ".join(n["message"] for n in out)
        for piece in ("falhou ao publicar", "Motivo: Mídia inválida", "pagamento pendente", "Meta Ads caiu",
                      "sai em 5 dias e ainda está em rascunho", "1 post dos próximos 3 dias"):
            self.assertIn(piece, text)
        self.assertTrue(all(n["urgent"] == (n["kind"] in ("publicacao_falhou", "conta_sem_saldo")) for n in out))
        self.assertFalse(any(n["client_visible"] for n in out))

    def test_spend_cap_and_nothing_when_all_is_fine(self):
        self.assertIn("96% do limite", build(account={"account_status": 1, "spend_cap": 10000, "amount_spent": 9600})[0]["message"])
        self.assertEqual(build(account={"account_status": 1, "spend_cap": 10000, "amount_spent": 100}), [])


class ScanTests(unittest.IsolatedAsyncioTestCase):
    async def test_saves_resolves_and_sends_urgent_once_per_level(self):
        failed = mn.build("roove", now=NOW, stats=[], requests=[], review_items=[], failed=[{"id": "p1", "title": "Reels", "scheduled_at": NOW.isoformat()}],
                          soon_posts=[], soon_emails=[], connections=[])
        upsert, update = AsyncMock(), AsyncMock()
        send = AsyncMock(return_value=1)
        select = AsyncMock(return_value=[{"key": "integracao_caida:ga4", "level": 1, "whatsapp_level": 0}])
        with patch.object(mn, "compute", AsyncMock(return_value=failed)), patch.object(mn, "sb_upsert", upsert), \
             patch.object(mn, "sb_update", update), patch.object(mn, "sb_select", select), patch.object(mn, "_send_urgent", send):
            result = await mn.scan_client("roove", now=NOW)
        self.assertEqual(result, {"notices": 1, "resolved": 1, "whatsapp": 1})
        self.assertEqual(upsert.await_args.args[1][0]["key"], "publicacao_falhou:p1")
        patches = [c.kwargs["patch"] for c in update.await_args_list]
        self.assertIn({"resolved_at": NOW.isoformat(), "whatsapp_level": 0}, patches)
        self.assertTrue(any(p.get("whatsapp_level") == 1 for p in patches))
        # Mesma situação na hora seguinte: não manda de novo.
        select2 = AsyncMock(return_value=[{"key": "publicacao_falhou:p1", "level": 1, "whatsapp_level": 1}])
        send.reset_mock()
        with patch.object(mn, "compute", AsyncMock(return_value=failed)), patch.object(mn, "sb_upsert", AsyncMock()), \
             patch.object(mn, "sb_update", AsyncMock()), patch.object(mn, "sb_select", select2), patch.object(mn, "_send_urgent", send):
            result = await mn.scan_client("roove", now=NOW)
        send.assert_not_awaited()
        self.assertEqual(result["whatsapp"], 0)

    async def test_urgent_whatsapp_only_to_team_that_opted_in(self):
        from services import task_assignment_notifications as tan, clients
        dispatch = AsyncMock(return_value=("sent", "m1"))

        async def select(table, **kw):
            if table == tan.PREFERENCES:
                return [{"user_id": "team-user"}, {"user_id": "client-user"}]
            return [{"name": "Roove", "trade_name": "Roove"}]

        async def listed(uid):
            return {"clients": [{"client_id": "roove", "role": "agency_admin" if uid == "team-user" else "client_viewer"}]}
        n = {"key": "publicacao_falhou:p1", "level": 1, "message": "O post \"Reels\" falhou ao publicar."}
        with patch.object(mn, "sb_select", select), patch.object(tan, "_whatsapp_dispatch", dispatch), \
             patch.object(clients, "list_clients_for_user", listed):
            sent = await mn._send_urgent("roove", n)
        self.assertEqual(sent, 1)
        uid, body = dispatch.await_args.args[1], dispatch.await_args.args[2]
        self.assertEqual(uid, "team-user")
        self.assertTrue(body.startswith("Mugô IA notou em Roove: O post"))


class VisibilityTests(unittest.IsolatedAsyncioTestCase):
    ROWS = [
        {"client_id": "roove", "key": "publicacao_falhou:p1", "kind": "publicacao_falhou", "level": 1, "urgency": 100,
         "message": "falhou", "actions": [], "client_visible": False, "first_seen_at": "x"},
        {"client_id": "roove", "key": "aprovacao_parada:cliente", "kind": "aprovacao_parada", "level": 5, "urgency": 70,
         "message": "4 posts", "actions": [{"label": "Ir", "route": "final_approval"}, {"label": "Cobrar", "kind": "remind", "team_only": True}],
         "client_visible": True, "first_seen_at": "x"},
        {"client_id": "ruah", "key": "custo_subindo:c1", "kind": "custo_subindo", "level": 1, "urgency": 80,
         "message": "custo", "actions": [], "client_visible": False, "first_seen_at": "x"},
    ]

    async def run_for(self, role_by_client, dismissed=()):
        async def listed(uid):
            return {"clients": [{"client_id": c, "role": r, "name": c.title()} for c, r in role_by_client.items()]}

        async def select(table, **kw):
            if table == mn.NOTICES:
                allowed = kw["filters"]["client_id"]
                return [r for r in self.ROWS if f'"{r["client_id"]}"' in allowed]
            return list(dismissed)
        from services import clients
        with patch.object(clients, "list_clients_for_user", listed), patch.object(mn, "sb_select", select):
            return await mn.for_user("u1", limit=3)

    async def test_team_sees_everything_across_clients_most_urgent_first(self):
        out = await self.run_for({"roove": "agency_admin", "ruah": "agency_admin"})
        self.assertEqual([n["kind"] for n in out["notices"]], ["publicacao_falhou", "aprovacao_parada", "custo_subindo"])
        self.assertEqual(len(out["notices"][1]["actions"]), 2)

    async def test_client_sees_only_own_actionable_without_team_buttons(self):
        out = await self.run_for({"roove": "client_viewer"})
        self.assertEqual([n["kind"] for n in out["notices"]], ["aprovacao_parada"])
        self.assertEqual([a["label"] for a in out["notices"][0]["actions"]], ["Ir"])

    async def test_dismissed_hides_until_it_gets_worse(self):
        out = await self.run_for({"roove": "agency_admin"}, dismissed=[{"client_id": "roove", "notice_key": "aprovacao_parada:cliente", "level": 5}])
        self.assertNotIn("aprovacao_parada", [n["kind"] for n in out["notices"]])
        out = await self.run_for({"roove": "agency_admin"}, dismissed=[{"client_id": "roove", "notice_key": "aprovacao_parada:cliente", "level": 4}])
        self.assertIn("aprovacao_parada", [n["kind"] for n in out["notices"]])

    async def test_dismiss_requires_access_to_the_company(self):
        from services import clients
        upsert = AsyncMock()
        with patch.object(clients, "list_clients_for_user", AsyncMock(return_value={"clients": [{"client_id": "roove"}]})), \
             patch.object(mn, "sb_select", AsyncMock(return_value=[{"level": 2}])), patch.object(mn, "sb_upsert", upsert), \
             redirect_stdout(io.StringIO()):
            self.assertFalse(await mn.dismiss("u1", "ruah|custo_subindo:c1"))
            self.assertTrue(await mn.dismiss("u1", "roove|publicacao_falhou:p1"))
        self.assertEqual(upsert.await_args.args[1][0]["level"], 2)


    async def test_completed_notice_persists_disposition_for_the_user(self):
        from services import clients
        upsert = AsyncMock()
        with patch.object(clients, "list_clients_for_user", AsyncMock(return_value={"clients": [{"client_id": "roove"}]})), \
             patch.object(mn, "sb_select", AsyncMock(return_value=[{"level": 2}])), patch.object(mn, "sb_upsert", upsert):
            self.assertTrue(await mn.dismiss("u1", "roove|publicacao_falhou:p1", completed=True))
        self.assertEqual(upsert.await_args.args[1][0]["disposition"], "completed")
        self.assertEqual(upsert.await_args.args[1][0]["user_id"], "u1")


if __name__ == "__main__":
    unittest.main()
