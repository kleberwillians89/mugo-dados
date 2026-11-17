import asyncio
import pytest
from services import google_ad_drafts

def payload(**patch):
    data = {
        "platform": "google_ads", "name": "Search — Running", "objective": "vendas",
        "daily_budget": 30, "start_date": "2026-11-17", "end_date": "2026-12-01",
        "final_url": "https://example.com", "locations": ["São Paulo"],
        "keywords": ["tênis de corrida"], "headlines": ["PACE Running"],
        "descriptions": ["Conheça nossa linha"], "notes": "Somente rascunho",
        "contains_eu_political_advertising": False,
    }
    return {**data, **patch}

def test_google_campaign_draft_normalization():
    result = google_ad_drafts.clean_payload(payload())
    assert result["platform"] == "google_ads"
    assert result["type"] == "SEARCH"
    assert result["daily_budget"] == 30
    assert result["keywords"] == ["tênis de corrida"]

def test_google_campaign_dates_and_url_are_validated():
    from services.studio_calendar import StudioError
    with pytest.raises(StudioError):
        google_ad_drafts.clean_payload(payload(start_date="2026-12-02"))
    with pytest.raises(StudioError):
        google_ad_drafts.clean_payload(payload(final_url="http://insecure.example.com"))
    with pytest.raises(StudioError):
        google_ad_drafts.clean_payload(payload(daily_budget=-5))

def test_google_draft_lookup_is_tenant_and_platform_scoped(monkeypatch):
    seen = []
    async def fake_select(table, *, select=None, filters=None, limit=None, **kwargs):
        seen.append(filters)
        return [{"id": "abc", "client_id": "acme", "payload": {"platform": "meta"}}]
    monkeypatch.setattr(google_ad_drafts, "sb_select", fake_select)
    with pytest.raises(Exception):
        asyncio.run(google_ad_drafts.owned("acme", "abc"))
    assert seen == [{"client_id": "eq.acme", "id": "eq.abc"}]
