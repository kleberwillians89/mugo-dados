"""Kanban → produção: seletor de tarefas, leitor de contexto e criação ligada à tarefa.

- ``GET  /api/clients/{id}/crm/work/tasks`` e ``/crm/work/tasks/{task_id}``: ler (guarda do módulo Tarefas, "crm").
  A tarefa segue a MESMA regra do quadro (_task_scope): quem só vê as dele não lê o briefing das outras.
- ``POST /api/clients/{id}/crm/work/tasks/{task_id}/email``: rascunho no E-mail Marketing. Exige quem cria campanha
  de e-mail (agency_admin/client_admin, a regra do próprio E-mail Marketing). Ler a tarefa não dá esse direito.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from services import email_from_task, task_context
from services.studio_calendar import StudioError
from services.tenant import require_client_read, require_client_role, require_user_id

router = APIRouter(prefix="/api/clients/{client_id}/crm/work", tags=["kanban-work"])
EMAIL_WRITERS = ("agency_admin", "client_admin")
ERRORS = {"TASK_NOT_FOUND": 404, "MODULE_INVALID": 400, "MODE_INVALID": 400, "EMAIL_OFFER_OVER_LIMIT": 422,
          "AI_TENANT_LEAK": 422}


def _http(exc: StudioError) -> HTTPException:
    detail = str(exc) if str(exc) != exc.code else "Não foi possível agora. Tente de novo."
    return HTTPException(status_code=ERRORS.get(exc.code, 502), detail=detail)


class EmailFromTask(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    deliverable: str = Field(default="", max_length=160)
    mode: str = Field(default="ia", max_length=10)
    new_version: bool = False
    instruction: str = Field(default="", max_length=600)


async def _scope(client_id: str, authorization: Optional[str]):
    from routes.crm import _task_scope
    cid = await require_client_read(client_id, authorization)
    return cid, await _task_scope(authorization, cid)


@router.get("/tasks")
async def work_tasks(client_id: str, q: Optional[str] = Query(default=None, max_length=80),
                     authorization: Optional[str] = Header(None)):
    cid, scope = await _scope(client_id, authorization)
    try:
        return await task_context.list_pickable(cid, scope, q=q)
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/tasks/{task_id}")
async def work_task_context(client_id: str, task_id: str, module: Optional[str] = Query(default=None, max_length=30),
                            authorization: Optional[str] = Header(None)):
    cid, scope = await _scope(client_id, authorization)
    if module and module not in task_context.MODULES:
        raise HTTPException(status_code=400, detail="Módulo inválido.")
    try:
        ctx = await task_context.task_context(cid, task_id, scope, module=module)
        if module == "email_marketing":
            ctx["existing"] = await email_from_task.existing_campaigns(cid, ctx["task"]["id"])
        return ctx
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/tasks/{task_id}/email", status_code=201)
async def work_task_email(client_id: str, task_id: str, body: EmailFromTask, authorization: Optional[str] = Header(None)):
    cid, scope = await _scope(client_id, authorization)
    await require_client_role(cid, authorization, allowed_roles=EMAIL_WRITERS)
    uid = await require_user_id(authorization)
    try:
        return await email_from_task.create_from_task(cid, task_id, scope, user_id=uid, deliverable=body.deliverable,
                                                      mode=body.mode, new_version=body.new_version, instruction=body.instruction)
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/tasks/{task_id}/produced")
async def work_task_produced(client_id: str, task_id: str, authorization: Optional[str] = Header(None)):
    """"Ir para o job": o que foi produzido a partir da tarefa, cada item com o lugar para abrir."""
    from services import task_produced
    cid, scope = await _scope(client_id, authorization)
    try:
        return await task_produced.produced(cid, task_id, scope)
    except StudioError as exc:
        raise _http(exc) from None


class LinkInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    module: str = Field(max_length=30)
    record_id: str = Field(min_length=1, max_length=80)
    deliverable: str = Field(default="", max_length=160)


@router.post("/tasks/{task_id}/links", status_code=201)
async def work_task_link(client_id: str, task_id: str, body: LinkInput, authorization: Optional[str] = Header(None)):
    """Grava na tarefa o que foi criado em outro módulo a partir dela (matriz do Social Media, post do Calendário…)."""
    from services import redacao_from_task
    cid, scope = await _scope(client_id, authorization)
    uid = await require_user_id(authorization)
    try:
        return await redacao_from_task.link_to_task(cid, task_id, scope, module=body.module, record_id=body.record_id,
                                                    deliverable=body.deliverable, user_id=uid)
    except StudioError as exc:
        raise _http(exc) from None
