"""Chamadas às APIs de TikTok (anúncios e orgânico), Pinterest (anúncios e orgânico) e Microsoft Clarity.

Cada função devolve linhas no formato de channel_daily_metrics (sem client_id), prontas para gravar.
Nada aqui grava no banco nem guarda token: isso é de services/channels.py.
"""
from __future__ import annotations

import base64
import json
import os
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import httpx

from .integration_errors import IntegrationError

TIMEOUT = 45
TIKTOK_ADS_API = "https://business-api.tiktok.com/open_api/v1.3"
TIKTOK_API = "https://open.tiktokapis.com/v2"
PINTEREST_API = "https://api.pinterest.com/v5"
CLARITY_API = "https://www.clarity.ms/export-data/api/v1/project-live-insights"

TIKTOK_SCOPES = ["user.info.basic", "user.info.stats", "video.list"]
PINTEREST_SCOPES = ["ads:read", "boards:read", "pins:read", "user_accounts:read"]
LINKEDIN_API = "https://api.linkedin.com/rest"
LINKEDIN_SCOPES = ["r_ads", "r_ads_reporting", "r_organization_admin", "r_organization_social"]


def env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def configured(provider: str) -> bool:
    keys = {"tiktok_ads": ("TIKTOK_ADS_APP_ID", "TIKTOK_ADS_APP_SECRET"), "tiktok": ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"),
            "pinterest": ("PINTEREST_CLIENT_ID", "PINTEREST_CLIENT_SECRET"),
            "linkedin": ("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"), "clarity": ()}[provider]
    return all(env(k) for k in keys)


def _fail(provider: str, message: str, status: int = 502, code: str = "CHANNEL_API_ERROR", retryable: bool = True) -> IntegrationError:
    return IntegrationError(message, status_code=status, code=code, provider=provider, retryable=retryable)


async def _json(provider: str, method: str, url: str, **kw: Any) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as http:
            res = await http.request(method, url, **kw)
    except httpx.HTTPError as exc:
        raise _fail(provider, f"Sem resposta da plataforma ({type(exc).__name__}).") from exc
    if res.status_code in (401, 403):
        raise _fail(provider, "A plataforma recusou o acesso. Reconecte a conta.", 401, "CHANNEL_REAUTH_REQUIRED", False)
    if res.status_code == 429:
        raise _fail(provider, "Limite de consultas da plataforma atingido. Tenta de novo mais tarde.", 429, "CHANNEL_RATE_LIMITED")
    try:
        body = res.json()
    except ValueError as exc:
        raise _fail(provider, f"Resposta inválida da plataforma (HTTP {res.status_code}).") from exc
    if res.status_code >= 400:
        detail = body.get("message") or (body.get("error") or {}).get("message") if isinstance(body, dict) else None
        raise _fail(provider, f"A plataforma respondeu HTTP {res.status_code}: {str(detail or '')[:160]}", 502)
    return body if isinstance(body, dict) else {"data": body}


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> Optional[int]:
    n = _num(value)
    return int(n) if n is not None else None


def _row(level: str, metric_date: str, *, account_id: str = "", entity_id: str = "", entity_name: Optional[str] = None,
         spend: Any = None, impressions: Any = None, clicks: Any = None, conversions: Any = None, metrics: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"level": level, "metric_date": metric_date, "account_id": str(account_id or ""), "entity_id": str(entity_id or ""),
            "entity_name": (str(entity_name)[:300] if entity_name else None), "spend": _num(spend), "impressions": _int(impressions),
            "clicks": _int(clicks), "conversions": _num(conversions), "metrics": metrics or {}}


# ---------------------------------------------------------------- OAuth
def authorize_url(provider: str, *, redirect_uri: str, state: str) -> str:
    if provider == "tiktok_ads":
        return "https://business-api.tiktok.com/portal/auth?" + urlencode({"app_id": env("TIKTOK_ADS_APP_ID"), "state": state, "redirect_uri": redirect_uri})
    if provider == "tiktok":
        return "https://www.tiktok.com/v2/auth/authorize/?" + urlencode({"client_key": env("TIKTOK_CLIENT_KEY"), "scope": ",".join(TIKTOK_SCOPES),
                                                                         "response_type": "code", "redirect_uri": redirect_uri, "state": state})
    if provider == "pinterest":
        return "https://www.pinterest.com/oauth/?" + urlencode({"client_id": env("PINTEREST_CLIENT_ID"), "redirect_uri": redirect_uri,
                                                                 "response_type": "code", "scope": ",".join(PINTEREST_SCOPES), "state": state})
    if provider == "linkedin":
        return "https://www.linkedin.com/oauth/v2/authorization?" + urlencode({"response_type": "code", "client_id": env("LINKEDIN_CLIENT_ID"),
                                                                                "redirect_uri": redirect_uri, "state": state, "scope": " ".join(LINKEDIN_SCOPES)})
    raise _fail(provider, "Este canal não usa autorização por login.", 400, "CHANNEL_NO_OAUTH", False)


def _linkedin_form(**data: str) -> Dict[str, str]:
    return {**data, "client_id": env("LINKEDIN_CLIENT_ID"), "client_secret": env("LINKEDIN_CLIENT_SECRET")}


def _li_head(access: str) -> Dict[str, str]:
    # Versão da API do LinkedIn (AAAAMM). Cada versão vale cerca de 1 ano: atualize LINKEDIN_API_VERSION quando vencer.
    return {"Authorization": f"Bearer {access}", "LinkedIn-Version": env("LINKEDIN_API_VERSION") or "202510", "X-Restli-Protocol-Version": "2.0.0"}


def _pinterest_basic() -> Dict[str, str]:
    raw = f"{env('PINTEREST_CLIENT_ID')}:{env('PINTEREST_CLIENT_SECRET')}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


async def exchange_code(provider: str, *, code: str, redirect_uri: str) -> Dict[str, Any]:
    """Devolve {access_token, refresh_token?, expires_in?, refresh_expires_in?, scope?, extra}."""
    if provider == "tiktok_ads":
        body = await _json(provider, "POST", f"{TIKTOK_ADS_API}/oauth2/access_token/",
                           json={"app_id": env("TIKTOK_ADS_APP_ID"), "secret": env("TIKTOK_ADS_APP_SECRET"), "auth_code": code})
        data = body.get("data") or {}
        if body.get("code") not in (0, None) or not data.get("access_token"):
            raise _fail(provider, f"O TikTok recusou a autorização: {body.get('message')}", 400, "CHANNEL_OAUTH_FAILED", False)
        return {"access_token": data["access_token"], "advertiser_ids": [str(a) for a in data.get("advertiser_ids") or []], "scope": data.get("scope")}
    if provider == "tiktok":
        data = await _json(provider, "POST", f"{TIKTOK_API}/oauth/token/", headers={"Content-Type": "application/x-www-form-urlencoded"},
                           data={"client_key": env("TIKTOK_CLIENT_KEY"), "client_secret": env("TIKTOK_CLIENT_SECRET"), "code": code,
                                 "grant_type": "authorization_code", "redirect_uri": redirect_uri})
        if not data.get("access_token"):
            raise _fail(provider, f"O TikTok recusou a autorização: {data.get('error_description') or data.get('error')}", 400, "CHANNEL_OAUTH_FAILED", False)
        return data
    if provider == "pinterest":
        data = await _json(provider, "POST", f"{PINTEREST_API}/oauth/token", headers=_pinterest_basic(),
                           data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri})
        if not data.get("access_token"):
            raise _fail(provider, "O Pinterest recusou a autorização.", 400, "CHANNEL_OAUTH_FAILED", False)
        return data
    if provider == "linkedin":
        data = await _json(provider, "POST", "https://www.linkedin.com/oauth/v2/accessToken", headers={"Content-Type": "application/x-www-form-urlencoded"},
                           data=_linkedin_form(grant_type="authorization_code", code=code, redirect_uri=redirect_uri))
        if not data.get("access_token"):
            raise _fail(provider, "O LinkedIn recusou a autorização.", 400, "CHANNEL_OAUTH_FAILED", False)
        return data
    raise _fail(provider, "Canal sem login.", 400, "CHANNEL_NO_OAUTH", False)


async def refresh_token(provider: str, token: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """TikTok orgânico (24 h) e Pinterest (30 dias) renovam pelo refresh_token. TikTok Ads não expira."""
    refresh = str(token.get("refresh_token") or "")
    if not refresh:
        return None
    if provider == "tiktok":
        return await _json(provider, "POST", f"{TIKTOK_API}/oauth/token/", headers={"Content-Type": "application/x-www-form-urlencoded"},
                           data={"client_key": env("TIKTOK_CLIENT_KEY"), "client_secret": env("TIKTOK_CLIENT_SECRET"),
                                 "grant_type": "refresh_token", "refresh_token": refresh})
    if provider == "pinterest":
        return await _json(provider, "POST", f"{PINTEREST_API}/oauth/token", headers=_pinterest_basic(),
                           data={"grant_type": "refresh_token", "refresh_token": refresh})
    if provider == "linkedin":
        return await _json(provider, "POST", "https://www.linkedin.com/oauth/v2/accessToken", headers={"Content-Type": "application/x-www-form-urlencoded"},
                           data=_linkedin_form(grant_type="refresh_token", refresh_token=refresh))
    return None


# ---------------------------------------------------------------- contas
async def account_info(provider: str, token: Dict[str, Any]) -> Tuple[str, str, Dict[str, Any]]:
    """(account_id, nome, metadata) para mostrar qual conta foi ligada."""
    access = str(token.get("access_token") or "")
    if provider == "tiktok_ads":
        body = await _json(provider, "GET", f"{TIKTOK_ADS_API}/oauth2/advertiser/get/", headers={"Access-Token": access},
                           params={"app_id": env("TIKTOK_ADS_APP_ID"), "secret": env("TIKTOK_ADS_APP_SECRET")})
        rows = (body.get("data") or {}).get("list") or []
        ids = [str(r.get("advertiser_id")) for r in rows if r.get("advertiser_id")] or list(token.get("advertiser_ids") or [])
        names = {str(r.get("advertiser_id")): r.get("advertiser_name") for r in rows}
        if not ids:
            raise _fail(provider, "Nenhuma conta de anúncios do TikTok foi autorizada.", 400, "CHANNEL_NO_ACCOUNT", False)
        return ids[0], str(names.get(ids[0]) or f"Conta {ids[0]}"), {"advertiser_ids": ids, "advertiser_names": names}
    if provider == "tiktok":
        body = await _json(provider, "GET", f"{TIKTOK_API}/user/info/", headers={"Authorization": f"Bearer {access}"},
                           params={"fields": "open_id,display_name,username"})
        user = (body.get("data") or {}).get("user") or {}
        handle = user.get("username") or user.get("display_name") or "TikTok"
        return str(user.get("open_id") or token.get("open_id") or ""), f"@{handle}" if user.get("username") else str(handle), {}
    if provider == "pinterest":
        user = await _json(provider, "GET", f"{PINTEREST_API}/user_account", headers={"Authorization": f"Bearer {access}"})
        ads = await _json(provider, "GET", f"{PINTEREST_API}/ad_accounts", headers={"Authorization": f"Bearer {access}"}, params={"page_size": 25})
        ad_ids = [str(a.get("id")) for a in ads.get("items") or [] if a.get("id")]
        name = user.get("username") or user.get("business_name") or "Pinterest"
        return str(user.get("username") or ""), f"@{name}", {"ad_account_ids": ad_ids}
    if provider == "linkedin":
        head = _li_head(access)
        ads = await _json(provider, "GET", f"{LINKEDIN_API}/adAccounts?q=search", headers=head)
        ad_ids = [str(a.get("id")) for a in ads.get("elements") or [] if a.get("id")]
        acls = await _json(provider, "GET", f"{LINKEDIN_API}/organizationAcls?q=roleAssignee&role=ADMINISTRATOR&state=APPROVED", headers=head)
        org_ids = [str(e.get("organization") or "").rsplit(":", 1)[-1] for e in acls.get("elements") or [] if e.get("organization")]
        name = "LinkedIn"
        if org_ids:
            try:
                name = str((await _json(provider, "GET", f"{LINKEDIN_API}/organizations/{org_ids[0]}", headers=head)).get("localizedName") or name)
            except IntegrationError:
                pass
        if not ad_ids and not org_ids:
            raise _fail(provider, "Nenhuma página ou conta de anúncios do LinkedIn foi autorizada.", 400, "CHANNEL_NO_ACCOUNT", False)
        return (org_ids[0] if org_ids else ad_ids[0]), name, {"ad_account_ids": ad_ids, "organization_ids": org_ids}
    raise _fail(provider, "Canal desconhecido.", 400, "CHANNEL_UNKNOWN", False)


# ---------------------------------------------------------------- coleta
def _dates(days: int) -> Tuple[str, str]:
    end = date.today()
    return (end - timedelta(days=max(1, days) - 1)).isoformat(), end.isoformat()


async def collect_tiktok_ads(token: Dict[str, Any], metadata: Dict[str, Any], days: int) -> List[Dict[str, Any]]:
    access = str(token.get("access_token") or "")
    start, end = _dates(min(days, 30))  # relatório diário do TikTok: até 30 dias por consulta
    out: List[Dict[str, Any]] = []
    for adv in metadata.get("advertiser_ids") or []:
        page = 1
        while page <= 20:
            body = await _json("tiktok_ads", "GET", f"{TIKTOK_ADS_API}/report/integrated/get/", headers={"Access-Token": access}, params={
                "advertiser_id": adv, "report_type": "BASIC", "data_level": "AUCTION_CAMPAIGN",
                "dimensions": json.dumps(["campaign_id", "stat_time_day"]),
                "metrics": json.dumps(["campaign_name", "spend", "impressions", "clicks", "conversion", "reach", "video_play_actions"]),
                "start_date": start, "end_date": end, "page": page, "page_size": 200})
            if body.get("code") not in (0, None):
                raise _fail("tiktok_ads", f"TikTok Ads: {body.get('message')}")
            data = body.get("data") or {}
            for item in data.get("list") or []:
                dim, met = item.get("dimensions") or {}, item.get("metrics") or {}
                out.append(_row("campaign", str(dim.get("stat_time_day") or "")[:10], account_id=adv, entity_id=dim.get("campaign_id"),
                                entity_name=met.get("campaign_name"), spend=met.get("spend"), impressions=met.get("impressions"),
                                clicks=met.get("clicks"), conversions=met.get("conversion"),
                                metrics={"reach": _int(met.get("reach")), "video_views": _int(met.get("video_play_actions"))}))
            info = data.get("page_info") or {}
            if page >= int(info.get("total_page") or 1):
                break
            page += 1
    return out


async def collect_tiktok(token: Dict[str, Any], metadata: Dict[str, Any], days: int) -> List[Dict[str, Any]]:
    """Orgânico: a API dá o total de hoje (seguidores, curtidas) e o acumulado de cada vídeo. Gravamos o retrato do dia."""
    access = str(token.get("access_token") or "")
    today = date.today().isoformat()
    head = {"Authorization": f"Bearer {access}"}
    user = ((await _json("tiktok", "GET", f"{TIKTOK_API}/user/info/", headers=head,
                         params={"fields": "open_id,follower_count,following_count,likes_count,video_count"})).get("data") or {}).get("user") or {}
    out = [_row("account", today, account_id=user.get("open_id") or "", metrics={
        "followers": _int(user.get("follower_count")), "likes": _int(user.get("likes_count")), "videos": _int(user.get("video_count"))})]
    fields = "id,title,create_time,view_count,like_count,comment_count,share_count,share_url"
    cursor, pages = None, 0
    while pages < 5:
        payload: Dict[str, Any] = {"max_count": 20}
        if cursor:
            payload["cursor"] = cursor
        data = (await _json("tiktok", "POST", f"{TIKTOK_API}/video/list/", headers={**head, "Content-Type": "application/json"},
                            params={"fields": fields}, json=payload)).get("data") or {}
        for v in data.get("videos") or []:
            out.append(_row("content", today, account_id=user.get("open_id") or "", entity_id=v.get("id"), entity_name=v.get("title") or "Vídeo",
                            impressions=v.get("view_count"), metrics={"views": _int(v.get("view_count")), "likes": _int(v.get("like_count")),
                                                                      "comments": _int(v.get("comment_count")), "shares": _int(v.get("share_count")),
                                                                      "url": v.get("share_url"), "created_at": v.get("create_time")}))
        if not data.get("has_more"):
            break
        cursor, pages = data.get("cursor"), pages + 1
    return out


async def collect_pinterest(token: Dict[str, Any], metadata: Dict[str, Any], days: int) -> List[Dict[str, Any]]:
    """Orgânico (provider pinterest) e anúncios (provider pinterest_ads) com a mesma autorização."""
    access = str(token.get("access_token") or "")
    head = {"Authorization": f"Bearer {access}"}
    start, end = _dates(min(days, 90))
    out: List[Dict[str, Any]] = []
    body = await _json("pinterest", "GET", f"{PINTEREST_API}/user_account/analytics", headers=head, params={
        "start_date": start, "end_date": end, "metric_types": "IMPRESSION,SAVE,PIN_CLICK,OUTBOUND_CLICK,ENGAGEMENT"})
    for day in ((body.get("all") or {}).get("daily_metrics") or []):
        m = day.get("metrics") or {}
        if day.get("data_status") not in (None, "READY"):
            continue
        out.append({**_row("account", str(day.get("date")), impressions=m.get("IMPRESSION"), clicks=m.get("OUTBOUND_CLICK"),
                           metrics={"saves": _int(m.get("SAVE")), "pin_clicks": _int(m.get("PIN_CLICK")), "engagement": _int(m.get("ENGAGEMENT"))}),
                    "provider": "pinterest"})
    for ad_id in metadata.get("ad_account_ids") or []:
        rows = await _json("pinterest", "GET", f"{PINTEREST_API}/ad_accounts/{ad_id}/analytics", headers=head, params={
            "start_date": start, "end_date": end, "granularity": "DAY",
            "columns": "SPEND_IN_DOLLAR,IMPRESSION_1,CLICKTHROUGH_1,TOTAL_CONVERSIONS"})
        for r in rows.get("data") if isinstance(rows.get("data"), list) else []:
            out.append({**_row("account", str(r.get("DATE"))[:10], account_id=ad_id, spend=r.get("SPEND_IN_DOLLAR"), impressions=r.get("IMPRESSION_1"),
                               clicks=r.get("CLICKTHROUGH_1"), conversions=r.get("TOTAL_CONVERSIONS")), "provider": "pinterest_ads"})
    return out


def _li_date(d: Dict[str, Any]) -> str:
    return f"{int(d.get('year')):04d}-{int(d.get('month')):02d}-{int(d.get('day')):02d}"


async def collect_linkedin(token: Dict[str, Any], metadata: Dict[str, Any], days: int) -> List[Dict[str, Any]]:
    """Anúncios (linkedin_ads, por campanha e dia) e página (linkedin, por dia) com a mesma autorização."""
    from urllib.parse import quote
    head = _li_head(str(token.get("access_token") or ""))
    start, end = date.fromisoformat(_dates(min(days, 90))[0]), date.today()
    out: List[Dict[str, Any]] = []
    rng = (f"(start:(year:{start.year},month:{start.month},day:{start.day}),"
           f"end:(year:{end.year},month:{end.month},day:{end.day}))")
    for ad_id in metadata.get("ad_account_ids") or []:
        urn = quote(f"urn:li:sponsoredAccount:{ad_id}", safe="")
        url = (f"{LINKEDIN_API}/adAnalytics?q=analytics&pivot=CAMPAIGN&timeGranularity=DAILY&dateRange={rng}&accounts=List({urn})"
               "&fields=costInLocalCurrency,impressions,clicks,externalWebsiteConversions,dateRange,pivotValues")
        for e in (await _json("linkedin", "GET", url, headers=head)).get("elements") or []:
            camp = str((e.get("pivotValues") or [""])[0]).rsplit(":", 1)[-1]
            out.append({**_row("campaign", _li_date((e.get("dateRange") or {}).get("start") or {}), account_id=ad_id, entity_id=camp,
                               entity_name=f"Campanha {camp}", spend=e.get("costInLocalCurrency"), impressions=e.get("impressions"),
                               clicks=e.get("clicks"), conversions=e.get("externalWebsiteConversions")), "provider": "linkedin_ads"})
    start_ms = int(datetime_from(start).timestamp() * 1000)
    end_ms = int(datetime_from(end + timedelta(days=1)).timestamp() * 1000)
    for org in metadata.get("organization_ids") or []:
        urn = quote(f"urn:li:organization:{org}", safe="")
        url = (f"{LINKEDIN_API}/organizationalEntityShareStatistics?q=organizationalEntity&organizationalEntity={urn}"
               f"&timeIntervals=(timeRange:(start:{start_ms},end:{end_ms}),timeGranularityType:DAY)")
        for e in (await _json("linkedin", "GET", url, headers=head)).get("elements") or []:
            s = e.get("totalShareStatistics") or {}
            day = date.fromtimestamp(int(((e.get("timeRange") or {}).get("start") or 0)) / 1000).isoformat()
            out.append({**_row("account", day, account_id=org, impressions=s.get("impressionCount"), clicks=s.get("clickCount"),
                               metrics={"likes": _int(s.get("likeCount")), "comments": _int(s.get("commentCount")),
                                        "shares": _int(s.get("shareCount")), "engagement": _num(s.get("engagement"))}), "provider": "linkedin"})
        try:
            size = await _json("linkedin", "GET", f"{LINKEDIN_API}/networkSizes/{urn}?edgeType=COMPANY_FOLLOWED_BY_MEMBER", headers=head)
            out.append({**_row("content", end.isoformat(), account_id=org, entity_id="followers", entity_name="Seguidores da página",
                               metrics={"followers": _int(size.get("firstDegreeSize"))}), "provider": "linkedin"})
        except IntegrationError:
            pass
    return out


def datetime_from(d: date):
    from datetime import datetime, timezone
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


CLARITY_KEYS = {"Traffic": ("totalSessionCount", "distinctUserCount", "pagesPerSessionPercentage"),
                "ScrollDepth": ("averageScrollDepth",), "EngagementTime": ("totalTime", "activeTime"),
                "DeadClickCount": ("sessionsWithMetricPercentage",), "RageClickCount": ("sessionsWithMetricPercentage",),
                "QuickbackClick": ("sessionsWithMetricPercentage",), "ExcessiveScroll": ("sessionsWithMetricPercentage",),
                "ScriptErrorCount": ("sessionsWithMetricPercentage",), "ErrorClickCount": ("sessionsWithMetricPercentage",)}


def parse_clarity(payload: Any, metric_date: str, *, by_url: bool = False) -> List[Dict[str, Any]]:
    """O Clarity devolve [{metricName, information:[...]}]. Sem dimensão: 1 linha do site; com URL: 1 por página."""
    groups: Dict[str, Dict[str, Any]] = {}
    for block in payload if isinstance(payload, list) else []:
        name = str(block.get("metricName") or "")
        for info in block.get("information") or []:
            key = str(info.get("Url") or info.get("URL") or "") if by_url else "site"
            if by_url and not key:
                continue
            slot = groups.setdefault(key, {})
            for field in CLARITY_KEYS.get(name, ()):
                if field in info:
                    slot[f"{name}.{field}" if name != "Traffic" else field] = _num(info.get(field))
    out = []
    for key, m in groups.items():
        out.append(_row("page" if by_url else "account", metric_date, entity_id=key if by_url else "", entity_name=key if by_url else None,
                        metrics={k: v for k, v in m.items() if v is not None}))
    if by_url:  # só as páginas com mais sessões
        out.sort(key=lambda r: -(r["metrics"].get("totalSessionCount") or 0))
        out = out[:25]
    return out


async def collect_clarity(token: Dict[str, Any], metadata: Dict[str, Any], days: int) -> List[Dict[str, Any]]:
    """API de exportação do Clarity: poucas consultas por dia e só as últimas 24 h. 2 consultas por coleta."""
    head = {"Authorization": f"Bearer {token.get('access_token')}", "Content-Type": "application/json"}
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    site = await _clarity_get(head, {"numOfDays": 1})
    pages = await _clarity_get(head, {"numOfDays": 1, "dimension1": "URL"})
    return parse_clarity(site, yesterday) + parse_clarity(pages, yesterday, by_url=True)


async def _clarity_get(head: Dict[str, str], params: Dict[str, Any]) -> Any:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as http:
            res = await http.get(CLARITY_API, headers=head, params=params)
    except httpx.HTTPError as exc:
        raise _fail("clarity", f"Sem resposta do Clarity ({type(exc).__name__}).") from exc
    if res.status_code in (401, 403):
        raise _fail("clarity", "O Clarity recusou o token. Gere um novo em Configurações > Exportação de dados.", 401, "CHANNEL_REAUTH_REQUIRED", False)
    if res.status_code == 429:
        raise _fail("clarity", "Limite diário de consultas do Clarity atingido.", 429, "CHANNEL_RATE_LIMITED")
    if res.status_code >= 400:
        raise _fail("clarity", f"O Clarity respondeu HTTP {res.status_code}.")
    return res.json()


COLLECTORS = {"tiktok_ads": collect_tiktok_ads, "tiktok": collect_tiktok, "pinterest": collect_pinterest, "linkedin": collect_linkedin,
              "clarity": collect_clarity}
