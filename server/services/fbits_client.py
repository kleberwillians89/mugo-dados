from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Iterable, List, Tuple

import httpx


FBITS_APPROVED_ORDER_STATUSES = "1,11,14"
FBITS_APPROVED_ORDER_STATUS_IDS = tuple(
    value.strip()
    for value in FBITS_APPROVED_ORDER_STATUSES.split(",")
    if value.strip()
)
FBITS_ORDER_PAGE_SIZE = 50


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def get_fbits_config() -> Dict[str, str]:
    return {
        "token": _env("CLIENT_FBITS_API_TOKEN"),
        "store_id": _env("CLIENT_FBITS_STORE_ID"),
        "base_url": _env("CLIENT_FBITS_BASE_URL") or "https://api.fbits.net",
    }


def fbits_is_configured() -> bool:
    return bool(get_fbits_config()["token"])


def _authorization_value(token: str) -> str:
    raw = _safe_str(token)
    if raw.lower().startswith("basic "):
        return raw
    return f"Basic {raw}"


def _orders_from_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("pedidos", "items", "data", "results"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _product_identity(item: Dict[str, Any]) -> Tuple[str, str]:
    product = item.get("produto")
    product_row = product if isinstance(product, dict) else {}
    for source in (item, product_row):
        for key in ("produtoVarianteId", "produto_id", "produtoId", "idProduto", "id"):
            value = _safe_str(source.get(key))
            if value:
                return value, "ProdutoVarianteId"
    for source in (item, product_row):
        for key in ("sku", "codigo", "codigoProduto"):
            value = _safe_str(source.get(key))
            if value:
                return value, "Sku"
    return "", ""


def _order_items(order: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ("itens", "produtos", "items", "pedidoItens", "produtosPedido"):
        rows = order.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _order_identity(order: Dict[str, Any]) -> str:
    for key in ("idPedido", "pedidoId", "codigoPedido", "id", "codigo"):
        value = _safe_str(order.get(key))
        if value:
            return f"{key}:{value.lower()}"
    return ""


def _status_rows(rows: Iterable[Dict[str, Any]], status_id: str) -> List[Dict[str, Any]]:
    tagged_rows: List[Dict[str, Any]] = []
    for row in rows:
        tagged = dict(row)
        if not tagged.get("situacaoPedidoId"):
            tagged["situacaoPedidoId"] = status_id
        tagged_rows.append(tagged)
    return tagged_rows


async def _fetch_orders_for_status(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    status_id: str,
    start: str,
    end: str,
    page_limit: int,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    page = 1
    while page <= max(1, page_limit):
        response = await client.get(
            f"{base_url}/pedidos/situacaoPedido/{status_id}",
            headers={
                "Accept": "application/json",
                "Authorization": _authorization_value(token),
            },
            params={
                "dataInicial": start,
                "dataFinal": end,
                "pagina": page,
                "quantidadeRegistros": FBITS_ORDER_PAGE_SIZE,
                "direcaoOrdenacao": "DESC",
            },
        )
        response.raise_for_status()
        page_rows = _status_rows(_orders_from_payload(response.json()), status_id)
        rows.extend(page_rows)
        if len(page_rows) < FBITS_ORDER_PAGE_SIZE:
            break
        page += 1
    return rows


async def _fetch_detailed_orders(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    start: str,
    end: str,
    page_limit: int,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    page = 1
    while page <= max(1, page_limit):
        response = await client.get(
            f"{base_url}/pedidos",
            headers={
                "Accept": "application/json",
                "Authorization": _authorization_value(token),
            },
            params={
                "dataInicial": start,
                "dataFinal": end,
                "pagina": page,
                "quantidadeRegistros": FBITS_ORDER_PAGE_SIZE,
                "direcaoOrdenacao": "DESC",
                "enumTipoFiltroData": "DataPedido",
            },
        )
        response.raise_for_status()
        page_rows = _orders_from_payload(response.json())
        rows.extend(page_rows)
        print(
            "[fbits][orders][page] "
            f"endpoint=/pedidos start={start} end={end} page={page} count={len(page_rows)}"
        )
        if len(page_rows) < FBITS_ORDER_PAGE_SIZE:
            break
        page += 1
    return rows


async def _get_json(
    *,
    client: httpx.AsyncClient,
    url: str,
    token: str,
    params: Dict[str, Any] | None = None,
) -> Any:
    response = await client.get(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": _authorization_value(token),
        },
        params=params,
    )
    response.raise_for_status()
    return response.json()


async def _fetch_order_detail(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    order: Dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> Dict[str, Any]:
    order_id = _safe_str(order.get("pedidoId") or order.get("idPedido") or order.get("id"))
    if not order_id:
        return order
    async with semaphore:
        try:
            detail = await _get_json(
                client=client,
                url=f"{base_url}/pedidos/{order_id}",
                token=token,
                params={"camposAdicionais": "Transacao"},
            )
            if isinstance(detail, dict):
                print(f"[fbits][orders] endpoint=/pedidos/{order_id} detail=ok")
                return {**order, **detail}
        except httpx.HTTPStatusError as exc:
            print(
                "[fbits][orders][detail_item_error] "
                f"endpoint=/pedidos/{order_id} http_status={exc.response.status_code}"
            )
        except httpx.HTTPError as exc:
            print(f"[fbits][orders][detail_item_error] endpoint=/pedidos/{order_id} error={exc}")
    return order


async def _fetch_product_catalog_probe(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
) -> None:
    try:
        payload = await _get_json(
            client=client,
            url=f"{base_url}/produtos",
            token=token,
            params={"pagina": 1, "quantidadeRegistros": 1},
        )
        print(f"[fbits][products] endpoint=/produtos sample_count={len(_orders_from_payload(payload))}")
    except httpx.HTTPStatusError as exc:
        print(f"[fbits][products][catalog_error] endpoint=/produtos http_status={exc.response.status_code}")
    except httpx.HTTPError as exc:
        print(f"[fbits][products][catalog_error] endpoint=/produtos error={exc}")


async def _fetch_product_detail(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    identifier: str,
    identifier_type: str,
    semaphore: asyncio.Semaphore,
) -> Dict[str, Any]:
    if not identifier or not identifier_type:
        return {}
    async with semaphore:
        try:
            payload = await _get_json(
                client=client,
                url=f"{base_url}/produtos/{identifier}",
                token=token,
                params={
                    "tipoIdentificador": identifier_type,
                    "camposAdicionais": "Imagem",
                },
            )
            if isinstance(payload, dict):
                print(
                    "[fbits][products] "
                    f"endpoint=/produtos/{identifier} tipoIdentificador={identifier_type} detail=ok"
                )
                return payload
        except httpx.HTTPStatusError as exc:
            print(
                "[fbits][products][detail_error] "
                f"endpoint=/produtos/{identifier} tipoIdentificador={identifier_type} "
                f"http_status={exc.response.status_code}"
            )
        except httpx.HTTPError as exc:
            print(
                "[fbits][products][detail_error] "
                f"endpoint=/produtos/{identifier} tipoIdentificador={identifier_type} error={exc}"
            )
    return {}


async def _enrich_orders(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    detail_semaphore = asyncio.Semaphore(6)
    detailed = await asyncio.gather(
        *[
            _fetch_order_detail(
                client=client,
                base_url=base_url,
                token=token,
                order=row,
                semaphore=detail_semaphore,
            )
            for row in rows
        ]
    )
    identities = {
        _product_identity(item)
        for order in detailed
        for item in _order_items(order)
        if any(_product_identity(item))
    }
    if not identities:
        return detailed
    await _fetch_product_catalog_probe(client=client, base_url=base_url, token=token)
    product_semaphore = asyncio.Semaphore(5)
    product_rows = await asyncio.gather(
        *[
            _fetch_product_detail(
                client=client,
                base_url=base_url,
                token=token,
                identifier=identifier,
                identifier_type=identifier_type,
                semaphore=product_semaphore,
            )
            for identifier, identifier_type in identities
        ]
    )
    product_map = {
        identity: detail
        for identity, detail in zip(identities, product_rows)
        if detail
    }
    enriched: List[Dict[str, Any]] = []
    for order in detailed:
        order_copy = dict(order)
        for key in ("itens", "produtos", "items", "pedidoItens", "produtosPedido"):
            rows_for_key = order_copy.get(key)
            if not isinstance(rows_for_key, list):
                continue
            product_items = []
            for item in rows_for_key:
                if not isinstance(item, dict):
                    product_items.append(item)
                    continue
                identity = _product_identity(item)
                product_items.append(
                    {**item, "produtoDetalhe": product_map[identity]}
                    if identity in product_map
                    else item
                )
            order_copy[key] = product_items
        enriched.append(order_copy)
    return enriched


def _dedupe_orders(rows: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int, int]:
    deduped: Dict[str, Dict[str, Any]] = {}
    unidentified: List[Dict[str, Any]] = []
    for row in rows:
        identity = _order_identity(row)
        if identity:
            deduped.setdefault(identity, row)
        else:
            unidentified.append(row)
    return [*deduped.values(), *unidentified], len(deduped), len(unidentified)


async def fetch_fbits_orders_with_diagnostics(
    *,
    start: str,
    end: str,
    page_limit: int = 200,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    config = get_fbits_config()
    if not config["token"]:
        return [], {}

    base_url = config["base_url"].rstrip("/")
    status_counts: Dict[str, int] = {}
    async with httpx.AsyncClient(timeout=45) as client:
        try:
            detailed_rows = await _fetch_detailed_orders(
                client=client,
                base_url=base_url,
                token=config["token"],
                start=start,
                end=end,
                page_limit=page_limit,
            )
            rows, deduped_count, unidentified_count = _dedupe_orders(detailed_rows)
            rows = await _enrich_orders(
                client=client,
                base_url=base_url,
                token=config["token"],
                rows=rows,
            )
            print(
                "[fbits][orders] "
                f"endpoint=/pedidos start={start} end={end} rows={len(rows)} "
                f"deduped={deduped_count} unidentified={unidentified_count}"
            )
            if rows:
                return rows, status_counts
        except httpx.HTTPStatusError as exc:
            print(
                "[fbits][orders][detail_error] "
                f"endpoint=/pedidos start={start} end={end} http_status={exc.response.status_code}"
            )
        except httpx.HTTPError as exc:
            print(f"[fbits][orders][detail_error] endpoint=/pedidos start={start} end={end} error={exc}")

        fallback_rows: List[Dict[str, Any]] = []
        for status_id in FBITS_APPROVED_ORDER_STATUS_IDS:
            status_counts[status_id] = 0
            try:
                status_rows = await _fetch_orders_for_status(
                    client=client,
                    base_url=base_url,
                    token=config["token"],
                    status_id=status_id,
                    start=start,
                    end=end,
                    page_limit=page_limit,
                )
            except httpx.HTTPStatusError as exc:
                print(
                    "[fbits][orders][status_error] "
                    f"status={status_id} start={start} end={end} "
                    f"http_status={exc.response.status_code} error={exc}"
                )
                continue
            except httpx.HTTPError as exc:
                print(
                    "[fbits][orders][status_error] "
                    f"status={status_id} start={start} end={end} error={exc}"
                )
                continue

            status_counts[status_id] = len(status_rows)
            print(f"[fbits][orders] endpoint=/pedidos/situacaoPedido/{status_id} status={status_id} count={len(status_rows)}")
            fallback_rows.extend(status_rows)

    rows, deduped_count, unidentified_count = _dedupe_orders(fallback_rows)

    print(
        "[fbits][orders] "
        f"store_id={config['store_id'] or '-'} start={start} end={end} "
        f"statuses={FBITS_APPROVED_ORDER_STATUSES} rows={len(rows)} "
        f"deduped={deduped_count} unidentified={unidentified_count}"
    )
    return rows, status_counts


async def fetch_fbits_orders(*, start: str, end: str, page_limit: int = 200) -> List[Dict[str, Any]]:
    rows, _status_counts = await fetch_fbits_orders_with_diagnostics(
        start=start,
        end=end,
        page_limit=page_limit,
    )
    return rows


async def fetch_fbits_revenue_dashboard(*, start: str, end: str) -> Dict[str, Any]:
    config = get_fbits_config()
    if not config["token"]:
        return {}
    base_url = config["base_url"].rstrip("/")
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.get(
            f"{base_url}/dashboard/faturamento",
            headers={
                "Accept": "application/json",
                "Authorization": _authorization_value(config["token"]),
            },
            params={
                "dataInicial": start,
                "dataFinal": end,
                "dataInicialComparativo": start,
                "dataFinalComparativo": end,
            },
        )
        response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}
