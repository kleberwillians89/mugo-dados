from __future__ import annotations

from typing import Any, Dict

from .ig_supabase import sb_rpc


async def refresh_dashboard_read_model(
    *, client_id: str, start: str, end: str, provider: str
) -> Dict[str, Any]:
    """Refresh a persisted date slice after the provider raw rows are durable."""
    result = await sb_rpc(
        "refresh_dashboard_read_model",
        {
            "p_client_id": client_id,
            "p_start": start,
            "p_end": end,
            "p_provider": provider,
        },
    )
    print(
        "[dashboard_read_model][refresh_complete] "
        f"client_id={client_id} provider={provider} start={start} end={end}"
    )
    return result if isinstance(result, dict) else {"ok": True, "result": result}


async def refresh_dashboard_read_model_safely(
    *, client_id: str, start: str, end: str, provider: str
) -> Dict[str, Any]:
    """Keep durable raw data and the previous snapshot when projection refresh fails."""
    try:
        return await refresh_dashboard_read_model(
            client_id=client_id, start=start, end=end, provider=provider
        )
    except Exception as exc:
        print(
            "[dashboard_read_model][refresh_warning] "
            f"client_id={client_id} provider={provider} start={start} end={end} "
            f"error_type={exc.__class__.__name__}"
        )
        return {"ok": False, "preserved": True, "error_type": exc.__class__.__name__}
