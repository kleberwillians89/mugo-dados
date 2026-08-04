from __future__ import annotations

from fastapi import APIRouter, Header, Query

from services.job_runs import get_job_run, list_job_runs
from services.tenant import require_agency_admin
from services.provider_health import client_provider_health
from services.integration_errors import IntegrationError

router = APIRouter(prefix="/api/admin", tags=["admin-health"])


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
