"""RUAH Black Friday: public, captcha-verified lead collection without Shopify App Proxy.
No Shopify/client credential is ever supplied to the browser. Never triggers messaging.
"""
from __future__ import annotations

import os
from urllib.parse import parse_qs

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from services import lead_capture

router = APIRouter(tags=["public-ruah-capture"])
ALLOWED_ORIGINS = {"https://ruahparfums.com.br", "https://www.ruahparfums.com.br"}
EXPECTED_HOSTS = {"ruahparfums.com.br", "www.ruahparfums.com.br"}
CAMPAIGN = "ruah_black_friday_2026"
MAX_BODY = 8192


async def _turnstile_valid(token: str, secret: str, remote_ip: str | None) -> bool:
    if not token or len(token) > 2048:
        return False
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={"secret": secret, "response": token, "remoteip": remote_ip or ""},
            )
            response.raise_for_status()
            verification = response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "Proteção do cadastro temporariamente indisponível.") from None
    return (
        verification.get("success") is True
        and str(verification.get("hostname") or "").lower() in EXPECTED_HOSTS
        and verification.get("action") == "ruah_bf_signup"
    )


@router.post("/api/public/ruah-bf/leads")
async def ruah_bf_leads(request: Request):
    # Origin is a browser cross-site request guard, not authentication; CAPTCHA is mandatory.
    if request.headers.get("origin", "").rstrip("/").lower() not in ALLOWED_ORIGINS:
        raise HTTPException(403, "Origem não autorizada.")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Formato de formulário inválido.")
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        raise HTTPException(413, "Cadastro excede o limite.")
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(413, "Cadastro excede o limite.")
    try:
        fields = parse_qs(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=24)
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(422, "Formulário inválido.") from None
    if any(len(values) != 1 for values in fields.values()):
        raise HTTPException(422, "Campos repetidos não são permitidos.")
    form = {key: items[0] for key, items in fields.items()}
    if form.get("website"):
        return JSONResponse({"ok": True, "accepted": False})
    client_id = os.getenv("RUAH_BF_CLIENT_ID", "").strip()
    source_id = os.getenv("RUAH_BF_SOURCE_ID", "").strip()
    source_key = os.getenv("RUAH_BF_INGEST_KEY", "").strip()
    turnstile_secret = os.getenv("RUAH_BF_TURNSTILE_SECRET", "").strip()
    if not all((client_id, source_id, source_key, turnstile_secret)):
        raise HTTPException(503, "Captação RUAH ainda não configurada.")
    if form.get("campaign") != CAMPAIGN:
        raise HTTPException(422, "Campanha inválida.")
    name = " ".join(form.get("name", "").split())
    email = form.get("email", "").strip()
    phone = form.get("phone", "").strip()
    if not (2 <= len(name) <= 100 and 3 <= len(email) <= 254 and 10 <= len(phone) <= 20):
        raise HTTPException(422, "Preencha nome, e-mail e WhatsApp com DDD.")
    if not await _turnstile_valid(form.get("cf-turnstile-response", ""), turnstile_secret, request.client.host if request.client else None):
        raise HTTPException(422, "Confirme a verificação de segurança e tente novamente.")
    try:
        source = await lead_capture._authenticate(source_id, source_key)
        if str(source.get("client_id")) != client_id:
            raise HTTPException(503, "Fonte não corresponde à empresa configurada.")
        result = await lead_capture._ingest_authenticated(source, {
            "event_id": form.get("event_id", ""),
            "name": name, "email": email, "phone": phone,
            "campaign": CAMPAIGN, "origin": "ruah_bf_public_landing",
            "utm_source": form.get("utm_source", "")[:100],
            "utm_medium": form.get("utm_medium", "")[:100],
            "utm_campaign": form.get("utm_campaign", "")[:100],
            "consent_version": "ruah_bf_2026_v1",
            "consent": {
                "email": form.get("consent_email") == "sim",
                "whatsapp": form.get("consent_whatsapp") == "sim",
            },
        })
    except lead_capture.LeadCaptureError as exc:
        raise HTTPException(exc.status, exc.message) from None
    return {"ok": True, "accepted": True, "duplicate": bool(result.get("duplicate"))}
