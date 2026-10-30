"""Creator Intelligence: adaptadores das fontes externas e cálculo de engajamento.

Fontes, em ordem de preferência:
- Meta Business Discovery (grátis, token Meta da própria empresa): perfis
  Instagram profissionais (Business/Criador) a partir do @.
- YouTube Data API v3 (grátis até a cota diária): canais por @ ou busca.
- Apify (créditos, com teto mensal): descoberta por hashtag e TikTok.

Regra de qualidade: métrica ausente vira None e entra em missing_fields;
nada é estimado ou preenchido por aproximação.
"""
import os
import re
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .integration_errors import IntegrationError
from .meta_config import META_GRAPH_BASE_URL

NETWORKS = ("instagram", "youtube", "tiktok")
SAMPLE_POSTS = 12
YOUTUBE_BASE = "https://www.googleapis.com/youtube/v3"
APIFY_BASE = "https://api.apify.com/v2"

_HANDLE_PATTERNS = {
    "instagram": re.compile(r"^[a-z0-9._]{1,30}$"),
    "youtube": re.compile(r"^[a-z0-9._-]{3,100}$"),
    "tiktok": re.compile(r"^[a-z0-9._]{2,24}$"),
}
_URL_PREFIX = re.compile(
    r"^(https?://)?(www\.|m\.)?(instagram\.com|youtube\.com|tiktok\.com)/", re.IGNORECASE
)


def normalize_handle(network: str, raw: str) -> str:
    if network not in NETWORKS:
        raise ValueError("Rede não suportada.")
    handle = _URL_PREFIX.sub("", str(raw or "").strip())
    handle = handle.split("?", 1)[0].strip("/").split("/", 1)[0]
    handle = handle.lstrip("@").strip().lower()
    if not _HANDLE_PATTERNS[network].fullmatch(handle):
        raise ValueError("Informe um @ válido para a rede selecionada.")
    return handle


def _int_or_none(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _avg(values: List[Optional[int]]) -> Optional[float]:
    present = [v for v in values if v is not None]
    return round(mean(present), 2) if present else None


def compute_engagement(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Métricas agregadas com metodologia explícita sobre os posts recentes."""
    network = profile["network"]
    posts = (profile.get("posts") or [])[:SAMPLE_POSTS]
    followers = _int_or_none(profile.get("followers"))
    avg_likes = _avg([p.get("likes") for p in posts])
    avg_comments = _avg([p.get("comments") for p in posts])
    avg_views = _avg([p.get("views") for p in posts])
    rate: Optional[float] = None
    method: Optional[str] = None
    if network == "instagram":
        if followers and avg_likes is not None and avg_comments is not None:
            rate = round((avg_likes + avg_comments) / followers * 100, 2)
        method = f"(média de curtidas + média de comentários) ÷ seguidores × 100, últimos {len(posts)} posts"
    else:
        rated = [p for p in posts if p.get("views") and p.get("likes") is not None and p.get("comments") is not None]
        if rated:
            interactions = sum(p["likes"] + p["comments"] for p in rated)
            rate = round(interactions / sum(p["views"] for p in rated) * 100, 2)
        method = f"(curtidas + comentários) ÷ visualizações × 100, últimos {len(rated)} vídeos com dados"
    result = {
        "followers": followers,
        "avg_likes": avg_likes,
        "avg_comments": avg_comments,
        "avg_views": avg_views,
        "engagement_rate": rate,
        "engagement_method": method if posts else None,
        "sample_size": len(posts),
    }
    expected = ["followers", "avg_likes", "avg_comments", "engagement_rate"]
    if network != "instagram":
        expected.append("avg_views")
    result["missing_fields"] = [field for field in expected if result[field] is None]
    return result


# ---------------------------------------------------------------- Meta


def _meta_error(response: httpx.Response) -> IntegrationError:
    try:
        error = (response.json() or {}).get("error") or {}
    except ValueError:
        error = {}
    code = _int_or_none(error.get("code"))
    if code == 190:
        return IntegrationError(
            "A conexão Meta da empresa expirou. Reconecte em Integrações.",
            status_code=401, code="META_REAUTH_REQUIRED", provider="meta",
        )
    if code in {4, 17, 32, 613}:
        return IntegrationError(
            "Limite de consultas da Meta atingido para esta empresa. Tente novamente em alguns minutos.",
            status_code=429, code="META_RATE_LIMITED", provider="meta", retryable=True,
        )
    if code in {10, 200}:
        return IntegrationError(
            "A conexão Meta da empresa não tem permissão para consultar outros perfis.",
            status_code=403, code="META_PERMISSION_MISSING", provider="meta",
        )
    if code in {100, 110}:
        return IntegrationError(
            "Perfil não encontrado ou não é uma conta profissional (Business/Criador) do Instagram.",
            status_code=404, code="CREATOR_NOT_FOUND", provider="meta",
        )
    return IntegrationError(
        "A Meta não respondeu à consulta do perfil.",
        status_code=502, code="META_UPSTREAM_ERROR", provider="meta", retryable=True,
    )


async def meta_business_discovery(ig_user_id: str, access_token: str, username: str) -> Dict[str, Any]:
    fields = (
        f"business_discovery.username({username})"
        "{id,username,name,biography,profile_picture_url,followers_count,media_count,"
        f"media.limit({SAMPLE_POSTS}){{id,like_count,comments_count,media_type,media_product_type,permalink,timestamp}}}}"
    )
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{META_GRAPH_BASE_URL}/{ig_user_id}",
            params={"fields": fields, "access_token": access_token},
        )
    if response.status_code >= 400:
        raise _meta_error(response)
    data = (response.json() or {}).get("business_discovery") or {}
    if not data:
        raise IntegrationError(
            "Perfil não encontrado ou não é uma conta profissional (Business/Criador) do Instagram.",
            status_code=404, code="CREATOR_NOT_FOUND", provider="meta",
        )
    handle = str(data.get("username") or username).lower()
    return {
        "network": "instagram",
        "handle": handle,
        "external_id": str(data.get("id") or "") or None,
        "display_name": data.get("name"),
        "profile_url": f"https://www.instagram.com/{handle}/",
        "avatar_url": data.get("profile_picture_url"),
        "biography": data.get("biography"),
        "followers": _int_or_none(data.get("followers_count")),
        "media_count": _int_or_none(data.get("media_count")),
        "source": "meta_business_discovery",
        "posts": [
            {
                "id": item.get("id"),
                "url": item.get("permalink"),
                "timestamp": item.get("timestamp"),
                "type": item.get("media_product_type") or item.get("media_type"),
                # like_count some quando o criador oculta curtidas: fica None.
                "likes": _int_or_none(item.get("like_count")),
                "comments": _int_or_none(item.get("comments_count")),
                "views": None,
            }
            for item in ((data.get("media") or {}).get("data") or [])
        ],
    }


# ---------------------------------------------------------------- YouTube


def youtube_api_key() -> str:
    key = (os.getenv("YOUTUBE_API_KEY") or "").strip()
    if not key:
        raise IntegrationError(
            "YouTube não configurado: defina YOUTUBE_API_KEY no backend.",
            status_code=503, code="YOUTUBE_NOT_CONFIGURED", provider="youtube",
        )
    return key


async def _youtube_get(client: httpx.AsyncClient, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    response = await client.get(f"{YOUTUBE_BASE}/{path}", params={**params, "key": youtube_api_key()})
    if response.status_code == 403:
        raise IntegrationError(
            "Cota diária do YouTube esgotada ou chave sem permissão.",
            status_code=429, code="YOUTUBE_QUOTA", provider="youtube", retryable=True,
        )
    if response.status_code >= 400:
        raise IntegrationError(
            "O YouTube não respondeu à consulta.",
            status_code=502, code="YOUTUBE_UPSTREAM_ERROR", provider="youtube", retryable=True,
        )
    return response.json() or {}


def _youtube_channel_profile(channel: Dict[str, Any]) -> Dict[str, Any]:
    snippet = channel.get("snippet") or {}
    stats = channel.get("statistics") or {}
    custom = str(snippet.get("customUrl") or "").lstrip("@").lower()
    handle = custom or str(channel.get("id") or "").lower()
    return {
        "network": "youtube",
        "handle": handle,
        "external_id": channel.get("id"),
        "display_name": snippet.get("title"),
        "profile_url": f"https://www.youtube.com/@{custom}" if custom else f"https://www.youtube.com/channel/{channel.get('id')}",
        "avatar_url": ((snippet.get("thumbnails") or {}).get("default") or {}).get("url"),
        "biography": snippet.get("description"),
        "followers": None if stats.get("hiddenSubscriberCount") else _int_or_none(stats.get("subscriberCount")),
        "media_count": _int_or_none(stats.get("videoCount")),
        "source": "youtube_data_api",
        "posts": [],
    }


async def youtube_channel(handle: str) -> Tuple[Dict[str, Any], int]:
    """Canal + últimos vídeos. Retorna (perfil, unidades de cota gastas)."""
    async with httpx.AsyncClient(timeout=30) as client:
        data = await _youtube_get(client, "channels", {"part": "snippet,statistics,contentDetails", "forHandle": f"@{handle}"})
        items = data.get("items") or []
        if not items:
            raise IntegrationError("Canal do YouTube não encontrado.", status_code=404, code="CREATOR_NOT_FOUND", provider="youtube")
        channel = items[0]
        profile = _youtube_channel_profile(channel)
        units = 1
        uploads = ((channel.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
        if uploads:
            playlist = await _youtube_get(client, "playlistItems", {"part": "contentDetails", "playlistId": uploads, "maxResults": SAMPLE_POSTS})
            units += 1
            ids = [((i.get("contentDetails") or {}).get("videoId")) for i in playlist.get("items") or []]
            ids = [i for i in ids if i]
            if ids:
                videos = await _youtube_get(client, "videos", {"part": "statistics,snippet", "id": ",".join(ids)})
                units += 1
                profile["posts"] = [
                    {
                        "id": v.get("id"),
                        "url": f"https://www.youtube.com/watch?v={v.get('id')}",
                        "timestamp": (v.get("snippet") or {}).get("publishedAt"),
                        "type": "video",
                        "likes": _int_or_none((v.get("statistics") or {}).get("likeCount")),
                        "comments": _int_or_none((v.get("statistics") or {}).get("commentCount")),
                        "views": _int_or_none((v.get("statistics") or {}).get("viewCount")),
                    }
                    for v in videos.get("items") or []
                ]
    return profile, units


async def youtube_search(query: str, limit: int) -> Tuple[List[Dict[str, Any]], int]:
    """Busca canais (search.list custa 100 unidades). Sem vídeos: engajamento só no refresh."""
    async with httpx.AsyncClient(timeout=30) as client:
        found = await _youtube_get(client, "search", {
            "part": "snippet", "type": "channel", "q": query, "maxResults": limit,
            "regionCode": "BR", "relevanceLanguage": "pt",
        })
        ids = [((i.get("id") or {}).get("channelId")) for i in found.get("items") or []]
        ids = [i for i in ids if i]
        if not ids:
            return [], 100
        channels = await _youtube_get(client, "channels", {"part": "snippet,statistics", "id": ",".join(ids)})
    return [_youtube_channel_profile(c) for c in channels.get("items") or []], 101


# ---------------------------------------------------------------- Apify


def apify_token() -> str:
    token = (os.getenv("APIFY_TOKEN") or "").strip()
    if not token:
        raise IntegrationError(
            "Apify não configurada: defina APIFY_TOKEN no backend.",
            status_code=503, code="APIFY_NOT_CONFIGURED", provider="apify",
        )
    return token


def apify_actor(kind: str) -> str:
    defaults = {
        "instagram_hashtag": ("APIFY_INSTAGRAM_HASHTAG_ACTOR", "apify~instagram-hashtag-scraper"),
        "tiktok": ("APIFY_TIKTOK_ACTOR", "clockworks~tiktok-scraper"),
    }
    env, default = defaults[kind]
    return (os.getenv(env) or "").strip() or default


async def apify_run(actor: str, run_input: Dict[str, Any], *, max_items: int, max_charge_usd: float) -> Tuple[List[Dict[str, Any]], Optional[float]]:
    """Executa o Actor, espera terminar e devolve (itens, custo real em US$ quando informado)."""
    headers = {"Authorization": f"Bearer {apify_token()}"}
    async with httpx.AsyncClient(timeout=200) as client:
        response = await client.post(
            f"{APIFY_BASE}/acts/{actor}/runs",
            params={"waitForFinish": 120, "maxItems": max_items, "maxTotalChargeUsd": f"{max_charge_usd:.2f}"},
            json=run_input, headers=headers,
        )
        if response.status_code >= 400:
            raise IntegrationError(
                "A Apify recusou a execução. Verifique o token, o Actor e os créditos.",
                status_code=502, code="APIFY_RUN_REJECTED", provider="apify",
            )
        run = (response.json() or {}).get("data") or {}
        for _ in range(2):
            if run.get("status") not in {"READY", "RUNNING"}:
                break
            polled = await client.get(f"{APIFY_BASE}/actor-runs/{run.get('id')}", params={"waitForFinish": 60}, headers=headers)
            run = (polled.json() or {}).get("data") or run
        cost = run.get("usageTotalUsd")
        cost = float(cost) if isinstance(cost, (int, float)) else None
        if run.get("status") != "SUCCEEDED":
            raise IntegrationError(
                f"A pesquisa na Apify não terminou (status {run.get('status') or 'desconhecido'}).",
                status_code=504, code="APIFY_RUN_INCOMPLETE", provider="apify", retryable=True,
                diagnostics={"cost_usd": cost},
            )
        items = await client.get(
            f"{APIFY_BASE}/datasets/{run.get('defaultDatasetId')}/items",
            params={"clean": "true", "limit": max_items}, headers=headers,
        )
        data = items.json() if items.status_code < 400 else []
    return (data if isinstance(data, list) else []), cost


def group_instagram_hashtag_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Posts da hashtag agrupados por autor. Seguidores não vêm nesse Actor."""
    by_author: Dict[str, Dict[str, Any]] = {}
    for item in items:
        handle = str(item.get("ownerUsername") or "").lower()
        if not _HANDLE_PATTERNS["instagram"].fullmatch(handle):
            continue
        profile = by_author.setdefault(handle, {
            "network": "instagram", "handle": handle, "external_id": item.get("ownerId"),
            "display_name": item.get("ownerFullName"), "profile_url": f"https://www.instagram.com/{handle}/",
            "avatar_url": None, "biography": None, "followers": None, "media_count": None,
            "source": "apify_instagram_hashtag", "posts": [],
        })
        likes = _int_or_none(item.get("likesCount"))
        profile["posts"].append({
            "id": item.get("id"), "url": item.get("url"), "timestamp": item.get("timestamp"),
            "type": item.get("type"),
            # O Actor devolve -1 quando a curtida está oculta.
            "likes": likes if likes is not None and likes >= 0 else None,
            "comments": _int_or_none(item.get("commentsCount")),
            "views": _int_or_none(item.get("videoViewCount") or item.get("videoPlayCount")),
        })
    return list(by_author.values())


def group_tiktok_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_author: Dict[str, Dict[str, Any]] = {}
    for item in items:
        author = item.get("authorMeta") or {}
        handle = str(author.get("name") or "").lower()
        if not _HANDLE_PATTERNS["tiktok"].fullmatch(handle):
            continue
        profile = by_author.setdefault(handle, {
            "network": "tiktok", "handle": handle, "external_id": str(author.get("id") or "") or None,
            "display_name": author.get("nickName"), "profile_url": f"https://www.tiktok.com/@{handle}",
            "avatar_url": author.get("avatar"), "biography": author.get("signature"),
            "followers": _int_or_none(author.get("fans")), "media_count": _int_or_none(author.get("video")),
            "source": "apify_tiktok", "posts": [],
        })
        profile["posts"].append({
            "id": item.get("id"), "url": item.get("webVideoUrl"), "timestamp": item.get("createTimeISO"),
            "type": "video",
            "likes": _int_or_none(item.get("diggCount")),
            "comments": _int_or_none(item.get("commentCount")),
            "views": _int_or_none(item.get("playCount")),
        })
    return list(by_author.values())
