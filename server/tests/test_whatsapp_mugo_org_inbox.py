"""Org-owned MugôZap inbox uses verified CRM link; Ruah and other tenants remain unchanged."""
import asyncio
from unittest.mock import AsyncMock
import pytest

from services import whatsapp_sources as sources
from services import crm_bridge
from services import crm_whatsapp_templates as org
from services.studio_calendar import StudioError


def test_org_owned_inbox_fallback_only_after_explicit_not_linked(monkeypatch):
    monkeypatch.setattr(sources, "bridge_for", lambda _: None)
    monkeypatch.setattr(sources.whatsapp_native, "active_number_ids", AsyncMock(return_value=[]))
    monkeypatch.setattr(crm_bridge, "brand_conversations",
                        AsyncMock(return_value={"available": False, "reason": "not_linked"}))
    org_mock = AsyncMock(return_value={"available": True, "connected": True, "conversations": [
        {"id": "c1", "contact": {"phone_masked": "•••• 1234"}}]})
    monkeypatch.setattr(org, "brand_conversations", org_mock)
    result = asyncio.run(sources.brand_conversations("mugo-tenant", limit=50))
    assert result["connected"] and len(result["conversations"]) == 1
    org_mock.assert_awaited_once_with("mugo-tenant", limit=50)


def test_no_cross_tenant_fallback_without_not_linked(monkeypatch):
    monkeypatch.setattr(sources, "bridge_for", lambda _: None)
    monkeypatch.setattr(sources.whatsapp_native, "active_number_ids", AsyncMock(return_value=[]))
    monkeypatch.setattr(crm_bridge, "brand_conversations",
                        AsyncMock(return_value={"available": True, "connected": True, "conversations": []}))
    org_mock = AsyncMock()
    monkeypatch.setattr(org, "brand_conversations", org_mock)
    result = asyncio.run(sources.brand_conversations("roove-tenant"))
    assert result["available"]
    org_mock.assert_not_awaited()


def test_missing_org_link_never_leaks_any_other_waba(monkeypatch):
    monkeypatch.setattr(sources, "bridge_for", lambda _: None)
    monkeypatch.setattr(sources.whatsapp_native, "active_number_ids", AsyncMock(return_value=[]))
    monkeypatch.setattr(crm_bridge, "brand_conversations",
                        AsyncMock(return_value={"available": False, "reason": "not_linked"}))
    org_mock = AsyncMock(side_effect=StudioError("CRM_TEMPLATES_NOT_LINKED"))
    monkeypatch.setattr(org, "brand_conversations", org_mock)
    result = asyncio.run(sources.brand_conversations("unlinked-tenant"))
    assert not result["available"] and result["reason"] == "not_linked"


def test_org_owned_messages_and_leads_are_separate_read_only_queries(monkeypatch):
    async def request(cid, *, method, mode=None, options=None, **_):
        assert cid == "mugo-tenant" and method == "GET"
        if mode == "messages":
            assert options["conversation_id"] == "11111111-1111-4111-8111-111111111111"
            return {"messages": [{"id": "message-1", "text": "Olá"}]}
        if mode == "leads":
            return {"connected": True, "leads": [{"first_seen_at": "2026-11-17T12:00:00Z"}]}
        return {"connected": True, "conversations": []}
    monkeypatch.setattr(org, "_request", request)
    messages = asyncio.run(org.brand_messages("mugo-tenant", "11111111-1111-4111-8111-111111111111"))
    leads = asyncio.run(org.brand_leads("mugo-tenant", "2026-11-17", "2026-11-17"))
    assert messages["messages"][0]["id"] == "message-1"
    assert leads["connected"] and len(leads["leads"]) == 1
