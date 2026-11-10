from __future__ import annotations

import time
import json
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_get_client_memberships, sb_insert, sb_select, sb_update
from .meta_tokens import upsert_meta_connection
from .client_lifecycle import is_operational


async def list_clients_for_user(user_id: str) -> Dict[str, Any]:
    started = time.perf_counter()
    memberships = await sb_get_client_memberships(user_id, include_clients=False)

    is_agency_admin = any(str(row.get("role") or "").strip() == "agency_admin" for row in memberships)
    from .platform_admin import is_platform_admin
    platform_admin = await is_platform_admin(user_id) if not is_agency_admin else False
    if is_agency_admin or platform_admin:
        rows = await sb_select("clients", select="id,name,trade_name,created_at,status", order="name.asc")
        return {
            "ok": True,
            "clients": [
                {"client_id": row.get("id"), "role": "platform_admin" if platform_admin else "agency_admin", "name": row.get("trade_name") or row.get("name") or "Sem nome", "created_at": row.get("created_at")}
                for row in rows if is_operational(row)
            ],
        }

    ids = sorted({str(m.get("client_id") or "").strip() for m in memberships if m.get("client_id")})
    by_id = {}
    for offset in range(0, len(ids), 100):
        batch = ids[offset:offset+100]
        rows = await sb_select("clients", select="id,name,trade_name,created_at,status",
            filters={"id": "in.(" + ",".join(json.dumps(cid) for cid in batch) + ")"}, limit=len(batch))
        by_id.update({str(row.get("id")): row for row in rows if str(row.get("id")) in batch and is_operational(row)})
    clients: List[Dict[str, Any]] = []
    for m in memberships:
        cid = str(m.get("client_id") or "").strip()
        c = by_id.get(cid)
        if c is None:
            continue
        clients.append({"client_id": cid, "role": m.get("role"),
            "name": c.get("trade_name") or c.get("name") or "Sem nome", "created_at": c.get("created_at")})

    print(
        "[clients] result "
        f"user_id={user_id} clients={len(clients)} duration_ms={int((time.perf_counter() - started) * 1000)}"
    )
    return {"ok": True, "clients": clients}


async def create_client_for_user(user_id: str, name: str) -> Dict[str, Any]:
    n = (name or "").strip()
    if len(n) < 2:
        raise RuntimeError("Nome do cliente deve ter ao menos 2 caracteres")

    client = await sb_insert("clients", {"name": n}, returning="representation")
    if not client:
        raise RuntimeError("Falha ao criar client")

    await sb_insert(
        "client_memberships",
        {
            "user_id": user_id,
            "client_id": client.get("id"),
            "role": "owner",
        },
        returning="minimal",
    )

    return {
        "ok": True,
        "client": {
            "id": client.get("id"),
            "name": client.get("name"),
            "created_at": client.get("created_at"),
            "role": "owner",
        },
    }


async def connect_meta_for_client(
    client_id: str,
    access_token: str,
    expires_at: Optional[str],
    ig_user_id: Optional[str],
) -> Dict[str, Any]:
    out = await upsert_meta_connection(
        client_id=client_id,
        access_token=access_token,
        expires_at=expires_at,
        ig_user_id=ig_user_id,
    )

    if ig_user_id is not None and str(ig_user_id).strip():
        await sb_update(
            "clients",
            filters={"id": f"eq.{client_id}"},
            patch={"ig_user_id": str(ig_user_id).strip()},
            returning="minimal",
        )

    rows = await sb_select("clients", filters={"id": f"eq.{client_id}"}, limit=1)
    client_row = rows[0] if rows else None

    return {
        **out,
        "client": {
            "id": client_id,
            "name": (client_row or {}).get("name"),
            "ig_user_id": (client_row or {}).get("ig_user_id"),
        },
    }
