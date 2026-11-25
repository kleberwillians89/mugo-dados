from datetime import date
from uuid import UUID
from typing import Literal
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from services.tenant import require_client_read, require_client_role, require_user_id
from typing import Any, Optional
from services.ig_supabase import sb_insert, sb_select, sb_update, sb_delete
from services.goals import DEFAULT_DIRECTION, evaluate_goal, goal_drivers, goal_history, list_goals, record_history, resolve_goal_actual, suggest_goal
from services.studio_calendar import StudioError

router=APIRouter(prefix="/api/clients/{client_id}/goals", tags=["goals"])
Metric=Literal["revenue","orders","average_ticket","ad_spend","roas","conversions","followers","reach","impressions","engagement",
               "cpa_meta","google_conversions","sessions","conversion_rate","followers_gained"]
class GoalInput(BaseModel):
    model_config=ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    metric: Metric
    label: str = Field(min_length=1,max_length=100)
    target_value: float = Field(gt=0,le=1e15)
    period_start: date
    period_end: date
    direction: Optional[Literal["min","max"]] = None
    is_primary: bool = False
    parent_goal_id: Optional[UUID] = None
    relation: Optional[str] = Field(default=None, max_length=160)
    owner_user_id: Optional[str] = Field(default=None, max_length=80)
    suggestion: Optional[dict[str, Any]] = None
    @model_validator(mode="after")
    def valid_period(self):
        if self.period_end < self.period_start or (self.period_end-self.period_start).days > 365:
            raise ValueError("Use um período válido de até 366 dias.")
        return self
    def payload(self):
        # Campos novos só vão quando usados: metas simples continuam gravando antes da migração 000150.
        data = self.model_dump(mode="json")
        direction = data.pop("direction") or DEFAULT_DIRECTION.get(self.metric, "min")
        if direction != "min": data["direction"] = direction
        if not data.get("is_primary"): data.pop("is_primary", None)
        for key in ("parent_goal_id","relation","owner_user_id","suggestion"):
            if data.get(key) in (None, ""): data.pop(key, None)
        if data.get("suggestion") is not None and len(str(data["suggestion"])) > 20000:
            raise ValueError("Premissas grandes demais.")
        return data

@router.get("")
async def read_goals(client_id:str, start:date|None=None,end:date|None=None,authorization:str|None=Header(default=None),include_actuals:bool=True):
    cid=await require_client_read(client_id,authorization)
    if start and end and end < start: raise HTTPException(422,"Período inválido.")
    try:
        args = (cid,start.isoformat() if start else None,end.isoformat() if end else None)
        return await list_goals(*args) if include_actuals else await list_goals(*args, include_actuals=False)
    except Exception: raise HTTPException(503,"Não foi possível carregar as metas. Tente novamente.") from None

async def writer(cid,auth):
    return await require_client_role(cid,auth,allowed_roles=("agency_admin","client_admin"))

async def _own_goal(cid, goal_id):
    rows = await sb_select("client_goals", filters={"client_id": f"eq.{cid}", "id": f"eq.{goal_id}"}, limit=1)
    if not rows or rows[0].get("client_id") != cid: raise HTTPException(404,"Meta não encontrada nesta empresa.")
    return rows[0]

async def _check_links(cid, body):
    # Submeta só aponta para meta da MESMA empresa; responsável precisa ser membro da empresa.
    if body.parent_goal_id: await _own_goal(cid, body.parent_goal_id)
    if body.owner_user_id:
        members = await sb_select("client_memberships", select="client_id,user_id", filters={"client_id": f"eq.{cid}", "user_id": f"eq.{body.owner_user_id}"}, limit=1)
        if not members: raise HTTPException(422,"O responsável precisa ter acesso a esta empresa.")

async def _single_primary(cid, keep_id):
    try: await sb_update("client_goals", filters={"client_id": f"eq.{cid}", "is_primary": "eq.true", "id": f"neq.{keep_id}"}, patch={"is_primary": False}, returning="minimal")
    except Exception: pass

@router.get("/suggest")
async def suggest(client_id:str, metric:Metric, start:date, end:date, authorization:str|None=Header(default=None)):
    """Cenários conservador, de referência e agressivo com premissas. Só sugere: nada é gravado."""
    cid=await require_client_read(client_id,authorization)
    if end < start or (end-start).days > 365: raise HTTPException(422,"Período inválido.")
    try: return await suggest_goal(cid, metric, start.isoformat(), end.isoformat())
    except Exception: raise HTTPException(503,"Não foi possível ler o histórico agora.") from None

@router.get("/{goal_id}/drivers")
async def drivers(client_id:str, goal_id:UUID, authorization:str|None=Header(default=None)):
    cid=await require_client_read(client_id,authorization)
    return await goal_drivers(cid, await _own_goal(cid, goal_id))

@router.get("/{goal_id}/history")
async def history(client_id:str, goal_id:UUID, authorization:str|None=Header(default=None)):
    cid=await require_client_read(client_id,authorization)
    return await goal_history(cid, str(goal_id))

@router.post("",status_code=201)
async def create_goal(client_id:str,body:GoalInput,authorization:str|None=Header(default=None)):
    cid=await writer(client_id,authorization)
    uid=await require_user_id(authorization)
    await _check_links(cid, body)
    row=await sb_insert("client_goals",{**body.payload(),"client_id":cid,"created_by":uid})
    if not row: raise HTTPException(502,"Não foi possível criar a meta.")
    if body.is_primary: await _single_primary(cid, row["id"])
    await record_history(cid, row["id"], "criada", None, row, uid)
    return {"ok":True,"goal":row}

@router.put("/{goal_id}")
async def edit_goal(client_id:str,goal_id:UUID,body:GoalInput,authorization:str|None=Header(default=None)):
    cid=await writer(client_id,authorization)
    uid=await require_user_id(authorization)
    before=await _own_goal(cid, goal_id)
    await _check_links(cid, body)
    if body.parent_goal_id and str(body.parent_goal_id) == str(goal_id): raise HTTPException(422,"Uma meta não pode ser submeta dela mesma.")
    patch=body.payload()
    if "direction" not in patch and before.get("direction") not in (None, "min"): patch["direction"]="min"
    if not body.is_primary and before.get("is_primary"): patch["is_primary"]=False
    rows=await sb_update("client_goals",filters={"client_id":f"eq.{cid}","id":f"eq.{goal_id}"},patch=patch)
    if not rows: raise HTTPException(404,"Meta não encontrada nesta empresa.")
    if body.is_primary: await _single_primary(cid, str(goal_id))
    await record_history(cid, str(goal_id), "editada", before, rows[0], uid)
    return {"ok":True,"goal":rows[0]}

@router.delete("/{goal_id}")
async def delete_goal(client_id:str,goal_id:UUID,authorization:str|None=Header(default=None)):
    cid=await writer(client_id,authorization)
    uid=await require_user_id(authorization)
    before=await _own_goal(cid, goal_id)
    rows=await sb_delete("client_goals",filters={"client_id":f"eq.{cid}","id":f"eq.{goal_id}"})
    if not rows: raise HTTPException(404,"Meta não encontrada nesta empresa.")
    await record_history(cid, str(goal_id), "excluida", before, None, uid)
    return {"ok":True}


# ---------------------------------------------------------------- metas conectadas à operação

async def _evaluated(cid, goal_id):
    goal = await _own_goal(cid, goal_id)
    try: actual = await resolve_goal_actual(cid, goal["metric"], goal["period_start"], goal["period_end"])
    except Exception: actual = {"available": False, "actual": None, "origin": None, "reason": "A fonte persistida não pôde ser lida agora."}
    return evaluate_goal(goal, actual)

class RecommendInput(BaseModel):
    model_config=ConfigDict(extra="forbid", str_strip_whitespace=True)
    constraints: Optional[str] = Field(default=None, max_length=1000)

class TaskFromRecommendation(BaseModel):
    model_config=ConfigDict(extra="forbid")
    index: int = Field(ge=0, le=9)
    assignee_user_ids: list[str] = Field(default_factory=list, max_length=10)
    due_date: Optional[date] = None

@router.get("/{goal_id}/diagnosis")
async def goal_diagnosis(client_id:str, goal_id:UUID, authorization:str|None=Header(default=None)):
    """Fatos e, quando sustentado, uma hipótese sobre o desvio (sem IA, sem afirmar causa)."""
    from services.goal_ops import diagnosis
    cid=await require_client_read(client_id,authorization)
    return await diagnosis(cid, await _own_goal(cid, goal_id))

@router.get("/{goal_id}/recommendations")
async def goal_recommendations(client_id:str, goal_id:UUID, authorization:str|None=Header(default=None)):
    from services.goal_ops import latest_recommendations
    cid=await require_client_read(client_id,authorization)
    await _own_goal(cid, goal_id)
    return {"recommendations": await latest_recommendations(cid, str(goal_id))}

@router.post("/{goal_id}/recommendations")
async def goal_recommend(client_id:str, goal_id:UUID, body:RecommendInput, authorization:str|None=Header(default=None)):
    """A IA analisa e recomenda (no clique); nada é executado. Fica registrado para rastrear a decisão."""
    from services.goal_ops import recommend
    cid=await require_client_read(client_id,authorization)
    uid=await require_user_id(authorization)
    try: return await recommend(cid, await _evaluated(cid, goal_id), body.constraints, user_id=uid)
    except StudioError as exc: raise HTTPException(503 if exc.code.startswith("AI_") else 422, str(exc) if str(exc) != exc.code else "A IA não conseguiu analisar agora.") from None

@router.post("/{goal_id}/recommendations/{rec_id}/task", status_code=201)
async def goal_recommendation_task(client_id:str, goal_id:UUID, rec_id:UUID, body:TaskFromRecommendation, authorization:str|None=Header(default=None)):
    """Item aprovado pela pessoa vira tarefa no Kanban (mesmo serviço e mesmas permissões de Tarefas). Não duplica."""
    from routes.crm import TASK_MANAGERS, _task_scope
    from services.goal_ops import to_task
    cid=await require_client_role(client_id,authorization,allowed_roles=TASK_MANAGERS)
    uid=await require_user_id(authorization)
    scope=await _task_scope(authorization, cid)
    try:
        return await to_task(cid, await _own_goal(cid, goal_id), str(rec_id), body.index, assignee_user_ids=body.assignee_user_ids,
                             due_date=body.due_date.isoformat() if body.due_date else None, user_id=uid,
                             client_view=scope["client_view"], only_user=scope["only_user"])
    except StudioError as exc:
        raise HTTPException(404 if exc.code == "RECOMMENDATION_NOT_FOUND" else 422, str(exc) if str(exc) != exc.code else "Não foi possível criar a tarefa.") from None


@router.get("/{goal_id}/evaluation")
async def evaluation(client_id:str, goal_id:UUID, authorization:str|None=Header(default=None)):
    """Alvo original x alterações, resultado, desvio, premissas e tarefas criadas (para comparar períodos)."""
    from services.goals import goal_evaluation
    cid=await require_client_read(client_id,authorization)
    goal=await _own_goal(cid, goal_id)
    return await goal_evaluation(cid, goal, await _evaluated(cid, goal_id))
