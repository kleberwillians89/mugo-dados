"""Pedidos de teste não são venda: nunca entram nos indicadores.

Regra (a mesma para ingestão e limpeza):
- Shopify marcou como teste (`test: true`, gateway de teste);
- a loja marcou com a tag "teste" ou "test";
- pedido a R$ 0 com cupom cobrindo o valor dos produtos (cupom de 100%),
  o jeito comum de testar o checkout de verdade.

Pedidos de teste não são gravados. Os que já estão no banco saem com
`cleanup_test_orders` (simulação antes, só administrador), e o read model é
recalculado nos dias afetados. Nenhum outro pedido é tocado.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

from .ig_supabase import sb_delete, sb_select

TZ = ZoneInfo("America/Sao_Paulo")
_TEST_TAGS = {"teste", "test", "pedido teste", "pedido de teste"}


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _tags(value: Any) -> set:
    if isinstance(value, list):
        items = value
    else:
        items = str(value or "").split(",")
    return {str(item).strip().lower() for item in items if str(item).strip()}


def is_test_shopify_order(payload: Dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("test") is True:
        return True
    if _tags(payload.get("tags")) & _TEST_TAGS:
        return True
    total = _num(payload.get("total_price"))
    items_value = _num(payload.get("total_line_items_price") or payload.get("subtotal_price"))
    coupons = [code for code in payload.get("discount_codes") or [] if isinstance(code, dict) and code.get("code")]
    discounts = _num(payload.get("total_discounts"))
    return total <= 0 and items_value > 0 and bool(coupons) and discounts >= items_value - 0.01


def is_test_fbits_order(row: Dict[str, Any]) -> bool:
    """`row` = pedido FBITS já normalizado (fbits_orders)."""
    if not isinstance(row, dict):
        return False
    total = _num(row.get("total_value"))
    subtotal = _num(row.get("subtotal_value"))
    return total <= 0 and subtotal > 0 and bool(str(row.get("coupon_code") or "").strip())


def _local_day(value: Any) -> Optional[str]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (parsed.astimezone(TZ) if parsed.tzinfo else parsed).date().isoformat()


async def _paged(table: str, select: str, client_id: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    offset = 0
    while True:
        page = await sb_select(table, select=select, filters={"client_id": f"eq.{client_id}"},
                               order="created_at.asc", limit=1000, offset=offset)
        rows.extend(row for row in page if str(row.get("client_id")) == client_id)
        if len(page) < 1000 or offset >= 50000:
            return rows
        offset += 1000


async def find_test_orders(client_id: str) -> Dict[str, Any]:
    shopify = [
        {"order_id": str(row["shopify_order_id"]), "day": _local_day(row.get("created_at_shopify"))}
        for row in await _paged("shopify_orders", "client_id,shopify_order_id,created_at_shopify,raw_payload", client_id)
        if row.get("shopify_order_id") and is_test_shopify_order(row.get("raw_payload") or {})
    ]
    fbits = [
        # Mesmo recorte de dia do fbits_order_daily_stats (data do pedido como veio).
        {"order_id": str(row["order_id"]), "day": str(row.get("order_date") or "")[:10] or None}
        for row in await _paged("fbits_orders", "client_id,order_id,order_date,total_value,subtotal_value,coupon_code", client_id)
        if row.get("order_id") and is_test_fbits_order(row)
    ]
    return {"shopify": shopify, "fbits": fbits}


def _in_list(ids: Iterable[str]) -> str:
    return "in.(" + ",".join(f'"{value}"' for value in ids) + ")"


async def cleanup_test_orders(client_id: str, *, dry_run: bool = True) -> Dict[str, Any]:
    found = await find_test_orders(client_id)
    summary = {
        "ok": True, "client_id": client_id, "dry_run": dry_run,
        "shopify_test_orders": len(found["shopify"]), "fbits_test_orders": len(found["fbits"]),
        "days": sorted({o["day"] for o in found["shopify"] + found["fbits"] if o["day"]}),
    }
    if dry_run or not (found["shopify"] or found["fbits"]):
        return summary
    if found["shopify"]:
        ids = [o["order_id"] for o in found["shopify"]]
        for chunk in range(0, len(ids), 100):
            part = ids[chunk:chunk + 100]
            filters = {"client_id": f"eq.{client_id}", "shopify_order_id": _in_list(part)}
            await sb_delete("shopify_order_items", filters=filters, returning="minimal")
            await sb_delete("shopify_refunds", filters=filters, returning="minimal")
            await sb_delete("shopify_orders", filters=filters, returning="minimal")
        days = sorted({o["day"] for o in found["shopify"] if o["day"]})
        if days:
            from .dashboard_read_model import refresh_dashboard_read_model
            await refresh_dashboard_read_model(client_id=client_id, start=days[0], end=days[-1], provider="shopify")
    if found["fbits"]:
        ids = [o["order_id"] for o in found["fbits"]]
        for chunk in range(0, len(ids), 100):
            part = ids[chunk:chunk + 100]
            filters = {"client_id": f"eq.{client_id}", "order_id": _in_list(part)}
            await sb_delete("fbits_order_items", filters=filters, returning="minimal")
            await sb_delete("fbits_orders", filters=filters, returning="minimal")
        from .fbits_connections import _refresh_daily_stats, load_fbits_connection
        row = await load_fbits_connection(client_id) or {}
        revenue_status_ids = [str(v) for v in (row.get("metadata") or {}).get("revenue_status_ids") or []]
        await _refresh_daily_stats(client_id, {o["day"] for o in found["fbits"] if o["day"]}, revenue_status_ids)
    print(f"[test_orders][cleanup] client_id={client_id} shopify={summary['shopify_test_orders']} fbits={summary['fbits_test_orders']}")
    return summary
