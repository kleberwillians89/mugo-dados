"""Read-only tenant-scoped Shopify discount codes for Mídia On.

Requires Shopify OAuth read_discounts; never stores or changes discount codes.
"""
from __future__ import annotations

from typing import Any

import httpx

from .integration_errors import IntegrationError
from .shopify_config import shopify_admin_url
from .shopify_oauth import resolve_shopify_connection_context

_QUERY = """
query MediaOnCodeDiscounts($cursor: String) {
  codeDiscountNodes(first: 50, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      codeDiscount {
        __typename
        ... on DiscountCodeBasic {
          title status startsAt endsAt
          codes(first: 10) { nodes { code } }
        }
        ... on DiscountCodeBxgy {
          title status startsAt endsAt
          codes(first: 10) { nodes { code } }
        }
        ... on DiscountCodeFreeShipping {
          title status startsAt endsAt
          codes(first: 10) { nodes { code } }
        }
      }
    }
  }
}
"""


async def list_shopify_promo_codes(client_id: str) -> dict[str, Any]:
    context = await resolve_shopify_connection_context(
        client_id, required_scopes=("read_discounts",),
    )
    result: list[dict[str, Any]] = []
    cursor: str | None = None
    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(4):
            response = await client.post(
                shopify_admin_url(context.shop_domain, "graphql.json"),
                headers={"X-Shopify-Access-Token": context.access_token},
                json={"query": _QUERY, "variables": {"cursor": cursor}},
            )
            if response.status_code in (401, 403):
                raise IntegrationError(
                    "Reconecte o Shopify autorizando leitura de descontos.",
                    status_code=403, code="SHOPIFY_DISCOUNTS_PERMISSION_REQUIRED",
                    provider="shopify",
                )
            if response.status_code >= 400:
                raise IntegrationError(
                    "A Shopify não conseguiu fornecer os cupons agora.",
                    status_code=502, code="SHOPIFY_DISCOUNTS_UNAVAILABLE", provider="shopify",
                )
            payload = response.json()
            if payload.get("errors"):
                raise IntegrationError(
                    "Não foi possível ler os descontos da Shopify. Confira as permissões da loja.",
                    status_code=502, code="SHOPIFY_DISCOUNTS_UNAVAILABLE", provider="shopify",
                )
            page = ((payload.get("data") or {}).get("codeDiscountNodes") or {})
            for node in page.get("nodes") or []:
                discount = node.get("codeDiscount") or {}
                codes = (discount.get("codes") or {}).get("nodes") or []
                for code_row in codes:
                    code = str(code_row.get("code") or "").strip()
                    if code:
                        result.append({
                            "code": code[:120],
                            "title": str(discount.get("title") or "")[:160],
                            "status": str(discount.get("status") or "").upper()[:25],
                            "starts_at": discount.get("startsAt"),
                            "ends_at": discount.get("endsAt"),
                        })
            info = page.get("pageInfo") or {}
            next_cursor = str(info.get("endCursor") or "")
            if not info.get("hasNextPage") or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
    return {"source": "shopify", "codes": result, "read_only": True,
            "partial": bool(cursor and len(result) >= 200)}
