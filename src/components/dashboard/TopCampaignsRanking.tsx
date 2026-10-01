import type { CampaignRankingRow } from "../../app/types";
import { formatRatio } from "../../app/dataFormat";

function fmtCurrency(value: number): string {
  return value.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
}

function campaignLabel(row: CampaignRankingRow): string {
  const raw = String(row.campaign_name || "").trim();
  if (raw && !/^\d+$/.test(raw)) return raw;
  return `Campanha — ${row.campaign_id}`;
}

type Highlight = { label: string; row: CampaignRankingRow | null; format: (row: CampaignRankingRow) => string };

/** Meta atribui "compras"; o Google Ads informa "conversões". */
export type ConversionNoun = { one: string; many: string };
const PURCHASES: ConversionNoun = { one: "compra", many: "compras" };

export default function TopCampaignsRanking({
  campaigns,
  loading,
  error,
  noun = PURCHASES,
}: {
  campaigns: CampaignRankingRow[];
  loading?: boolean;
  error?: string | null;
  noun?: ConversionNoun;
}) {
  if (loading && !campaigns.length) {
    return <p className="ds-status" role="status">Carregando campanhas...</p>;
  }

  if (!campaigns.length) {
    return (
      <p className="ds-emptyLine">
        {error ? "Não foi possível carregar as campanhas agora." : "Sem campanhas com investimento neste período."}
      </p>
    );
  }

  const count = (value: number) => `${value.toLocaleString("pt-BR")} ${value === 1 ? noun.one : noun.many}`;
  const ranked = [...campaigns].sort((a, b) => b.spend - a.spend).slice(0, 6);
  const maxSpend = Math.max(...ranked.map((row) => row.spend), 1);

  // Mesmas regras de antes: ROAS só com 2+ conversões; 1 conversão é amostra pequena.
  const bestRoas = ranked.reduce<CampaignRankingRow | null>((best, row) => {
    if (row.roas == null || row.conversions < 2) return best;
    if (!best || best.roas == null || row.roas > best.roas) return row;
    return best;
  }, null);
  const smallSampleRoas = ranked
    .filter((row) => row.roas != null && row.conversions === 1)
    .sort((left, right) => (right.roas || 0) - (left.roas || 0))[0] || null;
  const highestSpend = ranked[0] || null;
  const highestCpa = ranked.reduce<CampaignRankingRow | null>((worst, row) => {
    const cpa = row.conversions > 0 ? row.spend / row.conversions : null;
    if (cpa == null) return worst;
    const worstCpa = worst && worst.conversions > 0 ? worst.spend / worst.conversions : null;
    if (!worst || worstCpa == null || cpa > worstCpa) return row;
    return worst;
  }, null);
  const noConversion = ranked.find((row) => row.conversions === 0 && row.spend > 0) || null;

  const highlights: Highlight[] = [
    { label: "Melhor ROAS", row: bestRoas, format: (row: CampaignRankingRow) => (row.roas != null ? formatRatio(row.roas) : "—") },
    { label: "Maior investimento", row: highestSpend, format: (row: CampaignRankingRow) => fmtCurrency(row.spend) },
    {
      label: "Maior custo por " + noun.one,
      row: highestCpa,
      format: (row: CampaignRankingRow) => (row.conversions > 0 ? fmtCurrency(row.spend / row.conversions) : "—"),
    },
    { label: `Sem ${noun.one}`, row: noConversion, format: () => `0 ${noun.many}` },
    { label: "Amostra pequena", row: smallSampleRoas, format: (row: CampaignRankingRow) => `${row.roas != null ? formatRatio(row.roas) : "—"} · 1 ${noun.one}` },
  ].filter((item) => item.row);

  return (
    <div className="ds-campaigns">
      <ol className="ds-rankList">
        {ranked.map((row) => (
          <li key={row.campaign_id} className="ds-rankRow">
            <span className="ds-rankName">{campaignLabel(row)}</span>
            <span className="ds-rankValue">{fmtCurrency(row.spend)}</span>
            <span className="ds-rankMeta">ROAS {row.roas != null ? formatRatio(row.roas) : "—"} · {count(row.conversions)}</span>
            <span className="ds-rankBar" aria-hidden="true">
              <span className="topCampaignsBarFill" style={{ width: `${Math.max((row.spend / maxSpend) * 100, 2)}%` }} />
            </span>
          </li>
        ))}
      </ol>

      {highlights.length ? (
        <dl className="ds-highlights" aria-label="Destaques das campanhas">
          {highlights.map((item) => (
            <div key={item.label}>
              <dt>{item.label}</dt>
              <dd>
                <span className="ds-highlightName">{item.row ? campaignLabel(item.row) : "—"}</span>
                <span className="ds-highlightValue">{item.row ? item.format(item.row) : ""}</span>
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
    </div>
  );
}
