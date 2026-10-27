"""Origem de cada pedido (UTM, referência, canal), igual para Shopify e FBITS.

Por que existe: sem a origem do pedido, campanhas e vendas ficam em telas
separadas, sem ligação. Este módulo extrai, do payload que a loja JÁ envia,
os campos que dizem de onde a venda veio. Nenhuma chamada externa.

Regras:
- Só registra o que a plataforma informou. Nada é inferido de campanha,
  horário ou valor. Sem UTM e sem referência, o canal é `unknown`.
- `attribution_source` diz de onde veio a classificação: `utm` (parâmetros
  de campanha), `click_id` (identificador de clique do Google Ads — gclid,
  gbraid ou wbraid — que só existe em clique de anúncio com marcação
  automática), `referrer` (site de origem), `platform` (origem/canal que a
  própria loja registrou) ou `none`. UTM sempre vence o identificador de
  clique; o identificador nunca vira nome de campanha.
- URLs são reduzidas: guardamos só o domínio de referência e os parâmetros
  utm_*. Query strings podem carregar e-mail ou tokens e nunca são gravadas.
- Modelo de atribuição informado ao cliente: último clique com UTM
  registrado pela loja. Venda sem origem nunca é distribuída entre campanhas.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.parse import parse_qs, urlsplit

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")
ATTRIBUTION_COLUMNS = (
    *UTM_KEYS,
    "origin_channel",
    "origin_detail",
    "referrer_domain",
    "attribution_source",
)

CHANNEL_LABELS = {
    "paid_social": "Mídia paga · redes sociais",
    "paid_search": "Mídia paga · busca",
    "paid_other": "Mídia paga · outros",
    "organic_social": "Redes sociais (orgânico)",
    "organic_search": "Busca orgânica",
    "email": "E-mail",
    "sms_whatsapp": "SMS / WhatsApp",
    "affiliate": "Afiliados e parceiros",
    "referral": "Outros sites",
    "marketplace": "Marketplace",
    "direct": "Direto",
    "unknown": "Origem não identificada",
}

_SOCIAL = ("facebook", "fb", "instagram", "ig", "meta", "tiktok", "pinterest", "twitter", "x.com", "linkedin",
           "youtube", "kwai", "threads", "snapchat")
_SEARCH = ("google", "bing", "yahoo", "duckduckgo", "ecosia", "baidu", "yandex")
_PAID_MEDIUMS = ("cpc", "ppc", "paid", "cpm", "cpv", "cpa", "ads", "display", "paidsocial", "paid_social",
                 "paid-social", "social_paid", "pago", "midia_paga", "retargeting", "remarketing")
_EMAIL = ("email", "e-mail", "newsletter", "klaviyo", "mailchimp", "rd_station", "rdstation", "edrone")
_MESSAGING = ("sms", "whatsapp", "wpp", "zap")
_AFFILIATE = ("affiliate", "afiliado", "afiliados", "parceiro", "partner", "influencer", "influenciador", "cupom")
_MARKETPLACE = ("mercadolivre", "mercado_livre", "mercado livre", "amazon", "magalu", "shopee", "americanas",
                "netshoes", "dafiti", "marketplace", "b2w", "carrefour")
# Marcação automática do Google Ads: presentes só em clique de anúncio.
GOOGLE_CLICK_IDS = ("gclid", "gbraid", "wbraid")
GOOGLE_ADS_DETAIL = "Google Ads (clique de anúncio)"
_UTM_ALIASES = {
    "utm_source": ("utm_source", "utmsource", "source", "origem_utm"),
    "utm_medium": ("utm_medium", "utmmedium", "medium", "midia"),
    "utm_campaign": ("utm_campaign", "utmcampaign", "campaign", "campanha"),
    "utm_content": ("utm_content", "utmcontent", "content", "conteudo"),
    "utm_term": ("utm_term", "utmterm", "term", "termo"),
}


def _text(value: Any, limit: int = 200) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _norm_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]", "", _text(value).lower().replace("-", "_").replace(" ", "_"))


def _has(value: str, needles: Iterable[str]) -> bool:
    low = value.lower()
    return any(re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", low) for n in needles)


def _domain(url: Any) -> str:
    raw = _text(url, 500)
    if not raw:
        return ""
    if "://" not in raw and not raw.startswith("/"):
        raw = "https://" + raw
    try:
        host = (urlsplit(raw).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def utms_from_url(url: Any) -> Dict[str, str]:
    """utm_* da query de uma URL (ex.: landing_site da Shopify)."""
    raw = _text(url, 2000)
    if "?" not in raw:
        return {}
    try:
        query = parse_qs(urlsplit(raw if "://" in raw else "https://x" + (raw if raw.startswith("/") else "/" + raw)).query)
    except ValueError:
        return {}
    out: Dict[str, str] = {}
    for key in UTM_KEYS:
        values = query.get(key) or []
        value = _text(values[0]) if values else ""
        if value:
            out[key] = value
    return out


def utms_from_pairs(pairs: Iterable[Mapping[str, Any]], *, key_field: str, value_field: str) -> Dict[str, str]:
    """utm_* de listas chave/valor (Shopify note_attributes, FBITS metadados)."""
    found: Dict[str, str] = {}
    for pair in pairs or []:
        if not isinstance(pair, Mapping):
            continue
        key = _norm_key(pair.get(key_field))
        value = _text(pair.get(value_field))
        if not key or not value:
            continue
        for utm, aliases in _UTM_ALIASES.items():
            if key in aliases and utm not in found:
                found[utm] = value
    return found


def google_click_in_url(url: Any) -> bool:
    raw = _text(url, 2000)
    if "?" not in raw:
        return False
    try:
        query = parse_qs(urlsplit(raw if "://" in raw else "https://x" + (raw if raw.startswith("/") else "/" + raw)).query)
    except ValueError:
        return False
    return any(_text((query.get(key) or [""])[0]) for key in GOOGLE_CLICK_IDS)


def google_click_in_pairs(pairs: Iterable[Mapping[str, Any]], *, key_field: str, value_field: str) -> bool:
    for pair in pairs or []:
        if isinstance(pair, Mapping) and _norm_key(pair.get(key_field)) in GOOGLE_CLICK_IDS and _text(pair.get(value_field)):
            return True
    return False


def classify_channel(
    *,
    utm_source: str = "",
    utm_medium: str = "",
    referrer_domain: str = "",
    platform_origin: str = "",
    store_domain: str = "",
) -> str:
    source, medium = utm_source.lower(), utm_medium.lower()
    if source or medium:
        if _has(medium, _EMAIL) or _has(source, _EMAIL):
            return "email"
        if _has(medium, _MESSAGING) or _has(source, _MESSAGING):
            return "sms_whatsapp"
        if _has(medium, _AFFILIATE) or _has(source, _AFFILIATE):
            return "affiliate"
        paid = _has(medium, _PAID_MEDIUMS) or source in {"gads", "adwords", "fbads", "meta_ads", "google_ads"}
        if _has(source, _SOCIAL) or "social" in medium:
            return "paid_social" if paid or "paid" in medium else "organic_social"
        if _has(source, _SEARCH):
            return "paid_search" if paid else "organic_search"
        if paid:
            return "paid_other"
        if _has(source, _MARKETPLACE):
            return "marketplace"
        return "referral"
    if referrer_domain and referrer_domain != store_domain:
        if _has(referrer_domain, _SEARCH):
            return "organic_search"
        if _has(referrer_domain, _SOCIAL) or referrer_domain in {"l.facebook.com", "lm.facebook.com", "t.co"}:
            return "organic_social"
        if _has(referrer_domain, _MARKETPLACE):
            return "marketplace"
        return "referral"
    origin = platform_origin.lower()
    if origin:
        if _has(origin, _MARKETPLACE):
            return "marketplace"
        if _has(origin, _SEARCH):
            return "organic_search"
        if _has(origin, _SOCIAL):
            return "organic_social"
    return "unknown"


def _result(
    utms: Mapping[str, str], *, referrer_domain: str, origin_detail: str, platform_origin: str, store_domain: str = "",
    google_click: bool = False,
) -> Dict[str, Optional[str]]:
    channel = classify_channel(
        utm_source=utms.get("utm_source", ""), utm_medium=utms.get("utm_medium", ""),
        referrer_domain=referrer_domain, platform_origin=platform_origin, store_domain=store_domain,
    )
    if not utms and google_click and channel not in {"marketplace"}:
        # Sem UTM, mas com o clique do Google Ads: é anúncio do Google.
        # Campanha fica vazia — o gclid não diz qual é.
        out: Dict[str, Optional[str]] = {key: None for key in UTM_KEYS}
        out.update({
            "origin_channel": "paid_search",
            "origin_detail": GOOGLE_ADS_DETAIL,
            "referrer_domain": referrer_domain or None,
            "attribution_source": "click_id",
        })
        return out
    if utms:
        source = "utm"
    elif referrer_domain and referrer_domain != store_domain:
        source = "referrer"
    elif platform_origin and channel != "unknown":
        source = "platform"
    else:
        source = "none"
    out: Dict[str, Optional[str]] = {key: (utms.get(key) or None) for key in UTM_KEYS}
    out.update({
        "origin_channel": channel,
        "origin_detail": origin_detail or None,
        "referrer_domain": referrer_domain or None,
        "attribution_source": source,
    })
    return out


def shopify_order_attribution(payload: Mapping[str, Any], *, shop_domain: str = "") -> Dict[str, Optional[str]]:
    """Origem a partir do pedido Shopify (webhook ou REST orders.json).

    Prioridade das UTMs: landing_site (URL de entrada da sessão que comprou)
    e, na falta, note_attributes gravados por apps/tema. referring_site dá o
    domínio de origem quando não há UTM. source_name diz o canal de venda
    (web, pos, app) e entra como detalhe.
    """
    payload = payload if isinstance(payload, Mapping) else {}
    utms = utms_from_url(payload.get("landing_site"))
    for key, value in utms_from_pairs(payload.get("note_attributes") or [], key_field="name", value_field="value").items():
        utms.setdefault(key, value)
    referrer = _domain(payload.get("referring_site"))
    source_name = _text(payload.get("source_name"), 80)
    store = _domain(shop_domain)
    google_click = google_click_in_url(payload.get("landing_site")) or google_click_in_pairs(
        payload.get("note_attributes") or [], key_field="name", value_field="value")
    return _result(
        utms, referrer_domain=referrer, origin_detail=source_name,
        platform_origin="" if source_name in {"web", "shopify_draft_order", ""} else source_name,
        store_domain=store, google_click=google_click,
    )


def fbits_order_attribution(order: Mapping[str, Any]) -> Dict[str, Optional[str]]:
    """Origem a partir do pedido FBITS/Wake (`GET /pedidos`).

    A Wake guarda as UTMs da navegação até o fechamento. Pela documentação
    pública da API do pedido, os candidatos são `metadados` (chave/valor),
    `origemPedido` (com `subOrigem`), `canalOrigem` e `usuario.origemContato`.
    Também aceitamos chaves utm_* no topo do pedido, caso a loja exponha.
    O campo exato precisa ser confirmado com um pedido real da loja.
    """
    order = order if isinstance(order, Mapping) else {}
    utms = utms_from_pairs(order.get("metadados") or [], key_field="chave", value_field="valor")
    for key in UTM_KEYS:
        for alias in (key, key.replace("_", ""), "utm" + key[4:].capitalize()):
            if key not in utms and _text(order.get(alias)):
                utms[key] = _text(order.get(alias))
    origin = order.get("origemPedido") if isinstance(order.get("origemPedido"), Mapping) else {}
    sub = origin.get("subOrigem") if isinstance(origin.get("subOrigem"), Mapping) else {}
    user = order.get("usuario") if isinstance(order.get("usuario"), Mapping) else {}
    parts: List[str] = [p for p in (_text(origin.get("nome"), 80), _text(sub.get("nome"), 80)) if p]
    canal_origem = _text(order.get("canalOrigem"), 80)
    if canal_origem and canal_origem not in parts:
        parts.append(canal_origem)
    contact = _text(user.get("origemContato"), 40)
    detail = " · ".join(parts)
    platform_origin = " ".join(p for p in (detail, "" if contact in {"", "Outro"} else contact) if p)
    is_marketplace = bool(_text(order.get("marketPlacePedidoId"))) or any(
        isinstance(item, Mapping) and item.get("isMarketPlace") for item in order.get("itens") or []
    )
    if is_marketplace and "marketplace" not in platform_origin.lower():
        platform_origin = (platform_origin + " marketplace").strip()
    google_click = google_click_in_pairs(order.get("metadados") or [], key_field="chave", value_field="valor") or any(
        _text(order.get(key)) for key in GOOGLE_CLICK_IDS)
    return _result(utms, referrer_domain="", origin_detail=detail or contact, platform_origin=platform_origin,
                   google_click=google_click)


def fbits_order_from_raw(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Reconstrói, do `raw` já gravado, só os campos de origem do pedido FBITS."""
    raw = raw if isinstance(raw, Mapping) else {}
    order: Dict[str, Any] = {key: raw.get(key) for key in ("canalId", "canalOrigem", "marketPlacePedidoId") if key in raw}
    if isinstance(raw.get("origemPedido"), Mapping):
        order["origemPedido"] = raw["origemPedido"]
    if raw.get("origemContato"):
        order["usuario"] = {"origemContato": raw.get("origemContato")}
    if isinstance(raw.get("metadados_origem"), list):
        order["metadados"] = raw["metadados_origem"]
    if isinstance(raw.get("itens"), list):
        order["itens"] = [item for item in raw["itens"] if isinstance(item, Mapping)]
    return order


def fbits_origin_raw(order: Mapping[str, Any]) -> Dict[str, Any]:
    """Subconjunto de origem do pedido FBITS guardado em `raw` (sem PII)."""
    order = order if isinstance(order, Mapping) else {}
    raw: Dict[str, Any] = {}
    for key in ("canalId", "canalOrigem", "marketPlacePedidoId"):
        if key in order:
            raw[key] = order.get(key)
    origin = order.get("origemPedido")
    if isinstance(origin, Mapping):
        sub = origin.get("subOrigem") if isinstance(origin.get("subOrigem"), Mapping) else None
        raw["origemPedido"] = {
            "id": origin.get("id"), "nome": origin.get("nome"),
            **({"subOrigem": {"id": sub.get("id"), "nome": sub.get("nome")}} if sub else {}),
        }
    user = order.get("usuario")
    if isinstance(user, Mapping) and user.get("origemContato"):
        raw["origemContato"] = user.get("origemContato")
    # Metadados podem ter qualquer coisa: só chaves de origem/campanha entram.
    keep = {alias for aliases in _UTM_ALIASES.values() for alias in aliases} | {"origem", "canal", "parceiro", "fbclid", *GOOGLE_CLICK_IDS}
    meta = [
        {"chave": _text(pair.get("chave"), 60), "valor": _text(pair.get("valor"), 200)}
        for pair in order.get("metadados") or []
        if isinstance(pair, Mapping) and (_norm_key(pair.get("chave")) in keep or _norm_key(pair.get("chave")).startswith("utm"))
    ]
    if meta:
        raw["metadados_origem"] = meta
    return raw


_MISSING_COLUMNS_LOGGED: set = set()


async def upsert_orders_with_attribution(
    table: str, rows: List[Dict[str, Any]], *, on_conflict: str, upsert: Any = None,
) -> None:
    """Upsert que tolera a migration de origem ainda não aplicada.

    Se o banco ainda não tem as colunas de origem, grava o pedido sem elas e
    avisa no log — a venda nunca deixa de ser gravada por causa da atribuição.
    """
    import httpx

    from .ig_supabase import _is_column_compat_error, sb_upsert

    # Quem chama passa o próprio `sb_upsert` do módulo (mantém os mocks de teste).
    sb_upsert = upsert or sb_upsert
    try:
        await sb_upsert(table, rows, on_conflict=on_conflict)
        return
    except httpx.HTTPStatusError as exc:
        if not any(_is_column_compat_error(exc, column) for column in ATTRIBUTION_COLUMNS):
            raise
    if table not in _MISSING_COLUMNS_LOGGED:
        _MISSING_COLUMNS_LOGGED.add(table)
        print(f"[attribution] table={table} status=migration_pending action=upsert_without_origin_columns")
    stripped = [{k: v for k, v in row.items() if k not in ATTRIBUTION_COLUMNS} for row in rows]
    await sb_upsert(table, stripped, on_conflict=on_conflict)
