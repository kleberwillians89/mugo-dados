"""Shared template visibility must not imply CRM bridge send capability."""
import asyncio
from unittest.mock import AsyncMock
import pytest

from routes import email_marketing as routes
from services import brand_whatsapp_templates, crm_whatsapp_templates, whatsapp_native
from services import whatsapp_sources
from services.studio_calendar import StudioError


def test_ruah_templates_visible_but_not_sendable_by_native_automation(monkeypatch):
    async def access(client_id, authorization):
        return client_id
    monkeypatch.setattr(routes, "require_client_read", access)
    monkeypatch.setattr(whatsapp_native, "list_numbers", AsyncMock(return_value=[]))
    monkeypatch.setattr(whatsapp_sources, "bridge_for", lambda cid: {"url": "https://ruah.test/"} if cid == "ruah" else None)
    monkeypatch.setattr(brand_whatsapp_templates, "list_templates", AsyncMock(return_value=[{
        "name": "ruah_promocao", "status": "APPROVED", "language": "pt_BR",
        "category": "MARKETING", "body": "Olá", "variables": 0,
    }]))
    result = asyncio.run(routes.cart_templates(client_id="ruah"))
    assert result["provider"] == "crm_bridge"
    assert result["send_supported"] is False
    assert result["templates"][0]["name"] == "ruah_promocao"


def test_native_template_sender_keeps_its_own_number(monkeypatch):
    async def access(client_id, authorization):
        return client_id
    monkeypatch.setattr(routes, "require_client_read", access)
    monkeypatch.setattr(whatsapp_native, "list_numbers", AsyncMock(return_value=[{"id": "1", "status": "active"}]))
    monkeypatch.setattr(whatsapp_native, "list_templates", AsyncMock(return_value=[]))
    result = asyncio.run(routes.cart_templates(client_id="native-client"))
    assert result["provider"] == "native"
    assert result["send_supported"] is True
    assert result["templates"] == []


def test_missing_mugo_crm_mapping_returns_no_templates(monkeypatch):
    async def access(client_id, authorization):
        return client_id
    monkeypatch.setattr(routes, "require_client_read", access)
    monkeypatch.setattr(whatsapp_native, "list_numbers", AsyncMock(return_value=[]))
    monkeypatch.setattr(whatsapp_sources, "bridge_for", lambda _: None)
    monkeypatch.setattr(crm_whatsapp_templates, "list_templates", AsyncMock(side_effect=StudioError("CRM_TEMPLATES_NOT_LINKED")))
    result = asyncio.run(routes.cart_templates(client_id="unlinked"))
    assert result["templates"] == []
    assert result["provider"] == "none"
    assert result["send_supported"] is False
