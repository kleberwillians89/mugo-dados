from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import customers, intelligence, fbits_reporting
from test_customers import fbits_order, shopify_order
from test_intelligence_real_generation import SnapshotHarness

CID = "tenant-a"


def order(key, customer, day, **extra):
    return fbits_order(order_id=key, customer_id=customer, order_date=day, client_id=CID, **extra)


class PersistedRecurrenceTests(unittest.IsolatedAsyncioTestCase):
    async def count(self, rows, *, provider="fbits", profiles=None):
        async def select(table, **kwargs):
            self.assertEqual(kwargs["filters"]["client_id"], "eq.tenant-a")
            return rows if table in {"fbits_orders", "shopify_orders"} else (profiles or [])
        with (
            patch.object(customers, "resolve_commerce_provider", AsyncMock(return_value={"provider": provider})),
            patch.object(customers, "sb_select", AsyncMock(side_effect=select)),
            patch.object(fbits_reporting, "_tenant_revenue_context", AsyncMock(return_value=(True, {"6"}, {}))),
        ):
            return await customers.recurring_customers_in_period(client_id=CID, start="2026-10-01", end="2026-10-05", provider=provider)

    async def test_single_valid_order_is_not_recurring(self):
        self.assertEqual(await self.count([order("1", "a", "2026-10-01")]), 0)

    async def test_two_valid_orders_are_one_recurring_customer(self):
        self.assertEqual(await self.count([order(str(n), "a", "2026-10-01") for n in range(4)]), 1)

    async def test_invalid_orders_do_not_make_customer_recurring(self):
        self.assertEqual(await self.count([order("1", "a", "2026-10-01"), order("2", "a", "2026-10-02", is_valid=False)]), 0)

    async def test_external_ids_keep_same_name_and_email_separate(self):
        rows = [order(f"{key}-{n}", key, "2026-10-01", name="Mesmo nome", email="same@example.test") for key in ("a", "b") for n in range(2)]
        self.assertEqual(await self.count(rows), 2)

    async def test_email_fallback_uses_existing_identity_normalization(self):
        rows = [order("1", None, "2026-09-01", email="A@EXAMPLE.TEST"), order("2", None, "2026-10-01", email="a@example.test")]
        self.assertEqual(await self.count(rows), 1)
        self.assertEqual(customers._identity(email=None, phone="+55 (11) 99999-0000"), (customers.IDENTITY_PHONE, "5511999990000"))

    async def test_tenant_b_rows_never_change_tenant_a_count(self):
        rows = [order("1", "a", "2026-10-01"), {**order("2", "a", "2026-10-02"), "client_id": "tenant-b"}]
        self.assertEqual(await self.count(rows), 0)

    async def test_historical_repeat_buyer_must_purchase_in_period_and_future_is_excluded(self):
        rows = [order("1", "old", "2026-09-01"), order("2", "old", "2026-09-02"),
                order("3", "current", "2026-09-01"), order("4", "current", "2026-10-05"),
                order("5", "future", "2026-10-01"), order("6", "future", "2026-10-06")]
        self.assertEqual(await self.count(rows), 1)

    async def test_absent_or_unidentified_or_undated_data_remains_unknown(self):
        for rows in ([], [order("1", None, "2026-10-01")], [order("1", "a", None)]):
            with self.subTest(rows=rows):
                self.assertIsNone(await self.count(rows))

    async def test_unattributed_orders_do_not_hide_identified_customer_recurrence(self):
        rows = [order("1", "a", "2026-10-01"), order("2", "a", "2026-10-02"), order("3", None, "2026-10-03")]
        self.assertEqual(await self.count(rows), 1)

    async def test_scan_limit_is_not_reported_as_complete(self):
        with patch.object(customers, "CUSTOMER_ORDER_SCAN_LIMIT", 2):
            self.assertIsNone(await self.count([order("1", "a", "2026-10-01"), order("2", "a", "2026-10-02")]))

    async def test_shopify_reuses_same_customer_360_recognition(self):
        rows = [{**shopify_order(order_id=str(n), customer_id="a", created_at="2026-10-01T12:00:00Z"), "client_id": CID} for n in range(3)]
        self.assertEqual(await self.count(rows, provider="shopify"), 1)


class SnapshotRecurrenceTests(SnapshotHarness):
    async def test_real_persisted_recurrence_enters_snapshot_and_numeric_grounding(self):
        rows = [order(str(n), "a", "2026-09-01") for n in range(2)]
        async def select(table, **kwargs):
            return [{**row, "client_id": kwargs["filters"]["client_id"].removeprefix("eq.")} for row in rows] if table == "fbits_orders" else []
        with (
            patch.object(customers, "resolve_commerce_provider", AsyncMock(return_value={"provider": "fbits"})),
            patch.object(customers, "sb_select", AsyncMock(side_effect=select)),
            patch.object(fbits_reporting, "_tenant_revenue_context", AsyncMock(return_value=(True, {"6"}, {}))),
        ):
            snapshot = await self.snapshot()
        metric = next(item for item in snapshot["metrics"] if item["id"] == "repeat_customers")
        self.assertEqual((metric["value"], metric["status"], metric["source"]), (1, "confirmed", "fbits"))
        trusted = intelligence._trusted_numbers({"metrics": snapshot["metrics"], "period": snapshot["period"]})
        intelligence._assert_no_untrusted_numeric_text({"executive": {"main_change": "1 cliente recorrente"}}, trusted=trusted)
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, "AI_UNTRUSTED_NUMERIC_TEXT"):
            intelligence._assert_no_untrusted_numeric_text({"executive": {"main_change": "888888 clientes recorrentes"}}, trusted=trusted)

    async def test_missing_persisted_data_stays_unavailable(self):
        with patch.object(intelligence, "recurring_customers_in_period", AsyncMock(return_value=None)):
            snapshot = await self.snapshot()
        metric = next(item for item in snapshot["metrics"] if item["id"] == "repeat_customers")
        self.assertIsNone(metric["value"])
        self.assertEqual(metric["status"], "unavailable")

    async def test_fbits_never_borrows_shopify_returning_customers(self):
        from test_intelligence_real_generation import executive_context
        context = executive_context()
        context["shopify"]["returning_customers"] = 99
        with patch.object(intelligence, "recurring_customers_in_period", AsyncMock(return_value=2)) as fallback:
            snapshot = await self.snapshot(context=context)
        metric = next(item for item in snapshot["metrics"] if item["id"] == "repeat_customers")
        self.assertEqual(metric["value"], 2)
        self.assertEqual(fallback.await_args.kwargs["provider"], "fbits")

    async def test_trusted_official_kpi_takes_precedence(self):
        commerce = {"provider": "fbits", "connected": True, "official_kpis": True,
                    "status": "ok", "kpi_source": "official_persisted",
                    "metrics": {"repeat_customers": {"value": 3, "status": "confirmed"}}}
        with patch.object(intelligence, "resolve_commerce_context", AsyncMock(return_value=commerce)), patch.object(intelligence, "recurring_customers_in_period", AsyncMock()) as fallback:
            snapshot = await self.snapshot()
        metric = next(item for item in snapshot["metrics"] if item["id"] == "repeat_customers")
        self.assertEqual(metric["value"], 3)
        fallback.assert_not_awaited()

    async def test_existing_shopify_kpi_remains_prioritized(self):
        from test_intelligence_real_generation import executive_context
        context = executive_context()
        context["shopify"].update(connected=True, data_available=True, returning_customers=7)
        with patch.object(intelligence, "resolve_commerce_context", AsyncMock(return_value={"provider": "shopify", "connected": True, "metrics": {}})), patch.object(intelligence, "recurring_customers_in_period", AsyncMock()) as fallback:
            snapshot = await self.snapshot(context=context)
        metric = next(item for item in snapshot["metrics"] if item["id"] == "repeat_customers")
        self.assertEqual(metric["value"], 7)
        fallback.assert_not_awaited()
