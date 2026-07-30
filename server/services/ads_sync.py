from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from .ads_meta import (
    fetch_ad_account_insights,
    fetch_ad_catalog,
    fetch_ad_creatives,
    fetch_entity_insights,
)
from .bootstrap import bootstrap_meta_from_env
from .connection_resolver import resolve_connection_for_scope
from .job_runs import finish_job_run, start_job_run
from .meta_http import MetaApiError
from .ig_supabase import sb_select, sb_upsert
from .meta_tokens import (
    ensure_valid_meta_token,
    get_connection_by_id,
    mark_connection_sync_error,
    mark_connection_sync_success,
)
CATALOG_EFFECTIVE_STATUSES = [
    "ACTIVE",
    "INACTIVE",
    "PAUSED",
    "ARCHIVED",
    "DELETED",
    "WITH_ISSUES",
    "PENDING_BILLING_INFO",
    "CAMPAIGN_PAUSED",
    "ADSET_PAUSED",
    "PENDING_REVIEW",
    "DISAPPROVED",
    "PREAPPROVED",
    "IN_PROCESS",
]


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


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


def _normalize_ad_account_id(ad_account_id: str) -> str:
    raw = _safe_str(ad_account_id)
    if not raw:
        return ""
    return raw if raw.startswith("act_") else f"act_{raw}"


def _parse_iso_date_safe(value: Any) -> date | None:
    text = _safe_str(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except Exception:
        return None


def _date_ranges_overlap(
    *,
    start_a: date,
    end_a: date,
    start_b: date,
    end_b: date,
) -> bool:
    return start_a <= end_b and end_a >= start_b


def _ad_account_variants(value: Any) -> List[str]:
    raw = _safe_str(value)
    if not raw:
        return []
    variants = [raw]
    if raw.startswith("act_"):
        variants.append(raw.replace("act_", "", 1))
    else:
        variants.append(f"act_{raw}")
    out: List[str] = []
    for item in variants:
        text = _safe_str(item)
        if text and text not in out:
            out.append(text)
    return out


def _count_boosted_sources(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {
        "entity_insights_daily": 0,
        "entity_insights_all_days": 0,
        "insights_maximum_synthetic": 0,
        "unknown": 0,
    }
    for row in rows:
        source_name = _safe_str(row.get("boosted_source"))
        if source_name in counts:
            counts[source_name] += 1
        else:
            counts["unknown"] += 1
    return counts


def _synthetic_boosted_rows_from_maximum_insights(
    *,
    insight_rows: List[Dict[str, Any]],
    since: str,
    until: str,
) -> List[Dict[str, Any]]:
    since_date = _parse_iso_date_safe(since)
    until_date = _parse_iso_date_safe(until)
    if since_date is None or until_date is None:
        return []

    out: List[Dict[str, Any]] = []
    for row in insight_rows:
        ad_id = _safe_str(row.get("ad_id"))
        if not ad_id:
            continue
        row_start = _parse_iso_date_safe(row.get("date_start")) or since_date
        row_end = _parse_iso_date_safe(row.get("date_stop")) or row_start
        if row_start > row_end:
            row_start, row_end = row_end, row_start
        if not _date_ranges_overlap(
            start_a=row_start,
            end_a=row_end,
            start_b=since_date,
            end_b=until_date,
        ):
            continue
        synthetic = dict(row)
        synthetic["date_start"] = until_date.isoformat()
        synthetic["date_stop"] = until_date.isoformat()
        synthetic["ad_id"] = ad_id
        synthetic["post_id"] = _safe_str(row.get("post_id")) or f"ad_{ad_id}"
        synthetic["story_id"] = _safe_str(row.get("story_id"))
        synthetic["source_platform"] = _safe_str(row.get("source_platform")) or "unknown"
        synthetic["boosted_source"] = "insights_maximum_synthetic"
        synthetic["source_date_start"] = row_start.isoformat()
        synthetic["source_date_stop"] = row_end.isoformat()
        out.append(synthetic)
    return out

def _extract_conversions_and_revenue(row: Dict[str, Any]) -> Dict[str, float]:
    conversion_types = {
        "purchase",
        "omni_purchase",
        "offsite_conversion.fb_pixel_purchase",
        "onsite_web_purchase",
        "app_custom_event.fb_mobile_purchase",
    }
    conversions = 0.0
    revenue = 0.0

    for action in row.get("actions") or []:
        if not isinstance(action, dict):
            continue
        action_type = _safe_str(action.get("action_type")).lower()
        value = _safe_float(action.get("value"))
        if action_type in conversion_types or "purchase" in action_type:
            conversions += value

    for action in row.get("action_values") or []:
        if not isinstance(action, dict):
            continue
        action_type = _safe_str(action.get("action_type")).lower()
        value = _safe_float(action.get("value"))
        if action_type in conversion_types or "purchase" in action_type:
            revenue += value

    return {"conversions": conversions, "revenue": revenue}


def _metrics_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    spend = _safe_float(row.get("spend"))
    impressions = _safe_int(row.get("impressions"))
    reach = _safe_int(row.get("reach"))
    clicks = _safe_int(row.get("clicks"))

    ctr = _safe_float(row.get("ctr"))
    cpc = _safe_float(row.get("cpc"))
    cpm = _safe_float(row.get("cpm"))

    conv_rev = _extract_conversions_and_revenue(row)
    conversions = float(conv_rev["conversions"])
    revenue = float(conv_rev["revenue"])
    roas = (revenue / spend) if spend > 0 else 0.0

    # fallback quando Meta não retorna ctr/cpc/cpm em algumas combinações
    if ctr <= 0 and impressions > 0 and clicks > 0:
        ctr = (clicks / impressions) * 100.0
    if cpc <= 0 and clicks > 0:
        cpc = spend / clicks
    if cpm <= 0 and impressions > 0:
        cpm = (spend * 1000.0) / impressions

    return {
        "spend": spend,
        "impressions": impressions,
        "reach": reach,
        "clicks": clicks,
        "cpc": cpc,
        "cpm": cpm,
        "ctr": ctr,
        "conversions": conversions,
        "revenue": revenue,
        "roas": roas,
    }


async def _load_connection(connection_id: str) -> Optional[Dict[str, Any]]:
    return await get_connection_by_id(connection_id)


def _date_window(days: int) -> tuple[str, str]:
    d = max(1, min(days, 365))
    until = datetime.now(timezone.utc).date()
    since = until - timedelta(days=d - 1)
    return since.isoformat(), until.isoformat()


def _parse_iso_date_or_raise(value: str, field_name: str) -> date:
    text = _safe_str(value)
    if not text:
        raise RuntimeError(f"{field_name} é obrigatório (YYYY-MM-DD).")
    try:
        return date.fromisoformat(text[:10])
    except Exception as exc:
        raise RuntimeError(f"{field_name} inválido. Use YYYY-MM-DD.") from exc


def _normalize_period(since: str, until: str) -> tuple[str, str]:
    since_date = _parse_iso_date_or_raise(since, "since")
    until_date = _parse_iso_date_or_raise(until, "until")
    if since_date > until_date:
        since_date, until_date = until_date, since_date
    return since_date.isoformat(), until_date.isoformat()


def _http_error_text(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            return _safe_str(exc.response.text)
        except Exception:
            return _safe_str(exc)
    return _safe_str(exc)


def _is_missing_column_error(exc: Exception, column_name: str) -> bool:
    text = _http_error_text(exc).lower()
    col = _safe_str(column_name).lower()
    return col in text and ("column" in text or "schema cache" in text)


def _extract_missing_column_name(exc: Exception) -> str:
    text = _http_error_text(exc)
    if "column" not in text.lower():
        return ""
    patterns = (
        r"Could not find the '([^']+)' column",
        r'column "([^"]+)" of relation',
        r'column "([^"]+)" does not exist',
        r"column ([a-zA-Z0-9_]+) does not exist",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _safe_str(match.group(1))
    return ""


def _drop_column_from_rows(rows: List[Dict[str, Any]], column_name: str) -> tuple[List[Dict[str, Any]], bool]:
    col = _safe_str(column_name)
    if not col:
        return rows, False
    changed = False
    out: List[Dict[str, Any]] = []
    for row in rows:
        if col in row:
            row_copy = dict(row)
            row_copy.pop(col, None)
            out.append(row_copy)
            changed = True
        else:
            out.append(row)
    return out, changed


def _is_on_conflict_error(exc: Exception) -> bool:
    text = _http_error_text(exc).lower()
    return "no unique or exclusion constraint matching the on conflict specification" in text


def _is_missing_table_error(exc: Exception, table_name: str) -> bool:
    text = _http_error_text(exc).lower()
    table = _safe_str(table_name).lower()
    return table in text and (
        "relation" in text
        or "does not exist" in text
        or "schema cache" in text
    )


def _story_id_from_catalog_row(row: Dict[str, Any]) -> str:
    creative = row.get("creative") or {}
    if isinstance(creative, dict):
        candidate = _safe_str(creative.get("effective_object_story_id"))
        if candidate:
            return candidate
        candidate = _safe_str(creative.get("object_story_id"))
        if candidate:
            return candidate
        # Fallback para criativos de promoção onde só object_id vem preenchido.
        candidate = _safe_str(creative.get("object_id"))
        if candidate:
            return candidate
    return ""


def _post_id_from_story_id(story_id: str) -> str:
    text = _safe_str(story_id)
    if not text:
        return ""
    if "_" not in text:
        return text
    return text.split("_", 1)[1].strip()


def _ad_day_key(row: Dict[str, Any]) -> tuple[str, str]:
    return (
        _safe_str(row.get("ad_id")),
        _safe_str(row.get("date_start")),
    )


def _boosted_rows_not_in_classic(
    *,
    boosted_rows: List[Dict[str, Any]],
    classic_ad_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    classic_keys = {
        _ad_day_key(row)
        for row in classic_ad_rows
        if _safe_str(row.get("ad_id")) and _safe_str(row.get("date_start"))
    }
    out: List[Dict[str, Any]] = []
    for row in boosted_rows:
        ad_id = _safe_str(row.get("ad_id"))
        stat_date = _safe_str(row.get("date_start"))
        if not ad_id or not stat_date:
            continue
        key = (ad_id, stat_date)
        if key in classic_keys:
            continue
        out.append(row)
    return out


def _platform_from_story_id(story_id: str) -> str:
    text = _safe_str(story_id)
    if "_" in text:
        return "facebook"
    return "instagram"


def _campaign_meta_from_catalog_row(row: Dict[str, Any]) -> Dict[str, str]:
    campaign = row.get("campaign") or {}
    campaign_id = _safe_str(row.get("campaign_id"))
    campaign_name = ""
    objective = ""
    if isinstance(campaign, dict):
        campaign_id = _safe_str(campaign.get("id")) or campaign_id
        campaign_name = _safe_str(campaign.get("name"))
        objective = _safe_str(campaign.get("objective"))
    if not campaign_name:
        campaign_name = _safe_str(row.get("campaign_name"))
    if not objective:
        objective = _safe_str(row.get("objective"))
    return {
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "objective": objective,
    }


def _adset_meta_from_catalog_row(row: Dict[str, Any]) -> Dict[str, str]:
    adset = row.get("adset") or {}
    adset_id = _safe_str(row.get("adset_id"))
    adset_name = _safe_str(row.get("adset_name"))
    if isinstance(adset, dict):
        adset_id = _safe_str(adset.get("id")) or adset_id
        adset_name = _safe_str(adset.get("name")) or adset_name
    return {"adset_id": adset_id, "adset_name": adset_name}


async def _count_persisted_rows_for_period(
    *,
    table: str,
    client_id: str,
    connection_id: str,
    ad_account_id: str,
    since: str,
    until: str,
    allow_missing_table: bool = False,
    limit: int = 50000,
) -> Dict[str, Any]:
    base_filters = {
        "client_id": f"eq.{client_id}",
        "and": f"(stat_date.gte.{since},stat_date.lte.{until})",
    }
    mode = "client_scope"
    filters = dict(base_filters)
    if connection_id:
        filters["connection_id"] = f"eq.{connection_id}"
        mode = "connection_scope"

    try:
        rows = await sb_select(
            table,
            select="stat_date",
            filters=filters,
            limit=limit,
        )
        if rows or mode != "connection_scope":
            return {"count": len(rows), "mode": mode}

        account_variants = _ad_account_variants(ad_account_id)
        if not account_variants:
            return {"count": len(rows), "mode": mode}
        for account_id in account_variants:
            account_filters = dict(base_filters)
            account_filters["ad_account_id"] = f"eq.{account_id}"
            try:
                scoped_rows = await sb_select(
                    table,
                    select="stat_date",
                    filters=account_filters,
                    limit=limit,
                )
            except Exception as account_exc:
                if _is_missing_column_error(account_exc, "ad_account_id"):
                    break
                raise
            if scoped_rows:
                return {"count": len(scoped_rows), "mode": "ad_account_scope_fallback"}
        return {"count": len(rows), "mode": mode}
    except Exception as exc:
        if allow_missing_table and _is_missing_table_error(exc, table):
            return {"count": 0, "mode": "table_missing"}
        if not (connection_id and _is_missing_column_error(exc, "connection_id")):
            raise
        rows = await sb_select(
            table,
            select="stat_date",
            filters=base_filters,
            limit=limit,
        )
        return {"count": len(rows), "mode": "connection_column_missing"}


async def _readback_persisted_rows(
    *,
    client_id: str,
    connection_id: str,
    ad_account_id: str,
    since: str,
    until: str,
) -> Dict[str, Dict[str, Any]]:
    return {
        "ad_account_daily_stats": await _count_persisted_rows_for_period(
            table="ad_account_daily_stats",
            client_id=client_id,
            connection_id=connection_id,
            ad_account_id=ad_account_id,
            since=since,
            until=until,
        ),
        "campaign_daily_stats": await _count_persisted_rows_for_period(
            table="campaign_daily_stats",
            client_id=client_id,
            connection_id=connection_id,
            ad_account_id=ad_account_id,
            since=since,
            until=until,
        ),
        "ad_daily_stats": await _count_persisted_rows_for_period(
            table="ad_daily_stats",
            client_id=client_id,
            connection_id=connection_id,
            ad_account_id=ad_account_id,
            since=since,
            until=until,
        ),
        "promoted_post_daily_stats": await _count_persisted_rows_for_period(
            table="promoted_post_daily_stats",
            client_id=client_id,
            connection_id=connection_id,
            ad_account_id=ad_account_id,
            since=since,
            until=until,
            allow_missing_table=True,
        ),
    }


async def _fetch_boosted_insight_rows(
    *,
    ad_account_id: str,
    access_token: str,
    since: str,
    until: str,
    request_context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    catalog_rows_status_filtered: List[Dict[str, Any]] = []
    status_filter_error = ""
    try:
        catalog_rows_status_filtered = await fetch_ad_catalog(
            ad_account_id=ad_account_id,
            access_token=access_token,
            effective_statuses=CATALOG_EFFECTIVE_STATUSES,
            limit=500,
            request_context=request_context,
        )
    except Exception as exc:
        status_filter_error = _safe_str(exc)[:260]
        print(
            "[ads_sync][boosted][catalog_status_warning] "
            f"ad_account_id={ad_account_id} since={since} until={until} "
            f"error={status_filter_error or '-'}"
        )
    catalog_rows_all_statuses = await fetch_ad_catalog(
        ad_account_id=ad_account_id,
        access_token=access_token,
        effective_statuses=None,
        limit=500,
        request_context=request_context,
    )
    # Preferimos o catálogo com status por ser mais previsível;
    # se vazio, usamos all_statuses para descobrir turbinados legados.
    catalog_source = "status_filtered"
    catalog_rows = catalog_rows_status_filtered
    if not catalog_rows:
        catalog_source = "all_statuses"
        catalog_rows = catalog_rows_all_statuses

    catalog_samples: List[Dict[str, Any]] = []
    for row in catalog_rows[:5]:
        creative = row.get("creative") or {}
        promoted = row.get("promoted_object") or {}
        if not isinstance(creative, dict):
            creative = {}
        if not isinstance(promoted, dict):
            promoted = {}
        catalog_samples.append(
            {
                "ad_id": _safe_str(row.get("id")),
                "campaign_id": _safe_str(row.get("campaign_id")),
                "creative_id": _safe_str(creative.get("id")),
                "object_story_id": _safe_str(creative.get("object_story_id")),
                "effective_object_story_id": _safe_str(creative.get("effective_object_story_id")),
                "object_id": _safe_str(creative.get("object_id")),
                "promoted_post_id": _safe_str(promoted.get("post_id")),
                "promoted_page_id": _safe_str(promoted.get("page_id")),
                "promoted_ig_actor_id": _safe_str(promoted.get("instagram_actor_id")),
            }
        )
    print(
        "[ads_sync][boosted][catalog_probe] "
        f"ad_account_id={ad_account_id} since={since} until={until} "
        f"rows_with_status={len(catalog_rows_status_filtered)} "
        f"rows_without_status={len(catalog_rows_all_statuses)} "
        f"catalog_source_used={catalog_source} "
        f"status_filter_error={status_filter_error or '-'} "
        f"samples={json.dumps(catalog_samples, ensure_ascii=False)[:900]}"
    )

    boosted_meta: Dict[str, Dict[str, str]] = {}
    for row in catalog_rows:
        ad_id = _safe_str(row.get("id"))
        if not ad_id:
            continue
        story_id = _story_id_from_catalog_row(row)
        if not story_id:
            continue
        campaign_meta = _campaign_meta_from_catalog_row(row)
        adset_meta = _adset_meta_from_catalog_row(row)
        boosted_meta[ad_id] = {
            "ad_id": ad_id,
            "ad_name": _safe_str(row.get("name")),
            "story_id": story_id,
            "post_id": _post_id_from_story_id(story_id),
            "source_platform": _platform_from_story_id(story_id),
            **campaign_meta,
            **adset_meta,
        }

    boosted_rows: List[Dict[str, Any]] = []
    failed_ads = 0
    ads_with_daily_rows = 0
    ads_with_all_days_rows = 0
    ads_without_rows = 0
    for ad_id, meta in boosted_meta.items():
        try:
            rows = await fetch_entity_insights(
                entity_id=ad_id,
                access_token=access_token,
                since=since,
                until=until,
                level=None,
                fields=(
                    "date_start,date_stop,ad_id,ad_name,campaign_id,campaign_name,adset_id,adset_name,"
                    "spend,impressions,reach,clicks,cpc,ctr,cpm,actions,action_values"
                ),
                time_increment=1,
                limit=200,
                request_context=request_context,
            )
            insight_source = "entity_insights_daily"
            if not rows:
                rows = await fetch_entity_insights(
                    entity_id=ad_id,
                    access_token=access_token,
                    since=since,
                    until=until,
                    level=None,
                    fields=(
                        "date_start,date_stop,ad_id,ad_name,campaign_id,campaign_name,adset_id,adset_name,"
                        "spend,impressions,reach,clicks,cpc,ctr,cpm,actions,action_values"
                    ),
                    time_increment="all_days",
                    limit=200,
                    request_context=request_context,
                )
                if rows:
                    insight_source = "entity_insights_all_days"
        except Exception as exc:
            failed_ads += 1
            print(
                "[ads_sync][boosted][ad_error] "
                f"ad_account_id={ad_account_id} ad_id={ad_id} since={since} until={until} "
                f"error={_safe_str(exc)[:240]}"
            )
            continue

        if not rows:
            ads_without_rows += 1
            continue
        if insight_source == "entity_insights_all_days":
            ads_with_all_days_rows += 1
        else:
            ads_with_daily_rows += 1

        for row in rows:
            merged = dict(row)
            merged["ad_id"] = _safe_str(row.get("ad_id")) or meta.get("ad_id")
            merged["ad_name"] = _safe_str(row.get("ad_name")) or meta.get("ad_name")
            merged["campaign_id"] = _safe_str(row.get("campaign_id")) or meta.get("campaign_id")
            merged["campaign_name"] = _safe_str(row.get("campaign_name")) or meta.get("campaign_name")
            merged["adset_id"] = _safe_str(row.get("adset_id")) or meta.get("adset_id")
            merged["adset_name"] = _safe_str(row.get("adset_name")) or meta.get("adset_name")
            merged["objective"] = _safe_str(row.get("objective")) or meta.get("objective")
            merged["story_id"] = meta.get("story_id")
            merged["post_id"] = meta.get("post_id")
            merged["source_platform"] = meta.get("source_platform")
            merged["boosted_source"] = insight_source
            boosted_rows.append(merged)

    print(
        "[ads_sync][boosted][discovery] "
        f"ad_account_id={ad_account_id} since={since} until={until} "
        f"catalog_source={catalog_source} "
        f"catalog_rows={len(catalog_rows)} boosted_ads={len(boosted_meta)} "
        f"ads_daily={ads_with_daily_rows} ads_all_days={ads_with_all_days_rows} "
        f"ads_without_rows={ads_without_rows} failed_ads={failed_ads} "
        f"boosted_rows={len(boosted_rows)}"
    )
    return boosted_rows


def _to_upsert_ready_ad_account_rows(
    *,
    client_id: str,
    connection_id: str,
    meta_connection_id: str,
    ad_account_id: str,
    ad_account_name: str,
    since: str,
    raw_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    by_day: Dict[str, Dict[str, Any]] = {}
    for row in raw_rows:
        stat_date = _safe_str(row.get("date_start")) or since
        if stat_date not in by_day:
            by_day[stat_date] = {
                "client_id": client_id,
                "connection_id": connection_id,
                "meta_connection_id": meta_connection_id,
                "stat_date": stat_date,
                "ad_account_id": ad_account_id,
                "ad_account_name": ad_account_name or _safe_str(row.get("account_name")),
                "spend": 0.0,
                "impressions": 0,
                "reach": 0,
                "clicks": 0,
                "cpc": 0.0,
                "cpm": 0.0,
                "ctr": 0.0,
                "conversions": 0.0,
                "revenue": 0.0,
                "roas": 0.0,
                "raw_json": [],
            }

        day_row = by_day[stat_date]
        metrics = _metrics_payload(row)
        day_row["spend"] += float(metrics.get("spend") or 0.0)
        day_row["impressions"] += int(metrics.get("impressions") or 0)
        day_row["reach"] += int(metrics.get("reach") or 0)
        day_row["clicks"] += int(metrics.get("clicks") or 0)
        day_row["conversions"] += float(metrics.get("conversions") or 0.0)
        day_row["revenue"] += float(metrics.get("revenue") or 0.0)
        if isinstance(day_row.get("raw_json"), list):
            day_row["raw_json"].append(row)

    out_rows: List[Dict[str, Any]] = []
    for stat_date, row in sorted(by_day.items(), key=lambda item: item[0]):
        spend = float(row.get("spend") or 0.0)
        impressions = int(row.get("impressions") or 0)
        clicks = int(row.get("clicks") or 0)
        revenue = float(row.get("revenue") or 0.0)
        row["cpc"] = (spend / clicks) if clicks > 0 else 0.0
        row["cpm"] = ((spend * 1000.0) / impressions) if impressions > 0 else 0.0
        row["ctr"] = ((clicks / impressions) * 100.0) if impressions > 0 else 0.0
        row["roas"] = (revenue / spend) if spend > 0 else 0.0
        out_rows.append(row)
    return out_rows


async def _upsert_ad_account_daily_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"table": "ad_account_daily_stats", "upserted": 0, "on_conflict": "-"}

    rows_to_upsert = [dict(row) for row in rows]
    dropped_columns: List[str] = []
    attempts = [
        ("client_id,meta_connection_id,ad_account_id,stat_date", "meta_connection_id"),
        ("client_id,connection_id,ad_account_id,stat_date", "connection_id"),
        ("client_id,ad_account_id,stat_date", ""),
    ]

    for on_conflict, compat_column in attempts:
        while True:
            try:
                await sb_upsert(
                    "ad_account_daily_stats",
                    rows_to_upsert,
                    on_conflict=on_conflict,
                )
                result: Dict[str, Any] = {
                    "table": "ad_account_daily_stats",
                    "upserted": len(rows_to_upsert),
                    "on_conflict": on_conflict,
                }
                if dropped_columns:
                    result["dropped_columns"] = dropped_columns
                return result
            except Exception as exc:
                if compat_column and (
                    _is_missing_column_error(exc, compat_column) or _is_on_conflict_error(exc)
                ):
                    rows_without_compat, changed = _drop_column_from_rows(rows_to_upsert, compat_column)
                    if changed:
                        rows_to_upsert = rows_without_compat
                        if compat_column not in dropped_columns:
                            dropped_columns.append(compat_column)
                    print(
                        "[ads_sync][upsert_fallback] "
                        f"table=ad_account_daily_stats reason={compat_column}_unavailable"
                    )
                    break

                missing_col = _extract_missing_column_name(exc)
                rows_without_col, changed = _drop_column_from_rows(rows_to_upsert, missing_col)
                if changed:
                    rows_to_upsert = rows_without_col
                    if missing_col not in dropped_columns:
                        dropped_columns.append(missing_col)
                    print(
                        "[ads_sync][upsert_fallback] "
                        f"table=ad_account_daily_stats reason=missing_column column={missing_col}"
                    )
                    continue
                raise

    return {
        "table": "ad_account_daily_stats",
        "upserted": len(rows_to_upsert),
        "on_conflict": "client_id,ad_account_id,stat_date",
        "dropped_columns": dropped_columns,
    }


def _to_upsert_ready_campaign_rows(
    *,
    client_id: str,
    connection_id: str,
    ad_account_id: str,
    ad_account_name: str,
    since: str,
    raw_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    by_key: Dict[tuple[str, str], Dict[str, Any]] = {}
    for row in raw_rows:
        campaign_id = _safe_str(row.get("campaign_id"))
        if not campaign_id:
            continue
        stat_date = _safe_str(row.get("date_start")) or since
        key = (campaign_id, stat_date)
        if key not in by_key:
            by_key[key] = {
                "client_id": client_id,
                "connection_id": connection_id,
                "stat_date": stat_date,
                "ad_account_id": ad_account_id,
                "ad_account_name": ad_account_name or _safe_str(row.get("account_name")),
                "campaign_id": campaign_id,
                "campaign_name": _safe_str(row.get("campaign_name")),
                "campaign_status": _safe_str(row.get("campaign_status")),
                "objective": _safe_str(row.get("objective")),
                "spend": 0.0,
                "impressions": 0,
                "reach": 0,
                "clicks": 0,
                "cpc": 0.0,
                "cpm": 0.0,
                "ctr": 0.0,
                "conversions": 0.0,
                "revenue": 0.0,
                "roas": 0.0,
                "raw_json": [],
            }

        out_row = by_key[key]
        metrics = _metrics_payload(row)
        out_row["spend"] += float(metrics.get("spend") or 0.0)
        out_row["impressions"] += int(metrics.get("impressions") or 0)
        out_row["reach"] += int(metrics.get("reach") or 0)
        out_row["clicks"] += int(metrics.get("clicks") or 0)
        out_row["conversions"] += float(metrics.get("conversions") or 0.0)
        out_row["revenue"] += float(metrics.get("revenue") or 0.0)
        if isinstance(out_row.get("raw_json"), list):
            out_row["raw_json"].append(row)

        campaign_name = _safe_str(row.get("campaign_name"))
        if campaign_name:
            out_row["campaign_name"] = campaign_name
        campaign_status = _safe_str(row.get("campaign_status"))
        if campaign_status:
            out_row["campaign_status"] = campaign_status
        objective = _safe_str(row.get("objective"))
        if objective:
            out_row["objective"] = objective

    out_rows: List[Dict[str, Any]] = []
    for _, row in sorted(by_key.items(), key=lambda item: (item[0][1], item[0][0])):
        spend = float(row.get("spend") or 0.0)
        impressions = int(row.get("impressions") or 0)
        clicks = int(row.get("clicks") or 0)
        revenue = float(row.get("revenue") or 0.0)
        row["cpc"] = (spend / clicks) if clicks > 0 else 0.0
        row["cpm"] = ((spend * 1000.0) / impressions) if impressions > 0 else 0.0
        row["ctr"] = ((clicks / impressions) * 100.0) if impressions > 0 else 0.0
        row["roas"] = (revenue / spend) if spend > 0 else 0.0
        out_rows.append(row)
    return out_rows


def _to_upsert_ready_ad_rows(
    *,
    client_id: str,
    connection_id: str,
    ad_account_id: str,
    ad_account_name: str,
    since: str,
    raw_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    by_key: Dict[tuple[str, str], Dict[str, Any]] = {}
    for row in raw_rows:
        ad_id = _safe_str(row.get("ad_id"))
        if not ad_id:
            continue
        stat_date = _safe_str(row.get("date_start")) or since
        key = (ad_id, stat_date)
        if key not in by_key:
            by_key[key] = {
                "client_id": client_id,
                "connection_id": connection_id,
                "stat_date": stat_date,
                "ad_account_id": ad_account_id,
                "ad_account_name": ad_account_name or _safe_str(row.get("account_name")),
                "campaign_id": _safe_str(row.get("campaign_id")),
                "campaign_name": _safe_str(row.get("campaign_name")),
                "adset_id": _safe_str(row.get("adset_id")),
                "adset_name": _safe_str(row.get("adset_name")),
                "ad_id": ad_id,
                "ad_name": _safe_str(row.get("ad_name")),
                "ad_status": _safe_str(row.get("ad_status")),
                "spend": 0.0,
                "impressions": 0,
                "reach": 0,
                "clicks": 0,
                "cpc": 0.0,
                "cpm": 0.0,
                "ctr": 0.0,
                "conversions": 0.0,
                "revenue": 0.0,
                "roas": 0.0,
                "raw_json": [],
            }

        out_row = by_key[key]
        metrics = _metrics_payload(row)
        out_row["spend"] += float(metrics.get("spend") or 0.0)
        out_row["impressions"] += int(metrics.get("impressions") or 0)
        out_row["reach"] += int(metrics.get("reach") or 0)
        out_row["clicks"] += int(metrics.get("clicks") or 0)
        out_row["conversions"] += float(metrics.get("conversions") or 0.0)
        out_row["revenue"] += float(metrics.get("revenue") or 0.0)
        if isinstance(out_row.get("raw_json"), list):
            out_row["raw_json"].append(row)

        ad_name = _safe_str(row.get("ad_name"))
        if ad_name:
            out_row["ad_name"] = ad_name
        ad_status = _safe_str(row.get("ad_status"))
        if ad_status:
            out_row["ad_status"] = ad_status

    out_rows: List[Dict[str, Any]] = []
    for _, row in sorted(by_key.items(), key=lambda item: (item[0][1], item[0][0])):
        spend = float(row.get("spend") or 0.0)
        impressions = int(row.get("impressions") or 0)
        clicks = int(row.get("clicks") or 0)
        revenue = float(row.get("revenue") or 0.0)
        row["cpc"] = (spend / clicks) if clicks > 0 else 0.0
        row["cpm"] = ((spend * 1000.0) / impressions) if impressions > 0 else 0.0
        row["ctr"] = ((clicks / impressions) * 100.0) if impressions > 0 else 0.0
        row["roas"] = (revenue / spend) if spend > 0 else 0.0
        out_rows.append(row)
    return out_rows


async def _upsert_campaign_daily_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"table": "campaign_daily_stats", "upserted": 0, "on_conflict": "-"}
    rows_to_upsert = [dict(row) for row in rows]
    dropped_columns: List[str] = []
    for _ in range(10):
        try:
            await sb_upsert("campaign_daily_stats", rows_to_upsert, on_conflict="client_id,campaign_id,stat_date")
            result: Dict[str, Any] = {
                "table": "campaign_daily_stats",
                "upserted": len(rows_to_upsert),
                "on_conflict": "client_id,campaign_id,stat_date",
            }
            if dropped_columns:
                result["dropped_columns"] = dropped_columns
            return result
        except Exception as exc:
            missing_col = _extract_missing_column_name(exc)
            rows_without_col, changed = _drop_column_from_rows(rows_to_upsert, missing_col)
            if changed:
                dropped_columns.append(missing_col)
                rows_to_upsert = rows_without_col
                print(
                    "[ads_sync][upsert_fallback] "
                    f"table=campaign_daily_stats reason=missing_column column={missing_col}"
                )
                continue
            raise
    return {
        "table": "campaign_daily_stats",
        "upserted": len(rows_to_upsert),
        "on_conflict": "client_id,campaign_id,stat_date",
        "dropped_columns": dropped_columns,
    }


async def _upsert_ad_daily_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"table": "ad_daily_stats", "upserted": 0, "on_conflict": "-"}
    rows_to_upsert = [dict(row) for row in rows]
    dropped_columns: List[str] = []
    for _ in range(10):
        try:
            await sb_upsert("ad_daily_stats", rows_to_upsert, on_conflict="client_id,ad_id,stat_date")
            result: Dict[str, Any] = {
                "table": "ad_daily_stats",
                "upserted": len(rows_to_upsert),
                "on_conflict": "client_id,ad_id,stat_date",
            }
            if dropped_columns:
                result["dropped_columns"] = dropped_columns
            return result
        except Exception as exc:
            missing_col = _extract_missing_column_name(exc)
            rows_without_col, changed = _drop_column_from_rows(rows_to_upsert, missing_col)
            if changed:
                dropped_columns.append(missing_col)
                rows_to_upsert = rows_without_col
                print(
                    "[ads_sync][upsert_fallback] "
                    f"table=ad_daily_stats reason=missing_column column={missing_col}"
                )
                continue
            raise
    return {
        "table": "ad_daily_stats",
        "upserted": len(rows_to_upsert),
        "on_conflict": "client_id,ad_id,stat_date",
        "dropped_columns": dropped_columns,
    }


def _to_upsert_ready_promoted_post_rows(
    *,
    client_id: str,
    connection_id: str,
    ad_account_id: str,
    ad_account_name: str,
    since: str,
    raw_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    by_key: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    for row in raw_rows:
        ad_id = _safe_str(row.get("ad_id"))
        story_id = _safe_str(row.get("story_id"))
        post_id = _safe_str(row.get("post_id")) or _post_id_from_story_id(story_id)
        if not ad_id or not post_id:
            continue
        stat_date = _safe_str(row.get("date_start")) or since
        key = (ad_id, post_id, stat_date)
        if key not in by_key:
            by_key[key] = {
                "client_id": client_id,
                "connection_id": connection_id,
                "stat_date": stat_date,
                "ad_account_id": ad_account_id,
                "ad_account_name": ad_account_name or _safe_str(row.get("account_name")),
                "campaign_id": _safe_str(row.get("campaign_id")),
                "campaign_name": _safe_str(row.get("campaign_name")),
                "adset_id": _safe_str(row.get("adset_id")),
                "adset_name": _safe_str(row.get("adset_name")),
                "ad_id": ad_id,
                "ad_name": _safe_str(row.get("ad_name")),
                "post_id": post_id,
                "story_id": story_id,
                "source_platform": _safe_str(row.get("source_platform")) or _platform_from_story_id(story_id),
                "objective": _safe_str(row.get("objective")),
                "spend": 0.0,
                "impressions": 0,
                "reach": 0,
                "clicks": 0,
                "cpc": 0.0,
                "cpm": 0.0,
                "ctr": 0.0,
                "conversions": 0.0,
                "revenue": 0.0,
                "roas": 0.0,
                "raw_json": [],
            }

        out_row = by_key[key]
        metrics = _metrics_payload(row)
        out_row["spend"] += float(metrics.get("spend") or 0.0)
        out_row["impressions"] += int(metrics.get("impressions") or 0)
        out_row["reach"] += int(metrics.get("reach") or 0)
        out_row["clicks"] += int(metrics.get("clicks") or 0)
        out_row["conversions"] += float(metrics.get("conversions") or 0.0)
        out_row["revenue"] += float(metrics.get("revenue") or 0.0)
        if isinstance(out_row.get("raw_json"), list):
            out_row["raw_json"].append(row)

    out_rows: List[Dict[str, Any]] = []
    for _, row in sorted(by_key.items(), key=lambda item: (item[0][2], item[0][0], item[0][1])):
        spend = float(row.get("spend") or 0.0)
        impressions = int(row.get("impressions") or 0)
        clicks = int(row.get("clicks") or 0)
        revenue = float(row.get("revenue") or 0.0)
        row["cpc"] = (spend / clicks) if clicks > 0 else 0.0
        row["cpm"] = ((spend * 1000.0) / impressions) if impressions > 0 else 0.0
        row["ctr"] = ((clicks / impressions) * 100.0) if impressions > 0 else 0.0
        row["roas"] = (revenue / spend) if spend > 0 else 0.0
        out_rows.append(row)
    return out_rows


async def _upsert_promoted_post_daily_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"table": "promoted_post_daily_stats", "upserted": 0, "on_conflict": "-", "source": "boosted_posts"}
    try:
        await sb_upsert(
            "promoted_post_daily_stats",
            rows,
            on_conflict="client_id,connection_id,ad_account_id,post_id,ad_id,stat_date",
        )
        return {
            "table": "promoted_post_daily_stats",
            "upserted": len(rows),
            "on_conflict": "client_id,connection_id,ad_account_id,post_id,ad_id,stat_date",
            "source": "boosted_posts",
        }
    except Exception as exc:
        if _is_missing_table_error(exc, "promoted_post_daily_stats"):
            print(
                "[ads_sync][upsert_skip] "
                "table=promoted_post_daily_stats reason=table_missing"
            )
            return {
                "table": "promoted_post_daily_stats",
                "upserted": 0,
                "on_conflict": "-",
                "source": "boosted_posts",
                "skipped": True,
                "reason": "table_missing",
            }
        if not (_is_missing_column_error(exc, "connection_id") or _is_on_conflict_error(exc)):
            raise

    rows_no_conn: List[Dict[str, Any]] = []
    for row in rows:
        row_copy = dict(row)
        row_copy.pop("connection_id", None)
        rows_no_conn.append(row_copy)

    await sb_upsert(
        "promoted_post_daily_stats",
        rows_no_conn,
        on_conflict="client_id,ad_account_id,post_id,ad_id,stat_date",
    )
    return {
        "table": "promoted_post_daily_stats",
        "upserted": len(rows_no_conn),
        "on_conflict": "client_id,ad_account_id,post_id,ad_id,stat_date",
        "source": "boosted_posts",
    }


async def _pick_paid_connection(
    client_id: str,
    preferred_connection_id: str | None = None,
) -> Dict[str, Any]:
    cid = _safe_str(client_id)
    requested = _safe_str(preferred_connection_id) or None
    resolved = await resolve_connection_for_scope(
        client_id=cid,
        platform="meta_ads",
        connection_type="paid",
        requested_connection_id=requested,
        require_ad_account=True,
    )
    if not requested and not _safe_str((resolved.get("row") or {}).get("id")):
        try:
            applied = await bootstrap_meta_from_env()
            print(
                "[ads_sync][bootstrap] "
                f"client_id={cid} reason=missing_paid_connection applied={','.join(applied) or '-'}"
            )
        except Exception as exc:
            print(
                "[ads_sync][bootstrap][warning] "
                f"client_id={cid} reason=missing_paid_connection error={_safe_str(exc)[:280]}"
            )
        resolved = await resolve_connection_for_scope(
            client_id=cid,
            platform="meta_ads",
            connection_type="paid",
            requested_connection_id=None,
            require_ad_account=True,
        )
    conn = dict(resolved.get("row") or {})
    conn_id = _safe_str(conn.get("id"))
    if not conn_id:
        raise RuntimeError("Cliente sem conexão Meta Ads ativa. Conecte e selecione uma conta de anúncio.")
    conn["_resolved_source"] = str(resolved.get("source") or "none").strip() or "none"
    print(
        "[ads_sync][paid_connection] "
        f"client_id={cid} connection_id={conn_id} "
        f"ad_account_id={_normalize_ad_account_id(_safe_str(conn.get('ad_account_id'))) or '-'} "
        f"source={conn['_resolved_source']}"
    )
    return conn


def _sum_rows_upserted(result: Dict[str, Any]) -> int:
    saved = result.get("saved") or {}
    return (
        int(saved.get("ad_account_daily_stats") or 0)
        + int(saved.get("campaign_daily_stats") or 0)
        + int(saved.get("ad_daily_stats") or 0)
        + int(saved.get("promoted_post_daily_stats") or 0)
    )


async def sync_ads_for_client_period(
    *,
    client_id: str,
    since: str,
    until: str,
    connection_id: str | None = None,
    job_name: str = "meta_ads_manual_sync",
    trigger_source: str = "manual",
    record_job_run: bool = True,
) -> Dict[str, Any]:
    cid = _safe_str(client_id)
    if not cid:
        raise RuntimeError("client_id é obrigatório para sync de Ads.")

    since_in = _safe_str(since)
    until_in = _safe_str(until)
    if since_in and until_in:
        period_since, period_until = _normalize_period(since_in, until_in)
    elif since_in:
        period_since, period_until = _normalize_period(since_in, since_in)
    elif until_in:
        period_since, period_until = _normalize_period(until_in, until_in)
    else:
        period_since, period_until = _date_window(30)

    requested_connection_id = _safe_str(connection_id) or None
    job_run = (
        await start_job_run(
            job_name=job_name,
            client_id=cid,
            connection_id=requested_connection_id,
            trigger_source=trigger_source,
            payload_json={
                "date_range": {"since": period_since, "until": period_until},
                "requested_connection_id": requested_connection_id,
            },
        )
        if record_job_run
        else None
    )

    try:
        conn = await _pick_paid_connection(cid, preferred_connection_id=requested_connection_id)
    except Exception as exc:
        if job_run:
            await finish_job_run(
                job_run["id"],
                status="error",
                error=str(exc),
                client_id=cid,
                connection_id=requested_connection_id,
                payload_json={
                    "date_range": {"since": period_since, "until": period_until},
                    "requested_connection_id": requested_connection_id,
                },
            )
        raise

    resolved_connection_id = _safe_str(conn.get("id"))
    resolved_connection_source = _safe_str(conn.get("_resolved_source")) or "none"
    ad_account_id = _normalize_ad_account_id(_safe_str(conn.get("ad_account_id")))
    ad_account_name = _safe_str(conn.get("ad_account_name"))
    if not resolved_connection_id:
        raise RuntimeError("Conexão Meta Ads inválida (id ausente).")
    if not ad_account_id:
        raise RuntimeError("Conexão Meta Ads inválida (ad_account_id ausente).")

    print(
        "[ads_sync][start] "
        f"client_id={cid} connection_id={resolved_connection_id} ad_account_id={ad_account_id} "
        f"connection_source={resolved_connection_source} since={period_since} until={period_until}"
    )

    request_context = {
        "client_id": cid,
        "connection_id": resolved_connection_id,
        "ad_account_id": ad_account_id,
    }

    try:
        token = await ensure_valid_meta_token(
            cid,
            connection_id=resolved_connection_id,
            platform="meta_ads",
            connection_type="paid",
        )
        account_rows_raw = await fetch_ad_account_insights(
            ad_account_id=ad_account_id,
            access_token=token,
            since=period_since,
            until=period_until,
            level=None,
            fields=(
                "account_id,account_name,date_start,date_stop,"
                "spend,impressions,reach,clicks,cpc,ctr,cpm,actions,action_values"
            ),
            time_increment=1,
            limit=500,
            request_context=request_context,
        )
        campaign_rows_raw = await fetch_ad_account_insights(
            ad_account_id=ad_account_id,
            access_token=token,
            since=period_since,
            until=period_until,
            level="campaign",
            fields=(
                "account_id,account_name,date_start,date_stop,campaign_id,campaign_name,"
                "objective,spend,impressions,reach,clicks,cpc,ctr,cpm,actions,action_values"
            ),
            time_increment=1,
            limit=1000,
            request_context=request_context,
        )
        ad_rows_raw = await fetch_ad_account_insights(
            ad_account_id=ad_account_id,
            access_token=token,
            since=period_since,
            until=period_until,
            level="ad",
            fields=(
                "account_id,account_name,date_start,date_stop,campaign_id,campaign_name,"
                "adset_id,adset_name,ad_id,ad_name,spend,impressions,reach,clicks,"
                "cpc,ctr,cpm,actions,action_values"
            ),
            time_increment=1,
            limit=1500,
            request_context=request_context,
        )
        boosted_rows_raw: List[Dict[str, Any]] = []
        try:
            boosted_rows_raw = await _fetch_boosted_insight_rows(
                ad_account_id=ad_account_id,
                access_token=token,
                since=period_since,
                until=period_until,
                request_context=request_context,
            )
        except Exception as boosted_exc:
            print(
                "[ads_sync][boosted][warning] "
                f"client_id={cid} connection_id={resolved_connection_id} ad_account_id={ad_account_id} "
                f"since={period_since} until={period_until} error={_safe_str(boosted_exc)[:320]}"
            )
            boosted_rows_raw = []
        boosted_sources_count = _count_boosted_sources(boosted_rows_raw)
        print(
            "[ads_sync][boosted][source] "
            f"client_id={cid} connection_id={resolved_connection_id} ad_account_id={ad_account_id} "
            f"since={period_since} until={period_until} "
            f"rows_daily={boosted_sources_count['entity_insights_daily']} "
            f"rows_all_days={boosted_sources_count['entity_insights_all_days']} "
            f"rows_maximum_synthetic={boosted_sources_count['insights_maximum_synthetic']} "
            f"rows_unknown={boosted_sources_count['unknown']}"
        )
        boosted_rows_for_classic = _boosted_rows_not_in_classic(
            boosted_rows=boosted_rows_raw,
            classic_ad_rows=ad_rows_raw,
        )
        if (
            not account_rows_raw
            and not campaign_rows_raw
            and not ad_rows_raw
            and not boosted_rows_raw
        ):
            creatives_probe_rows: List[Dict[str, Any]] = []
            insights_probe_rows: List[Dict[str, Any]] = []
            try:
                creatives_probe_rows = await fetch_ad_creatives(
                    ad_account_id=ad_account_id,
                    access_token=token,
                    limit=200,
                    request_context=request_context,
                )
            except Exception as probe_exc:
                print(
                    "[ads_sync][probe][adcreatives_error] "
                    f"client_id={cid} connection_id={resolved_connection_id} ad_account_id={ad_account_id} "
                    f"since={period_since} until={period_until} error={_safe_str(probe_exc)[:280]}"
                )
            try:
                insights_probe_rows = await fetch_ad_account_insights(
                    ad_account_id=ad_account_id,
                    access_token=token,
                    since=period_since,
                    until=period_until,
                    level="ad",
                    fields=(
                        "date_start,date_stop,ad_id,ad_name,campaign_id,campaign_name,"
                        "adset_id,adset_name,spend,impressions,reach,clicks,cpc,ctr,cpm,"
                        "actions,action_values"
                    ),
                    time_increment="all_days",
                    date_preset="maximum",
                    limit=2000,
                    request_context=request_context,
                )
            except Exception as probe_exc:
                print(
                    "[ads_sync][probe][insights_error] "
                    f"client_id={cid} connection_id={resolved_connection_id} ad_account_id={ad_account_id} "
                    f"since={period_since} until={period_until} error={_safe_str(probe_exc)[:280]}"
                )

            creative_story_count = 0
            creative_effective_story_count = 0
            creative_object_id_count = 0
            creative_post_spec_count = 0
            creative_samples: List[Dict[str, Any]] = []
            for row in creatives_probe_rows:
                story_id = _safe_str(row.get("object_story_id"))
                effective_story_id = _safe_str(row.get("effective_object_story_id"))
                object_id = _safe_str(row.get("object_id"))
                story_spec = row.get("object_story_spec")
                has_story_spec = isinstance(story_spec, dict) and bool(story_spec)
                if story_id:
                    creative_story_count += 1
                if effective_story_id:
                    creative_effective_story_count += 1
                if object_id:
                    creative_object_id_count += 1
                if has_story_spec:
                    creative_post_spec_count += 1
                if len(creative_samples) < 5:
                    creative_samples.append(
                        {
                            "creative_id": _safe_str(row.get("id")),
                            "object_story_id": story_id,
                            "effective_object_story_id": effective_story_id,
                            "object_id": object_id,
                            "object_story_spec_keys": (
                                sorted(list(story_spec.keys()))[:8] if isinstance(story_spec, dict) else []
                            ),
                        }
                    )

            insight_samples: List[Dict[str, Any]] = []
            for row in insights_probe_rows[:5]:
                insight_samples.append(
                    {
                        "ad_id": _safe_str(row.get("ad_id")),
                        "campaign_id": _safe_str(row.get("campaign_id")),
                        "date_start": _safe_str(row.get("date_start")),
                        "date_stop": _safe_str(row.get("date_stop")),
                        "spend": _safe_float(row.get("spend")),
                        "impressions": _safe_int(row.get("impressions")),
                        "clicks": _safe_int(row.get("clicks")),
                    }
                )

            synthetic_rows = _synthetic_boosted_rows_from_maximum_insights(
                insight_rows=insights_probe_rows,
                since=period_since,
                until=period_until,
            )

            print(
                "[ads_sync][probe][discovery_zero] "
                f"client_id={cid} connection_id={resolved_connection_id} ad_account_id={ad_account_id} "
                f"since={period_since} until={period_until} "
                f"adcreatives_rows={len(creatives_probe_rows)} "
                f"adcreatives_object_story_id={creative_story_count} "
                f"adcreatives_effective_object_story_id={creative_effective_story_count} "
                f"adcreatives_object_id={creative_object_id_count} "
                f"adcreatives_object_story_spec={creative_post_spec_count} "
                f"insights_maximum_rows={len(insights_probe_rows)} "
                f"synthetic_rows={len(synthetic_rows)} "
                f"creative_samples={json.dumps(creative_samples, ensure_ascii=False)[:900]} "
                f"insight_samples={json.dumps(insight_samples, ensure_ascii=False)[:900]}"
            )
            if synthetic_rows:
                boosted_rows_raw = synthetic_rows
                boosted_sources_count = _count_boosted_sources(boosted_rows_raw)
                boosted_rows_for_classic = _boosted_rows_not_in_classic(
                    boosted_rows=boosted_rows_raw,
                    classic_ad_rows=ad_rows_raw,
                )
                print(
                    "[ads_sync][probe][fallback_applied] "
                    f"client_id={cid} connection_id={resolved_connection_id} ad_account_id={ad_account_id} "
                    f"since={period_since} until={period_until} "
                    f"source=insights_maximum_synthetic rows_boosted={len(boosted_rows_raw)} "
                    f"rows_boosted_for_classic={len(boosted_rows_for_classic)}"
                )
        campaign_rows_with_boosted = list(campaign_rows_raw)
        campaign_rows_with_boosted.extend(
            [row for row in boosted_rows_for_classic if _safe_str(row.get("campaign_id"))]
        )
        ad_rows_with_boosted = list(ad_rows_raw)
        ad_rows_with_boosted.extend(boosted_rows_for_classic)

        account_rows = _to_upsert_ready_ad_account_rows(
            client_id=cid,
            connection_id=resolved_connection_id,
            meta_connection_id=resolved_connection_id,
            ad_account_id=ad_account_id,
            ad_account_name=ad_account_name,
            since=period_since,
            raw_rows=account_rows_raw,
        )
        campaign_rows = _to_upsert_ready_campaign_rows(
            client_id=cid,
            connection_id=resolved_connection_id,
            ad_account_id=ad_account_id,
            ad_account_name=ad_account_name,
            since=period_since,
            raw_rows=campaign_rows_with_boosted,
        )
        ad_rows = _to_upsert_ready_ad_rows(
            client_id=cid,
            connection_id=resolved_connection_id,
            ad_account_id=ad_account_id,
            ad_account_name=ad_account_name,
            since=period_since,
            raw_rows=ad_rows_with_boosted,
        )
        promoted_post_rows = _to_upsert_ready_promoted_post_rows(
            client_id=cid,
            connection_id=resolved_connection_id,
            ad_account_id=ad_account_id,
            ad_account_name=ad_account_name,
            since=period_since,
            raw_rows=boosted_rows_raw,
        )

        account_upsert = await _upsert_ad_account_daily_stats(account_rows)
        campaign_upsert = await _upsert_campaign_daily_stats(campaign_rows)
        ad_upsert = await _upsert_ad_daily_stats(ad_rows)
        promoted_upsert = await _upsert_promoted_post_daily_stats(promoted_post_rows)
        persisted_readback = await _readback_persisted_rows(
            client_id=cid,
            connection_id=resolved_connection_id,
            ad_account_id=ad_account_id,
            since=period_since,
            until=period_until,
        )
        await mark_connection_sync_success(resolved_connection_id)
    except Exception as exc:
        message = str(exc)
        requires_reauth = isinstance(exc, MetaApiError) and exc.invalid_oauth
        if not requires_reauth:
            lowered = message.lower()
            requires_reauth = "reconecte" in lowered or "reconex" in lowered or "token meta" in lowered
        await mark_connection_sync_error(
            resolved_connection_id,
            message,
            requires_reauth=requires_reauth,
        )
        if job_run:
            await finish_job_run(
                job_run["id"],
                status="error",
                rows_upserted=0,
                error=message,
                client_id=cid,
                connection_id=resolved_connection_id,
                ad_account_id=ad_account_id,
                payload_json={
                    "date_range": {"since": period_since, "until": period_until},
                    "connection_source": resolved_connection_source,
                    "requires_reauth": requires_reauth,
                },
            )
        print(
            "[ads_sync][meta_error] "
            f"client_id={cid} ad_account_id={ad_account_id} since={period_since} until={period_until} "
            f"error={_safe_str(message)[:360]}"
        )
        raise

    print(
        "[ads_sync][done] "
        f"client_id={cid} ad_account_id={ad_account_id} since={period_since} until={period_until} "
        f"rows_account={len(account_rows_raw)} rows_campaign={len(campaign_rows_raw)} rows_ad={len(ad_rows_raw)} "
        f"rows_boosted={len(boosted_rows_raw)} "
        f"rows_boosted_for_classic={len(boosted_rows_for_classic)} "
        f"saved_account={int(account_upsert.get('upserted') or 0)} "
        f"saved_campaign={int(campaign_upsert.get('upserted') or 0)} "
        f"saved_ad={int(ad_upsert.get('upserted') or 0)} "
        f"saved_promoted={int(promoted_upsert.get('upserted') or 0)} "
        f"persisted_account={int((persisted_readback.get('ad_account_daily_stats') or {}).get('count') or 0)} "
        f"persisted_campaign={int((persisted_readback.get('campaign_daily_stats') or {}).get('count') or 0)} "
        f"persisted_ad={int((persisted_readback.get('ad_daily_stats') or {}).get('count') or 0)} "
        f"persisted_promoted={int((persisted_readback.get('promoted_post_daily_stats') or {}).get('count') or 0)}"
    )
    result = {
        "ok": True,
        "client_id": cid,
        "connection_id": resolved_connection_id,
        "connection_source": resolved_connection_source,
        "meta_connection_id": resolved_connection_id,
        "ad_account_id": ad_account_id,
        "date_range": {"since": period_since, "until": period_until},
        "rows_returned": {
            "ad_account": len(account_rows_raw),
            "campaign": len(campaign_rows_raw),
            "ad": len(ad_rows_raw),
            "boosted_posts": len(boosted_rows_raw),
            "boosted_fallback_in_classic": len(boosted_rows_for_classic),
        },
        "rows_inserted": (
            int(account_upsert.get("upserted") or 0)
            + int(campaign_upsert.get("upserted") or 0)
            + int(ad_upsert.get("upserted") or 0)
            + int(promoted_upsert.get("upserted") or 0)
        ),
        "upsert": {
            "ad_account_daily_stats": account_upsert,
            "campaign_daily_stats": campaign_upsert,
            "ad_daily_stats": ad_upsert,
            "promoted_post_daily_stats": promoted_upsert,
        },
        "saved": {
            "ad_account_daily_stats": int(account_upsert.get("upserted") or 0),
            "campaign_daily_stats": int(campaign_upsert.get("upserted") or 0),
            "ad_daily_stats": int(ad_upsert.get("upserted") or 0),
            "promoted_post_daily_stats": int(promoted_upsert.get("upserted") or 0),
        },
        "persisted_rows": {
            "ad_account_daily_stats": int(
                (persisted_readback.get("ad_account_daily_stats") or {}).get("count") or 0
            ),
            "campaign_daily_stats": int(
                (persisted_readback.get("campaign_daily_stats") or {}).get("count") or 0
            ),
            "ad_daily_stats": int((persisted_readback.get("ad_daily_stats") or {}).get("count") or 0),
            "promoted_post_daily_stats": int(
                (persisted_readback.get("promoted_post_daily_stats") or {}).get("count") or 0
            ),
        },
        "persisted_modes": {
            "ad_account_daily_stats": str(
                (persisted_readback.get("ad_account_daily_stats") or {}).get("mode") or "unknown"
            ),
            "campaign_daily_stats": str(
                (persisted_readback.get("campaign_daily_stats") or {}).get("mode") or "unknown"
            ),
            "ad_daily_stats": str((persisted_readback.get("ad_daily_stats") or {}).get("mode") or "unknown"),
            "promoted_post_daily_stats": str(
                (persisted_readback.get("promoted_post_daily_stats") or {}).get("mode") or "unknown"
            ),
        },
        "sources": {
            "classic_ads": len(ad_rows_raw),
            "boosted_posts": len(boosted_rows_raw),
            "boosted_fallback_in_classic": len(boosted_rows_for_classic),
            "boosted_source_breakdown": boosted_sources_count,
        },
    }
    if job_run:
        job_status = "partial" if any((item or {}).get("skipped") for item in (account_upsert, campaign_upsert, ad_upsert, promoted_upsert)) else "success"
        await finish_job_run(
            job_run["id"],
            status=job_status,
            rows_upserted=_sum_rows_upserted(result),
            client_id=cid,
            connection_id=resolved_connection_id,
            ad_account_id=ad_account_id,
            payload_json={
                "date_range": {"since": period_since, "until": period_until},
                "connection_source": resolved_connection_source,
                "rows_returned": result.get("rows_returned"),
                "saved": result.get("saved"),
                "persisted_rows": result.get("persisted_rows"),
                "persisted_modes": result.get("persisted_modes"),
                "sources": result.get("sources"),
            },
        )
        result["job_run_id"] = job_run["id"]
        result["job_status"] = job_status
    return result


async def sync_ads_connection(
    connection_id: str,
    days: int = 30,
    *,
    job_name: str = "meta_ads_sync",
    trigger_source: str = "system",
    record_job_run: bool = True,
) -> Dict[str, Any]:
    conn = await _load_connection(connection_id)
    if not conn:
        raise RuntimeError("Conexão Meta Ads não encontrada.")

    platform = _safe_str(conn.get("platform"))
    connection_type = _safe_str(conn.get("connection_type"))
    if platform != "meta_ads" or connection_type != "paid":
        raise RuntimeError("Conexão não é do tipo Meta Ads/Paid.")

    client_id = _safe_str(conn.get("client_id"))
    ad_account_id = _normalize_ad_account_id(_safe_str(conn.get("ad_account_id")))
    ad_account_name = _safe_str(conn.get("ad_account_name"))
    if not client_id or not ad_account_id:
        raise RuntimeError("Conexão Meta Ads inválida (client_id/ad_account_id ausente).")

    since, until = _date_window(days)
    _ = ad_account_name  # mantém compatibilidade sem alterar payload antigo
    return await sync_ads_for_client_period(
        client_id=client_id,
        since=since,
        until=until,
        connection_id=connection_id,
        job_name=job_name,
        trigger_source=trigger_source,
        record_job_run=record_job_run,
    )


async def sync_ads_for_client(client_id: str, days: int = 30) -> Dict[str, Any]:
    rows = await sb_select(
        "meta_connections",
        filters={
            "client_id": f"eq.{_safe_str(client_id)}",
            "platform": "eq.meta_ads",
            "connection_type": "eq.paid",
            "status": "eq.active",
        },
        order="updated_at.desc",
        limit=200,
    )
    if not rows:
        return {"ok": True, "client_id": client_id, "results": [], "message": "Sem conexões Meta Ads ativas."}

    results: List[Dict[str, Any]] = []
    for row in rows:
        connection_id = _safe_str(row.get("id"))
        if not connection_id:
            continue
        try:
            res = await sync_ads_connection(connection_id, days=days)
            results.append({"connection_id": connection_id, "ok": True, "saved": res.get("saved")})
        except Exception as exc:
            results.append({"connection_id": connection_id, "ok": False, "error": str(exc)[:220]})

    return {
        "ok": True,
        "client_id": client_id,
        "results": results,
        "connections_total": len(rows),
        "connections_ok": len([r for r in results if r.get("ok")]),
    }
