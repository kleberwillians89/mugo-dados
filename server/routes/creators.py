from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from services import creators
from services.ig_supabase import sb_delete, sb_get_one_by, sb_insert, sb_update
from services.tenant import require_client_role, require_user_id

# Creator Intelligence é operação da agência: cliente final não pesquisa nem gasta créditos.
AGENCY_ONLY = ("agency_admin",)
router = APIRouter(prefix="/api/clients/{client_id}/creators", tags=["creators"])
Network = Literal["instagram", "youtube", "tiktok"]
ItemStatus = Literal["candidate", "contacted", "approved", "rejected"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LookupInput(Strict):
    network: Network
    handle: str = Field(min_length=1, max_length=200)
    force: bool = False


class SearchInput(Strict):
    network: Network
    query: str = Field(min_length=1, max_length=80)
    limit: int = Field(default=10, ge=1, le=25)


class CompareInput(Strict):
    creator_ids: list[UUID] = Field(min_length=2, max_length=creators.MAX_COMPARE)


class ShortlistInput(Strict):
    name: str = Field(min_length=1, max_length=120)
    campaign_type: Literal["ugc", "influencer"] = "influencer"
    notes: Optional[str] = Field(default=None, max_length=2000)


class ShortlistItemInput(Strict):
    creator_id: UUID
    notes: Optional[str] = Field(default=None, max_length=2000)


class ShortlistItemPatch(Strict):
    status: Optional[ItemStatus] = None
    notes: Optional[str] = Field(default=None, max_length=2000)


async def agency(client_id: str, authorization: Optional[str]) -> str:
    return await require_client_role(client_id, authorization, allowed_roles=AGENCY_ONLY)


def _invalid(exc: ValueError) -> HTTPException:
    return HTTPException(422, str(exc))


@router.get("")
async def read_creators(
    client_id: str,
    network: Optional[Network] = None,
    q: Optional[str] = Query(default=None, max_length=60),
    min_followers: Optional[int] = Query(default=None, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    authorization: Optional[str] = Header(default=None),
):
    await agency(client_id, authorization)
    return {"creators": await creators.list_creators(network=network, q=q, min_followers=min_followers, limit=limit, offset=offset)}


@router.post("/lookup")
async def lookup_creator(client_id: str, body: LookupInput, authorization: Optional[str] = Header(default=None)):
    cid = await agency(client_id, authorization)
    try:
        return await creators.lookup(cid, body.network, body.handle, force=body.force)
    except ValueError as exc:
        raise _invalid(exc) from None


@router.post("/search")
async def search_creators(client_id: str, body: SearchInput, authorization: Optional[str] = Header(default=None)):
    cid = await agency(client_id, authorization)
    try:
        return await creators.search(cid, body.network, body.query, body.limit)
    except ValueError as exc:
        raise _invalid(exc) from None


@router.post("/compare")
async def compare_creators(client_id: str, body: CompareInput, authorization: Optional[str] = Header(default=None)):
    await agency(client_id, authorization)
    try:
        return {"creators": await creators.compare([str(i) for i in body.creator_ids])}
    except ValueError as exc:
        raise _invalid(exc) from None


@router.get("/usage")
async def read_usage(client_id: str, authorization: Optional[str] = Header(default=None)):
    cid = await agency(client_id, authorization)
    return await creators.usage_summary(cid)


@router.get("/shortlists")
async def read_shortlists(client_id: str, authorization: Optional[str] = Header(default=None)):
    cid = await agency(client_id, authorization)
    return {"shortlists": await creators.list_shortlists(cid)}


@router.post("/shortlists", status_code=201)
async def create_shortlist(client_id: str, body: ShortlistInput, authorization: Optional[str] = Header(default=None)):
    cid = await agency(client_id, authorization)
    uid = await require_user_id(authorization)
    return await sb_insert("creator_shortlists", {**body.model_dump(), "client_id": cid, "created_by": uid})


@router.get("/shortlists/{shortlist_id}")
async def read_shortlist(client_id: str, shortlist_id: UUID, authorization: Optional[str] = Header(default=None)):
    cid = await agency(client_id, authorization)
    shortlist = await creators.get_shortlist(cid, str(shortlist_id))
    if not shortlist:
        raise HTTPException(404, "Shortlist não encontrada.")
    return shortlist


@router.delete("/shortlists/{shortlist_id}", status_code=204)
async def delete_shortlist(client_id: str, shortlist_id: UUID, authorization: Optional[str] = Header(default=None)):
    cid = await agency(client_id, authorization)
    deleted = await sb_delete("creator_shortlists", filters={"id": f"eq.{shortlist_id}", "client_id": f"eq.{cid}"})
    if not deleted:
        raise HTTPException(404, "Shortlist não encontrada.")


@router.post("/shortlists/{shortlist_id}/items", status_code=201)
async def add_shortlist_item(client_id: str, shortlist_id: UUID, body: ShortlistItemInput, authorization: Optional[str] = Header(default=None)):
    cid = await agency(client_id, authorization)
    uid = await require_user_id(authorization)
    if not await creators.get_shortlist(cid, str(shortlist_id)):
        raise HTTPException(404, "Shortlist não encontrada.")
    if not await sb_get_one_by("creators", filters={"id": f"eq.{body.creator_id}"}, select="id"):
        raise HTTPException(404, "Criador não encontrado.")
    existing = await sb_get_one_by("creator_shortlist_items", filters={"shortlist_id": f"eq.{shortlist_id}", "creator_id": f"eq.{body.creator_id}", "client_id": f"eq.{cid}"})
    if existing:
        return existing
    return await sb_insert("creator_shortlist_items", {
        "shortlist_id": str(shortlist_id), "client_id": cid, "creator_id": str(body.creator_id),
        "notes": body.notes, "created_by": uid,
    })


@router.patch("/shortlists/{shortlist_id}/items/{item_id}")
async def update_shortlist_item(client_id: str, shortlist_id: UUID, item_id: UUID, body: ShortlistItemPatch, authorization: Optional[str] = Header(default=None)):
    cid = await agency(client_id, authorization)
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(422, "Nada para atualizar.")
    rows = await sb_update("creator_shortlist_items", filters={"id": f"eq.{item_id}", "shortlist_id": f"eq.{shortlist_id}", "client_id": f"eq.{cid}"}, patch=patch)
    if not rows:
        raise HTTPException(404, "Item não encontrado.")
    return rows[0]


@router.delete("/shortlists/{shortlist_id}/items/{item_id}", status_code=204)
async def delete_shortlist_item(client_id: str, shortlist_id: UUID, item_id: UUID, authorization: Optional[str] = Header(default=None)):
    cid = await agency(client_id, authorization)
    deleted = await sb_delete("creator_shortlist_items", filters={"id": f"eq.{item_id}", "shortlist_id": f"eq.{shortlist_id}", "client_id": f"eq.{cid}"})
    if not deleted:
        raise HTTPException(404, "Item não encontrado.")


# Rotas com parâmetro por último: /usage e /shortlists não podem cair aqui.
@router.get("/{creator_id}")
async def read_creator(client_id: str, creator_id: UUID, authorization: Optional[str] = Header(default=None)):
    await agency(client_id, authorization)
    creator = await creators.get_creator(str(creator_id))
    if not creator:
        raise HTTPException(404, "Criador não encontrado.")
    return creator


@router.post("/{creator_id}/refresh")
async def refresh_creator(client_id: str, creator_id: UUID, authorization: Optional[str] = Header(default=None)):
    cid = await agency(client_id, authorization)
    return await creators.refresh(cid, str(creator_id))
