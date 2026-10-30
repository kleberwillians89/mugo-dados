"""
Entrada de eventos vindos do CRM Mugô (sem usuário logado): autenticados pela mesma chave da ponte
(X-Dados-Ops-Key == CRM_OPS_API_KEY). Eventos: resposta do convite de resumo (invite_reply) e status de entrega
da Meta para mensagens da Central de Automações (message_status: sent/delivered/read/failed).
"""
from __future__ import annotations

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
