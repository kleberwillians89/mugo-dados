import asyncio
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routes import platform_admin as routes
from services import platform_admin, fbits_connections as fbits, sync_locks
from services.fbits_customer_backfill import CustomerBackfillError

CID = "239dfdd2-5bb9-4cfd-a4ef-e05ca0b2de94"
PATH = "/api/platform/fbits/customer-identities/backfill"
BODY = {"client_id": CID, "confirm_client_id": CID}
COUNTS = {"orders_processed": 200, "identities_found": 170, "identities_persisted": 165, "identities_without_contact": 5, "errors": 0}


class PlatformBackfillRouteTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, *, role="platform_admin", payload=None, authorization="Bearer fake", operation=None, rows=None):
        app = FastAPI()
        app.include_router(routes.router)
        with (
            patch.object(routes, "get_user_id_from_bearer", AsyncMock(return_value="actor" if role else None)),
            patch.object(platform_admin, "require_user_id", AsyncMock(return_value="actor")),
            patch.object(platform_admin, "is_platform_admin", AsyncMock(return_value=role == "platform_admin")),
            patch("services.tenant._has_agency_admin_membership", AsyncMock(return_value=True)) as agency,
            patch.object(routes, "sb_select", AsyncMock(return_value=[{"id": CID}] if rows is None else rows)) as select,
            patch.object(routes, "backfill_customer_identities", operation or AsyncMock(return_value=COUNTS)) as backfill,
        ):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(PATH, json=BODY if payload is None else payload, headers={"Authorization": authorization} if authorization else {})
        self.backfill = backfill
        self.select = select
        self.agency = agency
        return response

    async def test_missing_authentication_is_blocked(self):
        response = await self.request(authorization=None)
        self.assertEqual(response.status_code, 401)
        self.backfill.assert_not_awaited()

    async def test_invalid_authentication_is_blocked_even_with_local_bypass(self):
        response = await self.request(role=None)
        self.assertEqual(response.status_code, 401)
        self.backfill.assert_not_awaited()

    async def test_viewer_is_blocked(self):
        self.assertEqual((await self.request(role="viewer")).status_code, 403)
        self.backfill.assert_not_awaited()

    async def test_agency_admin_is_blocked_without_agency_fallback(self):
        self.assertEqual((await self.request(role="agency_admin")).status_code, 403)
        self.agency.assert_not_awaited()
        self.backfill.assert_not_awaited()

    async def test_client_admin_is_blocked(self):
        self.assertEqual((await self.request(role="client_admin")).status_code, 403)
        self.backfill.assert_not_awaited()

    async def test_platform_admin_calls_exact_existing_service_for_explicit_tenant(self):
        response = await self.request()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), COUNTS)
        self.backfill.assert_awaited_once_with(client_id=CID, confirm_client_id=CID)
        self.assertEqual(self.select.await_args.kwargs["filters"], {"id": f"eq.{CID}"})

    async def test_client_id_is_required(self):
        self.assertEqual((await self.request(payload={})).status_code, 400)
        self.backfill.assert_not_awaited()

    async def test_global_or_unconfirmed_execution_is_rejected(self):
        for payload in ({"client_id": "all", "confirm_client_id": "all"}, {"client_id": CID, "confirm_client_id": "other"}):
            self.assertEqual((await self.request(payload=payload)).status_code, 400)
            self.backfill.assert_not_awaited()

    async def test_request_does_not_accept_secrets_or_extra_fields(self):
        response = await self.request(payload={**BODY, "token": "private"})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("private", response.text)
        self.backfill.assert_not_awaited()

    async def test_nonexistent_tenant_returns_safe_404(self):
        response = await self.request(rows=[])
        self.assertEqual(response.status_code, 404)
        self.backfill.assert_not_awaited()

    async def test_response_allowlist_excludes_pii_and_payload(self):
        response = await self.request(operation=AsyncMock(return_value={**COUNTS, "email": "private@example.com", "raw": {"name": "Private"}}))
        self.assertEqual(response.json(), COUNTS)
        self.assertNotIn("private", response.text.lower())

    async def test_fbits_failure_never_returns_false_success_or_exception_payload(self):
        response = await self.request(operation=AsyncMock(side_effect=RuntimeError("private@example.com")))
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("private", response.text)

    async def test_timeout_and_lock_conflict_have_explicit_safe_status(self):
        for status, code in ((504, "FBITS_CUSTOMER_BACKFILL_TIMEOUT"), (409, "FBITS_CUSTOMER_BACKFILL_BUSY"), (429, "FBITS_CUSTOMER_BACKFILL_RATE_LIMITED")):
            response = await self.request(operation=AsyncMock(side_effect=CustomerBackfillError(counts={**COUNTS, "errors": 1}, status_code=status, code=code)))
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["detail"]["code"], code)

    async def test_nonzero_error_count_is_not_success(self):
        response = await self.request(operation=AsyncMock(return_value={**COUNTS, "errors": 1}))
        self.assertEqual(response.status_code, 502)

    async def test_get_is_not_allowed(self):
        app = FastAPI()
        app.include_router(routes.router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            self.assertEqual((await client.get(PATH)).status_code, 405)

    async def test_concurrent_calls_use_existing_backfill_and_shared_fbits_lock(self):
        from services.fbits_customer_backfill import backfill_customer_identities
        entered, finish = asyncio.Event(), asyncio.Event()
        held = False
        async def acquire(*args):
            nonlocal held
            if held:
                return False
            held = True
            return True
        async def release(*args):
            nonlocal held
            held = False
        async def select(table, **kwargs):
            entered.set()
            await finish.wait()
            return [{"client_id": CID, "order_date": "2026-10-01T00:00:00Z"}]
        connection = {"id": "conn", "client_id": CID, "provider": "fbits", "status": "connected"}
        with (
            patch.object(fbits, "load_fbits_connection", AsyncMock(return_value=connection)),
            patch.object(fbits, "sb_select", AsyncMock(side_effect=select)),
            patch.object(fbits, "get_connection", AsyncMock(return_value={})),
            patch.object(sync_locks, "acquire_sync_lock", acquire),
            patch.object(sync_locks, "release_sync_lock", release),
            redirect_stdout(io.StringIO()),
        ):
            first = asyncio.create_task(backfill_customer_identities(client_id=CID, confirm_client_id=CID))
            await asyncio.wait_for(entered.wait(), timeout=2)
            try:
                with self.assertRaises(CustomerBackfillError) as raised:
                    await backfill_customer_identities(client_id=CID, confirm_client_id=CID)
                self.assertEqual(raised.exception.status_code, 409)
            finally:
                finish.set()
                with self.assertRaises(CustomerBackfillError):
                    await first
            self.assertFalse(held)

    async def test_unexpected_timeout_does_not_become_generic_success(self):
        response = await self.request(operation=AsyncMock(side_effect=TimeoutError("private")))
        self.assertEqual(response.status_code, 504)
        self.assertNotIn("private", response.text)

    async def test_existing_service_timeout_is_translated_without_private_details(self):
        from services.fbits_customer_backfill import backfill_customer_identities
        with patch.object(fbits, "load_fbits_connection", AsyncMock(side_effect=TimeoutError("private"))), redirect_stdout(io.StringIO()):
            with self.assertRaises(CustomerBackfillError) as raised:
                await backfill_customer_identities(client_id=CID, confirm_client_id=CID)
        self.assertEqual(raised.exception.status_code, 504)
        self.assertEqual(raised.exception.counts["errors"], 1)
        self.assertNotIn("private", str(raised.exception))
