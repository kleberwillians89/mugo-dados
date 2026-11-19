"""
Entrada de eventos vindos do CRM Mugô (sem usuário logado): autenticados pela mesma chave da ponte
(X-Dados-Ops-Key == CRM_OPS_API_KEY). Eventos: resposta do convite de resumo (invite_reply) e status de entrega
da Meta para mensagens da Central de Automações (message_status: sent/delivered/read/failed).
"""
from __future__ import annotations

import asyncio
import hmac
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from services.automations import apply_status
from services.studio_messages import handle_invite_reply

router = APIRouter(prefix="/api/hooks", tags=["hooks"])


class InviteReply(BaseModel):
    model_config = ConfigDict(extra="ignore")
    provider_message_id: str = Field(min_length=1, max_length=240)
    context_message_id: str = Field(min_length=1, max_length=240)
    wa_id: str = Field(min_length=8, max_length=20)
    answer: str = Field(default="", max_length=200)


class MessageStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    provider_message_id: str = Field(min_length=1, max_length=240)
    status: str = Field(min_length=1, max_length=20)
    error: Optional[str] = Field(default=None, max_length=300)


class CrmHook(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str = Field(max_length=40)
    reply: Optional[InviteReply] = None
    status: Optional[MessageStatus] = None


def _authorized(key: Optional[str]) -> bool:
    expected = (os.getenv("CRM_OPS_API_KEY") or "").strip()
    return bool(expected) and hmac.compare_digest(expected, (key or "").strip())


@router.post("/crm")
async def crm_hook(body: CrmHook, x_dados_ops_key: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    if not _authorized(x_dados_ops_key):
        raise HTTPException(status_code=401, detail="Chave inválida.")
    if body.type == "invite_reply" and body.reply:
        return await handle_invite_reply(body.reply.model_dump())
    if body.type == "message_status" and body.status:
        return await apply_status(body.status.provider_message_id, body.status.status, body.status.error)
    raise HTTPException(status_code=400, detail="Evento desconhecido.")


class InstagramDmHook(BaseModel):
    model_config = ConfigDict(extra="ignore")
    client_id: str = Field(min_length=1, max_length=120)


@router.post("/instagram-dm")
async def instagram_dm_hook(body: InstagramDmHook, x_ig_dm_key: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """Aviso da Edge Function instagram-webhook: chegou Direct novo nesta marca → responde agora."""
    expected = (os.getenv("IG_DM_HOOK_KEY") or "").strip()
    if not expected or not hmac.compare_digest(expected, (x_ig_dm_key or "").strip()):
        raise HTTPException(status_code=401, detail="Chave inválida.")
    from services.ig_direct import process_client
    return await process_client(body.client_id)


_AI_TASKS: set = set()  # referência para a tarefa não ser recolhida antes de terminar


class WhatsAppAiHook(BaseModel):
    model_config = ConfigDict(extra="ignore")
    client_id: str = Field(min_length=1, max_length=120)


@router.post("/whatsapp-ai")
async def whatsapp_ai_hook(body: WhatsAppAiHook, x_whatsapp_ai_key: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """Aviso da Edge Function whatsapp-webhook: chegou mensagem nova nesta marca → a IA responde (ou sugere) agora."""
    expected = (os.getenv("WHATSAPP_AI_HOOK_KEY") or "").strip()
    if not expected or not hmac.compare_digest(expected, (x_whatsapp_ai_key or "").strip()):
        raise HTTPException(status_code=401, detail="Chave inválida.")
    from services.whatsapp_ai import process_client
    # Responde na hora para a Edge Function e processa em seguida: a cliente não espera o aviso voltar.
    task = asyncio.create_task(process_client(body.client_id))
    _AI_TASKS.add(task)
    task.add_done_callback(_AI_TASKS.discard)
    return {"queued": True}
