from __future__ import annotations

from fastapi import APIRouter, Header, Query

from services.job_runs import get_job_run, list_job_runs
from services.tenant import require_agency_admin
from services.provider_health import client_provider_health
from services.integration_errors import IntegrationError

router = APIRouter(prefix="/api/admin", tags=["admin-health"])


@router.get("/health/overview")
async def health_overview(client_id: str | None = Query(default=None, max_length=120), authorization: str | None = Header(default=None)):
    """Central de saúde das integrações: todas as empresas e fontes, com o que fazer em cada problema."""
    await require_agency_admin(authorization)
    from services.integration_center import overview
    return {"ok": True, **(await overview(client_id=client_id))}


@router.get("/health/clients/{client_id}")
async def health_client(client_id: str, authorization: str | None = Header(default=None)):
    await require_agency_admin(authorization)
    return await client_provider_health(client_id)


@router.get("/health/clients/{client_id}/providers/{provider}")
async def health_provider(client_id: str, provider: str, authorization: str | None = Header(default=None)):
    await require_agency_admin(authorization)
    return await client_provider_health(client_id, provider)


@router.get("/sync-runs")
async def sync_runs(
    client_id: str | None = Query(default=None), provider: str | None = Query(default=None),
    status: str | None = Query(default=None), limit: int = Query(50, ge=1, le=200),
    authorization: str | None = Header(default=None),
):
    await require_agency_admin(authorization)
    return await list_job_runs(client_id=client_id, provider=provider, status=status, limit=limit)


@router.get("/sync-runs/{run_id}")
async def sync_run(run_id: str, authorization: str | None = Header(default=None)):
    await require_agency_admin(authorization)
    row = await get_job_run(run_id)
    if not row:
        raise IntegrationError(
            "Execução de sincronização não encontrada.", status_code=404,
            code="SYNC_RUN_NOT_FOUND", provider="integration",
        )
    return {"ok": True, "run": row}


@router.get("/ai-usage")
async def ai_usage_report(
    start: str | None = Query(default=None, max_length=10), end: str | None = Query(default=None, max_length=10),
    authorization: str | None = Header(default=None),
):
    """Consumo de IA por cliente (tokens e custo estimado). Só a equipe Mugô."""
    await require_agency_admin(authorization)
    from services.ai_usage import report
    return {"ok": True, **(await report(start=start, end=end))}
