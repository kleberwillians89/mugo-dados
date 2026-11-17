"""All WhatsApp clients use one template UI, each owning its own WABA and secrets."""
import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from routes import whatsapp
from services import brand_whatsapp_templates as templates
from services import whatsapp_native as native
from services import whatsapp_sources as sources
from services.studio_calendar import StudioError


def test_ruah_bridge_reuses_existing_server_key_without_new_token(monkeypatch):
    monkeypatch.setattr(templates, "bridge_for", lambda cid: {
        "url": "https://ruah.supabase.co/functions/v1/mugoverso-bridge",
        "key": "ruah-existing-private-bridge-key",
    } if cid == "ruah" else None)
    assert templates._config("ruah") == (
        "https://ruah.supabase.co/functions/v1/mugoverso-templates",
        "ruah-existing-private-bridge-key",
    )
    with pytest.raises(StudioError):
        templates._config("mugo")
    with pytest.raises(StudioError):
        templates._config("../ruah")


def test_brand_template_creation_uses_approved_whitelisted_fields(monkeypatch):
    sent = []

    async def call(cid, *, method, payload=None):
        sent.append((cid, method, payload))
        return {"template": {"name": "ruah_pedido", "status": "PENDING", "id": "t1"}}

    monkeypatch.setattr(templates, "_request", call)
    item = asyncio.run(templates.create_template("ruah", payload={
        "name": "ruah_pedido", "category": "UTILITY", "language": "pt_BR",
        "body": "Olá {{1}}", "examples": ["Ana"], "footer": "Ruah Parfums",
    }))
    assert item["provider"] == "crm_bridge"
    assert item["status"] == "PENDING"
    assert sent[0][0:2] == ("ruah", "POST")
    assert sent[0][2]["components"][0]["example"] == {"body_text": [["Ana"]]}
    with pytest.raises(StudioError) as err:
        asyncio.run(templates.create_template("ruah", payload={
            "name": "bad", "category": "MARKETING", "language": "pt_BR",
            "body": "Olá {{2}}", "examples": ["Ana", "Bia"],
        }))
    assert err.value.code == "CRM_TEMPLATE_INVALID"
    assert len(sent) == 1


def test_brand_bridge_failure_keeps_waba_isolated(monkeypatch):
    monkeypatch.setattr(templates, "bridge_for", lambda cid: {
        "url": "https://ruah.supabase.co/functions/v1/mugoverso-bridge", "key": "secret",
    } if cid == "ruah" else None)

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def request(self, method, url, **kwargs):
            assert kwargs["headers"] == {"X-Mugoverso-Key": "secret"}
            return httpx.Response(409, json={"ok": False, "code": "WABA_NOT_CONFIGURED"})

    monkeypatch.setattr(templates.httpx, "AsyncClient", lambda **kwargs: Client())
    with pytest.raises(StudioError) as err:
        asyncio.run(templates.list_templates("ruah"))
    assert err.value.code == "CRM_TEMPLATES_NOT_CONNECTED"
    with pytest.raises(StudioError):
        asyncio.run(templates.list_templates("some-other-client"))


def test_routes_use_same_contract_for_ruah_and_mugo_without_cross_waba(monkeypatch):
    async def access(cid, auth, *, allowed_roles):
        assert allowed_roles == whatsapp.TEMPLATE_ROLES
        return cid

    monkeypatch.setattr(whatsapp, "require_client_role", access)
    monkeypatch.setattr(native, "active_number_ids", AsyncMock(return_value=[]))
    monkeypatch.setattr(sources, "bridge_for", lambda cid: {"url": "https://ruah/", "key": "secret"} if cid == "ruah" else None)
    monkeypatch.setattr(templates, "bridge_for", lambda cid: {"url": "https://ruah/", "key": "secret"} if cid == "ruah" else None)
    monkeypatch.setattr(templates, "list_templates", AsyncMock(return_value=[{
        "name": "ruah_pedido", "language": "pt_BR", "status": "APPROVED", "category": "UTILITY",
    }]))
    from services import crm_whatsapp_templates as mugozap
    monkeypatch.setattr(mugozap, "list_templates", AsyncMock(return_value=[]))
    result = asyncio.run(whatsapp.read_whatsapp_templates("ruah"))
    assert result["provider"] == "crm_bridge"
    assert result["templates"][0]["name"] == "ruah_pedido"
    templates.list_templates.assert_awaited_once_with("ruah")
    mugozap.list_templates.assert_not_awaited()
    result = asyncio.run(whatsapp.read_whatsapp_templates("mugo"))
    assert result["provider"] == "mugozap_crm"
    mugozap.list_templates.assert_awaited_once_with("mugo")
