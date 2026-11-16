"""PACE demo: persistent synthetic facts are readable without pretending OAuth exists."""
import asyncio
from datetime import date, timedelta

from services import intelligence_tools


def test_pace_demo_exposes_only_demo_evidence(monkeypatch):
    start = date(2026, 11, 9)
    end = date(2026, 11, 15)
    async def select(table, *, select=None, filters=None, order=None, limit=None):
        assert filters["client_id"] == "eq.pace-sneakers-demo"
        if table in {"integration_connections", "meta_connections"}:
            return []
        assert table == "dashboard_daily_metrics"
        assert "metric_date.gte.2026-11-09" in filters["and"]
        return [
            {"client_id": "pace-sneakers-demo", "metric_date": (start + timedelta(days=i)).isoformat(),
             "shopify_net_revenue": 5000, "shopify_orders": 8,
             "meta_spend": 350, "meta_attributed_revenue": 1100,
             "google_ads_spend": 230, "google_ads_conversion_value": 820,
             "ga4_sessions": 430, "instagram_followers": 9000 + i,
             "instagram_interactions": 700}
            for i in range(7)
        ]

    monkeypatch.setattr(intelligence_tools, "sb_select", select)
    tools = intelligence_tools.ReadTools("pace-sneakers-demo", {"start": start.isoformat(), "end": end.isoformat()}, None)
    capabilities = asyncio.run(tools.discover())
    result = asyncio.run(tools.execute({"name": "read_metrics"}))
    metrics = {m["id"]: m for m in result["metrics"]}
    assert capabilities["demo"] is True
    assert metrics["revenue"]["value"] == 35000
    assert metrics["orders"]["value"] == 56
    assert metrics["revenue"]["status"] == "confirmed"
    assert all(s["connected"] is False and s["demo"] is True for s in result["sources"])
    assert "fictícias" in " ".join(result["limitations"])


def test_regular_tenant_does_not_inherit_demo_data(monkeypatch):
    async def empty(table, *, select=None, filters=None, order=None, limit=None):
        return []
    monkeypatch.setattr(intelligence_tools, "sb_select", empty)
    tools = intelligence_tools.ReadTools("other-client", {"start": "2026-11-09", "end": "2026-11-15"}, None)
    capabilities = asyncio.run(tools.discover())
    assert capabilities["sources"] == []
    assert capabilities["demo"] is False
