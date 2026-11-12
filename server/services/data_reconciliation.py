"""Auditoria cruzada dos dados: loja (Shopify/FBITS) × GA4 × Meta × Google no mesmo período.

A loja é a fonte da verdade da venda (pedido real, não cancelado). Cada plataforma é conferida contra ela, e cada
conferência diz em português o que está acontecendo, a causa provável e o que fazer:

1. Compras no GA4 × pedidos da loja: o GA4 está vendo as vendas? (menos = tag de compra faltando; mais = evento
   duplicado).
2. Receita no GA4 × receita da loja.
3. Pedidos da loja achados no GA4 pela transação: o elo pedido a pedido que liga a venda à sessão.
4. Atribuição somada (Meta + Google) × receita da loja: as plataformas contando a mesma venda.
5. Compras que a Meta diz ter gerado × pedidos da loja vindos de redes pagas (mesmo para o Google).
6. Pedidos com origem identificada (UTM, referência ou GA4).
7. Dias sem dado por fonte no período.
8. Duplicidade: pedido repetido na loja (no GA4, compra a mais aparece na conferência 1).

Somente leitura; não altera nenhum número dos painéis. Limiares são de diagnóstico (onde vale olhar), não de
contabilidade. Nada é estimado: sem dado, a conferência fica "sem dado" e explica o porquê.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_select

DAILY_FIELDS = ("shopify_net_revenue", "shopify_orders", "ga4_revenue", "ga4_purchases", "meta_spend",
                "meta_attributed_revenue", "meta_purchases", "google_ads_spend", "google_ads_conversion_value",
                "google_ads_conversions")
COVERAGE = {"ga4_sessions": "GA4", "meta_spend": "Meta Ads", "google_ads_spend": "Google Ads"}


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _pct(part: Optional[float], whole: Optional[float]) -> Optional[float]:
    return round(part / whole * 100, 1) if part is not None and whole else None


def _fmt(n: Optional[float], money: bool = False) -> str:
    if n is None:
        return "—"
    text = f"{n:,.0f}".replace(",", ".")
    return f"R$ {text}" if money else text


def check(key: str, title: str, status: str, value: Optional[float], detail: str, *, cause: str = "", todo: str = "",
          unit: str = "%") -> Dict[str, Any]:
    return {"key": key, "title": title, "status": status, "value": value, "unit": unit, "detail": detail,
            "cause": cause if status not in ("ok", "na") else "", "todo": todo if status not in ("ok", "na") else ""}


def band(ratio: Optional[float], ok: tuple, warn: tuple) -> str:
    if ratio is None:
        return "na"
    if ok[0] <= ratio <= ok[1]:
        return "ok"
    if warn[0] <= ratio <= warn[1]:
        return "warn"
    return "bad"


def build_checks(store: Dict[str, Any], daily: Dict[str, Any], ga4: Dict[str, Any], dup: Dict[str, int]) -> List[Dict[str, Any]]:
    """Função pura: recebe os números já lidos e devolve as conferências."""
    out: List[Dict[str, Any]] = []
    orders, revenue = store.get("orders"), store.get("revenue")
    sums, days = daily["sums"], daily["days"]
    has_store = bool(orders)

    # 1 e 2: GA4 × loja
    if not has_store:
        out.append(check("ga4_orders", "GA4 enxerga as vendas da loja", "na", None, "Sem pedidos da loja no período para comparar."))
    elif not days.get("ga4_purchases"):
        out.append(check("ga4_orders", "GA4 enxerga as vendas da loja", "na", None, "Sem dado de compras do GA4 no período (GA4 não conectado ou sem sincronização)."))
    else:
        r = _pct(sums["ga4_purchases"], orders)
        st = band(r, (85, 110), (60, 130))
        out.append(check("ga4_orders", "GA4 enxerga as vendas da loja", st, r,
                         f"{_fmt(sums['ga4_purchases'])} compras no GA4 para {_fmt(orders)} pedidos da loja.",
                         cause=("O evento de compra não dispara em parte das vendas (checkout externo, página de obrigado sem tag, "
                                "bloqueador de anúncio ou consentimento de cookies)." if r is not None and r < 85 else
                                "O GA4 conta compras a mais: evento purchase disparando duas vezes (recarregar a página de obrigado) "
                                "ou duas tags enviando a mesma compra."),
                         todo=("Conferir a tag de compra no checkout (GTM/app da loja) e o modo de consentimento." if r is not None and r < 85
                               else "Garantir que o purchase envie transaction_id e dispare uma vez só.")))
        r2 = _pct(sums["ga4_revenue"], revenue)
        out.append(check("ga4_revenue", "Receita no GA4 × receita da loja", band(r2, (85, 110), (60, 130)), r2,
                         f"{_fmt(sums['ga4_revenue'], True)} no GA4 para {_fmt(revenue, True)} na loja.",
                         cause="Mesmas causas das compras; além disso, frete, desconto ou moeda podem entrar diferente no valor enviado ao GA4.",
                         todo="Comparar o value do evento purchase com o total do pedido em uma compra de teste."))

    # 3: elo pedido a pedido
    if has_store and ga4.get("transactions"):
        r = _pct(ga4.get("matched"), orders)
        out.append(check("ga4_match", "Pedidos da loja achados no GA4 pela transação", band(r, (80, 100), (50, 100)), r,
                         f"{_fmt(ga4.get('matched'))} de {_fmt(orders)} pedidos têm o mesmo ID de transação no GA4.",
                         cause="O GA4 recebe a compra com um transaction_id diferente do número do pedido (ou sem ID).",
                         todo="Enviar no purchase o mesmo ID do pedido da loja; é ele que liga cada venda à campanha."))
    elif has_store:
        out.append(check("ga4_match", "Pedidos da loja achados no GA4 pela transação", "na", None,
                         "Sem transações do GA4 guardadas no período (a sincronização por transação não rodou ou o GA4 não manda o ID)."))

    # 4: atribuição somada
    attributed = sums["meta_attributed_revenue"] + sums["google_ads_conversion_value"]
    if has_store and (days.get("meta_attributed_revenue") or days.get("google_ads_conversion_value")):
        r = _pct(attributed, revenue)
        st = "ok" if r is not None and r <= 100 else "warn" if r is not None and r <= 150 else "bad"
        out.append(check("overlap", "Atribuição de Meta + Google × receita da loja", st, r,
                         f"Meta {_fmt(sums['meta_attributed_revenue'], True)} + Google {_fmt(sums['google_ads_conversion_value'], True)} "
                         f"= {_fmt(attributed, True)}, para {_fmt(revenue, True)} vendidos na loja.",
                         cause="Cada plataforma reivindica a mesma venda (janelas de atribuição que se sobrepõem, view-through da Meta).",
                         todo="Usar a Origem das vendas (CRM) para decidir verba; tratar a receita das plataformas como sinal, não como faturamento."))

    # 5: compras atribuídas × pedidos da loja por canal pago
    channels = {c.get("channel"): c for c in store.get("channels") or []}
    for key, label, field, channel in (("meta_vs_store", "Compras da Meta × pedidos vindos de redes pagas", "meta_purchases", "paid_social"),
                                       ("google_vs_store", "Conversões do Google × pedidos vindos de busca paga", "google_ads_conversions", "paid_search")):
        if not has_store or not days.get(field):
            continue
        store_orders = int((channels.get(channel) or {}).get("orders") or 0)
        r = _pct(sums[field], store_orders) if store_orders else None
        st = "warn" if store_orders == 0 and sums[field] > 0 else band(r, (60, 150), (30, 250))
        out.append(check(key, label, st, r,
                         f"A plataforma diz {_fmt(sums[field])}; a loja registrou {_fmt(store_orders)} pedidos com origem nesse canal.",
                         cause=("Pedidos sem UTM caem em 'origem não identificada' e somem do canal; ou a plataforma conta "
                                "compras assistidas e de outros dispositivos."),
                         todo="Conferir as UTMs de todos os anúncios (utm_source e utm_medium) e a cobertura de origem abaixo."))

    # 6: origem identificada
    if has_store:
        r = store.get("origin_coverage_percent")
        out.append(check("origin", "Pedidos com origem identificada", band(r, (70, 100), (40, 100)), r,
                         f"{_fmt(store.get('orders_with_origin'))} de {_fmt(orders)} pedidos com UTM, referência ou GA4.",
                         cause="Anúncios ou links sem UTM, compras pelo app/WhatsApp sem rastreio.",
                         todo="Padronizar UTMs (Meta: parâmetros de URL no nível do anúncio; Google: auto-tagging + modelo de rastreamento)."))

    # 7: dias sem dado
    total_days = daily["period_days"]
    for field, label in COVERAGE.items():
        n = days.get(field, 0)
        if not n:
            continue
        missing = total_days - n
        out.append(check(f"coverage_{field}", f"Dias com dado: {label}", "ok" if missing <= 1 else "warn" if missing <= 5 else "bad",
                         float(n), f"{n} de {total_days} dias com dado.", unit="dias",
                         cause="Sincronização falhou ou não rodou nesses dias.",
                         todo="Ver a Saúde das integrações e reprocessar o período."))

    # 8: duplicidade
    if has_store:
        dups = dup.get("store", 0)
        out.append(check("duplicates", "Pedidos repetidos na loja", "ok" if not dups else "bad", float(dups),
                         "Nenhum pedido repetido." if not dups else f"{dups} pedido(s) gravado(s) mais de uma vez.",
                         unit="itens", cause="O mesmo pedido gravado duas vezes (reenvio de webhook ou reprocessamento).",
                         todo="Avisar a equipe técnica; a soma da loja pode estar inflada nesses pedidos."))
    return out


def duplicates(keys: List[str]) -> int:
    seen, dup = set(), 0
    for k in keys:
        if not k:
            continue
        if k in seen:
            dup += 1
        seen.add(k)
    return dup


async def _daily(client_id: str, start: str, end: str) -> Dict[str, Any]:
    rows = await sb_select("dashboard_daily_metrics", select="metric_date," + ",".join(DAILY_FIELDS + ("ga4_sessions",)),
                           filters={"client_id": f"eq.{client_id}", "and": f"(metric_date.gte.{start},metric_date.lte.{end})"},
                           order="metric_date.asc", limit=400)
    sums = {f: 0.0 for f in DAILY_FIELDS}
    days: Dict[str, int] = {}
    for r in rows:
        for f in DAILY_FIELDS + ("ga4_sessions",):
            if r.get(f) is not None:
                days[f] = days.get(f, 0) + 1
                if f in sums:
                    sums[f] += _num(r[f])
    period_days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    return {"sums": {k: round(v, 2) for k, v in sums.items()}, "days": days, "period_days": period_days}


async def reconcile(client_id: str, *, start: Optional[str] = None, end: Optional[str] = None) -> Dict[str, Any]:
    from . import sales_by_origin as sbo
    from .periods import resolve_period
    today = date.today()
    start = start or (today - timedelta(days=30)).isoformat()
    end = end or (today - timedelta(days=1)).isoformat()
    period = resolve_period(start=start, end=end)
    start, end = period.start.isoformat(), period.end.isoformat()

    store = await sbo.build_sales_by_origin(client_id, start=start, end=end)
    totals = store.get("totals") or {}
    store_view = {"provider": store.get("provider"), "status": store.get("status"), "orders": totals.get("orders"),
                  "revenue": totals.get("revenue"), "orders_with_origin": totals.get("orders_with_origin"),
                  "origin_coverage_percent": totals.get("origin_coverage_percent"), "channels": store.get("channels") or []}
    daily = await _daily(client_id, start, end)

    ga4_view: Dict[str, Any] = {"transactions": 0, "matched": 0}
    dup = {"store": 0}
    if store.get("provider") in (sbo.SHOPIFY, sbo.FBITS) and store.get("status") in ("available", "partial"):
        start_utc, end_utc = period.utc_bounds()
        loader = sbo._shopify_orders if store.get("provider") == sbo.SHOPIFY else sbo._fbits_orders
        orders, _ = await loader(client_id, start_utc.isoformat(), end_utc.isoformat())
        dup["store"] = duplicates([str(o.get("shopify_order_id") or o.get("order_id") or "") for o in orders])
        window = ((period.start - timedelta(days=2)).isoformat(), (period.end + timedelta(days=2)).isoformat())
        try:
            raw, _ = await sbo._paged("ga4_transaction_attribution", select="client_id,transaction_id,stat_date",
                                      filters={"client_id": f"eq.{client_id}", "and": f"(stat_date.gte.{window[0]},stat_date.lte.{window[1]})"},
                                      order="stat_date.asc,transaction_id.asc")
        except Exception as exc:  # noqa: BLE001 — tabela opcional
            print(f"[data_reconciliation] ga4_tx_unavailable client_id={client_id} {type(exc).__name__}")
            raw = []
        ids = [str(r.get("transaction_id") or "") for r in raw if r.get("client_id") == client_id]
        idset = set(ids)
        ga4_view = {"transactions": len(idset),
                    "matched": sum(1 for o in orders if any(k in idset for k in sbo._order_keys(o)))}

    checks = build_checks(store_view, daily, ga4_view, dup)
    return {"client_id": client_id, "period": {"start": start, "end": end}, "store": {k: v for k, v in store_view.items() if k != "channels"},
            "platforms": daily["sums"], "checks": checks,
            "summary": {s: sum(1 for c in checks if c["status"] == s) for s in ("ok", "warn", "bad", "na")}}
