"""Mídia On → Meta Ads: rascunhos de campanha e publicação PAUSADA. Só a equipe Mugô (mexe com verba)."""
from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from services import meta_ad_publisher as pub
from services.ig_supabase import sb_select
from services.studio_calendar import StudioError
from services.tenant import require_client_read, require_client_role, require_user_id

router = APIRouter(prefix="/api/clients/{client_id}/studio/ads", tags=["meta-ads-publish"])
AGENCY = ("agency_admin",)

ERRORS = {
    "AD_MIGRATION_PENDING": (503, "Falta aplicar a migração 000091 (campanhas do Mídia On) no banco."),
    "AD_DRAFT_NOT_FOUND": (404, "Campanha não encontrada."),
    "AD_OBJECTIVE_INVALID": (422, "Objetivo inválido."),
    "AD_SAVE_FAILED": (502, "Não foi possível salvar a campanha. Tente de novo."),
    "AD_ALREADY_PUBLISHED": (409, "Esta campanha já foi criada no Meta Ads."),
    "AD_ACCOUNT_MISSING": (409, "Escolha a conta de anúncios do Meta desta empresa em Integrações."),
    "AD_PERMISSION_MISSING": (409, "A conexão do Meta não tem permissão para criar anúncios. Reconecte o Meta em Integrações para liberar."),
    "AD_PAGE_MISSING": (409, "Não achei a página do Facebook ligada a esta empresa. Reconecte o Instagram/Facebook em Integrações."),
    "AD_PIXEL_MISSING": (409, "A conta de anúncios não tem pixel. Use o objetivo Tráfego ou configure o pixel no Meta."),
    "AD_IMAGE_UNREACHABLE": (422, "Não consegui baixar a imagem do anúncio. Use um post do Calendário com arte ou um link direto da imagem."),
    "AD_NOT_PUBLISHED_YET": (409, "Crie a campanha no Meta antes. Enquanto é rascunho, use o formato Vários anúncios no Estúdio de criativos."),
    "AD_ACCOUNT_CHANGED": (409, "A conta de anúncios mudou desde a campanha original. Use Duplicar campanha."),
    "AD_ALREADY_IMPORTED": (409, "Esta campanha já está na Mídia On."),
    "AD_CONFIRM_BUDGET": (409, "Confirme a verba diária para ativar a campanha."),
    "AD_AUDIENCE_INVALID": (422, "Público inválido."),
    "AI_INVALID_OUTPUT": (502, "A IA não devolveu a campanha. Tente de novo."),
    "AI_RATE_LIMIT": (429, "Muitas gerações seguidas. Espere um pouco e tente de novo."),
}
PASS_MESSAGE = {"AD_META_REJECTED", "AD_NOT_READY", "AD_AUDIENCE_INVALID"}


def _http(exc: StudioError) -> HTTPException:
    if exc.code in PASS_MESSAGE or (exc.code == "AD_PERMISSION_MISSING" and str(exc) != exc.code):
        prefix = "O Meta recusou: " if exc.code == "AD_META_REJECTED" else ""
        return HTTPException(status_code=422, detail=f"{prefix}{exc}")
    status, detail = ERRORS.get(exc.code, (502, "Não foi possível concluir agora."))
    return HTTPException(status_code=status, detail=detail)


class GenerateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    objective: str = Field(default="trafego", max_length=20)
    days_left: int = Field(default=14, ge=1, le=62)
    campaign: Dict[str, Any] = Field(default_factory=dict)


class DraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: Dict[str, Any]


@router.get("")
async def read_drafts(client_id: str, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    try:
        return {"drafts": await pub.list_drafts(cid), "objectives": {k: v["label"] for k, v in pub.OBJECTIVES.items()}, "ctas": pub.CTAS}
    except StudioError as exc:
        raise _http(exc) from None


class NewAudienceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern=r"^(instagram|facebook|site|compradores|semelhante|lista)$")
    name: Optional[str] = Field(default=None, max_length=120)
    event: Optional[str] = Field(default=None, max_length=30)
    days: Optional[int] = Field(default=None, ge=1, le=730)
    url_contains: Optional[str] = Field(default=None, max_length=200)
    origin_audience_id: Optional[str] = Field(default=None, max_length=30)
    ratio: Optional[int] = Field(default=None, ge=1, le=10)


@router.post("/audiences", status_code=201)
async def create_audience(client_id: str, body: NewAudienceInput, authorization: Optional[str] = Header(default=None)):
    """Cria um público na conta de anúncios (engajamento da marca, site, compradores, semelhante ou lista)."""
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    try:
        return await pub.create_account_audience(cid, body.model_dump(exclude_none=True))
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/audiences")
async def read_audiences(client_id: str, authorization: Optional[str] = Header(default=None)):
    """Públicos que já existem na conta de anúncios do cliente (salvos, personalizados e semelhantes)."""
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    try:
        return await pub.list_account_audiences(cid)
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/preflight")
async def account_publication_preflight(client_id: str,
                                         objective: str = Query(default="leads", max_length=20),
                                         authorization: Optional[str] = Header(default=None)):
    """Check the current tenant's Meta publishing prerequisites without creating an ad."""
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    try:
        return await pub.publication_preflight(cid, objective)
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/instagram-posts")
async def read_instagram_posts(client_id: str, authorization: Optional[str] = Header(default=None)):
    """Read synchronized Instagram media of the selected tenant (never global media)."""
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    rows = await sb_select(
        "ig_media",
        select="media_id,media_type,media_product_type,caption,permalink,timestamp,thumb_url,media_url,thumbnail_url",
        filters={"client_id": f"eq.{cid}"},
        order="timestamp.desc",
        limit=120,
    )
    posts = []
    for row in rows:
        kind = str(row.get("media_type") or "")
        cover = str(row.get("thumb_url") or row.get("thumbnail_url") or "").strip()
        original = str(row.get("media_url") or "").strip()
        photo_url = original if kind == "IMAGE" else ""
        if kind == "CAROUSEL_ALBUM":
            # Selecting its cover does not publish an actual carousel ad.
            photo_url = cover
        if not cover:
            cover = photo_url
        if not cover.startswith("https://"):
            continue
        permalink = str(row.get("permalink") or "").strip()
        posts.append({
            "id": str(row.get("media_id") or ""),
            "media_type": kind,
            "media_product_type": str(row.get("media_product_type") or ""),
            "caption": str(row.get("caption") or "")[:240],
            "permalink": permalink if permalink.startswith("https://") else None,
            "timestamp": str(row.get("timestamp") or ""),
            "preview_url": cover,
            "image_url": photo_url if photo_url.startswith("https://") else None,
            "video_url": original if kind == "VIDEO" and original.startswith("https://") else None,
            "selectable": (kind in ("IMAGE", "CAROUSEL_ALBUM") and photo_url.startswith("https://")) or
                (kind == "VIDEO" and original.startswith("https://")),
        })
    return {"posts": posts, "source": "instagram_synced", "count": len(posts)}


@router.get("/meta-campaigns")
async def read_meta_campaigns(client_id: str, authorization: Optional[str] = Header(default=None)):
    """Campanhas que já existem na conta de anúncios (para puxar para a Mídia On)."""
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    try:
        return {"campaigns": await pub.list_meta_campaigns(cid)}
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/meta-campaigns/overview")
async def read_meta_campaign_overview(client_id: str, authorization: Optional[str] = Header(default=None)):
    """Visão somente leitura da empresa autorizada, incluindo campanhas encerradas."""
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    try:
        return {"campaigns": await pub.list_meta_campaigns(cid, include_finished=True)}
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/promotion-codes")
async def read_media_promotion_codes(client_id: str, authorization: Optional[str] = Header(default=None)):
    """Read-only Shopify discount codes belonging to the authorized tenant."""
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    from services.integration_errors import IntegrationError
    from services.shopify_discount_codes import list_shopify_promo_codes
    try:
        return await list_shopify_promo_codes(cid)
    except IntegrationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None


class ImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_id: str = Field(pattern=r"^\d{5,30}$")


@router.post("/import", status_code=201)
async def import_meta_campaign(client_id: str, body: ImportInput, authorization: Optional[str] = Header(default=None)):
    """Traz uma campanha da Meta para a Mídia On (nada muda na Meta)."""
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    uid = await require_user_id(authorization)
    try:
        return {"draft": await pub.import_meta_campaign(cid, body.campaign_id, user_id=uid)}
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/whatsapp-numbers")
async def read_ad_whatsapp_numbers(client_id: str, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    return {"numbers": await pub.ad_whatsapp_numbers(cid)}


@router.get("/pixels")
async def read_ad_pixels(client_id: str, draft_id: Optional[str] = Query(default=None, max_length=40),
                         authorization: Optional[str] = Header(default=None)):
    """Conjuntos de dados (pixels) da conta de anúncios, com o recomendado e o da campanha."""
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    try:
        return await pub.list_pixels(cid, str(UUID(draft_id)) if draft_id else None)
    except ValueError:
        raise HTTPException(status_code=422, detail="Campanha inválida.") from None
    except StudioError as exc:
        raise _http(exc) from None


class PixelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pixel_id: str = Field(pattern=r"^\d{5,25}$")


@router.post("/{draft_id}/pixel")
async def change_ad_pixel(client_id: str, draft_id: UUID, body: PixelInput, authorization: Optional[str] = Header(default=None)):
    """Troca o pixel de uma campanha já criada (conjunto e anúncios)."""
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    uid = await require_user_id(authorization)
    try:
        return await pub.set_pixel(cid, str(draft_id), body.pixel_id, user_name=_who(authorization, uid))
    except StudioError as exc:
        raise _http(exc) from None


@router.post("", status_code=201)
async def create_draft(client_id: str, body: GenerateInput, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    uid = await require_user_id(authorization)
    try:
        return {"draft": await pub.generate_draft(cid, user_id=uid, month=body.month, campaign=body.campaign,
                                                  objective=body.objective, days_left=body.days_left)}
    except StudioError as exc:
        raise _http(exc) from None


@router.put("/{draft_id}")
async def update_draft(client_id: str, draft_id: UUID, body: DraftInput, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    try:
        return {"draft": await pub.save_draft(cid, str(draft_id), body.payload)}
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/{draft_id}/duplicate", status_code=201)
async def duplicate_ad_draft(client_id: str, draft_id: UUID, into: Optional[str] = None,
                             adset_id: Optional[str] = Query(default=None, pattern=r"^\d{5,30}$"),
                             authorization: Optional[str] = Header(default=None)):
    """into=campaign: novo anúncio dentro da mesma campanha (mesma verba). Sem 'into': campanha nova."""
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    uid = await require_user_id(authorization)
    try:
        return {"draft": await pub.duplicate_draft(cid, str(draft_id), uid, into_campaign=into == "campaign", adset_id=adset_id)}
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/live")
async def read_live_overview(client_id: str, authorization: Optional[str] = Header(default=None)):
    """Cliente e equipe: o que está sendo veiculado no Meta (criativo, se está no ar e números). Somente leitura."""
    cid = await require_client_read(client_id, authorization)
    try:
        return await pub.client_overview(cid)
    except StudioError as exc:
        raise _http(exc) from None


class UpdateLiveBudgetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    daily_budget: float = Field(gt=0, le=1_000_000)
    confirm: bool


class UpdateLiveCreativeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ad: Dict[str, Any]
    confirm: bool


@router.post("/{draft_id}/edit-budget")
async def edit_published_meta_budget(client_id: str, draft_id: UUID, body: UpdateLiveBudgetInput,
                                     authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    if not body.confirm:
        raise HTTPException(status_code=422, detail="Confirme a alteração de orçamento na Meta.")
    try:
        return await pub.edit_live_budget(cid, str(draft_id), body.daily_budget)
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/{draft_id}/edit-creative")
async def edit_published_meta_creative(client_id: str, draft_id: UUID, body: UpdateLiveCreativeInput,
                                       authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    if not body.confirm:
        raise HTTPException(status_code=422, detail="Confirme a troca do criativo na Meta.")
    try:
        return await pub.edit_live_single_image(cid, str(draft_id), body.ad)
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/{draft_id}/structure")
async def read_live_campaign_structure(client_id: str, draft_id: UUID,
                                       authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    try:
        return await pub.live_campaign_structure(cid, str(draft_id))
    except StudioError as exc:
        raise _http(exc) from None


class LiveObjectStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern=r"^(ACTIVE|PAUSED)$")
    confirm: bool


@router.post("/{draft_id}/objects/{level}/{object_id}/status")
async def update_live_object_status(client_id: str, draft_id: UUID, level: str, object_id: str,
                                    body: LiveObjectStatusInput, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    if not body.confirm:
        raise HTTPException(status_code=422, detail="Confirme a alteração na Meta.")
    try:
        return await pub.change_live_object_status(
            cid, str(draft_id), level=level, object_id=object_id, active=body.status == "ACTIVE")
    except StudioError as exc:
        raise _http(exc) from None


class LiveAdsetBudgetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    daily_budget: float = Field(gt=0, le=1_000_000)
    confirm: bool


@router.post("/{draft_id}/objects/adset/{object_id}/budget")
async def update_live_adset_budget(client_id: str, draft_id: UUID, object_id: str,
                                   body: LiveAdsetBudgetInput, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    if not body.confirm:
        raise HTTPException(status_code=422, detail="Confirme a verba do conjunto na Meta.")
    try:
        return await pub.edit_live_adset_budget(cid, str(draft_id), adset_id=object_id,
                                                daily_budget=body.daily_budget)
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/{draft_id}/objects/{level}/{object_id}/insights")
async def read_live_object_insights(client_id: str, draft_id: UUID, level: str, object_id: str,
                                    authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    try:
        return await pub.live_object_insights(cid, str(draft_id), level=level, object_id=object_id)
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/{draft_id}/delivery-status")
async def read_ad_delivery_status(client_id: str, draft_id: UUID, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    try:
        return await pub.live_delivery_status(cid, str(draft_id))
    except StudioError as exc:
        raise _http(exc) from None


def _who(authorization: Optional[str], uid: str) -> str:
    """Nome de quem ligou/pausou (fica registrado na campanha)."""
    from routes.studio import _chat_author
    return _chat_author(authorization, uid) or uid


class ActivateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_daily_budget: Optional[float] = Field(default=None, ge=0, le=1_000_000)


@router.post("/{draft_id}/activate")
async def activate_ad_draft(client_id: str, draft_id: UUID, body: ActivateInput, authorization: Optional[str] = Header(default=None)):
    """Liga a entrega na Meta (começa a gastar). Exige confirmar a verba diária."""
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    uid = await require_user_id(authorization)
    try:
        return await pub.set_delivery(cid, str(draft_id), active=True, user_name=_who(authorization, uid),
                                      confirm_daily_budget=body.confirm_daily_budget)
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/{draft_id}/pause")
async def pause_ad_draft(client_id: str, draft_id: UUID, authorization: Optional[str] = Header(default=None)):
    """Pausa a entrega na Meta na hora."""
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    uid = await require_user_id(authorization)
    try:
        return await pub.set_delivery(cid, str(draft_id), active=False, user_name=_who(authorization, uid))
    except StudioError as exc:
        raise _http(exc) from None


@router.get("/{draft_id}/results")
async def read_ad_results(client_id: str, draft_id: UUID, period: str = "maximum", authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    try:
        return await pub.live_results(cid, str(draft_id), period)
    except StudioError as exc:
        raise _http(exc) from None


@router.post("/{draft_id}/publish")
async def publish_draft(client_id: str, draft_id: UUID, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    try:
        return {"draft": await pub.publish(cid, str(draft_id))}
    except StudioError as exc:
        raise _http(exc) from None


@router.delete("/{draft_id}")
async def remove_draft(client_id: str, draft_id: UUID, authorization: Optional[str] = Header(default=None)):
    cid = await require_client_role(client_id, authorization, allowed_roles=AGENCY)
    try:
        await pub.delete_draft(cid, str(draft_id))
        return {"ok": True}
    except StudioError as exc:
        raise _http(exc) from None
