"""Gatilhos do Dados que alimentam a fila de automações (aprovação, publicação, ajustes e eventos explícitos).

Tarefas, resumo diário, financeiro e leads NÃO estão aqui: o CRM já dispara essas mensagens
(ver automation_definitions.owner = 'crm'); repetir aqui duplicaria o envio.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from . import automations
from .crypto import encrypt_secret
from .ig_supabase import sb_select, sb_update
from .studio_calendar import ITEMS_TABLE, StudioError

SAO_PAULO = automations.SAO_PAULO
PUBLISH_MATCH_WINDOW = timedelta(hours=48)
PUBLISH_LOOKBACK = timedelta(days=7)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: Any) -> Optional[datetime]:
    if not value:
        return None
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _active(definition: Optional[Dict[str, Any]]) -> bool:
    return bool(definition and definition.get("automation_enabled") and definition["owner"] == "dados")


async def _brand(client_id: str) -> str:
    from .studio_approvals import _client_name
    return await _client_name(client_id)


# ---------------------------------------------------------------- lembrete de aprovação


async def approval_reminders(*, now: Optional[datetime] = None) -> Dict[str, int]:
    """Pedidos abertos com conteúdo sem resposta: lembra no máximo uma vez a cada lead_minutes (padrão 48h)."""
    from .studio_messages import _approval_params

    now = now or _now()
    definition = (await automations.load_definitions()).get("lembrete_aprovacao")
    if not _active(definition):
        return {"skipped": 1}
    interval = timedelta(minutes=int(definition.get("lead_minutes") or 2880))
    requests = await sb_select("studio_approval_requests", select="id,client_id,status,expires_at,created_at,last_reminded_at",
                               filters={"status": "eq.aberto", "expires_at": f"gt.{now.isoformat()}"}, limit=500)
    counts = {"requests": 0, "queued": 0, "nothing_pending": 0, "errors": 0}
    for request in requests:
        last = _parse(request.get("last_reminded_at")) or _parse(request.get("created_at"))
        if last and now - last < interval:
            continue
        counts["requests"] += 1
        client_id = request["client_id"]
        brand = await _brand(client_id)
        queued = 0
        for contact in await automations.client_contacts(client_id, "conteudo"):
            try:
                params, extra = await _approval_params(client_id, "lembrete", request["id"], contact, brand)
            except StudioError as exc:
                counts["nothing_pending" if exc.code == "NOTHING_PENDING" else "errors"] += 1
                break
            row = await automations.enqueue(definition, client_id=client_id, recipient=contact, params=params,
                                            source_type="approval_request", source_id=request["id"],
                                            button_suffix="enc:" + encrypt_secret(extra["button_suffix"]),
                                            key_parts=(now.astimezone(SAO_PAULO).date().isoformat(),))
            queued += 1 if row else 0
        if queued:
            await sb_update("studio_approval_requests", filters={"id": f"eq.{request['id']}", "client_id": f"eq.{client_id}"},
                            patch={"last_reminded_at": now.isoformat()}, returning="minimal")
        counts["queued"] += queued
    return counts


# ---------------------------------------------------------------- conteúdo publicado (confirmado)


async def confirm_publications(*, now: Optional[datetime] = None) -> Dict[str, int]:
    """Só avisa quando o post existe de verdade no Instagram da empresa (ig_media perto do horário agendado)."""
    now = now or _now()
    definition = (await automations.load_definitions()).get("conteudo_publicado")
    if not _active(definition):
        return {"skipped": 1}
    items = await sb_select(ITEMS_TABLE, select="id,client_id,title,scheduled_at,status,published_at",
                            filters={"status": "eq.publicado", "published_at": f"gte.{(now - PUBLISH_LOOKBACK).isoformat()}"}, limit=500)
    counts = {"items": len(items), "confirmed": 0, "unconfirmed": 0, "queued": 0}
    for item in items:
        client_id = item["client_id"]
        scheduled = _parse(item.get("scheduled_at"))
        if not scheduled:
            counts["unconfirmed"] += 1
            continue
        media = await sb_select("ig_media", select="client_id,permalink,timestamp", order="timestamp.asc", limit=5, filters={
            "client_id": f"eq.{client_id}", "timestamp": f"gte.{(scheduled - PUBLISH_MATCH_WINDOW).isoformat()}",
            "and": f"(timestamp.lte.{(scheduled + PUBLISH_MATCH_WINDOW).isoformat()})", "permalink": "not.is.null"})
        media = [m for m in media if m.get("client_id") == client_id and m.get("permalink")]
        if not media:
            counts["unconfirmed"] += 1
            continue
        counts["confirmed"] += 1
        best = min(media, key=lambda m: abs((_parse(m["timestamp"]) - scheduled).total_seconds()))
        brand = await _brand(client_id)
        for contact in await automations.client_contacts(client_id, "conteudo"):
            row = await automations.enqueue(definition, client_id=client_id, recipient=contact, source_type="calendar_item",
                                            source_id=item["id"], key_parts=("publicado",),
                                            params={"nome": str(contact["name"]).split()[0], "marca": brand,
                                                    "titulo": str(item.get("title") or "conteúdo")[:60], "link": best["permalink"]})
            counts["queued"] += 1 if row else 0
    return counts


# ---------------------------------------------------------------- ajuste concluído


async def on_item_status_change(client_id: str, before: Dict[str, Any], after: Dict[str, Any]) -> int:
    """Ajuste pedido PELO CLIENTE e devolvido pela equipe (rejeitado → em revisão/aprovado). Nunca levanta."""
    try:
        if before.get("status") != "rejeitado" or after.get("status") not in ("em_revisao", "aprovado"):
            return 0
        if not str(before.get("reviewed_by") or "").startswith("cliente:"):
            return 0
        definition = (await automations.load_definitions()).get("ajuste_concluido")
        if not _active(definition):
            return 0
        brand = await _brand(client_id)
        queued = 0
        stamp = str(before.get("reviewed_at") or "")
        for contact in await automations.client_contacts(client_id, "conteudo"):
            row = await automations.enqueue(definition, client_id=client_id, recipient=contact, source_type="calendar_item",
                                            source_id=str(after.get("id") or before.get("id")), key_parts=("ajuste", stamp),
                                            params={"nome": str(contact["name"]).split()[0], "marca": brand,
                                                    "titulo": str(after.get("title") or before.get("title") or "conteúdo")[:60]})
            queued += 1 if row else 0
        return queued
    except Exception as exc:  # noqa: BLE001 — aviso complementar; a edição do item vale sempre
        print(f"[automations] ajuste_concluido_falhou client_id={client_id} {type(exc).__name__}")
        return 0


# ---------------------------------------------------------------- eventos explícitos (relatório pronto, alerta de campanha)

EXPLICIT = {"relatorio_pronto", "alerta_campanha"}


async def emit(key: str, *, client_id: str, params: Dict[str, str], source_id: str) -> Dict[str, Any]:
    """Disparo pedido pela equipe/integração. Alerta de campanha vai SÓ para a equipe Mugô."""
    if key not in EXPLICIT:
        raise automations.AutomationError("NOT_EXPLICIT", "Esta automação tem gatilho próprio.")
    definition = (await automations.load_definitions()).get(key)
    if not _active(definition):
        raise automations.AutomationError("AUTOMATION_DISABLED")
    brand = await _brand(client_id)
    if definition["audience"] == "equipe":
        recipients: List[Dict[str, Any]] = [{**m, "team_member": True} for m in await automations.team_members("receives_campaign_alerts")]
        target_client = client_id  # contexto da empresa para o histórico; destinatário é da equipe
    else:
        recipients = await automations.client_contacts(client_id, (definition.get("recipients") or {}).get("receives"))
        target_client = client_id
    queued = 0
    for recipient in recipients:
        values = {**params, "nome": str(recipient["name"]).split()[0], "marca": brand}
        row = await automations.enqueue(definition, client_id=target_client, recipient=recipient, params=values,
                                        source_type=f"explicit_{key}", source_id=source_id)
        queued += 1 if row else 0
    return {"queued": queued, "recipients": len(recipients)}
