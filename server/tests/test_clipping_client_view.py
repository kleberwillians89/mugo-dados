import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI

from routes import content_ops as routes

CID = "tenant-a"
VIEW = {
    "items": [{"id": "1", "relevant": True}, {"id": "2", "relevant": False}, {"id": "3", "relevant": None}],
    "week": {"current": {}},
    "settings": {"saved": True, "last_run_at": "2026-10-30", "brand_terms": ["x"], "competitor_terms": ["y"]},
}


class ClippingClientViewTests(unittest.IsolatedAsyncioTestCase):
    async def get(self, agency: bool):
        app = FastAPI()
        app.include_router(routes.router)
        read = AsyncMock(return_value=CID)
        with patch.object(routes, "require_client_read", read), \
             patch.object(routes, "is_agency_user", AsyncMock(return_value=agency)), \
             patch.object(routes.clipping, "list_clippings", AsyncMock(return_value=VIEW)):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get(f"/api/clients/{CID}/studio/clipping")
        read.assert_awaited_once()
        return response.json()

    async def test_client_sees_only_relevant_news_without_terms(self):
        data = await self.get(agency=False)
        self.assertEqual([i["id"] for i in data["items"]], ["1", "3"])
        self.assertEqual(data["settings"], {"saved": True, "last_run_at": "2026-10-30"})

    async def test_agency_sees_everything(self):
        data = await self.get(agency=True)
        self.assertEqual(len(data["items"]), 3)
        self.assertIn("competitor_terms", data["settings"])


if __name__ == "__main__":
    unittest.main()
