from datetime import date
from uuid import UUID
from typing import Literal
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from services.tenant import require_client_read, require_client_role, require_user_id
from typing import Any, Optional
from services.ig_supabase import sb_insert, sb_select, sb_update, sb_delete
from services.goals import DEFAULT_DIRECTION, goal_drivers, goal_history, list_goals, record_history, suggest_goal

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
