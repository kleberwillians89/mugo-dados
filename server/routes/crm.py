"""
Tarefas (guardadas no próprio Mugoverso) e Atendimento do CRM Mugô (somente leitura, agência).

Tarefas: equipe Mugô vê e gerencia todas; o cliente vê as marcadas como visíveis ao cliente e,
com "Gerenciar tarefas" (tasks.edit, conferido pela guarda de tenant), cria e altera essas.
As rotas mantêm o endereço /crm/... e o formato de resposta de antes, então as telas não mudam.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from services import studio_tasks
from services.crm_bridge import list_conversations, list_messages
from services.studio_messages import list_contacts
from services.studio_calendar import StudioError
from services.tenant import is_agency_user, require_client_read, require_client_role, require_user_id

router = APIRouter(prefix="/api/clients/{client_id}/crm", tags=["crm"])

AGENCY_ONLY = ("agency_admin",)
TASK_MANAGERS = ("agency_admin", "client_admin")

ERRORS = {
    "STATUS_INVALID": (400, "Status de tarefa inválido."),
    "PRIORITY_INVALID": (400, "Prioridade inválida."),
    "DUE_DATE_INVALID": (400, "Prazo inválido."),
    "TASK_TITLE_REQUIRED": (422, "Escreva o título da tarefa."),
    "TASK_NOT_FOUND": (404, "Tarefa não encontrada."),
    "TASK_SAVE_FAILED": (502, "Não foi possível salvar a tarefa. Tente de novo."),
    "CONVERSATION_NOT_FOUND": (404, "Conversa não encontrada para este cliente."),
    "CRM_UNREACHABLE": (502, "O CRM não respondeu agora. Tente de novo em instantes."),
    "CRM_FAILED": (502, "Não foi possível ler o CRM agora."),
}


def _http(exc: StudioError) -> HTTPException:
    status, detail = ERRORS.get(exc.code, (502, "Não foi possível ler o CRM agora."))
    return HTTPException(status_code=status, detail=detail)


class TaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=4000)
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = Field(default=None, max_length=10)
    due_time: Optional[str] = Field(default=None, max_length=5)
    category: Optional[str] = Field(default=None, max_length=60)
    assignee_name: Optional[str] = Field(default=None, max_length=80)
    visible_to_client: Optional[bool] = None


@router.get("/tasks")
async def crm_tasks(client_id: str, status: Optional[str] = None, limit: int = 200,
                    authorization: Optional[str] = Header(None)):
    cid = await require_client_read(client_id, authorization)
    client_view = not await is_agency_user(authorization, cid)
    try:
        return await studio_tasks.list_tasks(cid, status=status, limit=limit, client_view=client_view)
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/client-tasks")
async def crm_client_tasks(client_id: str, authorization: Optional[str] = Header(None)):
    # Leitura de qualquer membro da empresa: só as tarefas visíveis ao cliente, sem nada interno.
    cid = await require_client_read(client_id, authorization)
    try:
        return await studio_tasks.list_client_tasks(cid)
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/tasks", status_code=201)
async def crm_task_create(client_id: str, body: TaskInput, authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=TASK_MANAGERS)
    uid = await require_user_id(authorization)
    try:
        return {"task": await studio_tasks.create_task(cid, body.model_dump(exclude_unset=True), user_id=uid,
                                                       client_view=not await is_agency_user(authorization, cid))}
    except StudioError as exc:
        raise _http(exc) from None


@router.patch("/tasks/{task_id}")
async def crm_task_update(client_id: str, task_id: UUID, body: TaskInput, authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=TASK_MANAGERS)
    try:
        return {"task": await studio_tasks.update_task(cid, str(task_id), body.model_dump(exclude_unset=True),
                                                       client_view=not await is_agency_user(authorization, cid))}
    except StudioError as exc:
        raise _http(exc) from None


@router.delete("/tasks/{task_id}")
async def crm_task_delete(client_id: str, task_id: UUID, authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=TASK_MANAGERS)
    try:
        await studio_tasks.delete_task(cid, str(task_id), client_view=not await is_agency_user(authorization, cid))
        return {"ok": True}
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/conversations")
async def crm_conversations(client_id: str, limit: int = 50, authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY_ONLY)
    try:
        # Telefones vêm do cadastro do Dados (servidor), nunca do navegador.
        phones = [row.get("phone") for row in await list_contacts(cid)]
        return await list_conversations(cid, limit=limit, phones=phones)
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
