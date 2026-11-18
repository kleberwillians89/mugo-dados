"""Captura multitenant de leads de formulários externos (somente ingestão).

A chave da fonte é mostrada uma única vez. Eventos não ativam campanhas nem
comprovam opt-in: a declaração recebida fica pendente de validação da origem.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from .crypto import encrypt_secret
from .email_marketing import valid_email
from .ig_supabase import sb_insert, sb_select, sb_update

SOURCE_TABLE = "lead_capture_sources"
EVENT_TABLE = "lead_capture_events"
_EMAIL_MAX = 254
_PHONE = re.compile(r"^\+?[0-9]{8,15}$")


class LeadCaptureError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status
        self.message = message


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _phone(raw: Any) -> str | None:
    value = re.sub(r"[^0-9+]", "", str(raw or ""))
    if not value:
        return None
    if not _PHONE.fullmatch(value):
        raise LeadCaptureError("Telefone inválido.", 422)
    return value


async def list_sources(client_id: str) -> list[dict]:
    return await sb_select(
        SOURCE_TABLE,
        select="id,name,kind,active,created_at,last_received_at",
        filters={"client_id": f"eq.{client_id}"},
        order="created_at.desc",
        limit=200,
    )


async def create_source(client_id: str, name: Any, kind: Any) -> dict:
    name = " ".join(str(name or "").split())[:100]
    kind = str(kind or "custom_form").strip().lower()
    # Nomes de novos provedores não exigem deploy ou alteração no schema.
    # A categoria informa a origem, mas NÃO habilita integração nativa.
    if not name or not re.fullmatch(r"[a-z][a-z0-9_-]{1,49}", kind):
        raise LeadCaptureError("Informe nome e origem válidos.", 422)
    key = secrets.token_urlsafe(40)
    source_id = str(uuid.uuid4())
    row = {
        "id": source_id,
        "client_id": client_id,
        "name": name,
        "kind": kind,
        "token_hash": _digest(key),
        "active": True,
    }
    await sb_insert(SOURCE_TABLE, row)
    return {
        "id": source_id,
        "name": name,
        "kind": kind,
        "active": True,
        "ingest_key": key,  # somente no retorno da criação; jamais persistida em claro
    }


async def disable_source(client_id: str, source_id: str) -> None:
    rows = await sb_select(SOURCE_TABLE, select="id", filters={
        "client_id": f"eq.{client_id}", "id": f"eq.{source_id}"
    }, limit=1)
    if not rows:
        raise LeadCaptureError("Fonte não encontrada.", 404)
    await sb_update(SOURCE_TABLE, filters={
        "client_id": f"eq.{client_id}", "id": f"eq.{source_id}"
    }, patch={"active": False}, returning="minimal")


async def _authenticate(source_id: str, key: str) -> dict:
    try:
        source_id = str(uuid.UUID(source_id))
    except (ValueError, TypeError):
        raise LeadCaptureError("Fonte inválida.", 401) from None
    # Um ID não determina a empresa por si só: o segredo forte é obrigatório.
    if len(key) < 40 or len(key) > 256:
        raise LeadCaptureError("Credencial inválida.", 401)
    rows = await sb_select(SOURCE_TABLE, select="id,client_id,kind,token_hash,active",
                           filters={"id": f"eq.{source_id}"}, limit=1)
    source = rows[0] if rows else {}
    expected = str(source.get("token_hash") or "")
    if not expected or not hmac.compare_digest(expected, _digest(key)) or not source.get("active"):
        raise LeadCaptureError("Credencial inválida.", 401)
    return source


async def ingest(source_id: str, key: str, payload: dict[str, Any]) -> dict:
    source = await _authenticate(source_id, key)
    event_id = str(payload.get("event_id") or "").strip()
    if not 1 <= len(event_id) <= 160 or any(ord(c) < 32 for c in event_id):
        raise LeadCaptureError("event_id estável é obrigatório.", 422)
    email_raw = str(payload.get("email") or "").strip()
    email = valid_email(email_raw) if email_raw else None
    phone = _phone(payload.get("phone"))
    if email_raw and (not email or len(email) > _EMAIL_MAX):
        raise LeadCaptureError("E-mail inválido.", 422)
    if not email and not phone:
        raise LeadCaptureError("Informe e-mail ou telefone.", 422)
    consent = payload.get("consent")
    if consent is not None and not isinstance(consent, dict):
        raise LeadCaptureError("Consentimento deve ser um objeto.", 422)
    consent = consent or {}
    if any(type(consent.get(k)) is not bool for k in ("email", "whatsapp") if k in consent):
        raise LeadCaptureError("Consentimento por canal deve ser booleano.", 422)
    # Não colocar payload arbitrário em logs ou no banco. Dados fornecidos
    # por fontes externas não autorizam envios, nem são copiados para listas.
    cid = source["client_id"]
    rows = await sb_select(EVENT_TABLE, select="id", filters={
        "client_id": f"eq.{cid}", "source_id": f"eq.{source_id}", "event_id": f"eq.{event_id}"
    }, limit=1)
    if rows:
        return {"ok": True, "duplicate": True}
    name = " ".join(str(payload.get("name") or "").split())[:100]
    campaign = str(payload.get("campaign") or "").strip()[:80]
    if campaign and not re.fullmatch(r"[a-z0-9_-]{2,80}", campaign):
        raise LeadCaptureError("Campanha inválida.", 422)
    attribution = {}
    for field in ("utm_source", "utm_medium", "utm_campaign"):
        value = str(payload.get(field) or "").strip()[:100]
        attribution[field] = value or None
    consent_version = str(payload.get("consent_version") or "").strip()[:80] or None
    row = {
        "id": str(uuid.uuid4()),
        "client_id": cid,
        "source_id": source_id,
        "event_id": event_id,
        "email_hash": _digest(email) if email else None,
        "phone_hash": _digest(phone) if phone else None,
        "email_ciphertext": encrypt_secret(email) if email else None,
        "phone_ciphertext": encrypt_secret(phone) if phone else None,
        "origin_label": str(payload.get("origin") or "")[:100],
        "name_ciphertext": encrypt_secret(name) if name else None,
        "campaign_key": campaign or None,
        **attribution,
        "consent_version": consent_version,
        "consent_email_claimed": consent.get("email"),
        "consent_whatsapp_claimed": consent.get("whatsapp"),
        "consent_verified": False,
        "status": "captured",
    }
    try:
        await sb_insert(EVENT_TABLE, row)
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 409:
            return {"ok": True, "duplicate": True}
        raise
    await sb_update(SOURCE_TABLE, filters={"id": f"eq.{source_id}", "client_id": f"eq.{cid}"},
                    patch={"last_received_at": datetime.now(timezone.utc).isoformat()}, returning="minimal")
    return {"ok": True, "duplicate": False}


async def list_events(client_id: str, limit: int = 50) -> list[dict]:
    return await sb_select(EVENT_TABLE,
                           select="id,source_id,event_id,origin_label,consent_email_claimed,consent_whatsapp_claimed,consent_verified,status,created_at",
                           filters={"client_id": f"eq.{client_id}"},
                           order="created_at.desc", limit=max(1, min(limit, 100)))


async def campaign_summary(client_id: str, campaign: str) -> dict:
    """Aggregate tenant-isolated campaign signups without returning personal data."""
    if not re.fullmatch(r"[a-z0-9_-]{2,80}", campaign):
        raise LeadCaptureError("Campanha inválida.", 422)
    from .sales_by_origin import _paged
    rows, truncated = await _paged(
        EVENT_TABLE,
        select="email_hash,phone_hash,consent_email_claimed,consent_whatsapp_claimed,consent_verified,utm_source,utm_medium,created_at,status",
        filters={"client_id": f"eq.{client_id}", "campaign_key": f"eq.{campaign}"},
        order="created_at.desc", max_rows=100_000,
    )
    if truncated:
        raise LeadCaptureError("Campanha grande demais para totalização completa.", 422)
    unique = set()
    daily = {}
    sources = {}
    opted_email = opted_whatsapp = verified = 0
    for item in rows:
        identity = item.get("email_hash") or item.get("phone_hash")
        if identity:
            unique.add(identity)
        if item.get("consent_email_claimed") is True:
            opted_email += 1
        if item.get("consent_whatsapp_claimed") is True:
            opted_whatsapp += 1
        if item.get("consent_verified") is True:
            verified += 1
        day = str(item.get("created_at") or "")[:10]
        if day:
            daily[day] = daily.get(day, 0) + 1
        source = str(item.get("utm_source") or "direto/nao_identificado")[:100]
        sources[source] = sources.get(source, 0) + 1
    return {
        "campaign": campaign, "total": len(rows), "unique": len(unique),
        "email_opt_in_claimed": opted_email, "whatsapp_opt_in_claimed": opted_whatsapp,
        "consent_verified": verified, "pending_validation": len(rows) - verified,
        "daily": [{"day": d, "leads": n} for d, n in sorted(daily.items())],
        "sources": [{"source": s, "leads": n} for s, n in sorted(sources.items(), key=lambda kv: -kv[1])],
        "sending_enabled": False,
    }
