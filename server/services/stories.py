from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import time
from typing import Any, Dict, Optional

from .connection_resolver import resolve_connection_for_scope
from .ig_supabase import sb_get_one
from .meta_tokens import ensure_valid_meta_token
from .ig_meta import fetch_stories, fetch_story_insights


def _parse_date(value: str | None) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except Exception:
        return None


def _resolve_period(days: int, start: str | None, end: str | None) -> tuple[date, date]:
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    if start_date and end_date:
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        return start_date, end_date

    safe_days = max(1, min(int(days or 30), 3650))
    until = datetime.now(timezone.utc).date()
    since = until - timedelta(days=safe_days - 1)
    return since, until


def _story_in_range(story: Dict[str, Any], since: date, until: date) -> bool:
    ts = str(story.get("timestamp") or "").strip()
    if len(ts) < 10:
        return False
    try:
        d = date.fromisoformat(ts[:10])
    except Exception:
        return False
    return since <= d <= until


async def get_stories(
    client_id: str,
    connection_id: Optional[str] = None,
    limit: int = 25,
    days: int = 30,
    start: str | None = None,
    end: str | None = None,
) -> Dict[str, Any]:
    started = time.perf_counter()
    safe_limit = max(1, min(int(limit or 25), 50))
    requested_connection_id = str(connection_id or "").strip()
    resolved_connection_id = requested_connection_id
    try:
        resolved_connection = await resolve_connection_for_scope(
            client_id=client_id,
            platform="instagram",
            connection_type="organic",
            requested_connection_id=requested_connection_id or None,
        )
        resolved_connection_id = str(resolved_connection.get("connection_id") or "").strip()
        connection_source = str(resolved_connection.get("source") or "none").strip() or "none"
        resolved_row = resolved_connection.get("row") or {}
        token_connection_id: Optional[str] = resolved_connection_id or None
        client = await sb_get_one("clients", f"id=eq.{client_id}")
        if not client:
            raise RuntimeError("Client não encontrado")

        ig_user_id = str(resolved_row.get("ig_user_id") or "").strip()
        if not ig_user_id:
            ig_user_id = (client.get("ig_user_id") or "").strip()

        print(
            "[stories] request "
            f"client_id={client_id} connection_id_requested={requested_connection_id or '-'} "
            f"connection_id_resolved={resolved_connection_id or '-'} connection_source={connection_source} "
            f"ig_user_id={ig_user_id or '-'} limit={safe_limit}"
        )

        if not ig_user_id:
            return {
                "ok": False,
                "available": False,
                "client_id": client_id,
                "connection_id": resolved_connection_id or None,
                "message": "IG user não configurado para este cliente.",
                "stories": [],
            }

        token = await ensure_valid_meta_token(
            client_id,
            connection_id=token_connection_id,
            platform="instagram",
            connection_type="organic",
        )
        since, until = _resolve_period(days=days, start=start, end=end)
        stories = await fetch_stories(ig_user_id, token, limit=safe_limit)
        filtered = [story for story in stories if _story_in_range(story, since, until)]
        warnings: list[str] = []
        enriched = []
        for story in filtered:
            story_id = str(story.get("id") or "").strip()
            if not story_id:
                enriched.append(story)
                continue
            try:
                enriched.append({**story, "insights": await fetch_story_insights(story_id, token)})
            except Exception as exc:
                print(
                    "[stories][insights_warning] "
                    f"client_id={client_id} story_id={story_id} error={exc.__class__.__name__}"
                )
                warnings.append("Insights de stories ainda não disponíveis para esta conta.")
                enriched.append(story)
        print(
            "[stories] result "
            f"client_id={client_id} connection_id={resolved_connection_id or '-'} "
            f"stories={len(enriched)} limit={safe_limit} "
            f"start={since.isoformat()} end={until.isoformat()} "
            f"duration_ms={int((time.perf_counter() - started) * 1000)}"
        )
        return {
            "ok": True,
            "available": True,
            "client_id": client_id,
            "connection_id": resolved_connection_id or None,
            "stories": enriched,
            "warnings": sorted(set(warnings)),
        }
    except Exception as exc:
        print(
            "[stories] fallback "
            f"client_id={client_id} connection_id={resolved_connection_id or '-'} "
            f"duration_ms={int((time.perf_counter() - started) * 1000)} "
            f"error={exc.__class__.__name__}: {str(exc)[:260]}"
        )
        return {
            "ok": False,
            "available": False,
            "client_id": client_id,
            "connection_id": resolved_connection_id or None,
            "message": "Stories indisponíveis nesta conta/permissão da API Instagram Graph.",
            "stories": [],
        }
