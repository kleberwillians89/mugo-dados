"""Mugô Studio: perfil de marca e calendário editorial.

Leitura: qualquer membro da empresa. Escrita, geração por IA e aprovação:
agency_admin e client_admin (mesma regra das metas). A empresa vem sempre da
membership resolvida no backend; o client_id da URL é só um pedido.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from services.studio_calendar import (
    StudioError, create_item, delete_item, generate_month, list_items, load_profile,
    parse_month, save_profile, update_item,
)
from services.tenant import require_client_read, require_client_role, require_user_id

router = APIRouter(prefix="/api/clients/{client_id}/studio", tags=["studio"])

Format = Literal["reels", "carrossel", "imagem", "stories", "video"]
Status = Literal["rascunho", "em_revisao", "aprovado", "rejeitado"]

ERRORS = {
    "MONTH_INVALID": (422, "Use o mês no formato AAAA-MM."),
    "MONTH_OUT_OF_RANGE": (422, "Gere do mês atual até 3 meses à frente."),
    "MONTH_PAST": (422, "Esse mês já passou; escolha o mês atual ou um próximo."),
    "NO_SLOTS": (409, "Não sobrou dia livre neste mês para novas pautas."),
    "AI_GENERATION_COOLDOWN": (429, "Um calendário acabou de ser gerado. Aguarde um instante."),
    "AI_PROVIDER_NOT_CONFIGURED": (503, "O provedor de IA ainda não está configurado no backend."),
    "AI_PROVIDER_TIMEOUT": (502, "A IA demorou mais que o esperado. Tente novamente."),
    "AI_PROVIDER_ERROR": (502, "A IA não respondeu agora. Tente novamente."),
    "AI_INVALID_OUTPUT": (502, "A IA não devolveu pautas válidas. Tente novamente."),
    "ITEM_NOT_FOUND": (404, "Pauta não encontrada nesta empresa."),
    "STATUS_INVALID": (422, "Status inválido."),
    "FORMAT_INVALID": (422, "Formato inválido."),
    "EMPTY_PATCH": (422, "Nada para alterar."),
    "CREATE_FAILED": (502, "Não foi possível criar a pauta."),
}


def _http(exc: StudioError) -> HTTPException:
    status, detail = ERRORS.get(exc.code, (502, "Não foi possível concluir agora."))
    headers = {"Retry-After": "90"} if status == 429 else None
    return HTTPException(status_code=status, detail=detail, headers=headers)


WRITERS = ("agency_admin", "client_admin")


class Pillar(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    weight: int = Field(default=0, ge=0, le=100)
    description: str = Field(default="", max_length=400)


class CustomDate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    date: str = Field(pattern=r"^(\d{4}-)?\d{2}-\d{2}$")
    label: str = Field(min_length=1, max_length=80)


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    tone_of_voice: str = Field(default="", max_length=1000)
    personality: str = Field(default="", max_length=500)
    audience: str = Field(default="", max_length=1000)
    pillars: List[Pillar] = Field(default_factory=list, max_length=8)
    keywords_use: List[str] = Field(default_factory=list, max_length=30)
    keywords_avoid: List[str] = Field(default_factory=list, max_length=30)
    hashtags: List[str] = Field(default_factory=list, max_length=30)
    restrictions: str = Field(default="", max_length=1500)
    posts_per_week: int = Field(default=3, ge=1, le=14)
    formats_enabled: List[Format] = Field(default_factory=lambda: ["reels", "carrossel", "imagem"], max_length=5)
    custom_dates: List[CustomDate] = Field(default_factory=list, max_length=30)


class GenerateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: str = Field(pattern=r"^\d{4}-\d{2}$")


class ItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    scheduled_at: datetime
    format: Format
    title: str = Field(min_length=1, max_length=200)
    pillar: Optional[str] = Field(default=None, max_length=120)
    hook: Optional[str] = Field(default=None, max_length=400)
    caption_draft: Optional[str] = Field(default=None, max_length=4000)
    rationale: Optional[str] = Field(default=None, max_length=1200)


class ItemPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    scheduled_at: Optional[datetime] = None
    format: Optional[Format] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    pillar: Optional[str] = Field(default=None, max_length=120)
    hook: Optional[str] = Field(default=None, max_length=400)
    caption_draft: Optional[str] = Field(default=None, max_length=4000)
    rationale: Optional[str] = Field(default=None, max_length=1200)
    status: Optional[Status] = None
    review_note: Optional[str] = Field(default=None, max_length=1000)


@router.get("/brand-profile")
async def read_profile(client_id: str, authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id, authorization)
    return await load_profile(cid)


@router.put("/brand-profile")
async def write_profile(client_id: str, body: ProfileInput, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    return await save_profile(cid, body.model_dump(mode="json"), user_id=uid)


@router.get("/calendar")
async def read_calendar(client_id: str, month: str, authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id, authorization)
    try:
        target = parse_month(month)
    except StudioError as exc:
        raise _http(exc) from None
    return {"month": target.isoformat(), "items": await list_items(cid, target)}


@router.post("/calendar/generate")
async def generate_calendar(client_id: str, body: GenerateInput, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    try:
        return await generate_month(cid, body.month, user_id=uid)
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/calendar/items", status_code=201)
async def add_item(client_id: str, body: ItemCreate, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    try:
        return {"ok": True, "item": await create_item(cid, body.model_dump(mode="json"), user_id=uid)}
    except StudioError as exc:
        raise _http(exc) from None


@router.patch("/calendar/items/{item_id}")
async def edit_item(client_id: str, item_id: UUID, body: ItemPatch, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    uid = await require_user_id(authorization)
    try:
        item = await update_item(cid, str(item_id), body.model_dump(mode="json", exclude_none=True), user_id=uid)
    except StudioError as exc:
        raise _http(exc) from None
    return {"ok": True, "item": item}


@router.delete("/calendar/items/{item_id}")
async def remove_item(client_id: str, item_id: UUID, authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        await delete_item(cid, str(item_id))
    except StudioError as exc:
        raise _http(exc) from None
    return {"ok": True}
