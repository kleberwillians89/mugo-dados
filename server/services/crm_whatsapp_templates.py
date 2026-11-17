"""Approved-template management through the already connected CRM Mugô WABA.

The Meta access token stays in the CRM Supabase Edge Function. The Mugô Dados
backend authenticates by the existing server-to-server CRM_OPS_API_KEY and sends
only the active tenant ID, which CRM resolves through an explicit organization
or client link. This service NEVER imports any token into the Dados database.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

import httpx

from .crm_bridge import _config
from .studio_calendar import StudioError

TIMEOUT = 20
SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _url() -> tuple[str, str] | None:
    cfg = _config()
    if not cfg:
        return None
    url, key = cfg
    if not url.startswith("https://") or not url.endswith("/dados-ops-api"):
        return None
    return url.removesuffix("/dados-ops-api") + "/dados-whatsapp-templates", key


async def _request(client_id: str, *, method: str, payload: Dict[str, Any] | None = None, mode: str | None = None, options: Dict[str, str | int] | None = None) -> Dict[str, Any]:
    if not SAFE_ID.fullmatch(client_id):
        raise StudioError("CRM_TEMPLATE_INVALID_TENANT")
    cfg = _url()
    if not cfg:
        raise StudioError("CRM_TEMPLATES_NOT_CONFIGURED", "A conexão entre o Mugô Dados e o CRM ainda não está configurada.")
    url, key = cfg
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.request(
                method, url,
                headers={"X-Dados-Ops-Key": key},
                params={"external_client_id": client_id, **({"mode": mode} if mode else {}), **(options or {})},
                json=payload if method == "POST" else None,
            )
        body = response.json() if response.content else {}
    except (httpx.HTTPError, ValueError):
        raise StudioError("CRM_TEMPLATES_UNREACHABLE", "O CRM não respondeu à consulta de modelos.") from None
    if not isinstance(body, dict):
        raise StudioError("CRM_TEMPLATES_FAILED")
    if response.status_code == 403:
        raise StudioError("CRM_TEMPLATES_NOT_LINKED", "Esta empresa ainda não está vinculada à WABA correta no CRM.")
    if response.status_code == 404:
        if body.get("code") == "CONVERSATION_NOT_FOUND":
            raise StudioError("CONVERSATION_NOT_FOUND")
        raise StudioError("CRM_TEMPLATES_NOT_READY", "A ponte do CRM ainda não foi publicada.")
    if response.status_code == 409:
        raise StudioError("CRM_TEMPLATES_NOT_CONNECTED", "Não foi encontrada uma WABA autorizada para esta empresa.")
    if response.status_code == 422:
        raise StudioError("CRM_TEMPLATE_INVALID", str(body.get("message") or "Modelo inválido.")[:200])
    if response.status_code != 200 and response.status_code != 201:
        raise StudioError("CRM_TEMPLATES_FAILED", "Não foi possível consultar a Meta pela conexão do CRM.")
    if body.get("ok") is not True:
        raise StudioError("CRM_TEMPLATES_FAILED")
    return body.get("data") or {}


def _normalize(raw: Dict[str, Any]) -> Dict[str, Any]:
    components = raw.get("components") or []
    if not isinstance(components, list):
        components = []
    body = next((str(c.get("text") or "") for c in components
                 if isinstance(c, dict) and str(c.get("type") or "").upper() == "BODY"), "")
    return {
        "name": str(raw.get("name") or "")[:81],
        "language": str(raw.get("language") or "")[:20],
        "status": str(raw.get("status") or "PENDING").upper()[:30],
        "category": str(raw.get("category") or "UTILITY").upper()[:30],
        "body": body[:1024],
        "variables": len(set(re.findall(r"\{\{\s*(\d+)\s*\}\}", body))),
    }


async def list_templates(client_id: str) -> List[Dict[str, Any]]:
    data = await _request(client_id, method="GET")
    return [_normalize(t) for t in (data.get("templates") or []) if isinstance(t, dict)]


async def create_template(client_id: str, *, payload: Dict[str, Any]) -> Dict[str, Any]:
    from .whatsapp_native import validate_template_input
    validated = validate_template_input(
        name=payload.get("name", ""), category=payload.get("category", ""),
        language=payload.get("language", "pt_BR"), body=payload.get("body", ""),
        examples=payload.get("examples") or [], footer=payload.get("footer", ""),
    )
    data = await _request(client_id, method="POST", payload=validated)
    template = data.get("template") or {}
    if not isinstance(template, dict) or not template.get("name"):
        raise StudioError("CRM_TEMPLATES_FAILED")
    return {
        "id": str(template.get("id") or ""),
        "name": str(template["name"]),
        "language": str(template.get("language") or validated["language"]),
        "category": str(template.get("category") or validated["category"]),
        "status": str(template.get("status") or "PENDING").upper(),
        "provider": "mugozap_crm",
    }


async def connection_status(client_id: str) -> bool:
    result = await _request(client_id, method="GET", mode="status")
    return result.get("connected") is True and result.get("templates_supported") is True


async def brand_conversations(client_id: str, limit: int = 60) -> Dict[str, Any]:
    data = await _request(client_id, method="GET", mode="conversations",
                          options={"limit": max(1, min(int(limit), 200))})
    return {"available": True, "connected": bool(data.get("connected")), "channel_provider": "mugozap_crm",
            "conversations": data.get("conversations") or []}


async def brand_messages(client_id: str, conversation_id: str, limit: int = 100) -> Dict[str, Any]:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", conversation_id):
        raise StudioError("CONVERSATION_NOT_FOUND")
    data = await _request(client_id, method="GET", mode="messages",
                          options={"conversation_id": conversation_id})
    return {"available": True, "messages": (data.get("messages") or [])[-max(1, min(int(limit), 200)):]}


async def brand_leads(client_id: str, start: str, end: str) -> Dict[str, Any]:
    data = await _request(client_id, method="GET", mode="leads",
                          options={"period_start": start[:10], "period_end": end[:10]})
    return {"available": True, "connected": bool(data.get("connected")),
            "leads": data.get("leads") or [], "truncated": bool(data.get("truncated"))}
