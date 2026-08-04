from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from .ig_supabase import sb_select
from .meta_connection_adapter import meta_connection_adapter


def _text(value: Any) -> str:
    return str(value or "").strip()


def _token_status(row: Dict[str, Any]) -> str:
    if not any(_text(row.get(field)) for field in ("encrypted_token", "encrypted_access_token", "encrypted_refresh_token")):
        return "unavailable"
    expires = _text(row.get("token_expires_at"))
    if not expires:
        return "available"
    try:
        parsed = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        return "expired" if parsed <= datetime.now(timezone.utc) else "valid"
    except ValueError:
        return "unknown"


def _safe_connection_health(row: Dict[str, Any]) -> Dict[str, Any]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    provider = _text(row.get("provider"))
    required_asset = {
        "ga4": metadata.get("ga4_property_id"),
        "google_ads": metadata.get("google_ads_customer_id"),
        "shopify": metadata.get("shop_domain") or row.get("external_key"),
        "meta": metadata.get("selected_instagram_id") or metadata.get("selected_ad_account_id"),
    }.get(provider)
    last_error = _text(row.get("last_error"))
    return {
        "client_id": _text(row.get("client_id")), "provider": provider,
        "connection_id": _text(row.get("id")), "status": _text(row.get("status")),
        "capability": metadata.get("integration_product") or provider,
        "last_sync_at": row.get("last_sync_at"), "last_success_at": row.get("last_sync_at"),
        "last_error_code": metadata.get("last_error_code"),
        "last_error_message": last_error[:240] or None,
        "request_id": metadata.get("last_request_id"),
        "stale": False, "token_status": _token_status(row),
        "asset_status": "selected" if required_asset else "required",
        "retryable": bool(metadata.get("last_error_retryable")),
        "drift_detected": False, "sync_running": False,
    }


def _is_stale(value: Any, *, hours: int = 48) -> bool:
    raw = _text(value)
    if not raw:
        return True
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - parsed).total_seconds() > hours * 3600
    except ValueError:
        return True


async def client_provider_health(client_id: str, provider: str | None = None) -> Dict[str, Any]:
    filters = {"client_id": f"eq.{_text(client_id)}"}
    if _text(provider):
        filters["provider"] = f"eq.{_text(provider).lower()}"
    rows = await sb_select(
        "integration_connections", filters=filters,
        order="updated_at.desc", limit=500,
    )
    items = [_safe_connection_health(row) for row in rows]
    running = await sb_select(
        "cron_job_runs", select="id,job_name,connection_id,started_at,status,payload_json",
        filters={"client_id": f"eq.{_text(client_id)}", "status": "eq.running"},
        order="started_at.desc", limit=200,
    )
    last_runs = await sb_select(
        "cron_job_runs", select="id,job_name,connection_id,started_at,finished_at,status,error,payload_json",
        filters={"client_id": f"eq.{_text(client_id)}"},
        order="started_at.desc", limit=200,
    )
    for item in items:
        connection_runs = [run for run in last_runs if _text(run.get("connection_id")) == item["connection_id"]]
        item["sync_running"] = any(_text(run.get("connection_id")) == item["connection_id"] for run in running)
        if connection_runs:
            latest = connection_runs[0]
            latest_payload = latest.get("payload_json") if isinstance(latest.get("payload_json"), dict) else {}
            item["last_sync_at"] = latest.get("finished_at") or latest.get("started_at") or item["last_sync_at"]
            successes = [run for run in connection_runs if _text(run.get("status")) == "success"]
            if successes:
                item["last_success_at"] = successes[0].get("finished_at") or successes[0].get("started_at")
            if _text(latest.get("status")) == "error":
                item["last_error_code"] = latest_payload.get("error_code") or item["last_error_code"]
                item["last_error_message"] = _text(latest.get("error"))[:240] or item["last_error_message"]
            item["request_id"] = latest_payload.get("request_id") or item["request_id"]
            item["retryable"] = bool(latest_payload.get("retryable")) if "retryable" in latest_payload else item["retryable"]
        item["stale"] = _is_stale(item["last_success_at"] or item["last_sync_at"])
    if not provider or _text(provider).lower() == "meta":
        meta_health = await meta_connection_adapter.health(client_id)
        for item in items:
            if item["provider"] == "meta":
                item["drift_detected"] = meta_health["drift_detected"]
                if meta_health["drift_detected"]:
                    item["last_error_code"] = "META_CONNECTION_DRIFT"
        if provider and not items:
            items.append({
                "client_id": _text(client_id), "provider": "meta", "connection_id": None,
                "status": meta_health["status"], "capability": "meta", "last_sync_at": None,
                "last_success_at": None, "last_error_code": meta_health.get("code"),
                "last_error_message": None, "request_id": None, "stale": False,
                "token_status": "unavailable", "asset_status": "required", "retryable": False,
                "drift_detected": meta_health["drift_detected"], "sync_running": False,
            })
    return {"ok": True, "client_id": _text(client_id), "provider": _text(provider) or None, "connections": items}
