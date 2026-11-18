"""Registro Cloud API da Roove: leitura segura, consentimento e proteção do número principal."""
import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services import whatsapp_native as wn

ROW = {
    "id": "00000000-0000-4000-8000-000000000001",
    "client_id": "roove",
    "waba_id": "1491824329400600",
    "phone_number_id": "1063683626819387",
    "meta_app_id": "1161210926623351",
    "status": "active",
    "access_token": "EAAG" + "x" * 60,
}
PHONE = ROW["id"]


async def fake_graph(method, path, token, params=None, json_body=None):
    if method == "GET" and path == "1491824329400600/phone_numbers":
        return {"data": [{"id": ROW["phone_number_id"], "display_phone_number": "+55 11 94470-6392",
                          "status": "OFFLINE", "code_verification_status": "VERIFIED"}]}
    if method == "POST" and path == "1063683626819387/register":
        return {"success": True}
    raise AssertionError((method, path))


class RegistrationTests(unittest.TestCase):
    def test_status_is_read_only_and_never_exposes_token(self):
        with patch.object(wn, "sb_select", AsyncMock(return_value=[ROW])) as select, \
             patch.object(wn, "_graph", AsyncMock(side_effect=fake_graph)) as graph:
            out = asyncio.run(wn.get_roove_registration_status("roove", PHONE))
        self.assertEqual(out["status"], "OFFLINE")
        self.assertTrue(out["can_register"])
        self.assertFalse(out["registered_by_this_request"])
        self.assertNotIn("access_token", out)
        self.assertEqual([c.args[0] for c in graph.await_args_list], ["GET"])
        self.assertEqual(select.await_args.kwargs["filters"]["client_id"], "eq.roove")

    def test_register_requires_confirmation_without_any_meta_call(self):
        with patch.object(wn, "_graph", AsyncMock()) as graph:
            with self.assertRaises(wn.WhatsAppNativeError) as ctx:
                asyncio.run(wn.register_roove_cloud_number("roove", PHONE, pin="123456", confirmed=False))
        self.assertEqual(ctx.exception.code, "CONFIRMATION_REQUIRED")
        graph.assert_not_awaited()

    def test_invalid_pin_blocks_without_any_meta_call(self):
        with patch.object(wn, "_graph", AsyncMock()) as graph:
            for pin in ("12345", "1234567", "qwerty", "12 456"):
                with self.assertRaises(wn.WhatsAppNativeError):
                    asyncio.run(wn.register_roove_cloud_number("roove", PHONE, pin=pin, confirmed=True))
        graph.assert_not_awaited()

    def test_blocks_other_tenant_and_number_before_any_meta_call(self):
        with patch.object(wn, "sb_select", AsyncMock(return_value=[ROW])) as select, \
             patch.object(wn, "_graph", AsyncMock()) as graph:
            for cid, nid in (
                ("mugo", PHONE),
                ("roove", "00000000-0000-4000-8000-000000000002"),
            ):
                with self.assertRaises(wn.WhatsAppNativeError):
                    asyncio.run(wn.register_roove_cloud_number(cid, nid, pin="123456", confirmed=True))
        graph.assert_not_awaited()

    def test_rejects_primary_phone_even_if_row_claims_roove(self):
        row = {**ROW, "phone_number_id": "999999999999999"}
        with patch.object(wn, "sb_select", AsyncMock(return_value=[row])), \
             patch.object(wn, "_graph", AsyncMock()) as graph:
            with self.assertRaises(wn.WhatsAppNativeError):
                asyncio.run(wn.register_roove_cloud_number("roove", PHONE, pin="123456", confirmed=True))
        graph.assert_not_awaited()

    def test_approved_request_posts_only_secondary_number_with_stored_token(self):
        with patch.object(wn, "sb_select", AsyncMock(return_value=[ROW])), \
             patch.object(wn, "_graph", AsyncMock(side_effect=fake_graph)) as graph:
            out = asyncio.run(wn.register_roove_cloud_number("roove", PHONE, pin="123456", confirmed=True))
        self.assertTrue(out["registered_by_this_request"])
        self.assertEqual([c.args[0] for c in graph.await_args_list], ["GET", "POST"])
        post = graph.await_args_list[1]
        self.assertEqual(post.args[1], "1063683626819387/register")
        self.assertEqual(post.args[2], ROW["access_token"])
        self.assertEqual(post.kwargs["json_body"], {"messaging_product": "whatsapp", "pin": "123456"})
        self.assertNotIn("pin", out)

    def test_connected_number_is_idempotent_and_not_registered_again(self):
        async def connected(method, path, token, params=None, json_body=None):
            return {"data": [{"id": ROW["phone_number_id"], "status": "CONNECTED"}]}
        with patch.object(wn, "sb_select", AsyncMock(return_value=[ROW])), \
             patch.object(wn, "_graph", AsyncMock(side_effect=connected)) as graph:
            out = asyncio.run(wn.register_roove_cloud_number("roove", PHONE, pin="123456", confirmed=True))
        self.assertTrue(out["already_connected"])
        graph.assert_awaited_once()

    def test_unknown_status_fails_closed(self):
        async def unknown(method, path, token, params=None, json_body=None):
            return {"data": [{"id": ROW["phone_number_id"], "status": "SUSPENDED"}]}
        with patch.object(wn, "sb_select", AsyncMock(return_value=[ROW])), \
             patch.object(wn, "_graph", AsyncMock(side_effect=unknown)) as graph:
            with self.assertRaises(wn.WhatsAppNativeError) as ctx:
                asyncio.run(wn.register_roove_cloud_number("roove", PHONE, pin="123456", confirmed=True))
        self.assertEqual(ctx.exception.code, "REGISTRATION_UNSAFE")
        graph.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
