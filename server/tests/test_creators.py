import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI

from services import creators, creators_providers as providers
from services.integration_errors import IntegrationError
from routes import creators as routes

CID = "tenant-a"


def ig_profile(followers=10000, likes=(100, 200), comments=(10, 20)):
    return {
        "network": "instagram", "handle": "criadora", "followers": followers, "source": "test",
        "posts": [{"likes": l, "comments": c, "views": None} for l, c in zip(likes, comments)],
    }


class HandleTests(unittest.TestCase):
    def test_normalizes_at_url_and_case(self):
        self.assertEqual(providers.normalize_handle("instagram", "@Ruah.Parfums"), "ruah.parfums")
        self.assertEqual(providers.normalize_handle("instagram", "https://www.instagram.com/ruah_parfums/?hl=pt"), "ruah_parfums")
        self.assertEqual(providers.normalize_handle("tiktok", "https://www.tiktok.com/@nome.x"), "nome.x")

    def test_rejects_invalid_handles(self):
        for network, raw in [("instagram", "nome com espaço"), ("instagram", "a" * 31), ("tiktok", "x"), ("facebook", "x")]:
            with self.assertRaises(ValueError):
                providers.normalize_handle(network, raw)


class EngagementTests(unittest.TestCase):
    def test_instagram_rate_uses_followers_and_explicit_method(self):
        result = providers.compute_engagement(ig_profile())
        self.assertEqual(result["avg_likes"], 150)
        self.assertEqual(result["avg_comments"], 15)
        self.assertEqual(result["engagement_rate"], 1.65)
        self.assertIn("seguidores", result["engagement_method"])
        self.assertEqual(result["sample_size"], 2)
        self.assertEqual(result["missing_fields"], [])

    def test_hidden_likes_and_missing_followers_are_flagged_not_invented(self):
        result = providers.compute_engagement(ig_profile(followers=None, likes=(None, None)))
        self.assertIsNone(result["engagement_rate"])
        self.assertIsNone(result["avg_likes"])
        self.assertIn("followers", result["missing_fields"])
        self.assertIn("avg_likes", result["missing_fields"])

    def test_video_networks_rate_per_view(self):
        profile = {"network": "youtube", "followers": 5000, "posts": [
            {"likes": 90, "comments": 10, "views": 1000},
            {"likes": 5, "comments": None, "views": 50},
        ]}
        result = providers.compute_engagement(profile)
        self.assertEqual(result["engagement_rate"], 10.0)
        self.assertIn("visualizações", result["engagement_method"])

    def test_no_posts_has_no_method(self):
        result = providers.compute_engagement({"network": "tiktok", "followers": 1, "posts": []})
        self.assertIsNone(result["engagement_method"])
        self.assertIn("avg_views", result["missing_fields"])


class GroupingTests(unittest.TestCase):
    def test_instagram_hashtag_groups_by_owner_and_hides_negative_likes(self):
        items = [
            {"ownerUsername": "Ana", "likesCount": 10, "commentsCount": 1},
            {"ownerUsername": "ana", "likesCount": -1, "commentsCount": 2},
            {"ownerUsername": "", "likesCount": 5},
        ]
        grouped = providers.group_instagram_hashtag_items(items)
        self.assertEqual(len(grouped), 1)
        self.assertIsNone(grouped[0]["followers"])
        self.assertEqual([p["likes"] for p in grouped[0]["posts"]], [10, None])

    def test_tiktok_groups_with_followers(self):
        items = [{"authorMeta": {"name": "Bia", "fans": 900}, "diggCount": 50, "commentCount": 5, "playCount": 1000}]
        grouped = providers.group_tiktok_items(items)
        self.assertEqual(grouped[0]["handle"], "bia")
        self.assertEqual(grouped[0]["followers"], 900)


class MetaErrorTests(unittest.TestCase):
    def error(self, code):
        return providers._meta_error(httpx.Response(400, json={"error": {"code": code}}))

    def test_maps_meta_errors(self):
        self.assertEqual(self.error(110).code, "CREATOR_NOT_FOUND")
        self.assertEqual(self.error(190).code, "META_REAUTH_REQUIRED")
        self.assertEqual(self.error(4).status_code, 429)
        self.assertEqual(self.error(10).code, "META_PERMISSION_MISSING")


class BudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocks_when_month_spend_reaches_budget(self):
        with patch.object(creators, "sb_select", AsyncMock(return_value=[{"cost_usd": 4.9}])):
            with self.assertRaises(IntegrationError) as ctx:
                await creators.apify_budget_guard()
        self.assertEqual(ctx.exception.code, "CREATORS_BUDGET_EXCEEDED")
        self.assertEqual(ctx.exception.status_code, 402)

    async def test_returns_remaining_as_run_ceiling(self):
        with patch.object(creators, "sb_select", AsyncMock(return_value=[{"cost_usd": 1.5}])):
            self.assertEqual(await creators.apify_budget_guard(), 3.5)

    async def test_failed_rejected_run_costs_nothing(self):
        record = AsyncMock()
        rejected = IntegrationError("x", status_code=502, code="APIFY_RUN_REJECTED", provider="apify")
        with patch.object(creators, "apify_budget_guard", AsyncMock(return_value=5)), \
             patch.object(creators.providers, "apify_run", AsyncMock(side_effect=rejected)), \
             patch.object(creators, "record_usage", record):
            with self.assertRaises(IntegrationError):
                await creators._apify(CID, "tiktok", {}, 10)
        self.assertEqual(record.await_args.kwargs["cost_usd"], 0)

    async def test_unknown_cost_counts_estimate(self):
        record = AsyncMock()
        with patch.object(creators, "apify_budget_guard", AsyncMock(return_value=5)), \
             patch.object(creators.providers, "apify_run", AsyncMock(return_value=([{}], None))), \
             patch.object(creators, "record_usage", record):
            await creators._apify(CID, "tiktok", {}, 10)
        self.assertEqual(record.await_args.kwargs["cost_usd"], creators.apify_run_estimate())

    async def test_youtube_quota_guard(self):
        with patch.object(creators, "sb_select", AsyncMock(return_value=[{"units": 8950}])):
            with self.assertRaises(IntegrationError):
                await creators.youtube_quota_guard(101)
            await creators.youtube_quota_guard(3)


class LookupTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_cache_skips_provider(self):
        cached = {"id": "c1", "followers": 10, "collected_at": creators._now().isoformat()}
        meta = AsyncMock()
        with patch.object(creators, "get_by_handle", AsyncMock(return_value=cached)), patch.object(creators, "_meta_profile", meta):
            result = await creators.lookup(CID, "instagram", "@x")
        self.assertTrue(result["cached"])
        meta.assert_not_awaited()

    async def test_partial_profile_never_overwrites_complete_one(self):
        existing = {"id": "c1", "network": "instagram", "handle": "criadora", "followers": 5000}
        upsert = AsyncMock()
        with patch.object(creators, "get_by_handle", AsyncMock(return_value=existing)), patch.object(creators, "sb_upsert", upsert):
            saved = await creators.save_profile(ig_profile(followers=None))
        self.assertEqual(saved, existing)
        upsert.assert_not_awaited()

    async def test_meta_requires_client_connection(self):
        with patch.object(creators, "get_active_connection_for_client", AsyncMock(return_value=None)):
            with self.assertRaises(IntegrationError) as ctx:
                await creators._meta_credentials(CID)
        self.assertEqual(ctx.exception.code, "META_CONNECTION_REQUIRED")

    async def test_compare_limits(self):
        with self.assertRaises(ValueError):
            await creators.compare(["a"])
        with self.assertRaises(ValueError):
            await creators.compare([str(i) for i in range(6)])


class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = FastAPI()
        app.include_router(routes.router)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_routes_are_agency_only(self):
        role = AsyncMock(return_value=CID)
        with patch.object(routes, "require_client_role", role), patch.object(creators, "usage_summary", AsyncMock(return_value={})):
            response = await self.client.get(f"/api/clients/{CID}/creators/usage")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(role.await_args.kwargs["allowed_roles"], ("agency_admin",))

    async def test_shortlist_items_are_tenant_filtered(self):
        delete = AsyncMock(return_value=[])
        with patch.object(routes, "require_client_role", AsyncMock(return_value=CID)), patch.object(routes, "sb_delete", delete):
            response = await self.client.delete(f"/api/clients/{CID}/creators/shortlists/00000000-0000-0000-0000-000000000001/items/00000000-0000-0000-0000-000000000002")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(delete.await_args.kwargs["filters"]["client_id"], f"eq.{CID}")

    async def test_invalid_handle_is_422(self):
        with patch.object(routes, "require_client_role", AsyncMock(return_value=CID)):
            response = await self.client.post(f"/api/clients/{CID}/creators/lookup", json={"network": "instagram", "handle": "nome inválido"})
        self.assertEqual(response.status_code, 422)

    async def test_input_rejects_extra_fields(self):
        with patch.object(routes, "require_client_role", AsyncMock(return_value=CID)):
            response = await self.client.post(f"/api/clients/{CID}/creators/search", json={"network": "instagram", "query": "perfume", "client_id": "other"})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
