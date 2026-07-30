import calendar
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple
import httpx

from .connection_resolver import resolve_connection_for_scope
from .ig_supabase import sb_select


def _resolve_client_id(client_id: str | None) -> str:
    cid = (client_id or "").strip()
    if not cid:
        raise RuntimeError("client_id é obrigatório")
    return cid


def _is_missing_column_error(exc: httpx.HTTPStatusError, column_name: str) -> bool:
    if exc.response is None:
        return False
    if exc.response.status_code not in {400, 404}:
        return False
    body = str(exc.response.text or "").lower()
    col = str(column_name or "").lower()
    return col in body and ("column" in body or "schema cache" in body)


def _growth(current: int, previous: int) -> float:
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - previous) / previous) * 100, 2)


def _followers_growth(rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    first = int(rows[0].get("followers_count") or 0)
    last = int(rows[-1].get("followers_count") or 0)
    return last - first


def _month_range(month: str):
    y = int(month[:4])
    m = int(month[5:7])
    start = date(y, m, 1)
    last_day = calendar.monthrange(y, m)[1]
    end = date(y, m, last_day)
    return start.isoformat(), end.isoformat()


def _parse_iso_date(value: str | None) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except Exception:
        return None


def _resolve_window(
    *,
    days: int = 30,
    month: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> Tuple[date, date]:
    start_date = _parse_iso_date(start)
    end_date = _parse_iso_date(end)
    if start_date and end_date:
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        return start_date, end_date

    if month:
        month_start, month_end = _month_range(month)
        return date.fromisoformat(month_start), date.fromisoformat(month_end)

    safe_days = max(1, min(int(days or 30), 3650))
    until = datetime.now(timezone.utc).date()
    since = until - timedelta(days=safe_days - 1)
    return since, until


def _empty_totals() -> Dict[str, int]:
    return {
        "impressions": 0,
        "reach": 0,
        "total_interactions": 0,
        "website_clicks": 0,
        "profile_views": 0,
        "accounts_engaged": 0,
        # compat temporária
        "interactions": 0,
    }


def _sum_snapshot_rows(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    totals = _empty_totals()
    for r in rows:
        totals["impressions"] += int(r.get("impressions_day") or 0)
        totals["reach"] += int(r.get("reach_day") or 0)
        totals["total_interactions"] += int(r.get("total_interactions_day") or 0)
        totals["website_clicks"] += int(r.get("website_clicks_day") or 0)
        totals["profile_views"] += int(r.get("profile_views_day") or 0)
        totals["accounts_engaged"] += int(r.get("accounts_engaged_day") or 0)
    totals["interactions"] = int(totals["total_interactions"])
    return totals


def _sum_metric(rows: List[Dict[str, Any]], key: str) -> int:
    return sum(int(r.get(key) or 0) for r in rows)


def _max_metric(rows: List[Dict[str, Any]], key: str) -> int:
    if not rows:
        return 0
    return max(int(r.get(key) or 0) for r in rows)


def _followers_current(rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    return int(rows[-1].get("followers_count") or 0)


def _build_period_totals(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    totals = {
        "impressions": _sum_metric(rows, "impressions_day"),
        "reach": _sum_metric(rows, "reach_day"),
        "total_interactions": _sum_metric(rows, "total_interactions_day"),
        "website_clicks": _sum_metric(rows, "website_clicks_day"),
        "profile_views": _sum_metric(rows, "profile_views_day"),
        "accounts_engaged": _sum_metric(rows, "accounts_engaged_day"),
        "followers_growth": _followers_growth(rows),
        "followers_current": _followers_current(rows),
    }
    totals["interactions"] = int(totals["total_interactions"])
    return totals


def _bucket_start(snapshot_date: date, granularity: str) -> date:
    if granularity == "weekly":
        return snapshot_date - timedelta(days=snapshot_date.weekday())
    if granularity == "monthly":
        return snapshot_date.replace(day=1)
    return snapshot_date


def _build_series(rows: List[Dict[str, Any]], granularity: str) -> List[Dict[str, Any]]:
    if not rows:
        return []

    buckets: Dict[date, List[Dict[str, Any]]] = {}
    for row in rows:
        row_date = _parse_iso_date(str(row.get("snapshot_date") or ""))
        if not row_date:
            continue
        start_date = _bucket_start(row_date, granularity)
        buckets.setdefault(start_date, []).append(row)

    out: List[Dict[str, Any]] = []
    for start_date in sorted(buckets.keys()):
        bucket_rows = sorted(
            buckets[start_date],
            key=lambda item: str(item.get("snapshot_date") or ""),
        )
        if not bucket_rows:
            continue
        end_date = _parse_iso_date(str(bucket_rows[-1].get("snapshot_date") or "")) or start_date
        totals = _build_period_totals(bucket_rows)

        out.append(
            {
                "date": end_date.isoformat(),
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "impressions": int(totals["impressions"]),
                "reach": int(totals["reach"]),
                "total_interactions": int(totals["total_interactions"]),
                "website_clicks": int(totals["website_clicks"]),
                "profile_views": int(totals["profile_views"]),
                "accounts_engaged": int(totals["accounts_engaged"]),
                "followers": int(totals["followers_current"]),
                # compat temporária com front antigo
                "interactions": int(totals["total_interactions"]),
            }
        )
    return out

def _build_media_period_totals(media_rows: List[Dict[str, Any]]) -> Dict[str, int]:
    totals = {
        "impressions": 0,
        "reach": 0,
        "total_interactions": 0,
        "website_clicks": 0,
        "profile_views": 0,
        "accounts_engaged": 0,
        "followers_growth": 0,
        "followers_current": 0,
        "interactions": 0,
    }

    for m in media_rows:
        ins = m.get("insights_json") or {}
        if not isinstance(ins, dict):
            ins = {}

        totals["impressions"] += int(ins.get("impressions") or ins.get("views") or 0)
        totals["reach"] += int(ins.get("reach") or 0)
        totals["total_interactions"] += int(ins.get("total_interactions") or 0)
        totals["profile_views"] += int(ins.get("profile_visits") or 0)

    totals["interactions"] = int(totals["total_interactions"])
    return totals


async def _query_snapshot_rows(
    client_id: str,
    since: date,
    until: date,
    connection_id: str | None = None,
) -> List[Dict[str, Any]]:
    filters = {
        "client_id": f"eq.{client_id}",
        "and": f"(snapshot_date.gte.{since.isoformat()},snapshot_date.lte.{until.isoformat()})",
    }
    scoped_connection_id = str(connection_id or "").strip()
    if scoped_connection_id:
        filters["connection_id"] = f"eq.{scoped_connection_id}"
    try:
        return await sb_select(
            "ig_profile_snapshots",
            filters=filters,
            order="snapshot_date.asc",
            limit=5000,
        )
    except httpx.HTTPStatusError as exc:
        if not (scoped_connection_id and _is_missing_column_error(exc, "connection_id")):
            raise
        filters.pop("connection_id", None)
        print(
            "[dashboard][organic][snapshot_schema_pending] "
            f"client_id={client_id} connection_id={scoped_connection_id} missing=connection_id"
        )
        return await sb_select(
            "ig_profile_snapshots",
            filters=filters,
            order="snapshot_date.asc",
            limit=5000,
        )

async def get_dashboard(
    client_id: str | None,
    connection_id: str | None = None,
    days: int = 30,
    month: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> Dict[str, Any]:
    cid = _resolve_client_id(client_id)
    requested_connection_id = str(connection_id or "").strip()
    resolved_connection = await resolve_connection_for_scope(
        client_id=cid,
        platform="instagram",
        connection_type="organic",
        requested_connection_id=requested_connection_id or None,
    )
    resolved_connection_id = str(resolved_connection.get("connection_id") or "").strip()
    connection_source = str(resolved_connection.get("source") or "none").strip() or "none"
    since_date, until_date = _resolve_window(days=days, month=month, start=start, end=end)
    window_days = (until_date - since_date).days + 1
    since_iso = since_date.isoformat()
    until_iso = until_date.isoformat()

    print(
        "[dashboard][organic] request "
        f"client_id={cid} connection_id_requested={requested_connection_id or '-'} "
        f"connection_id_resolved={resolved_connection_id or '-'} connection_source={connection_source} "
        f"start={since_iso} end={until_iso} month={str(month or '').strip() or '-'}"
    )

    rows = await _query_snapshot_rows(cid, since_date, until_date, resolved_connection_id or None)

    media_filters = {
        "client_id": f"eq.{cid}",
        "and": f"(timestamp.gte.{since_iso}T00:00:00,timestamp.lte.{until_iso}T23:59:59)",
    }
    if resolved_connection_id:
        media_filters["connection_id"] = f"eq.{resolved_connection_id}"

    media_read_mode = "period_media_connection_scoped" if resolved_connection_id else "period_media_client_scoped"
    try:
        media_rows_period = await sb_select(
            "ig_media",
            filters=media_filters,
            order="timestamp.asc",
            limit=5000,
        )
    except httpx.HTTPStatusError as exc:
        if not (resolved_connection_id and _is_missing_column_error(exc, "connection_id")):
            raise
        fallback_filters = {
            "client_id": f"eq.{cid}",
            "and": f"(timestamp.gte.{since_iso}T00:00:00,timestamp.lte.{until_iso}T23:59:59)",
        }
        media_rows_period = await sb_select(
            "ig_media",
            filters=fallback_filters,
            order="timestamp.asc",
            limit=5000,
        )
        media_read_mode = "period_media_connection_column_missing"
    print(
        "[dashboard][organic] media_read "
        f"client_id={cid} connection_id={resolved_connection_id or '-'} "
        f"rows={len(media_rows_period)} mode={media_read_mode}"
    )
    # Fallback: quando snapshots ainda não existem, deriva daily/totais de ig_media.
    if not rows:
        media_rows = list(media_rows_period)
        by_day: Dict[str, Dict[str, int]] = {}
        for m in media_rows:
            ts = str(m.get("timestamp") or "")
            if len(ts) < 10:
                continue
            d = ts[:10]
            d_parsed = _parse_iso_date(d)
            if not d_parsed:
                continue
            if d_parsed < since_date or d_parsed > until_date:
                continue
            ins = m.get("insights_json") or {}
            if isinstance(ins, str):
                ins = {}
            cur = by_day.get(
                d,
                {
                    "impressions": 0,
                    "reach": 0,
                    "total_interactions": 0,
                    "website_clicks": 0,
                    "profile_views": 0,
                    "accounts_engaged": 0,
                    "followers": 0,
                },
            )
            cur["impressions"] += int((ins or {}).get("views") or 0)
            cur["reach"] += int((ins or {}).get("reach") or 0)
            cur["total_interactions"] += int((ins or {}).get("total_interactions") or 0)
            cur["profile_views"] += int((ins or {}).get("profile_visits") or 0)
            by_day[d] = cur

        rows = [
            {
                "snapshot_date": k,
                "impressions_day": v["impressions"],
                "reach_day": v["reach"],
                "total_interactions_day": v["total_interactions"],
                "website_clicks_day": v["website_clicks"],
                "profile_views_day": v["profile_views"],
                "accounts_engaged_day": v["accounts_engaged"],
                "followers_count": v["followers"],
            }
            for k, v in sorted(by_day.items())
        ]

    daily: List[Dict[str, Any]] = []

    for r in rows:
        impressions = int(r.get("impressions_day") or 0)
        reach = int(r.get("reach_day") or 0)
        total_interactions = int(r.get("total_interactions_day") or 0)
        website_clicks = int(r.get("website_clicks_day") or 0)
        profile_views = int(r.get("profile_views_day") or 0)
        accounts_engaged = int(r.get("accounts_engaged_day") or 0)
        followers = int(r.get("followers_count") or 0)

        daily.append(
            {
                "date": r["snapshot_date"],
                "start": r["snapshot_date"],
                "end": r["snapshot_date"],
                "impressions": impressions,
                "reach": reach,

                # ✅ padrão novo
                "total_interactions": total_interactions,

                "website_clicks": website_clicks,
                "profile_views": profile_views,
                "accounts_engaged": accounts_engaged,
                "followers": followers,

                # (compat temporária com front antigo)
                "interactions": total_interactions,
            }
        )

    covered_days = len(daily)
    expected_days = window_days
    is_partial = covered_days < expected_days
    missing_days = max(0, expected_days - covered_days)

    period_totals = _build_period_totals(rows)
    if is_partial and media_rows_period:
        media_period_totals = _build_media_period_totals(media_rows_period)
        for metric in ("impressions", "reach", "total_interactions", "profile_views"):
            period_totals[metric] = max(
                int(period_totals.get(metric) or 0),
                int(media_period_totals.get(metric) or 0),
            )
        period_totals["interactions"] = int(period_totals["total_interactions"])

    totals = {
        "impressions": int(period_totals["impressions"]),
        "reach": int(period_totals["reach"]),
        "total_interactions": int(period_totals["total_interactions"]),
        "website_clicks": int(period_totals["website_clicks"]),
        "profile_views": int(period_totals["profile_views"]),
        "accounts_engaged": int(period_totals["accounts_engaged"]),
        "interactions": int(period_totals["total_interactions"]),
    }
    followers_growth_last_days = int(period_totals["followers_growth"])

    prev_until_date = since_date - timedelta(days=1)
    prev_since_date = prev_until_date - timedelta(days=window_days - 1)
    previous_rows = await _query_snapshot_rows(
        cid,
        prev_since_date,
        prev_until_date,
        resolved_connection_id or None,
    )
    previous_period_totals = _build_period_totals(previous_rows)
    previous_totals = {
        "impressions": int(previous_period_totals["impressions"]),
        "reach": int(previous_period_totals["reach"]),
        "total_interactions": int(previous_period_totals["total_interactions"]),
        "website_clicks": int(previous_period_totals["website_clicks"]),
        "profile_views": int(previous_period_totals["profile_views"]),
        "accounts_engaged": int(previous_period_totals["accounts_engaged"]),
        "interactions": int(previous_period_totals["total_interactions"]),
    }
    followers_growth_previous_period = int(previous_period_totals["followers_growth"])

    period_growth_percent = {
        "impressions": _growth(int(totals["impressions"]), int(previous_totals["impressions"])),
        "reach": _growth(int(totals["reach"]), int(previous_totals["reach"])),
        "total_interactions": _growth(int(totals["total_interactions"]), int(previous_totals["total_interactions"])),
        "website_clicks": _growth(int(totals["website_clicks"]), int(previous_totals["website_clicks"])),
        "profile_views": _growth(int(totals["profile_views"]), int(previous_totals["profile_views"])),
        "accounts_engaged": _growth(int(totals["accounts_engaged"]), int(previous_totals["accounts_engaged"])),
        "followers": _growth(int(followers_growth_last_days), int(followers_growth_previous_period)),
        # compat temporária
        "interactions": _growth(int(totals["total_interactions"]), int(previous_totals["total_interactions"])),
    }

    # Mês do final do período (recurso secundário para compatibilidade).
    month_start = until_date.replace(day=1)
    month_end = until_date.replace(day=calendar.monthrange(until_date.year, until_date.month)[1])
    month_rows = await _query_snapshot_rows(
        cid,
        month_start,
        month_end,
        resolved_connection_id or None,
    )
    monthly_totals = _sum_snapshot_rows(month_rows)

    monthly_followers_growth = _followers_growth(month_rows)

    # mês anterior ao mês âncora
    last_month_end = month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    last_month_rows = await _query_snapshot_rows(
        cid,
        last_month_start,
        last_month_end,
        resolved_connection_id or None,
    )
    last_month_totals = _sum_snapshot_rows(last_month_rows)

    last_month_followers_growth = _followers_growth(last_month_rows)

    monthly_growth_percent = {
        "impressions": _growth(int(monthly_totals["impressions"]), int(last_month_totals["impressions"])),
        "reach": _growth(int(monthly_totals["reach"]), int(last_month_totals["reach"])),
        "total_interactions": _growth(int(monthly_totals["total_interactions"]), int(last_month_totals["total_interactions"])),
        "website_clicks": _growth(int(monthly_totals["website_clicks"]), int(last_month_totals["website_clicks"])),
        "profile_views": _growth(int(monthly_totals["profile_views"]), int(last_month_totals["profile_views"])),
        "accounts_engaged": _growth(int(monthly_totals["accounts_engaged"]), int(last_month_totals["accounts_engaged"])),
        "followers": _growth(int(monthly_followers_growth), int(last_month_followers_growth)),

        # (compat temporária)
        "interactions": _growth(int(monthly_totals["total_interactions"]), int(last_month_totals["total_interactions"])),
    }

    weekly_series = _build_series(rows, "weekly")
    monthly_series = _build_series(rows, "monthly")

    return {
        "ok": True,
        "client_id": cid,
        "connection_id": resolved_connection_id or None,
        "days": window_days,
        "start": since_iso,
        "end": until_iso,
        "date_range": {"since": since_iso, "until": until_iso},
        "daily": daily,
        "series": {
            "daily": list(daily),
            "weekly": weekly_series,
            "monthly": monthly_series,
        },
        "period_totals": dict(period_totals),
        "period_previous_totals": dict(previous_period_totals),
        "totals_last_days": dict(totals),
        "followers_growth_last_days": followers_growth_last_days,
        "totals_previous_period": dict(previous_totals),
        "followers_growth_previous_period": int(followers_growth_previous_period),
        "period_growth_percent": dict(period_growth_percent),
        "monthly_totals": dict(monthly_totals),
        "last_month_totals": dict(last_month_totals),
        "monthly_followers_growth": int(monthly_followers_growth),
        "last_month_followers_growth": int(last_month_followers_growth),
        "monthly_growth_percent": dict(monthly_growth_percent),
        "coverage": {
            "covered_days": covered_days,
            "expected_days": expected_days,
            "is_partial": is_partial,
            "missing_days": missing_days,
        },
    }
