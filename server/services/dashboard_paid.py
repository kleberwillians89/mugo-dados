from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple
import httpx

from .connection_resolver import resolve_connection_for_scope
from .ig_dashboard import get_dashboard as get_organic_dashboard
from .ig_supabase import sb_select
from .meta_tokens import serialize_connection_status


def _safe_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        if value is None or value == "":
            return 0
        return int(float(value))
    except Exception:
        return 0


def _month_range(month: str) -> Tuple[str, str]:
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


def _date_window(
    days: int,
    month: str | None,
    start: str | None = None,
    end: str | None = None,
) -> Tuple[str, str]:
    start_date = _parse_iso_date(start)
    end_date = _parse_iso_date(end)
    if start_date and end_date:
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        return start_date.isoformat(), end_date.isoformat()

    if month:
        return _month_range(month)
    d = max(1, min(days, 365))
    until = datetime.now(timezone.utc).date()
    since = until - timedelta(days=d - 1)
    return since.isoformat(), until.isoformat()


def _is_missing_column_error(exc: httpx.HTTPStatusError, column_name: str) -> bool:
    if exc.response is None:
        return False
    if exc.response.status_code not in {400, 404}:
        return False
    body = str(exc.response.text or "").lower()
    col = str(column_name or "").lower()
    return col in body and ("column" in body or "schema cache" in body)


def _is_missing_relation_error(exc: httpx.HTTPStatusError, table_name: str) -> bool:
    if exc.response is None:
        return False
    if exc.response.status_code not in {400, 404}:
        return False
    body = str(exc.response.text or "").lower()
    table = str(table_name or "").lower()
    return table in body and ("relation" in body or "does not exist" in body or "schema cache" in body)


def _ad_account_variants(value: Any) -> List[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    variants = [raw]
    if raw.startswith("act_"):
        variants.append(raw.replace("act_", "", 1))
    else:
        variants.append(f"act_{raw}")
    out: List[str] = []
    for item in variants:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _paid_totals_template() -> Dict[str, float]:
    return {
        "spend": 0.0,
        "impressions": 0.0,
        "reach": 0.0,
        "clicks": 0.0,
        "cpc": 0.0,
        "cpm": 0.0,
        "ctr": 0.0,
        "conversions": 0.0,
        "revenue": 0.0,
        "roas": 0.0,
    }


def _manager_metrics_template() -> Dict[str, float]:
    return {
        "link_clicks": 0.0,
        "video_views": 0.0,
        "page_engagement": 0.0,
        "post_engagement": 0.0,
        "profile_visits": 0.0,
    }


def _accumulate_paid_metric(target: Dict[str, float], row: Dict[str, Any]) -> None:
    target["spend"] += _safe_float(row.get("spend"))
    target["impressions"] += float(_safe_int(row.get("impressions")))
    target["reach"] += float(_safe_int(row.get("reach")))
    target["clicks"] += float(_safe_int(row.get("clicks")))
    target["conversions"] += _safe_float(row.get("conversions"))
    target["revenue"] += _safe_float(row.get("revenue"))


def _finalize_paid_metric(metrics: Dict[str, float]) -> Dict[str, float]:
    spend = float(metrics.get("spend") or 0.0)
    impressions = float(metrics.get("impressions") or 0.0)
    clicks = float(metrics.get("clicks") or 0.0)
    revenue = float(metrics.get("revenue") or 0.0)

    out = dict(metrics)
    out["cpc"] = (spend / clicks) if clicks > 0 else 0.0
    out["cpm"] = ((spend * 1000.0) / impressions) if impressions > 0 else 0.0
    out["ctr"] = ((clicks / impressions) * 100.0) if impressions > 0 else 0.0
    out["roas"] = (revenue / spend) if spend > 0 else 0.0
    return out


def _normalize_raw_json_payload(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _extract_action_value(action: Dict[str, Any]) -> float:
    if not isinstance(action, dict):
        return 0.0
    if "value" in action:
        return _safe_float(action.get("value"))
    return _safe_float(action.get("1d_click")) + _safe_float(action.get("1d_view"))


def _action_type_aliases() -> Dict[str, tuple[str, ...]]:
    return {
        "link_clicks": ("link_click",),
        "video_views": ("video_view", "video_play"),
        "page_engagement": ("page_engagement",),
        "post_engagement": ("post_engagement",),
        "profile_visits": ("profile_visit", "profile_visits", "ig_profile_visit"),
    }


def _aggregate_action_metrics(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    totals = _manager_metrics_template()
    aliases = _action_type_aliases()
    for row in rows:
        for payload in _normalize_raw_json_payload(row.get("raw_json")):
            actions = payload.get("actions")
            if not isinstance(actions, list):
                continue
            for action in actions:
                action_type = str((action or {}).get("action_type") or "").strip().lower()
                if not action_type:
                    continue
                value = _extract_action_value(action)
                for metric_key, accepted_types in aliases.items():
                    if action_type in accepted_types:
                        totals[metric_key] += value
                        break
    return totals


def _fill_daily_range(
    rows: List[Dict[str, Any]],
    *,
    since: str | None = None,
    until: str | None = None,
) -> List[Dict[str, Any]]:
    start_date = _parse_iso_date(since)
    end_date = _parse_iso_date(until)
    if start_date is None or end_date is None:
        return rows
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    by_date = {
        str(row.get("date") or "").strip(): row
        for row in rows
        if str(row.get("date") or "").strip()
    }
    zero_metrics = _finalize_paid_metric(_paid_totals_template())

    out: List[Dict[str, Any]] = []
    cursor = start_date
    while cursor <= end_date:
        key = cursor.isoformat()
        out.append(by_date.get(key, {"date": key, **zero_metrics}))
        cursor += timedelta(days=1)
    return out


async def _select_paid_rows(
    *,
    table: str,
    client_id: str,
    since: str,
    until: str,
    resolved_connection_id: str,
    resolved_ad_account_id: str = "",
    limit: int = 10000,
    allow_missing_table: bool = False,
) -> tuple[List[Dict[str, Any]], str]:
    filters = {
        "client_id": f"eq.{client_id}",
        "and": f"(stat_date.gte.{since},stat_date.lte.{until})",
    }
    mode = "client_scope"
    if resolved_connection_id:
        filters["connection_id"] = f"eq.{resolved_connection_id}"
        mode = "connection_scope"
    try:
        rows = await sb_select(
            table,
            filters=filters,
            order="stat_date.asc",
            limit=limit,
        )
        if rows or mode != "connection_scope":
            return rows, mode
        account_variants = _ad_account_variants(resolved_ad_account_id)
        if not account_variants:
            return rows, mode
        for account_id in account_variants:
            fallback_filters = {
                "client_id": f"eq.{client_id}",
                "and": f"(stat_date.gte.{since},stat_date.lte.{until})",
                "ad_account_id": f"eq.{account_id}",
            }
            try:
                scoped_rows = await sb_select(
                    table,
                    filters=fallback_filters,
                    order="stat_date.asc",
                    limit=limit,
                )
            except httpx.HTTPStatusError as account_exc:
                if _is_missing_column_error(account_exc, "ad_account_id"):
                    break
                raise
            if scoped_rows:
                return scoped_rows, "ad_account_scope_fallback"
        return rows, mode
    except httpx.HTTPStatusError as exc:
        if allow_missing_table and _is_missing_relation_error(exc, table):
            return [], "table_missing"
        if not (resolved_connection_id and _is_missing_column_error(exc, "connection_id")):
            raise
        fallback_filters = {
            "client_id": f"eq.{client_id}",
            "and": f"(stat_date.gte.{since},stat_date.lte.{until})",
        }
        rows = await sb_select(
            table,
            filters=fallback_filters,
            order="stat_date.asc",
            limit=limit,
        )
        return rows, "connection_column_missing"


def _aggregate_paid_rows(
    rows: List[Dict[str, Any]],
    *,
    since: str | None = None,
    until: str | None = None,
) -> Dict[str, Any]:
    by_day: Dict[str, Dict[str, float]] = {}
    by_account: Dict[str, Dict[str, float]] = {}
    account_names: Dict[str, str] = {}
    totals = _paid_totals_template()

    for row in rows:
        day = str(row.get("stat_date") or "")
        if not day:
            continue
        account_id = str(row.get("ad_account_id") or "").strip()
        account_name = str(row.get("ad_account_name") or "").strip()
        if account_id:
            account_names[account_id] = account_name or account_names.get(account_id, "")

        by_day.setdefault(day, _paid_totals_template())
        by_account.setdefault(account_id or "-", _paid_totals_template())

        _accumulate_paid_metric(by_day[day], row)
        _accumulate_paid_metric(by_account[account_id or "-"], row)
        _accumulate_paid_metric(totals, row)

    daily = [
        {"date": day, **_finalize_paid_metric(metrics)}
        for day, metrics in sorted(by_day.items(), key=lambda x: x[0])
    ]
    daily = _fill_daily_range(daily, since=since, until=until)
    accounts = [
        {
            "ad_account_id": acc_id if acc_id != "-" else "",
            "ad_account_name": account_names.get(acc_id, ""),
            **_finalize_paid_metric(metrics),
        }
        for acc_id, metrics in sorted(by_account.items(), key=lambda x: x[0])
    ]

    stat_dates = sorted(
        [str(row.get("stat_date") or "").strip() for row in rows if str(row.get("stat_date") or "").strip()]
    )
    first_stat_date = stat_dates[0] if stat_dates else None
    last_stat_date = stat_dates[-1] if stat_dates else None

    return {
        "daily": daily,
        "accounts": sorted(accounts, key=lambda a: float(a.get("spend") or 0.0), reverse=True),
        "totals": _finalize_paid_metric(totals),
        "first_stat_date": first_stat_date,
        "last_stat_date": last_stat_date,
    }


def _merge_promoted_rows(
    *,
    ad_rows: List[Dict[str, Any]],
    promoted_rows: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    ad_keys = {
        (
            str(row.get("ad_id") or "").strip(),
            str(row.get("stat_date") or "").strip(),
        )
        for row in ad_rows
    }
    promoted_unique = []
    for row in promoted_rows:
        key = (
            str(row.get("ad_id") or "").strip(),
            str(row.get("stat_date") or "").strip(),
        )
        if key in ad_keys:
            continue
        promoted_unique.append(row)
    merged_rows = list(ad_rows) + promoted_unique
    return merged_rows, promoted_unique


def _merge_group_rows(
    *,
    base_rows: List[Dict[str, Any]],
    extra_rows: List[Dict[str, Any]],
    id_field: str,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    base_keys = {
        (
            str(row.get(id_field) or "").strip(),
            str(row.get("stat_date") or "").strip(),
        )
        for row in base_rows
    }
    unique_extra: List[Dict[str, Any]] = []
    for row in extra_rows:
        row_id = str(row.get(id_field) or "").strip()
        stat_date = str(row.get("stat_date") or "").strip()
        if not row_id or not stat_date:
            continue
        key = (row_id, stat_date)
        if key in base_keys:
            continue
        unique_extra.append(row)
    return list(base_rows) + unique_extra, unique_extra


def _aggregate_top_creatives(rows: List[Dict[str, Any]], limit: int = 20) -> List[Dict[str, Any]]:
    grouped: Dict[tuple[str, str], Dict[str, Any]] = {}
    for row in rows:
        ad_id = str(row.get("ad_id") or "").strip()
        if not ad_id:
            continue
        post_id = str(row.get("post_id") or "").strip()
        key = (ad_id, post_id)
        if key not in grouped:
            grouped[key] = {
                "ad_id": ad_id,
                "ad_name": str(row.get("ad_name") or "").strip(),
                "post_id": post_id or None,
                "story_id": str(row.get("story_id") or "").strip() or None,
                "source_platform": str(row.get("source_platform") or "").strip() or None,
                "campaign_id": str(row.get("campaign_id") or "").strip() or None,
                "campaign_name": str(row.get("campaign_name") or "").strip() or None,
                "adset_id": str(row.get("adset_id") or "").strip() or None,
                "adset_name": str(row.get("adset_name") or "").strip() or None,
                "spend": 0.0,
                "impressions": 0,
                "reach": 0,
                "clicks": 0,
                "conversions": 0.0,
                "revenue": 0.0,
            }
        item = grouped[key]
        item["spend"] += _safe_float(row.get("spend"))
        item["impressions"] += _safe_int(row.get("impressions"))
        item["reach"] += _safe_int(row.get("reach"))
        item["clicks"] += _safe_int(row.get("clicks"))
        item["conversions"] += _safe_float(row.get("conversions"))
        item["revenue"] += _safe_float(row.get("revenue"))

    out: List[Dict[str, Any]] = []
    for item in grouped.values():
        spend = float(item.get("spend") or 0.0)
        clicks = int(item.get("clicks") or 0)
        impressions = int(item.get("impressions") or 0)
        revenue = float(item.get("revenue") or 0.0)
        out.append(
            {
                **item,
                "cpc": (spend / clicks) if clicks > 0 else 0.0,
                "cpm": ((spend * 1000.0) / impressions) if impressions > 0 else 0.0,
                "ctr": ((clicks / impressions) * 100.0) if impressions > 0 else 0.0,
                "roas": (revenue / spend) if spend > 0 else 0.0,
            }
        )
    out_sorted = sorted(out, key=lambda r: float(r.get("spend") or 0.0), reverse=True)
    return out_sorted[: max(1, int(limit))]


async def get_paid_dashboard(
    client_id: str,
    connection_id: str | None = None,
    days: int = 30,
    month: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> Dict[str, Any]:
    since, until = _date_window(days, month, start=start, end=end)
    requested_connection_id = str(connection_id or "").strip()
    resolved_connection = await resolve_connection_for_scope(
        client_id=client_id,
        platform="meta_ads",
        connection_type="paid",
        requested_connection_id=requested_connection_id or None,
        require_ad_account=True,
    )
    resolved_connection_id = str(resolved_connection.get("connection_id") or "").strip()
    resolved_ad_account_id = str((resolved_connection.get("row") or {}).get("ad_account_id") or "").strip()
    connection_source = str(resolved_connection.get("source") or "none").strip() or "none"
    if not resolved_connection_id:
        print(
            "[paid][dashboard] "
            f"client_id={client_id} connection_id_requested={requested_connection_id or '-'} "
            f"connection_id_resolved=- connection_source={connection_source} "
            f"since={since} until={until} mode=no_paid_connection rows=0"
        )
        return {
            "ok": True,
            "client_id": client_id,
            "connection_id": None,
            "connection_status": None,
            "days": days,
            "month": month,
            "date_range": {"since": since, "until": until},
            "row_count": 0,
            "first_stat_date": None,
            "last_stat_date": None,
            "has_data": False,
            "message": "nenhuma conexão paid ativa para este cliente",
            "daily": [],
            "totals": _finalize_paid_metric(_paid_totals_template()),
            "accounts": [],
            "sources": {
                "mode_account": "no_paid_connection",
                "mode_ad": "no_paid_connection",
                "mode_promoted": "no_paid_connection",
                "rows": {
                    "ad_account_daily_stats": 0,
                    "ad_daily_stats": 0,
                    "promoted_post_daily_stats": 0,
                    "promoted_post_unique": 0,
                    "aggregated_rows": 0,
                },
                "totals": {
                    "classic_ads": _finalize_paid_metric(_paid_totals_template()),
                    "boosted_posts": _finalize_paid_metric(_paid_totals_template()),
                    "consolidated": _finalize_paid_metric(_paid_totals_template()),
                },
            },
        }
    account_rows, account_mode = await _select_paid_rows(
        table="ad_account_daily_stats",
        client_id=client_id,
        since=since,
        until=until,
        resolved_connection_id=resolved_connection_id,
        resolved_ad_account_id=resolved_ad_account_id,
        limit=10000,
    )
    ad_rows, ad_mode = await _select_paid_rows(
        table="ad_daily_stats",
        client_id=client_id,
        since=since,
        until=until,
        resolved_connection_id=resolved_connection_id,
        resolved_ad_account_id=resolved_ad_account_id,
        limit=20000,
    )
    promoted_rows, promoted_mode = await _select_paid_rows(
        table="promoted_post_daily_stats",
        client_id=client_id,
        since=since,
        until=until,
        resolved_connection_id=resolved_connection_id,
        resolved_ad_account_id=resolved_ad_account_id,
        limit=20000,
        allow_missing_table=True,
    )

    merged_detail_rows, promoted_unique_rows = _merge_promoted_rows(
        ad_rows=ad_rows,
        promoted_rows=promoted_rows,
    )
    promoted_keys = {
        (
            str(row.get("ad_id") or "").strip(),
            str(row.get("stat_date") or "").strip(),
        )
        for row in promoted_rows
    }
    classic_exclusive_rows = [
        row
        for row in ad_rows
        if (
            str(row.get("ad_id") or "").strip(),
            str(row.get("stat_date") or "").strip(),
        )
        not in promoted_keys
    ]
    source_consolidated_rows = list(classic_exclusive_rows) + list(promoted_rows)
    aggregate_rows = account_rows if account_rows else merged_detail_rows
    aggregate_level = "account_rows" if account_rows else "detail_rows"
    creative_rows = merged_detail_rows if merged_detail_rows else account_rows
    aggregated = _aggregate_paid_rows(aggregate_rows, since=since, until=until)
    first_stat_date = aggregated.get("first_stat_date")
    last_stat_date = aggregated.get("last_stat_date")
    manager_metrics = (
        _aggregate_action_metrics(account_rows)
        if account_rows
        else _aggregate_action_metrics(source_consolidated_rows)
    )

    classic_aggregated = _aggregate_paid_rows(classic_exclusive_rows, since=since, until=until) if classic_exclusive_rows else {
        "daily": [],
        "accounts": [],
        "totals": _finalize_paid_metric(_paid_totals_template()),
    }
    boosted_aggregated = _aggregate_paid_rows(promoted_rows, since=since, until=until) if promoted_rows else {
        "daily": [],
        "accounts": [],
        "totals": _finalize_paid_metric(_paid_totals_template()),
    }
    consolidated_source_aggregated = (
        _aggregate_paid_rows(source_consolidated_rows, since=since, until=until)
        if source_consolidated_rows
        else {
            "daily": [],
            "accounts": [],
            "totals": _finalize_paid_metric(_paid_totals_template()),
        }
    )
    classic_manager_metrics = (
        _aggregate_action_metrics(classic_exclusive_rows)
        if classic_exclusive_rows
        else _manager_metrics_template()
    )
    boosted_manager_metrics = (
        _aggregate_action_metrics(promoted_rows)
        if promoted_rows
        else _manager_metrics_template()
    )
    consolidated_manager_metrics = (
        _aggregate_action_metrics(source_consolidated_rows)
        if source_consolidated_rows
        else _manager_metrics_template()
    )

    print(
        "[paid][dashboard] "
        f"client_id={client_id} connection_id_requested={requested_connection_id or '-'} "
        f"connection_id_resolved={resolved_connection_id or '-'} connection_source={connection_source} "
        f"since={since} until={until} "
        f"rows_account={len(account_rows)} rows_ad={len(ad_rows)} "
        f"rows_promoted={len(promoted_rows)} rows_promoted_unique={len(promoted_unique_rows)} "
        f"rows_classic_exclusive={len(classic_exclusive_rows)} "
        f"aggregate_level={aggregate_level} "
        f"mode_account={account_mode} mode_ad={ad_mode} mode_promoted={promoted_mode} "
        f"first_stat_date={first_stat_date or '-'} last_stat_date={last_stat_date or '-'}"
    )

    if not aggregate_rows:
        return {
            "ok": True,
            "client_id": client_id,
            "connection_id": resolved_connection_id or None,
            "connection_status": serialize_connection_status(resolved_connection.get("row") or {}),
            "days": days,
            "month": month,
            "date_range": {"since": since, "until": until},
            "row_count": 0,
            "first_stat_date": None,
            "last_stat_date": None,
            "has_data": False,
            "message": "sem dados pagos no período",
            "daily": [],
            "totals": _finalize_paid_metric(_paid_totals_template()),
            "manager_metrics": _manager_metrics_template(),
            "accounts": [],
            "top_creatives": [],
            "top_boosted_posts": [],
            "sources": {
                "mode_account": account_mode,
                "mode_ad": ad_mode,
                "mode_promoted": promoted_mode,
                "rows": {
                    "ad_account_daily_stats": len(account_rows),
                    "ad_daily_stats": len(ad_rows),
                    "promoted_post_daily_stats": len(promoted_rows),
                    "promoted_post_unique": len(promoted_unique_rows),
                    "aggregated_rows": 0,
                },
                "totals": {
                    "classic_ads": _finalize_paid_metric(_paid_totals_template()),
                    "boosted_posts": _finalize_paid_metric(_paid_totals_template()),
                    "consolidated": _finalize_paid_metric(_paid_totals_template()),
                },
                "manager_metrics": {
                    "classic_ads": _manager_metrics_template(),
                    "boosted_posts": _manager_metrics_template(),
                    "consolidated": _manager_metrics_template(),
                },
            },
        }

    return {
        "ok": True,
        "client_id": client_id,
        "connection_id": resolved_connection_id or None,
        "connection_status": serialize_connection_status(resolved_connection.get("row") or {}),
        "days": days,
        "month": month,
        "date_range": {"since": since, "until": until},
        "row_count": len(aggregate_rows),
        "first_stat_date": first_stat_date,
        "last_stat_date": last_stat_date,
        "has_data": True,
        "message": "",
        "daily": aggregated.get("daily") or [],
        "totals": aggregated.get("totals") or _finalize_paid_metric(_paid_totals_template()),
        "manager_metrics": manager_metrics,
        "accounts": aggregated.get("accounts") or [],
        "top_creatives": _aggregate_top_creatives(creative_rows, limit=20),
        "top_boosted_posts": _aggregate_top_creatives(
            [row for row in promoted_rows if str(row.get("post_id") or "").strip()],
            limit=20,
        ),
        "sources": {
            "mode_account": account_mode,
            "mode_ad": ad_mode,
            "mode_promoted": promoted_mode,
            "rows": {
                "ad_account_daily_stats": len(account_rows),
                "ad_daily_stats": len(ad_rows),
                "promoted_post_daily_stats": len(promoted_rows),
                "promoted_post_unique": len(promoted_unique_rows),
                "aggregated_rows": len(aggregate_rows),
            },
            "totals": {
                "classic_ads": classic_aggregated.get("totals")
                or _finalize_paid_metric(_paid_totals_template()),
                "boosted_posts": boosted_aggregated.get("totals")
                or _finalize_paid_metric(_paid_totals_template()),
                "consolidated": consolidated_source_aggregated.get("totals")
                or _finalize_paid_metric(_paid_totals_template()),
            },
            "manager_metrics": {
                "classic_ads": classic_manager_metrics,
                "boosted_posts": boosted_manager_metrics,
                "consolidated": consolidated_manager_metrics,
            },
        },
    }


async def get_summary_dashboard(
    client_id: str,
    connection_id: str | None = None,
    days: int = 30,
    month: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> Dict[str, Any]:
    organic = await get_organic_dashboard(
        client_id=client_id,
        connection_id=connection_id,
        days=days,
        month=month,
        start=start,
        end=end,
    )
    paid = await get_paid_dashboard(
        client_id=client_id,
        connection_id=connection_id,
        days=days,
        month=month,
        start=start,
        end=end,
    )

    organic_totals = organic.get("monthly_totals" if month else "totals_last_days") or {}
    paid_totals = paid.get("totals") or {}

    summary = {
        "impressions_total": _safe_int(organic_totals.get("impressions")) + _safe_int(paid_totals.get("impressions")),
        "reach_total": _safe_int(organic_totals.get("reach")) + _safe_int(paid_totals.get("reach")),
        "interactions_organic": _safe_int(organic_totals.get("total_interactions")),
        "spend_paid": _safe_float(paid_totals.get("spend")),
        "clicks_paid": _safe_int(paid_totals.get("clicks")),
        "conversions_paid": _safe_float(paid_totals.get("conversions")),
        "revenue_paid": _safe_float(paid_totals.get("revenue")),
        "roas_paid": _safe_float(paid_totals.get("roas")),
    }

    return {
        "ok": True,
        "client_id": client_id,
        "days": days,
        "month": month,
        "summary": summary,
        "organic": organic,
        "paid": paid,
    }


def _sum_grouped_rows(rows: List[Dict[str, Any]], key_name: str, name_key: str) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        gid = str(row.get(key_name) or "").strip()
        if not gid:
            continue
        if gid not in grouped:
            grouped[gid] = {
                key_name: gid,
                name_key: str(row.get(name_key) or "").strip(),
                "spend": 0.0,
                "impressions": 0,
                "reach": 0,
                "clicks": 0,
                "conversions": 0.0,
                "revenue": 0.0,
                "last_stat_date": str(row.get("stat_date") or ""),
            }

        cur = grouped[gid]
        cur["spend"] += _safe_float(row.get("spend"))
        cur["impressions"] += _safe_int(row.get("impressions"))
        cur["reach"] += _safe_int(row.get("reach"))
        cur["clicks"] += _safe_int(row.get("clicks"))
        cur["conversions"] += _safe_float(row.get("conversions"))
        cur["revenue"] += _safe_float(row.get("revenue"))

        stat_date = str(row.get("stat_date") or "")
        if stat_date > str(cur.get("last_stat_date") or ""):
            cur["last_stat_date"] = stat_date
            cur[name_key] = str(row.get(name_key) or "").strip() or str(cur.get(name_key) or "")

    out: List[Dict[str, Any]] = []
    for _, item in grouped.items():
        spend = float(item.get("spend") or 0.0)
        clicks = int(item.get("clicks") or 0)
        impressions = int(item.get("impressions") or 0)
        revenue = float(item.get("revenue") or 0.0)
        out.append(
            {
                **item,
                "cpc": (spend / clicks) if clicks > 0 else 0.0,
                "cpm": ((spend * 1000.0) / impressions) if impressions > 0 else 0.0,
                "ctr": ((clicks / impressions) * 100.0) if impressions > 0 else 0.0,
                "roas": (revenue / spend) if spend > 0 else 0.0,
            }
        )
    return sorted(out, key=lambda x: float(x.get("spend") or 0.0), reverse=True)


async def list_campaigns(
    client_id: str,
    connection_id: str | None = None,
    days: int = 30,
    month: str | None = None,
    limit: int = 100,
    start: str | None = None,
    end: str | None = None,
) -> Dict[str, Any]:
    since, until = _date_window(days, month, start=start, end=end)
    requested_connection_id = str(connection_id or "").strip()
    resolved_connection = await resolve_connection_for_scope(
        client_id=client_id,
        platform="meta_ads",
        connection_type="paid",
        requested_connection_id=requested_connection_id or None,
        require_ad_account=True,
    )
    resolved_connection_id = str(resolved_connection.get("connection_id") or "").strip()
    connection_source = str(resolved_connection.get("source") or "none").strip() or "none"
    if not resolved_connection_id:
        print(
            "[paid][campaigns] "
            f"client_id={client_id} connection_id_requested={requested_connection_id or '-'} "
            f"connection_id_resolved=- connection_source={connection_source} "
            f"since={since} until={until} mode=no_paid_connection rows=0"
        )
        return {
            "ok": True,
            "client_id": client_id,
            "connection_id": None,
            "date_range": {"since": since, "until": until},
            "campaigns": [],
            "total": 0,
            "sources": {
                "rows_campaign_daily_stats": 0,
                "rows_promoted_post_daily_stats": 0,
                "rows_promoted_unique": 0,
                "rows_merged": 0,
            },
        }

    campaign_rows, campaign_mode = await _select_paid_rows(
        table="campaign_daily_stats",
        client_id=client_id,
        since=since,
        until=until,
        resolved_connection_id=resolved_connection_id,
        limit=10000,
    )
    promoted_rows, promoted_mode = await _select_paid_rows(
        table="promoted_post_daily_stats",
        client_id=client_id,
        since=since,
        until=until,
        resolved_connection_id=resolved_connection_id,
        limit=20000,
        allow_missing_table=True,
    )
    promoted_campaign_rows = [
        row for row in promoted_rows if str(row.get("campaign_id") or "").strip()
    ]
    merged_rows, promoted_unique_rows = _merge_group_rows(
        base_rows=campaign_rows,
        extra_rows=promoted_campaign_rows,
        id_field="campaign_id",
    )

    print(
        "[paid][campaigns] "
        f"client_id={client_id} connection_id_requested={requested_connection_id or '-'} "
        f"connection_id_resolved={resolved_connection_id or '-'} connection_source={connection_source} "
        f"since={since} until={until} mode_campaign={campaign_mode} mode_promoted={promoted_mode} "
        f"rows_campaign={len(campaign_rows)} rows_promoted={len(promoted_rows)} "
        f"rows_promoted_unique={len(promoted_unique_rows)} rows_merged={len(merged_rows)}"
    )
    grouped = _sum_grouped_rows(merged_rows, "campaign_id", "campaign_name")
    return {
        "ok": True,
        "client_id": client_id,
        "connection_id": resolved_connection_id or None,
        "date_range": {"since": since, "until": until},
        "campaigns": grouped[: max(1, limit)],
        "total": len(grouped),
        "sources": {
            "rows_campaign_daily_stats": len(campaign_rows),
            "rows_promoted_post_daily_stats": len(promoted_rows),
            "rows_promoted_unique": len(promoted_unique_rows),
            "rows_merged": len(merged_rows),
        },
    }


async def list_ads(
    client_id: str,
    connection_id: str | None = None,
    days: int = 30,
    month: str | None = None,
    limit: int = 200,
    start: str | None = None,
    end: str | None = None,
) -> Dict[str, Any]:
    since, until = _date_window(days, month, start=start, end=end)
    requested_connection_id = str(connection_id or "").strip()
    resolved_connection = await resolve_connection_for_scope(
        client_id=client_id,
        platform="meta_ads",
        connection_type="paid",
        requested_connection_id=requested_connection_id or None,
        require_ad_account=True,
    )
    resolved_connection_id = str(resolved_connection.get("connection_id") or "").strip()
    connection_source = str(resolved_connection.get("source") or "none").strip() or "none"
    if not resolved_connection_id:
        print(
            "[paid][ads] "
            f"client_id={client_id} connection_id_requested={requested_connection_id or '-'} "
            f"connection_id_resolved=- connection_source={connection_source} "
            f"since={since} until={until} mode=no_paid_connection rows=0"
        )
        return {
            "ok": True,
            "client_id": client_id,
            "connection_id": None,
            "date_range": {"since": since, "until": until},
            "ads": [],
            "total": 0,
            "sources": {
                "rows_ad_daily_stats": 0,
                "rows_promoted_post_daily_stats": 0,
                "rows_promoted_unique": 0,
                "rows_merged": 0,
            },
        }

    ad_rows, ad_mode = await _select_paid_rows(
        table="ad_daily_stats",
        client_id=client_id,
        since=since,
        until=until,
        resolved_connection_id=resolved_connection_id,
        limit=20000,
    )
    promoted_rows, promoted_mode = await _select_paid_rows(
        table="promoted_post_daily_stats",
        client_id=client_id,
        since=since,
        until=until,
        resolved_connection_id=resolved_connection_id,
        limit=20000,
        allow_missing_table=True,
    )
    merged_rows, promoted_unique_rows = _merge_promoted_rows(
        ad_rows=ad_rows,
        promoted_rows=promoted_rows,
    )

    print(
        "[paid][ads] "
        f"client_id={client_id} connection_id_requested={requested_connection_id or '-'} "
        f"connection_id_resolved={resolved_connection_id or '-'} connection_source={connection_source} "
        f"since={since} until={until} mode_ad={ad_mode} mode_promoted={promoted_mode} "
        f"rows_ad={len(ad_rows)} rows_promoted={len(promoted_rows)} "
        f"rows_promoted_unique={len(promoted_unique_rows)} rows_merged={len(merged_rows)}"
    )
    grouped = _sum_grouped_rows(merged_rows, "ad_id", "ad_name")
    return {
        "ok": True,
        "client_id": client_id,
        "connection_id": resolved_connection_id or None,
        "date_range": {"since": since, "until": until},
        "ads": grouped[: max(1, limit)],
        "total": len(grouped),
        "sources": {
            "rows_ad_daily_stats": len(ad_rows),
            "rows_promoted_post_daily_stats": len(promoted_rows),
            "rows_promoted_unique": len(promoted_unique_rows),
            "rows_merged": len(merged_rows),
        },
    }
