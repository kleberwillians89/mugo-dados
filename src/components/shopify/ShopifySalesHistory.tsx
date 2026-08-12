import { useMemo, useState } from "react";
import type { DashboardDailyMetric } from "../../app/DashboardDataContext";
import { aggregateShopifyHistory, type ShopifyHistoryGranularity } from "../../app/shopifyHistory";
import { formatShopifyCompactNumber, formatShopifyCurrency } from "../../app/shopifyUi";

export default function ShopifySalesHistory({ rows, coverageStart, coverageEnd }: { rows: DashboardDailyMetric[]; coverageStart: string | null; coverageEnd: string | null }) {
  const [granularity, setGranularity] = useState<ShopifyHistoryGranularity>("month");
  const [metric, setMetric] = useState<"revenue" | "orders" | "ticket">("revenue");
  const points = useMemo(() => aggregateShopifyHistory(rows, granularity, coverageStart, coverageEnd), [coverageEnd, coverageStart, granularity, rows]);
  const max = Math.max(1, ...points.map((point) => point[metric]));
  const value = (point: (typeof points)[number]) => metric === "orders" ? formatShopifyCompactNumber(point.orders) : formatShopifyCurrency(point[metric]);
  const change = (amount: number | null) => amount == null ? "—" : `${amount > 0 ? "+" : ""}${amount.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
  return <section className="shopifySection shopifyHistory" aria-labelledby="shopify-history-title">
    <div className="shopifyChartHead"><div><span className="shopifyMiniLabel">Histórico comercial</span><h2 id="shopify-history-title">Evolução das vendas</h2><p className="shopifyChartDescription">Receita real, pedidos e ticket médio da Shopify dentro da cobertura disponível.</p></div>
      <div className="shopifyChartTabs" role="tablist" aria-label="Granularidade histórica">{(["day", "week", "month"] as const).map((item) => <button key={item} className={`shopifyChartTab${granularity === item ? " is-active" : ""}`} onClick={() => setGranularity(item)} role="tab" aria-selected={granularity === item}>{item === "day" ? "Dia" : item === "week" ? "Semana" : "Mês"}</button>)}</div></div>
    <div className="shopifyHistoryMetricTabs">{(["revenue", "orders", "ticket"] as const).map((item) => <button key={item} className={metric === item ? "is-active" : ""} onClick={() => setMetric(item)}>{item === "revenue" ? "Receita" : item === "orders" ? "Pedidos" : "Ticket médio"}</button>)}</div>
    {!points.length ? <p className="shopifyFeedbackCard">Sem cobertura Shopify disponível para o histórico.</p> : <>
      <p className="shopifyHistoryCoverage">Histórico disponível de {coverageStart} a {coverageEnd}. Períodos incompletos são identificados como parciais.</p>
      <div className="shopifyHistoryChart">{points.map((point) => <div className="shopifyHistoryBar" key={point.key} title={`${point.label}: ${value(point)}`}><span style={{ height: `${Math.max(3, point[metric] / max * 100)}%` }} /><small>{point.label}{point.isPartial ? " · parcial" : ""}</small></div>)}</div>
      <div className="shopifyHistoryTableWrap"><table className="shopifyHistoryTable"><thead><tr><th>Período</th><th>Receita</th><th>Pedidos</th><th>Ticket médio</th><th>Var. receita</th><th>Var. pedidos</th></tr></thead><tbody>{points.slice().reverse().map((point) => <tr key={point.key}><td>{point.label}{point.isPartial ? <small>Parcial</small> : null}</td><td>{formatShopifyCurrency(point.revenue)}</td><td>{formatShopifyCompactNumber(point.orders)}</td><td>{formatShopifyCurrency(point.ticket)}</td><td>{change(point.revenueVariation)}</td><td>{change(point.ordersVariation)}</td></tr>)}</tbody></table></div>
    </>}
  </section>;
}
