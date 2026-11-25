"""Disparo em massa de WhatsApp: envia um template aprovado pela Meta para a base da origem escolhida.

Decisão da agência (20/11/2026): vai para TODOS os contatos com telefone da origem, não só para quem tem aceite
registrado. A tela avisa o risco ao número (qualidade/bloqueio pela Meta) antes de enviar. Mesmo assim:
- quem respondeu SAIR/PARAR/STOP no WhatsApp da marca nunca recebe;
- o mesmo telefone recebe uma vez por campanha (retomar continua de onde parou, sem reenviar);
- só templates com até 1 variável ({{1}} = primeiro nome, ou "cliente"); modelo com imagem/vídeo no topo usa o
  arquivo enviado na campanha.
O envio NÃO roda no Render: "Enviar" e "Agendar" põem a campanha na fila e o Relógio dos jobs (GitHub Actions, de 5
em 5 minutos) envia até o fim, mesmo com o Render dormindo. Telefone nunca aparece na tela nem no log: só hashes.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from .crypto import decrypt_secret
from .ig_supabase import sb_insert, sb_select, sb_update
from .whatsapp_insights import phone_key

DRAFTS = "whatsapp_campaign_drafts"
SENDS = "whatsapp_campaign_sends"
PAGE = 1000
MAX_RECIPIENTS = 50000
CONCURRENCY = 4
SAVE_EVERY = 25
STALE_AFTER = timedelta(minutes=20)  # "enviando" sem progresso há mais que isso pode ser retomado
OPT_OUT = ("sair", "parar", "pare", "stop", "cancelar", "descadastrar", "remover")
HEADER_KINDS = {"IMAGE": "image", "VIDEO": "video", "DOCUMENT": "document"}


class BulkSendError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message = message
        self.status = status


def normalize_phone(value: Any) -> Optional[str]:
    """Só dígitos, com 55 quando o número é brasileiro sem DDI. Inválido devolve None."""
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) in (10, 11) and not str(value or "").lstrip().startswith("+"):
        digits = "55" + digits
    return digits if 12 <= len(digits) <= 15 else None


def phone_hash(client_id: str, digits: str) -> str:
    return hashlib.sha256(f"{client_id}:wa-bulk:{digits}".encode()).hexdigest()


def _plain(value: Any) -> str:
    if not value:
        return ""
    try:
        return decrypt_secret(str(value))
    except RuntimeError:
        return ""


def first_name(name: Any) -> str:
    text = re.sub(r"\s+", " ", str(name or "")).strip()
    word = text.split(" ")[0] if text else ""
    return word[:40].capitalize() if word and not any(ch.isdigit() for ch in word) else "cliente"


async def _pages(table: str, select: str, filters: Dict[str, str], order: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for offset in range(0, MAX_RECIPIENTS, PAGE):
        chunk = await sb_select(table, select=select, filters=filters, order=order, limit=PAGE, offset=offset)
        rows.extend(chunk)
        if len(chunk) < PAGE:
            break
    return rows


async def recipients(client_id: str, provider: str, selection: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """Telefones (sem repetir) da origem escolhida, com o nome quando houver.
    ``selection`` (só na planilha): os contatos escolhidos à mão, por identity_hash; vazio = todos."""
    out: Dict[str, Dict[str, str]] = {}

    def add(phone: Any, name: Any) -> None:
        digits = normalize_phone(phone)
        if not digits:
            return
        key = phone_key(digits, international=True)
        candidate = {"phone": digits, "name": first_name(name)}
        previous = out.setdefault(key, candidate)
        if len(digits) > len(previous["phone"]):
            previous["phone"] = digits
        if previous["name"] == "cliente":
            previous["name"] = candidate["name"]

    picked = [h for h in (selection or []) if re.fullmatch(r"[0-9a-f]{64}", str(h))] if provider == "planilha" else []
    if picked:
        for start in range(0, len(picked), 100):
            rows = await sb_select("relationship_contacts", select="phone_ciphertext,name_ciphertext", limit=100, filters={
                "client_id": f"eq.{client_id}", "provider": "eq.planilha", "identity_hash": f"in.({','.join(picked[start:start + 100])})"})
            for r in rows:
                add(_plain(r.get("phone_ciphertext")), _plain(r.get("name_ciphertext")))
        return list(out.values())[:MAX_RECIPIENTS]
    if provider in ("all", "shopify", "fbits", "planilha"):
        filters = {"client_id": f"eq.{client_id}", "phone_ciphertext": "not.is.null"}
        if provider != "all":
            filters["provider"] = f"eq.{provider}"
        for r in await _pages("relationship_contacts", "provider,phone_ciphertext,name_ciphertext", filters, "identity_hash.asc"):
            add(_plain(r.get("phone_ciphertext")), _plain(r.get("name_ciphertext")))
    if provider in ("all", "whatsapp"):
        for r in await _pages("whatsapp_threads", "wa_id,profile_name", {"client_id": f"eq.{client_id}"}, "first_seen_at.asc"):
            add(r.get("wa_id"), r.get("profile_name"))
    if provider in ("all", "capture"):
        for r in await _pages("lead_capture_events", "phone_ciphertext",
                              {"client_id": f"eq.{client_id}", "phone_ciphertext": "not.is.null"}, "id.asc"):
            add(_plain(r.get("phone_ciphertext")), None)
    return list(out.values())[:MAX_RECIPIENTS]


async def opted_out(client_id: str) -> Set[str]:
    """Telefones que pediram para sair (responderam SAIR, PARAR, STOP… no WhatsApp da marca)."""
    words = ",".join(f"text.ilike.{w}" for w in OPT_OUT)
    msgs = await _pages("whatsapp_messages", "thread_id",
                        {"client_id": f"eq.{client_id}", "direction": "eq.in", "or": f"({words})"}, "sent_at.desc")
    thread_ids = sorted({str(m["thread_id"]) for m in msgs if m.get("thread_id")})
    phones: Set[str] = set()
    for start in range(0, len(thread_ids), 100):
        rows = await sb_select("whatsapp_threads", select="wa_id", limit=100,
                               filters={"client_id": f"eq.{client_id}", "id": f"in.({','.join(thread_ids[start:start + 100])})"})
        phones.update(d for r in rows if (d := normalize_phone(r.get("wa_id"))))
    return phones


async def count_sendable(client_id: str, provider: str) -> Dict[str, int]:
    people = await recipients(client_id, provider)
    blocked = await opted_out(client_id)
    blocked_keys = {phone_key(p, international=True) for p in blocked}
    return {"sendable_count": sum(1 for p in people if phone_key(p["phone"], international=True) not in blocked_keys), "opted_out_count": len(blocked)}


async def _draft(client_id: str, draft_id: str) -> Dict[str, Any]:
    rows = await sb_select(DRAFTS, select="*", limit=1, filters={"client_id": f"eq.{client_id}", "id": f"eq.{draft_id}"})
    if not rows:
        raise BulkSendError("Campanha não encontrada.", 404)
    return rows[0]


async def _template_variables(client_id: str, name: str, language: str) -> int:
    from .whatsapp_native import list_templates
    templates = await list_templates(client_id)
    match = next((t for t in templates if t.get("name") == name and t.get("language") == language), None)
    if not match or str(match.get("status") or "").upper() != "APPROVED":
        raise BulkSendError("O modelo desta campanha não está aprovado na Meta. Escolha outro modelo.")
    return int(match.get("variables") or 0)


async def _template(client_id: str, name: str, language: str) -> Dict[str, Any]:
    from .whatsapp_native import list_templates
    templates = await list_templates(client_id)
    match = next((t for t in templates if t.get("name") == name and t.get("language") == language), None)
    if not match or str(match.get("status") or "").upper() != "APPROVED":
        raise BulkSendError("O modelo desta campanha não está aprovado na Meta. Escolha outro modelo.")
    return match


def _check_template(template: Dict[str, Any], header_media_url: Optional[str]) -> None:
    if int(template.get("variables") or 0) > 1:
        raise BulkSendError("O disparo em massa aceita modelos com até 1 variável ({{1}} vira o primeiro nome). "
                            "Crie um modelo mais simples na aba Modelos.")
    if int(template.get("header_variables") or 0) > 0:
        raise BulkSendError("Este modelo tem variável no título. Use um modelo com título fixo.")
    if template.get("header") in HEADER_KINDS and not header_media_url:
        raise BulkSendError("Este modelo tem imagem (ou vídeo) no topo. Envie o arquivo na campanha antes de disparar.")


def _iso(value: Any) -> Optional[datetime]:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


async def start(client_id: str, draft_id: str, scheduled_at: Optional[str] = None,
                exclude_previous_template_recipients: bool = True) -> Dict[str, Any]:
    """Põe a campanha na fila (agora ou na data agendada). Quem envia é o job ``whatsapp-bulk-due``."""
    from .whatsapp_native import _active_number, WhatsAppNativeError
    draft = await _draft(client_id, draft_id)
    status = draft.get("status") or "draft"
    if status == "sent":
        raise BulkSendError("Esta campanha já foi enviada para todos.")
    if status == "sending":
        started = _iso(draft.get("started_at"))
        if started and datetime.now(timezone.utc) - started < STALE_AFTER:
            raise BulkSendError("Esta campanha já está sendo enviada. Aguarde.", 409)
    when = _iso(scheduled_at) if scheduled_at else None
    if scheduled_at and not when:
        raise BulkSendError("Data de agendamento inválida.")
    if when and when < datetime.now(timezone.utc) - timedelta(minutes=5):
        raise BulkSendError("Escolha uma data no futuro para agendar.")
    if when and when > datetime.now(timezone.utc) + timedelta(days=60):
        raise BulkSendError("Agende no máximo 60 dias à frente.")
    try:
        await _active_number(client_id, None)
    except WhatsAppNativeError:
        raise BulkSendError("Esta empresa não tem número de WhatsApp ativo no MUGOVERSO para disparar.", 409) from None
    _check_template(await _template(client_id, draft["template_name"], draft["language"]), draft.get("header_media_url"))
    people = await recipients(client_id, draft.get("audience_provider") or "all", draft.get("audience_selection"))
    if not people:
        raise BulkSendError("Nenhum contato com telefone nesta origem. Importe os contatos antes.")
    await sb_update(DRAFTS, filters={"id": f"eq.{draft_id}", "client_id": f"eq.{client_id}"}, returning="minimal",
                    patch={"status": "queued", "scheduled_at": when.isoformat() if when else None, "finished_at": None,
                           "recipients_count": len(people), "last_error": None,
                           "exclude_previous_template_recipients": exclude_previous_template_recipients})
    return {"status": "queued", "scheduled_at": when.isoformat() if when else None, "recipients_count": len(people)}


async def cancel(client_id: str, draft_id: str) -> Dict[str, Any]:
    """Tira da fila uma campanha agendada que ainda não começou."""
    rows = await sb_update(DRAFTS, filters={"id": f"eq.{draft_id}", "client_id": f"eq.{client_id}", "status": "eq.queued"},
                           patch={"status": "draft", "scheduled_at": None})
    if not rows:
        raise BulkSendError("Só dá para cancelar campanha que ainda está na fila.", 409)
    return {"status": "draft"}


async def process_due(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Job (Relógio dos jobs, de 5 em 5 min): envia as campanhas da fila cujo horário chegou e retoma as que pararam.
    Cada campanha é "pega" com uma troca de status condicionada (duas execuções não enviam a mesma)."""
    now = now or datetime.now(timezone.utc)
    queued = await sb_select(DRAFTS, select="*", limit=20, order="created_at.asc",
                             filters={"status": "eq.queued", "or": f"(scheduled_at.is.null,scheduled_at.lte.{now.isoformat()})"})
    stale = await sb_select(DRAFTS, select="*", limit=20, order="started_at.asc",
                            filters={"status": "eq.sending", "started_at": f"lt.{(now - STALE_AFTER).isoformat()}"})
    done: List[Dict[str, Any]] = []
    for draft in queued + stale:
        claim = {"id": f"eq.{draft['id']}", "status": f"eq.{draft['status']}"}
        if draft["status"] == "sending":
            claim["started_at"] = f"eq.{draft['started_at']}"
        claimed = await sb_update(DRAFTS, filters=claim, patch={"status": "sending", "started_at": now.isoformat()})
        if not claimed:
            continue  # outra execução pegou antes
        client_id = draft["client_id"]
        try:
            template = await _template(client_id, draft["template_name"], draft["language"])
            _check_template(template, draft.get("header_media_url"))
            people = await recipients(client_id, draft.get("audience_provider") or "all", draft.get("audience_selection"))
            header = ({"type": HEADER_KINDS[template["header"]], "link": draft["header_media_url"]}
                      if template.get("header") in HEADER_KINDS else None)
            counts = await run(client_id, {**draft, "started_at": now.isoformat(), "template_body": template.get("body")}, people, int(template.get("variables") or 0), header)
            done.append({"draft_id": draft["id"], **counts})
        except Exception as exc:  # noqa: BLE001 - uma campanha com problema não para as outras
            await sb_update(DRAFTS, filters={"id": f"eq.{draft['id']}"}, returning="minimal",
                            patch={"status": "failed" if not isinstance(exc, BulkSendError) else "draft",
                                   "last_error": (exc.message if isinstance(exc, BulkSendError) else f"Envio parou: {str(exc)[:200]}")[:300],
                                   "finished_at": datetime.now(timezone.utc).isoformat()})
            done.append({"draft_id": draft["id"], "error": type(exc).__name__})
    return {"campaigns": len(done), "results": done}


async def _previous_template_phones(client_id: str, draft: Dict[str, Any], keys: List[str]) -> Set[str]:
    """Somente envios aceitos em outras campanhas da mesma marca, modelo e idioma."""
    seen: Set[str] = set()
    for offset in range(0, len(keys), 100):
        batch = ",".join(keys[offset:offset + 100])
        rows = await _pages(SENDS, "phone_key,whatsapp_campaign_drafts!inner(id)", {
            "client_id": f"eq.{client_id}", "draft_id": f"neq.{draft['id']}", "status": "eq.sent",
            "phone_key": f"in.({batch})", "whatsapp_campaign_drafts.client_id": f"eq.{client_id}",
            "whatsapp_campaign_drafts.template_name": f"eq.{draft['template_name']}",
            "whatsapp_campaign_drafts.language": f"eq.{draft['language']}",
        }, "id.asc")
        seen.update(r["phone_key"] for r in rows if r.get("phone_key"))
    return seen


async def run(client_id: str, draft: Dict[str, Any], people: List[Dict[str, str]], variables: int,
              header: Optional[Dict[str, str]] = None) -> Dict[str, int]:
    from .whatsapp_native import WhatsAppNativeError, send_template
    draft_id = str(draft["id"])
    try:
        done_rows = await _pages(SENDS, "phone_hash,phone_key,status", {
            "draft_id": f"eq.{draft_id}", "client_id": f"eq.{client_id}",
        }, "created_at.asc,id.asc")
        done = {r["phone_hash"]: r["status"] for r in done_rows}
        completed_keys = {r["phone_key"] for r in done_rows if r.get("phone_key") and r["status"] in ("sent", "skipped")}
        unique_people = {}
        for person in people:
            digits = normalize_phone(person["phone"])
            key = phone_key(digits, international=True) if digits else None
            if key and key not in completed_keys:
                unique_people.setdefault(key, {**person, "phone": digits})
        previous = (await _previous_template_phones(client_id, draft, list(unique_people))
                    if draft.get("exclude_previous_template_recipients") else set())
        counts = {s: sum(1 for v in done.values() if v == s) for s in ("sent", "failed", "skipped")}
        blocked = {phone_key(p, international=True) for p in await opted_out(client_id)}
        last_error: Optional[str] = None
        gate = asyncio.Semaphore(CONCURRENCY)
        progress = 0

        async def save(final: bool = False) -> None:
            patch: Dict[str, Any] = {"sent_count": counts["sent"], "failed_count": counts["failed"],
                                     "skipped_count": counts["skipped"], "last_error": last_error}
            if final:
                patch["finished_at"] = datetime.now(timezone.utc).isoformat()
                patch["status"] = "sent" if counts["failed"] == 0 else "partial" if counts["sent"] else "failed"
            await sb_update(DRAFTS, filters={"id": f"eq.{draft_id}", "client_id": f"eq.{client_id}"}, patch=patch, returning="minimal")

        async def one(canonical_key: str, person: Dict[str, str]) -> None:
            async with gate:  # envio e registro juntos: no máximo CONCURRENCY por vez
                await deliver(canonical_key, person)

        async def deliver(canonical_key: str, person: Dict[str, str]) -> None:
            nonlocal last_error, progress
            key = phone_hash(client_id, person["phone"])
            if done.get(key) in ("sent", "skipped"):
                return
            row: Dict[str, Any] = {"client_id": client_id, "draft_id": draft_id, "phone_hash": key,
                                   "phone_key": canonical_key}
            if canonical_key in blocked:
                row["status"] = "skipped"; row["error"] = "Pediu para sair"
            elif canonical_key in previous:
                row["status"] = "skipped"; row["error"] = "Já recebeu este modelo"
            else:
                try:
                    receipt: Dict[str, str] = {}
                    row["provider_message_id"] = await send_template(
                        client_id, number_id=None, to=person["phone"], template=draft["template_name"],
                        language=draft["language"], params=[person["name"]] if variables == 1 else [], header_media=header, receipt=receipt)
                    if not row["provider_message_id"]:
                        raise WhatsAppNativeError("META", "A Meta não retornou o ID da mensagem.")
                    if receipt:
                        body = str(draft.get("template_body") or "")
                        if variables == 1:
                            body = re.sub(r"\{\{\s*[^}\s]+\s*\}\}", lambda _: person["name"], body)
                        row["inbox_message"] = {**receipt, "name": person["name"], "text": body,
                                                "sent_at": datetime.now(timezone.utc).isoformat()}
                    row["status"] = "sent"
                except WhatsAppNativeError as exc:
                    row["status"] = "failed"; row["error"] = str(exc.message)[:300]
                    last_error = row["error"]
                except Exception as exc:  # noqa: BLE001 - um número com problema não para a campanha
                    row["status"] = "failed"; row["error"] = str(exc)[:300] or "Erro ao enviar"
                    last_error = row["error"]
            if done.get(key) == "failed":
                await sb_update(SENDS, filters={"draft_id": f"eq.{draft_id}", "phone_hash": f"eq.{key}"},
                                patch={k: v for k, v in row.items() if k in ("status", "error", "provider_message_id", "phone_key", "inbox_message")}, returning="minimal")
                counts["failed"] -= 1
            else:
                await sb_insert(SENDS, row, returning="minimal")
            counts[row["status"]] += 1
            progress += 1
            if progress % SAVE_EVERY == 0:
                await save()

        targets = list(unique_people.items())
        for start_at in range(0, len(targets), 200):
            await asyncio.gather(*(one(key, person) for key, person in targets[start_at:start_at + 200]))
        await save(final=True)
        return counts
    except Exception as exc:  # noqa: BLE001
        await sb_update(DRAFTS, filters={"id": f"eq.{draft_id}", "client_id": f"eq.{client_id}"}, returning="minimal",
                        patch={"status": "partial", "last_error": f"Envio interrompido: {str(exc)[:200]}",
                               "finished_at": datetime.now(timezone.utc).isoformat()})
        raise


async def report(client_id: str, draft_id: str) -> Dict[str, Any]:
    """Depois do envio: quantos responderam no WhatsApp e quantos compraram na loja em até 7 dias (pelo telefone)."""
    draft = await _draft(client_id, draft_id)
    started = _iso(draft.get("started_at"))
    if not started or draft.get("status") in ("draft", "queued"):
        raise BulkSendError("A campanha ainda não foi enviada.", 409)
    sends = await _pages(SENDS, "phone_key,status", {"draft_id": f"eq.{draft_id}", "status": "eq.sent"}, "created_at.asc")
    keys = {r["phone_key"] for r in sends if r.get("phone_key")}
    replied = 0
    if keys:
        threads = await _pages("whatsapp_threads", "phone_key,last_inbound_at",
                               {"client_id": f"eq.{client_id}", "last_inbound_at": f"gte.{started.isoformat()}"}, "last_inbound_at.asc")
        replied = len({t["phone_key"] for t in threads if t.get("phone_key") in keys})
    buyers, revenue, orders_count, available = set(), 0.0, 0, True
    end = min(datetime.now(timezone.utc), started + timedelta(days=7))
    try:
        from .whatsapp_insights import _shopify_orders, order_phone_keys
        orders, _ = await _shopify_orders(client_id, started.isoformat(), end.isoformat())
        for order in orders:
            hit = keys.intersection(order_phone_keys(order))
            if hit:
                buyers.update(hit)
                orders_count += 1
                revenue += float(order.get("value") or 0)
    except Exception:  # noqa: BLE001 - marca sem Shopify: mostra só envios e respostas
        available = False
    sent = int(draft.get("sent_count") or len(sends))
    return {"sent": sent, "failed": int(draft.get("failed_count") or 0), "skipped": int(draft.get("skipped_count") or 0),
            "replied": replied, "reply_rate": round(replied / sent * 100, 1) if sent else 0.0,
            "buyers": len(buyers), "orders": orders_count, "revenue": round(revenue, 2), "sales_available": available,
            "window": f"{started.date().isoformat()} a {end.date().isoformat()}", "matched_by": "telefone"}
