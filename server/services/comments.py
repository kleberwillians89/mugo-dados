from __future__ import annotations

from datetime import datetime, timedelta, timezone, date
import time
from typing import Any, Dict, List
import re
import httpx

from .connection_resolver import resolve_connection_for_scope
from .ig_supabase import sb_select

_STOPWORDS = {
    "a", "o", "os", "as", "de", "da", "do", "das", "dos", "e", "é", "em", "no", "na", "nos", "nas",
    "para", "por", "com", "sem", "que", "se", "um", "uma", "uns", "umas", "ao", "à", "às", "aos",
    "the", "and", "or", "to", "of", "for", "in", "on", "at", "is", "are", "be", "it", "this", "that",
    "i", "you", "he", "she", "we", "they", "me", "my", "your", "our", "their", "do", "does", "did",
}


_WORD_RE = re.compile(r"[a-zA-ZÀ-ÿ0-9]{3,}")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_missing_column_error(exc: httpx.HTTPStatusError, column_name: str) -> bool:
    if exc.response is None:
        return False
    if exc.response.status_code not in {400, 404}:
        return False
    body = str(exc.response.text or "").lower()
    col = str(column_name or "").lower()
    return col in body and ("column" in body or "schema cache" in body)


def _parse_date(value: str | None) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except Exception:
        return None


def _resolve_window(
    *,
    days: int,
    start: str | None,
    end: str | None,
) -> tuple[datetime | None, datetime | None]:
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    if start_date and end_date:
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        since_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
        until_dt = datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc)
        return since_dt, until_dt

    use_all = int(days or 0) <= 0
    if use_all:
        return None, None

    safe_days = max(1, min(days, 3650))
    since_dt = _utc_now() - timedelta(days=safe_days - 1)
    return since_dt, None


def _tokenize(text: str) -> List[str]:
    out: List[str] = []
    for m in _WORD_RE.findall((text or "").lower()):
        if m in _STOPWORDS:
            continue
        if m.isdigit():
            continue
        out.append(m)
    return out


def top_words(comments: List[Dict[str, Any]], limit: int = 20) -> List[Dict[str, Any]]:
    freq: Dict[str, int] = {}
    for c in comments:
        text = str(c.get("text") or "")
        for tok in _tokenize(text):
            freq[tok] = int(freq.get(tok) or 0) + 1

    items = sorted(freq.items(), key=lambda x: (-x[1], x[0]))[: max(1, limit)]
    return [{"word": w, "count": n} for w, n in items]


def _chunk(values: List[str], size: int = 140) -> List[List[str]]:
    if size <= 0:
        return [values]
    return [values[i : i + size] for i in range(0, len(values), size)]


async def get_comments(
    client_id: str,
    connection_id: str | None = None,
    days: int = 90,
    start: str | None = None,
    end: str | None = None,
    limit: int = 120,
    offset: int = 0,
    include_media_linked: bool = False,
) -> Dict[str, Any]:
    started = time.perf_counter()
    safe_limit = max(1, min(int(limit or 120), 500))
    safe_offset = max(0, int(offset or 0))
    since_dt, until_dt = _resolve_window(days=days, start=start, end=end)
    requested_connection_id = str(connection_id or "").strip()
    resolved_connection = await resolve_connection_for_scope(
        client_id=client_id,
        platform="instagram",
        connection_type="organic",
        requested_connection_id=requested_connection_id or None,
    )
    resolved_connection_id = str(resolved_connection.get("connection_id") or "").strip()
    connection_source = str(resolved_connection.get("source") or "none").strip() or "none"

    print(
        "[comments] request "
        f"client_id={client_id} connection_id_requested={requested_connection_id or '-'} "
        f"connection_id_resolved={resolved_connection_id or '-'} connection_source={connection_source} "
        f"days={days} "
        f"start={start or '-'} end={end or '-'} "
        f"resolved_start={since_dt.isoformat() if since_dt else '-'} "
        f"resolved_end={until_dt.isoformat() if until_dt else '-'} "
        f"limit={safe_limit} offset={safe_offset} include_media_linked={1 if include_media_linked else 0}"
    )

    filters = {"client_id": f"eq.{client_id}"}
  
    if since_dt and until_dt:
        filters["and"] = f"(timestamp.gte.{since_dt.isoformat()},timestamp.lte.{until_dt.isoformat()})"
    elif since_dt:
        filters["timestamp"] = f"gte.{since_dt.isoformat()}"

    try:
        # 1) Comentários por timestamp (janela tradicional), com paginação.
        rows = await sb_select(
            "ig_comments",
            filters=filters,
            order="timestamp.desc",
            limit=safe_limit,
            offset=safe_offset,
        )
    except httpx.HTTPStatusError as exc:
        # Compat: ambiente ainda sem tabela ig_comments
        if exc.response is None or exc.response.status_code != 404:
            raise
        rows = []

    media_count = 0
    media_scope_mode = "client_scope"
    media_ids: List[str] = []
    media_filters = {"client_id": f"eq.{client_id}"}
    if resolved_connection_id:
        media_filters["connection_id"] = f"eq.{resolved_connection_id}"
        media_scope_mode = "connection_scope"
    if since_dt and until_dt:
        media_filters["and"] = f"(timestamp.gte.{since_dt.isoformat()},timestamp.lte.{until_dt.isoformat()})"
    elif since_dt:
        media_filters["timestamp"] = f"gte.{since_dt.isoformat()}"

    try:
        try:
            media_rows = await sb_select(
                "ig_media",
                select="media_id",
                filters=media_filters,
                order="timestamp.desc",
                limit=min(800, max(200, safe_limit * 4)),
            )
        except httpx.HTTPStatusError as exc:
            if not (resolved_connection_id and _is_missing_column_error(exc, "connection_id")):
                raise
            media_filters_fallback = {"client_id": f"eq.{client_id}"}
            if since_dt and until_dt:
                media_filters_fallback["and"] = (
                    f"(timestamp.gte.{since_dt.isoformat()},timestamp.lte.{until_dt.isoformat()})"
                )
            elif since_dt:
                media_filters_fallback["timestamp"] = f"gte.{since_dt.isoformat()}"
            media_rows = await sb_select(
                "ig_media",
                select="media_id",
                filters=media_filters_fallback,
                order="timestamp.desc",
                limit=min(800, max(200, safe_limit * 4)),
            )
            media_scope_mode = "connection_column_missing"
        media_ids = [str(row.get("media_id") or "").strip() for row in media_rows if row.get("media_id")]
        media_ids = [media_id for media_id in media_ids if media_id]
        media_ids = list(dict.fromkeys(media_ids))
        media_count = len(media_ids)
    except Exception:
        media_ids = []
        media_count = 0

    if resolved_connection_id:
        media_id_set = set(media_ids)
        if media_id_set:
            rows = [
                row
                for row in rows
                if str(row.get("media_id") or "").strip() in media_id_set
            ]
        else:
            rows = []

    # Opcional para casos em que o comentário está fora da janela de timestamp,
    # mas pertence a mídias dentro do período.
    if include_media_linked and media_ids:
        extra_rows: List[Dict[str, Any]] = []
        media_id_set = set(media_ids)
        max_chunks = 4
        for idx, chunk_ids in enumerate(_chunk(media_ids, size=80)):
            if idx >= max_chunks:
                break
            if not chunk_ids:
                continue
            in_clause = ",".join(chunk_ids)
            chunk_filters = {
                "client_id": f"eq.{client_id}",
                "media_id": f"in.({in_clause})",
            }
            try:
                chunk_rows = await sb_select(
                    "ig_comments",
                    filters=chunk_filters,
                    order="timestamp.desc",
                    limit=max(safe_limit, 150),
                )
            except httpx.HTTPStatusError as exc:
                if exc.response is None or exc.response.status_code != 404:
                    raise
                chunk_rows = []
            extra_rows.extend(chunk_rows)
            if len(extra_rows) >= safe_limit * 2:
                break

        if extra_rows:
            merged: Dict[str, Dict[str, Any]] = {}
            for row in rows + extra_rows:
                media_id = str(row.get("media_id") or "").strip()
                if not media_id or media_id not in media_id_set:
                    continue
                key = str(row.get("comment_id") or "").strip() or str(row.get("id") or "")
                if not key:
                    continue
                merged[key] = row
            merged_rows = sorted(
                list(merged.values()),
                key=lambda row: str(row.get("timestamp") or ""),
                reverse=True,
            )
            total = len(merged_rows)
            rows = merged_rows[safe_offset : safe_offset + safe_limit]
            has_more = (safe_offset + safe_limit) < total
            next_offset = safe_offset + safe_limit if has_more else None
        else:
            filtered_rows = []
            for row in rows:
                media_id = str(row.get("media_id") or "").strip()
                if media_id and media_id in media_id_set:
                    filtered_rows.append(row)
            rows = filtered_rows
            has_more = len(rows) >= safe_limit
            next_offset = safe_offset + safe_limit if has_more else None
            total = safe_offset + len(rows) + (1 if has_more else 0)
    elif include_media_linked and not media_ids:
        rows = []
        has_more = False
        next_offset = None
        total = 0
    else:
        has_more = len(rows) >= safe_limit
        next_offset = safe_offset + safe_limit if has_more else None
        total = safe_offset + len(rows) + (1 if has_more else 0)

    print(
        "[comments] result "
        f"client_id={client_id} connection_id_requested={requested_connection_id or '-'} "
        f"connection_id_resolved={resolved_connection_id or '-'} connection_source={connection_source} "
        f"media_count={media_count} media_scope_mode={media_scope_mode} "
        f"comments_count={len(rows)} has_more={1 if has_more else 0} "
        f"duration_ms={int((time.perf_counter() - started) * 1000)}"
    )

    return {
        "ok": True,
        "client_id": client_id,
        "connection_id": resolved_connection_id or None,
        "days": days,
        "start": start,
        "end": end,
        "limit": safe_limit,
        "offset": safe_offset,
        "next_offset": next_offset,
        "has_more": has_more,
        "total": total,
        "comments": rows,
        "top_words": top_words(rows, limit=30),
    }
