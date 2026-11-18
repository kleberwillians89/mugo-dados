"""Shopify signed App Proxy -> Roove capture source.
Requires explicit store allowlist and dedicated server-side lead-source credentials.
No outbound sends are triggered.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from services import lead_capture

router = APIRouter(tags=["shopify-first-access"])


def verify_app_proxy_query(request: Request) -> str:
    params = request.query_params
    for key in ("signature", "shop", "timestamp"):
        if len(params.getlist(key)) != 1:
            raise HTTPException(401, "Origem inválida.")
    signature = str(params.get("signature") or "")
    if len(signature) != 64:
        raise HTTPException(401, "Assinatura inválida.")
    secret = os.getenv("SHOPIFY_CLIENT_SECRET", "").strip()
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
    shop = str(params["shop"]).strip().lower()
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
    data = await request.form()
    if data.get("website"):
        return JSONResponse({"ok": True})
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
