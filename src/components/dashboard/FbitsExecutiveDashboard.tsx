import type {
  FbitsOrderRow,
  FbitsOrdersResponse,
  FbitsOrdersSummaryResponse,
  FbitsTrendPoint,
} from "../../app/types";
import { formatSelectedPeriodLabel } from "../../app/periodRange";
import {
  formatCalendarDate,
  formatCalendarDateWords,
  formatCurrency,
  formatCurrencyAxis,
  formatCurrencyShort,
  formatInteger,
  uniquePeak,
} from "../../app/dataFormat";
import DataNotice from "../data/DataNotice";
import Delta from "../data/Delta";
import HeroFigure from "../data/HeroFigure";
import KpiFigure from "../data/KpiFigure";
import TrendChart from "../data/TrendChart";

type Props = {
  data: FbitsOrdersSummaryResponse | null;
  orders?: FbitsOrdersResponse | null;
  loading: boolean;
  error: string | null;
  /** Conectado, mas a primeira importação ainda não terminou. */
  syncPending?: boolean;
  observeOrders?: (element: HTMLElement | null) => void;
  ordersError?: string | null;
};

const fmt = formatInteger;
const money = formatCurrency;

/** Pedidos têm data e hora: exibidos no fuso comercial. */
function shortDate(value: string | null | undefined) {
  const raw = String(value || "").trim();
  if (!raw) return "—";
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime())
    ? raw.slice(0, 10)
    : parsed.toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo" });
}

function orderClient(order: FbitsOrderRow) {
  // Só o identificador: "#" evita confundi-lo com o número do pedido.
  return order.cliente_nome || order.cliente_email || (order.cliente_id ? `#${order.cliente_id}` : "Cliente não identificado");
}

function orderStatus(order: FbitsOrderRow) {
  return order.situacao_pedido || (order.situacao_pedido_id ? `Status ${order.situacao_pedido_id}` : "Sem status");
}

type Granularity = "day" | "week" | "month";

const GRANULARITY_NOUN: Record<Granularity, string> = { day: "dia", week: "semana", month: "mês" };

function axisDate(value: string, granularity: Granularity) {
  return formatCalendarDate(value, granularity === "month" ? "month" : "day");
}

function bucketLabel(value: string, granularity: Granularity) {
  if (granularity === "week") return `semana de ${formatCalendarDate(value)}`;
  if (granularity === "month") return formatCalendarDate(value, "month");
  return formatCalendarDate(value, "long");
}

/**
 * Título do gráfico: acrescenta ao resumo (não repete a receita). Só aponta
 * o pico quando ele é objetivo — um único maior valor; senão, é descritivo.
 */
function trendTitle(peak: FbitsTrendPoint | null, granularity: Granularity) {
  if (!peak) return "Vendas ao longo do período";
  if (granularity === "week") return `A semana de ${formatCalendarDateWords(peak.date)} concentrou o maior volume de vendas`;
  if (granularity === "month") {
    const month = formatCalendarDateWords(peak.date, "month");
    return `${month.charAt(0).toUpperCase()}${month.slice(1)} concentrou o maior volume de vendas`;
  }
  return `${formatCalendarDateWords(peak.date)} concentrou o maior volume de vendas`;
}

export default function FbitsExecutiveDashboard({ data, orders, loading, error, syncPending = false, observeOrders, ordersError }: Props) {
  const summary = data?.summary;
  const connected = Boolean(data?.connected);
  const statuses = data?.status_distribution || [];
  const trend = data?.trend?.items || [];
  const granularity: Granularity = data?.trend?.granularity || "day";
  const products = orders?.top_products || [];
  const recentOrders = orders?.items?.slice(0, 10) || [];
  const cancelled = statuses
    .reduce((total, item) => total + (item.invalid_orders || (/cancel|inválid|invalid/i.test(item.status) ? item.pedidos : 0)), 0);
  const pending = statuses
    .reduce((total, item) => total + (!item.counts_as_revenue ? Math.max(0, item.pedidos - (item.invalid_orders || (/cancel|inválid|invalid/i.test(item.status) ? item.pedidos : 0))) : 0), 0);
  const periodLabel = data?.period ? formatSelectedPeriodLabel(data.period) : "Período selecionado";
  const previousLabel = data?.previous_period ? formatSelectedPeriodLabel(data.previous_period) : null;

  if (loading && !data) {
    return <p className="ds-status" role="status">Atualizando vendas do período...</p>;
  }
  if (error && !data) {
    return (
      <DataNotice tone="negative" role="alert" title="Vendas FBITS indisponíveis">
        Não foi possível consultar o período selecionado. {error}
      </DataNotice>
    );
  }
  if (!connected && !error) {
    return <DataNotice title="FBITS ainda não conectado">Conecte a plataforma para acompanhar as vendas.</DataNotice>;
  }
  if (!summary) return null;
  // Sem nada importado ainda, zeros e "não houve vendas" seriam falsos: a
  // página mostra o aviso de sincronização pendente.
  if (syncPending && summary.pedidos === 0) return null;

  const peak = uniquePeak(trend, (point) => point.revenue);
  const noun = GRANULARITY_NOUN[granularity];
  const hasComparison = [data?.comparison?.receita_oficial, data?.comparison?.pedidos, data?.comparison?.ticket_medio]
    .some((metric) => typeof metric?.change_percent === "number" && Number.isFinite(metric.change_percent));
  // KPIs executivos oficiais (FBITS) x analíticos derivados dos pedidos.
  const officialKpis = data?.kpi_source === "fbits_dashboard";
  const fallbackKpis = data?.kpi_source === "fbits_orders_fallback" && connected;
  const shownOrders = recentOrders.length;
  const totalOrders = Number(orders?.count || 0);

  return (
    <div className={`ds-stack${loading ? " ds-refreshing" : ""}`} aria-busy={loading}>
      {loading ? <p className="ds-status" role="status">Atualizando vendas do período...</p> : null}
      {error ? <DataNotice tone="negative" role="alert" title="Não foi possível atualizar">{error}</DataNotice> : null}
      {fallbackKpis ? (
        <DataNotice tone="warning" role="status" title="Indicadores oficiais da FBITS indisponíveis agora" testId="fbits-kpi-fallback">
          Receita, pedidos e ticket médio abaixo foram calculados a partir dos pedidos sincronizados e podem diferir do painel FBITS.
        </DataNotice>
      ) : null}

      {/* Uma história principal: quanto vendeu e se melhorou. Depois, o que
          a explica (pedidos, ticket, clientes) e o operacional, mais baixo. */}
      <section className="ds-summary" aria-label="Resumo do período">
        <HeroFigure
          value={formatCurrencyShort(summary.receita_oficial)}
          exactValue={money(summary.receita_oficial)}
          rawValue={summary.receita_oficial}
          label="vendidos no período"
          delta={<Delta change={data?.comparison?.receita_oficial?.change_percent} showReference />}
          testId="kpi-receita"
        />
        <div className="ds-kpis">
          <KpiFigure
            label="Pedidos"
            value={fmt(summary.pedidos)}
            rawValue={summary.pedidos}
            delta={<Delta change={data?.comparison?.pedidos?.change_percent} />}
            testId="kpi-pedidos"
          />
          <KpiFigure
            label="Ticket médio"
            value={formatCurrencyShort(summary.ticket_medio)}
            exactValue={money(summary.ticket_medio)}
            rawValue={summary.ticket_medio}
            delta={<Delta change={data?.comparison?.ticket_medio?.change_percent} />}
            testId="kpi-ticket"
          />
          <KpiFigure label="Clientes" value={fmt(summary.clientes)} rawValue={summary.clientes} testId="kpi-clientes" />
        </div>
        <div className="ds-secondary">
          <dl className="ds-inlineStats">
            <div><dt>Aguardando</dt><dd>{fmt(pending)}</dd></div>
            <div><dt>Cancelados / inválidos</dt><dd>{fmt(cancelled)}</dd></div>
            <div><dt>Descontos</dt><dd>{money(summary.descontos || 0)}</dd></div>
            <div><dt>Frete</dt><dd>{money(summary.frete || 0)}</dd></div>
          </dl>
          <p className="ds-footnote">
            {previousLabel
              ? hasComparison ? `Variações em relação a ${previousLabel}. ` : `Sem base de comparação em ${previousLabel}. `
              : null}
            {officialKpis
              ? "Receita, pedidos e ticket médio: indicadores oficiais da FBITS. Os demais números vêm dos pedidos sincronizados."
              : "Cancelados e inválidos não entram na receita."}
          </p>
        </div>
      </section>

      <section className="ds-section ds-chartSection" aria-labelledby="fbits-trend-title">
        <div className="ds-sectionHead">
          <div className="ds-sectionHeadText">
            <h2 id="fbits-trend-title" className="ds-sectionTitle">{trendTitle(peak, granularity)}</h2>
            {peak ? (
              <p className="ds-caption">
                {money(peak.revenue)} em {fmt(peak.orders)} {peak.orders === 1 ? "pedido" : "pedidos"}
              </p>
            ) : null}
          </div>
          {trend.length && summary.pedidos > 0 ? (
            <p className="ds-chartKey" aria-hidden="true">
              <span className="is-line">Receita</span>
              <span className="is-bar">Pedidos</span>
              <span>por {noun}</span>
            </p>
          ) : null}
        </div>
        {summary.pedidos === 0 ? <p className="ds-emptyLine">Não houve vendas neste período.</p> : trend.length ? (
          <TrendChart
            data={trend}
            xKey="date"
            primaryKey="revenue"
            secondaryKey="orders"
            formatX={(value) => axisDate(value, granularity)}
            formatY={formatCurrencyAxis}
            ariaLabel={`Receita e pedidos por ${noun}, ${periodLabel}.`}
            testId="fbits-sales-chart"
            renderTooltip={(point) => (
              <>
                <strong>{bucketLabel(point.date, granularity)}</strong>
                <dl>
                  <dt>Receita</dt><dd>{money(point.revenue)}</dd>
                  <dt>Pedidos</dt><dd>{fmt(point.orders)}</dd>
                  <dt>Ticket médio</dt><dd>{money(point.average_ticket)}</dd>
                </dl>
              </>
            )}
          />
        ) : summary.pedidos > 0 ? (
          <p className="ds-emptyLine">Sem vendas válidas para exibir no gráfico.</p>
        ) : null}
      </section>

      <div className="ds-split">
        <section className="ds-section" aria-labelledby="fbits-status-title">
          <h2 id="fbits-status-title" className="ds-sectionTitle">Status dos pedidos</h2>
          {statuses.length ? (
            <div className="ds-group">
              <ul className="ds-statusList">
                {statuses.map((item) => (
                  <li key={`${item.status_id || "-"}-${item.status}`} className="ds-statusRow">
                    <span className={`ds-statusDot${item.counts_as_revenue ? " is-revenue" : ""}`} aria-hidden="true" />
                    <span>
                      <span className="ds-statusName">{item.status}</span>
                      <span className="ds-statusCount">
                        {fmt(item.pedidos)} pedidos
                        <span className="ds-srOnly">{item.counts_as_revenue ? ", entra na receita" : ", fora da receita"}</span>
                      </span>
                    </span>
                    <span className="ds-statusValue">{money(item.valor)}</span>
                  </li>
                ))}
              </ul>
              <p className="ds-legend" aria-hidden="true">
                <span><span className="ds-statusDot is-revenue" />entra na receita</span>
                <span><span className="ds-statusDot" />fora da receita</span>
              </p>
            </div>
          ) : (
            <p className="ds-emptyLine">Sem status no período.</p>
          )}
        </section>

        <section className="ds-section" aria-labelledby="fbits-products-title">
          <h2 id="fbits-products-title" className="ds-sectionTitle">Produtos mais vendidos</h2>
          {products.length ? (
            <ol className="ds-rankList">
              {products.slice(0, 8).map((product) => {
                const share = summary.receita_oficial > 0 ? (product.receita / summary.receita_oficial) * 100 : 0;
                return (
                  <li key={product.product_id || product.sku || product.produto} className="ds-rankRow">
                    <span className="ds-rankName">{product.produto}</span>
                    <span className="ds-rankValue">{money(product.receita)}</span>
                    <span className="ds-rankMeta">{product.sku ? `SKU ${product.sku} · ` : ""}{fmt(product.quantidade)} un.</span>
                    <span className="ds-rankShare">{share.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%</span>
                    <span className="ds-rankBar" aria-hidden="true">
                      <span style={{ width: `${Math.min(100, Math.max(0, share))}%` }} />
                    </span>
                  </li>
                );
              })}
            </ol>
          ) : (
            <p className="ds-emptyLine">Sem produtos vendidos no período.</p>
          )}
        </section>
      </div>

      <section ref={observeOrders} className="ds-section" aria-labelledby="fbits-orders-title">
        <div className="ds-sectionHead">
          <h2 id="fbits-orders-title" className="ds-sectionTitle">Pedidos recentes</h2>
          {shownOrders && totalOrders > shownOrders ? (
            <p className="ds-caption">{fmt(shownOrders)} de {fmt(totalOrders)}</p>
          ) : null}
        </div>
        {ordersError ? <p role="alert">{ordersError}</p> : !orders && observeOrders ? <p role="status">Carregando detalhes dos pedidos...</p> : shownOrders ? (
          <div className="ds-tableWrap">
            <table className="ds-table">
              <thead>
                <tr>
                  <th scope="col">Pedido</th>
                  <th scope="col">Data</th>
                  <th scope="col">Cliente</th>
                  <th scope="col" className="is-number">Valor</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {recentOrders.map((order) => (
                  <tr key={order.pedido_id}>
                    <td className="is-primary">{order.pedido_codigo || order.pedido_id}</td>
                    <td>{shortDate(order.data)}</td>
                    <td>{orderClient(order)}</td>
                    <td className="is-number">{money(order.receita_oficial)}</td>
                    <td>{orderStatus(order)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="ds-emptyLine">Não há pedidos neste período.</p>
        )}
      </section>
    </div>
  );
}
