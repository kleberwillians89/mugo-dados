"""De onde vem o WhatsApp de cada empresa.

- Empresa com CRM próprio (hoje só a Ruah): ponte só de leitura desse CRM (`mugoverso-bridge`),
  configurada em WHATSAPP_BRAND_BRIDGES = {"<client_id>": {"url": "...", "key": "..."}}. Esse CRM também
  manda as vendas que ele registra (a Ruah vende pelo WhatsApp e cadastra no CRM, não no Shopify).
- Número ligado direto no MUGOVERSO (app da Mugô na Meta → função `whatsapp-webhook`): `whatsapp_native`.
- Sem nenhum dos dois: número ligado à empresa no CRM Mugô (`dados-ops-api`) — hoje, o da própria Mugô.

Mesmo contrato de saída de `crm_bridge`: {"available": True, ...dados} ou {"available": False, "reason"}.
O telefone nunca chega aqui: só mascarado e a chave (hash) para casar com a venda.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional

import httpx

from . import crm_bridge, whatsapp_native
from .studio_calendar import StudioError

TIMEOUT_SECONDS = 20
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
# Id de empresa no MUGOVERSO: UUID ou slug antigo (ex.: "roove").
_CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$", re.I)


def _bridges() -> Dict[str, Dict[str, str]]:
    raw = (os.getenv("WHATSAPP_BRAND_BRIDGES") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        print("[whatsapp_sources] WHATSAPP_BRAND_BRIDGES inválido (JSON)")
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for client_id, cfg in (data or {}).items() if isinstance(data, dict) else []:
        url = str((cfg or {}).get("url") or "").strip()
        key = str((cfg or {}).get("key") or "").strip()
        if _CLIENT_ID.match(str(client_id)) and url.startswith("https://") and key:
            out[str(client_id).lower()] = {"url": url, "key": key}
    return out


def bridge_for(client_id: str) -> Optional[Dict[str, str]]:
    return _bridges().get(str(client_id).lower())


async def _bridge_call(cfg: Dict[str, str], endpoint: str, client_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
    query = {"endpoint": endpoint, **{k: v for k, v in params.items() if v is not None}}
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.get(cfg["url"], params=query, headers={"X-Mugoverso-Key": cfg["key"]})
        body = resp.json() if resp.content else {}
    except (httpx.HTTPError, ValueError):
        print(f"[whatsapp_sources] endpoint={endpoint} client_id={client_id} status=network_error")
        raise StudioError("CRM_UNREACHABLE") from None
    code = str((body or {}).get("code") or "") if isinstance(body, dict) else ""
    print(f"[whatsapp_sources] endpoint={endpoint} client_id={client_id} status={resp.status_code} "
          f"ms={int((time.monotonic() - started) * 1000)}")
    if resp.status_code == 200 and isinstance(body, dict) and body.get("ok"):
        return {"available": True, **(body.get("data") or {})}
    if code == "CONVERSATION_NOT_FOUND":
        raise StudioError("CONVERSATION_NOT_FOUND")
    if resp.status_code == 401:
        return crm_bridge.unavailable("auth_failed")
    if resp.status_code == 404:
        return crm_bridge.unavailable("function_missing")
    raise StudioError("CRM_FAILED")


async def brand_leads(client_id: str, start: str, end: str) -> Dict[str, Any]:
    cfg = bridge_for(client_id)
    if cfg:
        return await _bridge_call(cfg, "leads", client_id, {"period_start": start[:10], "period_end": end[:10]})
    if await whatsapp_native.active_number_ids(client_id):
        return await whatsapp_native.leads(client_id, start, end)
    return await crm_bridge.brand_leads(client_id, start, end)


async def brand_conversations(client_id: str, limit: int = 60) -> Dict[str, Any]:
    cfg = bridge_for(client_id)
    if cfg:
        return await _bridge_call(cfg, "conversations", client_id, {"limit": max(1, min(int(limit), 200))})
    if await whatsapp_native.active_number_ids(client_id):
        return await whatsapp_native.conversations(client_id, limit=limit)
    return await crm_bridge.brand_conversations(client_id, limit=limit)


async def brand_messages(client_id: str, conversation_id: str, limit: int = 100) -> Dict[str, Any]:
    if not _UUID.match(str(conversation_id)):
        raise StudioError("CONVERSATION_NOT_FOUND")
    cfg = bridge_for(client_id)
    if cfg:
        return await _bridge_call(cfg, "messages", client_id, {"conversation_id": conversation_id, "limit": max(1, min(int(limit), 300))})
    if await whatsapp_native.active_number_ids(client_id):
        native = await whatsapp_native.messages(client_id, conversation_id, limit=limit)
        if not native.pop("found", False):
            raise StudioError("CONVERSATION_NOT_FOUND")
        return native
    return await crm_bridge.list_messages(client_id, conversation_id, limit=limit)


async def brand_sales(client_id: str, start: str, end: str) -> List[Dict[str, Any]]:
    """Vendas que o CRM da marca registra (só quem tem CRM próprio). Formato de pedido do Shopify.

    `sale_date` é só a data: conta como 23:59 (horário de Brasília) daquele dia, para a venda do mesmo
    dia do primeiro contato entrar.
    """
    cfg = bridge_for(client_id)
    if not cfg:
        return []
    try:
        result = await _bridge_call(cfg, "sales", client_id, {"period_start": start[:10], "period_end": end[:10]})
    except StudioError:
        # Sem as vendas do CRM a tela ainda mostra conversas e origem; só o "virou venda" fica de fora.
        return []
    if not result.get("available"):
        return []
    out = []
    for index, sale in enumerate(result.get("sales") or []):
        day = str(sale.get("sale_date") or "")[:10]
        keys = [k for k in sale.get("phone_keys") or [] if isinstance(k, str) and re.fullmatch(r"[0-9a-f]{32}", k)]
        if not day or not keys:
            continue
        out.append({
            "name": f"Venda CRM {day}",
            "created_at_shopify": f"{day}T23:59:00-03:00",
            "value": max(0.0, float(sale.get("value") or 0)),
            "phone_keys": keys,
            "source": "crm",
            "_id": f"crm:{index}",
        })
    return out
