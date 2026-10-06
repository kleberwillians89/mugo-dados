"""Fronteiras reais do refresh; somente rede, banco e lock são simulados."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import AsyncMock, patch
from contextlib import ExitStack
from services import provider_refresh as refresh, fbits_connections as fc, fbits_official_kpis as official, runtime_cache, instagram_sync as ig, fbits_reporting as reporting
from test_fbits_multitenant import FakeDb, FakeFbitsApi, connection_row, order, NOW, no_lock
from test_fbits_official_kpis import indicators


class ManualPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_fbits_real_sync_persists_advances_freshness_and_expires_old_kpis(self):
        runtime_cache._CACHE.clear()
        official._FAILURES.clear()
        row = connection_row()
        db = FakeDb([row])
        db.upserts["fbits_customers"] = []
        api = FakeFbitsApi([order(900, total=987)])
        values = {"revenue": 10}
        class Dashboard:
            async def revenue_indicators(self, **kwargs):
                return indicators(receita=values["revenue"])
        async def get_conn(*args, **kwargs):
            return {"_token": '{"token":"synthetic"}'}
        async def real_sync(**kwargs):
            return await fc.sync_fbits_connection(**kwargs, client_factory=api.client_factory, now=NOW, record_job_run=False)
        with ExitStack() as stack:
            for target, name, value in [
                (refresh, "guarded_sync", no_lock), (refresh, "acquire_sync_lock", AsyncMock(return_value=True)),
                (refresh, "list_generic_connections", AsyncMock(return_value=[row])), (refresh, "sync_fbits_connection", real_sync),
                (fc, "guarded_sync", no_lock), (fc, "sb_select", AsyncMock(side_effect=db.select)),
                (fc, "sb_upsert", AsyncMock(side_effect=db.upsert)), (fc, "sb_update", AsyncMock(side_effect=db.update)),
                (fc, "get_connection", get_conn), (reporting, "sb_select", AsyncMock(side_effect=db.select)), (official, "load_fbits_connection", AsyncMock(return_value=row)),
                (official, "sb_update", AsyncMock(side_effect=db.update)), (official, "get_connection", get_conn), (official, "client_factory", lambda token: Dashboard()),
            ]: stack.enter_context(patch.object(target, name, value))
            async def read():
                return await official.fetch_official_kpis(client_id="curavino", start="2026-09-01", end="2026-09-30", previous_start="2026-08-01", previous_end="2026-08-31")
            self.assertEqual((await read())["current"]["receita_oficial"], 10)
            values["revenue"] = 987
            self.assertEqual((await read())["current"]["receita_oficial"], 10)
            await refresh.refresh_provider_data("curavino", "fbits", "2026-09-01", "2026-09-30")
            self.assertTrue(any(r.url.path == "/pedidos" for r in api.requests))
            self.assertTrue(db.upserts["fbits_orders"])
            self.assertTrue(db.upserts["fbits_order_daily_stats"])
            self.assertEqual(row["metadata"]["last_success_at"], NOW.isoformat())
            self.assertEqual((await read())["current"]["receita_oficial"], 987)
            report = await reporting.build_fbits_summary(client_id="curavino", period=reporting.FbitsPeriod("2026-09-01", "2026-09-30"))
            self.assertEqual(report["summary"]["receita_oficial"], 987)
            self.assertEqual(report["last_sync_at"], NOW.isoformat())

    async def test_meta_provider_persist_projection_freshness_in_order(self):
        rows = {}; stages = []
        async def upsert(table, values, **kwargs):
            rows[table] = values
            stages.append(table)
        async def project(**kwargs):
            self.assertEqual(rows["ig_profile_snapshots"][0]["reach_day"], 99)
            stages.append("projection_freshness")
            return {"ok": True}
        async def mark(*args): stages.append("connection_success")
        with ExitStack() as stack:
            for name, value in [
                ("_resolve_connection_by_id", AsyncMock(return_value={"platform":"instagram", "client_id":"curavino", "ig_user_id":"synthetic"})),
                ("ensure_valid_meta_token", AsyncMock(return_value="synthetic")),
                ("fetch_profile", AsyncMock(return_value={"followers_count":20})),
                ("fetch_media_list", AsyncMock(return_value=[{"id":"media", "media_type":"IMAGE"}])),
                ("fetch_media_insights", AsyncMock(return_value={"reach":99})),
                ("fetch_kpis_total_value", AsyncMock(return_value={"reach":99})),
                ("fetch_stories", AsyncMock(return_value=[])), ("sb_upsert", upsert),
                ("refresh_dashboard_read_model_safely", project), ("_mark_connection_success", mark),
            ]: stack.enter_context(patch.object(ig, name, value))
            result = await ig._sync_instagram_connection("organic", process_thumbnails=False, persisted_only=True)
        self.assertEqual(rows["ig_profile_snapshots"][0]["followers_count"], 20)
        self.assertTrue(result["snapshot_saved"])
        self.assertTrue(result["read_model_refreshed"])
        self.assertEqual(rows["ig_media"][0]["insights_json"]["reach"], 99)
        self.assertLess(stages.index("ig_profile_snapshots"), stages.index("projection_freshness"))
        self.assertLess(stages.index("projection_freshness"), stages.index("connection_success"))


    async def test_meta_duplicate_is_explicit_cooldown_even_after_organic_success(self):
        async def resolve(**kwargs):
            return {"connection_id": "organic" if kwargs["platform"] == "instagram" else "paid", "row": {"ig_user_id": "synthetic"}}
        from fastapi import HTTPException
        with patch.object(refresh, "guarded_sync", no_lock), patch.object(refresh, "acquire_sync_lock", AsyncMock(return_value=True)), patch.object(refresh, "resolve_connection_for_scope", AsyncMock(side_effect=resolve)), patch.object(refresh, "sync_instagram_for_client", AsyncMock(return_value={"ok": True})) as organic, patch.object(refresh, "sync_ads_for_client_period", AsyncMock(return_value={"ok": False, "skipped": True, "reason": "duplicate", "retry_after": 173})):
            with self.assertRaises(HTTPException) as error:
                await refresh.refresh_provider_data("curavino", "meta", "2026-09-01", "2026-09-30")
        organic.assert_awaited_once()
        self.assertEqual(error.exception.status_code, 429)
        self.assertEqual(error.exception.headers["Retry-After"], "173")
