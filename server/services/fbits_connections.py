"""FBITS/Wake multiempresa: conexão por tenant, sincronização e desconexão.

Regras:
- O token vem SEMPRE da conexão `integration_connections` (provider='fbits')
  do próprio tenant, cifrado pelo mecanismo existente (generic_connections).
  Não existe token global.
- Toda leitura/escrita usa o `client_id` já autorizado pela rota.
- Histórico inicial: 90 dias em janelas de 7 dias (DataPedido, ASC).
- Incremental: marcador persistido - 2h de sobreposição (DataAlteracao).
  A semântica exata de DataAlteracao não é detalhada pela documentação
  oficial e deve ser validada com o token real antes de ativar cron.
- `fbits_orders` segue contendo somente campos de analytics e o
  `customer_id`: nome, e-mail, CPF, telefone e endereço NUNCA entram no
  pedido. `sanitize_order_raw` continua reduzindo `usuario` a `usuarioId` e
  `tipoPessoa`, e isso é protegido por teste.
- A identidade do cliente (nome, e-mail, telefone) é extraída do MESMO
  payload de `/pedidos` e gravada em `fbits_customers`, tabela separada com
  finalidade declarada (Customer 360) e exclusão própria. CPF, endereço e
  meio de pagamento continuam descartados na leitura e não têm coluna lá.
  Nenhuma requisição externa adicional: o dado já vinha na resposta.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

from .fbits_client import FBITS_APPROVED_ORDER_STATUS_IDS, FbitsApiError, FbitsClient
from .generic_connections import (
    disconnect_generic_connection,
    get_connection,
    sanitize_connection,
    upsert_connection,
)
from .ig_supabase import sb_select, sb_update, sb_upsert
from .job_runs import finish_job_run, start_job_run
from .integration_errors import IntegrationError
from .runtime_cache import invalidate_namespace
from .sync_locks import guarded_sync

PROVIDER = "fbits"
HISTORY_DAYS = 90
WINDOW_DAYS = 7
INCREMENTAL_OVERLAP = timedelta(hours=2)
HISTORICAL_DATE_FILTER = "DataPedido"
INCREMENTAL_DATE_FILTER = "DataAlteracao"

ClientFactory = Callable[[str], FbitsClient]

_ORDER_RAW_KEYS = (
    "pedidoId", "situacaoPedidoId", "data", "dataPagamento", "dataUltimaAtualizacao",
    "valorTotalPedido", "valorSubTotalSemDescontos", "valorDesconto", "valorFrete",
    "cupomDesconto", "valido", "primeiraCompra", "canalNome",
)
_ITEM_RAW_KEYS = (
    "produtoVarianteId", "sku", "nome", "quantidade", "precoVenda", "precoPor",
    "desconto", "isBrinde",
)
_ITEM_TOTALS_KEYS = ("precoVenda", "precoPor", "desconto")


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> float:
    try:
        return float(str(value if value is not None else "0").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _bool_or_none(value: Any) -> Optional[bool]:
    return value if isinstance(value, bool) else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_dt(value: Any) -> Optional[datetime]:
    raw = _safe_str(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso_or_none(value: Any) -> Optional[str]:
    parsed = _parse_dt(value)
    return _iso(parsed) if parsed else None


def external_key_for(client_id: str) -> str:
    # A API documentada não expõe um identificador estável da loja. A chave é
    # interna e estável por tenant — nunca derivada do token (segredo).
    # Limitação: não detecta a mesma loja conectada em dois tenants.
    return f"fbits:{_safe_str(client_id)}"


def default_client_factory(token: str) -> FbitsClient:
    return FbitsClient(token)


# ---------------------------------------------------------------------------
# Normalização (sem PII)
# ---------------------------------------------------------------------------

def sanitize_order_raw(order: Dict[str, Any]) -> Dict[str, Any]:
    raw: Dict[str, Any] = {key: order.get(key) for key in _ORDER_RAW_KEYS if key in order}
    user = order.get("usuario")
    if isinstance(user, dict):
        raw["usuario"] = {
            key: user.get(key) for key in ("usuarioId", "tipoPessoa") if key in user
        }
    items = []
    for item in order.get("itens") or []:
        if not isinstance(item, dict):
            continue
        clean = {key: item.get(key) for key in _ITEM_RAW_KEYS if key in item}
        totals = item.get("totais")
        if isinstance(totals, dict):
            clean["totais"] = {key: totals.get(key) for key in _ITEM_TOTALS_KEYS if key in totals}
        items.append(clean)
    raw["itens"] = items
    return raw


def normalize_order(client_id: str, order: Dict[str, Any], status_names: Dict[str, str]) -> Optional[Dict[str, Any]]:
    order_id = _safe_str(order.get("pedidoId"))
    if not order_id:
        return None
    raw = sanitize_order_raw(order)
    status_id = _safe_str(order.get("situacaoPedidoId")) or None
    user = order.get("usuario") if isinstance(order.get("usuario"), dict) else {}
    freight = order.get("valorFrete")
    if freight in (None, "") and isinstance(order.get("frete"), dict):
        freight = order["frete"].get("valorFreteCliente")
    return {
        "client_id": client_id,
        "order_id": order_id,
        "order_code": order_id,
        "customer_id": _safe_str(user.get("usuarioId")) or None,
        "status_id": status_id,
        "status_name": status_names.get(status_id or "") or None,
        "order_date": _iso_or_none(order.get("data")),
        "approved_at": _iso_or_none(order.get("dataPagamento")),
        "source_updated_at": _iso_or_none(order.get("dataUltimaAtualizacao")),
        "total_value": round(_num(order.get("valorTotalPedido")), 2),
        "subtotal_value": round(_num(order.get("valorSubTotalSemDescontos")), 2),
        "discount_value": round(_num(order.get("valorDesconto")), 2),
        "freight_value": round(_num(freight), 2),
        "coupon_code": _safe_str(order.get("cupomDesconto")) or None,
        "is_valid": _bool_or_none(order.get("valido")),
        "first_purchase": _bool_or_none(order.get("primeiraCompra")),
        "sales_channel": _safe_str(order.get("canalNome")) or None,
        "products_count": sum(max(0, _int(item.get("quantidade"))) for item in raw["itens"]),
        "raw": raw,
    }


# Campos da identidade que o Customer 360 usa. `cpf` e endereço estão fora de
# propósito: não são lidos aqui nem têm coluna em fbits_customers.
_CUSTOMER_PHONE_KEYS = ("telefoneCelular", "telefone", "telefoneResidencial")


def normalize_customer(client_id: str, order: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Identidade do cliente a partir do objeto `usuario` do pedido.

    Só nome, e-mail e telefone. Campo ausente na API vira None — nada é
    inventado. Sem `usuarioId` não há identidade e nada é gravado.
    """
    user = order.get("usuario") if isinstance(order.get("usuario"), dict) else {}
    customer_id = _safe_str(user.get("usuarioId"))
    if not customer_id:
        return None
    phone = next(
        (_safe_str(user.get(key)) for key in _CUSTOMER_PHONE_KEYS if _safe_str(user.get(key))),
        "",
    )
    return {
        "client_id": client_id,
        "fbits_customer_id": customer_id,
        "name": _safe_str(user.get("nome")) or None,
        "email": (_safe_str(user.get("email")).lower() or None),
        "phone": phone or None,
        "created_at_provider": _iso_or_none(user.get("dataCriacao")),
        "updated_at_provider": _iso_or_none(user.get("dataAlteracao")),
        "synced_at": _iso(datetime.now(timezone.utc)),
    }


def normalize_customers(client_id: str, page: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Identidades distintas de uma página de pedidos.

    O mesmo cliente aparece em vários pedidos da página; o upsert recebe uma
    linha por cliente, com a leitura mais recente ganhando.
    """
    latest: Dict[str, Dict[str, Any]] = {}
    for order in page:
        row = normalize_customer(client_id, order)
        if row:
            latest[row["fbits_customer_id"]] = row
    return list(latest.values())


async def _persist_customer_identities(
    client_id: str, page: Iterable[Dict[str, Any]],
) -> int:
    """Grava as identidades da página, tolerando a migration 040 pendente.

    Enquanto `fbits_customers` não existir no remoto, o sync segue normal e o
    log diz que falta migration — em vez de a sincronização de pedidos
    inteira falhar por uma tabela ausente. O log nunca carrega PII: só a
    contagem.
    """
    rows = normalize_customers(client_id, page)
    if not rows:
        return 0
    try:
        await sb_upsert("fbits_customers", rows, on_conflict="client_id,fbits_customer_id")
    except Exception as exc:  # noqa: BLE001 - identidade não derruba pedidos
        print(
            f"[fbits][customers] client_id={client_id} status=unavailable "
            f"customers={len(rows)} error_type={exc.__class__.__name__} "
            "migration=20261004_000040_fbits_customer_identity"
        )
        return 0
    return len(rows)


def normalize_items(client_id: str, order_row: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, item in enumerate((order_row.get("raw") or {}).get("itens") or [], start=1):
        product_id = _safe_str(item.get("produtoVarianteId"))
        sku = _safe_str(item.get("sku"))
        quantity = max(0, _int(item.get("quantidade")))
        unit_value = _num(item.get("precoPor")) or _num(item.get("precoVenda"))
        totals = item.get("totais") if isinstance(item.get("totais"), dict) else {}
        total_value = _num(totals.get("precoPor")) or unit_value * quantity
        discount = _num(totals.get("desconto")) or _num(item.get("desconto"))
        rows.append({
            "client_id": client_id,
            "order_id": order_row["order_id"],
            # O schema oficial não traz id de item; posição + variante é estável
            # para o mesmo pedido e mantém o upsert idempotente.
            "item_id": f"{product_id or sku or 'item'}:{index}",
            "product_id": product_id or None,
            "sku": sku or None,
            "product_name": _safe_str(item.get("nome")) or None,
            "quantity": quantity,
            "unit_value": round(unit_value, 2),
            "total_value": round(total_value, 2),
            "discount_value": round(discount, 2),
            "is_gift": bool(item.get("isBrinde")),
            "raw": item,
        })
    return rows


def daily_stats_rows(
    client_id: str, orders: Iterable[Dict[str, Any]], days: Iterable[str], revenue_status_ids: Iterable[str],
) -> List[Dict[str, Any]]:
    revenue_statuses = {_safe_str(value) for value in revenue_status_ids}
    buckets: Dict[str, Dict[str, Any]] = {
        day: {"client_id": client_id, "stat_date": day, "receita_oficial": 0.0, "pedidos": 0,
              "ticket_medio": 0.0, "clientes": 0, "produtos_vendidos": 0}
        for day in days
    }
    customers: Dict[str, set] = {}
    for order in orders:
        day = _safe_str(order.get("order_date"))[:10]
        if day not in buckets:
            continue
        if _safe_str(order.get("status_id")) not in revenue_statuses or order.get("is_valid") is False:
            continue
        bucket = buckets[day]
        bucket["receita_oficial"] += _num(order.get("total_value"))
        bucket["pedidos"] += 1
        bucket["produtos_vendidos"] += _int(order.get("products_count"))
        customer = _safe_str(order.get("customer_id"))
        if customer:
            customers.setdefault(day, set()).add(customer)
    for day, bucket in buckets.items():
        revenue = round(bucket["receita_oficial"], 2)
        bucket["receita_oficial"] = revenue
        bucket["ticket_medio"] = round(revenue / bucket["pedidos"], 2) if bucket["pedidos"] else 0.0
        bucket["clientes"] = len(customers.get(day, set()))
    return list(buckets.values())


def plan_windows(start: datetime, end: datetime, *, window_days: int = WINDOW_DAYS) -> List[tuple[datetime, datetime]]:
    windows = []
    cursor = start
    while cursor < end:
        window_end = min(end, cursor + timedelta(days=window_days))
        windows.append((cursor, window_end))
        cursor = window_end
    return windows


# ---------------------------------------------------------------------------
# Conexão por tenant
# ---------------------------------------------------------------------------

async def load_fbits_connection(client_id: str) -> Optional[Dict[str, Any]]:
    rows = await sb_select(
        "integration_connections",
        filters={"client_id": f"eq.{client_id}", "provider": f"eq.{PROVIDER}"},
        order="updated_at.desc",
        limit=2,
    )
    rows = [row for row in rows if _safe_str(row.get("client_id")) == client_id and row.get("provider") == PROVIDER]
    if len(rows) > 1:
        raise IntegrationError(
            "Mais de uma conexão FBITS encontrada para esta empresa.",
            status_code=409, code="FBITS_CONNECTION_AMBIGUOUS", provider=PROVIDER,
        )
    return rows[0] if rows else None


async def fbits_connection_state(client_id: str) -> Dict[str, Any]:
    """Estado sanitizado (sem token) usado pelos relatórios."""
    row = await load_fbits_connection(client_id)
    if not row:
        return {"connected": False, "connection": None}
    connected = _safe_str(row.get("status")).lower() not in {"disconnected", "not_configured"} and not row.get("disconnected_at")
    return {"connected": connected, "connection": sanitize_connection(row)}


async def connect_fbits(
    *, client_id: str, user_id: str, token: str, client_factory: ClientFactory = default_client_factory,
) -> Dict[str, Any]:
    token = _safe_str(token)
    if not token:
        raise IntegrationError("Informe o token da API FBITS.", status_code=400, code="FBITS_TOKEN_REQUIRED", provider=PROVIDER)
    try:
        statuses = await client_factory(token).list_order_statuses()
    except FbitsApiError as exc:
        print(f"[fbits][connect] client_id={client_id} stage=validate status=error code={exc.code}")
        raise IntegrationError(
            exc.public_message,
            status_code=400 if exc.code in {"FBITS_INVALID_TOKEN", "FBITS_PERMISSION_DENIED", "FBITS_TOKEN_REQUIRED"} else 502,
            code=exc.code, provider=PROVIDER, retryable=exc.retryable,
        ) from None
    known_ids = {status["id"] for status in statuses}
    connection = await upsert_connection(
        client_id=client_id,
        provider=PROVIDER,
        external_key=external_key_for(client_id),
        token_payload=json.dumps({"token": token}),
        user_id=user_id,
        status="connected",
        account_name="FBITS / Wake Commerce",
        metadata={
            "order_statuses": statuses,
            # Sugestão inicial; a regra de receita precisa ser confirmada com
            # os dados reais do tenant antes de ser tratada como definitiva.
            "revenue_status_ids": [value for value in FBITS_APPROVED_ORDER_STATUS_IDS if value in known_ids],
            "revenue_rule_confirmed": False,
            "history_days": HISTORY_DAYS,
        },
    )
    print(f"[fbits][connect] client_id={client_id} stage=persisted status=ok statuses={len(statuses)} connection_id={connection.get('id')}")
    return {"connection": connection, "order_statuses_count": len(statuses)}


async def disconnect_fbits(*, client_id: str, user_id: str) -> Dict[str, Any]:
    row = await load_fbits_connection(client_id)
    if not row:
        raise IntegrationError(
            "Nenhuma conexão FBITS encontrada para esta empresa.",
            status_code=404, code="FBITS_CONNECTION_NOT_FOUND", provider=PROVIDER,
        )
    # Apaga só o token e marca disconnected; pedidos e métricas ficam.
    return await disconnect_generic_connection(client_id, _safe_str(row.get("id")), user_id)


# ---------------------------------------------------------------------------
# Sincronização
# ---------------------------------------------------------------------------

async def _safe_start_job_run(**kwargs) -> Dict[str, Any]:
    """Observabilidade nunca derruba a sincronização: sem o registro, os dados
    continuam entrando e a falha fica no log."""
    try:
        return await start_job_run(**kwargs)
    except Exception as exc:
        print(f"[fbits][sync] stage=job_run_start status=failed error_type={exc.__class__.__name__}")
        return {}


async def _safe_finish_job_run(job_run_id: str, **kwargs) -> None:
    try:
        await finish_job_run(job_run_id, **kwargs)
    except Exception as exc:
        print(f"[fbits][sync] stage=job_run_finish status=failed error_type={exc.__class__.__name__}")


async def _persist_state(client_id: str, connection_id: str, patch: Dict[str, Any]) -> None:
    await sb_update(
        "integration_connections",
        filters={"id": f"eq.{connection_id}", "client_id": f"eq.{client_id}", "provider": f"eq.{PROVIDER}"},
        patch={**patch, "updated_at": _iso(_now())},
        returning="minimal",
    )
    await invalidate_namespace("client_integrations")


async def _refresh_daily_stats(client_id: str, days: set, revenue_status_ids: List[str]) -> int:
    if not days:
        return 0
    ordered = sorted(days)
    day_after_last = (datetime.fromisoformat(ordered[-1]) + timedelta(days=1)).date().isoformat()
    orders = await sb_select(
        "fbits_orders",
        select="order_date,total_value,products_count,customer_id,status_id,is_valid",
        filters={
            "client_id": f"eq.{client_id}",
            "and": f"(order_date.gte.{ordered[0]},order_date.lt.{day_after_last})",
        },
        limit=50000,
    )
    rows = daily_stats_rows(client_id, orders, ordered, revenue_status_ids)
    await sb_upsert("fbits_order_daily_stats", rows, on_conflict="client_id,stat_date")
    return len(rows)


async def sync_fbits_connection(
    *,
    client_id: str,
    client_factory: ClientFactory = default_client_factory,
    now: Optional[datetime] = None,
    job_name: str = "fbits_sync_manual",
    trigger_source: str = "manual_api",
    record_job_run: bool = True,
) -> Dict[str, Any]:
    row = await load_fbits_connection(client_id)
    if not row:
        raise IntegrationError(
            "Nenhuma conexão FBITS encontrada para esta empresa.",
            status_code=404, code="FBITS_CONNECTION_NOT_FOUND", provider=PROVIDER,
        )
    if _safe_str(row.get("status")).lower() == "disconnected" or row.get("disconnected_at"):
        raise IntegrationError(
            "A conexão FBITS está desconectada. Conecte novamente para sincronizar.",
            status_code=409, code="FBITS_CONNECTION_DISCONNECTED", provider=PROVIDER,
        )
    connection_id = _safe_str(row.get("id"))
    full = await get_connection(client_id, connection_id, include_token=True)
    try:
        token = _safe_str(json.loads(full.get("_token") or "{}").get("token"))
    except (TypeError, ValueError):
        token = ""
    if not token:
        raise IntegrationError(
            "A conexão FBITS não possui token. Conecte novamente.",
            status_code=401, code="FBITS_REAUTH_REQUIRED", provider=PROVIDER,
        )

    metadata = dict(row.get("metadata") or {})
    revenue_status_ids = [str(value) for value in metadata.get("revenue_status_ids") or []]
    status_names = {
        _safe_str(item.get("id")): _safe_str(item.get("nome"))
        for item in metadata.get("order_statuses") or []
        if isinstance(item, dict)
    }
    run_started = now or _now()
    attempt_at = _iso(run_started)
    metadata["last_attempt_at"] = attempt_at
    job_run = None
    if record_job_run:
        job_run = await _safe_start_job_run(
            job_name=job_name, client_id=client_id, connection_id=connection_id,
            trigger_source=trigger_source, payload_json={"provider": PROVIDER},
        )
    job_run_id = _safe_str((job_run or {}).get("id"))
    historical = not metadata.get("history_completed_at")
    if historical:
        history_start = _parse_dt(metadata.get("history_start")) or (run_started - timedelta(days=HISTORY_DAYS))
        cursor = _parse_dt(metadata.get("history_cursor")) or history_start
        metadata["history_start"] = _iso(history_start)
        windows = plan_windows(cursor, run_started)
        date_filter = HISTORICAL_DATE_FILTER
    else:
        marker = _parse_dt(metadata.get("incremental_marker")) or run_started - timedelta(days=1)
        windows = plan_windows(marker - INCREMENTAL_OVERLAP, run_started)
        date_filter = INCREMENTAL_DATE_FILTER

    client = client_factory(token)
    orders_upserted = 0
    items_upserted = 0
    customers_upserted = 0
    affected_days: set = set()
    mode = "historical" if historical else "incremental"
    print(f"[fbits][sync] client_id={client_id} connection_id={connection_id} mode={mode} windows={len(windows)} filter={date_filter}")

    async with guarded_sync(client_id=client_id, provider=PROVIDER, connection_id=connection_id):
        try:
            for window_start, window_end in windows:
                async for page in client.iter_order_pages(start=window_start, end=window_end, date_filter=date_filter):
                    order_rows = [
                        normalized for order in page
                        for normalized in [normalize_order(client_id, order, status_names)] if normalized
                    ]
                    if not order_rows:
                        continue
                    await sb_upsert("fbits_orders", order_rows, on_conflict="client_id,order_id")
                    # Identidade do cliente extraída da MESMA página já lida:
                    # nenhuma requisição externa a mais, nenhum N+1.
                    customers_upserted += await _persist_customer_identities(
                        client_id, page,
                    )
                    item_rows = [item for order_row in order_rows for item in normalize_items(client_id, order_row)]
                    if item_rows:
                        await sb_upsert("fbits_order_items", item_rows, on_conflict="client_id,order_id,item_id")
                    orders_upserted += len(order_rows)
                    items_upserted += len(item_rows)
                    affected_days.update(
                        _safe_str(order_row.get("order_date"))[:10] for order_row in order_rows if order_row.get("order_date")
                    )
                if historical:
                    metadata["history_cursor"] = _iso(window_end)
                    await _persist_state(client_id, connection_id, {"metadata": metadata})
        except FbitsApiError as exc:
            await _refresh_daily_stats(client_id, affected_days, revenue_status_ids)
            await _persist_state(client_id, connection_id, {
                "status": "reauth_required" if exc.code in {"FBITS_INVALID_TOKEN", "FBITS_PERMISSION_DENIED"} else "sync_error",
                "last_error": exc.public_message[:300],
                "metadata": {**metadata, "last_sync_error_code": exc.code, "last_sync_requests": client.requests_made},
            })
            print(f"[fbits][sync] client_id={client_id} mode={mode} status=error code={exc.code} orders={orders_upserted} requests={client.requests_made}")
            if job_run_id:
                # Mensagem pública da FbitsApiError: nunca contém token.
                await _safe_finish_job_run(
                    job_run_id, status="error", rows_upserted=orders_upserted,
                    error=f"{exc.code}: {exc.public_message[:240]}",
                    payload_json={
                        "provider": PROVIDER, "mode": mode, "error_code": exc.code,
                        "orders_upserted": orders_upserted, "requests": client.requests_made,
                    },
                    client_id=client_id, connection_id=connection_id,
                )
            raise IntegrationError(
                exc.public_message,
                status_code=429 if exc.code == "FBITS_RATE_LIMITED" else (401 if exc.code == "FBITS_INVALID_TOKEN" else 502),
                code=exc.code, provider=PROVIDER, retryable=exc.retryable,
            ) from None

        daily_upserted = await _refresh_daily_stats(client_id, affected_days, revenue_status_ids)
        finished = _now() if now is None else run_started
        if historical:
            metadata["history_completed_at"] = _iso(finished)
            metadata.pop("history_cursor", None)
        metadata["incremental_marker"] = _iso(run_started)
        metadata["last_sync_mode"] = mode
        metadata["last_sync_requests"] = client.requests_made
        metadata["last_success_at"] = _iso(finished)
        metadata["last_sync_orders"] = orders_upserted
        metadata.pop("last_sync_error_code", None)
        patch: Dict[str, Any] = {
            "status": "connected",
            "last_sync_at": _iso(finished),
            "last_error": None,
            "metadata": metadata,
        }
        if historical:
            patch["historical_start"] = metadata["history_start"]
            patch["historical_end"] = _iso(run_started)
        await _persist_state(client_id, connection_id, patch)

    print(
        f"[fbits][sync] client_id={client_id} mode={mode} status=ok orders={orders_upserted} "
        f"items={items_upserted} customers={customers_upserted} days={daily_upserted} "
        f"requests={client.requests_made}"
    )
    payload = {
        "ok": True,
        "client_id": client_id,
        "mode": mode,
        "orders_upserted": orders_upserted,
        "items_upserted": items_upserted,
        # Contagem apenas: identidade de cliente nunca entra em log nem payload.
        "customers_upserted": customers_upserted,
        "daily_upserted": daily_upserted,
        "requests": client.requests_made,
        "last_attempt_at": attempt_at,
        "last_success_at": metadata.get("last_success_at"),
        "job_run_id": job_run_id or None,
    }
    if job_run_id:
        # Zero pedido novo é sucesso: a janela incremental simplesmente não
        # trouxe alteração. Nunca vira erro nem apaga last_success_at.
        await _safe_finish_job_run(
            job_run_id, status="success", rows_upserted=orders_upserted,
            payload_json=payload, client_id=client_id, connection_id=connection_id,
        )
    return payload
