"""Resend: envio de e-mail (lote de até 100), domínios e assinatura do webhook (Svix).

- ``RESEND_API_KEY``: chave da conta Resend da Mugô (cada marca envia do próprio domínio verificado nessa conta).
- ``EMAIL_SEND_ENABLED`` diferente de ``true`` = modo simulado: tudo roda (fila, histórico, números), mas nenhuma
  chamada sai para o Resend. É o padrão, igual às automações de WhatsApp.
- ``RESEND_WEBHOOK_SECRET``: segredo ``whsec_...`` do webhook cadastrado no painel do Resend.
- Descadastro em 1 clique (RFC 8058): todo e-mail de marketing leva ``List-Unsubscribe`` + ``List-Unsubscribe-Post``.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

API = "https://api.resend.com"
TIMEOUT = 30
BATCH_MAX = 100


class ResendError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.message = message
        self.retryable = retryable


def send_enabled() -> bool:
    return (os.getenv("EMAIL_SEND_ENABLED") or "").strip().lower() == "true"


def configured() -> bool:
    return bool((os.getenv("RESEND_API_KEY") or "").strip())


def public_api_url() -> str:
    """Endereço público do backend (para o link de descadastro). API_PUBLIC_URL ou a origem do webhook da Shopify."""
    explicit = (os.getenv("API_PUBLIC_URL") or "").strip().rstrip("/")
    if explicit.startswith("https://"):
        return explicit
    shopify = urlparse((os.getenv("SHOPIFY_WEBHOOK_URL") or "").strip())
    if shopify.scheme == "https" and shopify.netloc:
        return f"https://{shopify.netloc}"
    return ""


async def _call(method: str, path: str, *, json_body: Any = None, idem: Optional[str] = None) -> Any:
    key = (os.getenv("RESEND_API_KEY") or "").strip()
    if not key:
        raise ResendError("NOT_CONFIGURED", "Falta configurar a chave do Resend (RESEND_API_KEY) no servidor.")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if idem:
        headers["Idempotency-Key"] = idem[:256]
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.request(method, f"{API}{path}", json=json_body, headers=headers)
    except httpx.HTTPError:
        raise ResendError("UNREACHABLE", "O Resend não respondeu agora.", retryable=True) from None
    body: Any
    try:
        body = resp.json() if resp.content else {}
    except ValueError:
        body = {}
    if resp.status_code >= 400:
        name = str((body or {}).get("name") or resp.status_code) if isinstance(body, dict) else str(resp.status_code)
        message = str((body or {}).get("message") or "") if isinstance(body, dict) else ""
        print(f"[email_resend] path={path} status={resp.status_code} name={name}")
        retryable = resp.status_code == 429 or resp.status_code >= 500
        if name in ("validation_error", "invalid_from_address") and "domain" in message.lower():
            raise ResendError("DOMAIN_NOT_VERIFIED", "O domínio do remetente não está verificado no Resend.")
        raise ResendError(f"HTTP_{resp.status_code}", message or "O Resend recusou o envio.", retryable=retryable)
    return body


async def send_batch(emails: List[Dict[str, Any]], *, idem: Optional[str] = None) -> List[Optional[str]]:
    """Envia até 100 e-mails numa chamada. Retorna o id do Resend de cada um, na mesma ordem."""
    if not emails:
        return []
    if len(emails) > BATCH_MAX:
        raise ValueError("lote acima de 100")
    if not send_enabled():
        return [None] * len(emails)
    body = await _call("POST", "/emails/batch", json_body=emails, idem=idem)
    data = (body or {}).get("data") if isinstance(body, dict) else None
    ids = [str((item or {}).get("id") or "") or None for item in (data or [])]
    return ids + [None] * (len(emails) - len(ids))


async def list_domains() -> List[Dict[str, Any]]:
    body = await _call("GET", "/domains")
    return [{"name": d.get("name"), "status": d.get("status")} for d in ((body or {}).get("data") or []) if isinstance(d, dict)]


def domain_of(email: str) -> str:
    return str(email or "").rsplit("@", 1)[-1].strip().lower()


def verify_webhook(payload: bytes, headers: Dict[str, str], *, now: Optional[float] = None) -> bool:
    """Assinatura Svix: HMAC-SHA256 de ``id.timestamp.corpo`` com o segredo (base64 após ``whsec_``)."""
    secret = (os.getenv("RESEND_WEBHOOK_SECRET") or "").strip()
    msg_id, stamp, signatures = headers.get("svix-id"), headers.get("svix-timestamp"), headers.get("svix-signature")
    if not secret or not msg_id or not stamp or not signatures:
        return False
    try:
        if abs((now or time.time()) - int(stamp)) > 300:
            return False
        key = base64.b64decode(secret.split("_", 1)[1] if secret.startswith("whsec_") else secret)
    except (ValueError, IndexError):
        return False
    signed = f"{msg_id}.{stamp}.".encode() + payload
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    for part in signatures.split():
        version, _, value = part.partition(",")
        if version == "v1" and hmac.compare_digest(value, expected):
            return True
    return False
