"""Relatório enviado em texto livre quando o cliente responde ao convite de sexta.

A resposta do cliente abre a janela de 24h do WhatsApp, então este texto não é template.
Regras:
- dados só da empresa associada à conversa (client_id vem do convite, nunca do telefone);
- faturamento total da loja separado da receita atribuída às campanhas (pedidos com origem paga);
- faturamento total ÷ investimento aparece como indicador geral, nunca como ROAS atribuído;
- sem dado válido, nada é montado (StudioError), nunca um número inventado.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from .ig_supabase import sb_select
from .studio_calendar import StudioError
from .studio_messages import SAO_PAULO, _snapshot, _store_sales, _value, brl, first_name


async def first_data_day(client_id: str) -> Optional[date]:
    rows = await sb_select("dashboard_daily_metrics", select="client_id,metric_date", filters={"client_id": f"eq.{client_id}"},
                           order="metric_date.asc", limit=1)
    if not rows or rows[0].get("client_id") != client_id or not rows[0].get("metric_date"):
        return None
    return date.fromisoformat(str(rows[0]["metric_date"])[:10])


async def period_for(client_id: str, *, full: bool) -> Tuple[date, date]:
    end = datetime.now(SAO_PAULO).date() - timedelta(days=1)
    if not full:
        return end - timedelta(days=6), end
    start = await first_data_day(client_id)
    if not start or start > end:
        raise StudioError("NO_HISTORY")
    return start, end


def compose(*, name: str, brand: str, start: date, end: date, spend: float, sales: Dict[str, Any], full: bool) -> str:
    label = "todo o histórico disponível" if full else "a semana"
    lines = [f"Olá, {name}! Aqui está o resumo da {brand} ({label}: {start.strftime('%d/%m/%Y')} a {end.strftime('%d/%m/%Y')}).", ""]
    lines.append(f"Investimento em mídia: {brl(spend)}")
    orders = f" em {int(sales['orders'])} pedido(s)" if sales.get("orders") else ""
    lines.append(f"Faturamento total da loja: {brl(sales['revenue'])}{orders}")
    if sales.get("paid_revenue") is not None:
        paid_orders = f" em {sales['paid_orders']} pedido(s)" if sales.get("paid_orders") else ""
        lines.append(f"Receita atribuída às campanhas (pedidos com origem em mídia paga): {brl(sales['paid_revenue'])}{paid_orders}")
    else:
        lines.append("Receita atribuída às campanhas: a origem dos pedidos não foi identificada neste período.")
    ratio = sales["revenue"] / spend
    lines.append(f"Faturamento total para cada R$ 1 investido: {brl(ratio)} (indicador geral da loja, não é o ROAS atribuído às campanhas)")
    top = sales.get("top_campaign")
    if top:
        lines.append(f"Campanha com mais vendas atribuídas: {top['campanha']}, {top['pedidos']} pedido(s) e {brl(top['vendas'])}")
    lines += ["", "Os detalhes estão no Mugoverso. Qualquer dúvida, é só responder esta mensagem."]
    return "\n".join(lines)


async def report_text(client_id: str, contact: Dict[str, Any], *, full: bool) -> str:
    from .studio_approvals import _client_name

    start, end = await period_for(client_id, full=full)
    snap = await _snapshot(client_id, start, end)
    spend = _value(snap["metrics"], "investment")
    if not spend:
        raise StudioError("NO_PAID_DATA")
    sales = await _store_sales(client_id, start, end, snap["metrics"])
    if sales.get("revenue") is None:
        raise StudioError("NO_STORE_DATA")
    return compose(name=first_name(contact.get("name")), brand=await _client_name(client_id), start=start, end=end,
                   spend=spend, sales=sales, full=full)
