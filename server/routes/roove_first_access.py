"""Shopify signed App Proxy -> Roove capture source.
Requires explicit store allowlist and dedicated server-side lead-source credentials.
No outbound sends are triggered.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from urllib.parse import parse_qs
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from services import lead_capture

router = APIRouter(tags=["shopify-first-access"])


def verify_shopify_proxy_signature(request: Request, *, secret_env: str = "SHOPIFY_CLIENT_SECRET") -> str:
    params = request.query_params
    for key in ("signature", "shop", "timestamp"):
        if len(params.getlist(key)) != 1:
            raise HTTPException(401, "Origem inválida.")
    signature = str(params.get("signature") or "")
    if len(signature) != 64:
        raise HTTPException(401, "Assinatura inválida.")
    # Distinct app-proxy credentials must never replace the existing Shopify OAuth secret.
    secret = os.getenv(secret_env, "").strip()
    if not secret:
        raise HTTPException(503, "Integração Shopify não configurada.")
    try:
        timestamp = int(params["timestamp"])
    except (ValueError, TypeError):
        raise HTTPException(401, "Timestamp inválido.") from None
    if abs(int(time.time()) - timestamp) > 300:
        raise HTTPException(401, "Solicitação expirada.")
    # Shopify App Proxy: sorted key=value pairs concatenated without &.
    data = "".join(
        f"{key}={','.join(params.getlist(key))}"
        for key in sorted(set(params.keys()) - {"signature"})
    )
    expected = hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "Assinatura inválida.")
    return str(params["shop"]).strip().lower()


def verify_app_proxy_query(request: Request) -> str:
    """Backward-compatible Roove allowlist (legacy route)."""
    shop = verify_shopify_proxy_signature(request)
    allowed = os.getenv("ROOVE_FIRST_ACCESS_SHOP_DOMAIN", "").strip().lower()
    if not allowed or shop != allowed or not shop.endswith(".myshopify.com"):
        raise HTTPException(403, "Loja não autorizada.")
    return shop


@router.post("/api/shopify/first-access")
async def first_access(request: Request):
    verify_app_proxy_query(request)
    if int(request.headers.get("content-length") or 0) > 8192:
        raise HTTPException(413, "Cadastro muito grande.")
    raw = await request.body()
    if len(raw) > 8192:
        raise HTTPException(413, "Cadastro muito grande.")
    # Shopify App Proxy forwards application/x-www-form-urlencoded bodies.
    # Parse explicitly: request.form() depends on python-multipart, which is
    # not a declared server requirement, and would break live submissions.
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Envie o cadastro como formulário.")
    try:
        fields = parse_qs(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=24)
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(422, "Formulário inválido.") from None
    if any(len(values) != 1 for values in fields.values()):
        raise HTTPException(422, "Campos repetidos não são permitidos.")
    data = {key: values[0] for key, values in fields.items()}
    if data.get("website"):
        # Honeypot: silently drop bot submissions; do not record a lead.
        return JSONResponse({"ok": True, "accepted": False})
    name = " ".join(str(data.get("name") or "").split())
    email = str(data.get("email") or "").strip()
    phone = str(data.get("phone") or "").strip()
    if not (2 <= len(name) <= 100 and 3 <= len(email) <= 254 and 10 <= len(phone) <= 20):
        raise HTTPException(422, "Preencha nome, e-mail e WhatsApp com DDD.")
    source_id = os.getenv("ROOVE_FIRST_ACCESS_SOURCE_ID", "").strip()
    source_key = os.getenv("ROOVE_FIRST_ACCESS_INGEST_KEY", "").strip()
    if not source_id or not source_key:
        raise HTTPException(503, "Fonte First Access não configurada.")
    consent_email = data.get("consent_email") == "sim"
    consent_whatsapp = data.get("consent_whatsapp") == "sim"
    event_id = str(data.get("event_id") or "")
    payload: dict[str, Any] = {
        "event_id": event_id, "name": name,
        "email": email, "phone": phone,
        "campaign": "roove_first_access_2026",
        "origin": "shopify_first_access",
        "utm_source": str(data.get("utm_source") or ""),
        "utm_medium": str(data.get("utm_medium") or ""),
        "utm_campaign": str(data.get("utm_campaign") or ""),
        "consent": {"email": consent_email, "whatsapp": consent_whatsapp},
        "consent_version": str(data.get("consent_version") or ""),
    }
    try:
        # The source credential stays on the backend, never in Liquid.
        return await lead_capture.ingest(source_id, source_key, payload)
    except lead_capture.LeadCaptureError as exc:
        raise HTTPException(exc.status, exc.message) from None


@router.post("/api/shopify/lead-capture/", include_in_schema=False)
@router.post("/api/shopify/lead-capture")
async def generic_shopify_lead_capture(request: Request):
    """Reusable signed App Proxy for any connected Shopify tenant.

    Configure the Shopify app proxy once to forward /apps/mugo-first-access
    to this route; no brand-specific env vars or private keys in Liquid.
    """
    shop = verify_shopify_proxy_signature(request, secret_env="SHOPIFY_MUGO_METRICS_CLIENT_SECRET")
    if int(request.headers.get("content-length") or 0) > 8192:
        raise HTTPException(413, "Cadastro muito grande.")
    raw = await request.body()
    if len(raw) > 8192:
        raise HTTPException(413, "Cadastro muito grande.")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Envie o cadastro como formulário.")
    try:
        fields = parse_qs(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=32)
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(422, "Formulário inválido.") from None
    if any(len(values) != 1 for values in fields.values()):
        raise HTTPException(422, "Campos repetidos não são permitidos.")
    data = {key: values[0] for key, values in fields.items()}
    if data.get("website"):
        return JSONResponse({"ok": True, "accepted": False})
    name = " ".join(str(data.get("name") or "").split())
    email = str(data.get("email") or "").strip()
    phone = str(data.get("phone") or "").strip()
    if not (2 <= len(name) <= 100 and 3 <= len(email) <= 254 and 10 <= len(phone) <= 20):
        raise HTTPException(422, "Preencha nome, e-mail e WhatsApp com DDD.")
    campaign = str(data.get("campaign") or "").strip().lower()
    if not campaign:
        raise HTTPException(422, "Informe a campanha de captação.")
    payload: dict[str, Any] = {
        "event_id": str(data.get("event_id") or ""),
        "name": name, "email": email, "phone": phone,
        "campaign": campaign,
        "origin": "shopify_app_proxy",
        "utm_source": str(data.get("utm_source") or ""),
        "utm_medium": str(data.get("utm_medium") or ""),
        "utm_campaign": str(data.get("utm_campaign") or ""),
        "consent": {
            "email": data.get("consent_email") == "sim",
            "whatsapp": data.get("consent_whatsapp") == "sim",
        },
        "consent_version": str(data.get("consent_version") or ""),
    }
    try:
        return await lead_capture.ingest_shopify_proxy(shop, payload)
    except lead_capture.LeadCaptureError as exc:
        raise HTTPException(exc.status, exc.message) from None
