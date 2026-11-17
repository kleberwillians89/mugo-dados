"""Templates are submitted only to the selected tenant WABA and never send messages."""
import asyncio
from unittest.mock import AsyncMock
import pytest

from services import whatsapp_native as wa


def test_template_payload_has_meta_body_examples():
    payload = wa.validate_template_input(
        name="roove_pedido_confirmado", category="UTILITY", language="pt_BR",
        body="Olá {{1}}, pedido {{2}} confirmado.", examples=["Ana", "#123"],
        footer="Equipe Roove",
    )
    assert payload["name"] == "roove_pedido_confirmado"
    assert payload["components"][0]["example"]["body_text"] == [["Ana", "#123"]]
    assert payload["components"][1] == {"type": "FOOTER", "text": "Equipe Roove"}


@pytest.mark.parametrize("name,body,examples", [
    ("Bad Name", "Olá", []),
    ("ok_name", "Olá {{2}}", ["Ana", "Pedido"]),
    ("ok_name", "Olá {{1}}", []),
    ("ok_name", "Olá {{nome}}", []),
    ("ok_name", "Olá {{1}}", [""]),
])
def test_invalid_templates_rejected_before_meta(name, body, examples):
    with pytest.raises(wa.WhatsAppNativeError):
        wa.validate_template_input(name=name, category="MARKETING", language="pt_BR",
                                   body=body, examples=examples)


def test_create_template_uses_the_owning_waba_only(monkeypatch):
    calls = []
    async def active(client_id, number_id):
        assert client_id == "roove"
        assert number_id is None
        return {"waba_id": "987654321", "access_token": "secret"}
    async def graph(method, path, token, **kwargs):
        calls.append((method, path, token, kwargs))
        return {"id": "1234", "status": "PENDING", "category": "MARKETING"}
    monkeypatch.setattr(wa, "_active_number", active)
    monkeypatch.setattr(wa, "_graph", graph)
    result = asyncio.run(wa.create_template(
        "roove", number_id=None, name="roove_first_access", category="MARKETING",
        language="pt_BR", body="Acesso antecipado para {{1}}.", examples=["Ana"],
    ))
    assert result["status"] == "PENDING"
    assert result["waba_id"] == "987654321"
    assert calls[0][0:3] == ("POST", "987654321/message_templates", "secret")
    assert calls[0][3]["json_body"]["category"] == "MARKETING"
