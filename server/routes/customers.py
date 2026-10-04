from __future__ import annotations

import time

from fastapi import APIRouter, Header, HTTPException, Query

from api_support import get_request_id
from services.customers import PAGE_SIZE_DEFAULT, PAGE_SIZE_MAX, get_customer, list_customers
from services.tenant import require_client_read

router = APIRouter(prefix="/api/customers", tags=["customers"])


def _log(
    *,
    endpoint: str,
    client_id: str,
    provider: str | None,
    status: str,
    started: float,
    count: int | None = None,
    error_type: str | None = None,
) -> None:
    """Clientes são PII: o log carrega só tenant, provider, contagem e tempo.

    Nunca nome, e-mail, telefone, endereço ou payload de cliente.
    """
    parts = [
        f"endpoint={endpoint}",
        f"client_id={client_id}",
        f"provider={provider or '-'}",
        f"status={status}",
        f"count={count if count is not None else '-'}",
        f"duration_ms={int((time.perf_counter() - started) * 1000)}",
        f"request_id={get_request_id() or '-'}",
    ]
    if error_type:
        parts.append(f"error_type={error_type}")
    print("[customers] " + " ".join(parts), flush=True)


@router.get("")
async def customers_list(
    search: str = Query(default="", max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    # O client_id do browser é apenas um pedido: require_client_read resolve
    # contra a membership real e recusa o que não pertence ao usuário.
    cid = await require_client_read(client_id or x_client_id, authorization)
    started = time.perf_counter()
    try:
        payload = await list_customers(
            client_id=cid, search=search, page=page, page_size=page_size,
        )
    except Exception as exc:
        _log(
            endpoint="/api/customers", client_id=cid, provider=None,
            status="error", started=started, error_type=exc.__class__.__name__,
        )
        raise HTTPException(
            status_code=502,
            detail="A base de clientes não pôde ser carregada agora. Tente novamente em instantes.",
        ) from exc
    _log(
        endpoint="/api/customers", client_id=cid, provider=payload.get("provider"),
        status="ok", started=started, count=payload.get("total"),
    )
    return payload


@router.get("/{customer_id}")
async def customers_detail(
    customer_id: str,
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid = await require_client_read(client_id or x_client_id, authorization)
    started = time.perf_counter()
    try:
        payload = await get_customer(client_id=cid, customer_id=customer_id)
    except RuntimeError as exc:
        if str(exc) == "CUSTOMER_NOT_FOUND":
            _log(
                endpoint="/api/customers/{id}", client_id=cid, provider=None,
                status="not_found", started=started,
            )
            raise HTTPException(
                status_code=404, detail="Cliente não encontrado nesta empresa.",
            ) from exc
        _log(
            endpoint="/api/customers/{id}", client_id=cid, provider=None,
            status="error", started=started, error_type=exc.__class__.__name__,
        )
        raise HTTPException(
            status_code=502, detail="O cliente não pôde ser carregado agora.",
        ) from exc
    except Exception as exc:
        _log(
            endpoint="/api/customers/{id}", client_id=cid, provider=None,
            status="error", started=started, error_type=exc.__class__.__name__,
        )
        raise HTTPException(
            status_code=502, detail="O cliente não pôde ser carregado agora.",
        ) from exc
    _log(
        endpoint="/api/customers/{id}", client_id=cid,
        provider=(payload.get("customer") or {}).get("provider"),
        status="ok", started=started, count=len(payload.get("orders") or []),
    )
    return payload
