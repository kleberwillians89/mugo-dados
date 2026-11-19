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


class VerificationTests(unittest.TestCase):
    def test_request_requires_confirmation_without_graph_calls(self):
        with patch.object(wn, "_graph", AsyncMock()) as graph, \
             patch.object(wn, "sb_select", AsyncMock()) as select:
            with self.assertRaises(wn.WhatsAppNativeError) as err:
                asyncio.run(wn.request_roove_verification_code("roove", PHONE, method="SMS", confirmed=False))
        self.assertEqual(err.exception.code, "CONFIRMATION_REQUIRED")
        graph.assert_not_awaited()
        select.assert_not_awaited()

    def test_request_sms_uses_only_roove_secondary_number(self):
        with patch.object(wn, "sb_select", AsyncMock(return_value=[ROW])), \
             patch.object(wn, "_graph", AsyncMock(side_effect=fake_graph_verify)) as graph:
            out = asyncio.run(wn.request_roove_verification_code("roove", PHONE, method="SMS", confirmed=True))
        self.assertTrue(out["requested"])
        self.assertEqual(graph.await_args_list[1].args[1], "1063683626819387/request_code")
        self.assertEqual(graph.await_args_list[1].kwargs["json_body"], {"code_method": "SMS", "locale": "pt_BR"})

    def test_request_rejects_verified_status_and_does_not_send(self):
        async def verified(method, path, token, params=None, json_body=None):
            return {"data": [{"id": ROW["phone_number_id"], "status": "DISCONNECTED",
                              "code_verification_status": "VERIFIED"}]}
        with patch.object(wn, "sb_select", AsyncMock(return_value=[ROW])), \
             patch.object(wn, "_graph", AsyncMock(side_effect=verified)) as graph:
            with self.assertRaises(wn.WhatsAppNativeError) as err:
                asyncio.run(wn.request_roove_verification_code("roove", PHONE, method="VOICE", confirmed=True))
        self.assertEqual(err.exception.code, "ALREADY_VERIFIED")
        graph.assert_awaited_once()

    def test_verify_code_never_exposes_received_otp(self):
        with patch.object(wn, "sb_select", AsyncMock(return_value=[ROW])), \
             patch.object(wn, "_graph", AsyncMock(side_effect=fake_graph_verify)) as graph:
            out = asyncio.run(wn.verify_roove_verification_code("roove", PHONE, code="483719", confirmed=True))
        self.assertTrue(out["verified"])
        self.assertNotIn("code", out)
        self.assertEqual(graph.await_args_list[1].args[1], "1063683626819387/verify_code")
        self.assertEqual(graph.await_args_list[1].kwargs["json_body"], {"code": "483719"})

    def test_verify_refuses_wrong_tenant_and_bad_code(self):
        with patch.object(wn, "_graph", AsyncMock()) as graph, \
             patch.object(wn, "sb_select", AsyncMock(return_value=[ROW])) as select:
            with self.assertRaises(wn.WhatsAppNativeError):
                asyncio.run(wn.verify_roove_verification_code("another", PHONE, code="483719", confirmed=True))
            with self.assertRaises(wn.WhatsAppNativeError):
                asyncio.run(wn.verify_roove_verification_code("roove", PHONE, code="abc", confirmed=True))
        graph.assert_not_awaited()


async def fake_graph_verify(method, path, token, params=None, json_body=None):
    if method == "GET":
        return {"data": [{"id": ROW["phone_number_id"], "status": "DISCONNECTED",
                          "code_verification_status": "EXPIRED"}]}
    if method == "POST" and path in ("1063683626819387/request_code", "1063683626819387/verify_code"):
        return {"success": True}
    raise AssertionError((method, path))




class GraphErrorDiagnosticsTests(unittest.TestCase):
    def test_otp_error_100_not_misreported_as_wrong_id(self):
        import httpx
        from unittest.mock import Mock
        request = httpx.Request("POST", "https://graph.facebook.com/v23.0/1063683626819387/request_code")
        response = httpx.Response(
            400, request=request,
            json={"error": {"code": 100, "error_subcode": 33, "message": "private upstream detail"}},
        )
        fake_client = Mock()
        fake_client.request = AsyncMock(return_value=response)
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=None)
        with patch.object(wn.httpx, "AsyncClient", return_value=fake_client):
            with self.assertRaises(wn.WhatsAppNativeError) as ctx:
                asyncio.run(wn._graph("POST", "1063683626819387/request_code", "secret-token",
                                      json_body={"code_method": "SMS", "locale": "pt_BR"}))
        self.assertEqual(ctx.exception.code, "META_REQUEST_INVALID")
        self.assertIn("Meta #100", ctx.exception.message)
        self.assertIn("subcódigo 33", ctx.exception.message)
        self.assertNotIn("private upstream detail", ctx.exception.message)
        self.assertNotIn("secret-token", ctx.exception.message)

    def test_normal_get_error_100_keeps_legacy_id_diagnostic(self):
        import httpx
        from unittest.mock import Mock
        request = httpx.Request("GET", "https://graph.facebook.com/v23.0/invalid")
        response = httpx.Response(400, request=request, json={"error": {"code": 100}})
        fake_client = Mock()
        fake_client.request = AsyncMock(return_value=response)
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=None)
        with patch.object(wn.httpx, "AsyncClient", return_value=fake_client):
            with self.assertRaises(wn.WhatsAppNativeError) as ctx:
                asyncio.run(wn._graph("GET", "invalid", "secret-token"))
        self.assertEqual(ctx.exception.code, "NOT_FOUND")



class SafeMetaReasonTests(unittest.TestCase):
    def test_identifies_unsupported_operation_without_echoing_sensitive_details(self):
        detail = "Unsupported post request. Object with ID '1063683626819387' does not support this operation. token EAAGsecret"
        reason, trace = wn._safe_meta_operation_diagnostic({
            "message": detail, "fbtrace_id": "AqBcDfGh12345",
        })
        self.assertEqual(reason, "operacao_nao_suportada")
        self.assertEqual(trace, "AqBcDfGh12345")
        self.assertNotIn("1063683626819387", reason)
        self.assertNotIn("EAAG", reason)

    def test_untrusted_trace_rejected(self):
        reason, trace = wn._safe_meta_operation_diagnostic({
            "message": "Invalid parameter: locale", "fbtrace_id": "token secret!\nprivate",
        })
        self.assertEqual(reason, "idioma_ou_locale")
        self.assertEqual(trace, "")

    def test_meta_100_returns_categorized_diagnostic_without_raw_error(self):
        import httpx
        from unittest.mock import Mock
        request = httpx.Request("POST", "https://graph.facebook.com/v23.0/1063683626819387/request_code")
        response = httpx.Response(
            400, request=request,
            json={"error": {
                "code": 100, "message": "Unsupported post request for token SECRETDO_NOT_LEAK",
                "fbtrace_id": "AbCdEf123456",
            }},
        )
        fake_client = Mock()
        fake_client.request = AsyncMock(return_value=response)
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=None)
        with patch.object(wn.httpx, "AsyncClient", return_value=fake_client):
            with self.assertRaises(wn.WhatsAppNativeError) as ctx:
                asyncio.run(wn._graph("POST", "1063683626819387/request_code", "secret-token",
                                      json_body={"code_method": "SMS", "locale": "pt_BR"}))
        self.assertEqual(ctx.exception.code, "META_REQUEST_INVALID")
        self.assertIn("motivo=operacao_nao_suportada", ctx.exception.message)
        self.assertIn("trace=AbCdEf123456", ctx.exception.message)
        self.assertNotIn("SECRETDO_NOT_LEAK", ctx.exception.message)



if __name__ == "__main__":
    unittest.main()
