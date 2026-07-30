from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from .ga4_client import run_ga4_report
from .ga4_reporting import GA4ReportPeriod, resolve_ga4_report_period
from .ig_supabase import sb_delete, sb_insert_many, sb_upsert
from .job_runs import finish_job_run, start_job_run
from .single_tenant import resolve_ga4_context_for_client

GA4_FUNNEL_EVENTS = ("view_item", "add_to_cart", "begin_checkout", "purchase")
GA4_REPORT_METRICS = (
    "sessions",
    "activeUsers",
    "totalUsers",
    "eventCount",
    "ecommercePurchases",
    "purchaseRevenue",
    "totalRevenue",
)
GA4_OPTIONAL_UPSERT_COLUMNS = ("raw_payload",)


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any) -> int:
    try:
        if value is None or value == "":
            return 0
        return int(float(value))
    except Exception:
        return 0


def _safe_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _http_error_body(exc: httpx.HTTPStatusError) -> str:
    try:
        return (exc.response.text or "").strip()
    except Exception:
        return ""


def _sanitize_payload_value(value: Any) -> Any:
    if isinstance(value, dict):
        if "report" in value:
            values = value.get("values")
            raw_row = value.get("raw_row")
            return {
                "report": _safe_str(value.get("report")),
                "values_keys": sorted(values.keys()) if isinstance(values, dict) else [],
                "raw_row_keys": sorted(raw_row.keys()) if isinstance(raw_row, dict) else [],
            }
        return {str(key): _sanitize_payload_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_payload_value(item) for item in value[:5]]
    return value


def _sanitize_payload_item(row: Dict[str, Any]) -> Dict[str, Any]:
    sanitized: Dict[str, Any] = {}
    for key, value in row.items():
        sanitized[key] = _sanitize_payload_value(value)
    return sanitized


def _serialize_payload_log(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return str(value)


def _strip_columns(rows: List[Dict[str, Any]], columns: tuple[str, ...]) -> List[Dict[str, Any]]:
    stripped: List[Dict[str, Any]] = []
    for row in rows:
        next_row = dict(row)
        for column in columns:
            next_row.pop(column, None)
        stripped.append(next_row)
    return stripped


def _missing_optional_columns_from_error(exc: httpx.HTTPStatusError) -> tuple[str, ...]:
    body = _http_error_body(exc).lower()
    return tuple(column for column in GA4_OPTIONAL_UPSERT_COLUMNS if column.lower() in body)


def _is_missing_unique_constraint_error(exc: httpx.HTTPStatusError) -> bool:
    body = _http_error_body(exc).lower()
    return "42p10" in body or "no unique or exclusion constraint matching the on conflict specification" in body


def _log_upsert_failure(
    *,
    table: str,
    rows: List[Dict[str, Any]],
    on_conflict: str,
    exc: httpx.HTTPStatusError,
) -> None:
    first_item = _sanitize_payload_item(rows[0]) if rows else {}
    columns = sorted(rows[0].keys()) if rows else []
    print(
        "[ga4_sync][upsert_error] "
        f"table={table} "
        f"on_conflict={on_conflict} "
        f"rows={len(rows)} "
        f"columns={_serialize_payload_log(columns)} "
        f"first_item={_serialize_payload_log(first_item)} "
        f"supabase_error={_serialize_payload_log(_http_error_body(exc))}"
    )


def _replace_period_filters(rows: List[Dict[str, Any]]) -> Dict[str, str]:
    client_id = _safe_str(rows[0].get("client_id")) if rows else ""
    property_id = _safe_str(rows[0].get("property_id")) if rows else ""
    stat_dates = sorted({_safe_str(row.get("stat_date")) for row in rows if _safe_str(row.get("stat_date"))})

    filters: Dict[str, str] = {}
    if client_id:
        filters["client_id"] = f"eq.{client_id}"
    if property_id:
        filters["property_id"] = f"eq.{property_id}"
    if len(stat_dates) == 1:
        filters["stat_date"] = f"eq.{stat_dates[0]}"
    elif stat_dates:
        filters["and"] = f"(stat_date.gte.{stat_dates[0]},stat_date.lte.{stat_dates[-1]})"
    return filters


async def _replace_period_rows(
    *,
    table: str,
    rows: List[Dict[str, Any]],
) -> None:
    filters = _replace_period_filters(rows)
    print(
        "[ga4_sync][replace_period] "
        f"table={table} "
        f"rows={len(rows)} "
        f"filters={_serialize_payload_log(filters)}"
    )
    if filters:
        await sb_delete(table, filters=filters, returning="minimal")
    await sb_insert_many(table, rows, returning="minimal")


async def _upsert_with_compatibility(
    *,
    table: str,
    rows: List[Dict[str, Any]],
    on_conflict: str,
) -> None:
    attempt_rows = rows

    for _ in range(2):
        try:
            await sb_upsert(table, attempt_rows, on_conflict=on_conflict)
            return
        except httpx.HTTPStatusError as exc:
            _log_upsert_failure(table=table, rows=attempt_rows, on_conflict=on_conflict, exc=exc)

            missing_columns = _missing_optional_columns_from_error(exc)
            if missing_columns:
                attempt_rows = _strip_columns(attempt_rows, missing_columns)
                print(
                    "[ga4_sync][upsert_retry] "
                    f"table={table} "
                    f"removed_columns={_serialize_payload_log(list(missing_columns))}"
                )
                continue

            if _is_missing_unique_constraint_error(exc):
                await _replace_period_rows(table=table, rows=attempt_rows)
                return

            raise

    await sb_upsert(table, attempt_rows, on_conflict=on_conflict)


def _ga4_date_to_iso(value: Any) -> Optional[str]:
    text = _safe_str(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def _parse_source_medium(value: Any) -> tuple[str, str]:
    source_medium = _safe_str(value)
    if not source_medium:
        return ("", "")
    if " / " in source_medium:
        source, medium = source_medium.split(" / ", 1)
        return (source.strip(), medium.strip())
    return (source_medium, "")


def _to_report_date(day: datetime | Any) -> str:
    if hasattr(day, "isoformat"):
        return day.isoformat()
    return _safe_str(day)


def _event_funnel_by_date(event_rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    by_date: Dict[str, Dict[str, int]] = {}
    for row in event_rows:
        values = row.get("values") or {}
        stat_date = _ga4_date_to_iso(values.get("date"))
        event_name = _safe_str(values.get("eventName"))
        if not stat_date or event_name not in GA4_FUNNEL_EVENTS:
            continue
        bucket = by_date.setdefault(
            stat_date,
            {
                "view_item_count": 0,
                "add_to_cart_count": 0,
                "begin_checkout_count": 0,
                "purchase_count": 0,
            },
        )
        metric_value = _safe_int(values.get("eventCount"))
        if event_name == "view_item":
            bucket["view_item_count"] += metric_value
        elif event_name == "add_to_cart":
            bucket["add_to_cart_count"] += metric_value
        elif event_name == "begin_checkout":
            bucket["begin_checkout_count"] += metric_value
        elif event_name == "purchase":
            bucket["purchase_count"] += metric_value
    return by_date


def _daily_upsert_rows(
    *,
    client_id: str,
    property_id: str,
    daily_rows: List[Dict[str, Any]],
    funnel_by_date: Dict[str, Dict[str, int]],
) -> List[Dict[str, Any]]:
    now_iso = _utc_now_iso()
    rows: List[Dict[str, Any]] = []
    for row in daily_rows:
        values = row.get("values") or {}
        stat_date = _ga4_date_to_iso(values.get("date"))
        if not stat_date:
            continue
        funnel = funnel_by_date.get(
            stat_date,
            {
                "view_item_count": 0,
                "add_to_cart_count": 0,
                "begin_checkout_count": 0,
                "purchase_count": 0,
            },
        )
        rows.append(
            {
                "client_id": client_id,
                "property_id": property_id,
                "stat_date": stat_date,
                "sessions": _safe_int(values.get("sessions")),
                "active_users": _safe_int(values.get("activeUsers")),
                "total_users": _safe_int(values.get("totalUsers")),
                "event_count": _safe_int(values.get("eventCount")),
                "ecommerce_purchases": _safe_int(values.get("ecommercePurchases")),
                "purchase_revenue": round(_safe_float(values.get("purchaseRevenue")), 2),
                "total_revenue": round(_safe_float(values.get("totalRevenue")), 2),
                "view_item_count": funnel["view_item_count"],
                "add_to_cart_count": funnel["add_to_cart_count"],
                "begin_checkout_count": funnel["begin_checkout_count"],
                "purchase_count": funnel["purchase_count"],
                "updated_at": now_iso,
            }
        )
    return rows


def _channel_upsert_rows(
    *,
    client_id: str,
    property_id: str,
    rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    now_iso = _utc_now_iso()
    payload_rows: List[Dict[str, Any]] = []
    for row in rows:
        values = row.get("values") or {}
        stat_date = _ga4_date_to_iso(values.get("date"))
        source_medium = _safe_str(values.get("sessionSourceMedium"))
        if not stat_date or not source_medium:
            continue
        source, medium = _parse_source_medium(source_medium)
        payload_rows.append(
            {
                "client_id": client_id,
                "property_id": property_id,
                "stat_date": stat_date,
                "source_medium": source_medium,
                "source": source,
                "medium": medium,
                "sessions": _safe_int(values.get("sessions")),
                "active_users": _safe_int(values.get("activeUsers")),
                "total_users": _safe_int(values.get("totalUsers")),
                "event_count": _safe_int(values.get("eventCount")),
                "ecommerce_purchases": _safe_int(values.get("ecommercePurchases")),
                "purchase_revenue": round(_safe_float(values.get("purchaseRevenue")), 2),
                "total_revenue": round(_safe_float(values.get("totalRevenue")), 2),
                "updated_at": now_iso,
            }
        )
    return payload_rows


def _campaign_upsert_rows(
    *,
    client_id: str,
    property_id: str,
    rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    now_iso = _utc_now_iso()
    payload_rows: List[Dict[str, Any]] = []
    for row in rows:
        values = row.get("values") or {}
        stat_date = _ga4_date_to_iso(values.get("date"))
        campaign_name = _safe_str(values.get("sessionCampaignName")) or "(not set)"
        source_medium = _safe_str(values.get("sessionSourceMedium"))
        source, medium = _parse_source_medium(source_medium)
        if not stat_date:
            continue
        payload_rows.append(
            {
                "client_id": client_id,
                "property_id": property_id,
                "stat_date": stat_date,
                "campaign_name": campaign_name,
                "source_medium": source_medium,
                "source": source,
                "medium": medium,
                "sessions": _safe_int(values.get("sessions")),
                "active_users": _safe_int(values.get("activeUsers")),
                "total_users": _safe_int(values.get("totalUsers")),
                "event_count": _safe_int(values.get("eventCount")),
                "ecommerce_purchases": _safe_int(values.get("ecommercePurchases")),
                "purchase_revenue": round(_safe_float(values.get("purchaseRevenue")), 2),
                "total_revenue": round(_safe_float(values.get("totalRevenue")), 2),
                "updated_at": now_iso,
            }
        )
    return payload_rows


def _event_upsert_rows(
    *,
    client_id: str,
    property_id: str,
    rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    now_iso = _utc_now_iso()
    payload_rows: List[Dict[str, Any]] = []
    for row in rows:
        values = row.get("values") or {}
        stat_date = _ga4_date_to_iso(values.get("date"))
        event_name = _safe_str(values.get("eventName"))
        if not stat_date or not event_name:
            continue
        payload_rows.append(
            {
                "client_id": client_id,
                "property_id": property_id,
                "stat_date": stat_date,
                "event_name": event_name,
                "event_count": _safe_int(values.get("eventCount")),
                "total_users": _safe_int(values.get("totalUsers")),
                "updated_at": now_iso,
            }
        )
    return payload_rows


async def sync_ga4_for_period(
    *,
    since: Optional[str] = None,
    until: Optional[str] = None,
    days: int = 30,
    client_id: Optional[str] = None,
    property_id: Optional[str] = None,
    job_name: str = "ga4_sync_manual",
    trigger_source: str = "manual_api",
    record_job_run: bool = True,
) -> Dict[str, Any]:
    context_client_id, context_property_id = resolve_ga4_context_for_client(client_id)
    resolved_client_id = _safe_str(client_id) or context_client_id
    resolved_property_id = _safe_str(property_id) or context_property_id
    period = resolve_ga4_report_period(start=since, end=until, days=days)

    job_run = None
    if record_job_run:
        job_run = await start_job_run(
            job_name=job_name,
            client_id=resolved_client_id,
            trigger_source=trigger_source,
            payload_json={
                "property_id": resolved_property_id,
                "period": {
                    "start": period.start.isoformat(),
                    "end": period.end.isoformat(),
                    "days": period.days,
                },
            },
        )

    try:
        daily_report = await run_ga4_report(
            property_id=resolved_property_id,
            start_date=period.start.isoformat(),
            end_date=period.end.isoformat(),
            dimensions=("date",),
            metrics=GA4_REPORT_METRICS,
            order_bys=[{"dimension": {"dimensionName": "date"}}],
        )
        channel_report = await run_ga4_report(
            property_id=resolved_property_id,
            start_date=period.start.isoformat(),
            end_date=period.end.isoformat(),
            dimensions=("date", "sessionSourceMedium"),
            metrics=GA4_REPORT_METRICS,
            order_bys=[{"dimension": {"dimensionName": "date"}}],
        )
        campaign_report = await run_ga4_report(
            property_id=resolved_property_id,
            start_date=period.start.isoformat(),
            end_date=period.end.isoformat(),
            dimensions=("date", "sessionCampaignName", "sessionSourceMedium"),
            metrics=GA4_REPORT_METRICS,
            order_bys=[{"dimension": {"dimensionName": "date"}}],
        )
        event_report = await run_ga4_report(
            property_id=resolved_property_id,
            start_date=period.start.isoformat(),
            end_date=period.end.isoformat(),
            dimensions=("date", "eventName"),
            metrics=("eventCount", "totalUsers"),
            order_bys=[{"dimension": {"dimensionName": "date"}}],
        )

        funnel_by_date = _event_funnel_by_date(event_report.get("rows") or [])

        daily_rows = _daily_upsert_rows(
            client_id=resolved_client_id,
            property_id=resolved_property_id,
            daily_rows=daily_report.get("rows") or [],
            funnel_by_date=funnel_by_date,
        )
        channel_rows = _channel_upsert_rows(
            client_id=resolved_client_id,
            property_id=resolved_property_id,
            rows=channel_report.get("rows") or [],
        )
        campaign_rows = _campaign_upsert_rows(
            client_id=resolved_client_id,
            property_id=resolved_property_id,
            rows=campaign_report.get("rows") or [],
        )
        event_rows = _event_upsert_rows(
            client_id=resolved_client_id,
            property_id=resolved_property_id,
            rows=event_report.get("rows") or [],
        )

        if daily_rows:
            await _upsert_with_compatibility(
                table="ga4_daily_stats",
                rows=daily_rows,
                on_conflict="client_id,property_id,stat_date",
            )
        if channel_rows:
            await _upsert_with_compatibility(
                table="ga4_channel_stats",
                rows=channel_rows,
                on_conflict="client_id,property_id,stat_date,source_medium",
            )
        if campaign_rows:
            await _upsert_with_compatibility(
                table="ga4_campaign_stats",
                rows=campaign_rows,
                on_conflict="client_id,property_id,stat_date,campaign_name,source_medium",
            )
        if event_rows:
            await _upsert_with_compatibility(
                table="ga4_event_stats",
                rows=event_rows,
                on_conflict="client_id,property_id,stat_date,event_name",
            )

        rows_upserted = len(daily_rows) + len(channel_rows) + len(campaign_rows) + len(event_rows)
        payload = {
            "ok": True,
            "client_id": resolved_client_id,
            "property_id": resolved_property_id,
            "period": {
                "start": period.start.isoformat(),
                "end": period.end.isoformat(),
                "days": period.days,
            },
            "rows_upserted": {
                "daily": len(daily_rows),
                "channels": len(channel_rows),
                "campaigns": len(campaign_rows),
                "events": len(event_rows),
                "total": rows_upserted,
            },
            "source_row_count": {
                "daily": _safe_int(daily_report.get("row_count")),
                "channels": _safe_int(channel_report.get("row_count")),
                "campaigns": _safe_int(campaign_report.get("row_count")),
                "events": _safe_int(event_report.get("row_count")),
            },
            "job_run_id": _safe_str((job_run or {}).get("id")) or None,
        }

        if record_job_run and job_run and _safe_str(job_run.get("id")):
            await finish_job_run(
                _safe_str(job_run["id"]),
                status="success",
                rows_upserted=rows_upserted,
                payload_json=payload,
                client_id=resolved_client_id,
            )

        return payload
    except Exception as exc:
        if record_job_run and job_run and _safe_str(job_run.get("id")):
            await finish_job_run(
                _safe_str(job_run["id"]),
                status="error",
                error=str(exc),
                payload_json={
                    "property_id": resolved_property_id,
                    "period": {
                        "start": period.start.isoformat(),
                        "end": period.end.isoformat(),
                        "days": period.days,
                    },
                },
                client_id=resolved_client_id,
            )
        raise
