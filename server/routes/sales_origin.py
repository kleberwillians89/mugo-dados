"""Vendas por origem do pedido (somente leitura, escopo da empresa)."""
from datetime import date

from fastapi import APIRouter, Header, HTTPException

from services.sales_by_origin import build_sales_by_origin
from services.tenant import require_client_read

router = APIRouter(prefix="/api/clients/{client_id}/sales-by-origin", tags=["sales-by-origin"])


@router.get("")
async def read_sales_by_origin(
    client_id: str,
    start: date | None = None,
    end: date | None = None,
    authorization: str | None = Header(default=None),
):
    cid = await require_client_read(client_id, authorization)
    if start and end and (end < start or (end - start).days > 366):
        raise HTTPException(422, "Período inválido.")
    try:
        return await build_sales_by_origin(
            cid, start=start.isoformat() if start else None, end=end.isoformat() if end else None,
        )
    except Exception as exc:
        print(f"[sales_by_origin] client_id={cid} status=error error_type={exc.__class__.__name__}")
        raise HTTPException(503, "Não foi possível carregar as vendas por origem. Tente novamente.") from None
