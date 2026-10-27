"""Compras e receita do GA4 por canal e campanha, com investimento quando seguro.

- A receita aqui é a ATRIBUÍDA PELO GA4 (evento purchase): não é o faturamento
  confirmado do e-commerce e pode conter eventos duplicados.
- Canal de aquisição: o `sessionDefaultChannelGroup` gravado pela sincronização;
  em linhas antigas (sem a coluna) é derivado de origem/mídia/campanha pelas
  regras do agrupamento padrão do GA4 e marcado como "derivado".
- Investimento e ROAS só quando o vínculo é inequívoco: mesma empresa, mesma
  plataforma (Google Ads para google / cpc; Meta para origens Meta pagas), nome
  de campanha idêntico, um único registro de campanha com esse nome e uma única
  linha do GA4 recebendo esse investimento. Fora disso: sem investimento e sem
  ROAS, nunca uma estimativa.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_select

_SEARCH = {"google", "bing", "yahoo", "baidu", "duckduckgo", "ecosia", "yandex", "naver", "brave", "search"}
_SOCIAL = {"facebook", "fb", "instagram", "ig", "meta", "m.facebook.com", "l.facebook.com", "lm.facebook.com",
           "l.instagram.com", "tiktok", "pinterest", "linkedin", "twitter", "t.co", "x.com", "threads", "snapchat",
           "kwai", "whatsapp", "messenger", "an"}
_VIDEO = {"youtube", "youtube.com", "m.youtube.com", "vimeo", "twitch"}
_SHOPPING_SOURCES = {"shopping", "google shopping", "mercadolivre", "amazon", "shopee", "magalu", "igshopping"}
_PAID_MEDIUM = re.compile(r"^(.*cp.*|ppc|retargeting|paid.*)$")
_SHOPPING_CAMPAIGN = re.compile(r"^(.*(([^a-df-z]|^)shop|shopping).*)$")
_META_SOURCES = {"facebook", "fb", "instagram", "ig", "meta", "an", "messenger", "audience_network"}
_META_PAID_MEDIUM = re.compile(r"(paid|cpc|cpm|ads?$|social_paid|paid_social|paidsocial)")

GA4_CHANNEL_LABELS = {
    "Direct": "Direto", "Organic Search": "Busca orgânica", "Paid Search": "Busca paga",
    "Paid Shopping": "Shopping pago", "Organic Shopping": "Shopping orgânico", "Paid Social": "Social pago",
    "Organic Social": "Social orgânico", "Paid Video": "Vídeo pago", "Organic Video": "Vídeo orgânico",
    "Display": "Display", "Paid Other": "Outros pagos", "Cross-network": "Cross-network (PMax)",
    "Email": "E-mail", "Affiliates": "Afiliados", "Referral": "Referência", "SMS": "SMS",
    "Audio": "Áudio", "Mobile Push Notifications": "Notificações push", "Unassigned": "Não atribuído",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def derive_channel_group(source: str, medium: str, campaign: str) -> str:
    """Aproximação das regras do Default Channel Group do GA4 (linhas antigas)."""
    src, med, camp = _text(source).lower(), _text(medium).lower(), _text(campaign).lower()
    if src == "(direct)" and med in {"(none)", "(not set)", ""}:
        return "Direct"
    if "cross-network" in camp:
        return "Cross-network"
    paid = bool(_PAID_MEDIUM.match(med))
    if paid:
        if src in _SHOPPING_SOURCES or _SHOPPING_CAMPAIGN.match(camp):
            return "Paid Shopping"
        if src in _SEARCH:
            return "Paid Search"
        if src in _SOCIAL:
            return "Paid Social"
        if src in _VIDEO:
            return "Paid Video"
        return "Paid Other"
    if med in {"display", "banner", "expandable", "interstitial", "cpm"}:
        return "Display"
    if src in _SHOPPING_SOURCES or _SHOPPING_CAMPAIGN.match(camp):
        return "Organic Shopping"
    if src in _SOCIAL or med in {"social", "social-network", "social-media", "sm", "social network", "social media"}:
        return "Organic Social"
    if src in _VIDEO or "video" in med:
        return "Organic Video"
    if src in _SEARCH or med == "organic":
        return "Organic Search"
    if med in {"email", "e-mail", "e_mail", "e mail"} or src in {"email", "e-mail", "e_mail", "e mail"}:
        return "Email"
    if med == "affiliate":
        return "Affiliates"
    if med == "referral":
        return "Referral"
    if med == "audio":
        return "Audio"
    if med == "sms" or src == "sms":
        return "SMS"
    if med.endswith("push") or "mobile" in med or "notification" in med:
        return "Mobile Push Notifications"
    return "Unassigned"


def _platform_for(source: str, medium: str) -> Optional[str]:
    src, med = _text(source).lower(), _text(medium).lower()
    if src == "google" and med == "cpc":
        return "google_ads"
    if src in _META_SOURCES and _META_PAID_MEDIUM.search(med):
        return "meta_ads"
    return None


async def _google_ads_spend(client_id: str, start: str, end: str) -> Dict[str, float]:
    from .google_ads import resolve_google_ads_context

    context = await resolve_google_ads_context(client_id)
    if context.client_id != client_id or not context.connection_id or not context.customer_id:
        return {}
    rows = await sb_select(
        "google_ads_daily_stats", select="client_id,connection_id,customer_id,campaign_id,campaign_name,stat_date,cost",
        filters={"client_id": f"eq.{client_id}", "connection_id": f"eq.{context.connection_id}",
                 "customer_id": f"eq.{context.customer_id}", "and": f"(stat_date.gte.{start},stat_date.lte.{end})"},
        order="stat_date.asc", limit=20001,
    )
    if len(rows) > 20000:
        return {}
    return _spend_by_unique_name(
        [r for r in rows if r.get("client_id") == client_id and r.get("connection_id") == context.connection_id
         and r.get("customer_id") == context.customer_id and start <= _text(r.get("stat_date")) <= end],
        spend_key="cost",
    )


async def _meta_spend(client_id: str, start: str, end: str) -> Dict[str, float]:
    rows = await sb_select(
        "campaign_daily_stats", select="client_id,campaign_id,campaign_name,stat_date,spend",
        filters={"client_id": f"eq.{client_id}", "and": f"(stat_date.gte.{start},stat_date.lte.{end})"},
        order="stat_date.asc", limit=20001,
    )
    if len(rows) > 20000:
        return {}
    return _spend_by_unique_name(
        [r for r in rows if r.get("client_id") == client_id and start <= _text(r.get("stat_date")) <= end],
        spend_key="spend",
    )


def _spend_by_unique_name(rows: List[Dict[str, Any]], *, spend_key: str) -> Dict[str, float]:
    """Investimento por nome de campanha, só para nomes de UMA campanha."""
    ids_by_name: Dict[str, set] = defaultdict(set)
    spend: Dict[str, float] = defaultdict(float)
    for row in rows:
        name = _text(row.get("campaign_name"))
        if not name:
            continue
        ids_by_name[name].add(_text(row.get("campaign_id")))
        spend[name] += _num(row.get(spend_key))
    return {name: round(value, 2) for name, value in spend.items() if len(ids_by_name[name]) == 1}


async def campaign_investments(client_id: str, start: str, end: str) -> Dict[str, Dict[str, float]]:
    """Investimento por plataforma e nome; falha de uma plataforma não derruba o relatório."""
    out: Dict[str, Dict[str, float]] = {}
    for provider, loader in (("google_ads", _google_ads_spend), ("meta_ads", _meta_spend)):
        try:
            out[provider] = await loader(client_id, start, end)
        except Exception as exc:  # noqa: BLE001 — só o tipo vai para o log
            print(f"[ga4_attribution][investment] client_id={client_id} provider={provider} status=unavailable error={exc.__class__.__name__}")
            out[provider] = {}
    return out


def enrich_campaign_items(items: List[Dict[str, Any]], investments: Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]:
    # Quantas linhas do GA4 reivindicam cada campanha paga: com mais de uma, o
    # investimento não é atribuído a nenhuma (não há divisão segura).
    claims: Dict[tuple, int] = defaultdict(int)
    for item in items:
        platform = _platform_for(item.get("source"), item.get("medium"))
        if platform:
            claims[(platform, _text(item.get("campaign_name")))] += 1
    enriched = []
    for item in items:
        stored = _text(item.get("channel_group"))
        channel = stored or derive_channel_group(item.get("source"), item.get("medium"), item.get("campaign_name"))
        platform = _platform_for(item.get("source"), item.get("medium"))
        name = _text(item.get("campaign_name"))
        spend = None
        if platform and claims[(platform, name)] == 1:
            spend = (investments.get(platform) or {}).get(name)
        revenue = round(_num(item.get("purchase_revenue")), 2)
        enriched.append({
            **item,
            "channel_group": channel,
            "channel_group_label": GA4_CHANNEL_LABELS.get(channel, channel),
            "channel_group_source": "ga4" if stored else "derivado",
            "investment": spend,
            "investment_source": platform if spend is not None else None,
            "roas": round(revenue / spend, 2) if spend and spend > 0 else None,
        })
    return enriched


def build_channel_group_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for item in items:
        key = _text(item.get("channel_group")) or "Unassigned"
        bucket = grouped.setdefault(key, {
            "channel_group": key, "channel_group_label": GA4_CHANNEL_LABELS.get(key, key),
            "channel_group_source": item.get("channel_group_source"),
            "sessions": 0, "ecommerce_purchases": 0, "purchase_revenue": 0.0,
        })
        bucket["sessions"] += int(_num(item.get("sessions")))
        bucket["ecommerce_purchases"] += int(_num(item.get("ecommerce_purchases")))
        bucket["purchase_revenue"] = round(bucket["purchase_revenue"] + _num(item.get("purchase_revenue")), 2)
        if item.get("channel_group_source") == "derivado":
            bucket["channel_group_source"] = "derivado"
    return sorted(grouped.values(), key=lambda row: (-row["purchase_revenue"], -row["ecommerce_purchases"], -row["sessions"]))
