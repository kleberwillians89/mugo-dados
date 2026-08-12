from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List


SUMMABLE_METRICS = (
    "reach", "views", "likes", "comments", "shares", "saved",
    "total_interactions", "profile_visits",
)


def _insights(row: Dict[str, Any]) -> Dict[str, Any]:
    value = row.get("insights_json")
    return value if isinstance(value, dict) else {}


def _available(insights: Dict[str, Any]) -> set[str]:
    value = insights.get("available_metrics")
    return {str(item) for item in value} if isinstance(value, list) else set()


def is_story(row: Dict[str, Any]) -> bool:
    return str(row.get("media_product_type") or row.get("media_type") or "").upper() == "STORY"


def aggregate_instagram_content(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    permanent: List[Dict[str, Any]] = []
    stories: List[Dict[str, Any]] = []
    for row in rows:
        (stories if is_story(row) else permanent).append(row)

    metric_totals = {metric: 0.0 for metric in SUMMABLE_METRICS}
    metric_counts = {metric: 0 for metric in SUMMABLE_METRICS}
    content_with_insights = 0
    for row in permanent:
        insights = _insights(row)
        available = _available(insights)
        if available:
            content_with_insights += 1
        for metric in SUMMABLE_METRICS:
            if metric not in available:
                continue
            value = insights.get(metric)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                metric_totals[metric] += float(value)
                metric_counts[metric] += 1

    story_with_insights = sum(1 for row in stories if _available(_insights(row)))
    dates = sorted(str(row.get("timestamp") or "")[:10] for row in permanent if row.get("timestamp"))
    story_dates = sorted(str(row.get("timestamp") or "")[:10] for row in stories if row.get("timestamp"))
    return {
        "eligible_content_count": len(permanent),
        "content_with_insights_count": content_with_insights,
        "reels_count": sum(str(row.get("media_product_type") or "").upper() == "REELS" for row in permanent),
        "feed_count": sum(str(row.get("media_product_type") or "").upper() != "REELS" for row in permanent),
        "metrics": {
            metric: {
                "value": metric_totals[metric] if metric_counts[metric] else None,
                "available_count": metric_counts[metric],
                "eligible_count": len(permanent),
            }
            for metric in SUMMABLE_METRICS
        },
        "coverage_start": dates[0] if dates else None,
        "coverage_end": dates[-1] if dates else None,
        "stories": {
            "published_count": len(stories),
            "with_insights_count": story_with_insights,
            "coverage_start": story_dates[0] if story_dates else None,
            "coverage_end": story_dates[-1] if story_dates else None,
            "historical_insights_available": story_with_insights > 0,
        },
    }


def aggregate_instagram_months(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        timestamp = str(row.get("timestamp") or "")
        if len(timestamp) >= 7:
            grouped[timestamp[:7]].append(row)
    return [{"month": month, **aggregate_instagram_content(grouped[month])} for month in sorted(grouped)]
