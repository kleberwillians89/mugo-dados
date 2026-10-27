import type { Ga4Acquisition } from "../../app/types";
import { formatCurrency, formatInteger } from "../../app/dataFormat";
import DataNotice from "../data/DataNotice";

type Props = {
  acquisition?: Ga4Acquisition | null;
};

/** Compras e receita atribuídas pelo GA4 por canal de aquisição (todas as empresas com GA4). */
export default function Ga4CampaignPurchases({ acquisition }: Props) {
  const groups = acquisition?.channel_groups || [];
  const notes = acquisition?.notes || [];
  if (!acquisition?.has_purchases) {
    return (
      <DataNotice title="Sem eventos de compra (purchase) no GA4 neste período" testId="ga4-acquisition-empty">
        As sessões por campanha continuam abaixo. Compras e receita aparecem aqui quando o site envia o evento purchase ao GA4.
      </DataNotice>
    );
  }
  const derived = groups.some((row) => row.channel_group_source === "derivado");
  return (
    <div className="ds-stack" data-testid="ga4-acquisition">
      <div className="ds-tableWrap">
        <table className="ds-table" aria-label="Compras e receita do GA4 por canal de aquisição">
          <thead>
            <tr>
              <th scope="col">Canal de aquisição</th>
              <th scope="col" className="is-number">Sessões</th>
              <th scope="col" className="is-number">Compras</th>
              <th scope="col" className="is-number">Receita GA4</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((row) => (
              <tr key={row.channel_group}>
                <td className="is-primary">
                  {row.channel_group_label}
                  {row.channel_group_source === "derivado" ? <span className="ds-tableSub">estimado pela origem/mídia</span> : null}
                </td>
                <td className="is-number">{formatInteger(row.sessions)}</td>
                <td className="is-number">{formatInteger(row.ecommerce_purchases)}</td>
                <td className="is-number">{formatCurrency(row.purchase_revenue)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {notes.length || derived ? (
        <div>
          {notes.map((note) => <p key={note} className="ds-footnote">{note}</p>)}
          {derived ? <p className="ds-footnote">Canais marcados como estimados vêm de dados anteriores à coleta do agrupamento padrão do GA4; serão substituídos na próxima sincronização.</p> : null}
        </div>
      ) : null}
    </div>
  );
}
