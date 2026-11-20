"""Disparo em massa: todos com telefone, sem repetir, sem quem pediu para sair, retomando de onde parou."""
import asyncio
from unittest.mock import AsyncMock, patch

from services import whatsapp_campaign_send as send
from services.whatsapp_native import WhatsAppNativeError


def test_normaliza_telefone_brasileiro():
    assert send.normalize_phone("(11) 98888-7777") == "5511988887777"
    assert send.normalize_phone("+55 11 98888-7777") == "5511988887777"
    assert send.normalize_phone("123") is None
    assert send.first_name("maria eduarda silva") == "Maria"
    assert send.first_name("") == "cliente"


def _select_factory(tables):
    async def select(table, **kw):
        rows = tables.get(table, [])
        return rows if kw.get("offset", 0) == 0 else []
    return select


def test_recipients_junta_origens_sem_repetir():
    tables = {
        "relationship_contacts": [{"phone_ciphertext": "c1", "name_ciphertext": "n1"}],
        "whatsapp_threads": [{"wa_id": "5511988887777", "profile_name": "Ana"}, {"wa_id": "5521977776666", "profile_name": "Bia"}],
        "lead_capture_events": [{"phone_ciphertext": "c2"}],
    }
    plain = {"c1": "(11) 98888-7777", "n1": "Ana Souza", "c2": "21 96666-5555"}
    with patch.object(send, "sb_select", AsyncMock(side_effect=_select_factory(tables))), \
            patch.object(send, "decrypt_secret", side_effect=lambda v: plain[v]):
        people = asyncio.run(send.recipients("roove", "all"))
    assert [p["phone"] for p in people] == ["5511988887777", "5521977776666", "5521966665555"]
    assert people[0]["name"] == "Ana"


def test_run_envia_pula_quem_saiu_e_conta():
    people = [{"phone": "5511988887777", "name": "Ana"}, {"phone": "5521977776666", "name": "Bia"},
              {"phone": "5531955554444", "name": "Caio"}]
    inserted, updates = [], []

    async def select(table, **kw):
        if table == "whatsapp_campaign_sends":
            return []
        if table == "whatsapp_messages":
            return [{"thread_id": "t1"}] if kw.get("offset", 0) == 0 else []
        if table == "whatsapp_threads":
            return [{"wa_id": "5521977776666"}]
        return []

    async def deliver(client_id, **kw):
        if kw["to"] == "5531955554444":
            raise WhatsAppNativeError("META", "Número sem WhatsApp")
        return "wamid.1"
    sender = AsyncMock(side_effect=deliver)
    with patch.object(send, "sb_select", AsyncMock(side_effect=select)), \
            patch.object(send, "sb_insert", AsyncMock(side_effect=lambda t, row, **kw: inserted.append(row))), \
            patch.object(send, "sb_update", AsyncMock(side_effect=lambda t, **kw: updates.append(kw["patch"]))), \
            patch("services.whatsapp_native.send_template", sender):
        counts = asyncio.run(send.run("roove", {"id": "d1", "template_name": "bf", "language": "pt_BR"}, people, 1))
    assert counts == {"sent": 1, "failed": 1, "skipped": 1}
    assert sender.await_args_list[0].kwargs["params"] == ["Ana"]
    assert {r["status"] for r in inserted} == {"sent", "failed", "skipped"}
    assert all("5511" not in r["phone_hash"] for r in inserted)  # telefone não fica salvo em claro
    assert updates[-1]["status"] == "partial" and updates[-1]["last_error"] == "Número sem WhatsApp"


def test_retomar_nao_reenvia_quem_ja_recebeu():
    people = [{"phone": "5511988887777", "name": "Ana"}]
    already = [{"phone_hash": send.phone_hash("roove", "5511988887777"), "status": "sent"}]

    async def select(table, **kw):
        return already if table == "whatsapp_campaign_sends" and kw.get("offset", 0) == 0 else []
    sender = AsyncMock()
    updates = []
    with patch.object(send, "sb_select", AsyncMock(side_effect=select)), patch.object(send, "sb_insert", AsyncMock()), \
            patch.object(send, "sb_update", AsyncMock(side_effect=lambda t, **kw: updates.append(kw["patch"]))), \
            patch("services.whatsapp_native.send_template", sender):
        counts = asyncio.run(send.run("roove", {"id": "d1", "template_name": "bf", "language": "pt_BR"}, people, 0))
    sender.assert_not_awaited()
    assert counts["sent"] == 1 and updates[-1]["status"] == "sent"


def test_start_recusa_modelo_com_muitas_variaveis():
    draft = {"id": "d1", "status": "draft", "template_name": "bf", "language": "pt_BR", "audience_provider": "all"}
    with patch.object(send, "sb_select", AsyncMock(return_value=[draft])), \
            patch("services.whatsapp_native._active_number", AsyncMock(return_value={})), \
            patch("services.whatsapp_native.list_templates", AsyncMock(return_value=[
                {"name": "bf", "language": "pt_BR", "status": "APPROVED", "variables": 2}])):
        try:
            asyncio.run(send.start("roove", "d1"))
            raise AssertionError("deveria recusar")
        except send.BulkSendError as exc:
            assert "até 1 variável" in exc.message
