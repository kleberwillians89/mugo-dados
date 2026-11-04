import asyncio
from datetime import date
from unittest.mock import AsyncMock, patch

from services import ig_meta
from services import instagram_profile_history as ph

TODAY = date(2026, 11, 4)


def _insights(**values):
    return {"data": [{"name": k, "total_value": {"value": v}} for k, v in values.items()]}


def test_only_missing_days_are_written_never_today_or_existing():
    written = {}

    async def select(table, **kw):
        return [{"snapshot_date": "2026-11-03"}, {"snapshot_date": "2026-11-01"}]

    async def graph(path, params):
        return _insights(reach=100, profile_views=7, total_interactions=9)

    async def upsert(table, rows, on_conflict):
        written["rows"] = rows

    with patch.object(ph, "sb_select", select), patch.object(ph, "meta_get_json", graph), \
            patch.object(ph, "sb_upsert", upsert), patch.object(ph, "fetch_profile", AsyncMock(return_value={"followers_count": 500})):
        out = asyncio.run(ph.backfill_profile_days("tenant-a", "conn-a", "ig1", "tok", days=4, today=TODAY))
    days = sorted(r["snapshot_date"] for r in written["rows"])
    assert days == ["2026-10-31", "2026-11-02"]  # 03 e 01 já existiam; hoje (04) é do sync
    assert out == {"missing": 2, "written": 2, "refused": 0}
    row = written["rows"][0]
    assert row["client_id"] == "tenant-a" and row["reach_day"] == 100 and row["profile_views_day"] == 7
    assert "followers_count" in row["metrics_unavailable"]  # seguidores por dia não existem na API


def test_day_refused_by_meta_is_skipped_not_zeroed():
    async def select(table, **kw):
        return []

    async def graph(path, params):
        if params["since"] < 1793491200:  # antes de 01/11/2026 00:00 UTC
            raise RuntimeError("fora da janela")
        return _insights(reach=5)

    rows = []
    with patch.object(ph, "sb_select", select), patch.object(ph, "meta_get_json", graph), \
            patch.object(ph, "sb_upsert", AsyncMock(side_effect=lambda t, r, on_conflict: rows.extend(r))), \
            patch.object(ph, "fetch_profile", AsyncMock(return_value={})):
        out = asyncio.run(ph.backfill_profile_days("c", "k", "ig", "t", days=5, today=TODAY))
    assert sorted(r["snapshot_date"] for r in rows) == ["2026-11-01", "2026-11-02", "2026-11-03"]
    assert out["refused"] == 2


def test_nothing_missing_makes_no_meta_call():
    async def select(table, **kw):
        return [{"snapshot_date": f"2026-11-0{d}"} for d in (1, 2, 3)]

    graph = AsyncMock()
    with patch.object(ph, "sb_select", select), patch.object(ph, "meta_get_json", graph):
        out = asyncio.run(ph.backfill_profile_days("c", "k", "ig", "t", days=3, today=TODAY))
    assert out["written"] == 0
    graph.assert_not_awaited()


def test_profile_kpis_are_read_in_parallel_and_failures_isolated():
    state = {"now": 0, "max": 0}

    async def fetch(ig, token, metric):
        state["now"] += 1
        state["max"] = max(state["max"], state["now"])
        await asyncio.sleep(0.01)
        state["now"] -= 1
        if metric == "website_clicks":
            raise RuntimeError("indisponível")
        return {metric: 3}

    with patch.object(ig_meta, "_fetch_total_value_metrics", fetch):
        out = asyncio.run(ig_meta.fetch_kpis_total_value("ig", "tok"))
    assert state["max"] >= 5
    assert out["reach"] == 3 and out["impressions"] == 3
    assert "website_clicks" in out["unavailable_metrics"]
