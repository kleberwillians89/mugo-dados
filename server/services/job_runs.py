from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from .ig_supabase import _is_column_compat_error, sb_insert, sb_select, sb_update


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_payload(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def _normalize_status(value: Any) -> str:
    status = _safe_str(value).lower()
    if status in {"running", "success", "error", "partial", "skipped"}:
        return status
    return "running"


def _drop_optional_column(
    row: Dict[str, Any],
    exc: httpx.HTTPStatusError,
) -> tuple[Dict[str, Any], str]:
    for column_name in ("payload_json", "trigger_source"):
        if column_name in row and _is_column_compat_error(exc, column_name):
            next_row = dict(row)
            next_row.pop(column_name, None)
            return next_row, column_name
    return row, ""


async def _insert_with_compatibility(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    attempt = dict(row)
    while True:
        try:
            return await sb_insert("cron_job_runs", attempt, returning="representation")
        except httpx.HTTPStatusError as exc:
            next_attempt, removed_column = _drop_optional_column(attempt, exc)
            if not removed_column:
                raise
            print(
                "[job_runs][compat_insert] "
                f"removed_column={removed_column} reason=schema_mismatch"
            )
            attempt = next_attempt


async def _update_with_compatibility(
    job_run_id: str,
    patch: Dict[str, Any],
) -> list[Dict[str, Any]]:
    attempt = dict(patch)
    filters = {"id": f"eq.{_safe_str(job_run_id)}"}
    while True:
        try:
            return await sb_update(
                "cron_job_runs",
                filters=filters,
                patch=attempt,
                returning="representation",
            )
        except httpx.HTTPStatusError as exc:
            next_attempt, removed_column = _drop_optional_column(attempt, exc)
            if not removed_column:
                raise
            print(
                "[job_runs][compat_update] "
                f"job_run_id={_safe_str(job_run_id)} removed_column={removed_column} reason=schema_mismatch"
            )
            attempt = next_attempt


def _serialize_run(row: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(row or {})
    return {
        "id": _safe_str(payload.get("id")),
        "job_name": _safe_str(payload.get("job_name")),
        "client_id": _safe_str(payload.get("client_id")) or None,
        "connection_id": _safe_str(payload.get("connection_id")) or None,
        "ad_account_id": _safe_str(payload.get("ad_account_id")) or None,
        "trigger_source": _safe_str(payload.get("trigger_source")) or "cron",
        "started_at": payload.get("started_at"),
        "finished_at": payload.get("finished_at"),
        "status": _normalize_status(payload.get("status")),
        "rows_upserted": int(payload.get("rows_upserted") or 0),
        "error": _safe_str(payload.get("error")) or None,
        "payload_json": _normalize_payload(payload.get("payload_json")),
    }


async def start_job_run(
    *,
    job_name: str,
    client_id: Optional[str] = None,
    connection_id: Optional[str] = None,
    ad_account_id: Optional[str] = None,
    trigger_source: str = "cron",
    payload_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    row = await _insert_with_compatibility(
        {
            "job_name": _safe_str(job_name),
            "client_id": _safe_str(client_id) or None,
            "connection_id": _safe_str(connection_id) or None,
            "ad_account_id": _safe_str(ad_account_id) or None,
            "trigger_source": _safe_str(trigger_source) or "cron",
            "started_at": _utc_now_iso(),
            "status": "running",
            "rows_upserted": 0,
            "payload_json": _normalize_payload(payload_json),
        }
    )
    return _serialize_run(row or {})


async def finish_job_run(
    job_run_id: str,
    *,
    status: str,
    rows_upserted: int = 0,
    error: Optional[str] = None,
    payload_json: Optional[Dict[str, Any]] = None,
    client_id: Optional[str] = None,
    connection_id: Optional[str] = None,
    ad_account_id: Optional[str] = None,
) -> Dict[str, Any]:
    patch: Dict[str, Any] = {
        "finished_at": _utc_now_iso(),
        "status": _normalize_status(status),
        "rows_upserted": max(0, int(rows_upserted or 0)),
        "error": _safe_str(error)[:2000] or None,
        "payload_json": _normalize_payload(payload_json),
    }
    if _safe_str(client_id):
        patch["client_id"] = _safe_str(client_id)
    if _safe_str(connection_id):
        patch["connection_id"] = _safe_str(connection_id)
    if _safe_str(ad_account_id):
        patch["ad_account_id"] = _safe_str(ad_account_id)

    rows = await _update_with_compatibility(job_run_id, patch)
    return _serialize_run(rows[0] if rows else {"id": job_run_id})


async def get_job_run(job_run_id: str) -> Optional[Dict[str, Any]]:
    rows = await sb_select(
        "cron_job_runs",
        filters={"id": f"eq.{_safe_str(job_run_id)}"},
        limit=1,
    )
    return _serialize_run(rows[0]) if rows else None


async def list_job_runs(
    *,
    client_id: Optional[str] = None,
    connection_id: Optional[str] = None,
    job_name: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    filters: Dict[str, str] = {}
    if _safe_str(client_id):
        filters["client_id"] = f"eq.{_safe_str(client_id)}"
    if _safe_str(connection_id):
        filters["connection_id"] = f"eq.{_safe_str(connection_id)}"
    if _safe_str(job_name):
        filters["job_name"] = f"eq.{_safe_str(job_name)}"
    if _safe_str(status):
        filters["status"] = f"eq.{_normalize_status(status)}"

    rows = await sb_select(
        "cron_job_runs",
        filters=filters or None,
        order="started_at.desc",
        limit=max(1, min(int(limit or 50), 200)),
    )
    return {
        "ok": True,
        "runs": [_serialize_run(row) for row in rows],
        "total": len(rows),
    }
