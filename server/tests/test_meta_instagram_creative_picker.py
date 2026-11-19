"""Tenant isolation for synchronized Instagram creative picker."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routes import meta_ads_publish as route


class InstagramCreativePickerTests(unittest.IsolatedAsyncioTestCase):
    async def test_posts_are_filtered_by_authorized_company(self):
        records = [
            {"media_id": "img1", "media_type": "IMAGE", "caption": "Look de verão",
             "media_product_type": "FEED", "thumb_url": "https://cdn.example.com/cover.jpg",
             "media_url": "https://cdn.example.com/full.jpg", "permalink": "https://instagram.com/p/post1",
             "timestamp": "2026-11-18T12:00:00Z"},
            {"media_id": "vid1", "media_type": "VIDEO", "caption": "Reel",
             "media_product_type": "REELS", "thumb_url": "https://cdn.example.com/video.jpg",
             "media_url": "https://cdn.example.com/reel.mp4", "timestamp": "2026-11-18T12:00:00Z"},
            {"media_id": "car1", "media_type": "CAROUSEL_ALBUM", "caption": "Carrossel",
             "media_product_type": "FEED", "thumb_url": "https://cdn.example.com/carousel.jpg",
             "timestamp": "2026-11-18T12:00:00Z"},
        ]
        with patch.object(route, "require_client_role", new_callable=AsyncMock, return_value="roove"), \
             patch.object(route, "sb_select", new_callable=AsyncMock, return_value=records) as select:
            data = await route.read_instagram_posts("roove")
        self.assertEqual(select.await_args.kwargs["filters"], {"client_id": "eq.roove"})
        self.assertEqual(select.await_args.args[0], "ig_media")
        self.assertEqual([p["selectable"] for p in data["posts"]], [True, True, True])
        self.assertEqual(data["posts"][0]["image_url"], records[0]["media_url"])
        self.assertIsNone(data["posts"][1]["image_url"])
        self.assertEqual(data["posts"][1]["video_url"], records[1]["media_url"])
        self.assertEqual(data["posts"][2]["image_url"], records[2]["thumb_url"])
        self.assertEqual(data["count"], 3)

    async def test_company_membership_is_checked_before_database_read(self):
        from fastapi import HTTPException
        with patch.object(route, "require_client_role", new_callable=AsyncMock,
                          side_effect=HTTPException(403, "Acesso negado")), \
             patch.object(route, "sb_select", new_callable=AsyncMock) as select:
            with self.assertRaises(HTTPException):
                await route.read_instagram_posts("other-client")
        select.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
