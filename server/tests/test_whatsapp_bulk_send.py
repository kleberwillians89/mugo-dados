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
        "lead_capture_events": [{"phone_ciphertext": "c2", "name_ciphertext": "n2"}],
    }
    plain = {"c1": "(11) 98888-7777", "n1": "Ana Souza", "c2": "21 96666-5555", "n2": "Mariana Dias"}
    with patch.object(send, "sb_select", AsyncMock(side_effect=_select_factory(tables))), \
            patch.object(send, "decrypt_secret", side_effect=lambda v: plain[v]):
        people = asyncio.run(send.recipients("roove", "all"))
    assert [p["phone"] for p in people] == ["5511988887777", "5521977776666", "5521966665555"]
    assert people[0]["name"] == "Ana"
    assert people[2]["name"] == "Mariana"


def test_leads_unificados_usa_planilha_captacao_e_conversas_recebidas():
    tables = {
        "relationship_contacts": [{"phone_ciphertext": "sheet", "name_ciphertext": "name"}],
        "whatsapp_threads": [{"wa_id": "5511988887777", "profile_name": "Ana"}],
        "lead_capture_events": [{"phone_ciphertext": "capture"}],
    }
    plain = {"sheet": "5511988887777", "name": "Ana Souza", "capture": "5521977776666"}
    with patch.object(send, "sb_select", AsyncMock(side_effect=_select_factory(tables))) as select, \
            patch.object(send, "decrypt_secret", side_effect=lambda value: plain[value]):
        people = asyncio.run(send.recipients("roove", "leads_unificados"))

    assert [person["phone"] for person in people] == ["5511988887777", "5521977776666"]
    filters = {call.args[0]: call.kwargs["filters"] for call in select.await_args_list}
    assert all(item["client_id"] == "eq.roove" for item in filters.values())
    assert filters["relationship_contacts"]["provider"] == "eq.planilha"
    assert filters["whatsapp_threads"]["last_inbound_at"] == "not.is.null"


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


def test_enviar_poe_na_fila_e_agendar_valida_data():
    draft = {"id": "d1", "status": "draft", "template_name": "bf", "language": "pt_BR", "audience_provider": "all"}
    updates = []
    with patch.object(send, "sb_select", AsyncMock(return_value=[draft])), \
            patch.object(send, "sb_update", AsyncMock(side_effect=lambda t, **kw: updates.append(kw["patch"]) or [])), \
            patch.object(send, "recipients", AsyncMock(return_value=[{"phone": "5511988887777", "name": "Ana"}])), \
            patch("services.whatsapp_native._active_number", AsyncMock(return_value={})), \
            patch("services.whatsapp_native.list_templates", AsyncMock(return_value=[
                {"name": "bf", "language": "pt_BR", "status": "APPROVED", "variables": 1}])):
        out = asyncio.run(send.start("roove", "d1"))
        assert out["status"] == "queued" and updates[-1]["scheduled_at"] is None
        from datetime import datetime, timedelta, timezone
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        out = asyncio.run(send.start("roove", "d1", tomorrow))
        assert out["status"] == "queued" and updates[-1]["scheduled_at"]
        try:
            asyncio.run(send.start("roove", "d1", "2099-01-01T10:00:00-03:00"))
            raise AssertionError("deveria recusar data longe demais")
        except send.BulkSendError as exc:
            assert "60 dias" in exc.message
    try:
        with patch.object(send, "sb_select", AsyncMock(return_value=[draft])):
            asyncio.run(send.start("roove", "d1", "2020-01-01T10:00:00-03:00"))
        raise AssertionError("deveria recusar data no passado")
    except send.BulkSendError as exc:
        assert "futuro" in exc.message


def test_modelo_com_imagem_exige_arquivo():
    try:
        send._check_template({"variables": 0, "header": "IMAGE"}, None)
        raise AssertionError("deveria exigir a imagem")
    except send.BulkSendError as exc:
        assert "imagem" in exc.message
    send._check_template({"variables": 0, "header": "IMAGE"}, "https://x/a.jpg")


def test_job_pega_a_fila_uma_vez_e_manda_a_imagem_do_topo():
    from datetime import datetime, timezone
    draft = {"id": "d1", "client_id": "roove", "status": "queued", "template_name": "bf", "language": "pt_BR",
             "audience_provider": "all", "header_media_url": "https://x/a.jpg"}

    async def select(table, **kw):
        return [draft] if kw["filters"].get("status") == "eq.queued" else []
    claims = AsyncMock(side_effect=[[{"id": "d1"}]])
    runner = AsyncMock(return_value={"sent": 1, "failed": 0, "skipped": 0})
    with patch.object(send, "sb_select", AsyncMock(side_effect=select)), patch.object(send, "sb_update", claims), \
            patch.object(send, "recipients", AsyncMock(return_value=[{"phone": "5511988887777", "name": "Ana"}])), \
            patch.object(send, "run", runner), \
            patch("services.whatsapp_native.list_templates", AsyncMock(return_value=[
                {"name": "bf", "language": "pt_BR", "status": "APPROVED", "variables": 0, "header": "IMAGE"}])):
        out = asyncio.run(send.process_due(datetime(2026, 11, 20, 12, tzinfo=timezone.utc)))
    assert out["campaigns"] == 1
    assert claims.await_args.kwargs["filters"]["status"] == "eq.queued"  # troca condicionada: só uma execução pega
    assert runner.await_args.args[4] == {"type": "image", "link": "https://x/a.jpg"}


def test_relatorio_responderam_e_compraram():
    from services.whatsapp_insights import phone_key
    key = phone_key("+5511988887777", international=True)
    draft = {"id": "d1", "status": "sent", "started_at": "2026-11-10T12:00:00+00:00", "sent_count": 2}

    async def select(table, **kw):
        if kw.get("offset", 0):
            return []
        return {"whatsapp_campaign_drafts": [draft], "whatsapp_campaign_sends": [{"phone_key": key, "status": "sent"},
                                                                                   {"phone_key": "f" * 32, "status": "sent"}],
                "whatsapp_threads": [{"phone_key": key, "last_inbound_at": "2026-11-10T13:00:00+00:00"}]}[table]
    orders = [{"value": 199.9, "phone": "11988887777"}]
    with patch.object(send, "sb_select", AsyncMock(side_effect=select)), \
            patch("services.whatsapp_insights._shopify_orders", AsyncMock(return_value=(orders, False))):
        out = asyncio.run(send.report("roove", "d1"))
    assert (out["replied"], out["buyers"], out["revenue"], out["reply_rate"]) == (1, 1, 199.9, 50.0)


def test_disparo_filtra_numero_equivalente_e_quem_ja_recebeu_modelo():
    people = [
        {"phone": "5511988887777", "name": "Ana"},
        {"phone": "(11) 8888-7777", "name": "Ana"},
        {"phone": "5521977776666", "name": "Bia"},
        {"phone": "5521966665555", "name": "Caio"},
        {"phone": "5521966665555", "name": "Caio"},
    ]
    sent_before = send.phone_key("5521977776666", international=True)
    sent_in_draft = send.phone_key("551188887777", international=True)
    rows = []

    async def select(table, **kw):
        if "whatsapp_campaign_drafts!inner" in kw.get("select", ""):
            assert kw["filters"]["whatsapp_campaign_drafts.template_name"] == "eq.bf"
            assert kw["filters"]["whatsapp_campaign_drafts.language"] == "eq.pt_BR"
            assert kw["filters"]["client_id"] == "eq.roove"
            return [{"phone_key": sent_before}]
        return [{"phone_hash": "existing", "phone_key": sent_in_draft, "status": "sent"}]

    draft = {"id": "d1", "template_name": "bf", "language": "pt_BR", "exclude_previous_template_recipients": True}
    sender = AsyncMock(return_value="wamid.1")
    with patch.object(send, "sb_select", AsyncMock(side_effect=select)), \
            patch.object(send, "opted_out", AsyncMock(return_value=set())), \
            patch.object(send, "sb_insert", AsyncMock(side_effect=lambda t, row, **kw: rows.append(row))), \
            patch.object(send, "sb_update", AsyncMock()), \
            patch("services.whatsapp_native.send_template", sender):
        counts = asyncio.run(send.run("roove", draft, people, 0))
    sender.assert_awaited_once()
    assert sender.await_args.kwargs["to"] == "5521966665555"
    assert counts == {"sent": 2, "failed": 0, "skipped": 1}
    assert any(row.get("error") == "Já recebeu este modelo" for row in rows)


def test_envio_de_teste_faz_uma_chamada_para_o_numero_informado():
    async def accepted(*args, **kwargs):
        kwargs["receipt"].update(number_id="sender", wa_id="5511988887777")
        return "wamid.teste"

    sender = AsyncMock(side_effect=accepted)
    with patch.object(send, "_template", AsyncMock(return_value={"variables": 1, "body": "Oi, {{1}}!"})), \
            patch.object(send, "opted_out", AsyncMock(return_value=set())), \
            patch.object(send, "sb_insert", AsyncMock()) as insert, \
            patch.object(send, "sb_rpc", AsyncMock()) as record, \
            patch("services.whatsapp_native.send_template", sender):
        saved = asyncio.run(send.send_test("roove", phone="(11) 98888-7777", template_name="bf_roove",
                                           language="pt_BR", header_media_url=None, recipient_name="Kleber Willians"))
    assert saved is True
    sender.assert_awaited_once()
    assert sender.await_args.kwargs["to"] == "5511988887777"
    assert sender.await_args.kwargs["params"] == ["Kleber"]
    record.assert_awaited_once()
    assert record.await_args.args[1]["p_text"] == "Oi, Kleber!"
    insert.assert_not_awaited()
