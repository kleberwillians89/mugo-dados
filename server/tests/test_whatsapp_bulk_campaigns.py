"""Campanhas WhatsApp: rascunhos e audiência, nunca disparos reais."""
import asyncio
from unittest.mock import AsyncMock

from services import whatsapp_campaign_drafts as campaigns
from routes import whatsapp


def test_preview_has_no_sendable_contacts_even_with_verified_flag(monkeypatch):
    monkeypatch.setattr(campaigns, "sb_select", AsyncMock(return_value=[
        {"client_id": "tenant-a", "provider": "shopify", "identity_hash": "a" * 64,
         "marketing_whatsapp_verified": True},
        {"client_id": "tenant-b", "provider": "shopify", "identity_hash": "b" * 64,
         "marketing_whatsapp_verified": True},
    ]))
    result = asyncio.run(campaigns.audience_preview("tenant-a"))
    assert result["total_contacts"] == 1
    assert result["consent_verified_count"] == 1
    assert result["sendable_count"] == 0


def test_save_draft_requires_approved_template(monkeypatch):
    insert = AsyncMock()
    monkeypatch.setattr(campaigns, "sb_insert", insert)
    try:
        asyncio.run(campaigns.save_draft("tenant-a",
            {"name": "Campanha piloto", "template_name": "aprovado", "language": "pt_BR",
             "provider": "shopify"}, approved=False))
    except ValueError:
        pass
    else:
        raise AssertionError("Template pendente não pode criar rascunho")
    insert.assert_not_awaited()


def test_save_draft_is_tenant_scoped_and_has_no_recipients(monkeypatch):
    audience = AsyncMock(return_value={"truncated": False, "sendable_count": 0})
    insert = AsyncMock(return_value={"id": "draft-1", "client_id": "tenant-a", "status": "draft"})
    monkeypatch.setattr(campaigns, "audience_preview", audience)
    monkeypatch.setattr(campaigns, "sb_insert", insert)
    out = asyncio.run(campaigns.save_draft("tenant-a",
        {"name": "Campanha piloto", "template_name": "aprovado", "language": "pt_BR",
         "provider": "whatsapp"}, approved=True))
    record = insert.await_args.args[1]
    assert record["client_id"] == "tenant-a"
    assert record["audience_provider"] == "whatsapp"
    assert record["status"] == "draft"
    assert record["simulated_count"] == 0
    assert out["messages_sent"] == 0


def test_routes_require_role_before_draft_access(monkeypatch):
    from fastapi import HTTPException
    denied = AsyncMock(side_effect=HTTPException(403, "Forbidden"))
    monkeypatch.setattr(whatsapp, "require_client_role", denied)
    try:
        asyncio.run(whatsapp.whatsapp_campaign_draft_list("tenant-a", authorization="Bearer x"))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("Tenant authorization bypass")
