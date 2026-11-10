"""WhatsApp nativo: cadastro do número (validado na Meta) e leitura no contrato das outras fontes."""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import whatsapp_native as wn  # noqa: E402
from services import whatsapp_sources as ws  # noqa: E402

TOKEN = "EAAG" + "x" * 40


def graph_ok(method, path, token, params=None):
    if path == "109876543210987":
        return {"display_phone_number": "+55 11 99316-1161", "verified_name": "Roove"}
    if path == "112233445566778/phone_numbers":
        return {"data": [{"id": "109876543210987"}]}
    if path == "112233445566778/subscribed_apps":
        return {"success": True}
    raise AssertionError(path)


class RegisterTests(unittest.TestCase):
    def run_register(self, existing=None, graph=graph_ok, **kw):
        args = {"waba_id": "112233445566778", "phone_number_id": "109876543210987", "access_token": TOKEN, **kw}
        with patch.object(wn, "sb_select", AsyncMock(return_value=existing or [])), \
             patch.object(wn, "_graph", AsyncMock(side_effect=graph)) as g, \
             patch.object(wn, "sb_insert", AsyncMock(side_effect=lambda t, row: {**row, "id": "n1"})) as ins, \
             patch.object(wn, "sb_update", AsyncMock(return_value=[{"id": "n0", "status": "active"}])) as upd:
            out = asyncio.run(wn.register_number("roove", **args))
        return out, g, ins, upd

    def test_validates_on_meta_subscribes_and_never_returns_token(self):
        out, g, ins, _ = self.run_register()
        paths = [c.args[1] for c in g.await_args_list]
        self.assertEqual(paths, ["109876543210987", "112233445566778/phone_numbers", "112233445566778/subscribed_apps"])
        self.assertEqual(g.await_args_list[2].args[0], "POST")
        self.assertEqual(ins.await_args.args[1]["access_token"], TOKEN)
        self.assertNotIn("access_token", out)
        self.assertEqual(out["verified_name"], "Roove")

    def test_number_outside_waba_is_refused(self):
        def graph(method, path, token, params=None):
            return {"data": [{"id": "999"}]} if path.endswith("phone_numbers") else graph_ok(method, path, token, params)
        with self.assertRaises(wn.WhatsAppNativeError) as ctx:
            self.run_register(graph=graph)
        self.assertEqual(ctx.exception.code, "NOT_IN_WABA")

    def test_number_of_another_company_is_refused(self):
        with self.assertRaises(wn.WhatsAppNativeError) as ctx:
            self.run_register(existing=[{"id": "n0", "client_id": "ruah", "status": "active"}])
        self.assertEqual(ctx.exception.code, "NUMBER_IN_USE")

    def test_disconnected_number_of_another_company_is_also_refused(self):
        with self.assertRaises(wn.WhatsAppNativeError) as ctx:
            self.run_register(existing=[{"id": "n0", "client_id": "ruah", "status": "disconnected"}])
        self.assertEqual(ctx.exception.code, "NUMBER_IN_USE")

    def test_reconnect_same_company_updates(self):
        out, _, ins, upd = self.run_register(existing=[{"id": "n0", "client_id": "roove", "status": "disconnected"}])
        ins.assert_not_awaited()
        upd.assert_awaited_once()

    def test_bad_input(self):
        for kw in ({"waba_id": "abc"}, {"access_token": "curto"}, {"access_token": TOKEN + " x"}):
            with self.assertRaises(wn.WhatsAppNativeError):
                self.run_register(**kw)


class ReadTests(unittest.TestCase):
    def test_conversations_mask_phone_and_keep_key_for_matching(self):
        thread = {"id": "t1", "wa_id": "5511993161161", "phone_key": "a" * 32, "profile_name": "Mari",
                  "first_seen_at": "2026-11-10T10:00:00+00:00", "last_message_at": "2026-11-10T10:05:00+00:00",
                  "last_inbound_at": "2026-11-10T10:05:00+00:00", "last_preview": "Oi", "last_direction": "in", "unread_count": 1}
        touch = {"thread_id": "t1", "source": "META_ADS_WHATSAPP", "ad_id": "1", "headline": "Kit", "entry_code": None, "occurred_at": "x"}

        async def select(table, **kw):
            return {"whatsapp_numbers": [{"id": "n1"}], "whatsapp_threads": [thread], "whatsapp_origin_touches": [touch]}[table]
        with patch.object(wn, "sb_select", AsyncMock(side_effect=select)):
            out = asyncio.run(wn.conversations("roove"))
        conv = out["conversations"][0]
        self.assertEqual(conv["contact"]["phone_masked"], "•••• 1161")
        self.assertNotIn("wa_id", conv["contact"])
        self.assertEqual(conv["origin"]["ad_id"], "1")
        self.assertTrue(conv["service_window_expires_at"].startswith("2026-11-11T10:05"))

    def test_messages_scoped_to_company(self):
        with patch.object(wn, "sb_select", AsyncMock(return_value=[])):
            out = asyncio.run(wn.messages("roove", "b1281853-ab59-4fd2-b824-df88ebddabb6"))
        self.assertFalse(out["found"])


class SourceOrderTests(unittest.TestCase):
    def test_native_number_wins_over_crm(self):
        with patch.object(ws, "bridge_for", return_value=None), \
             patch.object(ws.whatsapp_native, "active_number_ids", AsyncMock(return_value=["n1"])), \
             patch.object(ws.whatsapp_native, "leads", AsyncMock(return_value={"available": True, "connected": True, "leads": []})) as native, \
             patch.object(ws.crm_bridge, "brand_leads", AsyncMock()) as crm:
            asyncio.run(ws.brand_leads("roove", "2026-11-01", "2026-11-07"))
        native.assert_awaited_once()
        crm.assert_not_awaited()

    def test_native_message_of_other_company_is_404(self):
        with patch.object(ws, "bridge_for", return_value=None), \
             patch.object(ws.whatsapp_native, "active_number_ids", AsyncMock(return_value=["n1"])), \
             patch.object(ws.whatsapp_native, "messages", AsyncMock(return_value={"available": True, "messages": [], "found": False})):
            with self.assertRaises(ws.StudioError):
                asyncio.run(ws.brand_messages("roove", "b1281853-ab59-4fd2-b824-df88ebddabb6"))


if __name__ == "__main__":
    unittest.main()
