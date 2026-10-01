import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type {
  FbitsMetricComparison,
  FbitsOrderRow,
  FbitsOrdersResponse,
  FbitsOrdersSummaryResponse,
} from "../../app/types";
import { formatSelectedPeriodLabel } from "../../app/periodRange";
import MetaStateNotice from "./MetaStateNotice";

type Props = {
  data: FbitsOrdersSummaryResponse | null;
  orders?: FbitsOrdersResponse | null;
  loading: boolean;
  error: string | null;
};

const numberFormatter = new Intl.NumberFormat("pt-BR");
const currencyFormatter = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
  maximumFractionDigits: 2,
});

function fmt(value: number) {
  return numberFormatter.format(Number(value || 0));
}

function money(value: number) {
  return currencyFormatter.format(Number(value || 0));
}

function shortDate(value: string | null | undefined) {
  const raw = String(value || "").trim();
  if (!raw) return "—";
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime())
    ? raw.slice(0, 10)
    : parsed.toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo" });
}

function delta(metric: FbitsMetricComparison | undefined) {
  const change = metric?.change_percent;
  if (change === null || typeof change === "undefined") return <span className="fbitsDelta isNeutral">— vs. período anterior</span>;
  const tone = change > 0 ? "isPositive" : change < 0 ? "isNegative" : "isNeutral";
  return <span className={`fbitsDelta ${tone}`}>{change > 0 ? "↑" : change < 0 ? "↓" : "→"} {Math.abs(change).toLocaleString("pt-BR")}% vs. período anterior</span>;
}

function orderClient(order: FbitsOrderRow) {
  return order.cliente_nome || order.cliente_email || order.cliente_id || "Cliente não identificado";
}

function orderStatus(order: FbitsOrderRow) {
  return order.situacao_pedido || (order.situacao_pedido_id ? `Status ${order.situacao_pedido_id}` : "Sem status");
}

function chartGranularity(value: string | undefined) {
  if (value === "week") return "semanal";
  if (value === "month") return "mensal";
  return "diária";
}

export default function FbitsExecutiveDashboard({ data, orders, loading, error }: Props) {
  const summary = data?.summary;
  const connected = Boolean(data?.connected);
  const statuses = data?.status_distribution || [];
  const trend = data?.trend?.items || [];
  const products = orders?.top_products || [];
  const recentOrders = orders?.items?.slice(0, 10) || [];
  const cancelled = statuses
    .reduce((total, item) => total + (item.invalid_orders || (/cancel|inválid|invalid/i.test(item.status) ? item.pedidos : 0)), 0);
  const pending = statuses
    .reduce((total, item) => total + (!item.counts_as_revenue ? Math.max(0, item.pedidos - (item.invalid_orders || (/cancel|inválid|invalid/i.test(item.status) ? item.pedidos : 0))) : 0), 0);
  const periodLabel = data?.period ? formatSelectedPeriodLabel(data.period) : "Período selecionado";

  if (loading && !data) {
    return <section className="fbitsExecutiveDashboard"><div className="fbitsExecutiveLoading" role="status">Atualizando vendas do período...</div></section>;
  }
  if (error && !data) {
    return <MetaStateNotice title="Vendas FBITS indisponíveis" description="Não foi possível consultar o período selecionado." message={error} tone="unavailable" />;
  }
  if (!connected && !error) {
    return <MetaStateNotice title="FBITS ainda não conectado" description="Conecte a plataforma para acompanhar as vendas." message="FBITS ainda não conectado." tone="empty" />;
  }

  return (
    <section className={`fbitsExecutiveDashboard${loading ? " isRefreshing" : ""}`} aria-busy={loading}>
      <div className="fbitsDashboardTitle">
        <div><div className="h1">Desempenho comercial</div><div className="p">Pedidos pela data comercial em {periodLabel}.</div></div>
        {loading ? <span className="pill">Atualizando...</span> : null}
      </div>

      {error ? <div className="pill pillDanger" role="alert">{error}</div> : null}

      {summary ? (
        <>
          <div className="fbitsKpiGrid">
            <article className="fbitsKpi isPrimary"><span>Faturamento</span><strong>{money(summary.receita_oficial)}</strong>{delta(data?.comparison?.receita_oficial)}</article>
            <article className="fbitsKpi"><span>Pedidos</span><strong>{fmt(summary.pedidos)}</strong>{delta(data?.comparison?.pedidos)}</article>
            <article className="fbitsKpi"><span>Ticket médio</span><strong>{money(summary.ticket_medio)}</strong>{delta(data?.comparison?.ticket_medio)}</article>
            <article className="fbitsKpi"><span>Clientes</span><strong>{fmt(summary.clientes)}</strong><small>Clientes identificados</small></article>
          </div>

          <div className="fbitsSecondaryMetrics">
            <span><small>Pedidos válidos</small><strong>{fmt(summary.pedidos)}</strong></span>
            <span><small>Aguardando</small><strong>{fmt(pending)}</strong></span>
            <span><small>Cancelados / inválidos</small><strong>{fmt(cancelled)}</strong></span>
            <span><small>Descontos</small><strong>{money(summary.descontos || 0)}</strong></span>
            <span><small>Frete</small><strong>{money(summary.frete || 0)}</strong></span>
          </div>

          {summary.pedidos === 0 ? <div className="fbitsNoSales">Não houve vendas neste período.</div> : null}

          <article className="fbitsDashboardCard fbitsSalesChartCard">
            <header><div><h2>Vendas ao longo do período</h2><p>Granularidade {chartGranularity(data?.trend?.granularity)} · cancelados não entram no faturamento.</p></div></header>
            {trend.length ? (
              <div className="fbitsChartViewport" data-testid="fbits-sales-chart">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={trend} margin={{ top: 12, right: 12, left: 6, bottom: 0 }}>
                    <CartesianGrid vertical={false} stroke="rgba(91,31,42,.08)" strokeDasharray="4 4" />
                    <XAxis dataKey="date" tickFormatter={shortDate} tick={{ fontSize: 11, fill: "rgba(26,23,24,.55)" }} axisLine={false} tickLine={false} minTickGap={30} />
                    <YAxis yAxisId="revenue" tickFormatter={(value) => `R$ ${numberFormatter.format(Number(value))}`} tick={{ fontSize: 11, fill: "rgba(26,23,24,.5)" }} axisLine={false} tickLine={false} width={78} />
                    <YAxis yAxisId="orders" orientation="right" allowDecimals={false} tick={{ fontSize: 11, fill: "rgba(26,23,24,.5)" }} axisLine={false} tickLine={false} width={36} />
                    <Tooltip content={({ active, payload, label }) => active && payload?.length ? (
                      <div className="fbitsChartTooltip">
                        <strong>{shortDate(String(label))}</strong>
                        <span>Faturamento <b>{money(Number(payload[0]?.payload?.revenue || 0))}</b></span>
                        <span>Pedidos <b>{fmt(Number(payload[0]?.payload?.orders || 0))}</b></span>
                        <span>Ticket médio <b>{money(Number(payload[0]?.payload?.average_ticket || 0))}</b></span>
                      </div>
                    ) : null} />
                    <Bar yAxisId="orders" dataKey="orders" name="Pedidos" fill="rgba(197,151,91,.38)" radius={[5, 5, 0, 0]} />
                    <Line yAxisId="revenue" dataKey="revenue" name="Faturamento" stroke="#5b1f2a" strokeWidth={3} dot={false} activeDot={{ r: 4 }} type="monotone" />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            ) : <div className="fbitsCardEmpty">Sem vendas válidas para exibir no gráfico.</div>}
          </article>

          <div className="fbitsInsightsGrid">
            <article className="fbitsDashboardCard">
              <header><div><h2>Status dos pedidos</h2><p>Quantidade e valor bruto por estado real da FBITS.</p></div></header>
              {statuses.length ? <div className="fbitsStatusList">{statuses.map((item) => (
                <div key={`${item.status_id || "-"}-${item.status}`}><span className={item.counts_as_revenue ? "isValid" : ""} /><p><strong>{item.status}</strong><small>{fmt(item.pedidos)} pedidos</small></p><b>{money(item.valor)}</b></div>
              ))}</div> : <div className="fbitsCardEmpty">Sem status no período.</div>}
            </article>

            <article className="fbitsDashboardCard">
              <header><div><h2>Produtos mais vendidos</h2><p>Ranking dos pedidos válidos.</p></div></header>
              {products.length ? <div className="fbitsProductRanking">{products.slice(0, 8).map((product) => {
                const share = summary.receita_oficial > 0 ? (product.receita / summary.receita_oficial) * 100 : 0;
                return <div key={product.product_id || product.sku || product.produto}><p><strong>{product.produto}</strong><small>{product.sku ? `SKU ${product.sku} · ` : ""}{fmt(product.quantidade)} un.</small></p><span><b>{money(product.receita)}</b><small>{share.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%</small></span></div>;
              })}</div> : <div className="fbitsCardEmpty">Sem produtos vendidos no período.</div>}
            </article>
          </div>

          <article className="fbitsDashboardCard">
            <header><div><h2>Pedidos recentes</h2><p>Últimos pedidos do período selecionado.</p></div></header>
            {recentOrders.length ? <div className="tableWrap fbitsRecentOrders"><table className="table"><thead><tr><th>Pedido</th><th>Data</th><th>Cliente</th><th>Valor</th><th>Status</th></tr></thead><tbody>{recentOrders.map((order) => (
              <tr key={order.pedido_id}><td>{order.pedido_codigo || order.pedido_id}</td><td>{shortDate(order.data)}</td><td>{orderClient(order)}</td><td>{money(order.receita_oficial)}</td><td><span className="fbitsOrderStatus">{orderStatus(order)}</span></td></tr>
            ))}</tbody></table></div> : <div className="fbitsCardEmpty">Não há pedidos neste período.</div>}
          </article>
        </>
      ) : null}
    </section>
  );
}
