"""Universal WhatsApp connection status — no credential exposure across tenants."""
import asyncio
from unittest.mock import AsyncMock

from routes import whatsapp


def test_native_status_is_tenant_scoped_and_secrets_are_never_returned(monkeypatch):
    async def role(client_id, authorization, *, allowed_roles):
        assert client_id == "roove"
        assert allowed_roles == whatsapp.NUMBER_ROLES
        return "roove"
    async def numbers(client_id):
        assert client_id == "roove"
        return [{"id": "n1", "status": "active", "display_phone_number": "•••• 1234",
                 "waba_id": "123", "phone_number_id": "456"}]
    monkeypatch.setattr(whatsapp, "require_client_role", role)
    monkeypatch.setattr(whatsapp, "list_numbers", numbers)
    import services.whatsapp_sources as sources
    monkeypatch.setattr(sources, "bridge_for", lambda client_id: None)
    data = asyncio.run(whatsapp.whatsapp_connection_status("roove"))
    assert data["provider"] == "native"
    assert data["meta_credentials_saved"] is True
    assert "access_token" not in str(data)
    assert "key" not in data["numbers"][0]


def test_crm_bridge_is_not_a_meta_credential(monkeypatch):
    async def role(cid, auth, *, allowed_roles):
        return cid
    async def numbers(_):
        return []
    monkeypatch.setattr(whatsapp, "require_client_role", role)
    monkeypatch.setattr(whatsapp, "list_numbers", numbers)
    import services.whatsapp_sources as sources
    monkeypatch.setattr(sources, "bridge_for", lambda cid: {"url": "https://crm.example", "key": "secret-key"})
    data = asyncio.run(whatsapp.whatsapp_connection_status("ruah-client"))
    assert data["provider"] == "crm_bridge"
    assert data["crm_bridge_configured"] is True
    assert data["requires_meta_credentials"] is True
    assert "secret-key" not in str(data)


def test_unconnected_tenant_has_clear_setup_state(monkeypatch):
    async def role(cid, auth, *, allowed_roles):
        return cid
    async def numbers(_):
        return []
    monkeypatch.setattr(whatsapp, "require_client_role", role)
    monkeypatch.setattr(whatsapp, "list_numbers", numbers)
    import services.whatsapp_sources as sources
    monkeypatch.setattr(sources, "bridge_for", lambda cid: None)
    data = asyncio.run(whatsapp.whatsapp_connection_status("another-client"))
    assert data["provider"] == "not_connected"
    assert data["number_count"] == 0
    assert data["requires_meta_credentials"] is True
