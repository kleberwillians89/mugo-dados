"""Operação explícita, de um tenant, sem alterar pedidos ou marcadores de sync."""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from uuid import UUID

from . import fbits_connections as fbits
from .integration_errors import IntegrationError


class CustomerBackfillError(RuntimeError):
    def __init__(self, *, counts: dict, status_code: int, code: str):
        super().__init__("FBITS_CUSTOMER_BACKFILL_FAILED")
        self.counts = dict(counts)
        self.status_code = status_code
        self.code = code


async def backfill_customer_identities(*, client_id: str, confirm_client_id: str, client_factory=fbits.default_client_factory) -> dict:
    # Confirmação dupla antes de qualquer acesso: nunca aceitar execução global.
    if not client_id or client_id != confirm_client_id:
        raise ValueError("Informe e confirme um único client_id.")
    UUID(client_id)
    counts = {"orders_processed": 0, "identities_found": 0, "identities_persisted": 0, "identities_without_contact": 0, "errors": 0}
    try:
        connection = await fbits.load_fbits_connection(client_id)
        if not connection or connection.get("client_id") != client_id or connection.get("provider") != "fbits":
            raise RuntimeError("FBITS_CONNECTION_NOT_FOUND")
        if connection.get("disconnected_at") or connection.get("status") == "disconnected":
            raise RuntimeError("FBITS_CONNECTION_DISCONNECTED")
        async with fbits.guarded_sync(client_id=client_id, provider="fbits", connection_id=str(connection["id"])):
            # Encerra antes de expirar o lease compartilhado de 30 minutos.
            async with asyncio.timeout(1500):
                current = await fbits.load_fbits_connection(client_id)
                if not current or current.get("client_id") != client_id or current.get("provider") != "fbits" or current.get("id") != connection["id"] or current.get("disconnected_at") or current.get("status") == "disconnected":
                    raise RuntimeError("FBITS_CONNECTION_DISCONNECTED")
                fbits.require_fbits_not_in_cooldown(current)
                # Intervalo completo dos pedidos persistidos; não usa DataAlteracao recente.
                bounds = []
                for direction in ("asc", "desc"):
                    rows = await fbits.sb_select("fbits_orders", select="client_id,order_date", filters={"client_id": f"eq.{client_id}", "order_date": "not.is.null"}, order=f"order_date.{direction}", limit=1)
                    date = fbits._parse_dt(rows[0].get("order_date")) if rows and rows[0].get("client_id") == client_id else None
                    if date is None:
                        raise RuntimeError("FBITS_PERSISTED_HISTORY_NOT_FOUND")
                    bounds.append(date)
                start = bounds[0].replace(hour=0, minute=0, second=0, microsecond=0)
                end = bounds[1].replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                if end <= start:
                    raise RuntimeError("FBITS_INVALID_HISTORY_RANGE")
                full = await fbits.get_connection(client_id, str(current["id"]), include_token=True)
                if full.get("client_id") != client_id or full.get("provider") != "fbits":
                    raise RuntimeError("FBITS_CONNECTION_TENANT_MISMATCH")
                token = fbits._safe_str(json.loads(full.get("_token") or "{}").get("token"))
                if not token:
                    raise RuntimeError("FBITS_REAUTH_REQUIRED")
                client = client_factory(token)
                for window_start, window_end in fbits.plan_windows(start, end):
                    async for page in client.iter_order_pages(start=window_start, end=window_end, date_filter=fbits.HISTORICAL_DATE_FILTER):
                        identities = fbits.normalize_customers(client_id, page, preserve_contacts=True)
                        counts["orders_processed"] += len(page)
                        counts["identities_found"] += len(identities)
                        counts["identities_without_contact"] += sum(not any(row.get(field) for field in ("name", "email", "phone")) for row in identities)
                        counts["identities_persisted"] += await fbits._persist_customer_identities(client_id, page, preserve_existing=True)
    except Exception as exc:
        counts["errors"] += 1
        print("[fbits][customer_backfill] " + json.dumps(counts, sort_keys=True), flush=True)
        status_code, code = 502, "FBITS_CUSTOMER_BACKFILL_FAILED"
        if isinstance(exc, TimeoutError):
            status_code, code = 504, "FBITS_CUSTOMER_BACKFILL_TIMEOUT"
        elif isinstance(exc, IntegrationError) and exc.code == "SYNC_ALREADY_RUNNING":
            status_code, code = 409, "FBITS_CUSTOMER_BACKFILL_BUSY"
        elif isinstance(exc, IntegrationError) and exc.status_code == 429:
            status_code, code = 429, "FBITS_CUSTOMER_BACKFILL_RATE_LIMITED"
        raise CustomerBackfillError(counts=counts, status_code=status_code, code=code) from None
    print("[fbits][customer_backfill] " + json.dumps(counts, sort_keys=True), flush=True)
    return counts
