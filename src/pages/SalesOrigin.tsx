import { useEffect, useState } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { usePeriod } from "../app/PeriodContext";
import { formatCurrency, formatInteger, formatPercentNumber } from "../app/dataFormat";
import { getSalesByOrigin, type SalesByOrigin } from "../app/salesByOrigin";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import PeriodSelector from "../components/data/PeriodSelector";
import KpiFigure from "../components/data/KpiFigure";
import DataNotice from "../components/data/DataNotice";
import "../styles/salesOrigin.css";

const PROVIDER_LABELS: Record<string, string> = { shopify: "Shopify", fbits: "FBITS/Wake" };

/** Abaixo disso, a leitura por campanha é parcial e precisa ser dita. */
const LOW_UTM_COVERAGE = 50;

type State = { scope: string; data: SalesByOrigin | null; error: boolean };

function percent(value: number | null | undefined) {
  return value == null ? "—" : `${formatPercentNumber(value)}%`;
}

/**
 * De onde vieram as vendas da loja da empresa ativa: canal e campanha (UTM)
 * de cada pedido. Sempre escopada pela empresa ativa — o backend revalida o
 * acesso (`require_client_read`) e só devolve pedidos daquele `client_id`.
 */
export default function SalesOrigin() {
  const { period } = usePeriod();
  const clientId = getActiveClientId();
  const scope = `${clientId}:${period.start}:${period.end}`;
  const [state, setState] = useState<State>({ scope: "", data: null, error: false });

  useEffect(() => {
    if (!clientId) return;
    let alive = true;
    getSalesByOrigin(period.start, period.end)
      .then((data) => { if (alive && getActiveClientId() === clientId) setState({ scope, data, error: false }); })
      .catch(() => { if (alive) setState({ scope, data: null, error: true }); });
    return () => { alive = false; };
  }, [clientId, period.end, period.start, scope]);

  const current = state.scope === scope ? state : { data: null, error: false };
  const data = current.data;
  const totals = data?.totals;
  const loading = !data && !current.error;
  const maxShare = Math.max(1, ...(data?.channels || []).map((row) => row.share_of_revenue || 0));

  return (
    <Shell title="Origem das vendas" variant="editorial">
      <div className="ds-page salesOriginPage" data-testid="sales-origin-page">
        <PageHeader
          company={getActiveClientName()}
          title="Origem das vendas"
          dateline={
            <span>
              {data?.provider ? `Pedidos da loja (${PROVIDER_LABELS[data.provider] || data.provider}) · ` : ""}
              Modelo: {data?.attribution_model_label || "último clique com UTM registrado pela loja"}
            </span>
          }
          controls={<PeriodSelector />}
        />

        {current.error ? (
          <DataNotice tone="negative" role="alert" title="Origem das vendas indisponível no momento.">
            Tente de novo em instantes.
          </DataNotice>
        ) : null}
        {loading ? <p className="salesOriginLoading" role="status">Carregando a origem dos pedidos…</p> : null}
        {data?.status === "not_connected" ? (
          <DataNotice title="Nenhuma loja conectada a esta empresa.">
            Conecte a Shopify ou a FBITS/Wake em Integrações para ver de onde vêm os pedidos.
          </DataNotice>
        ) : null}
        {data?.status === "migration_pending" ? (
          <DataNotice tone="warning" role="status" title="A origem dos pedidos ainda está sendo ativada para esta empresa." />
        ) : null}

        {totals ? (
          <>
            <section className="ds-kpis salesOriginKpis" aria-label="Resumo do período">
              <KpiFigure label="Receita da loja" value={formatCurrency(totals.revenue)} rawValue={totals.revenue} />
              <KpiFigure label="Pedidos" value={formatInteger(totals.orders)} rawValue={totals.orders} />
              <KpiFigure label="Pedidos com origem identificada" value={percent(totals.origin_coverage_percent)} />
              <KpiFigure label="Pedidos com campanha (UTM)" value={percent(totals.utm_coverage_percent)} />
            </section>

            {totals.orders > 0 && (totals.utm_coverage_percent ?? 0) < LOW_UTM_COVERAGE ? (
              <DataNotice tone="warning" title="Leitura por campanha ainda parcial.">
                Só {percent(totals.utm_coverage_percent)} dos pedidos do período trazem a campanha registrada pela loja.
                Pedidos sem origem aparecem como “Origem não identificada” e nunca são distribuídos entre campanhas.
              </DataNotice>
            ) : null}

            <section className="salesOriginSection" aria-labelledby="sales-origin-channels">
              <h2 id="sales-origin-channels">Por canal</h2>
              {data!.channels.length ? (
                <ol className="salesOriginBars">
                  {data!.channels.map((row) => (
                    <li key={row.channel} className={row.channel === "unknown" ? "is-unknown" : undefined}>
                      <div className="salesOriginBarHead">
                        <span className="salesOriginBarLabel">{row.label}</span>
                        <strong>{formatCurrency(row.revenue)}</strong>
                      </div>
                      <div className="salesOriginBarTrack" aria-hidden="true">
                        <span style={{ width: `${Math.max(2, ((row.share_of_revenue || 0) / maxShare) * 100)}%` }} />
                      </div>
                      <p className="salesOriginBarMeta">
                        {percent(row.share_of_revenue)} da receita · {formatInteger(row.orders)} pedidos · ticket{" "}
                        {row.average_ticket == null ? "—" : formatCurrency(row.average_ticket)}
                      </p>
                    </li>
                  ))}
                </ol>
              ) : <p className="salesOriginEmpty">Nenhum pedido no período.</p>}
            </section>

            <section className="salesOriginSection" aria-labelledby="sales-origin-campaigns">
              <h2 id="sales-origin-campaigns">Por campanha</h2>
              {data!.campaigns.length ? (
                <div className="salesOriginTableWrap">
                  <table className="salesOriginTable">
                    <thead><tr><th scope="col">Campanha</th><th scope="col">Origem / mídia</th><th scope="col">Pedidos</th><th scope="col">Receita</th><th scope="col">Ticket médio</th></tr></thead>
                    <tbody>{data!.campaigns.slice(0, 25).map((row, index) => (
                      <tr key={`${row.campaign}-${row.source}-${row.medium}-${index}`}>
                        <th scope="row">{row.campaign}</th>
                        <td>{[row.source, row.medium].filter(Boolean).join(" / ") || row.channel_label}</td>
                        <td>{formatInteger(row.orders)}</td>
                        <td>{formatCurrency(row.revenue)}</td>
                        <td>{row.average_ticket == null ? "—" : formatCurrency(row.average_ticket)}</td>
                      </tr>))}</tbody>
                  </table>
                </div>
              ) : <p className="salesOriginEmpty">Nenhum pedido com campanha (UTM) registrada no período.</p>}
            </section>

            {data!.truncated ? <p role="status" className="salesOriginNote">Período com muitos pedidos: mostrando os primeiros 20 mil.</p> : null}
            {data!.notes?.length ? <ul className="salesOriginNotes">{data!.notes.map((note) => <li key={note}>{note}</li>)}</ul> : null}
          </>
        ) : null}
      </div>
    </Shell>
  );
}
