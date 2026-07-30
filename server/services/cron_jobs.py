from __future__ import annotations

from typing import Any, Dict, List

from .ads_sync import sync_ads_connection
from .ig_supabase import sb_get_active_meta_connections, sb_rpc
from .instagram_sync import sync_instagram_connection
from .job_runs import finish_job_run, start_job_run
from .meta_tokens import ensure_valid_meta_token


async def _acquire_lock(client_id: str, job_name: str, ttl_seconds: int) -> bool:
    lock = await sb_rpc(
        "acquire_client_job_lock",
        {
            "p_client_id": client_id,
            "p_job_name": job_name,
            "p_ttl_seconds": ttl_seconds,
        },
    )
    return bool(lock)


async def _release_lock(client_id: str, job_name: str) -> None:
    await sb_rpc(
        "release_client_job_lock",
        {
            "p_client_id": client_id,
            "p_job_name": job_name,
        },
    )


async def run_token_refresh_job() -> Dict[str, Any]:
    conns = await sb_get_active_meta_connections()
    results: List[Dict[str, Any]] = []

    for c in conns:
        connection_id = str(c.get("id") or "").strip()
        client_id = str(c.get("client_id") or "").strip()
        if not connection_id or not client_id:
            continue

        job_name = f"token_refresh:{connection_id}"
        if not await _acquire_lock(client_id, job_name, ttl_seconds=900):
            results.append(
                {
                    "connection_id": connection_id,
                    "client_id": client_id,
                    "ok": False,
                    "skipped": True,
                    "reason": "locked",
                }
            )
            continue

        run = await start_job_run(
            job_name="meta_token_refresh",
            client_id=client_id,
            connection_id=connection_id,
            ad_account_id=str(c.get("ad_account_id") or "").strip() or None,
            trigger_source="cron",
            payload_json={"platform": c.get("platform"), "connection_type": c.get("connection_type")},
        )
        try:
            await ensure_valid_meta_token(
                client_id,
                connection_id=connection_id,
                platform=str(c.get("platform") or ""),
                connection_type=str(c.get("connection_type") or ""),
            )
            await finish_job_run(
                run["id"],
                status="success",
                client_id=client_id,
                connection_id=connection_id,
                ad_account_id=str(c.get("ad_account_id") or "").strip() or None,
                payload_json={"platform": c.get("platform"), "connection_type": c.get("connection_type")},
            )
            results.append({"connection_id": connection_id, "client_id": client_id, "ok": True, "job_run_id": run["id"]})
        except Exception as exc:
            await finish_job_run(
                run["id"],
                status="error",
                error=str(exc),
                client_id=client_id,
                connection_id=connection_id,
                ad_account_id=str(c.get("ad_account_id") or "").strip() or None,
                payload_json={"platform": c.get("platform"), "connection_type": c.get("connection_type")},
            )
            results.append({"connection_id": connection_id, "client_id": client_id, "ok": False, "error": str(exc)[:240], "job_run_id": run["id"]})
        finally:
            await _release_lock(client_id, job_name)

    ok_count = len([r for r in results if r.get("ok")])
    return {
        "ok": True,
        "job": "token_refresh",
        "connections_total": len(conns),
        "connections_ok": ok_count,
        "connections_fail": len(results) - ok_count,
        "results": results,
    }


async def run_daily_instagram_sync(limit: int = 40) -> Dict[str, Any]:
    conns = await sb_get_active_meta_connections(platform="instagram", connection_type="organic")
    results: List[Dict[str, Any]] = []

    for c in conns:
        connection_id = str(c.get("id") or "").strip()
        client_id = str(c.get("client_id") or "").strip()
        if not connection_id or not client_id:
            continue

        job_name = f"organic_sync:{connection_id}"
        if not await _acquire_lock(client_id, job_name, ttl_seconds=1800):
            results.append({"connection_id": connection_id, "client_id": client_id, "ok": False, "skipped": True, "reason": "locked"})
            continue

        run = await start_job_run(
            job_name="instagram_organic_sync",
            client_id=client_id,
            connection_id=connection_id,
            trigger_source="cron",
            payload_json={"platform": c.get("platform"), "connection_type": c.get("connection_type"), "limit": limit},
        )
        try:
            res = await sync_instagram_connection(connection_id=connection_id, limit=limit)
            await finish_job_run(
                run["id"],
                status="success",
                client_id=client_id,
                connection_id=connection_id,
                payload_json={
                    "platform": c.get("platform"),
                    "connection_type": c.get("connection_type"),
                    "limit": limit,
                    "media_count": len(res.get("media") or []),
                    "comments_saved": res.get("comments_saved", 0),
                },
            )
            results.append(
                {
                    "connection_id": connection_id,
                    "client_id": client_id,
                    "ok": True,
                    "comments_saved": res.get("comments_saved", 0),
                    "media_count": len(res.get("media") or []),
                    "job_run_id": run["id"],
                }
            )
        except Exception as exc:
            await finish_job_run(
                run["id"],
                status="error",
                error=str(exc),
                client_id=client_id,
                connection_id=connection_id,
                payload_json={"platform": c.get("platform"), "connection_type": c.get("connection_type"), "limit": limit},
            )
            results.append(
                {
                    "connection_id": connection_id,
                    "client_id": client_id,
                    "ok": False,
                    "error": str(exc)[:240],
                    "job_run_id": run["id"],
                }
            )
        finally:
            await _release_lock(client_id, job_name)

    ok_count = len([r for r in results if r.get("ok")])
    return {
        "ok": True,
        "job": "organic_sync",
        "connections_total": len(conns),
        "connections_ok": ok_count,
        "connections_fail": len(results) - ok_count,
        "results": results,
    }


async def run_hourly_ads_sync(window_days: int = 7) -> Dict[str, Any]:
    conns = await sb_get_active_meta_connections(platform="meta_ads", connection_type="paid")
    results: List[Dict[str, Any]] = []

    for c in conns:
        connection_id = str(c.get("id") or "").strip()
        client_id = str(c.get("client_id") or "").strip()
        if not connection_id or not client_id:
            continue

        job_name = f"paid_sync:{connection_id}"
        if not await _acquire_lock(client_id, job_name, ttl_seconds=3600):
            results.append(
                {
                    "connection_id": connection_id,
                    "client_id": client_id,
                    "ok": False,
                    "skipped": True,
                    "reason": "locked",
                }
            )
            continue

        try:
            res = await sync_ads_connection(
                connection_id=connection_id,
                days=window_days,
                job_name="meta_ads_hourly_sync",
                trigger_source="cron",
                record_job_run=True,
            )
            results.append(
                {
                    "connection_id": connection_id,
                    "client_id": client_id,
                    "ok": True,
                    "saved": res.get("saved"),
                    "rows_upserted": int(res.get("rows_inserted") or 0),
                    "job_run_id": res.get("job_run_id"),
                    "job_status": res.get("job_status"),
                }
            )
        except Exception as exc:
            results.append({"connection_id": connection_id, "client_id": client_id, "ok": False, "error": str(exc)[:240]})
        finally:
            await _release_lock(client_id, job_name)

    ok_count = len([r for r in results if r.get("ok")])
    return {
        "ok": True,
        "job": "paid_sync_hourly",
        "connections_total": len(conns),
        "connections_ok": ok_count,
        "connections_fail": len(results) - ok_count,
        "window_days": window_days,
        "results": results,
    }


async def run_daily_ads_sync(days: int = 7) -> Dict[str, Any]:
    return await run_hourly_ads_sync(window_days=days)


# Compat com endpoint legado /api/cron/ig_refresh_all
async def run_daily_instagram_refresh(limit: int = 40) -> Dict[str, Any]:
    return await run_daily_instagram_sync(limit=limit)
