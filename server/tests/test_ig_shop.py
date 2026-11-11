"""Produtos da loja do Instagram marcados no post: limpeza, contêiner de publicação, permissão e busca."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os

from services import ig_publish as ip
from services import ig_shop as shop
from services.studio_calendar import StudioError

ITEM = {"id": "i1", "client_id": "roove", "format": "imagem", "art_url": "https://cdn.roove.com/arte.jpg", "caption_draft": "Legenda"}
TAG = {"product_id": "111", "name": "Legging", "slide": 0, "x": 0.4, "y": 0.7}
CREDS = {"ig_user_id": "1784", "token": "tok", "scopes": {"instagram_content_publish", "instagram_shopping_tag_products"}}


class CleanTests(unittest.TestCase):
    def test_bad_ids_duplicates_and_limits(self):
        raw = [TAG, {**TAG}, {"product_id": "abc"}, {"product_id": "222", "x": 5, "y": -1, "slide": 3, "image_url": "http://x"}]
        raw += [{"product_id": str(300 + i)} for i in range(8)]
        out = shop.clean_product_tags(raw)
        self.assertEqual(out[0], {"product_id": "111", "name": "Legging", "image_url": None, "slide": 0, "x": 0.4, "y": 0.7})
        self.assertEqual(out[1], {"product_id": "222", "name": None, "image_url": None, "slide": 3, "x": 1.0, "y": 0.01})
        self.assertEqual(sum(1 for t in out if t["slide"] == 0), 5)  # no máximo 5 por slide


class ContainerTests(unittest.TestCase):
    def test_image_reels_carousel_and_story(self):
        image = ip.media_for({**ITEM, "product_tags": [TAG]})[0]
        self.assertEqual(json.loads(image["fields"]["product_tags"]), [{"product_id": "111", "x": 0.4, "y": 0.7}])
        reels = ip.media_for({**ITEM, "format": "reels", "art_url": "https://cdn.x/v.mp4", "product_tags": [TAG, {**TAG, "product_id": "222", "slide": 2}]})[0]
        self.assertEqual(json.loads(reels["fields"]["product_tags"]), [{"product_id": "111"}, {"product_id": "222"}])
        carousel = ip.media_for({**ITEM, "format": "carrossel", "art_url": "https://cdn.x/1.jpg\nhttps://cdn.x/2.mp4",
                                 "product_tags": [TAG, {**TAG, "product_id": "222", "slide": 1}]})[0]
        self.assertNotIn("product_tags", carousel["fields"])
        self.assertEqual(json.loads(carousel["children"][0]["product_tags"]), [{"product_id": "111", "x": 0.4, "y": 0.7}])
        self.assertEqual(json.loads(carousel["children"][1]["product_tags"]), [{"product_id": "222"}])  # vídeo: sem x/y
        story = ip.media_for({**ITEM, "format": "stories", "product_tags": [TAG]})[0]
        self.assertFalse(shop.has_tags(story))

    def test_strip_keeps_everything_else(self):
        plan = ip.media_for({**ITEM, "product_tags": [TAG], "collaborators": ["parceira"]})[0]
        bare = shop.strip_tags(plan)
        self.assertFalse(shop.has_tags(bare))
        self.assertIn("collaborators", bare["fields"])


class PublishTests(unittest.IsolatedAsyncioTestCase):
    async def run_item(self, *, creds=CREDS, publish=None):
        publish = publish or AsyncMock(return_value={"media_id": "m1", "permalink": None})
        with patch.object(ip, "sb_update", AsyncMock(return_value=[{"id": "i1"}])), patch.object(ip, "publish", publish), \
             patch("services.ig_engagement.credentials", AsyncMock(return_value=creds)), \
             patch("services.studio_history.record", AsyncMock()) as record, \
             patch.dict(os.environ, {"IG_PUBLISH_ENABLED": "true"}):
            result = await ip.publish_item({**ITEM, "product_tags": [TAG]}, creds_cache={})
        return result, publish, record

    async def test_with_permission_publishes_tagged(self):
        result, publish, record = await self.run_item()
        self.assertEqual(result, "publicado")
        self.assertTrue(shop.has_tags(publish.await_args.args[1]))
        record.assert_not_awaited()

    async def test_without_permission_publishes_untagged_and_says_why(self):
        result, publish, record = await self.run_item(creds={**CREDS, "scopes": {"instagram_content_publish"}})
        self.assertEqual(result, "publicado")
        self.assertFalse(shop.has_tags(publish.await_args.args[1]))
        self.assertIn("permissão de marcar produtos", record.await_args.args[2])

    async def test_meta_refuses_tags_then_publishes_without_them(self):
        publish = AsyncMock(side_effect=[StudioError("IG_PUBLISH_FAILED", "Product not eligible"), {"media_id": "m1", "permalink": None}])
        result, publish, record = await self.run_item(publish=publish)
        self.assertEqual(result, "publicado")
        self.assertEqual(publish.await_count, 2)
        self.assertFalse(shop.has_tags(publish.await_args_list[1].args[1]))
        self.assertIn("Product not eligible", record.await_args.args[2])


class ShopTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_ready_and_not_eligible(self):
        get = AsyncMock(side_effect=[{"shopping_product_tag_eligibility": True},
                                     {"data": [{"catalog_id": 9, "catalog_name": "Roove", "shop_name": "Roove", "product_count": 40}]}])
        with patch("services.ig_engagement.credentials", AsyncMock(return_value=CREDS)), patch.object(shop, "_get", get):
            out = await shop.shop_status("roove")
        self.assertTrue(out["ready"])
        self.assertEqual(out["catalogs"][0]["id"], "9")
        self.assertEqual(out["missing_scopes"], ["catalog_management"])
        with patch("services.ig_engagement.credentials", AsyncMock(return_value=CREDS)), \
             patch.object(shop, "_get", AsyncMock(return_value={"shopping_product_tag_eligibility": False})):
            out = await shop.shop_status("roove")
        self.assertFalse(out["ready"])
        self.assertIn("loja aprovada", out["message"])

    async def test_status_without_instagram_or_permission(self):
        with patch("services.ig_engagement.credentials", AsyncMock(side_effect=StudioError("IG_NOT_CONNECTED"))):
            out = await shop.shop_status("roove")
        self.assertIn("Conecte o Instagram", out["message"])
        with patch("services.ig_engagement.credentials", AsyncMock(return_value=CREDS)), \
             patch.object(shop, "_get", AsyncMock(side_effect=shop._friendly({"code": 10, "message": "Application does not have permission"}, 403))):
            out = await shop.shop_status("roove")
        self.assertIn("permissão de marcar produtos", out["message"])

    async def test_search_uses_first_catalog_and_maps_fields(self):
        get = AsyncMock(side_effect=[{"data": [{"catalog_id": "9"}]},
                                     {"data": [{"product_id": 5, "product_name": "Legging Preta", "image_url": "https://img", "retailer_id": "SKU1",
                                                "review_status": "approved", "product_variants": [{"product_id": 6, "variant_name": "P"}]}]}])
        with patch("services.ig_engagement.credentials", AsyncMock(return_value=CREDS)), patch.object(shop, "_get", get):
            out = await shop.search_products("roove", " legging ")
        self.assertEqual(get.await_args_list[1].kwargs["params"], {"catalog_id": "9", "q": "legging"})
        self.assertEqual(out[0], {"product_id": "5", "name": "Legging Preta", "image_url": "https://img", "sku": "SKU1",
                                  "review_status": "approved", "variants": [{"product_id": "6", "name": "P"}]})


if __name__ == "__main__":
    unittest.main()


class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_the_team_searches_products(self):
        from fastapi import HTTPException
        from routes import studio as r
        with patch.object(r, "require_client_read", AsyncMock(return_value="roove")), \
             patch.object(r, "is_agency_user", AsyncMock(return_value=False)):
            with self.assertRaises(HTTPException) as raised:
                await r.read_shop_products("roove", q="legging", authorization="Bearer cliente")
        self.assertEqual(raised.exception.status_code, 403)

    def test_client_cannot_send_product_tags(self):
        from services import studio_client as sc
        self.assertNotIn("product_tags", sc.CLIENT_FIELDS)
