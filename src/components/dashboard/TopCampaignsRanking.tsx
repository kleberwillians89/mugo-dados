import type { CampaignRankingRow } from "../../app/types";

function fmtCurrency(value: number): string {
  return value.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
}

function campaignLabel(row: CampaignRankingRow): string {
  const raw = String(row.campaign_name || "").trim();
  if (raw && !/^\d+$/.test(raw)) return raw;
  return `Campanha — ${row.campaign_id}`;
}

type Highlight = { label: string; row: CampaignRankingRow | null; format: (row: CampaignRankingRow) => string };

export default function TopCampaignsRanking({
  campaigns,
  loading,
  error,
}: {
  campaigns: CampaignRankingRow[];
  loading?: boolean;
  error?: string | null;
}) {
  if (loading && !campaigns.length) {
    return (
      <div className="topCampaigns">
        <div className="topCampaignsHead"><h3>Top campanhas</h3></div>
        <div className="topCampaignsSkeleton">
          {[0, 1, 2].map((i) => <div key={i} className="skeleton topCampaignsSkeletonRow" />)}
        </div>
      </div>
    );
  }

  if (!campaigns.length) {
    return (
      <div className="topCampaigns">
        <div className="topCampaignsHead"><h3>Top campanhas</h3></div>
        <div className="topCampaignsEmpty">
          <p>{error ? "Não foi possível carregar as campanhas agora." : "Sem campanhas com investimento neste período."}</p>
        </div>
      </div>
    );
  }

  const ranked = [...campaigns].sort((a, b) => b.spend - a.spend).slice(0, 6);
  const maxSpend = Math.max(...ranked.map((row) => row.spend), 1);

  const bestRoas = ranked.reduce<CampaignRankingRow | null>((best, row) => {
    if (row.roas == null) return best;
    if (!best || best.roas == null || row.roas > best.roas) return row;
    return best;
  }, null);
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
    {
      label: "Melhor ROAS",
      row: bestRoas,
      format: (row: CampaignRankingRow) => (row.roas != null ? `${row.roas.toFixed(2)}x` : "—"),
    },
    {
      label: "Maior investimento",
      row: highestSpend,
      format: (row: CampaignRankingRow) => fmtCurrency(row.spend),
    },
    {
      label: "Maior CPA",
      row: highestCpa,
      format: (row: CampaignRankingRow) => (row.conversions > 0 ? fmtCurrency(row.spend / row.conversions) : "—"),
    },
    { label: "Sem compra", row: noConversion, format: () => "0 compras" },
  ].filter((item) => item.row);

  return (
    <div className="topCampaigns">
      <div className="topCampaignsHead">
        <h3>Top campanhas</h3>
        <span className="smallMuted">Por investimento no período</span>
      </div>

      <ol className="topCampaignsList">
        {ranked.map((row, index) => (
          <li key={row.campaign_id} className="topCampaignsRow">
            <span className="topCampaignsRank">{index + 1}</span>
            <div className="topCampaignsMain">
              <div className="topCampaignsRowHead">
                <span className="topCampaignsName">{campaignLabel(row)}</span>
                <span className="topCampaignsSpend">{fmtCurrency(row.spend)}</span>
              </div>
              <div className="topCampaignsBarTrack">
                <span className="topCampaignsBarFill" style={{ width: `${Math.max((row.spend / maxSpend) * 100, 2)}%` }} />
              </div>
              <div className="topCampaignsMeta">
                <span>ROAS {row.roas != null ? `${row.roas.toFixed(2)}x` : "—"}</span>
                <span>{row.conversions.toLocaleString("pt-BR")} compras</span>
              </div>
            </div>
          </li>
        ))}
      </ol>

      {highlights.length ? (
        <div className="topCampaignsHighlights">
          {highlights.map((item) => (
            <div className="topCampaignsHighlight" key={item.label}>
              <span>{item.label}</span>
              <strong>{item.row ? campaignLabel(item.row) : "—"}</strong>
              <small>{item.row ? item.format(item.row) : ""}</small>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
