from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from .ads_sync import sync_ads_connection
from .ig_supabase import sb_get_active_meta_connections, sb_rpc, sb_select
from .instagram_sync import sync_instagram_connection
from .job_runs import finish_job_run, start_job_run
from .meta_tokens import ensure_valid_meta_token
from .periods import DEFAULT_TENANT_TIMEZONE
from .shopify_oauth import (
    list_active_shopify_connections,
    reconcile_shopify_period,
    resolve_shopify_reconciliation_since,
    sync_shopify_connection,
)


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


async def run_daily_instagram_sync(limit: int = 40, *, process_thumbnails: bool = True) -> Dict[str, Any]:
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
            payload_json={
                "platform": c.get("platform"), "connection_type": c.get("connection_type"),
                "limit": limit, "process_thumbnails": process_thumbnails,
            },
        )
        try:
            res = await sync_instagram_connection(
                connection_id=connection_id, limit=limit, process_thumbnails=process_thumbnails,
            )
            await finish_job_run(
                run["id"],
                status="success",
                client_id=client_id,
                connection_id=connection_id,
                payload_json={
                    "platform": c.get("platform"),
                    "connection_type": c.get("connection_type"),
                    "limit": limit,
                    "process_thumbnails": process_thumbnails,
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
                payload_json={
                    "platform": c.get("platform"), "connection_type": c.get("connection_type"),
                    "limit": limit, "process_thumbnails": process_thumbnails,
                },
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
        "job": "organic_sync" if process_thumbnails else "organic_wide_reconciliation",
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


async def run_ga4_sync_all(window_days: int = 3) -> Dict[str, Any]:
    from .ga4_sync import sync_ga4_for_period
    from .google_oauth import get_google_access_token

    conns = await sb_select(
        "integration_connections", filters={"provider": "eq.ga4", "status": "eq.connected"},
        order="updated_at.asc", limit=500,
    )
    results: List[Dict[str, Any]] = []
    for connection in conns:
        client_id = str(connection.get("client_id") or "").strip()
        connection_id = str(connection.get("id") or "").strip()
        metadata = connection.get("metadata") if isinstance(connection.get("metadata"), dict) else {}
        property_id = str(metadata.get("ga4_property_id") or "").strip()
        if not client_id or not connection_id or not property_id:
            results.append({"client_id": client_id, "connection_id": connection_id, "ok": False, "skipped": True, "reason": "property_required"})
            continue
        try:
            token = await get_google_access_token(client_id, connection_id)
            response = await sync_ga4_for_period(
                client_id=client_id, connection_id=connection_id, property_id=property_id,
                access_token=token, days=window_days, job_name="ga4_sync_cron",
                trigger_source="cron", record_job_run=True,
            )
            results.append({"client_id": client_id, "connection_id": connection_id, "ok": True, "rows_upserted": response.get("rows_upserted")})
        except Exception as exc:
            results.append({"client_id": client_id, "connection_id": connection_id, "ok": False, "error": str(exc)[:240]})
    return _provider_job_summary("ga4_sync", conns, results, window_days)


async def run_google_ads_sync_all(window_days: int = 7) -> Dict[str, Any]:
    from .google_ads import sync_google_ads

    conns = await sb_select(
        "integration_connections", filters={"provider": "eq.google_ads", "status": "eq.connected"},
        order="updated_at.asc", limit=500,
    )
    results: List[Dict[str, Any]] = []
    for connection in conns:
        client_id = str(connection.get("client_id") or "").strip()
        connection_id = str(connection.get("id") or "").strip()
        if not client_id or not connection_id:
            continue
        try:
            response = await sync_google_ads(
                client_id=client_id, connection_id=connection_id,
                start=None, end=None, days=window_days,
            )
            results.append({"client_id": client_id, "connection_id": connection_id, "ok": True, "rows_upserted": response.get("rows_upserted")})
        except Exception as exc:
            results.append({"client_id": client_id, "connection_id": connection_id, "ok": False, "error": str(exc)[:240]})
    return _provider_job_summary("google_ads_sync", conns, results, window_days)


def _provider_job_summary(
    job: str, connections: List[Dict[str, Any]], results: List[Dict[str, Any]], window_days: int,
) -> Dict[str, Any]:
    ok_count = sum(1 for result in results if result.get("ok"))
    return {
        "ok": True, "job": job, "window_days": window_days,
        "connections_total": len(connections), "connections_ok": ok_count,
        "connections_fail": len(results) - ok_count, "results": results,
    }


async def run_shopify_incremental(fallback_days: int = 30) -> Dict[str, Any]:
    """Frequent RAW-watermark sync; webhooks remain the fastest path."""
    conns = await list_active_shopify_connections()
    results: List[Dict[str, Any]] = []

    for c in conns:
        connection_id = str(c.get("id") or "").strip()
        client_id = str(c.get("client_id") or "").strip()
        if not connection_id or not client_id:
            continue

        print(f"[shopify][incremental][start] client={client_id} connection_id={connection_id}")

        run = await start_job_run(
            job_name="shopify_incremental",
            client_id=client_id,
            connection_id=connection_id,
            trigger_source="cron",
            payload_json={"fallback_days": fallback_days},
        )
        try:
            updated_at_min = await resolve_shopify_reconciliation_since(
                client_id, connection_id, fallback_days=fallback_days,
            )
            res = await sync_shopify_connection(
                client_id=client_id, connection_id=connection_id, updated_at_min=updated_at_min,
            )
            await finish_job_run(
                run["id"],
                status="success",
                client_id=client_id,
                connection_id=connection_id,
                payload_json={"updated_at_min": updated_at_min, "orders_synced": (res.get("synced") or {}).get("orders")},
            )
            results.append({"connection_id": connection_id, "client_id": client_id, "ok": True, "job_run_id": run["id"]})
            print(
                f"[shopify][incremental][done] client={client_id} connection_id={connection_id} "
                f"orders={(res.get('synced') or {}).get('orders_upserted', 0)}"
            )
        except Exception as exc:
            await finish_job_run(
                run["id"],
                status="error",
                error=str(exc),
                client_id=client_id,
                connection_id=connection_id,
                payload_json={"fallback_days": fallback_days},
            )
            results.append({"connection_id": connection_id, "client_id": client_id, "ok": False, "error": str(exc)[:240], "job_run_id": run["id"]})

    ok_count = len([r for r in results if r.get("ok")])
    return {
        "ok": True,
        "job": "shopify_incremental",
        "connections_total": len(conns),
        "connections_ok": ok_count,
        "connections_fail": len(results) - ok_count,
        "results": results,
    }


async def run_shopify_historical_reconciliation(
    window_days: int = 14, *, today: date | None = None,
) -> Dict[str, Any]:
    """Daily bounded self-healing pass using the same reconciliation service as the admin endpoint."""
    safe_days = max(1, min(int(window_days), 90))
    period_end = today or datetime.now(ZoneInfo(DEFAULT_TENANT_TIMEZONE)).date()
    period_start = period_end - timedelta(days=safe_days - 1)
    conns = await list_active_shopify_connections()
    results: List[Dict[str, Any]] = []
    for connection in conns:
        connection_id = str(connection.get("id") or "").strip()
        client_id = str(connection.get("client_id") or "").strip()
        if not connection_id or not client_id:
            continue
        start = period_start.isoformat()
        end = period_end.isoformat()
        print(
            f"[shopify][reconcile][start] client={client_id} connection_id={connection_id} "
            f"start={start} end={end}"
        )
        run = await start_job_run(
            job_name="shopify_historical_reconciliation", client_id=client_id,
            connection_id=connection_id, trigger_source="cron",
            payload_json={"start": start, "end": end, "window_days": safe_days},
        )
        try:
            response = await reconcile_shopify_period(
                client_id=client_id, connection_id=connection_id, start=start, end=end,
            )
            synced = response.get("synced") or {}
            print(
                f"[shopify][reconcile][fetched] client={client_id} connection_id={connection_id} "
                f"orders={synced.get('orders_received', 0)}"
            )
            print(
                f"[shopify][reconcile][persisted] client={client_id} connection_id={connection_id} "
                f"orders={synced.get('orders_upserted', 0)}"
            )
            print(
                f"[shopify][reconcile][projection] client={client_id} connection_id={connection_id} "
                f"start={start} end={end} status=complete"
            )
            await finish_job_run(
                run["id"], status="success", rows_upserted=int(synced.get("orders_upserted") or 0),
                client_id=client_id, connection_id=connection_id,
                payload_json={"start": start, "end": end, "window_days": safe_days, "synced": synced},
            )
            results.append({"client_id": client_id, "connection_id": connection_id, "ok": True, "synced": synced})
            print(f"[shopify][reconcile][done] client={client_id} connection_id={connection_id} status=success")
        except Exception as exc:
            await finish_job_run(
                run["id"], status="error", error=str(exc), client_id=client_id,
                connection_id=connection_id,
                payload_json={"start": start, "end": end, "window_days": safe_days},
            )
            results.append({"client_id": client_id, "connection_id": connection_id, "ok": False, "error": str(exc)[:240]})
            print(
                f"[shopify][reconcile][done] client={client_id} connection_id={connection_id} "
                f"status=error error_type={exc.__class__.__name__}"
            )
    ok_count = sum(1 for result in results if result.get("ok"))
    return {
        "ok": True, "job": "shopify_historical_reconciliation", "window_days": safe_days,
        "period": {"start": period_start.isoformat(), "end": period_end.isoformat()},
        "connections_total": len(conns), "connections_ok": ok_count,
        "connections_fail": len(results) - ok_count, "results": results,
    }


# Backwards-compatible name for callers that meant the frequent incremental pass.
run_shopify_reconciliation = run_shopify_incremental


# Compat com endpoint legado /api/cron/ig_refresh_all
async def run_daily_instagram_refresh(limit: int = 40) -> Dict[str, Any]:
    return await run_daily_instagram_sync(limit=limit)
