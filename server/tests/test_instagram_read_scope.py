from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import comments  # noqa: E402


class InstagramCommentScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_comments_are_queried_by_resolved_connection_and_civil_period(self):
        connection_id = "00bb094c-337a-49b3-b2bc-5aec75d79da5"
        calls = []

        async def select(table, **kwargs):
            calls.append((table, kwargs))
            if table == "ig_media":
                return [{"media_id": "media-1"}]
            return [{"comment_id": "comment-1", "media_id": "media-1", "timestamp": "2026-08-10T12:00:00Z"}]

        with (
            patch.object(
                comments,
                "resolve_connection_for_scope",
                AsyncMock(return_value={"connection_id": connection_id, "source": "requested"}),
            ),
            patch.object(comments, "sb_select", side_effect=select),
        ):
            result = await comments.get_comments(
                "amalie", connection_id=connection_id, start="2026-08-10", end="2026-08-10"
            )

        comment_filters = calls[0][1]["filters"]
        self.assertEqual(comment_filters["connection_id"], f"eq.{connection_id}")
        self.assertIn("timestamp.gte.2026-08-10T03:00:00+00:00", comment_filters["and"])
        self.assertIn("timestamp.lte.2026-08-11T02:59:59.999999+00:00", comment_filters["and"])
        self.assertEqual(result["comments"][0]["comment_id"], "comment-1")


if __name__ == "__main__":
    unittest.main()
