from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional
import httpx

from .ig_supabase import sb_select, sb_insert, sb_update


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_missing_column_error(exc: httpx.HTTPStatusError, column_name: str) -> bool:
    if exc.response is None:
        return False
    if exc.response.status_code not in {400, 404}:
        return False
    body = str(exc.response.text or "").lower()
    col = str(column_name or "").lower()
    return col in body and ("column" in body or "schema cache" in body)


def _is_missing_table_error(exc: httpx.HTTPStatusError) -> bool:
    if exc.response is None:
        return False
    if exc.response.status_code == 404:
        return True
    body = str(exc.response.text or "").lower()
    return "relation" in body and "does not exist" in body


async def list_notes(
    client_id: str,
    connection_id: Optional[str] = None,
    limit: int = 80,
) -> Dict[str, Any]:
    started = time.perf_counter()
    safe_limit = max(1, min(int(limit or 80), 300))
    requested_connection = str(connection_id or "").strip()
    base_filters: Dict[str, str] = {"client_id": f"eq.{client_id}"}
    rows: List[Dict[str, Any]] = []
    table_used: str | None = None
    available = False
    message: str | None = None

    for table_name in ("client_notes", "notes"):
        filters = dict(base_filters)
        if requested_connection:
            filters["connection_id"] = f"eq.{requested_connection}"
        try:
            rows = await sb_select(
                table_name,
                filters=filters,
                order="updated_at.desc",
                limit=safe_limit,
            )
            table_used = table_name
            available = True
            break
        except httpx.HTTPStatusError as exc:
            if requested_connection and _is_missing_column_error(exc, "connection_id"):
                filters.pop("connection_id", None)
                rows = await sb_select(
                    table_name,
                    filters=filters,
                    order="updated_at.desc",
                    limit=safe_limit,
                )
                print(f"[notes] compat=connection_id_column_missing table={table_name}")
                table_used = table_name
                available = True
                break
            if _is_missing_table_error(exc):
                print(f"[notes] compat=table_missing table={table_name}")
                continue
            raise

    if not table_used:
        message = "Notas indisponíveis neste ambiente da empresa."
    print(
        "[notes] result "
        f"client_id={client_id} connection_id={requested_connection or '-'} "
        f"table={table_used or '-'} "
        f"available={1 if available else 0} "
        f"notes={len(rows)} limit={safe_limit} "
        f"duration_ms={int((time.perf_counter() - started) * 1000)}"
    )
    return {
        "ok": True,
        "client_id": client_id,
        "connection_id": requested_connection or None,
        "available": available,
        "message": message,
        "notes": rows,
        "limit": safe_limit,
    }


async def create_note(client_id: str, title: str, body: str) -> Dict[str, Any]:
    row = await sb_insert(
        "client_notes",
        {
            "client_id": client_id,
            "title": (title or "Sem título").strip() or "Sem título",
            "body": body or "",
            "updated_at": _iso_now(),
        },
        returning="representation",
    )
    return {"ok": True, "note": row}


async def update_note(client_id: str, note_id: str, title: Optional[str], body: Optional[str]) -> Dict[str, Any]:
    patch: Dict[str, Any] = {"updated_at": _iso_now()}
    if title is not None:
        patch["title"] = (title or "Sem título").strip() or "Sem título"
    if body is not None:
        patch["body"] = body

    rows = await sb_update(
        "client_notes",
        filters={"id": f"eq.{note_id}", "client_id": f"eq.{client_id}"},
        patch=patch,
        returning="representation",
    )
    note = rows[0] if rows else None
    if not note:
        raise RuntimeError("Nota não encontrada")

    return {"ok": True, "note": note}
