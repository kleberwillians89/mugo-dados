"""Unified WhatsApp template adapter for CRM-owned brands (Ruah and future brands).

The existing WHATSAPP_BRAND_BRIDGES map selects the brand-specific CRM.
Each brand must deploy its own dedicated /mugoverso-templates Edge Function;
the inbox /mugoverso-bridge remains read-only. Secrets never leave the CRM.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

import httpx

from .crm_whatsapp_templates import _normalize
from .studio_calendar import StudioError
from .whatsapp_sources import bridge_for
from .whatsapp_native import validate_template_input, WhatsAppNativeError

_TIMEOUT = 25
_URL_SUFFIX = "/mugoverso-bridge"
_SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _config(client_id: str) -> tuple[str, str]:
    if not _SAFE_ID.fullmatch(client_id):
        raise StudioError("CRM_TEMPLATE_INVALID_TENANT")
    cfg = bridge_for(client_id)
    if not cfg:
        raise StudioError("CRM_TEMPLATES_NOT_CONNECTED", "CRM desta empresa não está conectado.")
    url, key = cfg["url"].rstrip("/"), cfg["key"]
    if not url.startswith("https://") or not url.endswith(_URL_SUFFIX) or not key:
        raise StudioError("CRM_TEMPLATES_NOT_CONFIGURED",
                          "A ponte do CRM não oferece gerenciamento de modelos.")
    return url[:-len(_URL_SUFFIX)] + "/mugoverso-templates", key


async def _request(client_id: str, *, method: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    url, key = _config(client_id)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.request(method, url,
                                            headers={"X-Mugoverso-Key": key},
                                            json=payload if method == "POST" else None)
        body = response.json() if response.content else {}
    except (httpx.HTTPError, ValueError):
        raise StudioError("CRM_TEMPLATES_UNREACHABLE",
                          "Não foi possível consultar os modelos no CRM da empresa.") from None
    if not isinstance(body, dict):
        raise StudioError("CRM_TEMPLATES_FAILED")
    if response.status_code == 404:
        raise StudioError("CRM_TEMPLATES_NOT_READY",
                          "A biblioteca de modelos ainda não foi publicada no CRM da empresa.")
    if response.status_code == 401:
        raise StudioError("CRM_TEMPLATES_AUTH_FAILED", "O CRM recusou a autenticação da ponte.")
    if response.status_code == 409:
        raise StudioError("CRM_TEMPLATES_NOT_CONNECTED",
                          str(body.get("message") or "WABA não configurada para esta marca.")[:200])
    if response.status_code == 422:
        raise StudioError("CRM_TEMPLATE_INVALID", str(body.get("message") or "Modelo inválido.")[:200])
    if response.status_code not in (200, 201) or body.get("ok") is not True:
        raise StudioError("CRM_TEMPLATES_FAILED", "O CRM não conseguiu administrar os modelos na Meta.")
    data = body.get("data")
    if not isinstance(data, dict):
        raise StudioError("CRM_TEMPLATES_FAILED")
    return data


async def list_templates(client_id: str) -> List[Dict[str, Any]]:
    data = await _request(client_id, method="GET")
    return [_normalize(item) for item in (data.get("templates") or []) if isinstance(item, dict)]


async def create_template(client_id: str, *, payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        validated = validate_template_input(
            name=payload.get("name", ""), category=payload.get("category", ""),
            language=payload.get("language", "pt_BR"), body=payload.get("body", ""),
            examples=payload.get("examples") or [], footer=payload.get("footer") or "",
            buttons=payload.get("buttons") or None,
        )
    except WhatsAppNativeError as exc:
        raise StudioError("CRM_TEMPLATE_INVALID", exc.message) from None
    data = await _request(client_id, method="POST", payload=validated)
    item = data.get("template") or {}
    if not isinstance(item, dict) or not item.get("name"):
        raise StudioError("CRM_TEMPLATES_FAILED")
    return {"id": str(item.get("id") or ""), "name": str(item["name"]),
            "language": str(item.get("language") or validated["language"]),
            "category": str(item.get("category") or validated["category"]),
            "status": str(item.get("status") or "PENDING").upper(),
            "provider": "crm_bridge"}
