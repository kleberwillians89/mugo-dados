"""Vendas por origem: pedidos, receita e ticket por canal e campanha (UTM).

Lê só o que está persistido (sem chamar Shopify, FBITS ou IA). Usa a MESMA
regra de receita de cada plataforma:

- Shopify: pedido não cancelado conta; valor = total_price (regra de
  `compute_shopify_revenue`). Reembolsos não são distribuídos por origem.
- FBITS: pedido conta quando a situação está nas situações de receita da
  conexão e `valido` não é falso (regra de `_counts_as_revenue`). O total aqui
  é dos pedidos persistidos e pode diferir do indicador oficial da loja.

Atribuição: último clique com UTM registrado pela loja; sem UTM, o
identificador de clique do Google Ads (gclid) marca o pedido como Google
Ads, sem campanha; sem nenhum dos dois, vale a origem que o GA4 registrou para
a mesma transação (ID do pedido no evento purchase). Pedido sem origem
fica em "Origem não identificada" e nunca é distribuído entre campanhas.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any, Dict, List, Optional

import httpx

from .commerce_context import FBITS, SHOPIFY, resolve_commerce_provider
from .ig_supabase import _is_column_compat_error, sb_select, sb_update
from .order_attribution import (
    ATTRIBUTION_COLUMNS, CHANNEL_LABELS, classify_channel, fbits_order_attribution, fbits_order_from_raw,
    shopify_order_attribution,
)
from .periods import resolve_period

PAGE_SIZE = 1000
MAX_ROWS = 20000
ATTRIBUTION_MODEL = "last_click_utm"
ATTRIBUTION_MODEL_LABEL = "Último clique com UTM registrado pela loja; sem UTM, a origem que o GA4 registrou para o mesmo pedido"
GOOGLE_ADS_NO_CAMPAIGN = "Google Ads (campanha não informada no pedido)"
ORIGIN_SELECT = "utm_source,utm_medium,utm_campaign,utm_content,origin_channel,origin_detail,referrer_domain,attribution_source"


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _num(value: Any) -> float:
    try:
        return float(str(value if value is not None else 0).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


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


def _origin_key(row: Dict[str, Any]) -> Dict[str, Any]:
    channel = _text(row.get("origin_channel")) or "unknown"
    if channel not in CHANNEL_LABELS:
        channel = "unknown"
    if _text(row.get("attribution_source")) == "click_id" and not _text(row.get("utm_campaign")):
        # Clique do Google Ads sem UTM: aparece como Google Ads, sem inventar campanha.
        return {"channel": channel, "channel_label": CHANNEL_LABELS[channel], "source": "google", "medium": "cpc",
                "campaign": GOOGLE_ADS_NO_CAMPAIGN}
    return {
        "channel": channel,
        "channel_label": CHANNEL_LABELS[channel],
        "source": _text(row.get("utm_source")) or _text(row.get("referrer_domain")) or None,
        "medium": _text(row.get("utm_medium")) or None,
        "campaign": _text(row.get("utm_campaign")) or None,
    }


def aggregate_sales_by_origin(orders: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Agrupa pedidos já filtrados pela regra de receita.

    Cada pedido: {"value": float, + colunas de origem}. Função pura (testável).
    """
    total_orders = len(orders)
    total_revenue = round(sum(_num(order.get("value")) for order in orders), 2)
    by_channel: Dict[str, Dict[str, Any]] = {}
    by_campaign: Dict[tuple, Dict[str, Any]] = {}
    sources = defaultdict(int)
    for order in orders:
        key = _origin_key(order)
        value = _num(order.get("value"))
        sources[_text(order.get("attribution_source")) or "none"] += 1
        channel = by_channel.setdefault(key["channel"], {
            "channel": key["channel"], "label": key["channel_label"], "orders": 0, "revenue": 0.0,
        })
        channel["orders"] += 1
        channel["revenue"] += value
        campaign_key = (key["channel"], key["source"], key["medium"], key["campaign"])
        campaign = by_campaign.setdefault(campaign_key, {**key, "orders": 0, "revenue": 0.0})
        campaign["orders"] += 1
        campaign["revenue"] += value

    def finish(row: Dict[str, Any]) -> Dict[str, Any]:
        row["revenue"] = round(row["revenue"], 2)
        row["average_ticket"] = round(row["revenue"] / row["orders"], 2) if row["orders"] else None
        row["share_of_revenue"] = round(row["revenue"] / total_revenue * 100, 2) if total_revenue else None
        return row

    channels = sorted((finish(row) for row in by_channel.values()), key=lambda r: (r["channel"] == "unknown", -r["revenue"]))
    campaigns = sorted(
        (finish(row) for row in by_campaign.values() if row["campaign"]),
        key=lambda r: -r["revenue"],
    )
    identified = total_orders - sources.get("none", 0)
    return {
        "totals": {
            "orders": total_orders,
            "revenue": total_revenue,
            "average_ticket": round(total_revenue / total_orders, 2) if total_orders else None,
            "orders_with_origin": identified,
            "orders_with_utm": sources.get("utm", 0),
            "orders_with_google_click": sources.get("click_id", 0),
            "origin_coverage_percent": round(identified / total_orders * 100, 2) if total_orders else None,
            "utm_coverage_percent": round(sources.get("utm", 0) / total_orders * 100, 2) if total_orders else None,
        },
        "channels": channels,
        "campaigns": campaigns[:50],
    }


async def _shopify_orders(client_id: str, start_iso: str, end_iso: str) -> tuple[List[Dict[str, Any]], bool]:
    rows, truncated = await _paged(
        "shopify_orders",
        select=f"shopify_order_id,order_number,name,total_price,cancelled_at,cancel_reason,created_at_shopify,{ORIGIN_SELECT}",
        filters={"client_id": f"eq.{client_id}", "and": f"(created_at_shopify.gte.{start_iso},created_at_shopify.lte.{end_iso})"},
        order="created_at_shopify.asc,shopify_order_id.asc",
    )
    recognized = [
        {**row, "value": max(0.0, _num(row.get("total_price")))}
        for row in rows
        if not (_text(row.get("cancelled_at")) or _text(row.get("cancel_reason")))
    ]
    return recognized, truncated


async def _fbits_orders(client_id: str, start_iso: str, end_iso: str) -> tuple[List[Dict[str, Any]], bool]:
    from .fbits_reporting import _counts_as_revenue, _tenant_revenue_context

    _connected, revenue_status_ids, _connection = await _tenant_revenue_context(client_id)
    rows, truncated = await _paged(
        "fbits_orders",
        select=f"order_id,total_value,status_id,is_valid,raw,order_date,{ORIGIN_SELECT}",
        filters={"client_id": f"eq.{client_id}", "and": f"(order_date.gte.{start_iso},order_date.lte.{end_iso})"},
        order="order_date.asc,order_id.asc",
    )
    recognized = [
        {**{k: v for k, v in row.items() if k != "raw"}, "value": _num(row.get("total_value"))}
        for row in rows if _counts_as_revenue(row, revenue_status_ids)
    ]
    return recognized, truncated


_GA4_PLACEHOLDER_CAMPAIGNS = {"(organic)", "(direct)", "(referral)", "(not set)", "(none)", "(cross-network)",
                              "(data not available)", "(not provided)"}


def _order_keys(order: Dict[str, Any]) -> List[str]:
    """IDs com que a loja pode ter enviado a transação ao GA4."""
    keys: List[str] = []
    for field in ("order_id", "shopify_order_id", "order_number", "name"):
        value = _text(order.get(field))
        for candidate in (value, value.lstrip("#").strip()):
            if candidate and candidate not in keys:
                keys.append(candidate)
    return keys


def ga4_origin(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Origem do pedido a partir da linha do GA4 da mesma transação (ou None)."""
    source, medium = _text(row.get("source")), _text(row.get("medium"))
    if not source or source.lower() in {"(not set)", "(data not available)"}:
        return None
    if source.lower() == "(direct)" and medium.lower() in {"(none)", "(not set)", ""}:
        channel = "direct"
    else:
        channel = classify_channel(utm_source=source, utm_medium=medium)
    campaign = _text(row.get("campaign_name"))
    return {
        "utm_source": source, "utm_medium": medium or None,
        "utm_campaign": None if campaign.lower() in _GA4_PLACEHOLDER_CAMPAIGNS else (campaign or None),
        "utm_content": None,
        "origin_channel": channel, "origin_detail": "GA4", "referrer_domain": None,
        "attribution_source": "ga4",
    }


async def _ga4_transactions(client_id: str, start: str, end: str) -> Dict[str, Dict[str, Any]]:
    """Transações do GA4 da empresa, por ID, numa janela com folga de 2 dias.

    Tabela ausente (migração 048 pendente) ou erro: devolve vazio e a tela segue
    só com a origem registrada pela loja.
    """
    try:
        rows, _truncated = await _paged(
            "ga4_transaction_attribution",
            select="client_id,transaction_id,stat_date,source,medium,campaign_name",
            filters={"client_id": f"eq.{client_id}", "and": f"(stat_date.gte.{start},stat_date.lte.{end})"},
            order="stat_date.asc,transaction_id.asc",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[sales_by_origin][ga4] client_id={client_id} status=unavailable error={exc.__class__.__name__}")
        return {}
    return {_text(row.get("transaction_id")): row for row in rows
            if _text(row.get("client_id")) == client_id and _text(row.get("transaction_id"))}


def merge_ga4_origins(orders: List[Dict[str, Any]], transactions: Dict[str, Dict[str, Any]]) -> int:
    """Preenche, só nos pedidos SEM origem, a origem do GA4 da mesma transação."""
    matched = 0
    if not transactions:
        return matched
    for order in orders:
        if (_text(order.get("origin_channel")) or "unknown") != "unknown":
            continue
        row = next((transactions[key] for key in _order_keys(order) if key in transactions), None)
        origin = ga4_origin(row) if row else None
        if origin:
            order.update(origin)
            matched += 1
    return matched


async def build_sales_by_origin(client_id: str, *, start: Optional[str] = None, end: Optional[str] = None) -> Dict[str, Any]:
    period = resolve_period(start=start, end=end)
    start_utc, end_utc = period.utc_bounds()
    resolution = await resolve_commerce_provider(client_id)
    provider = resolution.get("provider")
    base = {
        "ok": True,
        "period": {"start": period.start.isoformat(), "end": period.end.isoformat()},
        "provider": provider,
        "attribution_model": ATTRIBUTION_MODEL,
        "attribution_model_label": ATTRIBUTION_MODEL_LABEL,
    }
    if provider not in {SHOPIFY, FBITS}:
        return {**base, "status": "not_connected", "totals": None, "channels": [], "campaigns": []}
    loader = _shopify_orders if provider == SHOPIFY else _fbits_orders
    try:
        orders, truncated = await loader(client_id, start_utc.isoformat(), end_utc.isoformat())
    except httpx.HTTPStatusError as exc:
        # Colunas de origem ainda não migradas: diz isso em vez de mostrar zero.
        if any(_is_column_compat_error(exc, column) for column in ATTRIBUTION_COLUMNS):
            print(f"[sales_by_origin] client_id={client_id} provider={provider} status=migration_pending")
            return {**base, "status": "migration_pending", "totals": None, "channels": [], "campaigns": []}
        raise
    window_start = (period.start - timedelta(days=2)).isoformat()
    window_end = (period.end + timedelta(days=2)).isoformat()
    matched = merge_ga4_origins(orders, await _ga4_transactions(client_id, window_start, window_end))
    result = aggregate_sales_by_origin(orders)
    result["totals"]["orders_with_ga4_origin"] = matched
    notes = [
        "Receita da loja por origem do pedido. Não é a receita atribuída pelo Meta ou pelo Google.",
        "Pedidos sem UTM nem referência ficam em \"Origem não identificada\" e não são distribuídos entre campanhas.",
    ]
    if matched:
        notes.append(f"{matched} pedido(s) sem UTM receberam a origem e a campanha que o GA4 registrou para a mesma transação.")
    if provider == FBITS:
        notes.append("Total calculado a partir dos pedidos persistidos; pode diferir do indicador oficial da loja.")
    if provider == SHOPIFY:
        notes.append("Reembolsos não são distribuídos por origem; o total é o faturamento bruto dos pedidos não cancelados.")
    return {**base, "status": "partial" if truncated else "available", "truncated": truncated, "notes": notes, **result}


async def backfill_shopify_attribution(client_id: str, *, dry_run: bool = False, limit: int = 20000) -> Dict[str, Any]:
    """Preenche a origem dos pedidos Shopify já gravados, a partir do raw_payload.

    Nenhuma chamada à Shopify: o pedido completo já está salvo. Só toca linhas
    com `origin_channel` vazio, então pode ser repetido sem efeito colateral.
    """
    updated = 0
    scanned = 0
    channels: Dict[str, int] = defaultdict(int)
    while scanned < limit:
        page = await sb_select(
            "shopify_orders",
            select="id,shop_domain,raw_payload",
            filters={"client_id": f"eq.{client_id}", "origin_channel": "is.null"},
            order="id.asc",
            limit=200,
            # Em dry-run nada é gravado; é preciso avançar a página manualmente.
            offset=scanned if dry_run else 0,
        )
        if not page:
            break
        for row in page:
            scanned += 1
            attribution = shopify_order_attribution(row.get("raw_payload") or {}, shop_domain=_text(row.get("shop_domain")))
            channels[attribution["origin_channel"] or "unknown"] += 1
            if not dry_run:
                await sb_update(
                    "shopify_orders",
                    filters={"id": f"eq.{row['id']}", "client_id": f"eq.{client_id}"},
                    patch=attribution,
                    returning="minimal",
                )
                updated += 1
        if len(page) < 200:
            break
    print(f"[attribution][backfill] provider=shopify client_id={client_id} scanned={scanned} updated={updated} dry_run={dry_run}")
    return {"ok": True, "provider": "shopify", "scanned": scanned, "updated": updated, "dry_run": dry_run,
            "channels": dict(sorted(channels.items(), key=lambda item: -item[1]))}


_REPROCESS_SOURCES = {
    "shopify": ("shopify_orders", "id,shop_domain,raw_payload,origin_channel"),
    "fbits": ("fbits_orders", "id,raw,origin_channel"),
}


def _recompute(provider: str, row: Dict[str, Any]) -> Dict[str, Optional[str]]:
    if provider == "shopify":
        return shopify_order_attribution(row.get("raw_payload") or {}, shop_domain=_text(row.get("shop_domain")))
    return fbits_order_attribution(fbits_order_from_raw(row.get("raw") or {}))


async def reprocess_unknown_origins(
    client_id: str, *, provider: Optional[str] = None, dry_run: bool = True, limit: int = MAX_ROWS,
) -> Dict[str, Any]:
    """Recalcula a origem dos pedidos SEM origem, a partir do que já está salvo.

    Nenhuma chamada à loja. Só toca pedidos com origem vazia ou "unknown" e só
    grava quando a nova regra encontra uma origem (ex.: gclid do Google Ads).
    Pedido com origem já identificada nunca é alterado. Sem dados pessoais no
    retorno nem no log: só contagens.
    """
    providers = [provider] if provider else list(_REPROCESS_SOURCES)
    report: Dict[str, Any] = {"ok": True, "client_id": client_id, "dry_run": dry_run, "providers": {}}
    for name in providers:
        if name not in _REPROCESS_SOURCES:
            raise ValueError("provider inválido")
        table, select = _REPROCESS_SOURCES[name]
        scanned = changed = 0
        found: Dict[str, int] = defaultdict(int)
        last_id = ""
        while scanned < limit:
            filters = {"client_id": f"eq.{client_id}", "or": "(origin_channel.is.null,origin_channel.eq.unknown)"}
            if last_id:
                filters["id"] = f"gt.{last_id}"
            try:
                page = await sb_select(table, select=select, filters=filters, order="id.asc", limit=200)
            except httpx.HTTPStatusError as exc:
                if _is_column_compat_error(exc, "origin_channel"):
                    report["providers"][name] = {"status": "migration_pending"}
                    break
                raise
            if not page:
                break
            for row in page:
                last_id = _text(row.get("id"))
                scanned += 1
                attribution = _recompute(name, row)
                channel = attribution.get("origin_channel") or "unknown"
                if channel == "unknown":
                    continue
                found[f"{channel}:{attribution.get('attribution_source')}"] += 1
                changed += 1
                if not dry_run:
                    await sb_update(
                        table,
                        filters={"id": f"eq.{last_id}", "client_id": f"eq.{client_id}"},
                        patch=attribution,
                        returning="minimal",
                    )
            if len(page) < 200:
                break
        report["providers"].setdefault(name, {
            "scanned_without_origin": scanned,
            "origin_found": changed,
            "updated": 0 if dry_run else changed,
            "by_channel": dict(sorted(found.items(), key=lambda item: -item[1])),
        })
        print(f"[attribution][reprocess] provider={name} client_id={client_id} scanned={scanned} "
              f"found={changed} dry_run={dry_run}")
    return report
