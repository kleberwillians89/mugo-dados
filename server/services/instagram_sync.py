from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any, Dict, List, Optional

import httpx

from .connection_resolver import resolve_connection_for_scope
from .ig_meta import (
    download_image,
    fetch_kpis_total_value,
    fetch_media_comments,
    fetch_media_insights,
    fetch_media_list,
    fetch_profile,
    fetch_stories,
    fetch_story_insights,
)
from .ig_supabase import sb_get_one, sb_insert, sb_select, sb_update, sb_upsert, sb_upload_public
from .meta_oauth import fetch_instagram_identity
from .meta_tokens import ensure_valid_meta_token


def _utc_date_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_meta_ts(value: Any) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return None
    if len(raw) >= 5 and (raw.endswith("+0000") or raw.endswith("-0000")):
        raw = f"{raw[:-5]}{raw[-5:-2]}:{raw[-2:]}"
    return raw


def _classify_meta_error(exc: Exception) -> str:
    msg = str(exc)
    if "\"code\":10" in msg or "(#10)" in msg:
        return "permission_denied"
    if "\"code\":190" in msg:
        return "token_expired"
    return "error"


def _empty_kpis() -> Dict[str, int]:
    return {
        "impressions": 0,
        "views": 0,
        "reach": 0,
        "profile_views": 0,
        "website_clicks": 0,
        "accounts_engaged": 0,
        "total_interactions": 0,
    }


def _env(name: str) -> str:
    return str(os.getenv(name) or "").strip()


def _schema_warning(block: str, client_id: str, connection_id: str, exc: httpx.HTTPStatusError) -> None:
    status = exc.response.status_code if exc.response is not None else "-"
    print(
        "[ig_sync][schema_pending] "
        f"block={block} client_id={client_id} connection_id={connection_id} status={status}"
    )


async def _resolve_connection_by_id(connection_id: str) -> Optional[Dict[str, Any]]:
    rows = await sb_select("meta_connections", filters={"id": f"eq.{connection_id}"}, limit=1)
    return rows[0] if rows else None


async def _mark_connection_success(connection_id: str) -> None:
    await sb_update(
        "meta_connections",
        filters={"id": f"eq.{connection_id}"},
        patch={"last_synced_at": _iso_now(), "last_error": None, "status": "active"},
        returning="minimal",
    )


async def _mark_connection_error(connection_id: str, message: str) -> None:
    await sb_update(
        "meta_connections",
        filters={"id": f"eq.{connection_id}"},
        patch={"last_error": (message or "")[:1000], "status": "error"},
        returning="minimal",
    )


def _identity_candidates(identity: Dict[str, Any]) -> List[Dict[str, str]]:
    return [
        {
            "ig_user_id": str((account or {}).get("ig_user_id") or "").strip(),
            "username": str((account or {}).get("username") or "").strip(),
            "business_id": str((account or {}).get("business_id") or "").strip(),
            "business_name": str((account or {}).get("business_name") or "").strip(),
        }
        for account in (identity.get("instagram_accounts") or [])
        if str((account or {}).get("ig_user_id") or "").strip()
    ]


def _pick_identity_candidate(candidates: List[Dict[str, str]], client: Dict[str, Any] | None) -> Dict[str, str] | None:
    if len(candidates) == 1:
        return candidates[0]
    terms = [
        str((client or {}).get(key) or "").strip().lower()
        for key in ("name", "slug")
        if str((client or {}).get(key) or "").strip()
    ]
    matches = [
        candidate
        for candidate in candidates
        if any(
            term in f"{candidate.get('username', '')} {candidate.get('business_name', '')}".lower()
            for term in terms
        )
    ]
    return matches[0] if len(matches) == 1 else None


async def discover_instagram_identity_for_connection(
    connection_id: str,
    *,
    persist_if_unambiguous: bool = True,
) -> Dict[str, Any]:
    conn = await _resolve_connection_by_id(connection_id)
    if not conn:
        raise RuntimeError("Conexão Instagram não encontrada.")
    client_id = str(conn.get("client_id") or "").strip()
    if not client_id:
        raise RuntimeError("Conexão sem client_id.")

    token = await ensure_valid_meta_token(
        client_id,
        connection_id=connection_id,
        platform="instagram",
        connection_type="organic",
    )
    identity = await fetch_instagram_identity(token)
    candidates = _identity_candidates(identity)
    client = await sb_get_one("clients", f"id=eq.{client_id}")
    selected = _pick_identity_candidate(candidates, client)
    source = "single_or_client_match" if selected else "ambiguous_or_missing"
    print(
        "[ig_sync][identity] "
        f"client_id={client_id} connection_id={connection_id} candidates={len(candidates)} "
        f"selected={str((selected or {}).get('ig_user_id') or '-')} source={source}"
    )
    if selected and persist_if_unambiguous:
        patch = {
            "ig_user_id": selected["ig_user_id"],
            "username": selected.get("username") or None,
            "business_id": selected.get("business_id") or None,
            "meta_user_id": str((identity.get("meta_user") or {}).get("id") or "").strip() or None,
        }
        await sb_update("meta_connections", filters={"id": f"eq.{connection_id}"}, patch=patch, returning="minimal")
        await sb_update("clients", filters={"id": f"eq.{client_id}"}, patch={"ig_user_id": patch["ig_user_id"]}, returning="minimal")
    return {
        "ok": True,
        "client_id": client_id,
        "connection_id": connection_id,
        "meta_user": identity.get("meta_user") or {},
        "instagram_accounts": candidates,
        "selected": selected,
    }


async def _run_sync_for_client_and_ig(
    *,
    client_id: str,
    connection_id: str,
    ig_user_id: str,
    access_token: str,
    limit: int,
) -> Dict[str, Any]:
    warnings: List[str] = []
    block_status: Dict[str, Dict[str, Any]] = {
        "profile": {"ok": False, "status": "pending"},
        "media": {"ok": False, "status": "pending"},
        "comments": {"ok": False, "status": "pending"},
        "insights": {"ok": False, "status": "pending"},
        "stories": {"ok": False, "status": "pending"},
    }

    profile = await fetch_profile(ig_user_id, access_token)
    block_status["profile"] = {"ok": True, "status": "ok"}

    media: List[Dict[str, Any]] = []
    try:
        media = await fetch_media_list(ig_user_id, access_token, limit=limit)
        block_status["media"] = {"ok": True, "status": "ok", "count": len(media)}
    except Exception as exc:
        block_status["media"] = {
            "ok": False,
            "status": _classify_meta_error(exc),
            "detail": str(exc)[:180],
        }
        print(
            "[ig_sync][meta_error] "
            f"block=media client_id={client_id} ig_user_id={ig_user_id} error={str(exc)[:280]}"
        )
        warnings.append("Falha parcial na listagem de mídias.")

    kpis = _empty_kpis()
    try:
        kpis = await fetch_kpis_total_value(ig_user_id, access_token)
        block_status["insights"] = {"ok": True, "status": "ok"}
    except Exception as exc:
        block_status["insights"] = {
            "ok": False,
            "status": _classify_meta_error(exc),
            "detail": str(exc)[:180],
        }
        print(
            "[ig_sync][meta_error] "
            f"block=insights client_id={client_id} ig_user_id={ig_user_id} error={str(exc)[:280]}"
        )
        warnings.append("Falha parcial em insights do perfil.")

    enriched: List[Dict[str, Any]] = []
    media_rows: List[Dict[str, Any]] = []
    comment_rows: List[Dict[str, Any]] = []
    persisted_comments = 0
    persisted_media = 0
    persisted_snapshot = False

    for m in media:
        media_id = str(m.get("id") or "").strip()
        if not media_id:
            continue

        product_type = str(m.get("media_product_type") or "FEED").upper()
        media_type = str(m.get("media_type") or "").upper()

        insights: Dict[str, Any] = {}
        try:
            insights = await fetch_media_insights(media_id, access_token, product_type)
        except Exception:
            insights = {}

        likes_fallback = int(m.get("like_count") or 0)
        comments_fallback = int(m.get("comments_count") or 0)
        if int(insights.get("likes") or 0) == 0 and likes_fallback > 0:
            insights["likes"] = likes_fallback
        if int(insights.get("comments") or 0) == 0 and comments_fallback > 0:
            insights["comments"] = comments_fallback
        if int(insights.get("total_interactions") or 0) == 0:
            fallback_interactions = int(insights.get("likes") or 0) + int(insights.get("comments") or 0)
            if fallback_interactions > 0:
                insights["total_interactions"] = fallback_interactions

        if int(m.get("comments_count") or 0) > 0:
            try:
                comments = await fetch_media_comments(media_id, access_token, limit=200)
                for c in comments:
                    comment_rows.append(
                        {
                            "client_id": client_id,
                            "connection_id": connection_id,
                            "media_id": media_id,
                            "comment_id": str(c.get("id") or ""),
                            "text": c.get("text") or "",
                            "username": c.get("username") or "",
                            "like_count": c.get("like_count"),
                            "timestamp": _normalize_meta_ts(c.get("timestamp")),
                        }
                    )
            except Exception:
                print(
                    "[ig_sync][meta_error] "
                    f"block=comments client_id={client_id} media_id={media_id} error=fetch_comments_failed"
                )

        thumb_url = m.get("thumbnail_url")
        if not thumb_url and media_type in {"IMAGE", "CAROUSEL_ALBUM"}:
            thumb_url = m.get("media_url")

        public_thumb = None
        if thumb_url:
            try:
                content, ctype = await download_image(thumb_url)
                path = f"clients/{client_id}/media/{media_id}/thumb.jpg"
                public_thumb = await sb_upload_public(path, content, ctype)
            except Exception:
                public_thumb = None

        enriched.append(
            {
                "id": media_id,
                "media_type": m.get("media_type"),
                "media_product_type": product_type,
                "caption": m.get("caption"),
                "timestamp": m.get("timestamp"),
                "permalink": m.get("permalink"),
                "insights": insights,
                "thumb_url": public_thumb
                or m.get("thumbnail_url")
                or (m.get("media_url") if media_type in {"IMAGE", "CAROUSEL_ALBUM"} else None),
            }
        )

        media_rows.append(
            {
                "client_id": client_id,
                "connection_id": connection_id,
                "media_id": media_id,
                "media_type": m.get("media_type"),
                "media_product_type": product_type,
                "caption": m.get("caption"),
                "permalink": m.get("permalink"),
                "timestamp": _normalize_meta_ts(m.get("timestamp")),
                "thumb_url": public_thumb
                or m.get("thumbnail_url")
                or (m.get("media_url") if media_type in {"IMAGE", "CAROUSEL_ALBUM"} else None),
                "media_url": m.get("media_url"),
                "thumbnail_url": m.get("thumbnail_url"),
                "insights_json": insights or {},
            }
        )

    stories: List[Dict[str, Any]] = []
    try:
        stories = await fetch_stories(ig_user_id, access_token, limit=min(limit, 50))
        for story in stories:
            story_id = str(story.get("id") or "").strip()
            if not story_id:
                continue
            story_insights: Dict[str, Any] = {}
            try:
                story_insights = await fetch_story_insights(story_id, access_token)
            except Exception as exc:
                print(
                    "[ig_sync][meta_warning] "
                    f"block=story_insights client_id={client_id} story_id={story_id} error={exc.__class__.__name__}"
                )
            media_rows.append(
                {
                    "client_id": client_id,
                    "connection_id": connection_id,
                    "media_id": story_id,
                    "media_type": story.get("media_type"),
                    "media_product_type": "STORY",
                    "caption": None,
                    "permalink": story.get("permalink"),
                    "timestamp": _normalize_meta_ts(story.get("timestamp")),
                    "thumb_url": story.get("thumbnail_url") or story.get("media_url"),
                    "media_url": story.get("media_url"),
                    "thumbnail_url": story.get("thumbnail_url"),
                    "insights_json": story_insights or {},
                }
            )
        block_status["stories"] = {"ok": True, "status": "ok", "fetched": len(stories)}
    except Exception as exc:
        block_status["stories"] = {
            "ok": False,
            "status": _classify_meta_error(exc),
            "detail": str(exc)[:180],
        }
        print(
            "[ig_sync][meta_warning] "
            f"block=stories client_id={client_id} ig_user_id={ig_user_id} error={str(exc)[:280]}"
        )
        warnings.append("Stories não ficaram disponíveis nesta atualização.")

    if comment_rows:
        rows = [r for r in comment_rows if str(r.get("comment_id") or "").strip()]
        if rows:
            try:
                await sb_upsert("ig_comments", rows, on_conflict="client_id,comment_id")
                persisted_comments = len(rows)
            except httpx.HTTPStatusError as exc:
                if exc.response is None or exc.response.status_code not in {400, 404, 409}:
                    raise
                _schema_warning("comments", client_id, connection_id, exc)
                warnings.append("Comentários não foram persistidos por incompatibilidade de schema.")

    block_status["comments"] = {
        "ok": True,
        "status": "ok",
        "fetched": len(comment_rows),
        "saved": persisted_comments,
    }

    if media_rows:
        try:
            await sb_upsert("ig_media", media_rows, on_conflict="client_id,media_id")
            persisted_media = len(media_rows)
        except httpx.HTTPStatusError as exc:
            if exc.response is None or exc.response.status_code not in {400, 404, 409}:
                raise
            body = str(exc.response.text or "").lower()
            if "connection_id" in body and ("column" in body or "schema cache" in body):
                media_rows_no_conn = []
                for row in media_rows:
                    row_copy = dict(row)
                    row_copy.pop("connection_id", None)
                    media_rows_no_conn.append(row_copy)
                await sb_upsert("ig_media", media_rows_no_conn, on_conflict="client_id,media_id")
                persisted_media = len(media_rows_no_conn)
                warnings.append("Mídias persistidas sem connection_id (schema legado).")
            else:
                _schema_warning("media", client_id, connection_id, exc)
                warnings.append("Mídias não foram persistidas por incompatibilidade de schema.")

    impressions_or_views = int(kpis.get("impressions") or kpis.get("views") or 0)

    try:
        print(
            "[ig_sync] snapshot_upsert "
            f"client_id={client_id} connection_id={connection_id} "
            f"snapshot_date={_utc_date_str()} "
            f"reach={int(kpis.get('reach') or 0)} "
            f"profile_views={int(kpis.get('profile_views') or 0)} "
            f"accounts_engaged={int(kpis.get('accounts_engaged') or 0)} "
            f"followers={int(profile.get('followers_count') or 0)}"
        )

        await sb_upsert(
            "ig_profile_snapshots",
            [
                {
                    "client_id": client_id,
                    "connection_id": connection_id,
                    "snapshot_date": _utc_date_str(),
                    "followers_count": int(profile.get("followers_count") or 0),
                    "media_count": int(profile.get("media_count") or 0),
                    "impressions_day": impressions_or_views,
                    "reach_day": int(kpis.get("reach") or 0),
                    "total_interactions_day": int(kpis.get("total_interactions") or 0),
                    "website_clicks_day": int(kpis.get("website_clicks") or 0),
                    "profile_views_day": int(kpis.get("profile_views") or 0),
                    "accounts_engaged_day": int(kpis.get("accounts_engaged") or 0),
                    "created_at": _iso_now(),
                }
            ],
            on_conflict="client_id,snapshot_date",
        )
        persisted_snapshot = True
    except httpx.HTTPStatusError as exc:
        if exc.response is None or exc.response.status_code not in {400, 404, 409}:
            raise
        _schema_warning("snapshot", client_id, connection_id, exc)
        warnings.append("Snapshot diário não foi persistido por incompatibilidade de schema.")

    return {
        "ok": True,
        "client_id": client_id,
        "profile": profile,
        "kpis": {
            "impressions": impressions_or_views,
            "reach": int(kpis.get("reach") or 0),
            "total_interactions": int(kpis.get("total_interactions") or 0),
            "website_clicks": int(kpis.get("website_clicks") or 0),
            "profile_views": int(kpis.get("profile_views") or 0),
            "accounts_engaged": int(kpis.get("accounts_engaged") or 0),
        },
        "media": enriched,
        "stories_fetched": len(stories),
        "comments_fetched": len(comment_rows),
        "comments_saved": persisted_comments,
        "media_saved": persisted_media,
        "snapshot_saved": persisted_snapshot,
        "persisted": {
            "media": persisted_media,
            "comments": persisted_comments,
            "snapshot": persisted_snapshot,
        },
        "block_status": block_status,
        "warnings": warnings,
    }


async def sync_instagram_connection(connection_id: str, limit: int = 40) -> Dict[str, Any]:
    conn = await _resolve_connection_by_id(connection_id)
    if not conn:
        raise RuntimeError("Conexão Instagram não encontrada.")

    if str(conn.get("platform") or "") != "instagram":
        raise RuntimeError("Conexão informada não é Instagram.")

    client_id = str(conn.get("client_id") or "").strip()
    if not client_id:
        raise RuntimeError("Conexão sem client_id.")

    ig_user_id = str(conn.get("ig_user_id") or "").strip()
    if not ig_user_id:
        client = await sb_get_one("clients", f"id=eq.{client_id}")
        ig_user_id = str((client or {}).get("ig_user_id") or "").strip()
    if not ig_user_id:
        ig_user_id = _env("META_IG_USER_ID")
        if ig_user_id:
            await sb_update("meta_connections", filters={"id": f"eq.{connection_id}"}, patch={"ig_user_id": ig_user_id}, returning="minimal")
            await sb_update("clients", filters={"id": f"eq.{client_id}"}, patch={"ig_user_id": ig_user_id}, returning="minimal")
            print(f"[ig_sync][identity] client_id={client_id} connection_id={connection_id} source=env")
    if not ig_user_id:
        discovered = await discover_instagram_identity_for_connection(connection_id)
        ig_user_id = str(((discovered.get("selected") or {}).get("ig_user_id")) or "").strip()
    if not ig_user_id:
        raise RuntimeError("Conta Instagram Business ainda não vinculada à página Meta.")

    print(
        "[ig_sync] start "
        f"client_id={client_id} connection_id={connection_id} ig_user_id={ig_user_id} limit={limit}"
    )

    try:
        access_token = await ensure_valid_meta_token(
            client_id,
            connection_id=connection_id,
            platform="instagram",
            connection_type="organic",
        )
        res = await _run_sync_for_client_and_ig(
            client_id=client_id,
            connection_id=connection_id,
            ig_user_id=ig_user_id,
            access_token=access_token,
            limit=limit,
        )
        await _mark_connection_success(connection_id)
        print(
            "[ig_sync] success "
            f"client_id={client_id} connection_id={connection_id} media={len(res.get('media') or [])} "
            f"comments_saved={res.get('comments_saved') or 0}"
        )
        return {**res, "connection_id": connection_id}
    except Exception as exc:
        await _mark_connection_error(connection_id, str(exc))
        print(
            "[ig_sync] error "
            f"client_id={client_id} connection_id={connection_id} error={str(exc)[:280]}"
        )
        raise


async def sync_instagram_for_client(
    client_id: str,
    limit: int = 40,
    preferred_connection_id: str | None = None,
) -> Dict[str, Any]:
    preferred_id = str(preferred_connection_id or "").strip()
    resolved = await resolve_connection_for_scope(
        client_id=client_id,
        platform="instagram",
        connection_type="organic",
        requested_connection_id=preferred_id or None,
    )
    connection_id = str(resolved.get("connection_id") or "").strip()
    if not connection_id:
        raise RuntimeError("Cliente sem conexão Instagram utilizável. Reconecte a conta.")
    selected = resolved.get("row") or {}
    source = str(resolved.get("source") or "none").strip() or "none"

    print(
        "[ig_sync] selected_connection "
        f"client_id={client_id} preferred_connection_id={preferred_id or '-'} "
        f"connection_id={connection_id} source={source} status={str(selected.get('status') or '-')}"
    )

    return await sync_instagram_connection(connection_id, limit=limit)
