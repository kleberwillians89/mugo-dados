"""Reusable Shopify capture security: signed shops and tenant-scoped sources."""
import hashlib
import hmac
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException, FastAPI
from fastapi.routing import APIRoute
from starlette.requests import Request
from starlette.routing import Match

from routes.roove_first_access import generic_shopify_lead_capture, verify_shopify_proxy_signature
from services import lead_capture as lc


def signed_request(shop: str, form: dict, *, secret="test-shopify-app-secret"):
    params = {"shop": shop, "timestamp": str(int(time.time())), "path_prefix": "/apps/mugo-first-access"}
    msg = "".join(f"{key}={params[key]}" for key in sorted(params))
    params["signature"] = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    body = urlencode(form).encode()
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return Request({
        "type": "http", "method": "POST", "path": "/api/shopify/lead-capture",
        "query_string": urlencode(params).encode(),
        "headers": [(b"content-type", b"application/x-www-form-urlencoded"),(b"content-length",str(len(body)).encode())],
    }, receive)


class ShopifyProxyCaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_proxy_paths_match_without_redirect(self):
        from routes.roove_first_access import router
        app = FastAPI()
        app.include_router(router)
        for path in ("/api/shopify/lead-capture", "/api/shopify/lead-capture/"):
            scope = {"type": "http", "method": "POST", "path": path, "root_path": ""}
            matches = [route for route in app.routes if isinstance(route, APIRoute) and route.matches(scope)[0] == Match.FULL]
            self.assertEqual(len(matches), 1, f"{path} must resolve without a redirect")
            self.assertEqual(matches[0].endpoint, generic_shopify_lead_capture)

    async def test_campaign_from_signed_store(self):
        form = {
            "name": "Cliente Teste", "email": "cliente@example.org", "phone": "11912345678",
            "campaign": "first_access_bf_2026", "event_id": "test-evt-1",
            "utm_source": "instagram", "utm_medium": "paid_social",
            "consent_email": "sim", "consent_whatsapp": "",
        }
        req = signed_request("roove-test.myshopify.com", form)
        with patch.dict("os.environ", {"SHOPIFY_MUGO_METRICS_CLIENT_SECRET": "test-shopify-app-secret", "SHOPIFY_CLIENT_SECRET": "unrelated-oauth-secret"}), \
             patch("routes.roove_first_access.lead_capture.ingest_shopify_proxy", new_callable=AsyncMock,
                   return_value={"ok": True, "duplicate": False}) as ingest:
            result = await generic_shopify_lead_capture(req)
        self.assertTrue(result["ok"])
        self.assertEqual(ingest.await_args.args[0], "roove-test.myshopify.com")
        self.assertEqual(ingest.await_args.args[1]["campaign"], "first_access_bf_2026")
        self.assertEqual(ingest.await_args.args[1]["consent"]["whatsapp"], False)

    async def test_fails_closed_when_dedicated_secret_missing(self):
        req = signed_request("roove-test.myshopify.com", {
            "name": "Ana Silva", "email": "ana@example.org", "phone": "11988887777",
            "event_id": "event-1", "campaign": "roove_first_access_2026"
        })
        with patch.dict("os.environ", {
            "SHOPIFY_CLIENT_SECRET": "test-shopify-app-secret",
            "SHOPIFY_MUGO_METRICS_CLIENT_SECRET": ""
        }), patch("routes.roove_first_access.lead_capture.ingest_shopify_proxy",
                  new_callable=AsyncMock) as ingest:
            with self.assertRaises(HTTPException) as caught:
                await generic_shopify_lead_capture(req)
        self.assertEqual(caught.exception.status_code, 503)
        ingest.assert_not_awaited()

    async def test_unrelated_oauth_secret_is_not_accepted_for_proxy(self):
        req = signed_request("roove-test.myshopify.com", {
            "name": "Ana Silva", "email": "ana@example.org", "phone": "11988887777",
            "event_id": "event-2", "campaign": "roove_first_access_2026"
        }, secret="legacy-oauth-secret")
        with patch.dict("os.environ", {
            "SHOPIFY_CLIENT_SECRET": "legacy-oauth-secret",
            "SHOPIFY_MUGO_METRICS_CLIENT_SECRET": "metrics-proxy-secret"
        }), patch("routes.roove_first_access.lead_capture.ingest_shopify_proxy",
                  new_callable=AsyncMock) as ingest:
            with self.assertRaises(HTTPException) as caught:
                await generic_shopify_lead_capture(req)
        self.assertEqual(caught.exception.status_code, 401)
        ingest.assert_not_awaited()

    async def test_unsigned_request_cannot_reach_database(self):
        req = signed_request("evil.myshopify.com", {"name":"Ana"})
        req.scope["query_string"] = req.scope["query_string"] + b"&changed=true"
        with patch.dict("os.environ", {"SHOPIFY_MUGO_METRICS_CLIENT_SECRET": "test-shopify-app-secret", "SHOPIFY_CLIENT_SECRET": "unrelated-oauth-secret"}), \
             patch("routes.roove_first_access.lead_capture.ingest_shopify_proxy",new_callable=AsyncMock) as ingest:
            with self.assertRaises(HTTPException) as caught:
                await generic_shopify_lead_capture(req)
        self.assertEqual(caught.exception.status_code, 401)
        ingest.assert_not_awaited()

    async def test_unknown_shop_rejected_before_source_provision(self):
        with patch("services.shopify_oauth.resolve_store_by_domain",new_callable=AsyncMock,return_value=None), \
             patch.object(lc,"create_source",new_callable=AsyncMock) as create:
            with self.assertRaises(lc.LeadCaptureError) as caught:
                await lc.ingest_shopify_proxy("unknown.myshopify.com",{"event_id":"x"})
        self.assertEqual(caught.exception.status, 403)
        create.assert_not_awaited()

    async def test_inactive_shop_rejected(self):
        with patch("services.shopify_oauth.resolve_store_by_domain",new_callable=AsyncMock,
                   return_value={"client_id":"roove","status":"uninstalled"}), \
             patch.object(lc,"create_source",new_callable=AsyncMock) as create:
            with self.assertRaises(lc.LeadCaptureError):
                await lc.ingest_shopify_proxy("uninstalled.myshopify.com",{"event_id":"x"})
        create.assert_not_awaited()

    async def test_existing_source_is_reused_only_within_store_tenant(self):
        store = {"client_id":"roove","status":"active"}
        rows = [{"id":"source-roove","client_id":"roove","name":"Shopify Landing Pages","active":True}]
        with patch("services.shopify_oauth.resolve_store_by_domain",new_callable=AsyncMock,return_value=store), \
             patch.object(lc,"sb_select",new_callable=AsyncMock,return_value=rows) as select, \
             patch.object(lc,"create_source",new_callable=AsyncMock) as create, \
             patch.object(lc,"_ingest_authenticated",new_callable=AsyncMock,return_value={"ok":True}) as ingest:
            result = await lc.ingest_shopify_proxy("roove.myshopify.com",{"event_id":"one"})
        self.assertTrue(result["ok"])
        self.assertEqual(select.await_args.kwargs["filters"]["client_id"],"eq.roove")
        self.assertEqual(ingest.await_args.args[0]["client_id"],"roove")
        create.assert_not_awaited()

    async def test_initial_capture_creates_one_deterministic_source(self):
        with patch("services.shopify_oauth.resolve_store_by_domain",new_callable=AsyncMock,
                   return_value={"client_id":"new-client","status":"active"}), \
             patch.object(lc,"sb_select",new_callable=AsyncMock,return_value=[]), \
             patch.object(lc,"sb_insert",new_callable=AsyncMock) as insert, \
             patch.object(lc,"_ingest_authenticated",new_callable=AsyncMock,
                   return_value={"ok":True,"duplicate":False}) as ingest:
            result = await lc.ingest_shopify_proxy("other.myshopify.com",{"event_id":"a"})
        self.assertNotIn("ingest_key",result)
        row = insert.await_args.args[1]
        self.assertEqual(row["client_id"],"new-client")
        self.assertEqual(row["name"],"Shopify Landing Pages")
        self.assertEqual(ingest.await_args.args[0]["client_id"],"new-client")
        self.assertEqual(ingest.await_args.args[0]["id"],row["id"])

    async def test_disabled_auto_source_is_not_reenabled(self):
        with patch("services.shopify_oauth.resolve_store_by_domain",new_callable=AsyncMock,
                   return_value={"client_id":"disabled","status":"active"}), \
             patch.object(lc,"sb_select",new_callable=AsyncMock,side_effect=[
                [],[{"id":"existing","client_id":"disabled","active":False}]
             ]), \
             patch.object(lc,"sb_insert",new_callable=AsyncMock) as insert:
            with self.assertRaises(lc.LeadCaptureError) as caught:
                await lc.ingest_shopify_proxy("disabled.myshopify.com",{"event_id":"a"})
        self.assertEqual(caught.exception.status,409)
        insert.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
