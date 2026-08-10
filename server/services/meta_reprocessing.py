from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from .ads_sync import extract_canonical_purchase_metrics
from .dashboard_read_model import refresh_dashboard_read_model
from .ig_supabase import sb_select, sb_update


META_DAILY_TABLES = (
    "ad_account_daily_stats",
    "campaign_daily_stats",
    "ad_daily_stats",
)


def recalculate_purchase_columns(raw_json: Any, spend: Any) -> Dict[str, Any]:
    raw_rows = raw_json if isinstance(raw_json, list) else [raw_json]
    purchase_count = 0.0
    purchase_value = 0.0
    selected_types: List[str] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            continue
        metrics = extract_canonical_purchase_metrics(
            raw_row.get("actions"), raw_row.get("action_values")
        )
        purchase_count += float(metrics["purchase_count"])
        purchase_value += float(metrics["purchase_value"])
        selected = metrics["purchase_action_type_selected"]
        if selected and selected not in selected_types:
            selected_types.append(selected)
    numeric_spend = float(spend or 0)
    return {
        "conversions": purchase_count,
        "revenue": purchase_value,
        "roas": purchase_value / numeric_spend if numeric_spend > 0 else 0.0,
        "purchase_action_types_selected": selected_types,
    }


async def reprocess_meta_purchase_metrics(
    *, client_id: str, start: str, end: str, apply: bool = False
) -> Dict[str, Any]:
    if not client_id.strip():
        raise ValueError("client_id is required")
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    if start_date > end_date:
        raise ValueError("start must be on or before end")

    report: Dict[str, Any] = {
        "client_id": client_id,
        "start": start,
        "end": end,
        "mode": "apply" if apply else "dry-run",
        "tables": {},
    }
    for table in META_DAILY_TABLES:
        rows = await sb_select(
            table,
            select="id,stat_date,spend,conversions,revenue,roas,raw_json",
            filters={
                "client_id": f"eq.{client_id}",
                "and": f"(stat_date.gte.{start},stat_date.lte.{end})",
            },
            order="stat_date.asc",
            limit=10_000,
        )
        before_count = sum(float(row.get("conversions") or 0) for row in rows)
        before_value = sum(float(row.get("revenue") or 0) for row in rows)
        after_count = 0.0
        after_value = 0.0
        changed = 0
        selected_types: List[str] = []
        for row in rows:
            calculated = recalculate_purchase_columns(row.get("raw_json"), row.get("spend"))
            after_count += calculated["conversions"]
            after_value += calculated["revenue"]
            for selected in calculated["purchase_action_types_selected"]:
                if selected not in selected_types:
                    selected_types.append(selected)
            patch = {key: calculated[key] for key in ("conversions", "revenue", "roas")}
            differs = any(abs(float(row.get(key) or 0) - float(value)) > 0.000001 for key, value in patch.items())
            if differs:
                changed += 1
                if apply:
                    await sb_update(
                        table,
                        filters={"id": f"eq.{row['id']}"},
                        patch=patch,
                        returning="minimal",
                    )
        report["tables"][table] = {
            "rows": len(rows),
            "rows_changed": changed,
            "before": {"purchases": before_count, "revenue": before_value},
            "after": {"purchases": after_count, "revenue": after_value},
            "purchase_action_types_selected": selected_types,
        }

    if apply:
        report["read_model"] = await refresh_dashboard_read_model(
            client_id=client_id, start=start, end=end, provider="meta"
        )
    return report
