import asyncio
from datetime import date

from services import history_backfill as hb
from services import instagram_history as ih


def _item(i, ts, product="FEED", **extra):
    return {"id": str(i), "timestamp": ts, "media_type": "IMAGE", "media_product_type": product, **extra}


def test_lists_only_block_window_and_stops_after_start(monkeypatch):
    calls = []
    page1 = {"data": [_item(1, "2026-03-10T12:00:00+0000"), _item(2, "2026-02-20T12:00:00+0000"),
                      _item(3, "2026-02-05T12:00:00+0000", product="STORY")],
             "paging": {"next": "https://graph.facebook.com/next"}}

    async def first(path, params):
        calls.append(path)
        return {**page1, "data": page1["data"] + [_item(4, "2026-01-15T12:00:00+0000")]}

    monkeypatch.setattr(ih, "meta_get_json", first)
    items = asyncio.run(ih.list_media_between("ig1", "tok", date(2026, 2, 1), date(2026, 2, 28)))
    assert [i["id"] for i in items] == ["2"]  # story e fora da janela ficam de fora; não pagina além do início
    assert calls == ["/ig1/media"]


def test_media_row_uses_listing_fallback():
    row = ih.media_row("c1", "conn", _item(9, "2026-02-20T12:00:00+0000", like_count=12, comments_count=3,
                                           media_url="https://cdn/x.jpg", caption="oi"), {"reach": 100})
    assert row["insights_json"] == {"reach": 100, "likes": 12, "comments": 3, "total_interactions": 15}
    assert row["thumb_url"] == "https://cdn/x.jpg" and row["caption"] == "oi"


def test_instagram_is_part_of_history_plan():
    assert "instagram" in hb.PROVIDERS and "instagram" in hb.RUNNERS and "instagram" in hb.CONNECTIONS
    assert hb.EARLIEST["instagram"] == ("ig_media", "timestamp")
    assert hb.EARLIEST_FILTERS["instagram"]


def test_restart_cancels_running_and_requests_all(monkeypatch):
    seen = {"cancel": [], "all": None}

    async def select(table, **kw):
        return [{"client_id": "a"}, {"client_id": "a"}, {"client_id": "b"}]

    async def cancel(cid):
        seen["cancel"].append(cid)
        return {"ok": True}

    async def request_all(start, *, requested_by):
        seen["all"] = (start, requested_by)
        return {"ok": True, "start": start, "companies": []}

    monkeypatch.setattr(hb, "sb_select", select)
    monkeypatch.setattr(hb, "cancel_history", cancel)
    monkeypatch.setattr(hb, "request_history_all", request_all)
    out = asyncio.run(hb.restart_history_all("2026-01-01"))
    assert seen["cancel"] == ["a", "b"] and seen["all"] == ("2026-01-01", "github_actions") and out["cancelled"] == 2
