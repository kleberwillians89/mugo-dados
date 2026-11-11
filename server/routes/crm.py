"""
Tarefas (guardadas no próprio Mugoverso) e Atendimento do CRM Mugô (somente leitura, agência).

Tarefas: equipe Mugô vê e gerencia todas; o cliente vê as marcadas como visíveis ao cliente e,
com "Gerenciar tarefas" (tasks.edit, conferido pela guarda de tenant), cria e altera essas.
As rotas mantêm o endereço /crm/... e o formato de resposta de antes, então as telas não mudam.
"""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional
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
# Aprovar ou pedir ajuste: qualquer pessoa da empresa (o cliente que só visualiza também aprova a peça).
TASK_APPROVERS = ("agency_admin", "client_admin", "viewer", "owner", "admin")

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
    "ACTION_INVALID": (400, "Ação inválida."),
    "FORBIDDEN": (403, "Só a equipe Mugô faz a aprovação interna."),
    "STAGE_INVALID": (409, "A tarefa mudou de etapa. Atualize a tela."),
    "COMMENT_REQUIRED": (422, "Escreva o que precisa mudar."),
    "DELIVERABLE_URL_INVALID": (422, "O link da entrega precisa começar com https://"),
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
    assignee_user_id: Optional[UUID] = None
    visible_to_client: Optional[bool] = None
    needs_client_approval: Optional[bool] = None
    deliverable_url: Optional[str] = Field(default=None, max_length=1000)


class TaskApproval(BaseModel):
    action: Literal["submit", "internal_approve", "internal_changes", "client_approve", "client_changes", "comment"]
    comment: Optional[str] = Field(default=None, max_length=2000)
    internal: bool = False


async def _task_scope(authorization: Optional[str], cid: str) -> Dict[str, Any]:
    """Quem vê o quê nas Tarefas.

    - Equipe Mugô (admin da agência / gestora da conta): tudo, com aprovação interna.
    - Membro com "Ver e gerenciar as tarefas de todos" (acesso total da empresa tem): todas; aprovação interna só
      com "Aprovar internamente" (liberado pela Mugô), senão vê como cliente.
    - Os demais (ex.: designer, redatora): só as tarefas DELES (responsável ou quem criou), por completo; mandam para
      a aprovação interna, e aprovam só com "Aprovar internamente".
    """
    if await is_agency_user(authorization, cid):
        return {"client_view": False, "team": True, "only_user": None}
    from services.team_access import member_access
    uid = await require_user_id(authorization)
    access = await member_access(cid, uid)
    codes = set((access or {}).get("codes") or [])
    approve = "tasks.approve" in codes
    if "tasks.all" in codes:
        return {"client_view": not approve, "team": approve, "only_user": None}
    return {"client_view": False, "team": approve, "only_user": uid}


@router.get("/tasks")
async def crm_tasks(client_id: str, status: Optional[str] = None, limit: int = 200,
                    authorization: Optional[str] = Header(None)):
    cid = await require_client_read(client_id, authorization)
    scope = await _task_scope(authorization, cid)
    try:
        out = await studio_tasks.list_tasks(cid, status=status, limit=limit, client_view=scope["client_view"], only_user=scope["only_user"])
        return {**out, "scope": {"mine_only": bool(scope["only_user"]), "can_approve": scope["team"]}}
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
    scope = await _task_scope(authorization, cid)
    try:
        return {"task": await studio_tasks.create_task(cid, body.model_dump(exclude_unset=True), user_id=uid,
                                                       client_view=scope["client_view"], only_user=scope["only_user"])}
    except StudioError as exc:
        raise _http(exc) from None


@router.patch("/tasks/{task_id}")
async def crm_task_update(client_id: str, task_id: UUID, body: TaskInput, authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=TASK_MANAGERS)
    try:
        scope = await _task_scope(authorization, cid)
        return {"task": await studio_tasks.update_task(cid, str(task_id), body.model_dump(exclude_unset=True),
                                                       client_view=scope["client_view"], only_user=scope["only_user"])}
    except StudioError as exc:
        raise _http(exc) from None


@router.delete("/tasks/{task_id}")
async def crm_task_delete(client_id: str, task_id: UUID, authorization: Optional[str] = Header(None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=TASK_MANAGERS)
    try:
        scope = await _task_scope(authorization, cid)
        await studio_tasks.delete_task(cid, str(task_id), client_view=scope["client_view"], only_user=scope["only_user"])
        return {"ok": True}
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/assignees")
async def crm_assignees(client_id: str, authorization: Optional[str] = Header(None)):
    """Integrantes ativos da empresa para escolher o responsável (e para quem mandar o briefing)."""
    from services.team_admin import list_members
    cid = await require_client_read(client_id, authorization)
    try:
        members = (await list_members(cid)).get("items") or []
    except Exception as exc:  # noqa: BLE001 — sem a lista, a tela volta ao nome digitado
        print(f"[crm][assignees] client_id={cid} unavailable error_type={type(exc).__name__}")
        return {"available": False, "people": []}
    people = [{"user_id": m["user_id"], "name": m.get("name") or m.get("login") or "Sem nome"}
              for m in members if m.get("user_id") and m.get("status") == "active"]
    people.sort(key=lambda p: str(p["name"]).lower())
    return {"available": True, "people": people}


@router.get("/tasks/{task_id}/history")
async def crm_task_history(client_id: str, task_id: UUID, authorization: Optional[str] = Header(None)):
    cid = await require_client_read(client_id, authorization)
    try:
        scope = await _task_scope(authorization, cid)
        return {"events": await studio_tasks.task_history(cid, str(task_id), client_view=scope["client_view"], only_user=scope["only_user"])}
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/tasks/{task_id}/approval")
async def crm_task_approval(client_id: str, task_id: UUID, body: TaskApproval, authorization: Optional[str] = Header(None)):
    """Aprovação interna (equipe Mugô) e do cliente (qualquer pessoa da empresa, só tarefa visível a ela)."""
    from services.auth import get_user_from_bearer
    cid = await require_client_role(client_id, authorization, allowed_roles=TASK_APPROVERS)
    user = await get_user_from_bearer(authorization) or {}
    scope = await _task_scope(authorization, cid)
    name = str(user.get("email") or "").split("@")[0] or ("Equipe Mugô" if scope["team"] else "Cliente")
    try:
        return await studio_tasks.approval_action(cid, str(task_id), body.action, comment=body.comment, user_id=str(user.get("id") or ""),
                                                  actor_name=name, is_agency=scope["team"], internal_comment=body.internal,
                                                  only_user=scope["only_user"])
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
