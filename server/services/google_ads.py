from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, List

import httpx

from .connection_resolver import resolve_generic_connection
from .google_ads_ids import normalize_google_ads_customer_id
from .google_oauth import (
    _google_ads_error_details,
    _log_google_ads_error,
    get_google_access_token,
    google_ads_api_error,
)
from .ig_supabase import sb_select, sb_update, sb_upsert
from .integration_errors import IntegrationError
from .job_runs import finish_job_run, start_job_run
from .periods import resolve_period
from .sync_locks import guarded_sync
from .dashboard_read_model import refresh_dashboard_read_model_safely


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitized_error(exc: BaseException) -> Dict[str, Any]:
    """Erro observável sem credencial: só código, mensagem pública e diagnóstico
    já sanitizado pelo google_oauth (status upstream, request id, motivo)."""
    diagnostics = getattr(exc, "diagnostics", None)
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    message = str(getattr(exc, "message", "") or exc) if isinstance(exc, IntegrationError) else exc.__class__.__name__
    return {
        "code": str(getattr(exc, "code", "") or "GOOGLE_ADS_SYNC_FAILED"),
        "message": message[:240],
        "retryable": bool(getattr(exc, "retryable", False)),
        "upstream_status": diagnostics.get("upstream_status"),
        "request_id": diagnostics.get("request_id"),
        "upstream_reason": diagnostics.get("upstream_reason"),
    }


async def _record_sync_outcome(
    *, client_id: str, connection_id: str, attempt_at: str,
    success: bool, rows: int = 0, error: Dict[str, Any] | None = None,
) -> None:
    """Observabilidade na conexão (tela de Integrações). NÃO altera `status`:
    o cron seleciona `status=connected` e uma falha não pode desligar o
    provider para sempre."""
    if not client_id or not connection_id:
        return
    metadata_patch: Dict[str, Any] = {"last_attempt_at": attempt_at}
    if success:
        metadata_patch.update({
            "last_success_at": attempt_at, "last_sync_rows": rows,
            "last_error_code": None, "last_error_retryable": None, "last_request_id": None,
        })
    else:
        metadata_patch.update({
            "last_error_code": (error or {}).get("code"),
            "last_error_retryable": (error or {}).get("retryable"),
            "last_request_id": (error or {}).get("request_id"),
        })
    try:
        rows_found = await sb_select(
            "integration_connections", select="id,metadata",
            filters={"id": f"eq.{connection_id}", "client_id": f"eq.{client_id}", "provider": "eq.google_ads"},
            limit=1,
        )
        current = rows_found[0].get("metadata") if rows_found and isinstance(rows_found[0].get("metadata"), dict) else {}
        patch: Dict[str, Any] = {
            "metadata": {**current, **metadata_patch},
            "updated_at": attempt_at,
        }
        if success:
            patch["last_sync_at"] = attempt_at
            patch["last_error"] = None
        else:
            patch["last_error"] = f"{(error or {}).get('code')}: {(error or {}).get('message')}"[:300]
        await sb_update(
            "integration_connections",
            filters={"id": f"eq.{connection_id}", "client_id": f"eq.{client_id}", "provider": "eq.google_ads"},
            patch=patch, returning="minimal",
        )
    except Exception as exc:  # observabilidade nunca derruba a sincronização
        print(f"[google_ads] stage=observability client_id={client_id} status=write_failed error_type={exc.__class__.__name__}")


@dataclass(frozen=True)
class GoogleAdsContext:
    client_id: str
    connection_id: str
    customer_id: str
    login_customer_id: str | None


async def resolve_google_ads_context(client_id: str, connection_id: str | None = None) -> GoogleAdsContext:
    row = await resolve_generic_connection(
        client_id=client_id, provider="google_ads",
        requested_connection_id=connection_id, require_token=False,
    )
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    # Sempre a conta persistida na seleção da empresa — nunca a primeira da lista.
    customer_id = normalize_google_ads_customer_id(metadata.get("google_ads_customer_id"))
    if not customer_id:
        raise IntegrationError(
            "Selecione uma conta Google Ads.", status_code=409,
            code="GOOGLE_ADS_ACCOUNT_SELECTION_REQUIRED", provider="google_ads",
        )
    return GoogleAdsContext(
        client_id=client_id,
        connection_id=str(row.get("id") or ""),
        customer_id=customer_id,
        login_customer_id=normalize_google_ads_customer_id(metadata.get("google_ads_login_customer_id")),
    )


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _parse_result(client_id: str, context: GoogleAdsContext, item: Dict[str, Any]) -> Dict[str, Any] | None:
    segments = item.get("segments") if isinstance(item.get("segments"), dict) else {}
    campaign = item.get("campaign") if isinstance(item.get("campaign"), dict) else {}
    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    stat_date = str(segments.get("date") or "").strip()
    campaign_id = str(campaign.get("id") or "").strip()
    if not stat_date or not campaign_id:
        return None
    cost = _number(metrics.get("costMicros")) / 1_000_000
    clicks = _integer(metrics.get("clicks"))
    impressions = _integer(metrics.get("impressions"))
    return {
        "client_id": client_id,
        "connection_id": context.connection_id,
        "customer_id": context.customer_id,
        "stat_date": stat_date,
        "campaign_id": campaign_id,
        "campaign_name": str(campaign.get("name") or ""),
        "cost": round(cost, 6),
        "impressions": impressions,
        "clicks": clicks,
        "ctr": _number(metrics.get("ctr")),
        "cpc": round(cost / clicks, 6) if clicks else 0,
        "conversions": _number(metrics.get("conversions")),
        "conversion_value": _number(metrics.get("conversionsValue")),
    }


async def _sync_google_ads(
    *, client_id: str, connection_id: str | None, start: str | None, end: str | None, days: int,
) -> Dict[str, Any]:
    context = await resolve_google_ads_context(client_id, connection_id)
    developer_token = str(os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN") or "").strip()
    if not developer_token:
        raise IntegrationError(
            "GOOGLE_ADS_DEVELOPER_TOKEN não configurado.", status_code=409,
            code="GOOGLE_ADS_SETUP_REQUIRED", provider="google_ads",
        )
    version = str(os.getenv("GOOGLE_ADS_API_VERSION") or "v25").strip()
    if not re.fullmatch(r"v\d+", version):
        raise IntegrationError(
            "GOOGLE_ADS_API_VERSION inválida.", status_code=409,
            code="GOOGLE_ADS_API_VERSION_INVALID", provider="google_ads",
        )
    period = resolve_period(start=start, end=end, days=days, max_days=366)
    query = (
        "SELECT segments.date, campaign.id, campaign.name, metrics.cost_micros, "
        "metrics.impressions, metrics.clicks, metrics.ctr, metrics.average_cpc, "
        "metrics.conversions, metrics.conversions_value FROM campaign "
        # O status atual não deve excluir fatos financeiros históricos.
        f"WHERE segments.date BETWEEN '{period.start.isoformat()}' AND '{period.end.isoformat()}'"
    )
    token = await get_google_access_token(client_id, context.connection_id)
    headers = {"Authorization": f"Bearer {token}", "developer-token": developer_token}
    if context.login_customer_id:
        headers["login-customer-id"] = context.login_customer_id
    print(
        f"[google_ads] stage=sync client_id={client_id} connection_id={context.connection_id} "
        f"customer_id={context.customer_id} login_customer_id={context.login_customer_id or 'none'} "
        f"start={period.start.isoformat()} end={period.end.isoformat()}"
    )
    url = f"https://googleads.googleapis.com/{version}/customers/{context.customer_id}/googleAds:searchStream"
    async with httpx.AsyncClient(timeout=60) as http:
        response = await http.post(url, headers=headers, json={"query": query})
    if response.status_code >= 400:
        details = _google_ads_error_details(response)
        _log_google_ads_error(
            "sync", details, client_id=client_id, connection_id=context.connection_id,
            request_id="-", customer_id=context.customer_id,
            login_customer_id=context.login_customer_id,
            endpoint=f"POST /{version}/customers/{context.customer_id}/googleAds:searchStream",
        )
        mapped = google_ads_api_error(
            response, details, operation="consultar campanhas Google Ads", provider="google_ads",
        )
        known = mapped.code.startswith("GOOGLE_ADS_")
        error = mapped if known else IntegrationError(
            "Google Ads recusou a consulta diária.", status_code=502,
            code="GOOGLE_ADS_QUERY_FAILED", provider="google_ads",
        )
        error.diagnostics = {
            "upstream_status": response.status_code,
            "request_id": details["google_request_id"],
            "upstream_reason": ",".join(details["reasons"]) or details["google_status"] or None,
        }
        raise error
    payload = response.json()
    batches = payload if isinstance(payload, list) else [payload]
    rows: List[Dict[str, Any]] = []
    for batch in batches:
        if not isinstance(batch, dict):
            raise IntegrationError("Resposta Google Ads incompleta.", status_code=502,
                                   code="GOOGLE_ADS_RESPONSE_INCOMPLETE", provider="google_ads", retryable=True)
        for item in batch.get("results") or []:
            parsed = _parse_result(client_id, context, item)
            if not parsed:
                raise IntegrationError("Identidade diária Google Ads ausente.", status_code=502,
                                       code="GOOGLE_ADS_RESPONSE_INCOMPLETE", provider="google_ads", retryable=True)
            rows.append(parsed)
    if rows:
        await sb_upsert(
            "google_ads_daily_stats", rows,
            on_conflict="client_id,connection_id,customer_id,campaign_id,stat_date",
        )
    # Também projetar janelas vazias: sucesso exige read model utilizável.
    try:
        projection = await refresh_dashboard_read_model_safely(
            client_id=client_id,
            start=period.start.isoformat(),
            end=period.end.isoformat(),
            provider="google_ads",
        )
    except Exception:
        raise IntegrationError(
            "Os fatos foram consultados, mas a projeção de Google Ads falhou. Mantendo a última leitura válida.",
            status_code=502, code="GOOGLE_ADS_PROJECTION_FAILED", provider="google_ads", retryable=True,
        ) from None
    if not isinstance(projection, dict) or projection.get("ok") is not True:
        raise IntegrationError(
            "A projeção de Google Ads não foi concluída. Mantendo a última leitura válida.",
            status_code=502, code="GOOGLE_ADS_PROJECTION_FAILED", provider="google_ads", retryable=True,
        )
    return {
        "ok": True, "client_id": client_id, "connection_id": context.connection_id,
        "customer_id": context.customer_id,
        "period": {"start": period.start.isoformat(), "end": period.end.isoformat(), "days": period.days},
        "rows_received": len(rows), "rows_upserted": len(rows), "read_model_refreshed": True,
        "projection_success_at": _now_iso(),
        "collection_complete": True,
    }


async def sync_google_ads(
    *, client_id: str, connection_id: str | None, start: str | None, end: str | None, days: int,
    job_name: str = "google_ads_sync_manual", trigger_source: str = "manual_api",
    record_job_run: bool = True,
) -> Dict[str, Any]:
    """Sincroniza as campanhas e registra a tentativa.

    Toda execução deixa rastro (cron_job_runs + metadata da conexão), para que
    `last_attempt_at`/`last_success_at` e o código do erro sejam visíveis sem
    depender de log — e para provar se métricas novas entraram.
    """
    if not connection_id:
        context = await resolve_google_ads_context(client_id)
        connection_id = context.connection_id
    async with guarded_sync(
        client_id=client_id, provider="google_ads", connection_id=str(connection_id),
        ttl_seconds=1800,
    ):
        attempt_at = _now_iso()
        job_run = None
        if record_job_run:
            job_run = await start_job_run(
                job_name=job_name, client_id=client_id, connection_id=connection_id,
                trigger_source=trigger_source,
                payload_json={"requested": {"start": start, "end": end, "days": days}},
            )
        job_run_id = str((job_run or {}).get("id") or "")
        try:
            payload = await _sync_google_ads(
                client_id=client_id, connection_id=connection_id, start=start, end=end, days=days,
            )
        except Exception as exc:
            error = _sanitized_error(exc)
            resolved_connection_id = str(connection_id or "")
            print(
                f"[google_ads] stage=sync_result client_id={client_id} "
                f"connection_id={resolved_connection_id or '-'} status=error code={error['code']} "
                f"upstream_status={error['upstream_status'] or '-'} request_id={error['request_id'] or '-'}"
            )
            await _record_sync_outcome(
                client_id=client_id, connection_id=resolved_connection_id,
                attempt_at=attempt_at, success=False, error=error,
            )
            if job_run_id:
                await finish_job_run(
                    job_run_id, status="error", error=f"{error['code']}: {error['message']}",
                    payload_json={"error": error, "requested": {"start": start, "end": end, "days": days}},
                    client_id=client_id, connection_id=resolved_connection_id or None,
                )
            raise
        rows = int(payload.get("rows_upserted") or 0)
        print(
            f"[google_ads] stage=sync_result client_id={client_id} "
            f"connection_id={payload.get('connection_id') or '-'} status=ok rows_upserted={rows}"
        )
        await _record_sync_outcome(
            client_id=client_id, connection_id=str(payload.get("connection_id") or ""),
            attempt_at=attempt_at, success=True, rows=rows,
        )
        if job_run_id:
            await finish_job_run(
                job_run_id, status="success", rows_upserted=rows, payload_json=payload,
                client_id=client_id, connection_id=str(payload.get("connection_id") or "") or None,
            )
        payload["job_run_id"] = job_run_id or None
        payload["last_attempt_at"] = attempt_at
        payload["last_success_at"] = attempt_at
        return payload


async def build_google_ads_report(
    *, client_id: str, context: GoogleAdsContext, start: str, end: str,
) -> Dict[str, Any]:
    rows = await sb_select(
        "google_ads_daily_stats",
        filters={
            "client_id": f"eq.{client_id}", "connection_id": f"eq.{context.connection_id}",
            "customer_id": f"eq.{context.customer_id}",
            "and": f"(stat_date.gte.{start},stat_date.lte.{end})",
        },
        order="stat_date.asc", limit=20000,
    )
    by_day: Dict[str, Dict[str, float]] = {}
    for row in rows:
        day = str(row.get("stat_date") or "")
        item = by_day.setdefault(day, {"spend": 0.0, "impressions": 0.0, "clicks": 0.0, "conversions": 0.0, "conversion_value": 0.0})
        item["spend"] += _number(row.get("cost"))
        item["impressions"] += _number(row.get("impressions"))
        item["clicks"] += _number(row.get("clicks"))
        item["conversions"] += _number(row.get("conversions"))
        item["conversion_value"] += _number(row.get("conversion_value"))
    totals = {key: sum(item[key] for item in by_day.values()) for key in ("spend", "impressions", "clicks", "conversions", "conversion_value")}
    totals["roas"] = totals["conversion_value"] / totals["spend"] if totals["spend"] > 0 else None
    daily = [{"date": day, **values} for day, values in sorted(by_day.items())]
    covered = len(by_day)
    expected = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    return {
        "ok": True, "connected": True, "client_id": client_id,
        "connection_id": context.connection_id, "customer_id": context.customer_id,
        "data_available": bool(rows), "totals": totals, "daily": daily,
        "coverage": {"covered_days": covered, "expected_days": expected, "is_partial": covered < expected},
        "data_max_available": max(by_day, default=None),
    }
