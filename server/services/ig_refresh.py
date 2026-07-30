from __future__ import annotations

from typing import Any, Dict, Optional

from .instagram_sync import sync_instagram_for_client


async def refresh_all(
    client_id: Optional[str],
    limit: int = 40,
    connection_id: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Dict[str, Any]:
    cid = (client_id or "").strip()
    if not cid:
        raise RuntimeError("client_id é obrigatório")
    chosen_connection_id = (connection_id or "").strip() or None
    print(
        "[refresh_all] start "
        f"client_id={cid} connection_id={chosen_connection_id or '-'} "
        f"limit={limit} start={start or '-'} end={end or '-'}"
    )
    try:
        return await sync_instagram_for_client(
            client_id=cid,
            limit=limit,
            preferred_connection_id=chosen_connection_id,
        )
    except Exception as exc:
        print(
            "[refresh_all] error "
            f"client_id={cid} connection_id={chosen_connection_id or '-'} "
            f"start={start or '-'} end={end or '-'} error={str(exc)[:280]}"
        )
        raise
