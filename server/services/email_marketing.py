"""E-mail marketing da marca: remetente, públicos, campanhas, fila de envio (Resend) e descadastro.

Regras:
- O destinatário nunca é gravado em claro: ``email_sends`` guarda o hash (o mesmo da jornada). O e-mail vem da base
  de clientes da loja na hora do envio.
- Quem se descadastrou, deu bounce ou marcou spam entra em ``email_suppressions`` e não recebe mais nada da marca.
- Público "Com consentimento" (padrão) = quem aceitou receber marketing na Shopify. A FBITS não informa
  consentimento: lá só existe o público geral, e a tela avisa.
- Fila idempotente: cada destinatário tem a chave ``campanha/<id>/<hash>``; rodar o job de novo nunca duplica.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import email_builder, email_resend
from .ig_supabase import _request, sb_delete, sb_insert, sb_select, sb_update, sb_upsert

SETTINGS = "email_settings"
SUPPRESSIONS = "email_suppressions"
CAMPAIGNS = "email_campaigns"
SENDS = "email_sends"
SEGMENTS = ("consentimento", "todos", "compraram", "sem_compra", "recompra")
SEND_PER_RUN = 1000
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,24}$", re.I)
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class EmailError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.message = message
        self.status = status


def _text(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: Any) -> Optional[datetime]:
    raw = _text(value, 40)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def valid_email(value: Any) -> Optional[str]:
    email = _text(value, 254).lower()
    return email if _EMAIL.match(email) else None


def email_hash(value: Any) -> Optional[str]:
    from .customer_journey import email_hash as journey_hash
    return journey_hash(value)


# ---------------------------------------------------------------- remetente

SETTING_FIELDS = ("from_name", "from_email", "reply_to", "brand_color", "logo_url", "footer_text", "store_url")


async def get_settings(client_id: str) -> Dict[str, Any]:
    rows = await sb_select(SETTINGS, select=",".join(SETTING_FIELDS) + ",updated_at", filters={"client_id": f"eq.{client_id}"}, limit=1)
    return rows[0] if rows else {field: None for field in SETTING_FIELDS}


def clean_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for field in SETTING_FIELDS:
        if field not in patch:
            continue
        value = _text(patch.get(field), 600) or None
        if value and field in ("from_email", "reply_to") and not valid_email(value):
            raise EmailError("INVALID_EMAIL", "Confira o e-mail do remetente e o de resposta.")
        if value and field == "brand_color" and not _COLOR.match(value):
            raise EmailError("INVALID_COLOR", "A cor precisa ser no formato #RRGGBB.")
        if value and field in ("logo_url", "store_url") and not value.lower().startswith("https://"):
            raise EmailError("INVALID_URL", "Os links precisam começar com https://.")
        out[field] = value.lower() if value and field in ("from_email", "reply_to") else value
    return out


async def save_settings(client_id: str, patch: Dict[str, Any], *, user_id: Optional[str]) -> Dict[str, Any]:
    row = {"client_id": client_id, **clean_settings(patch), "updated_by": user_id, "updated_at": _now().isoformat()}
    await sb_upsert(SETTINGS, [row], on_conflict="client_id")
    return await get_settings(client_id)


async def sender_status(client_id: str) -> Dict[str, Any]:
    """Diz se a marca já pode enviar: chave do Resend, remetente e domínio verificado."""
    settings = await get_settings(client_id)
    from_email = _text(settings.get("from_email"), 160)
    status: Dict[str, Any] = {"configured": email_resend.configured(), "send_enabled": email_resend.send_enabled(),
                              "from_email": from_email or None, "domain": email_resend.domain_of(from_email) if from_email else None,
                              "domain_status": None, "ready": False}
    if status["configured"] and from_email:
        try:
            domains = await email_resend.list_domains()
            match = next((d for d in domains if d.get("name") == status["domain"]), None)
            status["domain_status"] = (match or {}).get("status") or "nao_cadastrado"
        except email_resend.ResendError as exc:
            status["domain_status"] = "indisponivel"
            print(f"[email_marketing] domains_failed client_id={client_id} code={exc.code}")
    status["ready"] = bool(status["configured"] and from_email and status["domain_status"] == "verified")
    return status


def sender(settings: Dict[str, Any]) -> str:
    name = re.sub(r"[<>\"\r\n]", "", _text(settings.get("from_name"), 80))
    email = _text(settings.get("from_email"), 160)
    if not valid_email(email):
        raise EmailError("NO_SENDER", "Configure o e-mail do remetente da marca antes de enviar.")
    return f"{name} <{email}>" if name else email


# ---------------------------------------------------------------- descadastro

def _unsub_key() -> bytes:
    for name in ("EMAIL_UNSUBSCRIBE_SECRET", "TOKEN_ENCRYPTION_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        value = (os.getenv(name) or "").strip()
        if value:
            return hashlib.sha256(f"mugo-unsub:{value}".encode()).digest()
    raise RuntimeError("Sem segredo para o link de descadastro")


def unsubscribe_token(client_id: str, ehash: str) -> str:
    payload = f"{client_id}|{ehash}"
    sig = hmac.new(_unsub_key(), payload.encode(), hashlib.sha256).hexdigest()[:24]
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode().rstrip("=")


def parse_unsubscribe_token(token: str) -> Optional[Tuple[str, str]]:
    try:
        raw = base64.urlsafe_b64decode(_text(token, 400) + "=" * (-len(_text(token, 400)) % 4)).decode()
        client_id, ehash, sig = raw.split("|")
    except (ValueError, UnicodeDecodeError):
        return None
    expected = hmac.new(_unsub_key(), f"{client_id}|{ehash}".encode(), hashlib.sha256).hexdigest()[:24]
    return (client_id, ehash) if hmac.compare_digest(sig, expected) and len(ehash) == 32 else None


def unsubscribe_url(client_id: str, ehash: str) -> str:
    base = email_resend.public_api_url()
    return f"{base}/api/email/unsubscribe?t={unsubscribe_token(client_id, ehash)}" if base else ""


async def suppress(client_id: str, ehash: str, reason: str) -> None:
    await sb_upsert(SUPPRESSIONS, [{"client_id": client_id, "email_hash": ehash, "reason": reason, "at": _now().isoformat()}],
                    on_conflict="client_id,email_hash")


async def suppressed(client_id: str) -> set:
    from .sales_by_origin import _paged
    rows, _ = await _paged(SUPPRESSIONS, select="email_hash", filters={"client_id": f"eq.{client_id}"}, order="email_hash.asc")
    return {r["email_hash"] for r in rows}


# ---------------------------------------------------------------- públicos

async def load_contacts(client_id: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Clientes da loja com e-mail: {email, hash, first_name, name, consent, orders, last_order_at}."""
    from .commerce_context import FBITS, SHOPIFY, resolve_commerce_provider
    from .sales_by_origin import _paged
    provider = _text((await resolve_commerce_provider(client_id)).get("provider"), 20).lower()
    since = (_now() - timedelta(days=730)).isoformat()
    contacts: Dict[str, Dict[str, Any]] = {}
    if provider == SHOPIFY:
        people, _ = await _paged("shopify_customers", select=("shopify_customer_id,email,first_name,last_name,orders_count,"
                                                              "consent:raw_payload->email_marketing_consent->>state,"
                                                              "accepts:raw_payload->>accepts_marketing"),
                                 filters={"client_id": f"eq.{client_id}", "email": "not.is.null"}, order="shopify_customer_id.asc")
        orders, _ = await _paged("shopify_orders", select="customer_id,created_at_shopify,cancelled_at",
                                 filters={"client_id": f"eq.{client_id}", "created_at_shopify": f"gte.{since}"}, order="created_at_shopify.asc")
        by_customer: Dict[str, List[str]] = {}
        for o in orders:
            if _text(o.get("customer_id")) and not o.get("cancelled_at"):
                by_customer.setdefault(_text(o["customer_id"]), []).append(o["created_at_shopify"])
        for p in people:
            email = valid_email(p.get("email"))
            if not email:
                continue
            dates = by_customer.get(_text(p.get("shopify_customer_id")), [])
            consent = _text(p.get("consent"), 30).lower() == "subscribed" or _text(p.get("accepts"), 10).lower() == "true"
            _merge(contacts, email, first=_text(p.get("first_name"), 80), name=f"{_text(p.get('first_name'), 80)} {_text(p.get('last_name'), 80)}".strip(),
                   consent=consent, orders=max(int(p.get("orders_count") or 0), len(dates)), last=max(dates) if dates else None)
    elif provider == FBITS:
        people, _ = await _paged("fbits_customers", select="fbits_customer_id,name,email",
                                 filters={"client_id": f"eq.{client_id}", "email": "not.is.null"}, order="fbits_customer_id.asc")
        orders, _ = await _paged("fbits_orders", select="customer_id,order_date,is_valid",
                                 filters={"client_id": f"eq.{client_id}", "order_date": f"gte.{since}"}, order="order_date.asc")
        by_customer = {}
        for o in orders:
            if _text(o.get("customer_id")) and o.get("is_valid") is not False:
                by_customer.setdefault(_text(o["customer_id"]), []).append(o["order_date"])
        for p in people:
            email = valid_email(p.get("email"))
            if not email:
                continue
            dates = by_customer.get(_text(p.get("fbits_customer_id")), [])
            name = _text(p.get("name"), 160)
            _merge(contacts, email, first=name.split(" ")[0] if name else "", name=name, consent=None,
                   orders=len(dates), last=max(dates) if dates else None)
    return provider, list(contacts.values())


def _merge(contacts: Dict[str, Dict[str, Any]], email: str, *, first: str, name: str, consent: Optional[bool],
           orders: int, last: Optional[str]) -> None:
    ehash = email_hash(email)
    if not ehash:
        return
    current = contacts.get(ehash)
    if current is None:
        contacts[ehash] = {"email": email, "hash": ehash, "first_name": first, "name": name, "consent": consent,
                           "orders": orders, "last_order_at": last}
        return
    current["consent"] = bool(current["consent"]) or bool(consent) if consent is not None else current["consent"]
    current["orders"] += orders
    if last and (not current["last_order_at"] or last > current["last_order_at"]):
        current["last_order_at"] = last
    current["first_name"] = current["first_name"] or first


def clean_audience(audience: Any) -> Dict[str, Any]:
    raw = audience if isinstance(audience, dict) else {}
    segment = raw.get("segment") if raw.get("segment") in SEGMENTS else "consentimento"
    try:
        days = max(1, min(int(raw.get("days") or 90), 730))
    except (TypeError, ValueError):
        days = 90
    only_consent = segment == "consentimento" or bool(raw.get("only_consent", segment != "todos"))
    return {"segment": segment, "days": days, "only_consent": only_consent}


def select_audience(contacts: Iterable[Dict[str, Any]], audience: Dict[str, Any], *, blocked: set,
                    now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Função pura: quem recebe. Bloqueados (descadastro/bounce/spam) nunca entram."""
    audience = clean_audience(audience)
    now = now or _now()
    cutoff = now - timedelta(days=audience["days"])
    out = []
    for c in contacts:
        if c["hash"] in blocked:
            continue
        if audience["only_consent"] and c.get("consent") is not True:
            continue
        last = _dt(c.get("last_order_at"))
        segment = audience["segment"]
        if segment == "compraram" and not (last and last >= cutoff):
            continue
        if segment == "sem_compra" and not (last and last < cutoff):
            continue
        if segment == "recompra" and int(c.get("orders") or 0) < 2:
            continue
        out.append(c)
    return out


async def audience_preview(client_id: str, audience: Any) -> Dict[str, Any]:
    provider, contacts = await load_contacts(client_id)
    blocked = await suppressed(client_id)
    chosen = select_audience(contacts, audience, blocked=blocked)
    return {"provider": provider or None, "count": len(chosen), "base": len(contacts),
            "with_consent": sum(1 for c in contacts if c.get("consent") is True), "blocked": len(blocked),
            "consent_known": provider != "fbits", "audience": clean_audience(audience)}


# ---------------------------------------------------------------- campanhas

CAMPAIGN_FIELDS = "id,name,subject,preheader,design,custom_html,audience,status,scheduled_at,started_at,finished_at,stats,created_at,updated_at"
EDITABLE = ("rascunho", "agendada")


async def list_campaigns(client_id: str) -> List[Dict[str, Any]]:
    return await sb_select(CAMPAIGNS, select="id,name,subject,status,scheduled_at,started_at,finished_at,stats,created_at,updated_at",
                           filters={"client_id": f"eq.{client_id}"}, order="created_at.desc", limit=100)


async def get_campaign(client_id: str, campaign_id: str) -> Dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f-]{36}", _text(campaign_id, 40)):
        raise EmailError("NOT_FOUND", "Campanha não encontrada.", 404)
    rows = await sb_select(CAMPAIGNS, select=CAMPAIGN_FIELDS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{campaign_id}"}, limit=1)
    if not rows:
        raise EmailError("NOT_FOUND", "Campanha não encontrada.", 404)
    return rows[0]


def clean_campaign(body: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if "name" in body:
        out["name"] = _text(body.get("name"), 120) or "Campanha sem nome"
    for field in ("subject", "preheader"):
        if field in body:
            out[field] = _text(body.get(field), 200)
    if "design" in body:
        out["design"] = email_builder.normalize_design(body.get("design"))
    if "custom_html" in body:
        out["custom_html"] = (str(body.get("custom_html") or "")[:300000]) or None
    if "audience" in body:
        out["audience"] = clean_audience(body.get("audience"))
    return out


async def save_campaign(client_id: str, body: Dict[str, Any], *, user_id: Optional[str], campaign_id: Optional[str] = None) -> Dict[str, Any]:
    patch = clean_campaign(body)
    stamp = _now().isoformat()
    if campaign_id:
        current = await get_campaign(client_id, campaign_id)
        if current["status"] not in EDITABLE:
            raise EmailError("LOCKED", "Esta campanha já foi enviada e não pode mais ser editada.", 409)
        await sb_update(CAMPAIGNS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{campaign_id}"},
                        patch={**patch, "updated_at": stamp}, returning="minimal")
        return await get_campaign(client_id, campaign_id)
    row = {"client_id": client_id, "name": "Nova campanha", "design": email_builder.default_campaign_design(),
           "audience": clean_audience({}), **patch, "created_by": user_id, "created_at": stamp, "updated_at": stamp}
    created = await sb_insert(CAMPAIGNS, row)
    return await get_campaign(client_id, created["id"])


async def delete_campaign(client_id: str, campaign_id: str) -> None:
    current = await get_campaign(client_id, campaign_id)
    if current["status"] != "rascunho":
        raise EmailError("LOCKED", "Só rascunho pode ser apagado.", 409)
    await sb_delete(CAMPAIGNS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{campaign_id}"}, returning="minimal")


def _variables(contact: Dict[str, Any], settings: Dict[str, Any], client_id: str) -> Dict[str, str]:
    first = _text(contact.get("first_name"), 80) or "Olá"
    return {"nome": _text(contact.get("name"), 160) or first, "primeiro_nome": first,
            "marca": _text(settings.get("from_name"), 80), "link_loja": _text(settings.get("store_url"), 300),
            "descadastro": unsubscribe_url(client_id, contact["hash"]) if contact.get("hash") else ""}


def render_campaign(campaign: Dict[str, Any], settings: Dict[str, Any], contact: Dict[str, Any], client_id: str) -> Tuple[str, str, str]:
    variables = _variables(contact, settings, client_id)
    html, text = email_builder.render(campaign.get("design"), settings, variables, preheader=campaign.get("preheader") or "",
                                      custom_html=campaign.get("custom_html"))
    subject = email_builder.fill(_text(campaign.get("subject"), 200), variables) or _text(campaign.get("name"), 120)
    return subject, html, text


SAMPLE = {"email": "cliente@exemplo.com", "hash": "0" * 32, "first_name": "Ana", "name": "Ana Ribeiro"}


async def preview(client_id: str, campaign: Dict[str, Any]) -> Dict[str, Any]:
    settings = await get_settings(client_id)
    subject, html, _ = render_campaign(clean_campaign(campaign) | {"preheader": campaign.get("preheader")}, settings, SAMPLE, client_id)
    return {"subject": subject, "html": html}


def _message(settings: Dict[str, Any], to: str, subject: str, html: str, text: str, unsub: str, tags: List[Dict[str, str]]) -> Dict[str, Any]:
    msg: Dict[str, Any] = {"from": sender(settings), "to": [to], "subject": subject[:200] or "(sem assunto)", "html": html, "text": text,
                           "tags": tags}
    if settings.get("reply_to"):
        msg["reply_to"] = settings["reply_to"]
    if unsub:
        msg["headers"] = {"List-Unsubscribe": f"<{unsub}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    return msg


async def send_test(client_id: str, campaign: Dict[str, Any], to: str) -> Dict[str, Any]:
    email = valid_email(to)
    if not email:
        raise EmailError("INVALID_EMAIL", "Informe um e-mail válido para o teste.")
    settings = await get_settings(client_id)
    contact = {**SAMPLE, "email": email, "hash": email_hash(email)}
    subject, html, text = render_campaign(clean_campaign(campaign) | {"preheader": campaign.get("preheader")}, settings, contact, client_id)
    msg = _message(settings, email, f"[TESTE] {subject}", html, text, "", [{"name": "kind", "value": "teste"}])
    ids = await email_resend.send_batch([msg])
    await _insert_ignore([{"client_id": client_id, "kind": "teste", "email_hash": contact["hash"],
                           "idem_key": f"teste/{_now().timestamp()}/{contact['hash']}", "resend_id": ids[0],
                           "status": "enviado" if ids[0] else "simulado"}])
    return {"status": "enviado" if ids[0] else "simulado"}


async def schedule(client_id: str, campaign_id: str, when: Optional[str]) -> Dict[str, Any]:
    campaign = await get_campaign(client_id, campaign_id)
    if campaign["status"] not in EDITABLE:
        raise EmailError("LOCKED", "Esta campanha já foi enviada.", 409)
    if not _text(campaign.get("subject")):
        raise EmailError("NO_SUBJECT", "Escreva o assunto antes de enviar.")
    sender(await get_settings(client_id))
    at = _dt(when) if when else _now()
    if not at:
        raise EmailError("INVALID_DATE", "Data de envio inválida.")
    await sb_update(CAMPAIGNS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{campaign_id}"},
                    patch={"status": "agendada", "scheduled_at": at.isoformat(), "updated_at": _now().isoformat()}, returning="minimal")
    return await get_campaign(client_id, campaign_id)


async def cancel(client_id: str, campaign_id: str) -> Dict[str, Any]:
    campaign = await get_campaign(client_id, campaign_id)
    if campaign["status"] not in ("agendada", "enviando"):
        raise EmailError("LOCKED", "Só dá para cancelar campanha agendada ou em envio.", 409)
    await sb_update(CAMPAIGNS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{campaign_id}"},
                    patch={"status": "cancelada" if campaign["status"] == "agendada" else "enviada",
                           "finished_at": _now().isoformat(), "updated_at": _now().isoformat()}, returning="minimal")
    if campaign["status"] == "enviando":
        await sb_delete(SENDS, filters={"campaign_id": f"eq.{campaign_id}", "status": "eq.na_fila"}, returning="minimal")
    return await get_campaign(client_id, campaign_id)


async def _insert_ignore(rows: List[Dict[str, Any]]) -> None:
    for offset in range(0, len(rows), 500):
        await _request("POST", f"/{SENDS}", params={"on_conflict": "client_id,idem_key"}, json=rows[offset:offset + 500],
                       headers={"Prefer": "resolution=ignore-duplicates,return=minimal"})


async def campaign_stats(client_id: str, campaign_id: str) -> Dict[str, Any]:
    from .sales_by_origin import _paged
    rows, _ = await _paged(SENDS, select="id,status,opened_at,clicked_at",
                           filters={"client_id": f"eq.{client_id}", "campaign_id": f"eq.{campaign_id}"}, order="id.asc")
    return summarize_sends(rows)


def summarize_sends(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    sent = sum(counts.get(k, 0) for k in ("enviado", "entregue", "bounce", "spam", "simulado"))
    delivered = counts.get("entregue", 0)
    opened = sum(1 for r in rows if r.get("opened_at"))
    clicked = sum(1 for r in rows if r.get("clicked_at"))
    base = delivered or sent
    return {"total": len(rows), "queued": counts.get("na_fila", 0), "sent": sent, "delivered": delivered,
            "bounced": counts.get("bounce", 0), "spam": counts.get("spam", 0), "failed": counts.get("falhou", 0),
            "simulated": counts.get("simulado", 0), "opened": opened, "clicked": clicked,
            "open_rate": round(opened / base * 100, 1) if base else None, "click_rate": round(clicked / base * 100, 1) if base else None}


async def _process_campaign(campaign: Dict[str, Any], client_id: str) -> Dict[str, Any]:
    cid, campaign_id = client_id, campaign["id"]
    settings = await get_settings(cid)
    _, contacts = await load_contacts(cid)
    by_hash = {c["hash"]: c for c in contacts}
    if campaign["status"] == "agendada":
        chosen = select_audience(contacts, campaign.get("audience") or {}, blocked=await suppressed(cid))
        await _insert_ignore([{"client_id": cid, "kind": "campanha", "campaign_id": campaign_id, "email_hash": c["hash"],
                               "idem_key": f"campanha/{campaign_id}/{c['hash']}"} for c in chosen])
        await sb_update(CAMPAIGNS, filters={"id": f"eq.{campaign_id}"}, returning="minimal",
                        patch={"status": "enviando", "started_at": _now().isoformat(), "stats": {"audience": len(chosen)}})
    pending = await sb_select(SENDS, select="id,client_id,kind,campaign_id,email_hash,idem_key",
                              filters={"campaign_id": f"eq.{campaign_id}", "status": "eq.na_fila"}, order="id.asc", limit=SEND_PER_RUN)
    blocked = await suppressed(cid)
    sent = 0
    for offset in range(0, len(pending), email_resend.BATCH_MAX):
        chunk = pending[offset:offset + email_resend.BATCH_MAX]
        messages, rows, skipped = [], [], []
        for row in chunk:
            contact = by_hash.get(row["email_hash"])
            if not contact or row["email_hash"] in blocked:
                skipped.append({**row, "status": "bloqueado", "error": "fora da base ou descadastrado", "updated_at": _now().isoformat()})
                continue
            subject, html, text = render_campaign(campaign, settings, contact, cid)
            unsub = unsubscribe_url(cid, contact["hash"])
            messages.append(_message(settings, contact["email"], subject, html, text, unsub,
                                     [{"name": "kind", "value": "campanha"}, {"name": "campaign", "value": campaign_id}]))
            rows.append(row)
        try:
            ids = await email_resend.send_batch(messages, idem=f"campanha/{campaign_id}/{rows[0]['id']}" if rows else None)
        except email_resend.ResendError as exc:
            if exc.retryable:
                print(f"[email_marketing] batch_retry campaign={campaign_id} code={exc.code}")
                break
            ids = None
            for row in rows:
                skipped.append({**row, "status": "falhou", "error": exc.code, "updated_at": _now().isoformat()})
            rows = []
        stamp = _now().isoformat()
        done = [{**row, "status": "enviado" if rid else "simulado", "resend_id": rid, "updated_at": stamp}
                for row, rid in zip(rows, ids or [])]
        if done or skipped:
            await sb_upsert(SENDS, done + skipped, on_conflict="id")
        sent += len(done)
    remaining = await sb_select(SENDS, select="id", filters={"campaign_id": f"eq.{campaign_id}", "status": "eq.na_fila"}, limit=1)
    if not remaining:
        stats = await campaign_stats(cid, campaign_id)
        await sb_update(CAMPAIGNS, filters={"id": f"eq.{campaign_id}"}, returning="minimal",
                        patch={"status": "enviada", "finished_at": _now().isoformat(), "stats": stats})
    return {"sent": sent}


async def process_due() -> Dict[str, Any]:
    """Cron: campanhas agendadas que venceram e campanhas em envio. Uma falha não para as outras."""
    rows = await sb_select(CAMPAIGNS, select=CAMPAIGN_FIELDS + ",client_id",
                           filters={"status": "in.(agendada,enviando)", "scheduled_at": f"lte.{_now().isoformat()}"},
                           order="scheduled_at.asc", limit=20)
    total = {"campaigns": 0, "sent": 0, "errors": 0}
    for campaign in rows:
        try:
            result = await _process_campaign(campaign, campaign["client_id"])
            total["campaigns"] += 1
            total["sent"] += result["sent"]
        except Exception as exc:  # noqa: BLE001
            total["errors"] += 1
            print(f"[email_marketing] campaign_failed id={campaign['id']} {type(exc).__name__}")
    return total


# ---------------------------------------------------------------- webhook do Resend

EVENT_STATUS = {"email.delivered": "entregue", "email.bounced": "bounce", "email.complained": "spam"}


async def handle_event(event: Dict[str, Any]) -> Dict[str, Any]:
    kind = _text(event.get("type"), 40)
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    resend_id = _text(data.get("email_id"), 80)
    if not resend_id:
        return {"ignored": True}
    rows = await sb_select(SENDS, select="id,client_id,email_hash,status,opened_at,clicked_at", filters={"resend_id": f"eq.{resend_id}"}, limit=1)
    if not rows:
        return {"ignored": True}
    row = rows[0]
    stamp = _text(event.get("created_at"), 40) or _now().isoformat()
    patch: Dict[str, Any] = {"updated_at": _now().isoformat()}
    if kind in EVENT_STATUS and not (kind == "email.delivered" and row["status"] in ("bounce", "spam")):
        patch["status"] = EVENT_STATUS[kind]
    if kind == "email.opened" and not row.get("opened_at"):
        patch["opened_at"] = stamp
    if kind == "email.clicked":
        patch.setdefault("opened_at", row.get("opened_at") or stamp)
        if not row.get("clicked_at"):
            patch["clicked_at"] = stamp
    await sb_update(SENDS, filters={"id": f"eq.{row['id']}"}, patch=patch, returning="minimal")
    if kind in ("email.bounced", "email.complained"):
        bounce = (data.get("bounce") or {}) if isinstance(data.get("bounce"), dict) else {}
        if kind == "email.complained" or _text(bounce.get("type"), 20).lower() != "transient":
            await suppress(row["client_id"], row["email_hash"], "spam" if kind == "email.complained" else "bounce")
    return {"updated": True, "status": patch.get("status")}
