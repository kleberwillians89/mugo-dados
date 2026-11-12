"""Fluxos comerciais: marco certo, janela de 3 dias (ligar não dispara para a base toda), consentimento,
um envio por pessoa/fluxo/marco e receita contada uma vez."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import commercial_flows as cf
from services import email_marketing as em
from services import email_resend as er

NOW = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)


def person(h, orders=1, first=None, last=None, consent=True, phone=None):
    return {"email": f"{h}@x.com", "hash": h * 32, "first_name": "Ana", "name": "Ana", "consent": consent, "orders": orders,
            "first_order_at": first, "last_order_at": last or first, "phone": phone}


def ago(days):
    return (NOW - timedelta(days=days)).isoformat()


class DueTests(unittest.TestCase):
    def test_milestones_and_catch_window(self):
        self.assertEqual(cf.due("boas_vindas", person("a", first=ago(1)), 0, NOW), (NOW - timedelta(days=1)).date().isoformat())
        self.assertIsNone(cf.due("boas_vindas", person("a", first=ago(10)), 0, NOW))  # fora da janela: não dispara retroativo
        self.assertIsNone(cf.due("boas_vindas", person("a", orders=2, first=ago(1)), 0, NOW))
        self.assertIsNotNone(cf.due("segunda_compra", person("a", first=ago(31)), 30, NOW))
        self.assertIsNone(cf.due("segunda_compra", person("a", orders=2, first=ago(31), last=ago(5)), 30, NOW))
        self.assertIsNotNone(cf.due("reativacao", person("a", orders=4, first=ago(400), last=ago(91)), 90, NOW))
        self.assertIsNone(cf.due("reativacao", person("a", orders=4, first=ago(400), last=ago(80)), 90, NOW))
        self.assertIsNotNone(cf.due("pos_venda", person("a", orders=3, first=ago(100), last=ago(7.5)), 7, NOW))
        self.assertIsNone(cf.due("pos_venda", person("a", orders=0), 7, NOW))

    def test_consent_rules(self):
        email_flow = {"channel": "email", "consent": "consentimento"}
        self.assertEqual(cf.allowed(email_flow, person("a", consent=False), blocked=set(), talked=False), (False, "sem consentimento de marketing"))
        self.assertEqual(cf.allowed({**email_flow, "consent": "todos"}, person("a", consent=False), blocked=set(), talked=False), (True, ""))
        self.assertEqual(cf.allowed({**email_flow, "consent": "todos"}, person("a"), blocked={"a" * 32}, talked=False), (False, "descadastrado"))
        wa = {"channel": "whatsapp", "consent": "todos"}
        self.assertEqual(cf.allowed(wa, person("a"), blocked=set(), talked=False), (False, "sem telefone"))
        self.assertEqual(cf.allowed(wa, person("a", consent=None, phone="11999990000"), blocked=set(), talked=True), (True, ""))
        self.assertEqual(cf.allowed({**wa, "consent": "consentimento"}, person("a", consent=None, phone="1199"), blocked=set(), talked=True)[0], False)

    def test_clean_flow(self):
        self.assertEqual(cf.clean_flow({"delay_days": "30", "whatsapp_variables": ["nome", "cpf", "link"]}),
                         {"delay_days": 30, "whatsapp_variables": ["nome", "link"]})
        with self.assertRaises(cf.FlowError):
            cf.clean_flow({"delay_days": 999})
        with self.assertRaises(cf.FlowError):
            cf.clean_flow({"channel": "sms"})

    def test_attribution_counts_each_order_once(self):
        sent_at = NOW - timedelta(days=10)
        sends = [{"kind": "reativacao", "email_hash": "a" * 32, "status": "enviado", "at": sent_at.isoformat()},
                 {"kind": "reativacao", "email_hash": "b" * 32, "status": "simulado", "at": sent_at.isoformat()},
                 {"kind": "reativacao", "email_hash": "c" * 32, "status": "pulado", "at": sent_at.isoformat()}]
        purchases = {"p1": [(sent_at + timedelta(days=2), 200.0), (sent_at + timedelta(days=20), 999.0)],
                     "p2": [(sent_at - timedelta(days=1), 50.0)]}
        out = cf.attribute(sends, {"a" * 32: "p1", "b" * 32: "p2"}, purchases)["reativacao"]
        self.assertEqual((out["sent"], out["skipped"], out["buyers"], out["revenue"], out["conversion"]), (2, 1, 1, 200.0, 50.0))


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_once_and_records(self):
        flow = {**cf.default_flow("boas_vindas"), "enabled": True}
        contacts = [person("a", first=ago(0.5)), person("b", first=ago(0.5), consent=False), person("c", first=ago(1))]
        upsert = AsyncMock()
        send_batch = AsyncMock(return_value=["re_1", "re_2"])
        insert_ignore = AsyncMock()
        done = [{"kind": "boas_vindas", "email_hash": "c" * 32, "ref": (NOW - timedelta(days=1)).date().isoformat()}]
        with patch.dict(os.environ, {"TOKEN_ENCRYPTION_KEY": "k", "API_PUBLIC_URL": "https://api.x.com"}), \
             patch.object(em, "load_contacts", AsyncMock(return_value=("shopify", contacts))), \
             patch.object(em, "suppressed", AsyncMock(return_value=set())), \
             patch.object(em, "get_settings", AsyncMock(return_value={"from_name": "Roove", "from_email": "oi@roove.com.br"})), \
             patch("services.sales_by_origin._paged", AsyncMock(return_value=(done, False))), \
             patch.object(cf, "sb_upsert", upsert), patch.object(em, "_insert_ignore", insert_ignore), patch.object(er, "send_batch", send_batch):
            out = await cf.run_client("roove", [flow], now=NOW)
        msgs = send_batch.await_args.args[0]
        self.assertEqual([m["to"] for m in msgs], [["a@x.com"], ["b@x.com"]])  # boas-vindas padrão = todos (com descadastro)
        self.assertEqual(msgs[0]["subject"], "Bem-vinda à Roove, Ana")
        self.assertEqual(out["boas_vindas"]["enviado"], 2)
        self.assertEqual(len(upsert.await_args.args[1]), 2)  # "c" já tinha recebido
        self.assertTrue(insert_ignore.await_args.args[0][0]["idem_key"].startswith("fluxo/boas_vindas/"))


if __name__ == "__main__":
    unittest.main()
