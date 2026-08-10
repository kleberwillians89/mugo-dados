from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import instagram_sync


class InstagramThumbnailBestEffortTests(unittest.IsolatedAsyncioTestCase):
    async def test_storage_400_opens_circuit_and_does_not_raise(self):
        request = httpx.Request("POST", "https://example.supabase.co/storage/v1/object/ig-media/path")
        response = httpx.Response(400, request=request, text='{"message":"invalid mime"}')
        upload_error = httpx.HTTPStatusError("bad request", request=request, response=response)
        jobs = [
            {"media_id": "m1", "source_url": "https://cdn/m1.jpg", "path": "clients/c/media/m1/thumb.jpg"},
            {"media_id": "m2", "source_url": "https://cdn/m2.jpg", "path": "clients/c/media/m2/thumb.jpg"},
        ]
        with (
            patch.object(instagram_sync, "download_image", AsyncMock(return_value=(b"image", "image/jpeg"))) as download,
            patch.object(instagram_sync, "sb_upload_public", AsyncMock(side_effect=upload_error)) as upload,
            patch.object(instagram_sync, "sb_update", AsyncMock()) as update,
        ):
            result = await instagram_sync._process_thumbnail_jobs(client_id="amalie", jobs=jobs)

        self.assertEqual(result, {"success": 0, "failed": 1, "skipped": 1})
        download.assert_awaited_once()
        upload.assert_awaited_once()
        update.assert_not_awaited()

    async def test_snapshot_and_connection_success_precede_best_effort_thumbnails(self):
        events: list[str] = []

        async def mark_success(_connection_id: str) -> None:
            events.append("connection_success")

        async def thumbnails(**_kwargs):
            events.append("thumbnails")
            return {"success": 0, "failed": 1, "skipped": 0}

        async def refresh_read_model(**_kwargs):
            events.append("read_model")
            return {"ok": True}

        sync_result = {
            "ok": True,
            "media": [],
            "comments_saved": 1,
            "snapshot_saved": True,
            "warnings": [],
            "_thumbnail_jobs": [{"media_id": "m1", "source_url": "url", "path": "path"}],
        }
        with (
            patch.object(instagram_sync, "_resolve_connection_by_id", AsyncMock(return_value={
                "id": "organic-1", "client_id": "amalie", "platform": "instagram", "ig_user_id": "ig-1",
            })),
            patch.object(instagram_sync, "ensure_valid_meta_token", AsyncMock(return_value="token")),
            patch.object(instagram_sync, "_run_sync_for_client_and_ig", AsyncMock(return_value=sync_result)),
            patch.object(instagram_sync, "_mark_connection_success", mark_success),
            patch.object(instagram_sync, "refresh_dashboard_read_model_safely", refresh_read_model),
            patch.object(instagram_sync, "_process_thumbnail_jobs", thumbnails),
        ):
            result = await instagram_sync._sync_instagram_connection("organic-1")

        self.assertEqual(events, ["read_model", "connection_success", "thumbnails"])
        self.assertTrue(result["ok"])
        self.assertTrue(result["read_model_refreshed"])
        self.assertIn("miniaturas", result["warnings"][0].lower())


if __name__ == "__main__":
    unittest.main()
