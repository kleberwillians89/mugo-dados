from typing import Any, Dict, List, Tuple
import httpx
import time

META_BASE = "https://graph.facebook.com/v19.0"


def _clean_token(token: str) -> str:
    return (token or "").strip()


async def meta_get_json(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{META_BASE}{path}"
    async with httpx.AsyncClient(timeout=60) as client:
        started = time.perf_counter()
        r = await client.get(url, params=params)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        print(
            "[meta][request_done] "
            f"path={path} status={r.status_code} duration_ms={elapsed_ms}"
        )
        if r.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Meta API error {r.status_code}: {r.text}",
                request=r.request,
                response=r,
            )
        return r.json()


async def fetch_profile(ig_user_id: str, access_token: str) -> Dict[str, Any]:
    fields = "id,username,name,profile_picture_url,followers_count,media_count"
    return await meta_get_json(
        f"/{ig_user_id}",
        {"fields": fields, "access_token": _clean_token(access_token)},
    )


async def _fetch_total_value_metrics(
    ig_user_id: str, access_token: str, metrics: str
) -> Dict[str, int]:
    data = await meta_get_json(
        f"/{ig_user_id}/insights",
        {
            "metric": metrics,
            "period": "day",
            "metric_type": "total_value",
            "access_token": _clean_token(access_token),
        },
    )
    out: Dict[str, int] = {}
    for item in data.get("data", []):
        name = item.get("name")
        tv = (item.get("total_value") or {}).get("value")
        out[name] = int(tv or 0)
    return out


async def fetch_kpis_total_value(ig_user_id: str, access_token: str) -> Dict[str, int]:
    """
    KPIs do PERFIL (snapshot do dia).
    """
    base_metrics = "reach,profile_views,website_clicks,accounts_engaged,total_interactions"
    out = await _fetch_total_value_metrics(ig_user_id, access_token, base_metrics)

    views_val = 0
    try:
        vv = await _fetch_total_value_metrics(ig_user_id, access_token, "views")
        views_val = int(vv.get("views") or 0)
    except Exception:
        views_val = 0

    imp_val = 0
    if views_val == 0:
        try:
            imp = await _fetch_total_value_metrics(ig_user_id, access_token, "impressions")
            imp_val = int(imp.get("impressions") or 0)
        except Exception:
            imp_val = 0

    out["views"] = int(views_val)
    out["impressions"] = int(views_val or imp_val or 0)
    return out


async def fetch_media_list(ig_user_id: str, access_token: str, limit: int = 40) -> List[Dict[str, Any]]:
    fields = (
        "id,media_type,media_product_type,caption,timestamp,permalink,"
        "media_url,thumbnail_url,comments_count,like_count"
    )
    token = _clean_token(access_token)
    items: List[Dict[str, Any]] = []
    next_url: str | None = None

    while len(items) < limit:
        if next_url:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.get(next_url)
                if r.status_code >= 400:
                    raise httpx.HTTPStatusError(
                        f"Meta API error {r.status_code}: {r.text}",
                        request=r.request,
                        response=r,
                    )
                resp = r.json()
        else:
            resp = await meta_get_json(
                f"/{ig_user_id}/media",
                {"fields": fields, "limit": min(limit, 100), "access_token": token},
            )

        page_items = resp.get("data", []) or []
        if not page_items:
            break

        items.extend(page_items)
        paging = resp.get("paging") or {}
        next_url = paging.get("next")
        if not next_url:
            break

    return items[:limit]


def media_metrics_for(product_type: str) -> str:
    pt = (product_type or "").upper()
    if pt == "REELS":
        return (
            "views,reach,likes,comments,shares,saved,total_interactions,"
            "ig_reels_avg_watch_time,ig_reels_video_view_total_time,reels_skip_rate"
        )
    return "reach,likes,comments,shares,saved,total_interactions,profile_visits"


async def fetch_media_insights(
    media_id: str, access_token: str, product_type: str
) -> Dict[str, int]:
    metrics = media_metrics_for(product_type)
    resp = await meta_get_json(
        f"/{media_id}/insights",
        {"metric": metrics, "access_token": _clean_token(access_token)},
    )
    out: Dict[str, int] = {}
    for item in resp.get("data", []):
        name = item.get("name")
        values = item.get("values") or []
        if values and isinstance(values, list):
            out[name] = int(values[0].get("value") or 0)
        else:
            tv = (item.get("total_value") or {}).get("value")
            out[name] = int(tv or 0)
    return out


async def fetch_media_comments(media_id: str, access_token: str, limit: int = 50) -> List[Dict[str, Any]]:
    fields = "id,text,username,timestamp,like_count"
    token = _clean_token(access_token)
    items: List[Dict[str, Any]] = []
    next_url: str | None = None

    while len(items) < limit:
        if next_url:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.get(next_url)
                if r.status_code >= 400:
                    raise httpx.HTTPStatusError(
                        f"Meta API error {r.status_code}: {r.text}",
                        request=r.request,
                        response=r,
                    )
                resp = r.json()
        else:
            resp = await meta_get_json(
                f"/{media_id}/comments",
                {
                    "fields": fields,
                    "limit": min(limit, 100),
                    "access_token": token,
                },
            )

        page_items = resp.get("data", []) or []
        if not page_items:
            break

        items.extend(page_items)
        paging = resp.get("paging") or {}
        next_url = paging.get("next")
        if not next_url:
            break

    return items[:limit]


async def fetch_stories(ig_user_id: str, access_token: str, limit: int = 25) -> List[Dict[str, Any]]:
    fields = "id,media_type,media_url,thumbnail_url,timestamp,permalink"
    resp = await meta_get_json(
        f"/{ig_user_id}/stories",
        {
            "fields": fields,
            "limit": limit,
            "access_token": _clean_token(access_token),
        },
    )
    return resp.get("data", [])


async def fetch_story_insights(story_id: str, access_token: str) -> Dict[str, int]:
    resp = await meta_get_json(
        f"/{story_id}/insights",
        {
            "metric": "impressions,reach,replies,shares,total_interactions,profile_activity",
            "access_token": _clean_token(access_token),
        },
    )
    out: Dict[str, int] = {}
    for item in resp.get("data", []):
        name = str(item.get("name") or "").strip()
        values = item.get("values") or []
        if not name:
            continue
        if values and isinstance(values, list):
            out[name] = int((values[0] or {}).get("value") or 0)
        else:
            out[name] = int(((item.get("total_value") or {}).get("value")) or 0)
    return out


def _normalize_ad_account_id(ad_account_id: str) -> str:
    raw = str(ad_account_id or "").strip()
    if not raw:
        return ""
    return raw if raw.startswith("act_") else f"act_{raw}"


async def fetch_ads_account_kpis(ad_account_id: str, access_token: str) -> Dict[str, int]:
    """
    Fallback de KPIs via Marketing API (ad account insights).
    """
    act_id = _normalize_ad_account_id(ad_account_id)
    if not act_id:
        raise RuntimeError("ad_account_id ausente")

    resp = await meta_get_json(
        f"/{act_id}/insights",
        {
            "fields": "impressions,reach,clicks,actions",
            "date_preset": "last_30d",
            "access_token": _clean_token(access_token),
        },
    )
    rows = resp.get("data") or []
    row = rows[0] if rows else {}
    impressions = int(row.get("impressions") or 0)
    reach = int(row.get("reach") or 0)
    clicks = int(row.get("clicks") or 0)
    actions = row.get("actions") or []
    link_clicks = 0
    profile_views = 0
    total_interactions = 0
    if isinstance(actions, list):
        for a in actions:
            if not isinstance(a, dict):
                continue
            a_type = str(a.get("action_type") or "").strip().lower()
            a_value = int(float(a.get("value") or 0))
            if a_type in {"link_click", "outbound_click"}:
                link_clicks += a_value
            if a_type in {"onsite_conversion.profile_visit", "profile_visit"}:
                profile_views += a_value
            if a_type in {
                "post_engagement",
                "post_reaction",
                "comment",
                "post",
                "like",
                "page_engagement",
                "video_view",
            }:
                total_interactions += a_value

    website_clicks = link_clicks if link_clicks > 0 else clicks
    if total_interactions == 0:
        total_interactions = clicks
    return {
        "impressions": impressions,
        "views": impressions,
        "reach": reach,
        "profile_views": profile_views,
        "website_clicks": website_clicks,
        "accounts_engaged": 0,
        "total_interactions": total_interactions,
    }


async def fetch_first_ad_account_id(access_token: str) -> str:
    """
    Descobre a primeira conta de anúncios acessível pelo token.
    Retorna no formato act_xxx.
    """
    resp = await meta_get_json(
        "/me/adaccounts",
        {
            "fields": "id,account_id,name",
            "limit": 1,
            "access_token": _clean_token(access_token),
        },
    )
    rows = resp.get("data") or []
    if not rows:
        return ""
    row = rows[0] or {}
    raw = str(row.get("id") or row.get("account_id") or "").strip()
    return _normalize_ad_account_id(raw)


async def download_image(url: str) -> Tuple[bytes, str]:
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        ctype = r.headers.get("content-type") or "image/jpeg"
        return r.content, ctype
