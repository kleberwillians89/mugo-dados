"""Planos: sem assinatura não há limite; cancelada bloqueia; cobrança gera 1 fatura por mês e atrasa só após a carência."""
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import saas

PLAN = {"id": "crescimento", "price_month_cents": 99700, "limits": {"email_sends_month": 100, "whatsapp_month": 10}}


class RemainingTests(unittest.TestCase):
    def test_rules(self):
        used = {"email_sends_month": 70, "whatsapp_month": 12}
        sub = {"status": "ativa", "plan": PLAN}
        self.assertIsNone(saas.remaining_from(None, used, "email_sends_month"))
        self.assertEqual(saas.remaining_from(sub, used, "email_sends_month"), 30)
        self.assertEqual(saas.remaining_from(sub, used, "whatsapp_month"), 0)
        self.assertIsNone(saas.remaining_from(sub, used, "competitors"))  # sem número no plano = sem limite
        self.assertEqual(saas.remaining_from({**sub, "status": "cancelada"}, used, "competitors"), 0)

    def test_clean_plan(self):
        out = saas.clean_plan({"name": "Pro", "price_month_cents": "149700", "limits": {"users": "5", "competitors": "", "x": 9}})
        self.assertEqual(out, {"name": "Pro", "price_month_cents": 149700, "limits": {"users": 5}})
        with self.assertRaises(saas.QuotaError):
            saas.clean_plan({"limits": {"users": "muitos"}})

    def test_invoice_due(self):
        sub = {"status": "ativa", "billing_day": 5}
        self.assertIsNone(saas.invoice_due(sub, date(2026, 11, 4)))
        self.assertEqual(saas.invoice_due(sub, date(2026, 11, 12)), {"period": "2026-11", "due_date": "2026-11-05"})
        self.assertIsNone(saas.invoice_due({**sub, "status": "cortesia"}, date(2026, 11, 12)))


class AsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_require_message_and_unlimited(self):
        with patch.object(saas, "get_subscription", AsyncMock(return_value={"status": "ativa", "plan": PLAN})), \
             patch.object(saas, "usage", AsyncMock(return_value={"email_sends_month": 90})):
            with self.assertRaises(saas.QuotaError) as ctx:
                await saas.require("roove", "email_sends_month", 25)
        self.assertIn("faltam 15", ctx.exception.message)
        with patch.object(saas, "get_subscription", AsyncMock(return_value=None)):
            await saas.require("roove", "email_sends_month", 10_000)  # sem plano: passa

    async def test_remaining_fails_open_when_unreadable(self):
        with patch.object(saas, "get_subscription", AsyncMock(side_effect=RuntimeError("tabela não existe"))):
            self.assertIsNone(await saas.remaining("roove", "email_sends_month"))

    async def test_billing_cycle(self):
        subs = [{"client_id": "roove", "plan_id": "crescimento", "status": "teste", "trial_ends_at": "2026-11-10T00:00:00Z", "billing_day": 5},
                {"client_id": "ruah", "plan_id": "crescimento", "status": "cortesia", "trial_ends_at": None, "billing_day": 5}]
        selects = AsyncMock(side_effect=[subs, [{"id": "i1", "client_id": "x", "due_date": "2026-11-01"}], [{"client_id": "x"}]])
        update, request = AsyncMock(), AsyncMock()
        with patch.object(saas, "sb_select", selects), patch.object(saas, "list_plans", AsyncMock(return_value=[PLAN])), \
             patch.object(saas, "sb_update", update), patch.object(saas, "_request", request):
            out = await saas.run_billing(date(2026, 11, 12))
        self.assertEqual(out, {"activated": 1, "invoices": 1, "overdue": 1})
        invoice = request.await_args.kwargs["json"][0]
        self.assertEqual((invoice["client_id"], invoice["amount_cents"], invoice["period"]), ("roove", 99700, "2026-11"))
        self.assertIn("ignore-duplicates", request.await_args.kwargs["headers"]["Prefer"])
        patches = [c.kwargs["patch"] for c in update.await_args_list]
        self.assertIn({"status": "ativa"}, patches)
        self.assertIn({"status": "vencida"}, patches)
        self.assertIn({"status": "atrasada"}, patches)


if __name__ == "__main__":
    unittest.main()
