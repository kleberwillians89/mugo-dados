import asyncio
from unittest.mock import AsyncMock, patch

from services import ig_supabase


def test_recurring_sync_retries_errored_but_not_reauth():
    rows = [{"id": "a", "status": "active"}, {"id": "b", "status": "error", "requires_reauth": False},
            {"id": "c", "status": "error", "requires_reauth": True}]
    select = AsyncMock(return_value=rows)
    with patch.object(ig_supabase, "sb_select", select):
        out = asyncio.run(ig_supabase.sb_get_active_meta_connections(platform="instagram", include_errored=True))
    assert select.await_args.kwargs["filters"]["status"] == "in.(active,error)"
    assert [r["id"] for r in out] == ["a", "b"]


def test_default_still_only_active():
    select = AsyncMock(return_value=[{"id": "a"}])
    with patch.object(ig_supabase, "sb_select", select):
        asyncio.run(ig_supabase.sb_get_active_meta_connections(platform="instagram"))
    assert select.await_args.kwargs["filters"]["status"] == "eq.active"


def test_daily_instagram_and_hourly_ads_include_errored():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "services" / "cron_jobs.py").read_text(encoding="utf-8")
    assert 'platform="instagram", connection_type="organic", include_errored=True' in text
    assert 'platform="meta_ads", connection_type="paid", include_errored=True' in text
