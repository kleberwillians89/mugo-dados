"""Shopify App Proxy form intake: validation, persistence and no false success."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException
from starlette.requests import Request

from routes.roove_first_access import first_access


def request_with(data, *, content_type="application/x-www-form-urlencoded"):
    body = urlencode(data, doseq=True).encode()
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return Request({
        "type": "http", "method": "POST", "path": "/api/shopify/first-access",
        "query_string": b"",
        "headers": [
            (b"content-type", content_type.encode()),
            (b"content-length", str(len(body)).encode()),
        ],
    }, receive)


class FormIntakeTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_form_persists_and_returns_service_success(self):
        request = request_with({
            "name": "Ana Silva", "email": "ana@example.org", "phone": "11988887777",
            "event_id": "landing-abc", "consent_email": "sim",
            "consent_whatsapp": "", "consent_version": "roove-bf-2026-v1",
            "utm_source": "meta", "utm_medium": "paid",
        })
        with patch("routes.roove_first_access.verify_app_proxy_query", return_value="roove-test.myshopify.com"), \
             patch.dict("os.environ", {
                 "ROOVE_FIRST_ACCESS_SOURCE_ID": "source",
                 "ROOVE_FIRST_ACCESS_INGEST_KEY": "server-only-secret",
             }), \
             patch("routes.roove_first_access.lead_capture.ingest", new_callable=AsyncMock,
                   return_value={"ok": True, "duplicate": False}) as ingest:
            output = await first_access(request)
        self.assertTrue(output["ok"])
        args = ingest.await_args.args
        self.assertEqual(args[0], "source")
        self.assertEqual(args[1], "server-only-secret")
        self.assertEqual(args[2]["campaign"], "roove_first_access_2026")
        self.assertEqual(args[2]["utm_source"], "meta")
        self.assertEqual(args[2]["consent"], {"email": True, "whatsapp": False})

    async def test_json_request_is_not_accepted(self):
        with patch("routes.roove_first_access.verify_app_proxy_query"):
            with self.assertRaises(HTTPException) as err:
                await first_access(request_with({"name": "Ana"}, content_type="application/json"))
        self.assertEqual(err.exception.status_code, 415)

    async def test_repeated_fields_are_rejected(self):
        with patch("routes.roove_first_access.verify_app_proxy_query"):
            with self.assertRaises(HTTPException) as err:
                await first_access(request_with({
                    "name": ["Ana", "Outra"], "email": "ana@example.org", "phone": "11988887777"
                }))
        self.assertEqual(err.exception.status_code, 422)

    async def test_honeypot_is_not_saved(self):
        with patch("routes.roove_first_access.verify_app_proxy_query"), \
             patch("routes.roove_first_access.lead_capture.ingest", new_callable=AsyncMock) as ingest:
            response = await first_access(request_with({"website": "bot-site"}))
        ingest.assert_not_awaited()
        self.assertFalse(__import__("json").loads(response.body)["accepted"])

    async def test_database_failure_cannot_return_success(self):
        request = request_with({"name":"Ana Silva","email":"ana@example.org","phone":"11988887777"})
        with patch("routes.roove_first_access.verify_app_proxy_query"), \
             patch.dict("os.environ", {
                 "ROOVE_FIRST_ACCESS_SOURCE_ID":"source",
                 "ROOVE_FIRST_ACCESS_INGEST_KEY":"server-only-secret",
             }), \
             patch("routes.roove_first_access.lead_capture.ingest", new_callable=AsyncMock,
                   side_effect=RuntimeError("Database unavailable")):
            with self.assertRaises(RuntimeError):
                await first_access(request)


if __name__ == "__main__":
    unittest.main()
