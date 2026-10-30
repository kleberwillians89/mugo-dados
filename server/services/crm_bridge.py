"""
Ponte somente leituro Mugoverso -> CRM Mugô (tarefas e atendimento WhatsApp).

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
from typing import Any, Dict, List, Optional

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
    if resp.status_code == 404 and code == "NOT_FOUND":
        # Função não publicada no CRM (ou versão antiga sem este endpoint).
        return unavailable("function_missing")
    if code == "CONVERSATION_NOT_FOUND":
        raise StudioError("CONVERSATION_NOT_FOUND")
    if resp.status_code == 401 or code in {"UNAUTHORIZED", "CONFIGURATION_MISSING"}:
        return unavailable("auth_failed")
    raise StudioError("CRM_FAILED")


async def list_tasks(client_id: str, status: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    if status and status not in TASK_STATUSES:
        raise StudioError("STATUS_INVALID")
    return await _call("tasks", client_id, {"status": status, "limit": max(1, min(int(limit), 200))})


async def list_client_tasks(client_id: str) -> Dict[str, Any]:
    """Visão do CLIENTE: só tarefas com a etiqueta "cliente" no CRM; o CRM já devolve sem nada interno."""
    result = await _call("tasks", client_id, {"audience": "client", "limit": 50})
    if not result.get("available"):
        return result
    allowed = {"id", "title", "status", "due_date", "updated_at"}
    tasks = [{k: v for k, v in (t or {}).items() if k in allowed} for t in result.get("tasks") or []]
    return {"available": True, "tasks": [t for t in tasks if t.get("status") in {"pending", "in_progress", "completed"}]}


async def list_conversations(client_id: str, limit: int = 50, phones: Optional[List[str]] = None) -> Dict[str, Any]:
    wa_ids = ",".join(p for p in (re.sub(r"\D", "", str(x or "")) for x in (phones or [])[:30]) if p)
    return await _call("conversations", client_id, {"limit": max(1, min(int(limit), 200)), "wa_ids": wa_ids or None})


async def list_messages(client_id: str, conversation_id: str, limit: int = 100) -> Dict[str, Any]:
    if not _UUID.match(conversation_id or ""):
        raise StudioError("CONVERSATION_NOT_FOUND")
    return await _call("messages", client_id, {"conversation_id": conversation_id, "limit": max(1, min(int(limit), 200))})


def _events_url(api_url: str) -> str:
    # Mesmo projeto e mesma chave: dados-ops-api (leitura) e dados-ops-events (escrita) ficam lado a lado.
    return api_url[: -len("dados-ops-api")] + "dados-ops-events" if api_url.endswith("dados-ops-api") else ""


async def post_event(client_id: str, event_type: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """Manda um evento ao CRM (tarefa + aviso ao time). Nunca levanta: devolve ok/código para quem guarda o resultado."""
    cfg = _config()
    if not cfg:
        return {"ok": False, "code": "not_configured"}
    url = _events_url(cfg[0])
    if not url:
        return {"ok": False, "code": "not_configured"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(url, headers={"X-Dados-Ops-Key": cfg[1]},
                                     json={"type": event_type, "external_client_id": client_id, "event": event})
        body = resp.json() if resp.content else {}
    except (httpx.HTTPError, ValueError):
        print(f"[crm_bridge] event={event_type} client_id={client_id} status=network_error")
        return {"ok": False, "code": "network"}
    print(f"[crm_bridge] event={event_type} client_id={client_id} status={resp.status_code}")
    if resp.status_code == 200 and isinstance(body, dict) and body.get("ok"):
        return {"ok": True, "task_id": str((body.get("data") or {}).get("task_id") or "")[:80] or None}
    code = str((body or {}).get("code") or f"HTTP_{resp.status_code}")[:80]
    if resp.status_code == 404 and code == "NOT_FOUND":
        code = "function_missing"
    return {"ok": False, "code": code}
