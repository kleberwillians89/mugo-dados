import { useEffect, useState } from "react";
import { getActiveClientId } from "../app/activeClient";
import { usePeriod } from "../app/PeriodContext";
import { formatCurrency, formatInteger, formatPercentNumber } from "../app/dataFormat";
import { getSalesByOrigin, type SalesByOrigin } from "../app/salesByOrigin";
import useSectionDemand from "../hooks/useSectionDemand";
import "../styles/salesOrigin.css";

const PROVIDER_LABELS: Record<string, string> = { shopify: "Shopify", fbits: "FBITS/Wake" };

/** Receita da loja por origem do pedido (UTM / referência / canal da loja). */
export default function SalesByOriginPanel() {
  const { period } = usePeriod();
  const clientId = getActiveClientId();
  const scope = `${clientId}:${period.start}:${period.end}`;
  const { observe, enabled } = useSectionDemand(scope, Boolean(clientId));
  const [state, setState] = useState<{ scope: string; data: SalesByOrigin | null; error: boolean }>({ scope: "", data: null, error: false });

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    getSalesByOrigin(period.start, period.end)
      .then((data) => { if (alive && getActiveClientId() === clientId) setState({ scope, data, error: false }); })
      .catch(() => { if (alive) setState({ scope, data: null, error: true }); });
    return () => { alive = false; };
  }, [clientId, enabled, period.end, period.start, scope]);

  const current = state.scope === scope ? state : { data: null, error: false };
  const data = current.data;
  if (data?.status === "not_connected") return null;
  const totals = data?.totals;

  return (
    <section ref={observe} className="salesOrigin ds-page" aria-label="Vendas por origem" data-testid="sales-by-origin">
      <header>
        <h2>Vendas por origem</h2>
        <p>De onde vieram os pedidos da loja{data?.provider ? ` (${PROVIDER_LABELS[data.provider] || data.provider})` : ""}. Modelo: {data?.attribution_model_label || "último clique com UTM registrado pela loja"}.</p>
      </header>
      {current.error ? <p role="status">Vendas por origem indisponíveis no momento.</p> : null}
      {!data && !current.error ? <p>{enabled ? "Carregando…" : "Carregado ao visualizar esta seção."}</p> : null}
      {data?.status === "migration_pending" ? <p role="status">A origem dos pedidos ainda está sendo ativada para esta empresa.</p> : null}
      {totals ? (
        <>
          <dl className="salesOriginCoverage">
            <div><dt>Pedidos no período</dt><dd>{formatInteger(totals.orders)}</dd></div>
            <div><dt>Receita da loja</dt><dd>{formatCurrency(totals.revenue)}</dd></div>
            <div><dt>Pedidos com origem identificada</dt><dd>{totals.origin_coverage_percent == null ? "—" : `${formatPercentNumber(totals.origin_coverage_percent)}%`}</dd></div>
            <div><dt>Pedidos com UTM de campanha</dt><dd>{totals.utm_coverage_percent == null ? "—" : `${formatPercentNumber(totals.utm_coverage_percent)}%`}</dd></div>
          </dl>
          {data!.channels.length ? (
            <table className="salesOriginTable">
              <caption>Por canal</caption>
              <thead><tr><th scope="col">Canal</th><th scope="col">Pedidos</th><th scope="col">Receita</th><th scope="col">Ticket médio</th><th scope="col">% da receita</th></tr></thead>
              <tbody>{data!.channels.map((row) => (
                <tr key={row.channel} className={row.channel === "unknown" ? "is-unknown" : undefined}>
                  <th scope="row">{row.label}</th><td>{formatInteger(row.orders)}</td><td>{formatCurrency(row.revenue)}</td>
                  <td>{row.average_ticket == null ? "—" : formatCurrency(row.average_ticket)}</td>
                  <td>{row.share_of_revenue == null ? "—" : `${formatPercentNumber(row.share_of_revenue)}%`}</td>
                </tr>))}</tbody>
            </table>
          ) : <p>Nenhum pedido no período.</p>}
          {data!.campaigns.length ? (
            <table className="salesOriginTable">
              <caption>Por campanha (utm_campaign)</caption>
              <thead><tr><th scope="col">Campanha</th><th scope="col">Origem / mídia</th><th scope="col">Pedidos</th><th scope="col">Receita</th><th scope="col">Ticket médio</th></tr></thead>
              <tbody>{data!.campaigns.slice(0, 15).map((row, index) => (
                <tr key={`${row.campaign}-${row.source}-${row.medium}-${index}`}>
                  <th scope="row">{row.campaign}</th><td>{[row.source, row.medium].filter(Boolean).join(" / ") || row.channel_label}</td>
                  <td>{formatInteger(row.orders)}</td><td>{formatCurrency(row.revenue)}</td>
                  <td>{row.average_ticket == null ? "—" : formatCurrency(row.average_ticket)}</td>
                </tr>))}</tbody>
            </table>
          ) : null}
          {data!.truncated ? <p role="status">Período com muitos pedidos: mostrando os primeiros 20 mil.</p> : null}
          {data!.notes?.length ? <ul className="salesOriginNotes">{data!.notes.map((note) => <li key={note}>{note}</li>)}</ul> : null}
        </>
      ) : null}
    </section>
  );
}
