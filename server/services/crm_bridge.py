"""
Ponte somente leitura Mugô Dados -> CRM Mugô (tarefas e atendimento WhatsApp).

O CRM continua sendo a fonte da verdade: nada é copiado nem guardado aqui. Cada chamada vai à
função `dados-ops-api` do CRM, que resolve organização + cliente a partir do id da empresa no Dados
(tabela external_integrations do CRM). Este módulo nunca manda organization_id/client_id do CRM.

Configuração (Render):
- CRM_OPS_API_URL: https://<projeto-crm>.supabase.co/functions/v1/dados-ops-api
- CRM_OPS_API_KEY: mesma chave do segredo DADOS_OPS_API_KEY no Supabase do CRM

Sem configuração ou com cliente ainda não ligado no CRM, devolve `available: false` com o motivo,
para a tela mostrar um aviso claro em vez de erro.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, Optional

import httpx

from .studio_calendar import StudioError

TIMEOUT_SECONDS = 15
TASK_STATUSES = {"pending", "in_progress", "completed", "cancelled"}
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _config() -> Optional[tuple[str, str]]:
    url = (os.getenv("CRM_OPS_API_URL") or "").strip().rstrip("/")
    key = (os.getenv("CRM_OPS_API_KEY") or "").strip()
    return (url, key) if url and key else None


def unavailable(reason: str) -> Dict[str, Any]:
    return {"available": False, "reason": reason}


async def _call(endpoint: str, client_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
    cfg = _config()
    if not cfg:
        return unavailable("not_configured")
    url, key = cfg
    query = {"external_client_id": client_id, **{k: v for k, v in params.items() if v is not None}}
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.get(f"{url}/{endpoint}", params=query, headers={"X-Dados-Ops-Key": key})
        body = resp.json() if resp.content else {}
    except (httpx.HTTPError, ValueError):
        print(f"[crm_bridge] endpoint={endpoint} client_id={client_id} status=network_error")
        raise StudioError("CRM_UNREACHABLE") from None
    duration_ms = int((time.monotonic() - started) * 1000)
    code = str((body or {}).get("code") or "")
    print(f"[crm_bridge] endpoint={endpoint} client_id={client_id} status={resp.status_code} ms={duration_ms}")
    if resp.status_code == 200 and isinstance(body, dict) and body.get("ok"):
        return {"available": True, **(body.get("data") or {})}
    if code == "UNKNOWN_EXTERNAL_CLIENT":
        return unavailable("not_linked")
    if code == "CONVERSATION_NOT_FOUND":
        raise StudioError("CONVERSATION_NOT_FOUND")
    if resp.status_code == 401 or code in {"UNAUTHORIZED", "CONFIGURATION_MISSING"}:
        return unavailable("auth_failed")
    raise StudioError("CRM_FAILED")


async def list_tasks(client_id: str, status: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    if status and status not in TASK_STATUSES:
        raise StudioError("STATUS_INVALID")
    return await _call("tasks", client_id, {"status": status, "limit": max(1, min(int(limit), 200))})


async def list_conversations(client_id: str, limit: int = 50) -> Dict[str, Any]:
    return await _call("conversations", client_id, {"limit": max(1, min(int(limit), 200))})


async def list_messages(client_id: str, conversation_id: str, limit: int = 100) -> Dict[str, Any]:
    if not _UUID.match(conversation_id or ""):
        raise StudioError("CONVERSATION_NOT_FOUND")
    return await _call("messages", client_id, {"conversation_id": conversation_id, "limit": max(1, min(int(limit), 200))})
