"""Read existing leases/cooldown only. Never acquire locks or start providers."""
import math
import time
from datetime import datetime, timezone

from fastapi import HTTPException

from . import ads_sync
from .ig_supabase import sb_select


async def refresh_status(client_id, provider, start, end):
    now = datetime.now(timezone.utc)
    facade = f"sync:data_refresh:{provider}"
    cooldown = f"refresh_cooldown:{provider}"
    prefixes = {"meta": ("sync:meta_ads:", "sync:meta_organic:"),
                "google": ("sync:ga4:", "sync:google_ads:"),
                "shopify": ("sync:shopify:",), "fbits": ("sync:fbits:",)}.get(provider)
    if prefixes is None:
        raise HTTPException(400, "Plataforma inválida.")
    choices = [f"job_name.eq.{facade}", f"job_name.eq.{cooldown}"] + [f"job_name.like.{prefix}*" for prefix in prefixes]
    rows = await sb_select("cron_locks", select="client_id,job_name,locked_until",
        filters={"client_id": f"eq.{client_id}", "locked_until": f"gt.{now.isoformat()}",
                 "or": "(" + ",".join(choices) + ")"}, limit=101)
    if len(rows) > 100:
        raise HTTPException(503, "Não foi possível verificar a atualização. Tente novamente.")
    running, seconds = False, 0
    for row in rows:
        name = str(row.get("job_name") or "")
        if row.get("client_id") != client_id or not (name in {facade, cooldown} or name.startswith(prefixes)):
            continue
        try:
            until = datetime.fromisoformat(str(row["locked_until"]).replace("Z", "+00:00"))
            remaining = (until - now).total_seconds()
        except (KeyError, TypeError, ValueError):
            raise HTTPException(503, "Não foi possível verificar a atualização. Tente novamente.") from None
        if remaining > 0:
            if name == cooldown:
                seconds = max(seconds, math.ceil(remaining))
            else:
                running = True
    if provider == "meta":
        # Reuse the concrete Ads dedup window; a browser reload must not bypass it.
        suffix = f":{start}:{end}"
        for key, completed in ads_sync._RECENT_SYNC_KEYS.items():
            if key.startswith(f"{client_id}:") and key.endswith(suffix):
                seconds = max(seconds, math.ceil(ads_sync._SYNC_DEDUP_SECONDS - (time.monotonic() - completed)))
    return {"client_id": client_id, "provider": provider, "authorized": True,
            "running": running, "cooldown_seconds": max(0, seconds)}
