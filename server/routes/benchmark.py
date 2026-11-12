"""Benchmarking: tenant-scoped public observations + first-party connected KPIs.

Competitor metrics must have an auditable source. This API never infers
competitors' ad spend, revenue, ROAS, conversions or audience reach.
"""
from __future__ import annotations

from datetime import date, timedelta, datetime, timezone
from typing import Any, Dict, Literal, Optional
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from services import benchmark
from services.ig_supabase import sb_insert, sb_select, sb_update
from services.integration_errors import IntegrationError
from services.studio_calendar import StudioError
from services.tenant import require_client_read, require_client_role

router = APIRouter(prefix="/api/clients/{client_id}/benchmark", tags=["benchmark"])
WRITERS = ("agency_admin", "client_admin")

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

def _url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Informe um link público HTTPS válido.")
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Endereço local não permitido.")
    return value

class CompetitorCreate(Strict):
    name: str = Field(min_length=2, max_length=120)
    website: Optional[str] = Field(default=None, max_length=500)
    instagram_handle: Optional[str] = Field(default=None, max_length=80)
    youtube_handle: Optional[str] = Field(default=None, max_length=100)
    facebook_page: Optional[str] = Field(default=None, max_length=200)
    keywords: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("website")
    @classmethod
    def website_https(cls, value: Optional[str]) -> Optional[str]:
        return _url(value) if value else None

    @field_validator("keywords")
    @classmethod
    def clean_terms(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(term.strip()[:80] for term in value if term.strip()))

class EvidenceCreate(Strict):
    competitor_id: UUID
    category: Literal["ads", "search", "ecommerce", "content"]
    title: str = Field(min_length=3, max_length=240)
    source_url: str = Field(min_length=12, max_length=2000)
    observation: Optional[str] = Field(default=None, max_length=2000)
    metric_name: Optional[str] = Field(default=None, max_length=80)
    metric_value: Optional[float] = None
    unit: Optional[str] = Field(default=None, max_length=40)
    observed_at: Optional[datetime] = None

    @field_validator("source_url")
    @classmethod
    def source_https(cls, value: str) -> str:
        return _url(value)

FIRST_PARTY_FIELDS = (
    "meta_spend", "meta_attributed_revenue", "meta_impressions", "meta_clicks",
    "google_ads_spend", "google_ads_conversion_value", "google_ads_impressions", "google_ads_clicks",
    "ga4_sessions", "ga4_revenue", "ga4_purchases",
    "shopify_net_revenue", "shopify_orders", "instagram_reach", "instagram_interactions",
)

def summarize_own(rows: list[Dict[str, Any]]) -> Dict[str, Any]:
    """None is missing data, not zero. Never conflate Meta, Google and Shopify revenue."""
    totals: Dict[str, Optional[float]] = {}
    covered: Dict[str, int] = {}
    for field in FIRST_PARTY_FIELDS:
        observed = []
        for row in rows:
            raw = row.get(field)
            if raw is None or isinstance(raw, bool):
                continue
            try:
                observed.append(float(raw))
            except (TypeError, ValueError):
                continue
        totals[field] = round(sum(observed), 2) if observed else None
        covered[field] = len(observed)
    return {
        "totals": totals, "days_with_data": covered,
        "period_days_with_rows": len(rows),
        "methodology": "Soma de dias com dados, sem preencher dias ausentes. Receitas atribuidas por plataforma não são somadas à receita Shopify/GA4.",
    }

@router.get("/overview")
async def overview(
    client_id: str,
    days: int = Query(default=30, ge=7, le=90),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    cid = await require_client_read(client_id, authorization)
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    competitors = await sb_select(
        "benchmark_competitors", filters={"client_id": f"eq.{cid}", "active": "is.true"},
        order="created_at.desc", limit=100,
    )
    observations = await sb_select(
        "benchmark_evidence", filters={"client_id": f"eq.{cid}", "observed_at": f"gte.{since}T00:00:00Z"},
        order="observed_at.desc", limit=300,
    )
    own = await sb_select(
        "dashboard_daily_metrics",
        filters={"client_id": f"eq.{cid}", "metric_date": f"gte.{since}"},
        order="metric_date.desc", limit=90,
    )
    clipping = await sb_select(
        "studio_clippings",
        select="id,term,title,url,published_at,source",
        filters={"client_id": f"eq.{cid}", "kind": "eq.concorrente",
                 "published_at": f"gte.{since}T00:00:00Z"},
        order="published_at.desc", limit=60,
    )
    counts = {category: sum(row.get("category") == category for row in observations)
              for category in ("ads", "search", "ecommerce", "content")}
    return {
        "client_id": cid,
        "days": days,
        "competitors": competitors,
        "evidence": observations,
        "public_mentions": clipping,
        "evidence_by_category": counts,
        "own": summarize_own(own),
        "instagram": await benchmark.instagram_block(cid, competitors, days=days),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "limitations": [
            "Observações de concorrentes são evidências públicas cadastradas, não dados internos de anúncios ou vendas.",
            "Anúncios, busca e lojas concorrentes exigem fontes públicas/licenciadas e coleta adicional; nenhuma métrica privada é estimada.",
            "Dados próprios vêm do read model existente, com cobertura por métrica e sem soma de receitas de fontes diferentes.",
        ],
    }

def _competitor_fields(body: "CompetitorCreate") -> Dict[str, Any]:
    """facebook_page só vai quando preenchido (a coluna vem da 000111; sem ela o resto continua funcionando)."""
    data = body.model_dump()
    if not data.get("facebook_page"):
        data.pop("facebook_page", None)
    return data


@router.post("/competitors", status_code=201)
async def add_competitor(
    client_id: str, body: CompetitorCreate,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    existing = await sb_select("benchmark_competitors",
        filters={"client_id": f"eq.{cid}", "name": f"eq.{body.name}"}, limit=1)
    if existing and existing[0].get("active", True):
        raise HTTPException(status_code=409, detail="Este concorrente já foi cadastrado.")
    if existing:
        # Removido antes: volta com os dados novos (as evidências antigas continuam ligadas a ele).
        rows = await sb_update("benchmark_competitors", filters={"client_id": f"eq.{cid}", "id": f"eq.{existing[0]['id']}"},
                               patch={**_competitor_fields(body), "active": True, "updated_at": datetime.now(timezone.utc).isoformat()})
        return rows[0] if rows else existing[0]
    from services import saas
    try:
        await saas.require(cid, "competitors")
    except saas.QuotaError as exc:
        raise HTTPException(status_code=402, detail=exc.message) from None
    saved = await sb_insert("benchmark_competitors", {"client_id": cid, **_competitor_fields(body)})
    if not saved:
        raise HTTPException(status_code=502, detail="Não foi possível salvar o concorrente.")
    return saved

@router.post("/evidence", status_code=201)
async def add_evidence(
    client_id: str, body: EvidenceCreate,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    competitor = await sb_select("benchmark_competitors", select="id",
        filters={"client_id": f"eq.{cid}", "id": f"eq.{body.competitor_id}"}, limit=1)
    if not competitor:
        raise HTTPException(status_code=404, detail="Concorrente não encontrado nesta empresa.")
    payload = body.model_dump(mode="json", exclude_none=True)
    saved = await sb_insert("benchmark_evidence", {"client_id": cid, **payload})
    if not saved:
        raise HTTPException(status_code=502, detail="Não foi possível salvar a evidência.")
    return saved


@router.delete("/competitors/{competitor_id}")
async def remove_competitor(
    client_id: str, competitor_id: UUID,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Tira o concorrente do monitoramento (sem apagar as evidências; cadastrar de novo o traz de volta)."""
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    rows = await sb_update("benchmark_competitors", filters={"client_id": f"eq.{cid}", "id": f"eq.{competitor_id}"},
                           patch={"active": False, "updated_at": datetime.now(timezone.utc).isoformat()})
    if not rows:
        raise HTTPException(status_code=404, detail="Concorrente não encontrado nesta empresa.")
    return {"removed": str(competitor_id)}


REFRESH_ERRORS = {
    "BENCHMARK_COOLDOWN": (429, "O Instagram foi atualizado há pouco. Os números públicos mudam devagar: tente de novo em algumas horas."),
    "BENCHMARK_NO_HANDLES": (422, "Cadastre o @ do Instagram de pelo menos um concorrente."),
}


@router.post("/instagram/refresh")
async def refresh_instagram(
    client_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Busca agora o perfil público (Instagram) da marca e dos concorrentes com @. No máximo a cada 6 horas."""
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    competitors = await sb_select("benchmark_competitors", filters={"client_id": f"eq.{cid}", "active": "is.true"}, limit=100)
    try:
        return await benchmark.refresh_instagram(cid, competitors)
    except StudioError as exc:
        status, detail = REFRESH_ERRORS.get(exc.code, (502, "Não foi possível atualizar agora."))
        raise HTTPException(status_code=status, detail=detail) from None
    except IntegrationError as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 502) or 502, detail=str(exc)) from None



# ---------------------------------------------------------------- preços públicos e Biblioteca de Anúncios

class ProductAdd(Strict):
    url: str = Field(min_length=12, max_length=1000)
    competitor_id: Optional[UUID] = None


class CatalogRequest(Strict):
    website: str = Field(min_length=10, max_length=500)


def _price_fail(exc: Exception) -> HTTPException:
    from services.benchmark_prices import PriceError
    if isinstance(exc, PriceError):
        return HTTPException(status_code=exc.status, detail=exc.message)
    import httpx
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None and exc.response.status_code in (400, 404):
        return HTTPException(status_code=409, detail="Falta aplicar a migração 000111 (preços do benchmarking) no Supabase.")
    print(f"[benchmark_prices_routes] unexpected {type(exc).__name__}")
    return HTTPException(status_code=502, detail="Não foi possível concluir agora.")


@router.get("/prices")
async def list_prices(client_id: str, days: int = Query(default=90, ge=7, le=365), authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    from services import benchmark_prices
    cid = await require_client_read(client_id, authorization)
    try:
        competitors = await sb_select("benchmark_competitors", filters={"client_id": f"eq.{cid}", "active": "is.true"}, limit=100)
        return {"products": await benchmark_prices.list_products(cid, days),
                "ad_library": [{"competitor_id": c["id"], "name": c["name"], "url": benchmark_prices.ad_library_url(c)} for c in competitors]}
    except Exception as exc:  # noqa: BLE001
        raise _price_fail(exc) from exc


@router.post("/prices", status_code=201)
async def add_price(client_id: str, body: ProductAdd, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """Começa a acompanhar o preço de uma página de produto (lê na hora e depois todo dia)."""
    from services import benchmark_prices
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        return await benchmark_prices.add_product(cid, body.url, str(body.competitor_id) if body.competitor_id else None)
    except Exception as exc:  # noqa: BLE001
        raise _price_fail(exc) from exc


@router.post("/prices/{product_id}/check")
async def check_price(client_id: str, product_id: UUID, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    from services import benchmark_prices
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        return await benchmark_prices.check_product(cid, str(product_id))
    except Exception as exc:  # noqa: BLE001
        raise _price_fail(exc) from exc


@router.delete("/prices/{product_id}")
async def remove_price(client_id: str, product_id: UUID, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    from services import benchmark_prices
    cid = await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        await benchmark_prices.remove_product(cid, str(product_id))
        return {"removed": str(product_id)}
    except Exception as exc:  # noqa: BLE001
        raise _price_fail(exc) from exc


@router.post("/catalog")
async def store_catalog(client_id: str, body: CatalogRequest, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """Lista produtos de uma loja Shopify para escolher quais acompanhar."""
    from services import benchmark_prices
    await require_client_role(client_id, authorization, allowed_roles=WRITERS)
    try:
        return {"products": await benchmark_prices.catalog(body.website)}
    except Exception as exc:  # noqa: BLE001
        raise _price_fail(exc) from exc
