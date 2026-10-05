from datetime import date
from uuid import UUID
from typing import Literal
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from services.tenant import require_client_read, require_client_role, require_user_id
from services.ig_supabase import sb_insert, sb_update, sb_delete
from services.goals import list_goals

router=APIRouter(prefix="/api/clients/{client_id}/goals", tags=["goals"])
Metric=Literal["revenue","orders","average_ticket","ad_spend","roas","conversions","followers","reach","impressions","engagement"]
class GoalInput(BaseModel):
    model_config=ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    metric: Metric
    label: str = Field(min_length=1,max_length=100)
    target_value: float = Field(gt=0,le=1e15)
    period_start: date
    period_end: date
    @model_validator(mode="after")
    def valid_period(self):
        if self.period_end < self.period_start or (self.period_end-self.period_start).days > 365:
            raise ValueError("Use um período válido de até 366 dias.")
        return self
    def payload(self):
        return self.model_dump(mode="json")

@router.get("")
async def read_goals(client_id:str, start:date|None=None,end:date|None=None,authorization:str|None=Header(default=None)):
    cid=await require_client_read(client_id,authorization)
    if start and end and end < start: raise HTTPException(422,"Período inválido.")
    try: return await list_goals(cid,start.isoformat() if start else None,end.isoformat() if end else None)
    except Exception: raise HTTPException(503,"Não foi possível carregar as metas. Tente novamente.") from None

async def writer(cid,auth):
    return await require_client_role(cid,auth,allowed_roles=("agency_admin","client_admin"))

@router.post("",status_code=201)
async def create_goal(client_id:str,body:GoalInput,authorization:str|None=Header(default=None)):
    cid=await writer(client_id,authorization)
    uid=await require_user_id(authorization)
    row=await sb_insert("client_goals",{**body.payload(),"client_id":cid,"created_by":uid})
    if not row: raise HTTPException(502,"Não foi possível criar a meta.")
    return {"ok":True,"goal":row}

@router.put("/{goal_id}")
async def edit_goal(client_id:str,goal_id:UUID,body:GoalInput,authorization:str|None=Header(default=None)):
    cid=await writer(client_id,authorization)
    rows=await sb_update("client_goals",filters={"client_id":f"eq.{cid}","id":f"eq.{goal_id}"},patch=body.payload())
    if not rows: raise HTTPException(404,"Meta não encontrada nesta empresa.")
    return {"ok":True,"goal":rows[0]}

@router.delete("/{goal_id}")
async def delete_goal(client_id:str,goal_id:UUID,authorization:str|None=Header(default=None)):
    cid=await writer(client_id,authorization)
    rows=await sb_delete("client_goals",filters={"client_id":f"eq.{cid}","id":f"eq.{goal_id}"})
    if not rows: raise HTTPException(404,"Meta não encontrada nesta empresa.")
    return {"ok":True}
