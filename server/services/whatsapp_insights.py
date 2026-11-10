"""WhatsApp da marca: de onde vêm as conversas, quantas viram venda e quanto custa cada venda.

Fontes (nada é copiado do CRM; tudo é lido na hora):
- Conversas e origem: CRM Mugô (`dados-ops-api`, endpoints `brand-leads` e `brand-conversations`), só do
  número de WhatsApp ligado a esta empresa. O telefone NUNCA chega aqui: o CRM manda uma chave (hash)
  e este módulo calcula a mesma chave do telefone do pedido (`phone_key`).
- Pedidos: `shopify_orders` já persistidos (mesma regra de receita de Vendas por origem: pedido não
  cancelado, valor = total_price).
- Gasto por anúncio: `ad_daily_stats` (Meta), pelo ID do anúncio que abriu a conversa.

Regra de atribuição (simples e dita na tela): o pedido conta para a conversa quando o telefone do
pedido é o mesmo do contato e a compra acontece até 7 dias depois do primeiro contato. Cada pedido
conta uma vez só. Sem telefone no pedido, ele não entra — nunca é distribuído por estimativa.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from . import whatsapp_sources
from .commerce_context import SHOPIFY, resolve_commerce_provider
from .ig_supabase import sb_select
from .periods import resolve_period

CONVERSION_WINDOW_DAYS = 7
PAGE_SIZE = 1000
MAX_ROWS = 20000
ATTRIBUTION_LABEL = "Venda conta para a conversa quando o telefone do pedido é o mesmo do contato e a compra acontece até 7 dias depois do primeiro contato."

# Leitura de cada anúncio (só quando há gasto suficiente para julgar).
MIN_SPEND_TO_JUDGE = 150.0
SCALE_ROAS = 4.0

ORIGIN_LABELS = {
    "ad": "Anúncio no Meta",
    "instagram": "Instagram (orgânico)",
    "link": "Link ou QR code",
    "site": "Botão do site",
    "google": "Google Ads",
    "direct": "Direto / orgânico",
}
ORIGIN_ORDER = ["ad", "instagram", "link", "site", "google", "direct"]

_PHONE_FIELDS = (
    "phone:raw_payload->>phone",
    "customer_phone:raw_payload->customer->>phone",
    "billing_phone:raw_payload->billing_address->>phone",
    "shipping_phone:raw_payload->shipping_address->>phone",
)


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _num(value: Any) -> float:
    try:
        return float(str(value if value is not None else 0).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _dt(value: Any) -> Optional[datetime]:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def phone_key_source(value: Any, *, international: bool = False) -> str:
    """Mesma regra do CRM (`_shared/whatsappOrigin.js`): celular BR com ou sem 9º dígito → mesma chave.

    Telefone de pedido sem "+" e com 10/11 dígitos é nacional (DDD + número), inclusive DDD 55.
    """
    raw = _text(value)
    digits = re.sub(r"\D", "", raw)
    if not international and not raw.startswith("+") and len(digits) in (10, 11):
        digits = f"55{digits}"
    if digits.startswith("55") and len(digits) in (12, 13):
        return f"55{digits[2:4]}{digits[-8:]}"
    return digits if 8 <= len(digits) <= 15 else ""


def phone_key(value: Any, *, international: bool = False) -> Optional[str]:
    source = phone_key_source(value, international=international)
    if not source:
        return None
    return hashlib.sha256(f"mugo-wa:{source}".encode()).hexdigest()[:32]


def order_phone_keys(order: Dict[str, Any]) -> List[str]:
    # Venda do CRM da marca já vem com as chaves prontas (o telefone não sai de lá).
    if isinstance(order.get("phone_keys"), list):
        return [k for k in order["phone_keys"] if isinstance(k, str) and k]
    keys: List[str] = []
    for field in ("phone", "customer_phone", "billing_phone", "shipping_phone"):
        key = phone_key(order.get(field))
        if key and key not in keys:
            keys.append(key)
    return keys


def origin_bucket(origin: Optional[Dict[str, Any]]) -> str:
    origin = origin or {}
    source = _text(origin.get("source")).upper()
    if _text(origin.get("ad_id")) or source == "META_ADS_WHATSAPP":
        return "ad"
    if _text(origin.get("entry_code")) or source == "ENTRY_CODE":
        return "link"
    if source == "INSTAGRAM":
        return "instagram"
    if source == "SITE":
        return "site"
    if source == "GOOGLE_ADS":
        return "google"
    return "direct"


def origin_label(origin: Optional[Dict[str, Any]]) -> str:
    """Rótulo curto para a etiqueta da conversa: 'Anúncio · Kit BF', 'Link · loja-qr'."""
    origin = origin or {}
    bucket = origin_bucket(origin)
    if bucket == "ad":
        headline = _text(origin.get("ad_headline"))
        return f"Anúncio · {headline[:28]}" if headline else "Anúncio"
    if bucket == "link":
        code = _text(origin.get("entry_code"))
        return f"Link · {code}" if code else "Link ou QR"
    return {"instagram": "Instagram", "site": "Site", "google": "Google Ads", "direct": "Direto"}[bucket]


def match_orders(leads: List[Dict[str, Any]], orders: List[Dict[str, Any]],
                 window_days: int = CONVERSION_WINDOW_DAYS) -> Dict[int, List[Dict[str, Any]]]:
    """Liga pedidos a conversas. Função pura (testável).

    Devolve {índice do lead: [pedidos]}. Cada pedido vai para o lead com a mesma chave de telefone cujo
    primeiro contato é o mais recente antes da compra, dentro da janela. Pedido sem telefone não entra.
    """
    by_key: Dict[str, List[tuple[datetime, int]]] = defaultdict(list)
    for index, lead in enumerate(leads):
        seen = _dt(lead.get("first_seen_at"))
        key = _text(lead.get("phone_key"))
        if seen and key:
            by_key[key].append((seen, index))
    for items in by_key.values():
        items.sort()
    window = timedelta(days=window_days)
    out: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for order in orders:
        bought = _dt(order.get("created_at_shopify"))
        if not bought:
            continue
        best: Optional[tuple[datetime, int]] = None
        for key in order_phone_keys(order):
            for seen, index in by_key.get(key, []):
                # Pequena folga (5 min) para pedido criado no mesmo instante da primeira mensagem.
                if seen - timedelta(minutes=5) <= bought <= seen + window and (best is None or seen > best[0]):
                    best = (seen, index)
        if best:
            out[best[1]].append(order)
    return dict(out)


def _verdict(spend: float, conversations: int, sales: int, roas: Optional[float]) -> Optional[Dict[str, str]]:
    if spend < MIN_SPEND_TO_JUDGE:
        return None
    if sales == 0 or (roas is not None and roas < 1):
        if conversations >= 10:
            return {"code": "talk_no_sale", "label": "Muita conversa, pouca venda"}
        return {"code": "weak", "label": "Revisar"}
    if roas is not None and roas >= SCALE_ROAS:
        return {"code": "scale", "label": "Escalar"}
    return {"code": "keep", "label": "Manter"}


def aggregate(leads: List[Dict[str, Any]], orders_in_window: List[Dict[str, Any]],
              store_orders_in_period: List[Dict[str, Any]], ad_stats: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Junta tudo em números para a tela. Função pura (testável)."""
    matched = match_orders(leads, orders_in_window)
    in_period = {id(o) for o in store_orders_in_period}
    wa_revenue_in_period = sum(_num(o.get("value")) for orders in matched.values() for o in orders if id(o) in in_period)
    origins: Dict[str, Dict[str, Any]] = {
        key: {"key": key, "label": ORIGIN_LABELS[key], "conversations": 0, "sales": 0, "orders": 0, "revenue": 0.0}
        for key in ORIGIN_ORDER
    }
    ads: Dict[str, Dict[str, Any]] = {}
    links: Dict[str, Dict[str, Any]] = {}
    converted = 0
    wa_orders = 0
    wa_revenue = 0.0
    for index, lead in enumerate(leads):
        origin = lead.get("origin") or {}
        bucket = origin_bucket(origin)
        lead_orders = matched.get(index, [])
        revenue = sum(_num(o.get("value")) for o in lead_orders)
        row = origins[bucket]
        row["conversations"] += 1
        row["orders"] += len(lead_orders)
        row["revenue"] += revenue
        if lead_orders:
            row["sales"] += 1
            converted += 1
            wa_orders += len(lead_orders)
            wa_revenue += revenue
        ad_id = _text(origin.get("ad_id"))
        if bucket == "ad" and ad_id:
            ad = ads.setdefault(ad_id, {"ad_id": ad_id, "headline": _text(origin.get("ad_headline")) or None,
                                        "conversations": 0, "sales": 0, "orders": 0, "revenue": 0.0})
            ad["conversations"] += 1
            ad["orders"] += len(lead_orders)
            ad["revenue"] += revenue
            ad["sales"] += 1 if lead_orders else 0
        code = _text(origin.get("entry_code"))
        if bucket == "link" and code:
            link = links.setdefault(code, {"code": code, "conversations": 0, "sales": 0, "revenue": 0.0})
            link["conversations"] += 1
            link["sales"] += 1 if lead_orders else 0
            link["revenue"] += revenue

    ad_rows = []
    for ad_id, ad in ads.items():
        stats = ad_stats.get(ad_id) or {}
        spend = round(_num(stats.get("spend")), 2)
        roas = round(ad["revenue"] / spend, 2) if spend else None
        ad_rows.append({
            **ad,
            "revenue": round(ad["revenue"], 2),
            "ad_name": stats.get("ad_name") or ad["headline"],
            "campaign_name": stats.get("campaign_name"),
            "spend": spend if stats else None,
            "cost_per_conversation": round(spend / ad["conversations"], 2) if spend and ad["conversations"] else None,
            "cost_per_sale": round(spend / ad["sales"], 2) if spend and ad["sales"] else None,
            "roas": roas,
            "verdict": _verdict(spend, ad["conversations"], ad["sales"], roas) if stats else None,
        })
    ad_rows.sort(key=lambda r: (-r["revenue"], -r["sales"], -r["conversations"]))

    ad_spend = round(sum(r["spend"] or 0 for r in ad_rows), 2)
    ad_origin = origins["ad"]
    store_revenue = round(sum(_num(o.get("value")) for o in store_orders_in_period), 2)
    total = len(leads)

    alerts = []
    for row in ad_rows:
        if row["verdict"] and row["verdict"]["code"] in {"talk_no_sale", "weak"}:
            best = next((r for r in ad_rows if r["verdict"] and r["verdict"]["code"] == "scale"), None)
            name = row["ad_name"] or "Um anúncio"
            money = f"{row['spend']:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
            text = f"{name} já gastou R$ {money} e gerou {row['sales']} venda(s) pelo WhatsApp."
            if best:
                text += f" Vale mover verba para {best['ad_name'] or 'o anúncio que mais vende'}."
            alerts.append({"ad_id": row["ad_id"], "text": text})

    def finish(row: Dict[str, Any]) -> Dict[str, Any]:
        row["revenue"] = round(row["revenue"], 2)
        row["share"] = round(row["conversations"] / total * 100, 1) if total else 0.0
        return row

    return {
        "totals": {
            "conversations": total,
            "converted_conversations": converted,
            "conversion_rate": round(converted / total * 100, 1) if total else None,
            "orders": wa_orders,
            "revenue": round(wa_revenue, 2),
            "store_revenue": store_revenue,
            # Só pedidos do período nos dois lados (a receita do WhatsApp inclui a janela de 7 dias depois).
            "share_of_store_revenue": round(min(wa_revenue_in_period / store_revenue * 100, 100.0), 1) if store_revenue else None,
            "ad_spend": ad_spend if ad_rows else None,
            "cost_per_conversation": round(ad_spend / ad_origin["conversations"], 2) if ad_spend and ad_origin["conversations"] else None,
            "cost_per_sale": round(ad_spend / ad_origin["sales"], 2) if ad_spend and ad_origin["sales"] else None,
            "ads_roas": round(ad_origin["revenue"] / ad_spend, 2) if ad_spend else None,
        },
        "origins": [finish(origins[key]) for key in ORIGIN_ORDER if origins[key]["conversations"]],
        "ads": ad_rows[:30],
        "links": sorted(({**l, "revenue": round(l["revenue"], 2)} for l in links.values()), key=lambda r: -r["conversations"])[:30],
        "alerts": alerts[:3],
    }


async def _paged(table: str, *, select: str, filters: Dict[str, str], order: str) -> tuple[List[Dict[str, Any]], bool]:
    rows: List[Dict[str, Any]] = []
    offset = 0
    while offset < MAX_ROWS:
        page = await sb_select(table, select=select, filters=filters, order=order, limit=PAGE_SIZE, offset=offset)
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows, False
        offset += PAGE_SIZE
    return rows, True


async def _shopify_orders(client_id: str, start_iso: str, end_iso: str) -> tuple[List[Dict[str, Any]], bool]:
    rows, truncated = await _paged(
        "shopify_orders",
        select="shopify_order_id,name,total_price,cancelled_at,cancel_reason,created_at_shopify," + ",".join(_PHONE_FIELDS),
        filters={"client_id": f"eq.{client_id}", "and": f"(created_at_shopify.gte.{start_iso},created_at_shopify.lte.{end_iso})"},
        order="created_at_shopify.asc,shopify_order_id.asc",
    )
    return [
        {**row, "value": max(0.0, _num(row.get("total_price")))}
        for row in rows if not (_text(row.get("cancelled_at")) or _text(row.get("cancel_reason")))
    ], truncated


INBOX_ORDER_DAYS = 120
INBOX_MAX_ORDERS = 3000


async def _recent_shopify_orders(client_id: str, since_iso: str) -> List[Dict[str, Any]]:
    """Pedidos mais recentes primeiro (o selo de compra precisa dos novos, não dos antigos)."""
    rows: List[Dict[str, Any]] = []
    for offset in range(0, INBOX_MAX_ORDERS, PAGE_SIZE):
        page = await sb_select(
            "shopify_orders",
            select="shopify_order_id,name,total_price,cancelled_at,cancel_reason,created_at_shopify," + ",".join(_PHONE_FIELDS),
            filters={"client_id": f"eq.{client_id}", "created_at_shopify": f"gte.{since_iso}"},
            order="created_at_shopify.desc,shopify_order_id.desc", limit=PAGE_SIZE, offset=offset,
        )
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
    return [{**row, "value": max(0.0, _num(row.get("total_price")))}
            for row in rows if not (_text(row.get("cancelled_at")) or _text(row.get("cancel_reason")))]


async def _ad_stats(client_id: str, ad_ids: Iterable[str], start: str, end: str) -> Dict[str, Dict[str, Any]]:
    ids = sorted({i for i in ad_ids if i and i.isdigit()})
    out: Dict[str, Dict[str, Any]] = {}
    for offset in range(0, len(ids), 80):
        chunk = ids[offset: offset + 80]
        rows, _ = await _paged(
            "ad_daily_stats",
            select="ad_id,ad_name,campaign_name,spend,stat_date",
            filters={"client_id": f"eq.{client_id}", "ad_id": f"in.({','.join(chunk)})",
                     "and": f"(stat_date.gte.{start},stat_date.lte.{end})"},
            order="stat_date.asc,ad_id.asc",
        )
        for row in rows:
            ad = out.setdefault(_text(row.get("ad_id")), {"spend": 0.0, "ad_name": None, "campaign_name": None})
            ad["spend"] += _num(row.get("spend"))
            ad["ad_name"] = row.get("ad_name") or ad["ad_name"]
            ad["campaign_name"] = row.get("campaign_name") or ad["campaign_name"]
    return out


def _in_bounds(value: Any, start: datetime, end: datetime) -> bool:
    moment = _dt(value)
    return bool(moment and start <= moment <= end)


async def build_whatsapp_insights(client_id: str, *, start: Optional[str] = None, end: Optional[str] = None) -> Dict[str, Any]:
    period = resolve_period(start=start, end=end)
    start_utc, end_utc = period.utc_bounds()
    base = {
        "ok": True,
        "period": {"start": period.start.isoformat(), "end": period.end.isoformat()},
        "attribution_label": ATTRIBUTION_LABEL,
        "window_days": CONVERSION_WINDOW_DAYS,
    }
    result = await whatsapp_sources.brand_leads(client_id, period.start.isoformat(), period.end.isoformat())
    if not result.get("available"):
        return {**base, "status": "crm_unavailable", "reason": result.get("reason")}
    if not result.get("connected"):
        return {**base, "status": "no_brand_number"}
    leads = [lead for lead in result.get("leads") or [] if _in_bounds(lead.get("first_seen_at"), start_utc, end_utc)]

    provider = (await resolve_commerce_provider(client_id)).get("provider")
    notes = [ATTRIBUTION_LABEL]
    orders_window: List[Dict[str, Any]] = []
    store_orders: List[Dict[str, Any]] = []
    truncated = bool(result.get("truncated"))
    if provider == SHOPIFY:
        window_end = end_utc + timedelta(days=CONVERSION_WINDOW_DAYS)
        orders_window, cut = await _shopify_orders(client_id, start_utc.isoformat(), window_end.isoformat())
        truncated = truncated or cut
        store_orders = [o for o in orders_window if _in_bounds(o.get("created_at_shopify"), start_utc, end_utc)]
        if window_end > datetime.now(timezone.utc):
            notes.append("Conversas dos últimos 7 dias ainda podem virar venda: os números desses dias sobem nos próximos dias.")
    crm_sales = await whatsapp_sources.brand_sales(client_id, period.start.isoformat(), period.end.isoformat())
    if crm_sales:
        orders_window = orders_window + crm_sales
        store_orders = store_orders + [o for o in crm_sales if _in_bounds(o.get("created_at_shopify"), start_utc, end_utc)]
        notes.append("Vendas: pedidos da loja e vendas registradas no CRM da marca (mesma cliente no mesmo dia = 1 venda).")
    elif provider != SHOPIFY:
        notes.append("Vendas pelo WhatsApp aparecem quando a loja Shopify estiver conectada.")

    ad_ids = [_text((lead.get("origin") or {}).get("ad_id")) for lead in leads]
    stats = await _ad_stats(client_id, ad_ids, period.start.isoformat(), period.end.isoformat())
    data = aggregate(leads, orders_window, store_orders, stats)
    if any(origin_bucket(lead.get("origin")) == "ad" and not _text((lead.get("origin") or {}).get("ad_id")) for lead in leads):
        notes.append("Conversas de anúncio anteriores à captura do ID do anúncio aparecem como anúncio, mas sem custo por anúncio.")
    return {**base, "status": "partial" if truncated else "available", "provider": provider,
            "truncated": truncated, "notes": notes, **data}


async def build_whatsapp_inbox(client_id: str, *, limit: int = 60) -> Dict[str, Any]:
    """Caixa de entrada do número da marca, com a origem e o selo de compra de cada conversa."""
    result = await whatsapp_sources.brand_conversations(client_id, limit=limit)
    if not result.get("available"):
        return {"ok": True, "status": "crm_unavailable", "reason": result.get("reason"), "conversations": []}
    if not result.get("connected"):
        return {"ok": True, "status": "no_brand_number", "conversations": []}
    conversations = result.get("conversations") or []

    purchases: Dict[str, Dict[str, Any]] = {}
    provider = (await resolve_commerce_provider(client_id)).get("provider")
    now = datetime.now(timezone.utc)
    orders: List[Dict[str, Any]] = []
    if conversations:
        if provider == SHOPIFY:
            orders = await _recent_shopify_orders(client_id, (now - timedelta(days=INBOX_ORDER_DAYS)).isoformat())
        brt_today = (now - timedelta(hours=3)).date()
        orders = orders + await whatsapp_sources.brand_sales(
            client_id, (brt_today - timedelta(days=INBOX_ORDER_DAYS)).isoformat(), brt_today.isoformat())
    if orders:
        # Primeiro contato de cada telefone: pedido feito ANTES dele não é venda do WhatsApp.
        first_seen: Dict[str, Optional[datetime]] = {}
        for c in conversations:
            contact = c.get("contact") or {}
            key = _text(contact.get("phone_key"))
            if not key:
                continue
            seen = _dt(contact.get("first_seen_at"))
            previous = first_seen.get(key)
            first_seen[key] = min(previous, seen) if previous and seen else (previous or seen)
        for order in orders:
            bought = _dt(order.get("created_at_shopify"))
            for key in order_phone_keys(order):
                if key not in first_seen:
                    continue
                seen = first_seen[key]
                if seen is None or (bought is not None and bought >= seen - timedelta(minutes=5)):
                    row = purchases.setdefault(key, {"orders": 0, "revenue": 0.0, "last_order": None, "last_order_at": None})
                    row["orders"] += 1
                    row["revenue"] += _num(order.get("value"))
                    if not row["last_order_at"] or _text(order.get("created_at_shopify")) > row["last_order_at"]:
                        row["last_order"] = order.get("name")
                        row["last_order_at"] = _text(order.get("created_at_shopify"))
                    break

    out = []
    for conv in conversations:
        contact = dict(conv.get("contact") or {})
        key = _text(contact.pop("phone_key", None))
        purchase = purchases.get(key)
        origin = conv.get("origin") or {}
        out.append({
            **{k: v for k, v in conv.items() if k not in {"contact", "origin"}},
            "contact": contact,
            "origin": {**origin, "bucket": origin_bucket(origin), "label": origin_label(origin)},
            "purchase": {**purchase, "revenue": round(purchase["revenue"], 2)} if purchase else None,
        })
    return {"ok": True, "status": "available", "provider": provider, "conversations": out}
