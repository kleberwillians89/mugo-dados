from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx

from .ads_sync import sync_ads_for_client_period
from .dashboard_read_model import refresh_dashboard_read_model
from .ig_supabase import sb_insert, sb_insert_many, sb_query, sb_rpc, sb_select, sb_update

MAX_ATTEMPTS = 3
SLICE_DAYS = 7
ADDITIVE_FIELDS = ("spend", "conversions", "revenue", "clicks", "impressions")


def build_slices(since: str, until: str, days: int = SLICE_DAYS) -> List[Dict[str, str]]:
    start, end = date.fromisoformat(since), date.fromisoformat(until)
    if start > end:
        raise ValueError("since deve ser anterior ou igual a until.")
    slices: List[Dict[str, str]] = []
    cursor = start
    while cursor <= end:
        slice_end = min(end, cursor + timedelta(days=max(1, days) - 1))
        slices.append({"since": cursor.isoformat(), "until": slice_end.isoformat()})
        cursor = slice_end + timedelta(days=1)
    return slices


async def enqueue_backfill(*, client_id: str, connection_id: str, since: str, until: str, created_by: str) -> Dict[str, Any]:
    parts = build_slices(since, until)
    connections = await sb_select("meta_connections", select="id,client_id,platform,connection_type", filters={
        "id": f"eq.{connection_id}", "client_id": f"eq.{client_id}", "platform": "eq.meta_ads", "connection_type": "eq.paid"
    }, limit=1)
    if not connections:
        raise ValueError("Conexão Meta Ads paga não encontrada para esta empresa.")
    existing = await sb_select("meta_ads_backfill_jobs", filters={
        "connection_id": f"eq.{connection_id}", "status": "in.(queued,running,waiting)"
    }, order="created_at.desc", limit=1)
    if existing:
        return await get_backfill(str(existing[0]["id"]), client_id=client_id)
    job = await sb_insert("meta_ads_backfill_jobs", {
        "client_id": client_id, "connection_id": connection_id,
        "requested_since": since, "requested_until": until,
        "total_slices": len(parts), "created_by": created_by,
    }, returning="representation")
    if not job:
        raise RuntimeError("Não foi possível persistir o backfill.")
    await sb_insert_many("meta_ads_backfill_slices", [{
        "backfill_job_id": job["id"], "slice_index": index,
        "slice_since": item["since"], "slice_until": item["until"],
    } for index, item in enumerate(parts)], returning="minimal")
    return await get_backfill(str(job["id"]), client_id=client_id)


async def get_backfill(job_id: str, *, client_id: str | None = None) -> Dict[str, Any]:
    filters = {"id": f"eq.{job_id}"}
    if client_id:
        filters["client_id"] = f"eq.{client_id}"
    jobs = await sb_select("meta_ads_backfill_jobs", filters=filters, limit=1)
    if not jobs:
        raise LookupError("Backfill não encontrado.")
    slices = await sb_select("meta_ads_backfill_slices", filters={"backfill_job_id": f"eq.{job_id}"}, order="slice_index.asc")
    current = next((item for item in slices if item.get("status") in {"running", "waiting"}), None)
    return {"ok": True, "backfill_job_id": job_id, **jobs[0], "current_slice": current, "slices": slices}


def _totals(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    return {key: round(sum(float(row.get(key) or 0) for row in rows), 6) for key in ADDITIVE_FIELDS}


async def reconcile_slice(*, client_id: str, connection_id: str, since: str, until: str) -> Dict[str, Any]:
    async def read(table: str) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        while True:
            page = await sb_query(table,
                f"client_id=eq.{client_id}&connection_id=eq.{connection_id}&stat_date=gte.{since}&stat_date=lte.{until}"
                f"&limit=1000&offset={len(rows)}")
            rows.extend(page)
            if len(page) < 1000:
                return rows
    account, campaign, ads = await read("ad_account_daily_stats"), await read("campaign_daily_stats"), await read("ad_daily_stats")
    totals = {"account": _totals(account), "campaign": _totals(campaign), "ad": _totals(ads)}
    mismatches = [key for key in ADDITIVE_FIELDS if any(abs(totals["account"][key] - totals[level][key]) > 0.01 for level in ("campaign", "ad"))]
    dates = sorted({str(row.get("stat_date")) for row in account if row.get("stat_date")})
    return {"valid": bool(account) and not mismatches, "needs_review": bool(account) and bool(mismatches),
            "mismatches": mismatches, "totals": totals,
            "rows": {"account": len(account), "campaign": len(campaign), "ad": len(ads)},
            "first_date": dates[0] if dates else None, "last_date": dates[-1] if dates else None}


def _retryable(exc: Exception) -> bool:
    if bool(getattr(exc, "retryable", False)) or getattr(exc, "status_code", None) in {409, 429, 502, 503, 504}:
        return True
    return isinstance(exc, (TimeoutError, httpx.TimeoutException, httpx.NetworkError)) or any(
        token in str(exc).lower() for token in ("timeout", "timed out", "rate limit", "temporarily", "502", "503", "504", "already running")
    )


async def _update_job(job_id: str) -> None:
    slices = await sb_select("meta_ads_backfill_slices", filters={"backfill_job_id": f"eq.{job_id}"})
    done = [item for item in slices if item.get("status") in {"success", "skipped"}]
    rows = sum(int(item.get("rows_upserted") or 0) for item in done)
    dates = [str(item.get("reconciliation_json", {}).get(key)) for item in done for key in ("first_date", "last_date") if item.get("reconciliation_json", {}).get(key)]
    terminal_review = next((item for item in slices if item.get("status") == "needs_review"), None)
    terminal_error = next((item for item in slices if item.get("status") == "error"), None)
    pending = [item for item in slices if item.get("status") not in {"success", "skipped", "needs_review", "error"}]
    status = "needs_review" if terminal_review else "error" if terminal_error else "success" if not pending else "waiting" if any(item.get("status") == "waiting" for item in pending) else "running"
    level_rows = {level: sum(int((item.get("reconciliation_json") or {}).get("rows", {}).get(level) or 0) for item in done)
                  for level in ("account", "campaign", "ad")}
    patch: Dict[str, Any] = {"status": status, "completed_slices": len(done),
        "skipped_slices": len([item for item in done if item.get("status") == "skipped"]), "rows_upserted": rows,
        "actual_first_date": min(dates) if dates else None, "actual_last_date": max(dates) if dates else None,
        "summary_json": {"slices_success": len([item for item in done if item.get("status") == "success"]),
                         "slices_skipped": len([item for item in done if item.get("status") == "skipped"]),
                         "slices_failed": len([item for item in slices if item.get("status") in {"error", "needs_review"}]),
                         "rows": level_rows},
        "updated_at": datetime.now(timezone.utc).isoformat()}
    terminal = terminal_review or terminal_error
    if terminal:
        patch.update({"failed_slice": terminal.get("slice_since"), "error": terminal.get("error"), "finished_at": datetime.now(timezone.utc).isoformat()})
    elif status == "success":
        patch["finished_at"] = datetime.now(timezone.utc).isoformat()
    await sb_update("meta_ads_backfill_jobs", filters={"id": f"eq.{job_id}"}, patch=patch, returning="minimal")


async def process_next_slice() -> Dict[str, Any]:
    claimed = await sb_rpc("claim_meta_ads_backfill_slice", {"p_stale_minutes": 75})
    if not claimed:
        return {"ok": True, "processed": False, "reason": "queue_empty"}
    item = claimed[0] if isinstance(claimed, list) else claimed
    job = (await sb_select("meta_ads_backfill_jobs", filters={"id": f"eq.{item['backfill_job_id']}"}, limit=1))[0]
    slice_id, since, until = str(item["id"]), str(item["slice_since"]), str(item["slice_until"])
    if int(item.get("attempts") or 1) > 1:
        existing = await reconcile_slice(client_id=str(job["client_id"]), connection_id=str(job["connection_id"]), since=since, until=until)
        if existing["valid"]:
            try:
                await refresh_dashboard_read_model(client_id=str(job["client_id"]), start=since, end=until, provider="meta")
                await sb_update("meta_ads_backfill_slices", filters={"id": f"eq.{slice_id}"}, patch={
                    "status": "success", "reconciliation_json": existing, "error": None,
                    "updated_at": datetime.now(timezone.utc).isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(),
                }, returning="minimal")
                await _update_job(str(item["backfill_job_id"]))
                return {"ok": True, "processed": True, "recovered_from_persistence": True,
                        "backfill_job_id": item["backfill_job_id"], "slice": {"since": since, "until": until}}
            except Exception as projection_exc:
                terminal = int(item.get("attempts") or 1) >= MAX_ATTEMPTS
                await sb_update("meta_ads_backfill_slices", filters={"id": f"eq.{slice_id}"}, patch={
                    "status": "error" if terminal else "waiting", "reconciliation_json": existing,
                    "error": f"Read model: {str(projection_exc)[:900]}",
                    "next_attempt_at": (datetime.now(timezone.utc) + timedelta(minutes=2 ** int(item.get("attempts") or 1))).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "finished_at": datetime.now(timezone.utc).isoformat() if terminal else None,
                }, returning="minimal")
                await _update_job(str(item["backfill_job_id"]))
                return {"ok": False, "processed": True, "projection_pending": not terminal,
                        "backfill_job_id": item["backfill_job_id"], "slice": {"since": since, "until": until}}
    try:
        result = await sync_ads_for_client_period(client_id=str(job["client_id"]), connection_id=str(job["connection_id"]),
            since=since, until=until, job_name="meta_ads_backfill_slice", trigger_source="backfill_worker",
            record_job_run=True, refresh_read_model=False)
        reconciliation = await reconcile_slice(client_id=str(job["client_id"]), connection_id=str(job["connection_id"]), since=since, until=until)
        duplicate = result.get("reason") == "duplicate"
        no_data = result.get("sync_outcome") == "no_data"
        if reconciliation["needs_review"]:
            status, error = "needs_review", f"Divergência aditiva: {','.join(reconciliation['mismatches'])}"
        elif reconciliation["valid"]:
            await refresh_dashboard_read_model(client_id=str(job["client_id"]), start=since, end=until, provider="meta")
            status, error = ("skipped" if duplicate else "success"), None
        elif no_data or duplicate:
            status, error = "skipped", None
        else:
            raise RuntimeError("Slice sem account canônico persistido.")
        await sb_update("meta_ads_backfill_slices", filters={"id": f"eq.{slice_id}"}, patch={"status": status,
            "rows_upserted": int(result.get("rows_inserted") or 0), "reconciliation_json": reconciliation,
            "error": error, "updated_at": datetime.now(timezone.utc).isoformat(), "finished_at": datetime.now(timezone.utc).isoformat()}, returning="minimal")
    except Exception as exc:
        # A resposta pode falhar depois da persistência. Readback vem antes de qualquer retry.
        reconciliation = await reconcile_slice(client_id=str(job["client_id"]), connection_id=str(job["connection_id"]), since=since, until=until)
        if reconciliation["valid"]:
            try:
                await refresh_dashboard_read_model(client_id=str(job["client_id"]), start=since, end=until, provider="meta")
                patch = {"status": "success", "reconciliation_json": reconciliation, "error": None,
                         "updated_at": datetime.now(timezone.utc).isoformat(), "finished_at": datetime.now(timezone.utc).isoformat()}
            except Exception as projection_exc:
                if int(item.get("attempts") or 1) < MAX_ATTEMPTS:
                    patch = {"status": "waiting", "error": f"Read model: {str(projection_exc)[:900]}",
                             "next_attempt_at": (datetime.now(timezone.utc) + timedelta(minutes=2 ** int(item.get("attempts") or 1))).isoformat(),
                             "updated_at": datetime.now(timezone.utc).isoformat()}
                else:
                    patch = {"status": "error", "error": f"Read model: {str(projection_exc)[:900]}",
                             "reconciliation_json": reconciliation, "updated_at": datetime.now(timezone.utc).isoformat(),
                             "finished_at": datetime.now(timezone.utc).isoformat()}
        elif reconciliation.get("needs_review"):
            patch = {"status": "needs_review", "error": f"Divergência aditiva: {','.join(reconciliation.get('mismatches') or [])}",
                     "reconciliation_json": reconciliation, "updated_at": datetime.now(timezone.utc).isoformat(),
                     "finished_at": datetime.now(timezone.utc).isoformat()}
        elif _retryable(exc) and int(item.get("attempts") or 1) < MAX_ATTEMPTS:
            delay = 2 ** int(item.get("attempts") or 1)
            patch = {"status": "waiting", "error": str(exc)[:1000],
                     "next_attempt_at": (datetime.now(timezone.utc) + timedelta(minutes=delay)).isoformat(),
                     "updated_at": datetime.now(timezone.utc).isoformat()}
        else:
            patch = {"status": "error", "error": str(exc)[:1000], "reconciliation_json": reconciliation,
                     "updated_at": datetime.now(timezone.utc).isoformat(), "finished_at": datetime.now(timezone.utc).isoformat()}
        await sb_update("meta_ads_backfill_slices", filters={"id": f"eq.{slice_id}"}, patch=patch, returning="minimal")
    await _update_job(str(item["backfill_job_id"]))
    return {"ok": True, "processed": True, "backfill_job_id": item["backfill_job_id"], "slice": {"since": since, "until": until}}
