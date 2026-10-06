from __future__ import annotations

from datetime import datetime, timedelta, timezone, date
import time
from typing import Any, Dict, List
import json
import httpx

from .connection_resolver import resolve_connection_for_scope
from .ig_supabase import sb_select
from .periods import resolve_period
from .instagram_organic_history import aggregate_instagram_months
from .request_performance import measured


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_date(value: str | None) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except Exception:
        return None


def _resolve_window(
    *,
    days: int,
    start: str | None,
    end: str | None,
) -> tuple[datetime, datetime | None]:
    if _parse_date(start) and _parse_date(end):
        return resolve_period(start=start, end=end, days=days, max_days=3650).utc_bounds()

    safe_days = max(1, min(days, 3650))
    since_dt = _utc_now() - timedelta(days=safe_days - 1)
    return since_dt, None


def _to_insights(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _is_missing_column_error(exc: httpx.HTTPStatusError, column_name: str) -> bool:
    if exc.response is None:
        return False
    if exc.response.status_code not in {400, 404}:
        return False
    body = str(exc.response.text or "").lower()
    col = str(column_name or "").lower()
    return col in body and ("column" in body or "schema cache" in body)


@measured("data_media")
async def get_media(
    client_id: str,
    connection_id: str | None = None,
    days: int = 365,
    start: str | None = None,
    end: str | None = None,
    limit: int = 120,
    offset: int = 0,
) -> Dict[str, Any]:
    started = time.perf_counter()
    safe_limit = max(1, min(int(limit or 120), 1000))
    safe_offset = max(0, int(offset or 0))
    since_dt, until_dt = _resolve_window(days=days, start=start, end=end)
    period_requested = bool(str(start or "").strip() or str(end or "").strip())
    requested_connection = str(connection_id or "").strip()
    resolved_conn = await resolve_connection_for_scope(
        client_id=client_id,
        platform="instagram",
        connection_type="organic",
        requested_connection_id=requested_connection or None,
    )
    resolved_connection_id = str(resolved_conn.get("connection_id") or "").strip()
    connection_source = str(resolved_conn.get("source") or "none").strip() or "none"
    since = since_dt.isoformat()
    table_name = "ig_media"
    print(
        f"[media_read] table={table_name} client_id_received={client_id} "
        f"connection_id_requested={requested_connection or '-'} "
        f"connection_id_resolved={resolved_connection_id or '-'} "
        f"connection_source={connection_source} "
        f"since={since} until={until_dt.isoformat() if until_dt else '-'} "
        f"limit={safe_limit} offset={safe_offset}"
    )

    try:
        filters = {"client_id": f"eq.{client_id}"}
        if until_dt:
            filters["and"] = f"(timestamp.gte.{since_dt.isoformat()},timestamp.lte.{until_dt.isoformat()})"
        else:
            filters["timestamp"] = f"gte.{since}"
        rows: List[Dict[str, Any]] = []
        read_mode = "timestamp_filter"
        if resolved_connection_id:
            conn_filters = dict(filters)
            conn_filters["connection_id"] = f"eq.{resolved_connection_id}"
            try:
                rows = await sb_select(
                    table_name,
                    filters=conn_filters,
                    order="timestamp.desc,id.desc",
                    limit=safe_limit,
                    offset=safe_offset,
                )
                read_mode = "timestamp_filter_connection_scoped"
            except httpx.HTTPStatusError as exc:
                if not _is_missing_column_error(exc, "connection_id"):
                    raise
                rows = await sb_select(
                    table_name,
                    filters=filters,
                    order="timestamp.desc,id.desc",
                    limit=safe_limit,
                    offset=safe_offset,
                )
                read_mode = "timestamp_filter_connection_column_missing"
        else:
            rows = await sb_select(
                table_name,
                filters=filters,
                order="timestamp.desc,id.desc",
                limit=safe_limit,
                offset=safe_offset,
            )
        print(
            f"[media_read] table={table_name} client_id_resolved={client_id} "
            f"rows_read={len(rows)} mode={read_mode}"
        )
        # Compat legado: só tenta fallback sem timestamp quando NÃO há período explícito.
        # Para períodos explícitos (start/end), respeita estritamente a janela solicitada.
        if not rows and not period_requested:
            fallback_filters = {"client_id": f"eq.{client_id}"}
            if resolved_connection_id:
                fallback_filters["connection_id"] = f"eq.{resolved_connection_id}"
            rows = await sb_select(
                table_name,
                filters=fallback_filters,
                order="created_at.desc",
                limit=safe_limit,
                offset=safe_offset,
            )
            print(
                f"[media_read] table={table_name} client_id_resolved={client_id} "
                f"rows_read={len(rows)} mode=fallback_no_timestamp"
            )
        elif not rows and period_requested:
            print(
                f"[media_read] table={table_name} client_id_resolved={client_id} "
                "rows_read=0 mode=timestamp_filter_strict"
            )
    except httpx.HTTPStatusError as exc:
        # Compat: ambiente ainda sem tabela ig_media.
        if exc.response is None or exc.response.status_code != 404:
            raise
        rows = []
        print(f"[media_read] table={table_name} client_id_resolved={client_id} rows_read=0 mode=table_missing")

    media: List[Dict[str, Any]] = []
    for r in rows:
        media.append(
            {
                "id": str(r.get("media_id") or ""),
                "media_type": r.get("media_type"),
                "media_product_type": r.get("media_product_type"),
                "caption": r.get("caption"),
                "timestamp": r.get("timestamp"),
                "permalink": r.get("permalink"),
                "thumb_url": r.get("thumb_url") or r.get("thumbnail_url") or r.get("media_url"),
                "insights": _to_insights(r.get("insights_json")),
            }
        )

    last_media_timestamp = ""
    for item in media:
        ts = str(item.get("timestamp") or "").strip()
        if ts:
            last_media_timestamp = ts
            break

    print(
        f"[media_read] table={table_name} client_id_resolved={client_id} "
        f"rows_returned={len(media)} last_media_timestamp={last_media_timestamp or '-'} "
        f"duration_ms={int((time.perf_counter() - started) * 1000)}"
    )
    has_more = len(media) >= safe_limit
    next_offset = safe_offset + safe_limit if has_more else None
    return {
        "ok": True,
        "client_id": client_id,
        "connection_id": resolved_connection_id or None,
        "days": days,
        "start": start,
        "end": end,
        "limit": safe_limit,
        "offset": safe_offset,
        "has_more": has_more,
        "next_offset": next_offset,
        "media": media,
    }


def _month_key_from_timestamp(value: str | None) -> str:
    text = str(value or "").strip()
    if len(text) >= 7 and text[4:5] == "-" and text[5:7].isdigit():
        return text[:7]
    return ""


async def _read_monthly_pages(table: str, *, select: str, filters: dict, order: str, limit: int) -> list:
    rows = []
    for offset in range(0, 200000, 1000):
        page = await sb_select(table, select=select, filters=filters, order=order + ",id.asc", limit=1000, offset=offset)
        rows.extend(page)
        if len(page) < 1000:
            return rows
    raise RuntimeError("Paginação mensal de publicações incompleta.")


@measured("data_monthly")
async def get_media_monthly(
    client_id: str,
    connection_id: str | None = None,
    days: int = 3650,
    start: str | None = None,
    end: str | None = None,
) -> Dict[str, Any]:
    started = time.perf_counter()
    since_dt, until_dt = _resolve_window(days=days, start=start, end=end)
    requested_connection = str(connection_id or "").strip()
    resolved_conn = await resolve_connection_for_scope(
        client_id=client_id,
        platform="instagram",
        connection_type="organic",
        requested_connection_id=requested_connection or None,
    )
    resolved_connection_id = str(resolved_conn.get("connection_id") or "").strip()
    connection_source = str(resolved_conn.get("source") or "none").strip() or "none"
    filters = {"client_id": f"eq.{client_id}"}
    if resolved_connection_id:
        filters["connection_id"] = f"eq.{resolved_connection_id}"
    if until_dt:
        filters["and"] = f"(timestamp.gte.{since_dt.isoformat()},timestamp.lte.{until_dt.isoformat()})"
    else:
        filters["timestamp"] = f"gte.{since_dt.isoformat()}"

    read_mode = "monthly_connection_scoped" if resolved_connection_id else "monthly_client_scoped"
    try:
        rows = await _read_monthly_pages(
            "ig_media",
            select="timestamp,media_product_type,insights_json",
            filters=filters,
            order="timestamp.asc",
            limit=10000,
        )
    except httpx.HTTPStatusError as exc:
        schema_pending = (
            exc.response is not None
            and exc.response.status_code == 404
        ) or _is_missing_column_error(exc, "media_product_type") or _is_missing_column_error(exc, "insights_json")
        if schema_pending:
            rows = []
            read_mode = "monthly_schema_pending"
        elif resolved_connection_id and _is_missing_column_error(exc, "connection_id"):
            filters_no_conn = {"client_id": f"eq.{client_id}"}
            if until_dt:
                filters_no_conn["and"] = f"(timestamp.gte.{since_dt.isoformat()},timestamp.lte.{until_dt.isoformat()})"
            else:
                filters_no_conn["timestamp"] = f"gte.{since_dt.isoformat()}"
            try:
                rows = await _read_monthly_pages(
                    "ig_media",
                    select="timestamp,media_product_type,insights_json",
                    filters=filters_no_conn,
                    order="timestamp.asc",
                    limit=10000,
                )
                read_mode = "monthly_connection_column_missing"
            except httpx.HTTPStatusError as fallback_exc:
                fallback_schema_pending = (
                    fallback_exc.response is not None
                    and fallback_exc.response.status_code == 404
                ) or _is_missing_column_error(fallback_exc, "media_product_type") or _is_missing_column_error(
                    fallback_exc, "insights_json"
                )
                if not fallback_schema_pending:
                    raise
                rows = []
                read_mode = "monthly_schema_pending"
        else:
            raise

    months = []
    for aggregate in aggregate_instagram_months(rows):
        metrics = aggregate["metrics"]
        months.append({
            **aggregate,
            "posts": aggregate["feed_count"],
            "reels": aggregate["reels_count"],
            "reach": metrics["reach"]["value"],
            "views": metrics["views"]["value"],
            "interactions": metrics["total_interactions"]["value"],
            "profile_visits": metrics["profile_visits"]["value"],
            "likes": metrics["likes"]["value"],
            "comments": metrics["comments"]["value"],
            "shares": metrics["shares"]["value"],
            "saved": metrics["saved"]["value"],
        })
    print(
        "[media_monthly] result "
        f"client_id={client_id} connection_id_requested={requested_connection or '-'} "
        f"connection_id_resolved={resolved_connection_id or '-'} connection_source={connection_source} "
        f"rows={len(rows)} months={len(months)} mode={read_mode} "
        f"duration_ms={int((time.perf_counter() - started) * 1000)}"
    )
    return {
        "ok": True,
        "client_id": client_id,
        "connection_id": resolved_connection_id or None,
        "days": days,
        "start": start,
        "end": end,
        "months": months,
    }
