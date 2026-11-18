"""First Access regression: signature + campaign metrics without sending messages."""
import hashlib
import hmac
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from starlette.requests import Request
from fastapi import HTTPException
from routes.roove_first_access import verify_app_proxy_query
from services import lead_capture


def signed_request(shop="roove-test.myshopify.com", **changes):
    values = {"shop": shop, "timestamp": str(int(time.time())), "path_prefix": "/apps/mugo-first-access"}
    values.update(changes)
    message = "".join(f"{key}={values[key]}" for key in sorted(values))
    values["signature"] = hmac.new(b"test-secret", message.encode(), hashlib.sha256).hexdigest()
    return Request({"type": "http", "method": "POST", "path": "/api/shopify/first-access",
                    "query_string": urlencode(values).encode(), "headers": []})


class ProxySecurityTests(unittest.TestCase):
    def test_signed_allowed_shop(self):
        with patch.dict(os.environ, {"SHOPIFY_CLIENT_SECRET": "test-secret",
                                     "ROOVE_FIRST_ACCESS_SHOP_DOMAIN": "roove-test.myshopify.com"}):
            self.assertEqual(verify_app_proxy_query(signed_request()), "roove-test.myshopify.com")

    def test_other_store_is_blocked_even_with_valid_signature(self):
        with patch.dict(os.environ, {"SHOPIFY_CLIENT_SECRET": "test-secret",
                                     "ROOVE_FIRST_ACCESS_SHOP_DOMAIN": "roove-test.myshopify.com"}):
            with self.assertRaises(HTTPException) as ctx:
                verify_app_proxy_query(signed_request("unrelated.myshopify.com"))
            self.assertEqual(ctx.exception.status_code, 403)

    def test_signature_tampering_is_blocked(self):
        with patch.dict(os.environ, {"SHOPIFY_CLIENT_SECRET": "test-secret",
                                     "ROOVE_FIRST_ACCESS_SHOP_DOMAIN": "roove-test.myshopify.com"}):
            signed = signed_request()
            query = signed.scope["query_string"] + b"&campaign=other"
            signed.scope["query_string"] = query
            with self.assertRaises(HTTPException) as ctx:
                verify_app_proxy_query(signed)
            self.assertEqual(ctx.exception.status_code, 401)


class CampaignMetricsTests(unittest.IsolatedAsyncioTestCase):
    async def test_counts_are_scoped_and_opt_in_is_not_verified(self):
        items = [
            {"email_hash": "a", "phone_hash": "x", "consent_email_claimed": True,
             "consent_whatsapp_claimed": True, "consent_verified": False,
             "utm_source": "instagram", "created_at": "2026-11-18T13:00:00Z"},
            {"email_hash": "a", "phone_hash": "x", "consent_email_claimed": True,
             "consent_whatsapp_claimed": False, "consent_verified": False,
             "utm_source": "instagram", "created_at": "2026-11-18T13:05:00Z"},
            {"email_hash": "b", "phone_hash": "y", "consent_email_claimed": False,
             "consent_whatsapp_claimed": True, "consent_verified": False,
             "utm_source": "ads", "created_at": "2026-11-19T13:00:00Z"},
        ]
        with patch("services.sales_by_origin._paged", new_callable=AsyncMock, return_value=(items, False)) as page:
            out = await lead_capture.campaign_summary("roove", "roove_first_access_2026")
        self.assertEqual(page.await_args.kwargs["filters"]["client_id"], "eq.roove")
        self.assertEqual(out["total"], 3)
        self.assertEqual(out["unique"], 2)
        self.assertEqual(out["email_opt_in_claimed"], 2)
        self.assertEqual(out["whatsapp_opt_in_claimed"], 2)
        self.assertEqual(out["pending_validation"], 3)
        self.assertFalse(out["sending_enabled"])


if __name__ == "__main__":
    unittest.main()
