import type { ReactNode } from "react";
import type { CampaignRankingRow, PaidTotals } from "../../app/types";
import {
  formatCurrency,
  formatCurrencyShort,
  formatInteger,
  formatPercent,
  formatRatio,
} from "../../app/dataFormat";
import Delta from "../data/Delta";
import HeroFigure from "../data/HeroFigure";
import KpiFigure from "../data/KpiFigure";
import PerformanceChart from "./PerformanceChart";
import TopCampaignsRanking from "./TopCampaignsRanking";

type Source = "Meta Ads" | "Google Ads";

export type PaidMediaTotals = {
  spend: number;
  /** Receita atribuída (Meta) ou valor de conversão (Google Ads). */
  revenue: number | null;
  conversions: number | null;
  impressions: number | null;
  clicks: number | null;
  reach?: number | null;
  linkClicks?: number | null;
  videoViews?: number | null;
  ctr: number | null;
  cpc: number | null;
  cpm: number | null;
};

/** Variações já calculadas pela página (%); null = sem base de comparação. */
export type PaidMediaChanges = {
  spend: number | null;
  revenue: number | null;
  conversions: number | null;
};

type Props = {
  source: Source;
  totals: PaidMediaTotals;
  /** Ausente quando a fonte não tem comparação com o período anterior. */
  changes?: PaidMediaChanges;
  /** Primeira frase da nota de rodapé (base da comparação). */
  comparisonNote: string;
  daily: Array<{ date: string; missing?: boolean } & PaidTotals>;
  /** Vendas da loja (Shopify) no mesmo período, quando a fonte cobre o recorte. */
  store: { revenue: number; orders: number; ticket: number | null; roas: number | null } | null;
  /** Bloco "Hoje" da loja, quando o período inclui o dia atual. */
  today?: ReactNode;
  campaigns: { rows: CampaignRankingRow[]; loading: boolean; error: string | null };
  testId?: string;
};

const VOCABULARY: Record<Source, {
  revenue: string; conversions: string; one: string; many: string; perConversion: string; attribution: string;
}> = {
  "Meta Ads": {
    revenue: "Receita atribuída", conversions: "Compras atribuídas", one: "compra", many: "compras atribuídas",
    perConversion: "Custo por compra", attribution: "Compras e receita são atribuídas pela Meta e podem diferir das vendas registradas na loja.",
  },
  "Google Ads": {
    revenue: "Valor de conversão", conversions: "Conversões", one: "conversão", many: "conversões",
    perConversion: "Custo por conversão", attribution: "Conversões e valor de conversão são informados pelo Google Ads e podem diferir das vendas registradas na loja.",
  },
};

const optional = (value: number | null | undefined, format: (value: number) => string) =>
  value == null || !Number.isFinite(value) ? "—" : format(value);

/**
 * Leitura da mídia paga, igual para Meta Ads e Google Ads: quanto foi
 * investido (protagonista) e o que a plataforma informa como resultado;
 * depois a tendência, a loja no mesmo período e as campanhas.
 * Só apresenta valores já calculados pela página — nada é inferido aqui.
 */
export default function PaidMediaReport({ source, totals, changes, comparisonNote, daily, store, today, campaigns, testId }: Props) {
  const words = VOCABULARY[source];
  const conversions = totals.conversions;
  const roas = totals.revenue != null && totals.spend > 0 ? totals.revenue / totals.spend : null;
  const costPerConversion = conversions != null && conversions > 0 ? totals.spend / conversions : null;
  const ticket = totals.revenue != null && conversions != null && conversions > 0 ? totals.revenue / conversions : null;
  const conversionText = conversions == null
    ? ""
    : `, com ${formatInteger(conversions)} ${conversions === 1 ? words.one + (source === "Meta Ads" ? " atribuída" : "") : words.many}`;

  return (
    <div className="ds-stack" data-testid={testId}>
      <section className="ds-summary" aria-label={`Resumo de ${source}`}>
        <HeroFigure
          value={formatCurrencyShort(totals.spend)}
          exactValue={formatCurrency(totals.spend)}
          rawValue={totals.spend}
          label={`investidos em ${source}${conversionText} no período`}
          delta={changes ? <Delta change={changes.spend} sentiment="neutral" showReference /> : undefined}
          testId={`${testId || "paid"}-spend`}
        />
        <div className="ds-kpis is-four">
          {conversions != null ? (
            <KpiFigure
              label={words.conversions}
              value={formatInteger(conversions)}
              rawValue={conversions}
              delta={changes ? <Delta change={changes.conversions} /> : undefined}
            />
          ) : null}
          {totals.revenue != null ? (
            <KpiFigure
              label={words.revenue}
              value={formatCurrencyShort(totals.revenue)}
              exactValue={formatCurrency(totals.revenue)}
              rawValue={totals.revenue}
              delta={changes ? <Delta change={changes.revenue} /> : undefined}
            />
          ) : null}
          {roas != null ? <KpiFigure label="ROAS atribuído" value={formatRatio(roas)} rawValue={roas} /> : null}
          {costPerConversion != null ? (
            <KpiFigure
              label={words.perConversion}
              value={formatCurrencyShort(costPerConversion)}
              exactValue={formatCurrency(costPerConversion)}
              rawValue={costPerConversion}
            />
          ) : null}
        </div>
        <div className="ds-secondary">
          <dl className="ds-inlineStats">
            <div><dt>Impressões</dt><dd>{optional(totals.impressions, formatInteger)}</dd></div>
            {totals.reach != null ? <div><dt>Alcance</dt><dd>{formatInteger(totals.reach)}</dd></div> : null}
            <div><dt>Cliques</dt><dd>{optional(totals.clicks, formatInteger)}</dd></div>
            {totals.linkClicks != null ? <div><dt>Cliques no link</dt><dd>{formatInteger(totals.linkClicks)}</dd></div> : null}
            <div><dt>CTR</dt><dd>{optional(totals.ctr, (value) => formatPercent(value))}</dd></div>
            <div><dt>CPC</dt><dd>{optional(totals.cpc, formatCurrency)}</dd></div>
            <div><dt>CPM</dt><dd>{optional(totals.cpm, formatCurrency)}</dd></div>
            {totals.videoViews != null ? <div><dt>Visualizações de vídeo</dt><dd>{formatInteger(totals.videoViews)}</dd></div> : null}
            {ticket != null ? <div><dt>Valor médio por {words.one}</dt><dd>{formatCurrency(ticket)}</dd></div> : null}
          </dl>
          <p className="ds-footnote">{comparisonNote} {words.attribution}</p>
        </div>
      </section>

      <PerformanceChart daily={daily} source={source} />

      {store ? (
        <section className="ds-section" aria-labelledby={`${testId || "paid"}-store-title`}>
          <div className="ds-sectionHead">
            <div className="ds-sectionHeadText">
              <h2 id={`${testId || "paid"}-store-title`} className="ds-sectionTitle">
                A loja vendeu {formatCurrencyShort(store.revenue)} no mesmo período
              </h2>
              <p className="ds-caption">Vendas reais da loja ao lado do que a plataforma atribui a si mesma.</p>
            </div>
          </div>
          <dl className="ds-sourceList">
            <div>
              <dt>Loja · Shopify</dt>
              <dd>
                <strong>{formatCurrency(store.revenue)}</strong>
                <span>{formatInteger(store.orders)} {store.orders === 1 ? "pedido" : "pedidos"}</span>
                <span>ticket médio {optional(store.ticket, formatCurrency)}</span>
              </dd>
            </div>
            <div>
              <dt>Atribuído · {source}</dt>
              <dd>
                <strong>{optional(totals.revenue, formatCurrency)}</strong>
                {conversions != null ? <span>{formatInteger(conversions)} {conversions === 1 ? words.one : words.many}</span> : null}
              </dd>
            </div>
            <div>
              <dt>ROAS sobre a loja</dt>
              <dd>
                <strong>{optional(store.roas, formatRatio)}</strong>
                <span>receita da loja ÷ investimento em {source}</span>
              </dd>
            </div>
          </dl>
          {today}
        </section>
      ) : today ? <section className="ds-section">{today}</section> : null}

      <section className="ds-section" aria-labelledby={`${testId || "paid"}-campaigns-title`}>
        <h2 id={`${testId || "paid"}-campaigns-title`} className="ds-sectionTitle">Campanhas por investimento</h2>
        <TopCampaignsRanking
          campaigns={campaigns.rows}
          loading={campaigns.loading}
          error={campaigns.error}
          noun={source === "Meta Ads" ? { one: "compra", many: "compras" } : { one: "conversão", many: "conversões" }}
        />
      </section>
    </div>
  );
}
