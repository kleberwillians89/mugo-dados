"""
Tarefas e Atendimento do CRM Mugô dentro do Mugô Dados — somente leitura, só para a agência.

Cliente (client_admin/viewer) não vê: conversas e tarefas são operação interna da Mugô.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from services.crm_bridge import list_conversations, list_messages, list_tasks
from services.studio_calendar import StudioError
from services.tenant import require_client_role

router = APIRouter(prefix="/api/clients/{client_id}/crm", tags=["crm"])

AGENCY_ONLY = ("agency_admin",)

ERRORS = {
    "STATUS_INVALID": (400, "Status de tarefa inválido."),
    "CONVERSATION_NOT_FOUND": (404, "Conversa não encontrada para este cliente."),
    "CRM_UNREACHABLE": (502, "O CRM não respondeu agora. Tente de novo em instantes."),
    "CRM_FAILED": (502, "Não foi possível ler o CRM agora."),
}


def _http(exc: StudioError) -> HTTPException:
    status, detail = ERRORS.get(exc.code, (502, "Não foi possível ler o CRM agora."))
    return HTTPException(status_code=status, detail=detail)


@router.get("/tasks")
async def crm_tasks(client_id: str, status: Optional[str] = None, limit: int = 100,
                    authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY_ONLY)
    try:
        return await list_tasks(cid, status=status, limit=limit)
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/conversations")
async def crm_conversations(client_id: str, limit: int = 50, authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY_ONLY)
    try:
        return await list_conversations(cid, limit=limit)
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/conversations/{conversation_id}/messages")
async def crm_messages(client_id: str, conversation_id: str, limit: int = 100,
                       authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY_ONLY)
    try:
        return await list_messages(cid, conversation_id, limit=limit)
    except StudioError as exc:
        raise _http(exc) from None
