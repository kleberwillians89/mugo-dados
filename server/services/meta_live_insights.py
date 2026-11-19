"""Leitura ao vivo (somente GET) da conta Meta Ads para a tela Meta no padrão da Mídia On.

O que a sincronização diária não guarda e a tela precisa:
- campanhas com status, verba e resultado do período (vendas, receita, ROAS, leads);
- qualidade dos anúncios (rankings de qualidade, engajamento e conversão da Meta);
- vídeo (ThruPlay e retenção em 25/50/75/100%);
- prévia do criativo (miniatura, título e texto) do anúncio que mais gastou em cada campanha;
- quebras do período: idade e gênero, posicionamento, região e dispositivo;
- "O que fazer agora": regras simples e explicáveis sobre esses números (nada inventado).

Nada é escrito na Meta. Cache de 15 minutos por empresa e período, para a tela não estourar o limite da API.
Também diz quais funções do MUGOVERSO estão liberadas pelas permissões que a conexão recebeu.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .studio_calendar import StudioError

CACHE_TTL = 900
_CACHE: Dict[Tuple[str, str, str], Tuple[float, Dict[str, Any]]] = {}

PURCHASE_TYPES = ("omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase", "onsite_web_purchase")
LEAD_TYPES = ("lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead")
RANK_SCORE = {"ABOVE_AVERAGE": 2, "AVERAGE": 1, "BELOW_AVERAGE_35": 0, "BELOW_AVERAGE_20": -1, "BELOW_AVERAGE_10": -2}
RANK_LABEL = {2: "acima da média", 1: "na média", 0: "abaixo da média", -1: "abaixo da média", -2: "bem abaixo da média"}
STATUS_LABEL = {"ACTIVE": "Ativa", "PAUSED": "Pausada", "CAMPAIGN_PAUSED": "Pausada", "ARCHIVED": "Arquivada",
                "IN_PROCESS": "Em análise", "WITH_ISSUES": "Com problema", "PENDING_REVIEW": "Em análise", "DISAPPROVED": "Reprovada"}
INSIGHT_FIELDS = "spend,impressions,reach,clicks,ctr,cpm,frequency,actions,action_values,purchase_roas"


# ------------------------------------------------------------------ números

def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _action(rows: Any, types: Iterable[str]) -> float:
    """Primeiro tipo de ação encontrado, na ordem de preferência (evita somar a mesma compra duas vezes)."""
    found = {str(r.get("action_type")): _num(r.get("value")) for r in rows or [] if isinstance(r, dict)}
    for kind in types:
        if kind in found:
            return found[kind]
    return 0.0


def results(row: Dict[str, Any]) -> Dict[str, float]:
    spend = _num(row.get("spend"))
    purchases = _action(row.get("actions"), PURCHASE_TYPES)
    revenue = _action(row.get("action_values"), PURCHASE_TYPES)
    leads = _action(row.get("actions"), LEAD_TYPES)
    return {
        "spend": round(spend, 2), "impressions": _num(row.get("impressions")), "reach": _num(row.get("reach")),
        "clicks": _num(row.get("clicks")), "ctr": round(_num(row.get("ctr")), 2), "cpm": round(_num(row.get("cpm")), 2),
        "frequency": round(_num(row.get("frequency")), 2), "purchases": purchases, "revenue": round(revenue, 2),
        "roas": round(revenue / spend, 2) if spend and revenue else 0.0, "leads": leads,
        "cost_per_purchase": round(spend / purchases, 2) if purchases else None,
        "cost_per_lead": round(spend / leads, 2) if leads else None,
    }


def _video(row: Dict[str, Any]) -> Optional[Dict[str, float]]:
    plays = _action(row.get("video_play_actions"), ("video_view",))
    if not plays:
        return None
    pick = lambda key: _action(row.get(key), ("video_view",))  # noqa: E731
    thru = pick("video_thruplay_watched_actions")
    return {"plays": plays, "thruplays": thru, "p25": round(pick("video_p25_watched_actions") / plays * 100, 1),
            "p50": round(pick("video_p50_watched_actions") / plays * 100, 1),
            "p75": round(pick("video_p75_watched_actions") / plays * 100, 1),
            "p100": round(pick("video_p100_watched_actions") / plays * 100, 1),
            "cost_per_thruplay": round(_num(row.get("spend")) / thru, 2) if thru else None}


def _rank(ads: List[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    """Ranking da campanha = média dos anúncios ponderada pelo gasto (a Meta só dá por anúncio)."""
    scored = [(RANK_SCORE[a[key]], _num(a.get("spend"))) for a in ads if a.get(key) in RANK_SCORE]
    if not scored:
        return None
    weight = sum(w for _, w in scored) or len(scored)
    score = round(sum(s * (w or 1) for s, w in scored) / weight)
    return {"score": score, "label": RANK_LABEL[max(-2, min(2, score))]}


def build_breakdown(rows: List[Dict[str, Any]], keys: Tuple[str, ...]) -> List[Dict[str, Any]]:
    total_spend = sum(_num(r.get("spend")) for r in rows) or 0.0
    total_buy = sum(_action(r.get("actions"), PURCHASE_TYPES) for r in rows) or 0.0
    grouped: Dict[str, Dict[str, float]] = {}
    for row in rows:
        label = " · ".join(str(row.get(k) or "—") for k in keys)
        item = grouped.setdefault(label, {"spend": 0.0, "purchases": 0.0, "revenue": 0.0, "impressions": 0.0})
        item["spend"] += _num(row.get("spend"))
        item["purchases"] += _action(row.get("actions"), PURCHASE_TYPES)
        item["revenue"] += _action(row.get("action_values"), PURCHASE_TYPES)
        item["impressions"] += _num(row.get("impressions"))
    out = []
    for label, item in grouped.items():
        out.append({"label": label, "spend": round(item["spend"], 2), "purchases": item["purchases"],
                    "revenue": round(item["revenue"], 2),
                    "spend_share": round(item["spend"] / total_spend * 100, 1) if total_spend else 0.0,
                    "purchase_share": round(item["purchases"] / total_buy * 100, 1) if total_buy else 0.0,
                    "roas": round(item["revenue"] / item["spend"], 2) if item["spend"] and item["revenue"] else 0.0,
                    "cost_per_purchase": round(item["spend"] / item["purchases"], 2) if item["purchases"] else None})
    return sorted(out, key=lambda r: -r["spend"])[:12]


# ------------------------------------------------------------------ "o que fazer agora"

def recommendations(campaigns: List[Dict[str, Any]], ads: List[Dict[str, Any]], age: List[Dict[str, Any]],
                    account: Dict[str, float]) -> List[Dict[str, Any]]:
    """Regras simples, cada uma mostra o número que a disparou. No máximo 4."""
    out: List[Dict[str, Any]] = []
    active_ads = [a for a in ads if _num(a.get("spend")) > 0]
    ctrs = sorted(_num(a.get("ctr")) for a in active_ads if _num(a.get("impressions")) >= 1000)
    median_ctr = ctrs[len(ctrs) // 2] if ctrs else 0.0
    for ad in sorted(active_ads, key=lambda a: -_num(a.get("spend"))):
        freq, ctr = _num(ad.get("frequency")), _num(ad.get("ctr"))
        if freq >= 3.5 and median_ctr and ctr < median_ctr * 0.7:
            out.append({"kind": "fatigue", "tone": "bad", "title": "Criativo cansado",
                        "text": f"{ad.get('ad_name') or 'Anúncio'}: frequência {freq:.1f} e CTR {ctr:.2f}% (a mediana da conta é {median_ctr:.2f}%).",
                        "campaign_id": ad.get("campaign_id"), "action": "creatives"})
            break
    if account.get("roas"):
        for c in sorted(campaigns, key=lambda c: -c["metrics"]["roas"]):
            m = c["metrics"]
            if c["status"] == "ACTIVE" and m["spend"] >= account["spend"] * 0.05 and m["roas"] >= account["roas"] * 1.3:
                out.append({"kind": "scale", "tone": "ok", "title": "Pode escalar",
                            "text": f"{c['name']}: ROAS {m['roas']:.2f}, acima da conta ({account['roas']:.2f}).",
                            "campaign_id": c["id"], "action": "budget"})
                break
    for bucket in age:
        if bucket["spend_share"] >= 15 and bucket["spend_share"] - bucket["purchase_share"] >= 15:
            out.append({"kind": "audience", "tone": "warn", "title": "Público",
                        "text": f"{bucket['label']} leva {bucket['spend_share']:.0f}% da verba e traz {bucket['purchase_share']:.0f}% das vendas.",
                        "action": "breakdown"})
            break
    for c in campaigns:
        q = c.get("quality") or {}
        if c["status"] == "ACTIVE" and (q.get("conversion") or {}).get("score", 1) <= 0:
            out.append({"kind": "quality", "tone": "warn", "title": "Conversão abaixo da média",
                        "text": f"{c['name']}: a Meta classifica a taxa de conversão abaixo dos concorrentes. Revise página e oferta.",
                        "campaign_id": c["id"], "action": "creatives"})
            break
    return out[:4]


# ------------------------------------------------------------------ leitura

def _period(since: Optional[str], until: Optional[str]) -> Tuple[str, str]:
    today = date.today()
    try:
        end = date.fromisoformat(until) if until else today - timedelta(days=1)
        start = date.fromisoformat(since) if since else end - timedelta(days=29)
    except ValueError as exc:
        raise StudioError("PERIOD_INVALID") from exc
    if start > end or (end - start).days > 92:
        raise StudioError("PERIOD_INVALID")
    return start.isoformat(), end.isoformat()


async def _get(path: str, token: str, params: Dict[str, Any]) -> Dict[str, Any]:
    from .meta_ad_publisher import _graph
    return await _graph("GET", path, token=token, params=params)


async def _paged(path: str, token: str, params: Dict[str, Any], pages: int = 4) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    query = dict(params)
    for _ in range(pages):
        body = await _get(path, token, query)
        out.extend(r for r in body.get("data") or [] if isinstance(r, dict))
        after = ((body.get("paging") or {}).get("cursors") or {}).get("after")
        if not after or not (body.get("paging") or {}).get("next"):
            break
        query = {**query, "after": after}
    return out


async def _safe(coro) -> Tuple[Any, Optional[str]]:
    """Uma parte que falha (ex.: sem permissão para quebras) não derruba a tela inteira."""
    try:
        return await coro, None
    except StudioError as exc:
        return None, exc.code
    except Exception as exc:  # noqa: BLE001
        return None, type(exc).__name__


async def overview(client_id: str, *, since: Optional[str] = None, until: Optional[str] = None, fresh: bool = False) -> Dict[str, Any]:
    start, end = _period(since, until)
    key = (client_id, start, end)
    cached = _CACHE.get(key)
    if cached and not fresh and time.monotonic() - cached[0] < CACHE_TTL:
        return cached[1]
    from .meta_ad_publisher import _ad_account
    account_ctx = await _ad_account(client_id)
    act, token = account_ctx["act"], account_ctx["token"]
    time_range = json.dumps({"since": start, "until": end})
    base = {"time_range": time_range, "limit": 200}

    def breakdown(keys: str):
        return _paged(f"/{act}/insights", token, {**base, "level": "account", "fields": "spend,impressions,actions,action_values", "breakdowns": keys})

    (account_rows, e1), (camp_rows, e2), (ad_rows, e3), (creative_rows, e4), (age_rows, e5), (place_rows, e6), \
        (region_rows, e7), (device_rows, e8) = await asyncio.gather(
        _safe(_paged(f"/{act}/insights", token, {**base, "level": "account", "fields": INSIGHT_FIELDS})),
        _safe(_paged(f"/{act}/campaigns", token, {"limit": 100, "fields": "id,name,objective,effective_status,daily_budget,lifetime_budget,start_time,stop_time",
                                                  "effective_status": json.dumps(["ACTIVE", "PAUSED", "CAMPAIGN_PAUSED", "IN_PROCESS", "WITH_ISSUES"])})),
        _safe(_paged(f"/{act}/insights", token, {**base, "level": "ad", "fields": (
            "ad_id,ad_name,campaign_id,campaign_name,adset_id,spend,impressions,clicks,ctr,frequency,actions,action_values,"
            "quality_ranking,engagement_rate_ranking,conversion_rate_ranking,video_play_actions,video_thruplay_watched_actions,"
            "video_p25_watched_actions,video_p50_watched_actions,video_p75_watched_actions,video_p100_watched_actions")})),
        _safe(_paged(f"/{act}/ads", token, {"limit": 200, "fields": "id,campaign_id,effective_status,creative{thumbnail_url,image_url,title,body}"}, pages=2)),
        _safe(breakdown("age,gender")),
        _safe(breakdown("publisher_platform,platform_position")),
        _safe(breakdown("region")),
        _safe(breakdown("device_platform")),
    )
    if e1 and e2:
        raise StudioError(e1 if e1.startswith("AD_") else "META_UNAVAILABLE")
    account_metrics = results((account_rows or [{}])[0] if account_rows else {})
    ads = ad_rows or []
    creatives = {str(r.get("id")): (r.get("creative") or {}) for r in creative_rows or []}
    by_campaign: Dict[str, List[Dict[str, Any]]] = {}
    for ad in ads:
        by_campaign.setdefault(str(ad.get("campaign_id")), []).append(ad)

    campaigns: List[Dict[str, Any]] = []
    for row in camp_rows or []:
        cid = str(row.get("id"))
        own = by_campaign.get(cid, [])
        totals: Dict[str, Any] = {"spend": 0.0, "impressions": 0.0, "clicks": 0.0, "actions": [], "action_values": []}
        merged_actions: Dict[str, float] = {}
        merged_values: Dict[str, float] = {}
        for ad in own:
            totals["spend"] += _num(ad.get("spend"))
            totals["impressions"] += _num(ad.get("impressions"))
            totals["clicks"] += _num(ad.get("clicks"))
            for a in ad.get("actions") or []:
                merged_actions[a.get("action_type")] = merged_actions.get(a.get("action_type"), 0.0) + _num(a.get("value"))
            for a in ad.get("action_values") or []:
                merged_values[a.get("action_type")] = merged_values.get(a.get("action_type"), 0.0) + _num(a.get("value"))
        totals["actions"] = [{"action_type": k, "value": v} for k, v in merged_actions.items()]
        totals["action_values"] = [{"action_type": k, "value": v} for k, v in merged_values.items()]
        totals["ctr"] = totals["clicks"] / totals["impressions"] * 100 if totals["impressions"] else 0
        metrics = results(totals)
        top = max(own, key=lambda a: _num(a.get("spend")), default=None)
        creative = creatives.get(str(top.get("ad_id"))) if top else None
        video_rows = [v for v in (_video(a) for a in own) if v]
        status = str(row.get("effective_status") or "")
        if not metrics["spend"] and status not in ("ACTIVE", "IN_PROCESS", "WITH_ISSUES"):
            continue  # pausada e sem gasto no período: fica só na tabela completa
        campaigns.append({
            "id": cid, "name": str(row.get("name") or "Campanha"), "objective": str(row.get("objective") or ""),
            "status": status, "status_label": STATUS_LABEL.get(status, status.title() or "—"),
            "daily_budget": round(_num(row.get("daily_budget")) / 100, 2) or None,
            "ads": len(own), "adsets": len({a.get("adset_id") for a in own if a.get("adset_id")}),
            "metrics": metrics,
            "quality": {"quality": _rank(own, "quality_ranking"), "engagement": _rank(own, "engagement_rate_ranking"),
                        "conversion": _rank(own, "conversion_rate_ranking")},
            "video": max(video_rows, key=lambda v: v["plays"]) if video_rows else None,
            "creative": {"thumbnail": creative.get("thumbnail_url") or creative.get("image_url"),
                         "title": str(creative.get("title") or "")[:120], "body": str(creative.get("body") or "")[:240]} if creative else None,
            "ads_manager_url": f"https://adsmanager.facebook.com/adsmanager/manage/campaigns?act={act[4:]}&selected_campaign_ids={cid}",
        })
    campaigns.sort(key=lambda c: (c["status"] != "ACTIVE", -c["metrics"]["spend"]))
    age = build_breakdown(age_rows or [], ("age",))
    data = {
        "period": {"since": start, "until": end},
        "account": account_metrics,
        "campaigns": campaigns,
        "breakdowns": {
            "age_gender": build_breakdown(age_rows or [], ("age", "gender")), "age": age,
            "placement": build_breakdown(place_rows or [], ("publisher_platform", "platform_position")),
            "region": build_breakdown(region_rows or [], ("region",)), "device": build_breakdown(device_rows or [], ("device_platform",)),
        },
        "recommendations": recommendations(campaigns, ads, age, account_metrics),
        "unavailable": sorted(k for k, err in {"campaigns": e2, "ads": e3, "creatives": e4, "age": e5, "placement": e6,
                                               "region": e7, "device": e8}.items() if err),
        "loaded_at": int(time.time()),
    }
    _CACHE[key] = (time.monotonic(), data)
    return data


# ------------------------------------------------------------------ permissões por função

FEATURES: List[Dict[str, Any]] = [
    {"key": "ads_reports", "label": "Relatórios de anúncios e Mídia On", "scopes": ["ads_read", "ads_management", "business_management"],
     "connection": "paid", "effect": "Sem elas, não aparecem campanhas nem dá para criar anúncios pausados."},
    {"key": "instagram", "label": "Instagram: perfil, posts e insights",
     "scopes": ["instagram_basic", "instagram_manage_insights", "pages_read_engagement"], "connection": "organic",
     "effect": "Sem elas, os relatórios do Instagram ficam vazios."},
    {"key": "comments", "label": "Responder comentários", "scopes": ["instagram_manage_comments"], "connection": "organic",
     "effect": "Sem ela, a tela Comentários só lê."},
    {"key": "direct", "label": "Direct com IA e boas-vindas", "scopes": ["instagram_manage_messages", "pages_messaging"],
     "connection": "organic", "any": True, "effect": "Sem ela, a automação do Direct não envia."},
    {"key": "publish", "label": "Publicar Reels e posts", "scopes": ["instagram_content_publish"], "connection": "organic",
     "effect": "Sem ela, o calendário não publica direto no Instagram."},
    {"key": "catalog", "label": "Catálogo: loja e cartões no WhatsApp", "scopes": ["catalog_management"], "connection": "any",
     "effect": "Sem ela, as peças vão como link da loja."},
    {"key": "leads", "label": "Leads de formulário instantâneo", "scopes": ["leads_retrieval"], "connection": "any",
     "effect": "Sem ela, os leads dos anúncios ficam só no Gerenciador."},
    {"key": "mentions", "label": "Página do Facebook e menções", "scopes": ["read_insights", "pages_read_user_content"],
     "connection": "organic", "effect": "Sem elas, Clipping e Saúde da Marca não leem menções e a Página."},
]


def feature_status(paid: Optional[set], organic: Optional[set]) -> List[Dict[str, Any]]:
    """ok | missing | unknown (conexão antiga sem permissões salvas) | not_connected."""
    out = []
    for feature in FEATURES:
        pools = {"paid": [paid], "organic": [organic], "any": [paid, organic]}[feature["connection"]]
        pools = [p for p in pools if p is not None]
        if not pools:
            state = "not_connected"
            missing = list(feature["scopes"])
        elif all(not p for p in pools):
            state, missing = "unknown", []
        else:
            granted = set().union(*pools)
            missing = [s for s in feature["scopes"] if s not in granted]
            ok = (len(missing) < len(feature["scopes"])) if feature.get("any") else not missing
            state = "ok" if ok else "missing"
            if ok:
                missing = []
        out.append({"key": feature["key"], "label": feature["label"], "scopes": feature["scopes"], "state": state,
                    "missing": missing, "effect": feature["effect"]})
    return out


async def permissions(client_id: str) -> Dict[str, Any]:
    from .connection_resolver import resolve_connection_for_scope
    from .ig_supabase import sb_select

    async def scopes_of(platform: str, connection_type: str) -> Tuple[Optional[set], Dict[str, Any]]:
        try:
            resolved = await resolve_connection_for_scope(client_id=client_id, platform=platform, connection_type=connection_type)
        except Exception:  # noqa: BLE001 — sem conexão
            return None, {}
        connection_id = str(resolved.get("connection_id") or "")
        if not connection_id:
            return None, {}
        rows = await sb_select("meta_connections", select="id,scopes_json,username,ad_account_id,business_id,updated_at",
                               filters={"id": f"eq.{connection_id}", "client_id": f"eq.{client_id}"}, limit=1)
        row = rows[0] if rows else {}
        return {str(s) for s in (row.get("scopes_json") or []) if s}, {
            "username": row.get("username"), "ad_account": row.get("ad_account_id"), "updated_at": row.get("updated_at"),
            "page": bool(row.get("business_id"))}

    (paid, paid_info), (organic, organic_info) = await asyncio.gather(scopes_of("meta_ads", "paid"), scopes_of("instagram", "organic"))
    return {"features": feature_status(paid, organic),
            "connections": {"paid": {"connected": paid is not None, **paid_info},
                            "organic": {"connected": organic is not None, **organic_info}}}
