import { useMemo, useState } from "react";
import type { DashboardDailyMetric } from "../../app/DashboardDataContext";
import { formatCalendarDate } from "../../app/dataFormat";
import { aggregateShopifyHistory, type ShopifyHistoryGranularity } from "../../app/shopifyHistory";
import { formatShopifyCompactNumber, formatShopifyCurrency } from "../../app/shopifyUi";
import SegmentedControl from "../data/SegmentedControl";

type HistoryMetric = "revenue" | "orders" | "ticket";

const METRIC_OPTIONS: Array<{ id: HistoryMetric; label: string }> = [
  { id: "revenue", label: "Receita" },
  { id: "orders", label: "Pedidos" },
  { id: "ticket", label: "Ticket médio" },
];

const GRANULARITY_OPTIONS: Array<{ id: ShopifyHistoryGranularity; label: string }> = [
  { id: "day", label: "Dia" },
  { id: "week", label: "Semana" },
  { id: "month", label: "Mês" },
];

export default function ShopifySalesHistory({ rows, coverageStart, coverageEnd }: { rows: DashboardDailyMetric[]; coverageStart: string | null; coverageEnd: string | null }) {
  const [granularity, setGranularity] = useState<ShopifyHistoryGranularity>("month");
  const [metric, setMetric] = useState<HistoryMetric>("revenue");
  const points = useMemo(() => aggregateShopifyHistory(rows, granularity, coverageStart, coverageEnd), [coverageEnd, coverageStart, granularity, rows]);
  const max = Math.max(1, ...points.map((point) => point[metric]));
  const value = (point: (typeof points)[number]) => metric === "orders" ? formatShopifyCompactNumber(point.orders) : formatShopifyCurrency(point[metric]);
  const change = (amount: number | null) => amount == null ? "—" : `${amount > 0 ? "+" : ""}${amount.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
  // Rótulos sob as barras: no máximo ~12, para não virar ruído.
  const labelEvery = Math.max(1, Math.ceil(points.length / 12));
  const metricLabel = METRIC_OPTIONS.find((option) => option.id === metric)?.label || "Receita";

  return (
    <section className="ds-section shopifyHistory" aria-labelledby="shopify-history-title">
      <div className="ds-sectionHead">
        <div className="ds-sectionHeadText">
          <h2 id="shopify-history-title" className="ds-sectionTitle">Histórico de vendas</h2>
          {points.length && coverageStart && coverageEnd ? (
            <p className="ds-caption">
              Cobertura de {formatCalendarDate(coverageStart, "long")} a {formatCalendarDate(coverageEnd, "long")}. Períodos incompletos aparecem como parciais.
            </p>
          ) : null}
        </div>
        <div className="shopifyHistoryControls">
          <SegmentedControl ariaLabel="Métrica do histórico" value={metric} onSelect={(id) => setMetric(id as HistoryMetric)} options={METRIC_OPTIONS} />
          <SegmentedControl ariaLabel="Granularidade do histórico" value={granularity} onSelect={(id) => setGranularity(id as ShopifyHistoryGranularity)} options={GRANULARITY_OPTIONS} />
        </div>
      </div>
      {!points.length ? <p className="ds-emptyLine">Sem cobertura Shopify disponível para o histórico.</p> : <>
        <div className="ds-historyBars" role="img" aria-label={`${metricLabel} por período, dentro da cobertura disponível.`}>
          {points.map((point, index) => (
            <div className={`ds-historyBar${point.isPartial ? " is-partial" : ""}`} key={point.key} title={`${point.label}: ${value(point)}${point.isPartial ? " (parcial)" : ""}`}>
              <span style={{ height: `${Math.max(2, (point[metric] / max) * 100)}%` }} />
              {index % labelEvery === 0 ? <small>{point.label}</small> : null}
            </div>
          ))}
        </div>
        <div className="ds-tableWrap">
          <table className="ds-table">
            <thead>
              <tr>
                <th scope="col">Período</th>
                <th scope="col" className="is-number">Receita</th>
                <th scope="col" className="is-number">Pedidos</th>
                <th scope="col" className="is-number">Ticket médio</th>
                <th scope="col" className="is-number">Var. receita</th>
                <th scope="col" className="is-number">Var. pedidos</th>
              </tr>
            </thead>
            <tbody>
              {points.slice().reverse().map((point) => (
                <tr key={point.key}>
                  <td className="is-primary">{point.label}{point.isPartial ? <span className="ds-tableSub">Parcial</span> : null}</td>
                  <td className="is-number">{formatShopifyCurrency(point.revenue)}</td>
                  <td className="is-number">{formatShopifyCompactNumber(point.orders)}</td>
                  <td className="is-number">{formatShopifyCurrency(point.ticket)}</td>
                  <td className="is-number">{change(point.revenueVariation)}</td>
                  <td className="is-number">{change(point.ordersVariation)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </>}
    </section>
  );
}
