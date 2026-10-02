"""Reconciliação FBITS pedido a pedido — diagnóstico SOMENTE LEITURA.

Compara, para um tenant e um período:
  1. os indicadores oficiais da loja (GET /dashboard/faturamento);
  2. os pedidos que a API devolve agora (GET /pedidos por DataPedido e por
     DataAprovacao, com x-total-count);
  3. os pedidos persistidos no Mugô (fbits_orders) e a regra atual do
     dashboard (situação em revenue_status_ids e valido != false).

Também testa regras candidatas (todas, só válidos, sem cancelados, pagos no
período e todo subconjunto de situações) contra os indicadores oficiais, para
descobrir a regra real com evidência — nada é ajustado para "bater".

Nunca grava nada, nunca imprime token e nunca lê dados pessoais do comprador:
só id, datas, situação, valido e valores do pedido.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from .fbits_client import FbitsApiError
from .fbits_connections import ClientFactory, default_client_factory, load_fbits_connection
from .fbits_reporting import FbitsPeriod, _counts_as_revenue as _dashboard_counts_as_revenue, _read_persisted_orders
from .generic_connections import get_connection
from .ig_supabase import sb_select

MAX_STATUS_SUBSET = 14
CANCELLED_NAME = re.compile(r"cancel|estorn|devolv|negad|reprov|inv[aá]lid|fraud", re.I)
VALUE_FIELDS = ("total", "total_sem_frete", "subtotal_menos_desconto")


def _s(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _num(value: Any) -> float:
    try:
        return float(_s(value).replace(",", ".") or 0)
    except ValueError:
        return 0.0


def _money(value: float) -> float:
    return round(value + 0.0, 2)


def _freight(order: Dict[str, Any]) -> float:
    if order.get("valorFrete") not in (None, ""):
        return _num(order.get("valorFrete"))
    frete = order.get("frete")
    return _num(frete.get("valorFreteCliente")) if isinstance(frete, dict) else 0.0


def api_order_row(order: Dict[str, Any]) -> Dict[str, Any]:
    """Só campos do pedido; o objeto usuario/endereço/pagamento é ignorado."""
    total = _num(order.get("valorTotalPedido"))
    freight = _freight(order)
    discount = _num(order.get("valorDesconto"))
    subtotal = _num(order.get("valorSubTotalSemDescontos"))
    valid = order.get("valido")
    raw_date = _s(order.get("data"))
    return {
        "order_id": _s(order.get("pedidoId")),
        "created_at": raw_date or None,
        "created_at_has_offset": bool(re.search(r"(Z|[+-]\d\d:?\d\d)$", raw_date)),
        "approved_at": _s(order.get("dataPagamento")) or None,
        "status_id": _s(order.get("situacaoPedidoId")) or None,
        "valid": valid if isinstance(valid, bool) else None,
        "total": _money(total),
        "discount": _money(discount),
        "freight": _money(freight),
        "subtotal": _money(subtotal),
        "values": {
            "total": total,
            "total_sem_frete": total - freight,
            "subtotal_menos_desconto": subtotal - discount,
        },
    }


def _counts_as_revenue(status_id: Optional[str], valid: Optional[bool], revenue_status_ids: set[str]) -> bool:
    return _s(status_id) in revenue_status_ids and valid is not False


def _metrics(rows: Iterable[Dict[str, Any]], value_field: str = "total") -> Dict[str, Any]:
    rows = list(rows)
    revenue = sum(row["values"][value_field] for row in rows)
    return {
        "pedidos": len(rows),
        "receita": _money(revenue),
        "ticket_medio": _money(revenue / len(rows)) if rows else 0.0,
    }


def _matches(metrics: Dict[str, Any], official: Dict[str, Any]) -> bool:
    if official.get("pedidos") is None:
        return False
    return metrics["pedidos"] == official["pedidos"] and abs(metrics["receita"] - official["receita"]) <= 0.01


def _status_subset_search(
    rows: List[Dict[str, Any]], official: Dict[str, Any], status_names: Dict[str, str],
) -> Dict[str, Any]:
    """Testa todo subconjunto das situações presentes contra o oficial."""
    if official.get("pedidos") is None:
        return {"skipped": "indicadores oficiais indisponíveis", "matches": [], "closest": []}
    statuses = sorted({_s(row["status_id"]) for row in rows})
    if len(statuses) > MAX_STATUS_SUBSET:
        return {"skipped": f"{len(statuses)} situações (> {MAX_STATUS_SUBSET})", "matches": [], "closest": []}
    matches: List[Dict[str, Any]] = []
    closest: List[Dict[str, Any]] = []
    for only_valid in (False, True):
        base = [row for row in rows if not only_valid or row["valid"] is not False]
        for field in VALUE_FIELDS:
            counts = [sum(1 for r in base if _s(r["status_id"]) == st) for st in statuses]
            sums = [sum(r["values"][field] for r in base if _s(r["status_id"]) == st) for st in statuses]
            size = 1 << len(statuses)
            acc_count = [0] * size
            acc_sum = [0.0] * size
            for mask in range(1, size):
                low = mask & -mask
                index = low.bit_length() - 1
                acc_count[mask] = acc_count[mask ^ low] + counts[index]
                acc_sum[mask] = acc_sum[mask ^ low] + sums[index]
                if acc_count[mask] != official["pedidos"]:
                    continue
                chosen = [statuses[i] for i in range(len(statuses)) if mask >> i & 1]
                entry = {
                    "status_ids": chosen,
                    "status_names": [status_names.get(st) or st for st in chosen],
                    "only_valid": only_valid,
                    "value_field": field,
                    "pedidos": acc_count[mask],
                    "receita": _money(acc_sum[mask]),
                    "diff_receita": _money(acc_sum[mask] - official["receita"]),
                }
                if abs(entry["diff_receita"]) <= 0.01:
                    matches.append(entry)
                else:
                    closest.append(entry)
    closest.sort(key=lambda entry: abs(entry["diff_receita"]))
    return {"skipped": None, "matches": matches[:20], "closest": closest[:5]}


def _exclusion_reason(
    *, api: Optional[Dict[str, Any]], db: Optional[Dict[str, Any]], db_in_period: bool,
    revenue_status_ids: set[str], status_names: Dict[str, str],
) -> Optional[str]:
    if db is None:
        return "não persistido no Mugô (sincronização não trouxe o pedido)"
    if not db_in_period:
        return "persistido com order_date fora do período do dashboard (data/fuso)"
    status = _s(db.get("status_id"))
    if db.get("is_valid") is False:
        return "marcado inválido (valido=false)"
    if status not in revenue_status_ids:
        stale = f"; na API agora é {api['status_id']}" if api and _s(api["status_id"]) != status else ""
        return f"situação {status or '-'} ({status_names.get(status) or 'sem nome'}) fora de revenue_status_ids{stale}"
    return None


async def _tenant_token(client_id: str) -> tuple[Dict[str, Any], str]:
    row = await load_fbits_connection(client_id)
    if not row:
        raise RuntimeError("Nenhuma conexão FBITS encontrada para esta empresa.")
    full = await get_connection(client_id, _s(row.get("id")), include_token=True)
    try:
        token = _s(json.loads(full.get("_token") or "{}").get("token"))
    except (TypeError, ValueError):
        token = ""
    if not token:
        raise RuntimeError("A conexão FBITS não possui token. Conecte novamente.")
    return row, token


async def _collect_api_orders(client, *, period: FbitsPeriod, date_filter: str) -> Dict[str, Any]:
    start = datetime.combine(date.fromisoformat(period.start), datetime.min.time())
    end = datetime.combine(date.fromisoformat(period.end), datetime.max.time()).replace(microsecond=0)
    rows: List[Dict[str, Any]] = []
    pages = 0
    total_count: Optional[int] = None
    async for page in client.iter_order_pages(start=start, end=end, date_filter=date_filter):
        pages += 1
        if total_count is None:
            total_count = client.last_total_count
        rows.extend(api_order_row(order) for order in page)
    ids = [row["order_id"] for row in rows]
    unique: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if row["order_id"]:
            unique.setdefault(row["order_id"], row)
    return {
        "filter": date_filter,
        "query": {"dataInicial": start.strftime("%Y-%m-%d %H:%M:%S"), "dataFinal": end.strftime("%Y-%m-%d %H:%M:%S")},
        "x_total_count": total_count,
        "pages": pages,
        "rows_returned": len(rows),
        "unique_orders": len(unique),
        "duplicates": len(ids) - len(set(ids)),
        "without_id": sum(1 for value in ids if not value),
        "orders": unique,
    }


async def _persisted_by_id(client_id: str, order_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    ids = sorted({value for value in order_ids if value})
    out: Dict[str, Dict[str, Any]] = {}
    for chunk_start in range(0, len(ids), 100):
        chunk = ids[chunk_start:chunk_start + 100]
        rows = await sb_select(
            "fbits_orders",
            select="order_id,status_id,order_date,approved_at,total_value,discount_value,freight_value,is_valid,updated_at",
            filters={"client_id": f"eq.{client_id}", "order_id": f"in.({','.join(chunk)})"},
            limit=len(chunk),
        )
        out.update({_s(row.get("order_id")): row for row in rows})
    return out


def build_reconciliation(
    *,
    period: FbitsPeriod,
    official_payload: Optional[Dict[str, Any]],
    official_error: Optional[str],
    by_order_date: Dict[str, Any],
    by_approval_date: Optional[Dict[str, Any]],
    persisted_in_period: List[Dict[str, Any]],
    persisted_by_id: Dict[str, Dict[str, Any]],
    revenue_status_ids: set[str],
    status_names: Dict[str, str],
    connection_state: Dict[str, Any],
) -> Dict[str, Any]:
    """Parte pura: recebe o que foi coletado e monta o diagnóstico."""
    official = {
        "receita": _money(_num(official_payload.get("indicadorReceita"))) if official_payload else None,
        "pedidos": int(_num(official_payload.get("indicadorPedido"))) if official_payload else None,
        "ticket_medio": _money(_num(official_payload.get("indicadorTicketMedio"))) if official_payload else None,
        "error": official_error,
    }
    api_orders: Dict[str, Dict[str, Any]] = by_order_date["orders"]
    approval_orders: Dict[str, Dict[str, Any]] = (by_approval_date or {}).get("orders") or {}
    in_period = {_s(row.get("order_id")): row for row in persisted_in_period}
    db_all = {**persisted_by_id, **in_period}

    table: List[Dict[str, Any]] = []
    for order_id in sorted(set(api_orders) | set(in_period)):
        api = api_orders.get(order_id)
        db = db_all.get(order_id)
        db_in_period = order_id in in_period
        # Mesma decisão do dashboard (inclui o fallback raw.valido).
        included = bool(db is not None and db_in_period and _dashboard_counts_as_revenue(db, revenue_status_ids))
        status_raw = api["status_id"] if api else None
        table.append({
            "order_id": order_id,
            "order_number": order_id,
            "created_at": api["created_at"] if api else _s(db.get("order_date")) or None,
            "approved_at": api["approved_at"] if api else _s(db.get("approved_at")) or None,
            "status_raw_id": status_raw,
            "status_raw_name": status_names.get(_s(status_raw)) if status_raw else None,
            "status_mugo_id": (_s(db.get("status_id")) or None) if db else None,
            "status_stale": bool(api and db and _s(api["status_id"]) != _s(db.get("status_id"))),
            "valid": api["valid"] if api else (db or {}).get("is_valid"),
            "total": api["total"] if api else _money(_num((db or {}).get("total_value"))),
            "discount": api["discount"] if api else _money(_num((db or {}).get("discount_value"))),
            "freight": api["freight"] if api else _money(_num((db or {}).get("freight_value"))),
            "total_mugo": _money(_num(db.get("total_value"))) if db else None,
            "in_api_period": api is not None,
            "in_mugo_period": db_in_period,
            "included_in_orders": included,
            "included_in_revenue": included,
            "exclusion_reason": None if included else _exclusion_reason(
                api=api, db=db, db_in_period=db_in_period,
                revenue_status_ids=revenue_status_ids, status_names=status_names,
            ),
        })

    def by_status(rows: Iterable[Dict[str, Any]], status_key: str, value_key: str) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            status = _s(row.get(status_key)) or "-"
            bucket = grouped.setdefault(status, {
                "status_id": status, "status": status_names.get(status) or None,
                "in_revenue_rule": status in revenue_status_ids, "pedidos": 0, "valor": 0.0, "invalidos": 0,
            })
            bucket["pedidos"] += 1
            bucket["valor"] += _num(row.get(value_key))
            bucket["invalidos"] += 1 if row.get("valid", row.get("is_valid")) is False else 0
        for bucket in grouped.values():
            bucket["valor"] = _money(bucket["valor"])
        return sorted(grouped.values(), key=lambda item: -item["pedidos"])

    api_rows = list(api_orders.values())
    fresh_rule = [row for row in api_rows if _counts_as_revenue(row["status_id"], row["valid"], revenue_status_ids)]
    dashboard_rule = [row for row in persisted_in_period if _dashboard_counts_as_revenue(row, revenue_status_ids)]
    dashboard_revenue = sum(_num(row.get("total_value")) for row in dashboard_rule)
    candidates = {
        "dashboard_atual_mugo": {
            "pedidos": len(dashboard_rule), "receita": _money(dashboard_revenue),
            "ticket_medio": _money(dashboard_revenue / len(dashboard_rule)) if dashboard_rule else 0.0,
        },
        "regra_atual_com_dados_frescos": _metrics(fresh_rule),
        "todos_por_data_pedido": _metrics(api_rows),
        "validos_por_data_pedido": _metrics(row for row in api_rows if row["valid"] is not False),
        "sem_cancelados_por_nome": _metrics(
            row for row in api_rows
            if row["valid"] is not False and not CANCELLED_NAME.search(status_names.get(_s(row["status_id"])) or "")
        ),
        "todos_sem_frete": _metrics(api_rows, "total_sem_frete"),
    }
    if by_approval_date is not None:
        approval_rows = list(approval_orders.values())
        candidates["aprovados_por_data_aprovacao"] = _metrics(approval_rows)
        candidates["aprovados_validos_por_data_aprovacao"] = _metrics(row for row in approval_rows if row["valid"] is not False)
    for metrics in candidates.values():
        metrics["bate_com_oficial"] = _matches(metrics, official)

    boundary = timedelta(hours=3)
    start_dt = datetime.fromisoformat(period.start)
    end_dt = datetime.fromisoformat(period.end) + timedelta(days=1)
    near_boundary = 0
    for row in api_rows:
        try:
            created = datetime.fromisoformat(_s(row["created_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            continue
        if abs(created - start_dt) <= boundary or abs(created - end_dt) <= boundary:
            near_boundary += 1

    return {
        "period": {"start": period.start, "end": period.end},
        "official": official,
        "connection": connection_state,
        "revenue_status_ids": sorted(revenue_status_ids),
        "api": {
            key: value for key, value in by_order_date.items() if key != "orders"
        } | {"approval_filter": {k: v for k, v in (by_approval_date or {}).items() if k != "orders"} or None},
        "mugo": {
            "persisted_in_period": len(persisted_in_period),
            "missing_in_mugo": sum(1 for row in table if row["in_api_period"] and row["total_mugo"] is None),
            "persisted_outside_period": sum(1 for row in table if row["in_api_period"] and row["total_mugo"] is not None and not row["in_mugo_period"]),
            "only_in_mugo": sum(1 for row in table if row["in_mugo_period"] and not row["in_api_period"]),
            "status_stale": sum(1 for row in table if row["status_stale"]),
            "value_diverges": sum(
                1 for row in table
                if row["in_api_period"] and row["total_mugo"] is not None and abs(row["total"] - row["total_mugo"]) > 0.01
            ),
        },
        "timezone": {
            "api_dates_with_offset": sum(1 for row in api_rows if row["created_at_has_offset"]),
            "api_dates_without_offset": sum(1 for row in api_rows if row["created_at"] and not row["created_at_has_offset"]),
            "orders_within_3h_of_boundary": near_boundary,
        },
        "by_status_api": by_status(api_rows, "status_id", "total"),
        "by_status_mugo": by_status(persisted_in_period, "status_id", "total_value"),
        "candidates": candidates,
        "status_subsets": _status_subset_search(api_rows, official, status_names),
        "orders": table,
    }


async def collect_fbits_reconciliation(
    *, client_id: str, period: FbitsPeriod, client_factory: ClientFactory = default_client_factory,
    include_approval_filter: bool = True,
) -> Dict[str, Any]:
    row, token = await _tenant_token(client_id)
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    revenue_status_ids = {_s(value) for value in metadata.get("revenue_status_ids") or []}
    client = client_factory(token)

    statuses = await client.list_order_statuses()
    status_names = {item["id"]: item["nome"] for item in statuses}
    official_payload: Optional[Dict[str, Any]] = None
    official_error: Optional[str] = None
    try:
        official_payload = await client.revenue_indicators(start=period.start, end=period.end)
    except FbitsApiError as exc:
        official_error = exc.code

    by_order_date = await _collect_api_orders(client, period=period, date_filter="DataPedido")
    by_approval_date = (
        await _collect_api_orders(client, period=period, date_filter="DataAprovacao")
        if include_approval_filter else None
    )
    persisted_in_period = await _read_persisted_orders(client_id=client_id, period=period)
    api_ids = set(by_order_date["orders"]) | set((by_approval_date or {}).get("orders") or {})
    persisted_by_id = await _persisted_by_id(client_id, api_ids)

    report = build_reconciliation(
        period=period,
        official_payload=official_payload,
        official_error=official_error,
        by_order_date=by_order_date,
        by_approval_date=by_approval_date,
        persisted_in_period=persisted_in_period,
        persisted_by_id=persisted_by_id,
        revenue_status_ids=revenue_status_ids,
        status_names=status_names,
        connection_state={
            "status": row.get("status"),
            "last_sync_at": row.get("last_sync_at"),
            "history_completed_at": metadata.get("history_completed_at"),
            "incremental_marker": metadata.get("incremental_marker"),
            "last_sync_mode": metadata.get("last_sync_mode"),
            "last_sync_error_code": metadata.get("last_sync_error_code"),
            "revenue_rule_confirmed": metadata.get("revenue_rule_confirmed"),
        },
    )
    report["client_id"] = client_id
    report["requests"] = client.requests_made
    print(
        f"[fbits][reconciliation] client_id={client_id} start={period.start} end={period.end} "
        f"api_orders={by_order_date['unique_orders']} mugo_orders={len(persisted_in_period)} requests={client.requests_made}"
    )
    return report
