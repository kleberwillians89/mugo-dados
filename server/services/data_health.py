"""Bounded, read-only freshness evidence. Projection time is not sync success."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .ig_supabase import sb_select

# Expected maximum intervals from render.yaml, not proof that crons run remotely.
POLICIES = {
    "meta_ads": (3600, 7200), "instagram": (25200, 28800),
    "ga4": (10800, 21600), "google_ads": (10800, 21600),
    "shopify": (1800, 3600), "fbits": (1800, 3600),
    # Official FBITS aggregates are collected only by explicit period refresh.
    "fbits_official": (None, None),
    "instagram_content": (25200, 28800),
}
FIELDS = {"meta_ads": "meta_spend", "instagram": "instagram_reach", "ga4": "ga4_sessions",
          "google_ads": "google_ads_spend", "shopify": "shopify_net_revenue"}


def instant(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else None
    except (TypeError, ValueError):
        return None


def latest(values):
    valid = [value for value in values if instant(value)]
    return max(valid, key=instant) if valid else None


def job_provider(job):
    name = str(job.get("job_name") or "")
    if "token" in name:
        return None
    for token, provider in (("google_ads", "google_ads"), ("ga4", "ga4"), ("instagram", "instagram"),
                            ("shopify", "shopify"), ("fbits", "fbits"), ("meta_ads", "meta_ads")):
        if name.startswith(token) or name.startswith(f"provider_history_{token}"):
            return provider
    return None


def period_of(payload):
    period = payload.get("period") or payload.get("date_range") or payload
    return period.get("start") or period.get("since") or period.get("start_date"), period.get("end") or period.get("until") or period.get("end_date")


def compose_source(provider, connection, jobs, locks, daily, start, end, *, now, read_error=False):
    row = connection or {}
    metadata = row.get("metadata") or {}
    def same_resource(job):
        if not row.get("id") or job.get("client_id") != row.get("client_id") or job_provider(job) != provider:
            return False
        details = job.get("payload_json") or {}
        if provider == "ga4" and str(details.get("property_id") or "").removeprefix("properties/") != str(metadata.get("ga4_property_id") or "").removeprefix("properties/"):
            return False
        if provider == "google_ads" and metadata.get("google_ads_customer_id"):
            if str(details.get("customer_id") or "") != str(metadata["google_ads_customer_id"]):
                return False
        if provider == "meta_ads":
            # Legacy jobs without an account cannot certify the selected account.
            account = str(row.get("ad_account_id") or "").removeprefix("act_")
            if not account or str(job.get("ad_account_id") or "").removeprefix("act_") != account:
                return False
        return job.get("connection_id") == row["id"] or (provider == "ga4" and not job.get("connection_id"))
    selected = [j for j in jobs if same_resource(j)]
    selected.sort(key=lambda j: instant(j.get("started_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    last = selected[0] if selected else {}
    successes = [j for j in selected if j.get("status") == "success" and (j.get("payload_json") or {}).get("collection_complete") is not False
                 and (j.get("payload_json") or {}).get("read_model_refreshed") is not False
                 and (j.get("payload_json") or {}).get("sync_outcome") not in {"partial", "no_data"}]
    success = latest([j.get("finished_at") for j in successes])
    if provider in {"fbits", "shopify"}:
        success = latest([success, metadata.get("last_success_at"), row.get("last_sync_at")])
    elif provider == "instagram" and row.get("last_sync_status") == "success":
        success = latest([success, row.get("last_synced_at")])
    # Última vez que dados novos foram gravados, inclusive em coleta parcial (o que
    # faltou manteve o valor anterior). É o que a tela mostra como "Atualizado em";
    # last_successful_sync_at continua sendo só a coleta completa.
    updated = latest([success] + [j.get("finished_at") for j in selected if j.get("status") in {"success", "partial"}])
    if provider == "instagram" and row.get("last_sync_status") in {"success", "partial"}:
        updated = latest([updated, row.get("last_sync_at"), row.get("last_synced_at")])
    attempt = latest([j.get("started_at") for j in selected] + [metadata.get("last_attempt_at")])
    dates = sorted({str(d.get("metric_date")) for d in daily if d.get(FIELDS.get(provider, "")) is not None})
    data_at = dates[-1] if dates else None
    verified = set()
    for job in successes:
        payload = job.get("payload_json") or {}
        # Only an explicit complete collection + durable projection certifies a window.
        if payload.get("collection_complete") is not True or payload.get("read_model_refreshed") is not True:
            continue
        a, b = period_of(payload)
        try:
            since, until = max(date.fromisoformat(a), date.fromisoformat(start)), min(date.fromisoformat(b), date.fromisoformat(end))
        except (ValueError, TypeError):
            continue
        # No future-day certification.
        until = min(until, now.astimezone(ZoneInfo("America/Sao_Paulo")).date())
        verified.update((since + timedelta(days=i)).isoformat() for i in range(max(0, (until - since).days + 1)))
    cursor = date.fromisoformat(start)
    while cursor.isoformat() in verified:
        cursor += timedelta(days=1)
    coverage_end = (cursor - timedelta(days=1)).isoformat() if cursor > date.fromisoformat(start) else None
    status = last.get("status") or row.get("last_sync_status") or ("success" if success else "unknown")
    if (last.get("payload_json") or {}).get("collection_complete") is False:
        status = "partial"
    if row.get("status") == "sync_error" or (metadata.get("last_error_code") and latest([metadata.get("last_attempt_at"), last.get("started_at")]) == metadata.get("last_attempt_at")):
        status = "error"
    if status == "skipped":
        status = "no_data" if (last.get("payload_json") or {}).get("sync_outcome") == "no_data" else "unknown"
    lock_provider = "meta_organic" if provider == "instagram" else provider
    lock_connection = "property:" + str(metadata.get("ga4_property_id") or "").removeprefix("properties/") if provider == "ga4" else row.get("id")
    lock_prefix = f"sync:{lock_provider}:{lock_connection}"
    live_lock = bool(connection) and any(
        (str(lock.get("job_name") or "") == lock_prefix or str(lock.get("job_name") or "").startswith(lock_prefix + ":"))
        and (instant(lock.get("locked_until")) or datetime.min.replace(tzinfo=timezone.utc)) > now for lock in locks)

    if status == "running" and not live_lock:
        status = "unknown"
    reauth = row.get("requires_reauth") or row.get("status") in {"reauth_required", "needs_reauth", "token_expired"}
    code = "REAUTH_REQUIRED" if reauth else "SYNC_FAILED" if status == "error" else None
    if status == "partial": code = "INCOMPLETE_COLLECTION"
    if last.get("status") == "running" and not live_lock: code = "OPERATION_NOT_CONFIRMED_RUNNING"
    if read_error: code = "FRESHNESS_READ_FAILED"
    cadence, stale_after = POLICIES[provider]
    age = (now - instant(success)).total_seconds() if success else None
    if reauth: state = "reauth_required"
    elif live_lock: state = "updating"
    elif read_error or status in {"error", "partial"}: state = "attention"
    elif success and stale_after and age is not None and age > stale_after: state = "stale"
    elif not success or (not data_at and not coverage_end): state = "no_data"
    elif not coverage_end or coverage_end < end: state = "attention"
    else: state = "synced"
    return {"provider": provider, "dataset": provider, "connected": bool(connection) and not row.get("disconnected_at") and row.get("status") != "disconnected",
            "last_attempt_at": attempt, "last_successful_sync_at": success, "last_updated_at": updated, "last_data_at": data_at,
            "last_data_semantics": "latest_persisted_metric_day_in_selected_period",
            "coverage_end": coverage_end, "sync_status": status, "error_code": code, "state": state,
            "expected_interval_seconds": cadence, "stale_after_seconds": stale_after,
            "schedule_verified": False, "requested_start": start, "requested_end": end}


def official_source(connection, start, end, *, now):
    from .fbits_official_kpis import persisted_snapshot
    previous_end = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
    previous_start = (date.fromisoformat(start) - timedelta(days=(date.fromisoformat(end)-date.fromisoformat(start)).days+1)).isoformat()
    result = compose_source("fbits_official", connection, [], [], [], start, end, now=now)
    result.update(last_successful_sync_at=None, last_attempt_at=None, dataset="fbits_dashboard", coverage_end=None,
                  last_data_at=None, last_data_semantics="aggregate_period_has_no_latest_order_timestamp", sync_status="unknown", state="no_data")
    try:
        entry, _value = persisted_snapshot(connection, start, end, previous_start, previous_end)
    except RuntimeError as exc:
        result["error_code"] = str(exc)
        if connection and connection.get("status") in {"reauth_required", "token_expired"}:
            result.update(state="reauth_required", error_code="REAUTH_REQUIRED")
        return result
    stamp = entry.get("updated_at")
    if not instant(stamp):
        result["error_code"] = "FBITS_OFFICIAL_TIMESTAMP_UNKNOWN"
        return result
    coverage = min(end, instant(stamp).astimezone(ZoneInfo("America/Sao_Paulo")).date().isoformat())
    result.update(last_successful_sync_at=stamp, coverage_end=coverage, sync_status="success",
                  state="synced" if coverage >= end else "attention", error_code=None)
    if result["connected"] and connection.get("status") == "reauth_required":
        result.update(state="reauth_required", error_code="REAUTH_REQUIRED")
    return result


async def client_data_health(client_id: str, start: str, end: str):
    queries = [
        ("integration_connections", "id,client_id,provider,status,disconnected_at,last_sync_at,metadata", 50),
        ("meta_connections", "id,client_id,platform,connection_type,ad_account_id,status,requires_reauth,last_synced_at,last_sync_at,last_sync_status", 50),
        ("cron_job_runs", "client_id,connection_id,ad_account_id,job_name,status,started_at,finished_at,payload_json", 100),
        ("cron_locks", "client_id,job_name,locked_until", 100),
        ("dashboard_daily_metrics", "client_id,metric_date," + ",".join(FIELDS.values()), 366),
        ("fbits_orders", "client_id,order_date", 1),
        ("ig_media", "client_id,timestamp", 1),
    ]
    async def read(table, select, limit):
        filters = {"client_id": f"eq.{client_id}"}
        if table == "dashboard_daily_metrics": filters["and"] = f"(metric_date.gte.{start},metric_date.lte.{end})"
        kwargs = {"order": "started_at.desc"} if table == "cron_job_runs" else {}
        if table in {"fbits_orders", "ig_media"}:
            from .periods import resolve_period
            since, until = resolve_period(start=start, end=end, max_days=366).utc_bounds()
            column = "order_date" if table == "fbits_orders" else "timestamp"
            filters["and"] = f"({column}.gte.{since.isoformat()},{column}.lte.{until.isoformat()})"
            if table == "ig_media": filters["or"] = "(media_product_type.is.null,media_product_type.neq.STORY)"
            kwargs["order"] = f"{column}.desc"
        rows = await sb_select(table, select=select, filters=filters, limit=limit, **kwargs)
        return [row for row in rows if row.get("client_id") == client_id]
    reads = await asyncio.gather(*(read(*q) for q in queries), return_exceptions=True)
    failed = {queries[i][0] for i, result in enumerate(reads) if isinstance(result, BaseException)}
    generic, meta, jobs, locks, daily, orders, media = [r if isinstance(r, list) else [] for r in reads]
    now = datetime.now(timezone.utc)
    sources = []
    for provider in FIELDS.keys() | {"fbits"}:
        rows = [r for r in (meta if provider in {"instagram", "meta_ads"} else generic)
                if (r.get("platform") if provider in {"instagram", "meta_ads"} else r.get("provider")) == provider
                and not r.get("disconnected_at") and r.get("status") != "disconnected"]
        # Multiple active connections require an explicit choice; never mix clocks.
        connection = rows[0] if len(rows) == 1 else None
        dependencies = {"cron_job_runs", "cron_locks", "meta_connections" if provider in {"instagram", "meta_ads"} else "integration_connections"}
        dependencies.add("fbits_orders" if provider == "fbits" else "dashboard_daily_metrics")
        source = compose_source(provider, connection, jobs, locks, daily if connection else [], start, end, now=now, read_error=bool(failed & dependencies))
        if len(rows) > 1: source.update(state="attention", error_code="CONNECTION_AMBIGUOUS")
        if provider == "fbits" and connection and orders:
            source.update(last_data_at=orders[0].get("order_date"), last_data_semantics="latest_persisted_order_timestamp_in_period")
            if source["state"] == "no_data" and source["last_successful_sync_at"]:
                source["state"] = "attention"
        sources.append(source)
        if provider == "instagram":
            content = {**source, "provider": "instagram_content", "dataset": "ig_media",
                       "last_data_at": media[0].get("timestamp") if connection and media else None,
                       "last_data_semantics": "latest_publication_timestamp_in_period", "coverage_end": None}
            if content["state"] == "synced": content["state"] = "attention"
            if "ig_media" in failed: content.update(state="attention", error_code="FRESHNESS_READ_FAILED")
            sources.append(content)
        if provider == "fbits":
            official = official_source(connection, start, end, now=now)
            if "integration_connections" in failed: official.update(state="attention", error_code="FRESHNESS_READ_FAILED")
            sources.append(official)
    return {"client_id": client_id, "period": {"start": start, "end": end}, "sources": sorted(sources, key=lambda s: s["provider"])}
