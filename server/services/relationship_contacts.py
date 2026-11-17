"""Base de Relacionamento a partir dos clientes já sincronizados por e-commerce.

Não faz scraping nem reimporta pedidos. Cada fonte continua sendo a verdade;
esta projeção criptografada é atualizada por tenant e não concede opt-in.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from .commerce_context import FBITS, SHOPIFY, resolve_commerce_provider
from .crypto import encrypt_secret
from .email_marketing import valid_email
from .ig_supabase import sb_select, sb_upsert
from .sales_by_origin import _paged

TABLE = "relationship_contacts"
LIMIT = 20000
BATCH = 200


class ContactSyncError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


def _key(client_id: str, provider: str, external: str) -> str:
    return hashlib.sha256(f"{client_id}|{provider}|{external}".encode()).hexdigest()


def _clean(value, length=250) -> str:
    return str(value or "").strip()[:length]


def _row(client_id: str, provider: str, item: dict) -> dict | None:
    external = _clean(item.get("shopify_customer_id") if provider == SHOPIFY else item.get("fbits_customer_id"))
    mail = valid_email(item.get("email"))
    phone = "".join(c for c in _clean(item.get("phone"), 40) if c.isdigit())
    phone = phone if 10 <= len(phone) <= 15 else ""
    if not (external or mail or phone):
        return None
    identity = external or (f"email:{mail}" if mail else f"phone:{phone}")
    name = (" ".join(x for x in [_clean(item.get("first_name"), 100), _clean(item.get("last_name"), 100)] if x)
            if provider == SHOPIFY else _clean(item.get("name"), 200))
    return {
        "client_id": client_id,
        "provider": provider,
        "identity_hash": _key(client_id, provider, identity),
        "external_id": external or None,
        "email_hash": hashlib.sha256(f"mugo-mail:{mail}".encode()).hexdigest()[:32] if mail else None,
        "phone_hash": hashlib.sha256(f"mugo-phone:{phone}".encode()).hexdigest() if phone else None,
        "name_ciphertext": encrypt_secret(name) if name else None,
        "email_ciphertext": encrypt_secret(mail) if mail else None,
        "phone_ciphertext": encrypt_secret(phone) if phone else None,
        "marketing_email_verified": False,
        "marketing_whatsapp_verified": False,
        "last_synced_at": datetime.now(timezone.utc).isoformat(),
    }


async def sync_existing_customers(client_id: str) -> dict:
    """Projeção da base já gravada, sem importar novas fontes nem criar consentimento."""
    resolution = await resolve_commerce_provider(client_id)
    provider = str(resolution.get("provider") or "").lower()
    if provider not in (SHOPIFY, FBITS):
        raise ContactSyncError("Empresa sem e-commerce conectado. CRM externo precisa de adaptador próprio.", 409)
    table = "shopify_customers" if provider == SHOPIFY else "fbits_customers"
    order = "updated_at_shopify.desc" if provider == SHOPIFY else "synced_at.desc"
    rows, truncated = await _paged(table, select="*", filters={"client_id": f"eq.{client_id}"}, order=order, max_rows=LIMIT)
    if truncated:
        raise ContactSyncError("Base com 20 mil registros ou mais: aumente a janela de importação antes de executar.", 409)
    data = {}
    for item in rows:
        if str(item.get("client_id") or "") != client_id:
            continue
        prepared = _row(client_id, provider, item)
        if prepared:
            data[prepared["identity_hash"]] = prepared
    values = list(data.values())
    for start in range(0, len(values), BATCH):
        await sb_upsert(TABLE, values[start:start + BATCH], on_conflict="client_id,provider,identity_hash")
    return {"provider": provider, "source_records": len(rows), "contacts_synchronized": len(values),
            "eligible_for_marketing": 0, "note": "Consentimento não inferido por cadastro ou compra."}


async def contacts_status(client_id: str) -> dict:
    """Resumo sem PII, limitado ao tenant."""
    rows, truncated = await _paged(TABLE, select="provider,identity_hash,last_synced_at", filters={
        "client_id": f"eq.{client_id}"}, order="last_synced_at.desc", max_rows=LIMIT)
    return {"total": len(rows), "truncated": truncated,
            "by_provider": {provider: sum(1 for r in rows if r.get("provider") == provider)
                            for provider in sorted({str(r.get("provider") or "") for r in rows})},
            "last_synced_at": rows[0].get("last_synced_at") if rows else None}
