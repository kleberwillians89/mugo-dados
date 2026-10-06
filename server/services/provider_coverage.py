"""Cobertura read-only; datas existentes não certificam coleta completa."""
from datetime import date, datetime, timedelta
from .periods import resolve_period, local_date

from .provider_history import validate_history
from .ga4_connections import resolve_ga4_connection_context
from .google_ads import resolve_google_ads_context
from .connection_resolver import resolve_connection_for_scope
from .ig_supabase import sb_select


async def provider_coverage(*, client_id: str, provider: str, start_date: str, end_date: str,
                            connection_id: str | None = None) -> dict:
    validate_history(client_id, "instagram_content" if provider == "instagram" else provider, start_date, end_date)
    if provider in {"ga4", "google_ads"}:
        context = (await resolve_ga4_connection_context(client_id, connection_id) if provider == "ga4"
                   else await resolve_google_ads_context(client_id, connection_id))
        table = "ga4_daily_stats" if provider == "ga4" else "google_ads_daily_stats"
        resource = context.property_id if provider == "ga4" else context.customer_id
        filters = {"client_id": f"eq.{client_id}",
                   "property_id" if provider == "ga4" else "customer_id": f"eq.{resource}"}
        if provider == "google_ads":
            filters["connection_id"] = f"eq.{context.connection_id}"
        connection = context.connection_id
        column = "stat_date"
    else:
        context = await resolve_connection_for_scope(client_id=client_id,
                platform="meta_ads" if provider == "meta_ads" else "instagram",
                connection_type="paid" if provider == "meta_ads" else "organic",
                requested_connection_id=connection_id)
        connection = context.get("connection_id")
        if not connection:
            raise ValueError("Nenhuma conexão selecionada para esta empresa.")
        table = "ad_account_daily_stats" if provider == "meta_ads" else "ig_media" if provider == "instagram_content" else "ig_profile_snapshots"
        filters = {"client_id": f"eq.{client_id}", "connection_id": f"eq.{connection}"}
        column = "stat_date" if provider == "meta_ads" else "timestamp" if provider == "instagram_content" else "snapshot_date"
        resource = None
    filters["and"] = f"({column}.gte.{start_date},{column}.lte.{end_date})"
    if column == "timestamp":
        since, until = resolve_period(start=start_date, end=end_date, max_days=90).utc_bounds()
        filters["and"] = f"(timestamp.gte.{since.isoformat()},timestamp.lte.{until.isoformat()})"
        filters["or"] = "(media_product_type.is.null,media_product_type.neq.STORY)"
    rows = []
    for offset in range(0, 1000000, 1000):
        page = await sb_select(table, select=f"{column},updated_at", filters=filters,
                               order=f"{column}.asc,id.asc", limit=1000, offset=offset)
        rows.extend(page)
        if len(page) < 1000:
            break
    else:
        raise RuntimeError("Consulta de cobertura excedeu o limite; não certificada.")
    dates = sorted({local_date(datetime.fromisoformat(str(row[column]).replace("Z", "+00:00"))).isoformat() if column == "timestamp" else str(row[column]) for row in rows if row.get(column)})
    # Somente checkpoints de ingestão + projeção concluídos certificam janelas.
    verified = set()
    last_sync = None
    if resource:
        jobs = []
        for offset in range(0, 1000000, 1000):
            page = await sb_select("cron_job_runs", select="finished_at,payload_json", filters={
                "client_id": f"eq.{client_id}", "connection_id": f"eq.{connection}",
                "job_name": f"eq.provider_history_{provider}", "status": "eq.success",
                "payload_json->>resource_id": f"eq.{resource}",
                "payload_json->>collection_complete": "eq.true",
            }, order="finished_at.asc,id.asc", limit=1000, offset=offset)
            jobs.extend(page)
            if len(page) < 1000:
                break
        else:
            raise RuntimeError("Consulta de checkpoints incompleta; cobertura não certificada.")
        for job in jobs:
            payload = job.get("payload_json") or {}
            start, end = date.fromisoformat(payload["start_date"]), date.fromisoformat(payload["end_date"])
            verified.update((start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1))
            last_sync = max(last_sync or "", str(job.get("finished_at") or "")) or None
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    expected = {(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)}
    source = "meta" if provider == "meta_ads" else "instagram" if provider in {"instagram_content", "instagram"} else provider
    snapshots = await sb_select("dashboard_source_snapshots", select="last_success_at", filters={
        "client_id": f"eq.{client_id}", "provider": f"eq.{source}"}, limit=1)
    return {"client_id": client_id, "provider": provider, "dataset": table,
            "requested_start": start_date, "requested_end": end_date,
            "coverage_start": dates[0] if dates else None, "coverage_end": dates[-1] if dates else None,
            "distinct_dates": len(dates), "records": len(rows), "last_sync_at": last_sync,
            "projection_success_at": (snapshots[0].get("last_success_at") if snapshots else None),
            "completeness": "complete" if expected <= verified else "unknown",
            "status": "sem dados" if not rows else "suficiente para 90 dias" if len(expected) == 90 and expected <= verified else "parcial"}
