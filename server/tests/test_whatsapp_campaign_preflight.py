"""A pré-validação não dispara mensagens: só diz se o modelo aprovado pode ser usado no envio."""
import asyncio
from unittest.mock import AsyncMock

from routes import whatsapp as routes
from services import whatsapp_native


def test_whatsapp_preflight_approved_without_send(monkeypatch):
    monkeypatch.setattr(routes, "require_client_role", AsyncMock(return_value="tenant-a"))
    monkeypatch.setattr(whatsapp_native, "active_number_ids", AsyncMock(return_value=["number-a"]))
    monkeypatch.setattr(routes, "list_templates", AsyncMock(return_value=[
        {"name": "campanha_vip", "language": "pt_BR", "status": "APPROVED"}
    ]))
    result = asyncio.run(routes.whatsapp_template_preflight(
        "tenant-a", routes.WhatsAppTemplatePreflight(template_name="campanha_vip"), authorization="Bearer test"
    ))
    assert result["template_approved"] is True
    assert result["can_send"] is True
    assert result["messages_sent"] == 0


def test_whatsapp_preflight_rejects_pending_template(monkeypatch):
    monkeypatch.setattr(routes, "require_client_role", AsyncMock(return_value="tenant-a"))
    monkeypatch.setattr(whatsapp_native, "active_number_ids", AsyncMock(return_value=["number-a"]))
    monkeypatch.setattr(routes, "list_templates", AsyncMock(return_value=[
        {"name": "campanha_vip", "language": "pt_BR", "status": "PENDING"}
    ]))
    result = asyncio.run(routes.whatsapp_template_preflight(
        "tenant-a", routes.WhatsAppTemplatePreflight(template_name="campanha_vip"), authorization="Bearer test"
    ))
    assert result["template_approved"] is False
    assert result["can_send"] is False
