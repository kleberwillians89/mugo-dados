from __future__ import annotations

from typing import Any, Dict, Iterable


ADDITIVE_METRICS = ("spend", "clicks", "impressions", "conversions", "revenue")


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _totals(rows: Iterable[Dict[str, Any]]) -> Dict[str, float] | None:
    materialized = list(rows)
    if not materialized:
        return None
    return {metric: sum(_number(row.get(metric)) for row in materialized) for metric in ADDITIVE_METRICS}


def reconcile_ads_levels(
    account_rows: Iterable[Dict[str, Any]],
    campaign_rows: Iterable[Dict[str, Any]],
    ad_rows: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """Read-only diagnostic. Account remains canonical; detail never fills missing totals."""
    account = _totals(account_rows)
    campaign = _totals(campaign_rows)
    ad = _totals(ad_rows)

    def delta(detail: Dict[str, float] | None) -> Dict[str, float] | None:
        if account is None or detail is None:
            return None
        return {metric: detail[metric] - account[metric] for metric in ADDITIVE_METRICS}

    return {
        "canonical_level": "account" if account is not None else None,
        "account": account,
        "campaign": campaign,
        "ad": ad,
        "delta_campaign": delta(campaign),
        "delta_ad": delta(ad),
        "compared_metrics": list(ADDITIVE_METRICS),
        "excluded_non_additive_metrics": ["reach"],
    }
