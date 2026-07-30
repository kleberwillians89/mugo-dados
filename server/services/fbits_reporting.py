from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List

import httpx

from .fbits_client import (
    FBITS_APPROVED_ORDER_STATUSES,
    FBITS_APPROVED_ORDER_STATUS_IDS,
    fbits_is_configured,
    fetch_fbits_orders,
    fetch_fbits_orders_with_diagnostics,
    fetch_fbits_revenue_dashboard,
)
from .ig_supabase import sb_select, sb_upsert


APPROVED_ORDER_STATUS_IDS = {
    int(value)
    for value in FBITS_APPROVED_ORDER_STATUSES.split(",")
    if value.strip().isdigit()
}


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _safe_float(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "."))
    except Exception:
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except Exception:
        return 0


def _nested_value(source: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _safe_str(source.get(key))
        if value:
            return value
    return ""


@dataclass(frozen=True)
class FbitsPeriod:
    start: str
    end: str


def resolve_fbits_period(*, start: str | None, end: str | None, days: int = 30) -> FbitsPeriod:
    if start and end:
        return FbitsPeriod(start=start, end=end)
    until = date.today()
    since = until - timedelta(days=max(1, int(days)) - 1)
    return FbitsPeriod(start=since.isoformat(), end=until.isoformat())


def _customer_key(order: Dict[str, Any]) -> str:
    for row in (order.get("usuario"), order.get("cliente"), order.get("comprador"), order):
        if not isinstance(row, dict):
            continue
        for key in (
            "usuarioId",
            "clienteId",
            "idCliente",
            "customer_id",
            "customerId",
            "id",
            "customerEmail",
            "email",
            "documento",
            "cpf",
            "cnpj",
        ):
            value = _safe_str(row.get(key))
            if value:
                return f"{key}:{value.lower()}"
    return ""


def _customer_fields(order: Dict[str, Any]) -> Dict[str, str]:
    user = order.get("usuario")
    user_row = user if isinstance(user, dict) else {}
    customer = order.get("cliente")
    customer_row = customer if isinstance(customer, dict) else {}
    buyer = order.get("comprador")
    buyer_row = buyer if isinstance(buyer, dict) else {}
    return {
        "id": _nested_value(user_row, "usuarioId", "id", "clienteId")
        or _nested_value(customer_row, "id", "clienteId", "usuarioId")
        or _nested_value(buyer_row, "id", "clienteId", "idCliente", "customer_id")
        or _nested_value(order, "usuarioId", "clienteId", "idCliente", "customer_id", "customerId"),
        "name": _nested_value(user_row, "nome", "name", "nomeCompleto")
        or _nested_value(customer_row, "nome", "name", "nomeCompleto")
        or _nested_value(buyer_row, "nome", "name", "nomeCompleto")
        or _nested_value(order, "nomeCliente", "customerName"),
        "email": _nested_value(user_row, "email")
        or _nested_value(customer_row, "email", "customerEmail")
        or _nested_value(buyer_row, "email", "customerEmail")
        or _nested_value(order, "email", "customerEmail"),
        "document": _nested_value(user_row, "documento", "cpf", "cnpj")
        or _nested_value(customer_row, "documento", "cpf", "cnpj")
        or _nested_value(buyer_row, "documento", "cpf", "cnpj")
        or _nested_value(order, "documento", "cpf", "cnpj"),
    }


def _items(order: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for key in ("itens", "produtos", "items", "pedidoItens", "produtosPedido"):
        rows = order.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _products_sold(order: Dict[str, Any]) -> int:
    total = 0
    for item in _items(order):
        total += max(0, _safe_int(item.get("quantidade") or item.get("qtd") or item.get("quantity")))
    return total


def _product_image_url(*sources: Dict[str, Any]) -> str:
    for source in sources:
        for key in ("urlImagem", "imagem", "image", "imageUrl", "media_url", "thumbnail_url"):
            value = source.get(key)
            if isinstance(value, str) and value.strip().startswith(("http://", "https://")):
                return value.strip()
            if isinstance(value, dict):
                nested = _nested_value(value, "url", "urlImagem", "src", "link")
                if nested:
                    return nested
        for key in ("imagens", "images", "midias", "medias"):
            rows = source.get(key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict):
                    nested = _nested_value(row, "url", "urlImagem", "src", "link", "urlMiniatura")
                    if nested:
                        return nested
    return ""


def _item_product_row(item: Dict[str, Any]) -> Dict[str, Any]:
    product = item.get("produto")
    product_row = product if isinstance(product, dict) else {}
    detail = item.get("produtoDetalhe")
    detail_row = detail if isinstance(detail, dict) else {}
    quantity = max(0, _safe_int(item.get("quantidade") or item.get("qtd") or item.get("quantity")))
    revenue = 0.0
    for key in ("valorTotal", "total", "receita", "precoTotal"):
        if item.get(key) not in (None, ""):
            revenue = _safe_float(item.get(key))
            break
    unit_value = _safe_float(
        item.get("precoPor")
        or item.get("precoVenda")
        or item.get("preco")
        or item.get("precoUnitario")
        or item.get("valorUnitario")
        or item.get("unitValue")
        or item.get("price")
    )
    item_value = _safe_float(item.get("valorItemArredondado") or item.get("valorItem") or item.get("valor"))
    if not unit_value and item_value:
        unit_value = item_value
    if not unit_value and revenue and quantity:
        unit_value = revenue / quantity
    if not revenue:
        revenue = (item_value or unit_value) * quantity
    product_id = (
        _nested_value(item, "produtoVarianteId", "produtoId", "idProduto", "sku", "codigo", "id")
        or _nested_value(product_row, "produtoVarianteId", "id", "produtoId", "sku", "codigo")
        or _nested_value(detail_row, "produtoVarianteId", "produtoId", "id")
    )
    name = (
        _nested_value(item, "nome", "nomeProduto", "descricao", "title", "name")
        or _nested_value(product_row, "nome", "nomeProduto", "descricao", "title", "name")
        or _nested_value(detail_row, "nomeProduto", "nome", "descricao", "title", "name")
        or (_safe_str(product) if not isinstance(product, dict) else "")
        or "Produto FBits"
    )
    return {
        "product_id": product_id or name.lower(),
        "sku": _nested_value(item, "sku", "codigo", "codigoProduto")
        or _nested_value(product_row, "sku", "codigo", "codigoProduto")
        or _nested_value(detail_row, "sku", "codigo", "codigoProduto"),
        "produto": name,
        "quantidade": quantity,
        "valor_unitario": round(unit_value, 2),
        "receita": round(revenue, 2),
        "imagem": _product_image_url(item, product_row, detail_row) or None,
    }


def _order_products(order: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        product
        for item in _items(order)
        for product in [_item_product_row(item)]
        if product["quantidade"] > 0 or product["receita"] > 0
    ]


def _products_ranking(orders: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for order in orders:
        for product in _order_products(order):
            product_id = _safe_str(product.get("product_id")) or _safe_str(product.get("produto")).lower()
            bucket = grouped.setdefault(
                product_id,
                {
                    "product_id": product_id,
                    "sku": _safe_str(product.get("sku")) or None,
                    "produto": _safe_str(product.get("produto")) or "Produto FBits",
                    "quantidade": 0,
                    "receita": 0.0,
                    "imagem": _safe_str(product.get("imagem")) or None,
                },
            )
            bucket["quantidade"] += _safe_int(product.get("quantidade"))
            bucket["receita"] += _safe_float(product.get("receita"))
            if not bucket.get("imagem"):
                bucket["imagem"] = _safe_str(product.get("imagem")) or None
    rows = list(grouped.values())
    for row in rows:
        row["receita"] = round(_safe_float(row.get("receita")), 2)
    return sorted(
        rows,
        key=lambda row: (_safe_int(row.get("quantidade")), _safe_float(row.get("receita"))),
        reverse=True,
    )


def _order_total(order: Dict[str, Any]) -> float:
    for key in (
        "valorTotalPedido",
        "valorTotal",
        "total",
        "valorPedido",
        "valorPago",
    ):
        value = order.get(key)
        if value not in (None, ""):
            return _safe_float(value)
    return 0.0


def _order_id(order: Dict[str, Any]) -> str:
    return _nested_value(order, "idPedido", "pedidoId", "codigoPedido", "id", "codigo")


def _order_code(order: Dict[str, Any]) -> str:
    return _nested_value(order, "codigoPedido", "codigo", "numeroPedido", "pedido")


def _status_id(order: Dict[str, Any]) -> str:
    return _nested_value(order, "situacaoPedidoId", "statusId", "situacaoId")


def _status_name(order: Dict[str, Any]) -> str:
    situation = order.get("situacaoPedido")
    situation_row = situation if isinstance(situation, dict) else {}
    return _nested_value(order, "situacaoPedidoNome", "statusName", "situacao") or _nested_value(
        situation_row, "nome", "descricao", "name"
    )


def _parse_timestamp(value: Any) -> str | None:
    raw = _safe_str(value)
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = datetime.strptime(raw[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def _order_date(order: Dict[str, Any]) -> str | None:
    return _parse_timestamp(
        _nested_value(order, "data", "dataPedido", "dataCriacao", "createdAt", "orderDate")
    )


def _approved_at(order: Dict[str, Any]) -> str | None:
    return _parse_timestamp(
        _nested_value(order, "dataPagamento", "dataAprovacao", "approvedAt", "paidAt")
    )


def _payment_method(order: Dict[str, Any]) -> str:
    for value in (order.get("formaPagamento"), order.get("pagamento"), order.get("meioPagamento")):
        if isinstance(value, list):
            for row in value:
                if not isinstance(row, dict):
                    continue
                info_rows = row.get("informacoesAdicionais")
                if isinstance(info_rows, list):
                    for info in info_rows:
                        if not isinstance(info, dict):
                            continue
                        key = _safe_str(info.get("chave")).lower()
                        if key in {"paymentmethod", "grupo forma pagamento - nome exibicao"}:
                            text = _safe_str(info.get("valor"))
                            if text:
                                return text
                text = _nested_value(row, "nome", "descricao", "formaPagamento", "name", "tipo")
                if text:
                    return text
            continue
        if isinstance(value, dict):
            text = _nested_value(value, "nome", "descricao", "formaPagamento", "name", "tipo")
            if text:
                return text
        text = _safe_str(value)
        if text:
            return text
    return _nested_value(order, "formaPagamentoNome", "payment_method", "paymentMethod")


def _payment_status(order: Dict[str, Any]) -> str:
    for value in (order.get("formaPagamento"), order.get("pagamento"), order.get("meioPagamento")):
        rows = value if isinstance(value, list) else [value]
        for row in rows:
            if not isinstance(row, dict):
                continue
            info_rows = row.get("informacoesAdicionais")
            if isinstance(info_rows, list):
                for info in info_rows:
                    if not isinstance(info, dict):
                        continue
                    key = _safe_str(info.get("chave")).lower()
                    if key in {"wakestatus", "billstatus", "lasttransactionstatus", "gatewaymessage"}:
                        text = _safe_str(info.get("valor"))
                        if text:
                            return text
            status_rows = row.get("pagamentoStatus")
            if isinstance(status_rows, list) and status_rows:
                text = _nested_value(status_rows[0], "status", "descricao", "name")
                if text:
                    return text
    return _nested_value(order, "statusPagamento", "payment_status", "paymentStatus")


def _raw_order_without_payment_secrets(order: Dict[str, Any]) -> Dict[str, Any]:
    raw = dict(order)
    for key in ("formaPagamento", "pagamento", "meioPagamento", "transacao", "transacoes"):
        raw.pop(key, None)
    return raw


def _stat_date(value: Any) -> str:
    raw = _safe_str(value)
    return raw[:10] if len(raw) >= 10 else ""


def normalize_fbits_order(order: Dict[str, Any]) -> Dict[str, Any]:
    customer = _customer_fields(order)
    return {
        "pedido_id": _order_id(order),
        "pedido_codigo": _order_code(order),
        "situacao_pedido_id": _safe_int(_status_id(order)),
        "situacao_pedido": _status_name(order),
        "data": _safe_str(_order_date(order)),
        "data_pagamento": _safe_str(_approved_at(order)) or None,
        "receita_oficial": _order_total(order),
        "produtos_vendidos": _products_sold(order),
        "cliente_key": _customer_key(order) or None,
        "cliente_id": customer["id"] or None,
        "cliente_nome": customer["name"] or None,
        "cliente_email": customer["email"] or None,
        "cliente_documento": customer["document"] or None,
        "forma_pagamento": _payment_method(order) or None,
        "status_pagamento": _payment_status(order) or None,
        "produtos": _order_products(order),
    }


def _is_approved_order(order: Dict[str, Any]) -> bool:
    included, _reason = _reconciliation_decision(order)
    return included


def _reconciliation_decision(order: Dict[str, Any]) -> tuple[bool, str]:
    if _order_id(order):
        return True, "pedido retornado por GET /pedidos na DataPedido do período"
    return False, "pedido sem identificador retornado pela FBits"


def _log_orders_by_status(*, client_id: str, orders: Iterable[Dict[str, Any]], prefix: str) -> None:
    counts: Dict[str, int] = {}
    revenue: Dict[str, float] = {}
    total = 0
    for order in orders:
        total += 1
        status = _status_id(order) or "-"
        counts[status] = counts.get(status, 0) + 1
        revenue[status] = revenue.get(status, 0.0) + _order_total(order)
    rounded_revenue = {status: round(value, 2) for status, value in sorted(revenue.items())}
    print(
        f"[fbits][{prefix}] client_id={client_id} raw_orders={total} "
        f"counts_by_status={dict(sorted(counts.items()))} revenue_by_status={rounded_revenue}"
    )


def _persisted_order_item(row: Dict[str, Any]) -> Dict[str, Any]:
    raw = row.get("raw")
    raw_order = raw if isinstance(raw, dict) else {}
    raw_customer = _customer_fields(raw_order)
    customer_key = (
        _safe_str(row.get("customer_id"))
        or _safe_str(row.get("customer_email"))
        or raw_customer["document"]
    )
    return {
        "pedido_id": _safe_str(row.get("order_id")),
        "pedido_codigo": _safe_str(row.get("order_code")),
        "situacao_pedido_id": _safe_int(row.get("status_id")),
        "situacao_pedido": _safe_str(row.get("status_name")),
        "data": _safe_str(row.get("order_date")),
        "data_pagamento": _safe_str(row.get("approved_at")) or None,
        "receita_oficial": _safe_float(row.get("total_value")),
        "produtos_vendidos": _safe_int(row.get("products_count")),
        "cliente_key": customer_key or None,
        "cliente_id": _safe_str(row.get("customer_id")) or raw_customer["id"] or None,
        "cliente_nome": _safe_str(row.get("customer_name")) or raw_customer["name"] or None,
        "cliente_email": _safe_str(row.get("customer_email")) or raw_customer["email"] or None,
        "cliente_documento": raw_customer["document"] or None,
        "forma_pagamento": _safe_str(row.get("payment_method")) or _payment_method(raw_order) or None,
        "status_pagamento": _safe_str(row.get("payment_status")) or _payment_status(raw_order) or None,
        "produtos": _order_products(raw_order),
    }


def _period_filter(period: FbitsPeriod, column: str) -> str:
    return f"({column}.gte.{period.start},{column}.lte.{period.end})"


def _is_schema_pending_error(exc: httpx.HTTPStatusError, *names: str) -> bool:
    if exc.response is None or exc.response.status_code not in {400, 404}:
        return False
    body = str(exc.response.text or "").lower()
    return any(str(name or "").lower() in body for name in names) and (
        "column" in body or "schema cache" in body or "relation" in body
    )


async def _read_persisted_orders(*, client_id: str, period: FbitsPeriod) -> List[Dict[str, Any]]:
    return await sb_select(
        "fbits_orders",
        select=(
            "client_id,order_id,order_code,customer_id,customer_name,customer_email,status_id,status_name,"
            "order_date,approved_at,total_value,products_count,payment_method,payment_status,raw,created_at,updated_at"
        ),
        filters={
            "client_id": f"eq.{client_id}",
            "and": _period_filter(period, "order_date"),
        },
        order="order_date.desc",
        limit=10000,
    )


async def _read_persisted_daily(*, client_id: str, period: FbitsPeriod) -> List[Dict[str, Any]]:
    return await sb_select(
        "fbits_order_daily_stats",
        select="client_id,stat_date,receita_oficial,pedidos,ticket_medio,clientes,produtos_vendidos,updated_at",
        filters={
            "client_id": f"eq.{client_id}",
            "and": _period_filter(period, "stat_date"),
        },
        order="stat_date.asc",
        limit=500,
    )


def _summary_from_orders(*, client_id: str, period: FbitsPeriod, orders: List[Dict[str, Any]]) -> Dict[str, Any]:
    revenue = sum(_safe_float(order.get("receita_oficial")) for order in orders)
    customer_keys = {
        _safe_str(order.get("cliente_key"))
        for order in orders
        if _safe_str(order.get("cliente_key"))
    }
    order_count = len(orders)
    print(f"[fbits][summary] client_id={client_id} receita={round(revenue, 2)} pedidos={order_count}")
    return {
        "ok": True,
        "connected": fbits_is_configured(),
        "client_id": client_id,
        "period": {"start": period.start, "end": period.end},
        "summary": {
            "receita_oficial": round(revenue, 2),
            "pedidos": order_count,
            "ticket_medio": round(revenue / order_count, 2) if order_count else 0.0,
            "clientes": len(customer_keys),
            "produtos_vendidos": sum(_safe_int(order.get("produtos_vendidos")) for order in orders),
        },
        "message": (
            None
            if order_count
            else (
                "FBits conectada, aguardando dados do período."
                if fbits_is_configured()
                else "FBits ainda não conectada."
            )
        ),
    }


def _summary_from_daily(*, client_id: str, period: FbitsPeriod, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    revenue = sum(_safe_float(row.get("receita_oficial")) for row in rows)
    order_count = sum(_safe_int(row.get("pedidos")) for row in rows)
    print(f"[fbits][summary] client_id={client_id} receita={round(revenue, 2)} pedidos={order_count}")
    return {
        "ok": True,
        "connected": True,
        "client_id": client_id,
        "period": {"start": period.start, "end": period.end},
        "summary": {
            "receita_oficial": round(revenue, 2),
            "pedidos": order_count,
            "ticket_medio": round(revenue / order_count, 2) if order_count else 0.0,
            "clientes": sum(_safe_int(row.get("clientes")) for row in rows),
            "produtos_vendidos": sum(_safe_int(row.get("produtos_vendidos")) for row in rows),
        },
        "message": None,
        "source": "supabase",
    }


def _detail_metrics_from_items(items: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    item_rows = list(items)
    customer_keys = {
        _safe_str(item.get("cliente_key"))
        for item in item_rows
        if _safe_str(item.get("cliente_key"))
    }
    return {
        "clientes": len(customer_keys),
        "produtos_vendidos": sum(_safe_int(item.get("produtos_vendidos")) for item in item_rows),
    }


def _normalized_sync_row(*, client_id: str, order: Dict[str, Any]) -> Dict[str, Any] | None:
    normalized = normalize_fbits_order(order)
    order_id = _safe_str(normalized.get("pedido_id"))
    if not order_id:
        return None
    customer = _customer_fields(order)
    return {
        "client_id": client_id,
        "order_id": order_id,
        "order_code": _order_code(order) or None,
        "customer_id": customer["id"] or None,
        "customer_name": customer["name"] or None,
        "customer_email": customer["email"] or None,
        "status_id": _status_id(order) or None,
        "status_name": _status_name(order) or None,
        "order_date": _order_date(order),
        "approved_at": _approved_at(order),
        "total_value": _safe_float(normalized.get("receita_oficial")),
        "products_count": _safe_int(normalized.get("produtos_vendidos")),
        "payment_method": _payment_method(order) or None,
        "payment_status": _payment_status(order) or None,
        "raw": _raw_order_without_payment_secrets(order),
    }


def _sync_item_rows(*, client_id: str, order_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for order_row in order_rows:
        order_id = _safe_str(order_row.get("order_id"))
        raw_order = order_row.get("raw")
        if not order_id or not isinstance(raw_order, dict):
            continue
        for index, item in enumerate(_items(raw_order), start=1):
            product = _item_product_row(item)
            item_id = _nested_value(item, "id", "itemId", "pedidoItemId", "idPedidoItem")
            if not item_id:
                item_id = f"{product.get('product_id') or product.get('sku') or 'item'}:{index}"
            rows.append(
                {
                    "client_id": client_id,
                    "order_id": order_id,
                    "item_id": item_id,
                    "product_id": _safe_str(product.get("product_id")) or None,
                    "sku": _safe_str(product.get("sku")) or None,
                    "product_name": _safe_str(product.get("produto")) or None,
                    "product_image_url": _safe_str(product.get("imagem")) or None,
                    "quantity": _safe_int(product.get("quantidade")),
                    "unit_value": _safe_float(product.get("valor_unitario")),
                    "total_value": _safe_float(product.get("receita")),
                    "raw": item,
                }
            )
    return rows


async def _read_persisted_items(*, client_id: str, order_ids: set[str]) -> List[Dict[str, Any]]:
    if not order_ids:
        return []
    rows = await sb_select(
        "fbits_order_items",
        select="client_id,order_id,item_id,product_id,sku,product_name,product_image_url,quantity,unit_value,total_value,raw",
        filters={"client_id": f"eq.{client_id}"},
        limit=20000,
    )
    return [row for row in rows if _safe_str(row.get("order_id")) in order_ids]


def _products_ranking_from_items(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key = _safe_str(row.get("product_id")) or _safe_str(row.get("sku")) or _safe_str(row.get("product_name")).lower()
        if not key:
            continue
        bucket = grouped.setdefault(
            key,
            {
                "product_id": _safe_str(row.get("product_id")) or key,
                "sku": _safe_str(row.get("sku")) or None,
                "produto": _safe_str(row.get("product_name")) or "Produto FBits",
                "quantidade": 0,
                "receita": 0.0,
                "imagem": _safe_str(row.get("product_image_url")) or None,
            },
        )
        bucket["quantidade"] += _safe_int(row.get("quantity"))
        bucket["receita"] += _safe_float(row.get("total_value"))
        if not bucket.get("imagem"):
            bucket["imagem"] = _safe_str(row.get("product_image_url")) or None
    ranked = list(grouped.values())
    for row in ranked:
        row["receita"] = round(_safe_float(row.get("receita")), 2)
    return sorted(ranked, key=lambda row: (_safe_int(row.get("quantidade")), _safe_float(row.get("receita"))), reverse=True)


def _sync_customer_key(row: Dict[str, Any]) -> str:
    raw = row.get("raw")
    raw_order = raw if isinstance(raw, dict) else {}
    return (
        _safe_str(row.get("customer_id"))
        or _safe_str(row.get("customer_email"))
        or _safe_str(_customer_fields(raw_order).get("document"))
    )


def _top_customers(orders: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for order in orders:
        key = (
            _safe_str(order.get("cliente_key"))
            or _safe_str(order.get("cliente_id"))
            or _safe_str(order.get("cliente_email"))
            or _safe_str(order.get("cliente_documento"))
        )
        if not key:
            continue
        bucket = grouped.setdefault(
            key.lower(),
            {
                "customer_id": _safe_str(order.get("cliente_id")) or None,
                "cliente": _safe_str(order.get("cliente_nome"))
                or _safe_str(order.get("cliente_email"))
                or "Cliente identificado",
                "email": _safe_str(order.get("cliente_email")) or None,
                "pedidos": 0,
                "receita": 0.0,
            },
        )
        bucket["pedidos"] += 1
        bucket["receita"] += _safe_float(order.get("receita_oficial"))
    rows = list(grouped.values())
    for row in rows:
        row["receita"] = round(_safe_float(row.get("receita")), 2)
    return sorted(
        rows,
        key=lambda row: (_safe_float(row.get("receita")), _safe_int(row.get("pedidos"))),
        reverse=True,
    )


def _daily_upsert_rows(*, client_id: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    customer_ids: Dict[str, set[str]] = {}
    for row in rows:
        day = _stat_date(row.get("order_date"))
        if not day:
            continue
        bucket = grouped.setdefault(
            day,
            {
                "client_id": client_id,
                "stat_date": day,
                "receita_oficial": 0.0,
                "pedidos": 0,
                "ticket_medio": 0.0,
                "clientes": 0,
                "produtos_vendidos": 0,
            },
        )
        bucket["receita_oficial"] += _safe_float(row.get("total_value"))
        bucket["pedidos"] += 1
        bucket["produtos_vendidos"] += _safe_int(row.get("products_count"))
        customer_key = _sync_customer_key(row)
        if customer_key:
            customer_ids.setdefault(day, set()).add(customer_key.lower())
    for day, bucket in grouped.items():
        orders = _safe_int(bucket.get("pedidos"))
        revenue = _safe_float(bucket.get("receita_oficial"))
        bucket["receita_oficial"] = round(revenue, 2)
        bucket["ticket_medio"] = round(revenue / orders, 2) if orders else 0.0
        bucket["clientes"] = len(customer_ids.get(day, set()))
    return list(grouped.values())


def _days_in_period(period: FbitsPeriod) -> List[str]:
    start = date.fromisoformat(period.start)
    end = date.fromisoformat(period.end)
    out: List[str] = []
    current = start
    while current <= end:
        out.append(current.isoformat())
        current += timedelta(days=1)
    return out


def _dashboard_daily_row(*, client_id: str, stat_date: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    revenue = _safe_float(payload.get("indicadorReceita"))
    orders = _safe_int(payload.get("indicadorPedido"))
    ticket = _safe_float(payload.get("indicadorTicketMedio"))
    return {
        "client_id": client_id,
        "stat_date": stat_date,
        "receita_oficial": round(revenue, 2),
        "pedidos": orders,
        "ticket_medio": round(ticket or (revenue / orders if orders else 0.0), 2),
        "clientes": 0,
        "produtos_vendidos": 0,
    }


async def _fetch_dashboard_daily_rows(*, client_id: str, period: FbitsPeriod) -> List[Dict[str, Any]]:
    daily_rows: List[Dict[str, Any]] = []
    for stat_date in _days_in_period(period):
        try:
            payload = await fetch_fbits_revenue_dashboard(start=stat_date, end=stat_date)
        except httpx.HTTPError as exc:
            print(f"[fbits][dashboard][day_error] client_id={client_id} stat_date={stat_date} error={exc}")
            continue
        daily_rows.append(_dashboard_daily_row(client_id=client_id, stat_date=stat_date, payload=payload))
    return daily_rows


async def sync_fbits_orders(*, client_id: str, period: FbitsPeriod) -> Dict[str, Any]:
    print(f"[fbits][sync] client_id={client_id} start={period.start} end={period.end}")
    if not fbits_is_configured():
        return {
            "ok": True,
            "connected": False,
            "client_id": client_id,
            "period": {"start": period.start, "end": period.end},
            "orders_upserted": 0,
            "daily_upserted": 0,
            "message": "FBits ainda não conectada.",
        }
    raw_orders = await fetch_fbits_orders(start=period.start, end=period.end)
    _log_orders_by_status(client_id=client_id, orders=raw_orders, prefix="sync][orders")
    rows = [
        sync_row
        for row in raw_orders
        if _is_approved_order(row)
        for sync_row in [_normalized_sync_row(client_id=client_id, order=row)]
        if sync_row
    ]
    daily_rows = _daily_upsert_rows(client_id=client_id, rows=rows)
    dashboard_fallback = False
    if not daily_rows:
        daily_rows = await _fetch_dashboard_daily_rows(client_id=client_id, period=period)
        dashboard_fallback = bool(daily_rows)
    if rows:
        try:
            await sb_upsert("fbits_orders", rows, on_conflict="client_id,order_id")
        except httpx.HTTPStatusError as exc:
            body = str((exc.response.text if exc.response is not None else "") or "").lower()
            if exc.response is None or exc.response.status_code not in {400, 404} or not any(
                column in body for column in ("payment_method", "payment_status")
            ):
                raise
            legacy_rows = []
            for row in rows:
                legacy_row = dict(row)
                legacy_row.pop("payment_method", None)
                legacy_row.pop("payment_status", None)
                legacy_rows.append(legacy_row)
            await sb_upsert("fbits_orders", legacy_rows, on_conflict="client_id,order_id")
            print(f"[fbits][orders][legacy_schema] client_id={client_id} missing=payment_method")
        item_rows = _sync_item_rows(client_id=client_id, order_rows=rows)
        item_rows_upserted = 0
        if item_rows:
            try:
                await sb_upsert("fbits_order_items", item_rows, on_conflict="client_id,order_id,item_id")
                item_rows_upserted = len(item_rows)
            except httpx.HTTPStatusError as exc:
                if exc.response is None or exc.response.status_code not in {400, 404, 409}:
                    raise
                print(f"[fbits][items][persist_warning] client_id={client_id} items={len(item_rows)}")
    else:
        item_rows = []
        item_rows_upserted = 0
    if daily_rows:
        await sb_upsert("fbits_order_daily_stats", daily_rows, on_conflict="client_id,stat_date")
    return {
        "ok": True,
        "connected": True,
        "client_id": client_id,
        "period": {"start": period.start, "end": period.end},
        "orders_upserted": len(rows),
        "items_upserted": item_rows_upserted,
        "daily_upserted": len(daily_rows),
        "daily_source": "dashboard_faturamento" if dashboard_fallback else "orders",
        "message": None
        if rows
        else "FBits conectada, aguardando dados do período.",
    }


def _value_fields(order: Dict[str, Any]) -> List[str]:
    return [
        key
        for key in ("valorTotalPedido", "valorTotal", "total", "valorPedido", "valorPago")
        if order.get(key) not in (None, "")
    ]


async def build_fbits_orders_debug(*, client_id: str, period: FbitsPeriod) -> Dict[str, Any]:
    if not fbits_is_configured():
        return {
            "ok": True,
            "connected": False,
            "client_id": client_id,
            "period": {"start": period.start, "end": period.end},
            "statuses": list(FBITS_APPROVED_ORDER_STATUS_IDS),
            "counts_by_status": {},
            "message": "FBits ainda não conectada.",
        }
    rows, counts_by_status = await fetch_fbits_orders_with_diagnostics(
        start=period.start,
        end=period.end,
    )
    first = rows[0] if rows else {}
    first_item = next(iter(_items(first)), {}) if isinstance(first, dict) else {}
    return {
        "ok": True,
        "connected": True,
        "client_id": client_id,
        "period": {"start": period.start, "end": period.end},
        "statuses": list(FBITS_APPROVED_ORDER_STATUS_IDS),
        "counts_by_status": counts_by_status,
        "orders_after_dedupe": len(rows),
        "first_order_keys": sorted(str(key) for key in first.keys())[:80],
        "first_item_keys": sorted(str(key) for key in first_item.keys())[:80] if isinstance(first_item, dict) else [],
        "first_item_value_fields": [
            str(key)
            for key, value in (first_item.items() if isinstance(first_item, dict) else [])
            if "valor" in str(key).lower() or "preco" in str(key).lower() or "price" in str(key).lower()
            if value not in (None, "")
        ][:30],
        "value_fields_found": _value_fields(first),
        "message": None if rows else "FBits conectada, aguardando dados do período.",
    }


async def build_fbits_reconciliation_debug(*, client_id: str, period: FbitsPeriod) -> Dict[str, Any]:
    target_revenue = 17950.65
    target_orders = 44
    target_aov = 407.97
    if not fbits_is_configured():
        return {
            "ok": True,
            "connected": False,
            "client_id": client_id,
            "period": {"start": period.start, "end": period.end},
            "message": "FBits ainda não conectada.",
            "target": {
                "target_revenue": target_revenue,
                "target_orders": target_orders,
                "target_aov": target_aov,
            },
        }

    raw_orders = await fetch_fbits_orders(start=period.start, end=period.end)
    try:
        dashboard_payload = await fetch_fbits_revenue_dashboard(start=period.start, end=period.end)
    except httpx.HTTPError as exc:
        print(f"[fbits][reconciliation][dashboard_error] client_id={client_id} error={exc}")
        dashboard_payload = {}

    status_counts: Dict[str, int] = {}
    status_revenue: Dict[str, float] = {}
    included_rows: List[Dict[str, Any]] = []
    excluded_rows: List[Dict[str, Any]] = []
    debug_rows: List[Dict[str, Any]] = []
    for raw in raw_orders:
        normalized = normalize_fbits_order(raw)
        included, reason = _reconciliation_decision(raw)
        status_key = _status_id(raw) or "-"
        value = _safe_float(normalized.get("receita_oficial"))
        status_counts[status_key] = status_counts.get(status_key, 0) + 1
        status_revenue[status_key] = status_revenue.get(status_key, 0.0) + value
        row = {
            "pedido_id": normalized.get("pedido_id"),
            "data": normalized.get("data"),
            "status": {
                "id": normalized.get("situacao_pedido_id"),
                "name": normalized.get("situacao_pedido") or None,
            },
            "valor": round(value, 2),
            "cliente": normalized.get("cliente_nome")
            or normalized.get("cliente_email")
            or normalized.get("cliente_id"),
            "pagamento": normalized.get("forma_pagamento"),
            "incluido_no_dashboard": included,
            "motivo": reason,
        }
        debug_rows.append(row)
        if included:
            included_rows.append(row)
        else:
            excluded_rows.append(row)
        print(
            "[fbits][reconciliation][order] "
            f"client_id={client_id} pedido_id={row['pedido_id'] or '-'} status={status_key} "
            f"valor={row['valor']} included={str(included).lower()} reason={reason}"
        )

    raw_sum = round(sum(_safe_float(row.get("valor")) for row in debug_rows), 2)
    included_sum = round(sum(_safe_float(row.get("valor")) for row in included_rows), 2)
    dashboard_summary = {
        "receita": round(_safe_float(dashboard_payload.get("indicadorReceita")), 2),
        "pedidos": _safe_int(dashboard_payload.get("indicadorPedido")),
        "ticket_medio": round(_safe_float(dashboard_payload.get("indicadorTicketMedio")), 2),
    }
    rounded_status_revenue = {
        key: round(value, 2)
        for key, value in sorted(status_revenue.items(), key=lambda item: item[0])
    }
    print(
        "[fbits][reconciliation] "
        f"client_id={client_id} start={period.start} end={period.end} raw={len(debug_rows)} "
        f"included={len(included_rows)} excluded={len(excluded_rows)} raw_sum={raw_sum} "
        f"included_sum={included_sum} counts_by_status={status_counts} "
        f"revenue_by_status={rounded_status_revenue} dashboard={dashboard_summary}"
    )
    return {
        "ok": True,
        "connected": True,
        "client_id": client_id,
        "period": {"start": period.start, "end": period.end},
        "total_bruto_pedidos": len(debug_rows),
        "total_incluido": len(included_rows),
        "total_excluido": len(excluded_rows),
        "soma_bruta": raw_sum,
        "soma_incluida": included_sum,
        "contagem_por_status": dict(sorted(status_counts.items(), key=lambda item: item[0])),
        "soma_por_status": rounded_status_revenue,
        "fbits_dashboard": dashboard_summary,
        "target": {
            "target_revenue": target_revenue,
            "target_orders": target_orders,
            "target_aov": target_aov,
        },
        "orders": debug_rows,
    }


async def build_fbits_orders_report(*, client_id: str, period: FbitsPeriod) -> Dict[str, Any]:
    if not fbits_is_configured():
        return {
            "ok": True,
            "connected": False,
            "client_id": client_id,
            "period": {"start": period.start, "end": period.end},
            "count": 0,
            "items": [],
            "message": "FBits ainda não conectada.",
        }
    try:
        persisted = await _read_persisted_orders(client_id=client_id, period=period)
    except httpx.HTTPStatusError as exc:
        if _is_schema_pending_error(exc, "payment_method", "payment_status", "fbits_orders"):
            print(
                "[fbits][orders][schema_pending] "
                f"client_id={client_id} missing=fbits_orders.payment_columns"
            )
        else:
            print(f"[fbits][orders][persisted_read_error] client_id={client_id} status={exc.response.status_code}")
        persisted = []
    if persisted:
        items = [_persisted_order_item(row) for row in persisted]
        try:
            persisted_items = await _read_persisted_items(
                client_id=client_id,
                order_ids={_safe_str(row.get("order_id")) for row in persisted if _safe_str(row.get("order_id"))},
            )
        except httpx.HTTPStatusError as exc:
            if _is_schema_pending_error(exc, "fbits_order_items"):
                print(
                    "[fbits][items][schema_pending] "
                    f"client_id={client_id} missing=fbits_order_items"
                )
            else:
                print(f"[fbits][items][persisted_read_error] client_id={client_id} status={exc.response.status_code}")
            persisted_items = []
        return {
            "ok": True,
            "connected": True,
            "client_id": client_id,
            "period": {"start": period.start, "end": period.end},
            "count": len(items),
            "items": items,
            "top_products": (
                _products_ranking_from_items(persisted_items)
                or _products_ranking([row.get("raw") for row in persisted if isinstance(row.get("raw"), dict)])
            )[:20],
            "top_customers": _top_customers(items)[:20],
            "detail_available": bool(items),
            "source": "supabase",
        }
    print(
        "[fbits][orders][persisted_empty] "
        f"client_id={client_id} start={period.start} end={period.end} source=supabase"
    )
    return {
        "ok": True,
        "connected": True,
        "client_id": client_id,
        "period": {"start": period.start, "end": period.end},
        "count": 0,
        "items": [],
        "top_products": [],
        "top_customers": [],
        "detail_available": False,
        "message": "FBits conectada, aguardando dados do período.",
        "source": "supabase",
    }


async def build_fbits_summary(*, client_id: str, period: FbitsPeriod) -> Dict[str, Any]:
    if not fbits_is_configured():
        return _summary_from_orders(client_id=client_id, period=period, orders=[])
    try:
        daily_rows = await _read_persisted_daily(client_id=client_id, period=period)
    except httpx.HTTPStatusError as exc:
        if _is_schema_pending_error(exc, "fbits_order_daily_stats"):
            print(
                "[fbits][summary][schema_pending] "
                f"client_id={client_id} missing=fbits_order_daily_stats"
            )
        else:
            print(f"[fbits][summary][persisted_read_error] client_id={client_id} status={exc.response.status_code}")
        daily_rows = []
    if daily_rows:
        summary = _summary_from_daily(client_id=client_id, period=period, rows=daily_rows)
        try:
            detailed_rows = await _read_persisted_orders(client_id=client_id, period=period)
        except httpx.HTTPStatusError as exc:
            if _is_schema_pending_error(exc, "payment_method", "payment_status", "fbits_orders"):
                print(
                    "[fbits][summary][schema_pending] "
                    f"client_id={client_id} missing=fbits_orders.payment_columns"
                )
            else:
                print(f"[fbits][summary][detail_read_error] client_id={client_id} status={exc.response.status_code}")
            detailed_rows = []
        if detailed_rows:
            details = _detail_metrics_from_items(_persisted_order_item(row) for row in detailed_rows)
            if details["clientes"]:
                summary["summary"]["clientes"] = details["clientes"]
            if details["produtos_vendidos"]:
                summary["summary"]["produtos_vendidos"] = details["produtos_vendidos"]
        return summary
    return {
        **_summary_from_orders(client_id=client_id, period=period, orders=[]),
        "connected": True,
        "source": "supabase",
    }
