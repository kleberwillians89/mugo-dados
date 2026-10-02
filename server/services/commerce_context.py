"""Qual plataforma de e-commerce é a fonte de verdade desta empresa.

O provider é resolvido pela conexão do tenant em `integration_connections` —
NUNCA pelo nome da empresa. "Curavino = FBITS" e "Roove = Shopify" são
coincidências dos dados atuais, não regra.

FBITS e Shopify não têm a mesma semântica, e a diferença é preservada:

- **FBITS**: receita, pedidos e ticket médio vêm dos indicadores oficiais da
  própria loja (`GET /dashboard/faturamento`, via `build_fbits_summary`). São
  os mesmos números do painel FBITS e **não são recalculados aqui**. Quando o
  oficial está indisponível, o backend já devolve `kpi_source`
  `fbits_orders_fallback`, e essa procedência é propagada em vez de escondida.
- **Shopify**: os agregados normalizados do read model, calculados pelo
  pipeline próprio da Shopify.

Depois de normalizado, quem consome pode raciocinar sobre conceitos comuns
(receita, pedidos, ticket) desde que carregue `provider` e `kpi_source`: é o
que impede atribuir a uma loja FBITS um número com semântica de Shopify.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .ig_supabase import sb_select

SHOPIFY = "shopify"
FBITS = "fbits"
COMMERCE_PROVIDERS = (FBITS, SHOPIFY)
PROVIDER_LABELS = {FBITS: "FBITS/Wake", SHOPIFY: "Shopify"}
INACTIVE_STATUSES = {"disconnected", "not_configured"}


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool) or _text(value) == "":
        return None
    try:
        return float(_text(value).replace(",", "."))
    except ValueError:
        return None


def is_active_connection(row: Dict[str, Any]) -> bool:
    return (
        not row.get("disconnected_at")
        and _text(row.get("status")).lower() not in INACTIVE_STATUSES
    )


def select_commerce_connection(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A conexão de e-commerce ativa da empresa.

    Com FBITS e Shopify ativos ao mesmo tempo, FBITS vence por ter indicadores
    oficiais da própria loja. A escolha é explícita e fica em `ambiguous` para
    quem consome poder avisar, em vez de depender da ordem da listagem.
    """
    active = [
        row for row in rows
        if _text(row.get("provider")).lower() in COMMERCE_PROVIDERS and is_active_connection(row)
    ]
    for provider in COMMERCE_PROVIDERS:
        for row in active:
            if _text(row.get("provider")).lower() == provider:
                return row
    return None


def _empty_context(reason: str) -> Dict[str, Any]:
    return {
        "provider": None,
        "provider_label": None,
        "connected": False,
        "status": reason,
        "kpi_source": None,
        "metrics": {},
        "provenance": {},
    }


def build_fbits_commerce_context(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza o resumo FBITS sem recalcular os KPIs executivos."""
    totals = summary.get("summary") if isinstance(summary.get("summary"), dict) else {}
    comparison = summary.get("comparison") if isinstance(summary.get("comparison"), dict) else {}
    kpi_source = _text(summary.get("kpi_source")) or None

    def previous(metric: str) -> Optional[float]:
        entry = comparison.get(metric)
        return _number((entry or {}).get("previous")) if isinstance(entry, dict) else None

    def variation(metric: str) -> Optional[float]:
        entry = comparison.get(metric)
        return _number((entry or {}).get("change_percent")) if isinstance(entry, dict) else None

    return {
        "provider": FBITS,
        "provider_label": PROVIDER_LABELS[FBITS],
        "connected": bool(summary.get("connected")),
        "status": "ok",
        "kpi_source": kpi_source,
        "metrics": {
            "revenue": {"value": _number(totals.get("receita_oficial")), "previous": previous("receita_oficial"), "variation": variation("receita_oficial")},
            "orders": {"value": _number(totals.get("pedidos")), "previous": previous("pedidos"), "variation": variation("pedidos")},
            "average_ticket": {"value": _number(totals.get("ticket_medio")), "previous": previous("ticket_medio"), "variation": variation("ticket_medio")},
            "customers": {"value": _number(totals.get("clientes")), "previous": None, "variation": None},
            "discounts": {"value": _number(totals.get("descontos")), "previous": None, "variation": None},
            "freight": {"value": _number(totals.get("frete")), "previous": None, "variation": None},
        },
        "provenance": {
            # Oficial da loja: o mesmo número do painel FBITS, não derivado dos pedidos.
            "revenue": kpi_source, "orders": kpi_source, "average_ticket": kpi_source,
            # Analíticos: derivados de GET /pedidos já sincronizados.
            "customers": "fbits_orders", "discounts": "fbits_orders", "freight": "fbits_orders",
        },
        "official_kpis": kpi_source == "fbits_dashboard",
        "last_success_at": summary.get("last_sync_at"),
        "status_distribution": summary.get("status_distribution") or [],
    }


def build_shopify_commerce_context(
    *, connected: bool, current: Dict[str, Any], previous: Dict[str, Any], deltas: Dict[str, Any],
) -> Dict[str, Any]:
    """Normaliza os agregados Shopify do read model, sem semântica FBITS."""
    def delta(key: str) -> Optional[float]:
        entry = deltas.get(key)
        return _number((entry or {}).get("percent")) if isinstance(entry, dict) else None

    return {
        "provider": SHOPIFY,
        "provider_label": PROVIDER_LABELS[SHOPIFY],
        "connected": connected,
        "status": "ok",
        "kpi_source": "shopify_read_model",
        "metrics": {
            "revenue": {"value": _number(current.get("net_revenue")), "previous": _number(previous.get("net_revenue")), "variation": delta("shopify_net_revenue")},
            "orders": {"value": _number(current.get("orders")), "previous": _number(previous.get("orders")), "variation": delta("shopify_orders")},
            "average_ticket": {"value": _number(current.get("average_order_value")), "previous": _number(previous.get("average_order_value")), "variation": None},
            "customers": {"value": _number(current.get("new_customers")), "previous": None, "variation": None},
        },
        "provenance": {
            "revenue": "shopify_read_model", "orders": "shopify_read_model",
            "average_ticket": "shopify_read_model", "customers": "shopify_read_model",
        },
        "official_kpis": False,
        "last_success_at": current.get("last_success_at"),
        "status_distribution": [],
    }


async def resolve_commerce_provider(client_id: str) -> Dict[str, Any]:
    """Provider de e-commerce do tenant, pela conexão — nunca pelo nome."""
    try:
        rows = await sb_select(
            "integration_connections",
            select="id,client_id,provider,status,disconnected_at,updated_at",
            filters={"client_id": f"eq.{_text(client_id)}"},
            order="updated_at.desc", limit=50,
        )
    except Exception as exc:
        # Degrada: sem provider resolvido a análise segue com as outras fontes,
        # em vez de falhar inteira por causa da leitura das conexões.
        print(
            f"[intelligence][commerce] client_id={_text(client_id)} stage=resolve_provider "
            f"status=unavailable error_type={exc.__class__.__name__}"
        )
        return {"provider": None, "connection_id": None, "ambiguous": False, "active_providers": [], "resolution_failed": True}
    tenant_rows = [row for row in rows if _text(row.get("client_id")) == _text(client_id)]
    chosen = select_commerce_connection(tenant_rows)
    active_providers = sorted({
        _text(row.get("provider")).lower() for row in tenant_rows
        if _text(row.get("provider")).lower() in COMMERCE_PROVIDERS and is_active_connection(row)
    })
    if not chosen:
        return {"provider": None, "connection_id": None, "ambiguous": False, "active_providers": [], "resolution_failed": False}
    return {
        "provider": _text(chosen.get("provider")).lower(),
        "connection_id": _text(chosen.get("id")) or None,
        "ambiguous": len(active_providers) > 1,
        "active_providers": active_providers,
    }


async def resolve_commerce_context(
    *, client_id: str, start: str, end: str,
    shopify_section: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Contexto de e-commerce normalizado, com provider e procedência.

    `shopify_section` são os agregados que o chamador já leu do read model —
    não há segunda consulta para Shopify. Para FBITS, os indicadores oficiais
    são buscados pelo caminho oficial do backend.
    """
    resolved = await resolve_commerce_provider(client_id)
    provider = resolved["provider"]
    if not provider:
        reason = "unavailable" if resolved.get("resolution_failed") else "not_connected"
        return {**_empty_context(reason), "ambiguous": False, "active_providers": []}

    if provider == FBITS:
        from .fbits_reporting import FbitsPeriod, build_fbits_summary

        try:
            summary = await build_fbits_summary(
                client_id=client_id, period=FbitsPeriod(start=start, end=end),
            )
        except Exception as exc:
            print(
                f"[intelligence][commerce] client_id={client_id} provider=fbits "
                f"status=unavailable error_type={exc.__class__.__name__}"
            )
            return {
                **_empty_context("unavailable"), "provider": FBITS,
                "provider_label": PROVIDER_LABELS[FBITS], "connected": True,
                "ambiguous": resolved["ambiguous"], "active_providers": resolved["active_providers"],
            }
        context = build_fbits_commerce_context(summary)
    else:
        section = shopify_section if isinstance(shopify_section, dict) else {}
        context = build_shopify_commerce_context(
            connected=True,
            current=section,
            previous=section.get("previous") if isinstance(section.get("previous"), dict) else {},
            deltas=section.get("deltas") if isinstance(section.get("deltas"), dict) else {},
        )

    context["connection_id"] = resolved["connection_id"]
    context["ambiguous"] = resolved["ambiguous"]
    context["active_providers"] = resolved["active_providers"]
    return context
