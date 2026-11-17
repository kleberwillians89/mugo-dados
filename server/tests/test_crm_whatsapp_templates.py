"""Mugô CRM model management never accesses another tenant's WABA or token."""
import asyncio
from unittest.mock import AsyncMock
import httpx
import pytest

from services import crm_whatsapp_templates as service
from services.studio_calendar import StudioError
from routes import whatsapp as route


def test_bridge_only_reuses_existing_secure_crm_endpoint(monkeypatch):
    monkeypatch.setattr(service, "_config", lambda: (
        "https://crm.example.supabase.co/functions/v1/dados-ops-api", "private-server-key"))
    assert service._url() == (
        "https://crm.example.supabase.co/functions/v1/dados-whatsapp-templates", "private-server-key")


def test_templates_normalize_without_meta_secrets():
    item = service._normalize({
        "id": "123", "name": "modelo_mugo", "category": "UTILITY",
        "status": "APPROVED", "language": "pt_BR",
        "components": [{"type": "BODY", "text": "Olá {{1}}, seu pedido {{2}}."}],
    })
    assert item == {"name": "modelo_mugo", "language": "pt_BR", "status": "APPROVED",
                    "category": "UTILITY", "body": "Olá {{1}}, seu pedido {{2}}.", "variables": 2}


def test_403_denies_unlinked_company_without_fallback(monkeypatch):
    monkeypatch.setattr(service, "_config", lambda: (
        "https://crm.example.supabase.co/functions/v1/dados-ops-api", "private-key"))
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def request(self, method, url, **kwargs):
            assert kwargs["params"]["external_client_id"] == "other-company"
            return httpx.Response(403, json={"ok": False, "code": "UNKNOWN_EXTERNAL_CLIENT"})
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **kwargs: Client())
    with pytest.raises(StudioError) as exc:
        asyncio.run(service.list_templates("other-company"))
    assert exc.value.code == "CRM_TEMPLATES_NOT_LINKED"


def test_crm_create_only_uses_validated_templates(monkeypatch):
    calls = []
    async def request(tenant, *, method, payload=None, mode=None):
        calls.append((tenant, method, payload, mode))
        return {"template": {"id": "t1", "name": "modelo_mugo", "status": "PENDING"}}
    monkeypatch.setattr(service, "_request", request)
    result = asyncio.run(service.create_template("mugo-company", payload={
        "name": "modelo_mugo", "category": "UTILITY", "language": "pt_BR",
        "body": "Olá {{1}}", "examples": ["Ana"],
    }))
    assert result["status"] == "PENDING"
    assert result["provider"] == "mugozap_crm"
    assert calls[0][0:2] == ("mugo-company", "POST")
    assert calls[0][2]["components"][0]["example"] == {"body_text": [["Ana"]]}


def test_route_uses_crm_when_no_native_number(monkeypatch):
    from services import whatsapp_native as native
    from services import whatsapp_sources as sources
    async def agency(tenant, authorization, *, allowed_roles):
        return tenant
    async def no_numbers(_): return []
    async def crm_list(tenant):
        assert tenant == "mugo-tenant"
        return [{"name": "boas_vindas", "status": "APPROVED", "language": "pt_BR"}]
    monkeypatch.setattr(route, "require_client_role", agency)
    monkeypatch.setattr(native, "active_number_ids", no_numbers)
    monkeypatch.setattr(sources, "bridge_for", lambda _: None)
    monkeypatch.setattr(service, "list_templates", crm_list)
    result = asyncio.run(route.read_whatsapp_templates("mugo-tenant"))
    assert result["provider"] == "mugozap_crm"
    assert result["templates"][0]["name"] == "boas_vindas"
