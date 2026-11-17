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


def test_mugo_crm_with_messages_shows_connected_and_no_tokens(monkeypatch):
    import services.crm_bridge as crm
    import services.whatsapp_sources as sources
    async def role(cid, auth, *, allowed_roles):
        return cid
    async def numbers(_):
        return []
    async def crm_threads(cid, limit):
        assert cid == "mugo"
        assert limit == 1
        return {"available": True, "connected": True, "conversations": [{"id": "thread"}]}
    monkeypatch.setattr(whatsapp, "require_client_role", role)
    monkeypatch.setattr(whatsapp, "list_numbers", numbers)
    monkeypatch.setattr(sources, "bridge_for", lambda cid: None)
    monkeypatch.setattr(crm, "_config", lambda: ("https://crm.example", "SECRET-DO-NOT-EXPOSE"))
    monkeypatch.setattr(crm, "brand_conversations", crm_threads)
    data = asyncio.run(whatsapp.whatsapp_connection_status("mugo"))
    assert data["provider"] == "mugozap_crm"
    assert data["connected"] is True
    assert data["requires_meta_credentials"] is True
    assert data["meta_credentials_saved"] is False
    assert "SECRET-DO-NOT-EXPOSE" not in str(data)


def test_global_crm_config_does_not_mark_other_tenants_connected(monkeypatch):
    import services.crm_bridge as crm
    import services.whatsapp_sources as sources
    async def role(cid, auth, *, allowed_roles):
        return cid
    async def numbers(_):
        return []
    async def crm_threads(cid, limit):
        return {"available": False, "reason": "not_linked"}
    monkeypatch.setattr(whatsapp, "require_client_role", role)
    monkeypatch.setattr(whatsapp, "list_numbers", numbers)
    monkeypatch.setattr(sources, "bridge_for", lambda cid: None)
    monkeypatch.setattr(crm, "_config", lambda: ("https://crm.example", "SECRET"))
    monkeypatch.setattr(crm, "brand_conversations", crm_threads)
    data = asyncio.run(whatsapp.whatsapp_connection_status("other"))
    assert data["provider"] == "not_connected"
    assert data["connected"] is False
    assert data["crm_status_unavailable"] is True
