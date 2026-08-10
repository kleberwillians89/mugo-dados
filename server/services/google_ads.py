from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List

import httpx

from .connection_resolver import resolve_generic_connection
from .google_oauth import get_google_access_token
from .ig_supabase import sb_select, sb_upsert
from .integration_errors import IntegrationError
from .periods import resolve_period
from .sync_locks import guarded_sync
from .dashboard_read_model import refresh_dashboard_read_model_safely


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
    customer_id = re.sub(r"\D", "", str(metadata.get("google_ads_customer_id") or ""))
    if not customer_id:
        raise IntegrationError(
            "Selecione uma conta Google Ads.", status_code=409,
            code="GOOGLE_ADS_ACCOUNT_SELECTION_REQUIRED", provider="google_ads",
        )
    return GoogleAdsContext(
        client_id=client_id,
        connection_id=str(row.get("id") or ""),
        customer_id=customer_id,
        login_customer_id=re.sub(r"\D", "", str(metadata.get("google_ads_login_customer_id") or "")) or None,
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
        f"WHERE segments.date BETWEEN '{period.start.isoformat()}' AND '{period.end.isoformat()}' "
        "AND campaign.status != 'REMOVED'"
    )
    token = await get_google_access_token(client_id, context.connection_id)
    headers = {"Authorization": f"Bearer {token}", "developer-token": developer_token}
    if context.login_customer_id:
        headers["login-customer-id"] = context.login_customer_id
    url = f"https://googleads.googleapis.com/{version}/customers/{context.customer_id}/googleAds:searchStream"
    async with httpx.AsyncClient(timeout=60) as http:
        response = await http.post(url, headers=headers, json={"query": query})
    if response.status_code >= 400:
        raise IntegrationError(
            "Google Ads recusou a consulta diária.", status_code=502,
            code="GOOGLE_ADS_QUERY_FAILED", provider="google_ads",
            diagnostics={"upstream_status": response.status_code, "request_id": response.headers.get("request-id")},
        )
    payload = response.json()
    batches = payload if isinstance(payload, list) else [payload]
    rows: List[Dict[str, Any]] = []
    for batch in batches:
        for item in (batch.get("results") or []) if isinstance(batch, dict) else []:
            parsed = _parse_result(client_id, context, item)
            if parsed:
                rows.append(parsed)
    if rows:
        await sb_upsert(
            "google_ads_daily_stats", rows,
            on_conflict="client_id,connection_id,customer_id,campaign_id,stat_date",
        )
        await refresh_dashboard_read_model_safely(
            client_id=client_id,
            start=period.start.isoformat(),
            end=period.end.isoformat(),
            provider="google_ads",
        )
    return {
        "ok": True, "client_id": client_id, "connection_id": context.connection_id,
        "customer_id": context.customer_id,
        "period": {"start": period.start.isoformat(), "end": period.end.isoformat(), "days": period.days},
        "rows_received": len(rows), "rows_upserted": len(rows),
    }


async def sync_google_ads(
    *, client_id: str, connection_id: str | None, start: str | None, end: str | None, days: int,
) -> Dict[str, Any]:
    async with guarded_sync(
        client_id=client_id, provider="google_ads", connection_id=str(connection_id or "resolved"),
        ttl_seconds=1800,
    ):
        return await _sync_google_ads(
            client_id=client_id, connection_id=connection_id, start=start, end=end, days=days,
        )


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
