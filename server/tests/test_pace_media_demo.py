"""Showcase media strategy reads the demo projection, not an OAuth account."""
import asyncio
from datetime import date, timedelta
from services import media_strategy


def test_demo_paid_window_is_scoped_and_has_two_channels(monkeypatch):
    async def fake_select(table, *, select=None, filters=None, order=None, limit=None):
        assert filters["client_id"] == "eq.pace-sneakers-demo"
        if table == "dashboard_daily_metrics":
            return [{
                "metric_date": "2026-11-15", "meta_spend": 350, "meta_impressions": 31000,
                "meta_clicks": 410, "meta_purchases": 3, "meta_attributed_revenue": 1100,
                "google_ads_spend": 220, "google_ads_impressions": 14000,
                "google_ads_clicks": 270, "google_ads_conversions": 2, "google_ads_conversion_value": 790,
            }]
        assert table == "dashboard_campaign_metrics"
        return [
            {"metric_date": "2026-11-15", "provider": "meta", "campaign_id": "M1",
             "campaign_name": "Run Your Way", "spend": 350, "impressions": 31000,
             "clicks": 410, "conversions": 3, "revenue": 1100},
            {"metric_date": "2026-11-15", "provider": "google_ads", "campaign_id": "G1",
             "campaign_name": "Search Running", "spend": 220, "impressions": 14000,
             "clicks": 270, "conversions": 2, "revenue": 790},
        ]
    from services import ig_supabase
    monkeypatch.setattr(ig_supabase, "sb_select", fake_select)
    result = asyncio.run(media_strategy.read_window("pace-sneakers-demo", date(2026, 11, 16)))
    assert result["meta"]["daily"][0]["spend"] == 350
    assert result["google_ads"]["daily"][0]["revenue"] == 790
    assert result["meta"]["campaigns"][0]["campaign_name"] == "Run Your Way"
    assert result["google_ads"]["campaigns"][0]["spend"] == 220
    assert result["meta"]["connected"] is False
