"""Customer 360: base de clientes do e-commerce, independente do provider.

O provider é resolvido pela conexão do tenant (FBITS ou Shopify), nunca pelo
nome da empresa, e os dois caminhos entregam o MESMO contrato — o frontend não
sabe de onde veio. Tudo sai do que já está persistido pelos syncs existentes:
nenhuma chamada a FBITS ou Shopify acontece ao abrir a página.

Identidade (nunca por nome): id externo do cliente → e-mail normalizado →
telefone normalizado. Pedido sem nenhum desses não é atribuído a ninguém.

Receita/pedidos reaproveitam a regra que cada provider já tem:
- FBITS: situação na lista de receita da conexão do tenant E `is_valid` não
  falso, o mesmo `_counts_as_revenue` do relatório oficial.
- Shopify: `_is_recognized_order`, o mesmo reconhecimento do relatório.

PII (nome, e-mail, telefone) nunca entra em log: só client_id, provider,
contagens, status, duração e request_id.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .commerce_context import FBITS, SHOPIFY, resolve_commerce_provider
from .ig_supabase import sb_select

# Teto de pedidos lidos por tenant numa listagem. Uma consulta por tabela,
# agregação em memória: sem N+1 e sem chamar o provider por cliente. O teto
# existe para a página não degradar numa base muito grande; quando ele é
# atingido o contrato devolve `truncated=True` e a interface pode dizer isso.
CUSTOMER_ORDER_SCAN_LIMIT = 20000
PAGE_SIZE_DEFAULT = 25
PAGE_SIZE_MAX = 100

IDENTITY_EXTERNAL_ID = "external_id"
IDENTITY_EMAIL = "email"
IDENTITY_PHONE = "phone"

STATUS_RECURRING = "recurring"
STATUS_SINGLE = "single"
STATUS_NO_PURCHASE = "no_purchase"

PROVIDER_LABELS = {FBITS: "FBITS", SHOPIFY: "Shopify"}

_DIGITS = re.compile(r"\D+")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float:
    try:
        return float(str(value if value is not None else "0").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _normalized_email(value: Any) -> str:
    email = _text(value).lower()
    return email if "@" in email and "." in email.split("@")[-1] else ""


def _normalized_phone(value: Any) -> str:
    """Só dígitos. Curto demais não identifica ninguém e é tratado como ausente."""
    digits = _DIGITS.sub("", _text(value))
    return digits if len(digits) >= 10 else ""


def _identity(
    *, external_id: Any = None, email: Any = None, phone: Any = None,
) -> Tuple[str, str]:
    """Identificador mais confiável disponível, em ordem de prioridade.

    Nome jamais entra: homônimos são pessoas diferentes e fundi-los inventaria
    um cliente que não existe.
    """
    identifier = _text(external_id)
    if identifier:
        return IDENTITY_EXTERNAL_ID, identifier
    email_value = _normalized_email(email)
    if email_value:
        return IDENTITY_EMAIL, email_value
    phone_value = _normalized_phone(phone)
    if phone_value:
        return IDENTITY_PHONE, phone_value
    return "", ""


def customer_key(client_id: str, kind: str, value: str) -> str:
    """Chave pública opaca e estável do cliente.

    Inclui o tenant, então a chave de um cliente nunca colide com a de outra
    empresa. É um hash de propósito: e-mail e telefone não podem viajar em URL
    nem aparecer em log de acesso.
    """
    seed = f"{_text(client_id)}|{_text(kind)}|{_text(value)}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()[:32]


def _parse_timestamp(value: Any) -> Optional[datetime]:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso_or_none(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


class _Accumulator:
    """Agrega os pedidos de um cliente sem inventar o que não existe."""

    __slots__ = (
        "kind", "value", "external_id", "name", "email", "phone",
        "orders_count", "total_revenue", "first_order_at", "last_order_at",
        "contact_seen_at", "orders",
    )

    def __init__(self, kind: str, value: str) -> None:
        self.kind = kind
        self.value = value
        self.external_id: Optional[str] = None
        self.name: Optional[str] = None
        self.email: Optional[str] = None
        self.phone: Optional[str] = None
        self.orders_count = 0
        self.total_revenue = 0.0
        self.first_order_at: Optional[datetime] = None
        self.last_order_at: Optional[datetime] = None
        self.contact_seen_at: Optional[datetime] = None
        self.orders: List[Dict[str, Any]] = []

    def observe_contact(
        self, *, name: Any, email: Any, phone: Any, seen_at: Optional[datetime],
    ) -> None:
        """Dados de contato mais recentes, campo por campo, sem sobrescrever
        um valor existente por vazio."""
        newer = (
            self.contact_seen_at is None
            or (seen_at is not None and seen_at >= self.contact_seen_at)
        )
        for attribute, incoming in (
            ("name", _text(name) or None),
            ("email", _normalized_email(email) or None),
            ("phone", _normalized_phone(phone) or None),
        ):
            if incoming and (newer or getattr(self, attribute) is None):
                setattr(self, attribute, incoming)
        if seen_at is not None and (self.contact_seen_at is None or seen_at >= self.contact_seen_at):
            self.contact_seen_at = seen_at

    def observe_revenue(self, *, value: float, happened_at: Optional[datetime]) -> None:
        self.orders_count += 1
        self.total_revenue += value
        if happened_at is not None:
            if self.first_order_at is None or happened_at < self.first_order_at:
                self.first_order_at = happened_at
            if self.last_order_at is None or happened_at > self.last_order_at:
                self.last_order_at = happened_at

    def summary(self, *, client_id: str, provider: str) -> Dict[str, Any]:
        average = round(self.total_revenue / self.orders_count, 2) if self.orders_count else None
        status = (
            STATUS_RECURRING if self.orders_count >= 2
            else STATUS_SINGLE if self.orders_count == 1
            else STATUS_NO_PURCHASE
        )
        return {
            "id": customer_key(client_id, self.kind, self.value),
            "external_id": self.external_id,
            "client_id": client_id,
            "provider": provider,
            "provider_label": PROVIDER_LABELS.get(provider, provider),
            "identity_kind": self.kind,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "orders_count": self.orders_count,
            "total_revenue": round(self.total_revenue, 2),
            "average_ticket": average,
            "first_order_at": _iso_or_none(self.first_order_at),
            "last_order_at": _iso_or_none(self.last_order_at),
            "status": status,
        }


def _own_rows(rows: Iterable[Dict[str, Any]], client_id: str) -> List[Dict[str, Any]]:
    """Segunda barreira: linha de outro tenant é descartada mesmo que a query
    tenha sido montada errado. O backend usa service role e ignora RLS."""
    return [row for row in rows or [] if _text(row.get("client_id")) == _text(client_id)]


# --------------------------------------------------------------------------
# FBITS
# --------------------------------------------------------------------------

async def _fbits_identities(client_id: str) -> Dict[str, Dict[str, Any]]:
    """Identidades de `fbits_customers`, numa leitura só.

    A tabela pode não existir ainda (migration 040 pendente): nesse caso o
    Customer 360 segue sem contato, exatamente como antes, em vez de a página
    inteira falhar. O log carrega só a contagem, nunca PII.
    """
    try:
        rows = _own_rows(
            await sb_select(
                "fbits_customers",
                select="client_id,fbits_customer_id,name,email,phone,updated_at_provider,synced_at",
                filters={"client_id": f"eq.{_text(client_id)}"},
                order="synced_at.desc",
                limit=CUSTOMER_ORDER_SCAN_LIMIT,
            ),
            client_id,
        )
    except Exception as exc:  # noqa: BLE001 - sem identidade a base ainda serve
        print(
            f"[customers] client_id={_text(client_id)} provider={FBITS} "
            f"status=identity_unavailable error_type={exc.__class__.__name__} "
            "migration=20261004_000040_fbits_customer_identity",
            flush=True,
        )
        return {}
    return {
        _text(row.get("fbits_customer_id")): row
        for row in rows
        if _text(row.get("fbits_customer_id"))
    }


async def _fbits_accumulators(client_id: str) -> Tuple[Dict[str, _Accumulator], Dict[str, Any]]:
    from .fbits_reporting import _counts_as_revenue, _tenant_revenue_context

    _, revenue_status_ids, _ = await _tenant_revenue_context(client_id)
    identities = await _fbits_identities(client_id)
    rows = _own_rows(
        await sb_select(
            "fbits_orders",
            select=(
                "client_id,order_id,order_code,customer_id,customer_name,customer_email,"
                "status_id,status_name,order_date,total_value,is_valid,raw"
            ),
            filters={"client_id": f"eq.{_text(client_id)}"},
            order="order_date.desc",
            limit=CUSTOMER_ORDER_SCAN_LIMIT,
        ),
        client_id,
    )
    accumulators: Dict[str, _Accumulator] = {}
    unattributed = 0
    for row in rows:
        kind, value = _identity(
            external_id=row.get("customer_id"),
            email=row.get("customer_email"),
        )
        if not kind:
            unattributed += 1
            continue
        accumulator = accumulators.setdefault(f"{kind}:{value}", _Accumulator(kind, value))
        if kind == IDENTITY_EXTERNAL_ID:
            accumulator.external_id = value
        happened_at = _parse_timestamp(row.get("order_date"))
        # A identidade vem de `fbits_customers`, não do pedido: `fbits_orders`
        # segue sem PII. As colunas customer_name/customer_email do pedido só
        # têm valor em linhas legadas e entram apenas como último recurso.
        identity = identities.get(_text(row.get("customer_id"))) or {}
        accumulator.observe_contact(
            name=identity.get("name") or row.get("customer_name"),
            email=identity.get("email") or row.get("customer_email"),
            phone=identity.get("phone"),
            seen_at=happened_at,
        )
        counts = _counts_as_revenue(row, revenue_status_ids)
        if counts:
            accumulator.observe_revenue(
                value=_number(row.get("total_value")), happened_at=happened_at,
            )
        accumulator.orders.append({
            "order_id": _text(row.get("order_id")),
            "reference": _text(row.get("order_code")) or _text(row.get("order_id")),
            "happened_at": _iso_or_none(happened_at),
            "value": round(_number(row.get("total_value")), 2),
            "status": _text(row.get("status_name")) or _text(row.get("status_id")) or None,
            "counts_as_revenue": counts,
        })
    return accumulators, {"orders_scanned": len(rows), "orders_unattributed": unattributed}


# --------------------------------------------------------------------------
# Shopify
# --------------------------------------------------------------------------

async def _shopify_accumulators(client_id: str) -> Tuple[Dict[str, _Accumulator], Dict[str, Any]]:
    from .shopify_reporting import _is_recognized_order

    orders = _own_rows(
        await sb_select(
            "shopify_orders",
            select=(
                "client_id,shopify_order_id,order_number,name,email,customer_id,"
                "financial_status,total_price,cancelled_at,created_at_shopify"
            ),
            filters={"client_id": f"eq.{_text(client_id)}"},
            order="created_at_shopify.desc",
            limit=CUSTOMER_ORDER_SCAN_LIMIT,
        ),
        client_id,
    )
    profiles = {
        _text(row.get("shopify_customer_id")): row
        for row in _own_rows(
            await sb_select(
                "shopify_customers",
                select=(
                    "client_id,shopify_customer_id,email,first_name,last_name,phone,"
                    "orders_count,total_spent,updated_at_shopify"
                ),
                filters={"client_id": f"eq.{_text(client_id)}"},
                order="updated_at_shopify.desc",
                limit=CUSTOMER_ORDER_SCAN_LIMIT,
            ),
            client_id,
        )
        if _text(row.get("shopify_customer_id"))
    }
    accumulators: Dict[str, _Accumulator] = {}
    unattributed = 0
    for row in orders:
        external_id = _text(row.get("customer_id"))
        profile = profiles.get(external_id) or {}
        kind, value = _identity(
            external_id=external_id,
            email=row.get("email") or profile.get("email"),
            phone=profile.get("phone"),
        )
        if not kind:
            unattributed += 1
            continue
        accumulator = accumulators.setdefault(f"{kind}:{value}", _Accumulator(kind, value))
        if kind == IDENTITY_EXTERNAL_ID:
            accumulator.external_id = value
        happened_at = _parse_timestamp(row.get("created_at_shopify"))
        full_name = " ".join(
            part for part in (_text(profile.get("first_name")), _text(profile.get("last_name"))) if part
        )
        accumulator.observe_contact(
            name=full_name or None,
            email=row.get("email") or profile.get("email"),
            phone=profile.get("phone"),
            seen_at=happened_at,
        )
        counts = _is_recognized_order(row)
        if counts:
            accumulator.observe_revenue(
                value=_number(row.get("total_price")), happened_at=happened_at,
            )
        accumulator.orders.append({
            "order_id": _text(row.get("shopify_order_id")),
            "reference": _text(row.get("name")) or _text(row.get("order_number")) or _text(row.get("shopify_order_id")),
            "happened_at": _iso_or_none(happened_at),
            "value": round(_number(row.get("total_price")), 2),
            "status": (
                "Cancelado" if _text(row.get("cancelled_at"))
                else _text(row.get("financial_status")) or None
            ),
            "counts_as_revenue": counts,
        })
    return accumulators, {"orders_scanned": len(orders), "orders_unattributed": unattributed}


# --------------------------------------------------------------------------
# Contrato público
# --------------------------------------------------------------------------

async def _accumulators_for(client_id: str) -> Tuple[str, Dict[str, _Accumulator], Dict[str, Any]]:
    resolution = await resolve_commerce_provider(client_id)
    provider = _text(resolution.get("provider")).lower()
    if provider == FBITS:
        accumulators, stats = await _fbits_accumulators(client_id)
    elif provider == SHOPIFY:
        accumulators, stats = await _shopify_accumulators(client_id)
    else:
        return "", {}, {"orders_scanned": 0, "orders_unattributed": 0}
    stats["truncated"] = stats.get("orders_scanned", 0) >= CUSTOMER_ORDER_SCAN_LIMIT
    return provider, accumulators, stats


_PHONE_SEARCH = re.compile(r"^[\d\s()+.\-]+$")


def _matches(summary: Dict[str, Any], search: str) -> bool:
    """Busca por nome, e-mail ou telefone, ignorando a formatação do telefone.

    O termo só é lido como telefone quando não tem letra nem arroba: senão
    `cliente7@exemplo.com` viraria o dígito "7" e casaria com meia base.
    """
    if not search:
        return True
    needle = search.strip().lower()
    for field in ("name", "email"):
        if needle in _text(summary.get(field)).lower():
            return True
    if _PHONE_SEARCH.fullmatch(needle):
        digits = _DIGITS.sub("", needle)
        if len(digits) >= 4 and digits in _text(summary.get("phone")):
            return True
    return False


def _base_totals(summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
    revenue = round(sum(_number(item.get("total_revenue")) for item in summaries), 2)
    orders = sum(int(item.get("orders_count") or 0) for item in summaries)
    buyers = [item for item in summaries if int(item.get("orders_count") or 0) > 0]
    return {
        "customers": len(summaries),
        "recurring_customers": len([item for item in summaries if item.get("status") == STATUS_RECURRING]),
        "buyers": len(buyers),
        "total_revenue": revenue,
        "total_orders": orders,
        "average_ticket": round(revenue / orders, 2) if orders else None,
    }


async def list_customers(
    *,
    client_id: str,
    search: str = "",
    page: int = 1,
    page_size: int = PAGE_SIZE_DEFAULT,
) -> Dict[str, Any]:
    """Base de clientes do tenant, já agregada e paginada."""
    provider, accumulators, stats = await _accumulators_for(client_id)
    if not provider:
        return {
            "ok": True, "client_id": client_id, "provider": None, "provider_label": None,
            "connected": False, "totals": _base_totals([]), "customers": [],
            "page": 1, "page_size": page_size, "total": 0, "truncated": False,
            "contact_details_available": False, "orders_unattributed": 0,
        }
    summaries = [
        accumulator.summary(client_id=client_id, provider=provider)
        for accumulator in accumulators.values()
    ]
    totals = _base_totals(summaries)
    filtered = [item for item in summaries if _matches(item, search)]
    # Maior receita primeiro; empate pela compra mais recente.
    filtered.sort(
        key=lambda item: (
            -_number(item.get("total_revenue")),
            _text(item.get("last_order_at")) == "",
            [-ord(char) for char in _text(item.get("last_order_at"))],
        ),
    )
    size = max(1, min(int(page_size or PAGE_SIZE_DEFAULT), PAGE_SIZE_MAX))
    current = max(1, int(page or 1))
    start = (current - 1) * size
    return {
        "ok": True,
        "client_id": client_id,
        "provider": provider,
        "provider_label": PROVIDER_LABELS.get(provider, provider),
        "connected": True,
        "totals": totals,
        "customers": filtered[start:start + size],
        "page": current,
        "page_size": size,
        "total": len(filtered),
        "truncated": bool(stats.get("truncated")),
        # FBITS não persiste contato: a interface informa em vez de fingir.
        "contact_details_available": any(
            item.get("email") or item.get("phone") or item.get("name") for item in summaries
        ),
        "orders_unattributed": int(stats.get("orders_unattributed") or 0),
    }


async def get_customer(*, client_id: str, customer_id: str) -> Dict[str, Any]:
    """Detalhe de um cliente do tenant, com histórico de pedidos.

    A busca é pela chave opaca, que já carrega o tenant: a chave de outra
    empresa simplesmente não existe aqui.
    """
    provider, accumulators, _ = await _accumulators_for(client_id)
    wanted = _text(customer_id)
    for accumulator in accumulators.values():
        if customer_key(client_id, accumulator.kind, accumulator.value) != wanted:
            continue
        summary = accumulator.summary(client_id=client_id, provider=provider)
        orders = sorted(
            accumulator.orders,
            key=lambda item: _text(item.get("happened_at")),
            reverse=True,
        )
        return {"ok": True, "client_id": client_id, "customer": summary, "orders": orders}
    raise RuntimeError("CUSTOMER_NOT_FOUND")
