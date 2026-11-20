"""Tests for public RUAH landing capture. No live traffic or leads."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException
from starlette.requests import Request
from routes.ruah_public_capture import ruah_bf_leads

SOURCE = "11111111-1111-4111-8111-111111111111"
SETTINGS = {
    "RUAH_BF_CLIENT_ID": "ruah",
    "RUAH_BF_SOURCE_ID": SOURCE,
    "RUAH_BF_INGEST_KEY": "x" * 50,
    "RUAH_BF_TURNSTILE_SECRET": "server-only-secret",
}
FORM = {
    "name": "Cliente Teste",
    "email": "cliente@example.org",
    "phone": "11999999999",
    "campaign": "ruah_black_friday_2026",
    "event_id": "test-event-001",
    "utm_source": "meta",
    "utm_medium": "paid_social",
    "utm_campaign": "ruah_black_friday_2026",
    "consent_whatsapp": "sim",
    "cf-turnstile-response": "captcha",
}

def request(form=None, origin="https://ruahparfums.com.br"):
    raw = urlencode(form or FORM).encode()
    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}
    return Request({
        "type": "http", "method": "POST", "path": "/api/public/ruah-bf/leads",
        "headers": [(b"origin", origin.encode()), (b"content-type", b"application/x-www-form-urlencoded"),
                    (b"content-length", str(len(raw)).encode())],
        "client": ("127.0.0.1", 12345),
        "query_string": b"",
    }, receive)


class PublicRuahCaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_non_storefront_origin(self):
        with self.assertRaises(HTTPException) as caught:
            await ruah_bf_leads(request(origin="https://another-shop.com"))
        self.assertEqual(caught.exception.status_code, 403)

    async def test_missing_configuration_fails_closed(self):
        with patch.dict("os.environ", {key: "" for key in SETTINGS}):
            with self.assertRaises(HTTPException) as caught:
                await ruah_bf_leads(request())
        self.assertEqual(caught.exception.status_code, 503)

    async def test_honeypot_does_not_persist(self):
        with patch("routes.ruah_public_capture.lead_capture._ingest_authenticated", new_callable=AsyncMock) as ingest:
            response = await ruah_bf_leads(request({**FORM, "website": "bad-bot"}))
        self.assertEqual(response.status_code, 200)
        ingest.assert_not_awaited()

    async def test_bad_captcha_rejected_before_database(self):
        with patch.dict("os.environ", SETTINGS), \
             patch("routes.ruah_public_capture._turnstile_valid", new_callable=AsyncMock, return_value=False), \
             patch("routes.ruah_public_capture.lead_capture._authenticate", new_callable=AsyncMock) as auth:
            with self.assertRaises(HTTPException) as caught:
                await ruah_bf_leads(request())
        self.assertEqual(caught.exception.status_code, 422)
        auth.assert_not_awaited()

    async def test_mismatched_tenant_fails_closed(self):
        with patch.dict("os.environ", SETTINGS), \
             patch("routes.ruah_public_capture._turnstile_valid", new_callable=AsyncMock, return_value=True), \
             patch("routes.ruah_public_capture.lead_capture._authenticate", new_callable=AsyncMock, return_value={"id": SOURCE, "client_id": "roove"}), \
             patch("routes.ruah_public_capture.lead_capture._ingest_authenticated", new_callable=AsyncMock) as ingest:
            with self.assertRaises(HTTPException) as caught:
                await ruah_bf_leads(request())
        self.assertEqual(caught.exception.status_code, 503)
        ingest.assert_not_awaited()

    async def test_valid_submission_is_tenant_bound_and_opt_in_unverified(self):
        with patch.dict("os.environ", SETTINGS), \
             patch("routes.ruah_public_capture._turnstile_valid", new_callable=AsyncMock, return_value=True), \
             patch("routes.ruah_public_capture.lead_capture._authenticate", new_callable=AsyncMock, return_value={"id": SOURCE, "client_id": "ruah"}), \
             patch("routes.ruah_public_capture.lead_capture._ingest_authenticated", new_callable=AsyncMock, return_value={"ok": True, "duplicate": False}) as ingest:
            result = await ruah_bf_leads(request())
        payload = ingest.await_args.args[1]
        self.assertTrue(result["ok"])
        self.assertTrue(result["accepted"])
        self.assertEqual(payload["campaign"], "ruah_black_friday_2026")
        self.assertEqual(payload["utm_source"], "meta")
        self.assertEqual(payload["consent"], {"email": False, "whatsapp": True})

    async def test_unrecognized_campaign_rejected(self):
        with patch.dict("os.environ", SETTINGS), \
             patch("routes.ruah_public_capture._turnstile_valid", new_callable=AsyncMock) as captcha:
            with self.assertRaises(HTTPException) as caught:
                await ruah_bf_leads(request({**FORM, "campaign": "another_campaign"}))
        self.assertEqual(caught.exception.status_code, 422)
        captcha.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
