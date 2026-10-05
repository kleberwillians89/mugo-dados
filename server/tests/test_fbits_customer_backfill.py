import asyncio
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import customers, sync_locks, fbits_connections as fbits
from services.fbits_customer_backfill import CustomerBackfillError, backfill_customer_identities
from test_fbits_customer_identity import order, no_lock

TENANT = "239dfdd2-5bb9-4cfd-a4ef-e05ca0b2de94"
OTHER = "7f98cf6e-bfab-4157-bbb4-77cc98d374b1"


class BackfillTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.identities = {}
        self.pages = [[order(customer_id=1)], [order(customer_id=2)]]
        self.connection = {"id": "connection", "client_id": TENANT, "provider": "fbits", "status": "connected", "_token": json.dumps({"token": "fake-test-only"})}
        self.calls = []
        self.windows = []
        self.fail_persistence = False

    async def select(self, table, **kwargs):
        self.calls.append((table, kwargs))
        if table == "fbits_orders":
            return [{"client_id": TENANT, "order_date": "2026-10-01T00:00:00Z"}]
        return list(self.identities.values())

    async def upsert(self, table, rows, on_conflict):
        self.assertEqual(table, "fbits_customers")
        self.assertEqual(on_conflict, "client_id,fbits_customer_id")
        if self.fail_persistence:
            raise RuntimeError("private payload must not be logged")
        for row in rows:
            self.assertEqual(row["client_id"], TENANT)
            self.identities[(row["client_id"], row["fbits_customer_id"])] = dict(row)

    async def run_backfill(self):
        outer = self
        class Client:
            async def iter_order_pages(self, **kwargs):
                outer.windows.append(kwargs)
                for page in outer.pages:
                    yield page
        with (
            patch.object(fbits, "load_fbits_connection", AsyncMock(return_value=self.connection)),
            patch.object(fbits, "get_connection", AsyncMock(return_value=self.connection)),
            patch.object(fbits, "guarded_sync", no_lock),
            patch.object(fbits, "sb_select", AsyncMock(side_effect=self.select)),
            patch.object(fbits, "sb_upsert", AsyncMock(side_effect=self.upsert)),
            patch.object(fbits, "sb_update", AsyncMock(side_effect=AssertionError("No sync markers"))),
            redirect_stdout(io.StringIO()) as output,
        ):
            try:
                result = await backfill_customer_identities(client_id=TENANT, confirm_client_id=TENANT, client_factory=lambda _: Client())
            finally:
                self.log = output.getvalue()
        self.log = output.getvalue()
        return result

    async def test_multiple_pages_populate_only_identities_using_history_filter(self):
        result = await self.run_backfill()
        self.assertEqual(len(self.identities), 2)
        self.assertEqual(result["orders_processed"], 2)
        self.assertEqual(result["identities_persisted"], 2)
        self.assertTrue(all(window["date_filter"] == "DataPedido" for window in self.windows))
        self.assertTrue(all(call[1]["filters"]["client_id"] == f"eq.{TENANT}" for call in self.calls))

    async def test_reexecution_is_idempotent_and_homonyms_remain_separate(self):
        await self.run_backfill()
        await self.run_backfill()
        self.assertEqual(len(self.identities), 2)
        self.assertEqual({row["fbits_customer_id"] for row in self.identities.values()}, {"1", "2"})

    async def test_existing_contacts_survive_partial_and_conflicting_payloads(self):
        original = fbits.normalize_customer(TENANT, order(customer_id=1))
        self.identities[(TENANT, "1")] = original.copy()
        self.pages = [[order(customer_id=1, name="Changed", email=None, phone=None)]]
        await self.run_backfill()
        for field in ("name", "email", "phone"):
            self.assertEqual(self.identities[(TENANT, "1")][field], original[field])

    async def test_absent_contact_or_external_id_does_not_create_fake_profile(self):
        self.pages = [[order(customer_id=1, name=None, email=None, phone=None), order(customer_id=None)]]
        result = await self.run_backfill()
        self.assertEqual(self.identities, {})
        self.assertEqual(result["identities_without_contact"], 1)

    async def test_sparse_duplicate_in_page_keeps_available_contacts(self):
        self.pages = [[order(customer_id=1), order(customer_id=1, name=None, email=None, phone=None)]]
        await self.run_backfill()
        self.assertTrue(self.identities[(TENANT, "1")]["email"])

    async def test_other_tenant_profile_cannot_enrich_this_tenant(self):
        self.identities[(OTHER, "1")] = {"client_id": OTHER, "fbits_customer_id": "1", "name": "Other", "email": "other@example.com", "phone": "11888887777"}
        await self.run_backfill()
        self.assertNotEqual(self.identities[(TENANT, "1")]["email"], "other@example.com")
        self.assertEqual(self.identities[(OTHER, "1")]["name"], "Other")

    async def test_listing_and_detail_return_contacts_after_backfill(self):
        await self.run_backfill()
        async def read(table, **kwargs):
            if table == "fbits_customers":
                return list(self.identities.values())
            return [{"client_id": TENANT, "order_id": "42", "customer_id": "1", "status_id": "1", "order_date": "2026-10-01T00:00:00Z", "total_value": 120}]
        with (
            patch.object(customers, "sb_select", AsyncMock(side_effect=read)),
            patch.object(customers, "resolve_commerce_provider", AsyncMock(return_value={"provider": "fbits"})),
            patch("services.fbits_reporting._tenant_revenue_context", AsyncMock(return_value=(True, {"1"}, {}))),
        ):
            listing = await customers.list_customers(client_id=TENANT)
            row = listing["customers"][0]
            detail = await customers.get_customer(client_id=TENANT, customer_id=row["id"])
        self.assertEqual(row["identity_kind"], "external_id")
        for field in ("name", "email", "phone"):
            self.assertEqual(row[field], self.identities[(TENANT, "1")][field])
            self.assertEqual(detail["customer"][field], row[field])

    async def test_confirmation_rejected_before_any_access(self):
        with patch.object(fbits, "load_fbits_connection", AsyncMock()) as load:
            with self.assertRaises(ValueError):
                await backfill_customer_identities(client_id=TENANT, confirm_client_id=OTHER)
            load.assert_not_awaited()

    async def test_persistence_error_stops_and_never_logs_private_exception(self):
        self.fail_persistence = True
        with redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(RuntimeError, "FBITS_CUSTOMER_BACKFILL_FAILED"):
                await self.run_backfill()
        self.assertNotIn("private payload", self.log)
        self.assertIn('"errors": 1', self.log)

    async def test_logs_only_counts(self):
        await self.run_backfill()
        for value in ("Cliente Sigiloso", "cliente@", "11999998888"):
            self.assertNotIn(value, self.log)

    async def test_missing_phone_is_null_and_other_contacts_are_preserved(self):
        self.pages = [[order(customer_id=1, phone=None)]]
        await self.run_backfill()
        self.assertIsNone(self.identities[(TENANT, "1")]["phone"])
        self.assertTrue(self.identities[(TENANT, "1")]["name"])
        self.assertTrue(self.identities[(TENANT, "1")]["email"])

    async def test_existing_empty_fields_are_filled(self):
        self.identities[(TENANT, "1")] = {"client_id": TENANT, "fbits_customer_id": "1", "name": "Existing", "email": None, "phone": None}
        await self.run_backfill()
        row = self.identities[(TENANT, "1")]
        self.assertEqual(row["name"], "Existing")
        self.assertTrue(row["email"])
        self.assertTrue(row["phone"])

    async def test_shopify_connection_is_rejected_without_writes(self):
        self.connection["provider"] = "shopify"
        with self.assertRaises(RuntimeError):
            await self.run_backfill()
        self.assertEqual(self.identities, {})
        self.assertEqual(self.windows, [])

    async def test_disconnected_connection_is_rejected(self):
        self.connection["status"] = "disconnected"
        with self.assertRaises(RuntimeError):
            await self.run_backfill()
        self.assertEqual(self.identities, {})

    async def test_invalid_tenant_is_rejected_before_connection_lookup(self):
        with patch.object(fbits, "load_fbits_connection", AsyncMock()) as load:
            with self.assertRaises(ValueError):
                await backfill_customer_identities(client_id="all", confirm_client_id="all")
            load.assert_not_awaited()


class BackfillLockAndTimeoutTests(unittest.IsolatedAsyncioTestCase):
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
            return [{"client_id": TENANT, "order_date": "2026-10-01T00:00:00Z"}]
        connection = {"id": "conn", "client_id": TENANT, "provider": "fbits", "status": "connected"}
        with (
            patch.object(fbits, "load_fbits_connection", AsyncMock(return_value=connection)),
            patch.object(fbits, "sb_select", AsyncMock(side_effect=select)),
            patch.object(fbits, "get_connection", AsyncMock(return_value={})),
            patch.object(sync_locks, "acquire_sync_lock", acquire),
            patch.object(sync_locks, "release_sync_lock", release),
            redirect_stdout(io.StringIO()),
        ):
            first = asyncio.create_task(backfill_customer_identities(client_id=TENANT, confirm_client_id=TENANT))
            await asyncio.wait_for(entered.wait(), timeout=2)
            try:
                with self.assertRaises(CustomerBackfillError) as raised:
                    await backfill_customer_identities(client_id=TENANT, confirm_client_id=TENANT)
                self.assertEqual(raised.exception.status_code, 409)
            finally:
                finish.set()
                with self.assertRaises(CustomerBackfillError):
                    await first
            self.assertFalse(held)

    async def test_existing_service_timeout_is_translated_without_private_details(self):
        from services.fbits_customer_backfill import backfill_customer_identities
        with patch.object(fbits, "load_fbits_connection", AsyncMock(side_effect=TimeoutError("private"))), redirect_stdout(io.StringIO()):
            with self.assertRaises(CustomerBackfillError) as raised:
                await backfill_customer_identities(client_id=TENANT, confirm_client_id=TENANT)
        self.assertEqual(raised.exception.status_code, 504)
        self.assertEqual(raised.exception.counts["errors"], 1)
        self.assertNotIn("private", str(raised.exception))
