"""Primeiro carregamento progressivo da Meta: descoberta rápida, KPI primeiro, histórico depois.

Cobre: chamadas da descoberta (sem detalhe repetido, em paralelo), reconexão (token inválido),
carregamento parcial (uma fonte falha, o resto aparece), falhas e limite da API Meta,
e isolamento entre tenants (o segundo plano usa só o tenant validado pela rota).
"""
import asyncio
import io
import sys
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import meta_oauth, meta_progressive  # noqa: E402
from services.meta_http import MetaApiError  # noqa: E402


class FakeGraph:
    def __init__(self, pages=3, fail=None, latency=0.01):
        self.pages, self.fail, self.latency = pages, fail or {}, latency
        self.paths, self.inflight, self.max_inflight = [], 0, 0

    async def __call__(self, path, params=None, **_kw):
        key = path.split("?", 1)[0]
        self.paths.append(key)
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            await asyncio.sleep(self.latency)
            for suffix, exc in self.fail.items():
                if key.endswith(suffix):
                    raise exc
            if key.endswith("/me/accounts"):
                return {"data": [{"id": f"p{i}", "name": f"P{i}", "instagram_business_account": {"id": f"ig{i}", "username": f"u{i}"}}
                                 for i in range(self.pages)]}
            if key.endswith("/me/adaccounts"):
                return {"data": [{"id": "act_1", "account_id": "1", "name": "Conta", "account_status": 1}]}
            if key.endswith("/me/businesses"):
                return {"data": [{"id": "b1", "name": "BM"}]}
            if key.endswith("/me/permissions"):
                return {"data": [{"permission": "ads_read", "status": "granted"}]}
            if key.endswith("/me"):
                return {"id": "u1", "name": "Usuária"}
            return {"data": []}
        finally:
            self.inflight -= 1


async def _discover(graph):
    with patch.object(meta_oauth, "meta_get_json", graph), redirect_stdout(io.StringIO()):
        return await meta_oauth.discover_assets("token")


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_per_page_detail_and_initial_reads_in_parallel(self):
        graph = FakeGraph(pages=25)
        out = await _discover(graph)
        self.assertEqual(len(out["pages"]), 25)
        self.assertEqual(len(out["instagram_accounts"]), 25)
        self.assertFalse([p for p in graph.paths if p.rsplit("/", 1)[-1].startswith("p") and p.rsplit("/", 1)[-1][1:].isdigit()])
        self.assertGreaterEqual(graph.max_inflight, 4)  # /me, Páginas, contas, permissões e Businesses juntos

    async def test_invalid_token_requires_reconnection(self):
        graph = FakeGraph(fail={"/me/accounts": MetaApiError("expirado", status_code=401, error_code=190, invalid_oauth=True)})
        with self.assertRaises(MetaApiError) as caught:
            await _discover(graph)
        self.assertTrue(caught.exception.invalid_oauth)

    async def test_business_listing_failure_still_delivers_direct_assets(self):
        graph = FakeGraph(fail={"/me/businesses": MetaApiError("sem permissão", status_code=403, error_code=200)})
        out = await _discover(graph)
        self.assertEqual(len(out["pages"]), 3)
        self.assertEqual(len(out["ad_accounts"]), 1)
        self.assertTrue(out["discovery_warnings"])

    async def test_rate_limit_on_ad_accounts_is_reported_not_swallowed(self):
        graph = FakeGraph(fail={"/me/adaccounts": MetaApiError("limite", status_code=400, error_code=17, rate_limited=True)})
        with self.assertRaises(MetaApiError) as caught:
            await _discover(graph)
        self.assertTrue(caught.exception.rate_limited)

    async def test_diagnostics_failure_never_breaks_discovery(self):
        graph = FakeGraph(fail={"/me/permissions": RuntimeError("diag")})
        out = await _discover(graph)
        self.assertEqual(len(out["pages"]), 3)


class BackgroundTests(unittest.IsolatedAsyncioTestCase):
    async def test_background_error_stays_in_log(self):
        async def boom():
            raise RuntimeError("https://graph.facebook.com/?access_token=SEGREDO")
        output = io.StringIO()
        with redirect_stdout(output):
            meta_progressive.schedule("teste", "tenant-a", boom)
            await meta_progressive.drain()
        self.assertIn("stage=error job=teste client_id=tenant-a code=RuntimeError", output.getvalue())
        self.assertNotIn("SEGREDO", output.getvalue())

    async def test_paid_history_syncs_30_days_then_queues_the_rest_of_90(self):
        sync = AsyncMock(return_value={"ok": True, "status": "success"})
        enqueue = AsyncMock(return_value={"status": "queued"})
        today = date(2026, 11, 3)
        fake_period = lambda days, max_days: type("P", (), {"start": date.fromordinal(today.toordinal() - days + 1), "end": today})()
        with patch("services.ads_sync.sync_ads_for_client_period", sync), \
                patch("services.meta_backfill.enqueue_backfill", enqueue), \
                patch("services.periods.resolve_period", fake_period):
            out = await meta_progressive.paid_history("tenant-a", "conn-1")
        self.assertEqual(sync.await_args.kwargs["client_id"], "tenant-a")
        self.assertEqual(sync.await_args.kwargs["since"], "2026-10-05")
        self.assertEqual(enqueue.await_args.kwargs["since"], "2026-08-06")
        self.assertEqual(enqueue.await_args.kwargs["until"], "2026-10-04")  # sem sobrepor os 30 dias
        self.assertEqual(out["backfill_90d"], "queued")

    async def test_paid_history_survives_busy_queue(self):
        with patch("services.ads_sync.sync_ads_for_client_period", AsyncMock(return_value={"ok": True})), \
                patch("services.meta_backfill.enqueue_backfill", AsyncMock(side_effect=ValueError("ativo"))):
            out = await meta_progressive.paid_history("tenant-a", "conn-1")
        self.assertEqual(out["backfill_90d"], "skipped:ValueError")


class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_link_assets_reads_7_days_then_schedules_history_for_the_validated_tenant(self):
        from routes import meta_legacy
        scheduled = []
        sync = AsyncMock(return_value={"ok": True, "status": "success"})
        with patch.object(meta_legacy, "require_user_id", AsyncMock(return_value="user-1")), \
                patch.object(meta_legacy, "require_client_role", AsyncMock(return_value="tenant-a")), \
                patch.object(meta_legacy, "save_connections", AsyncMock(return_value={"connections": [{"platform": "meta_ads", "id": "conn-a"}]})), \
                patch.object(meta_legacy, "sync_ads_for_client_period", sync), \
                patch.object(meta_progressive, "schedule", lambda name, cid, factory: scheduled.append((name, cid))):
            out = await meta_legacy.api_link_assets("tenant-b-na-url", {"handoff": "h", "client_id": "tenant-b"}, authorization="Bearer x")
        kwargs = sync.await_args.kwargs
        self.assertEqual(kwargs["client_id"], "tenant-a")
        self.assertEqual((date.fromisoformat(kwargs["until"]) - date.fromisoformat(kwargs["since"])).days + 1, 7)
        self.assertEqual(scheduled, [("meta_ads_history", "tenant-a")])
        self.assertEqual(out["history_sync"]["status"], "scheduled")

    async def test_link_assets_initial_failure_returns_partial_without_history(self):
        from routes import meta_legacy
        scheduled = []
        with patch.object(meta_legacy, "require_user_id", AsyncMock(return_value="user-1")), \
                patch.object(meta_legacy, "require_client_role", AsyncMock(return_value="tenant-a")), \
                patch.object(meta_legacy, "save_connections", AsyncMock(return_value={"connections": [{"platform": "meta_ads", "id": "conn-a"}]})), \
                patch.object(meta_legacy, "sync_ads_for_client_period", AsyncMock(side_effect=MetaApiError("limite", rate_limited=True))), \
                patch.object(meta_progressive, "schedule", lambda *a: scheduled.append(a)):
            out = await meta_legacy.api_link_assets("tenant-a", {"handoff": "h"}, authorization="Bearer x")
        self.assertFalse(out["meta_ads_initial_sync"]["ok"])
        self.assertEqual(scheduled, [])

    async def test_link_assets_denied_tenant_never_syncs(self):
        from fastapi import HTTPException
        from routes import meta_legacy
        sync = AsyncMock()
        with patch.object(meta_legacy, "require_user_id", AsyncMock(return_value="user-1")), \
                patch.object(meta_legacy, "require_client_role", AsyncMock(side_effect=HTTPException(status_code=403))), \
                patch.object(meta_legacy, "sync_ads_for_client_period", sync):
            with self.assertRaises(HTTPException):
                await meta_legacy.api_link_assets("tenant-b", {"handoff": "h"}, authorization="Bearer x")
        sync.assert_not_awaited()

    async def test_selecting_ad_account_reads_7_days_and_schedules_history(self):
        from routes import meta_legacy
        scheduled = []
        sync = AsyncMock(return_value={"ok": True, "status": "success"})
        with patch.object(meta_legacy, "require_user_id", AsyncMock(return_value="user-1")), \
                patch.object(meta_legacy, "require_client_role", AsyncMock(return_value="tenant-a")), \
                patch.object(meta_legacy, "select_paid_connection", AsyncMock(return_value={"connection_id": "conn-a"})), \
                patch.object(meta_legacy, "sync_ads_for_client_period", sync), \
                patch.object(meta_progressive, "schedule", lambda name, cid, factory: scheduled.append((name, cid))):
            out = await meta_legacy.api_select_meta_ads_account("tenant-b-na-url", {"ad_account_id": "act_1"}, authorization="Bearer x")
        self.assertTrue(out["ok"])
        self.assertEqual(sync.await_args.kwargs["client_id"], "tenant-a")
        self.assertEqual(sync.await_args.kwargs["connection_id"], "conn-a")
        self.assertEqual(out["meta_ads_initial_sync"]["days"], 7)
        self.assertEqual(scheduled, [("meta_ads_history", "tenant-a")])

    async def test_selecting_ad_account_keeps_selection_when_meta_fails(self):
        from routes import meta_legacy
        with patch.object(meta_legacy, "require_user_id", AsyncMock(return_value="user-1")), \
                patch.object(meta_legacy, "require_client_role", AsyncMock(return_value="tenant-a")), \
                patch.object(meta_legacy, "select_paid_connection", AsyncMock(return_value={"connection_id": "conn-a"})), \
                patch.object(meta_legacy, "sync_ads_for_client_period", AsyncMock(side_effect=MetaApiError("fora", status_code=500))):
            out = await meta_legacy.api_select_meta_ads_account("tenant-a", {"ad_account_id": "act_1"}, authorization="Bearer x")
        self.assertTrue(out["ok"])  # a conta continua escolhida
        self.assertFalse(out["meta_ads_initial_sync"]["ok"])
        self.assertNotIn("history_sync", out)

    async def test_organic_activation_is_quick_then_full_in_background(self):
        from routes import meta_legacy
        scheduled = []
        quick = AsyncMock(return_value={"media_saved": 12, "comments_saved": 0, "snapshot_saved": True})
        request = type("R", (), {"state": type("S", (), {"request_id": "req-1"})()})()
        with patch.object(meta_legacy, "require_user_id", AsyncMock(return_value="user-1")), \
                patch.object(meta_legacy, "require_client_role", AsyncMock(return_value="tenant-a")), \
                patch.object(meta_legacy, "activate_meta_organic_assets", AsyncMock(return_value={"organic_connection_id": "org-a"})), \
                patch.object(meta_legacy, "sync_instagram_connection", quick), \
                patch.object(meta_legacy, "finalize_meta_organic_activation", AsyncMock()), \
                patch.object(meta_progressive, "schedule", lambda name, cid, factory: scheduled.append((name, cid))):
            out = await meta_legacy.api_activate_meta_organic("auth-1", {"page_id": "p", "instagram_id": "ig"}, request,
                                                              client_id="tenant-a", x_client_id=None, authorization="Bearer x")
        self.assertTrue(out["ok"])
        self.assertEqual(quick.await_args.kwargs, {"limit": meta_progressive.QUICK_MEDIA, "process_thumbnails": False})
        self.assertEqual(scheduled, [("instagram_history", "tenant-a")])
        self.assertEqual(out["history_sync"]["status"], "scheduled")

    async def test_organic_quick_failure_does_not_schedule_history(self):
        from routes import meta_legacy
        scheduled = []
        request = type("R", (), {"state": type("S", (), {"request_id": "req-1"})()})()
        with patch.object(meta_legacy, "require_user_id", AsyncMock(return_value="user-1")), \
                patch.object(meta_legacy, "require_client_role", AsyncMock(return_value="tenant-a")), \
                patch.object(meta_legacy, "activate_meta_organic_assets", AsyncMock(return_value={"organic_connection_id": "org-a"})), \
                patch.object(meta_legacy, "sync_instagram_connection", AsyncMock(side_effect=MetaApiError("falha", status_code=500))), \
                patch.object(meta_legacy, "finalize_meta_organic_activation", AsyncMock()), \
                patch.object(meta_progressive, "schedule", lambda *a: scheduled.append(a)):
            out = await meta_legacy.api_activate_meta_organic("auth-1", {}, request, client_id="tenant-a",
                                                              x_client_id=None, authorization="Bearer x")
        self.assertFalse(out.get("ok", False))
        self.assertEqual(scheduled, [])


if __name__ == "__main__":
    unittest.main()
