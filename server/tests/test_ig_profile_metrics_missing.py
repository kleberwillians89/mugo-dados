"""Conta sem métricas de perfil na Meta (ex.: < 100 seguidores): posts entram e a conexão não vira erro."""
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest

from services import instagram_sync as ig

NO_PROFILE = {"available_metrics": [], "unavailable_metrics": ["reach", "profile_views", "views"],
              "errors": {"reach": "HTTP 400 · código 10 · Application does not have permission for this action"}}


class ProfileMetricsMissingTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, media):
        rows, marks = {}, []

        async def upsert(table, values, **kwargs):
            rows[table] = values

        with ExitStack() as stack:
            for name, value in [
                ("_resolve_connection_by_id", AsyncMock(return_value={"platform": "instagram", "client_id": "m2", "ig_user_id": "17841"})),
                ("ensure_valid_meta_token", AsyncMock(return_value="synthetic")),
                ("fetch_profile", AsyncMock(return_value={"followers_count": 80})),
                ("fetch_media_list", AsyncMock(return_value=media)),
                ("fetch_media_insights", AsyncMock(return_value={"likes": 3, "available_metrics": ["likes"]})),
                ("fetch_kpis_total_value", AsyncMock(return_value=NO_PROFILE)),
                ("fetch_stories", AsyncMock(return_value=[])), ("sb_upsert", upsert),
                ("refresh_dashboard_read_model_safely", AsyncMock(return_value={"ok": True})),
                ("_mark_connection_success", AsyncMock(side_effect=lambda *a, **k: marks.append(k))),
                ("_mark_connection_error", AsyncMock(side_effect=lambda cid, msg: marks.append({"error": msg}))),
            ]:
                stack.enter_context(patch.object(ig, name, value))
            result = await ig._sync_instagram_connection("organic", process_thumbnails=False, persisted_only=True)
        return result, rows, marks

    async def test_posts_saved_without_profile_metrics_is_partial_success(self):
        result, rows, marks = await self._run([{"id": "m1", "media_type": "IMAGE"}])
        self.assertFalse(result["snapshot_saved"])
        self.assertTrue(rows["ig_media"])
        self.assertTrue(result["partial"])
        self.assertEqual(marks[0]["partial"], True)
        self.assertIn("código 10", marks[0]["detail"])  # motivo da Meta fica salvo na conexão
        self.assertTrue(any("código 10" in w for w in result["warnings"]))

    async def test_nothing_saved_still_fails_with_the_reason(self):
        with self.assertRaises(RuntimeError) as caught:
            await self._run([])
        self.assertIn("a Meta devolveu a conta sem nenhum post", str(caught.exception))
        self.assertIn("código 10", str(caught.exception))


if __name__ == "__main__":
    unittest.main()


def test_meta_error_summary_never_carries_token():
    import httpx
    from services.ig_meta import meta_error_summary
    request = httpx.Request("GET", "https://graph.facebook.com/v21.0/1/insights?access_token=SEGREDO")
    response = httpx.Response(400, request=request, json={"error": {"code": 100, "error_subcode": 2108006, "message": "Invalid parameter"}})
    out = meta_error_summary(httpx.HTTPStatusError("x", request=request, response=response))
    assert out == "HTTP 400 · código 100/2108006 · Invalid parameter" and "SEGREDO" not in out
