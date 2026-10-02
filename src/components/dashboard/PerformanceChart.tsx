import { useMemo, useState } from "react";
import type { PaidTotals } from "../../app/types";
import {
  formatCalendarDate,
  formatCalendarDateWords,
  formatCompactInteger,
  formatCurrency,
  formatCurrencyAxis,
  formatInteger,
  formatRatio,
  uniquePeak,
} from "../../app/dataFormat";
import SegmentedControl from "../data/SegmentedControl";
import TrendChart from "../data/TrendChart";

type MetricKey = "spend" | "revenue" | "conversions" | "clicks" | "impressions" | "reach" | "roas";
type Kind = "currency" | "count" | "ratio";
type Source = "Meta Ads" | "Google Ads";
type DailyRow = { date: string; missing?: boolean } & PaidTotals;

type MetricDef = { label: string; kind: Kind; peak: string | null };

/**
 * Vocabulário de cada plataforma: a Meta atribui "compras" e "receita";
 * o Google Ads informa "conversões" e "valor de conversão". O ROAS do
 * gráfico é o da loja (receita Shopify ÷ investimento), como antes.
 */
function metricDefs(source: Source): Record<MetricKey, MetricDef> {
  const meta = source === "Meta Ads";
  return {
    spend: { label: "Investimento", kind: "currency", peak: "o maior investimento" },
    revenue: meta
      ? { label: "Receita atribuída", kind: "currency", peak: "a maior receita atribuída" }
      : { label: "Valor de conversão", kind: "currency", peak: "o maior valor de conversão" },
    conversions: meta
      ? { label: "Compras", kind: "count", peak: "o maior número de compras" }
      : { label: "Conversões", kind: "count", peak: "o maior número de conversões" },
    clicks: { label: "Cliques", kind: "count", peak: "o maior número de cliques" },
    impressions: { label: "Impressões", kind: "count", peak: "o maior número de impressões" },
    reach: { label: "Alcance", kind: "count", peak: "o maior alcance" },
    roas: { label: "ROAS da loja", kind: "ratio", peak: null },
  };
}

const ORDER: MetricKey[] = ["spend", "revenue", "conversions", "clicks", "impressions", "reach", "roas"];

function formatValue(kind: Kind, value: number | null): string {
  if (value == null) return "Sem dados";
  if (kind === "currency") return formatCurrency(value);
  if (kind === "ratio") return formatRatio(value);
  return formatInteger(value);
}

function formatAxis(kind: Kind, value: number): string {
  if (kind === "currency") return formatCurrencyAxis(value);
  if (kind === "ratio") return formatRatio(value);
  return formatCompactInteger(value);
}

/**
 * Evolução diária da mídia paga (Meta Ads e Google Ads). Dia sem dado é
 * lacuna no gráfico — nunca zero; um único dia vira um valor, não uma linha.
 * O título aponta o pico só quando ele é objetivo (um único maior valor).
 */
export default function PerformanceChart({
  daily,
  source = "Meta Ads",
  defaultMetric = "spend",
}: {
  daily: DailyRow[] | undefined;
  source?: Source;
  defaultMetric?: MetricKey;
}) {
  const rows = useMemo(() => daily || [], [daily]);
  const defs = useMemo(() => metricDefs(source), [source]);
  // Só entram no seletor as métricas que a fonte realmente trouxe no período.
  const available = useMemo(
    () => ORDER.filter((key) => rows.some((row) => !row.missing && row[key] != null)),
    [rows]
  );
  const [chosen, setChosen] = useState<MetricKey>(defaultMetric);
  const metric = available.includes(chosen) ? chosen : available[0] || chosen;
  const def = defs[metric];
  const series = useMemo(
    () => rows.map((row) => ({ date: row.date, value: row.missing || row[metric] == null ? null : Number(row[metric]) })),
    [metric, rows]
  );
  const withValue = series.filter((point): point is { date: string; value: number } => point.value != null);
  const peak = def.peak ? uniquePeak(withValue, (point) => point.value) : null;
  const title = peak && def.peak
    ? `${formatCalendarDateWords(peak.date)} concentrou ${def.peak}`
    : `${def.label} por dia`;
  const coverage = rows.length > 1 && withValue.length < rows.length
    ? `Dados em ${formatInteger(withValue.length)} de ${formatInteger(rows.length)} dias`
    : null;
  const shortSource = source === "Meta Ads" ? "Meta" : "Google Ads";

  return (
    <section className="ds-section ds-chartSection" aria-label={`Evolução diária · ${source}`}>
      <div className="ds-sectionHead">
        <div className="ds-sectionHeadText">
          <h2 className="ds-sectionTitle">{title}</h2>
          {peak || coverage ? (
            <p className="ds-caption">
              {peak ? `${formatValue(def.kind, peak.value)} nesse dia` : null}
              {peak && coverage ? " · " : null}
              {coverage}
            </p>
          ) : null}
        </div>
        {available.length > 1 ? (
          <SegmentedControl
            ariaLabel="Métrica do gráfico"
            value={metric}
            onSelect={(id) => setChosen(id as MetricKey)}
            options={available.map((key) => ({ id: key, label: defs[key].label }))}
          />
        ) : null}
      </div>
      {withValue.length === 1 ? (
        <div className="ds-singleValue" data-testid="performance-single-day">
          <span>{formatCalendarDateWords(withValue[0].date)}</span>
          <strong>{formatValue(def.kind, withValue[0].value)}</strong>
          <small>{def.label} · Fonte: {source}</small>
        </div>
      ) : withValue.length > 1 ? (
        <TrendChart
          data={series}
          xKey="date"
          primaryKey="value"
          formatX={(value) => formatCalendarDate(value)}
          formatY={(value) => formatAxis(def.kind, value)}
          ariaLabel={`${def.label} por dia no período, fonte ${source}.`}
          testId="performance-chart"
          renderTooltip={(point) => {
            const row = rows.find((item) => item.date === point.date);
            return (
              <>
                <strong>{formatCalendarDate(point.date, "long")}</strong>
                <dl>
                  {ORDER.filter((key) => available.includes(key) && row && !row.missing && row[key] != null).map((key) => (
                    <div key={key} style={{ display: "contents" }}>
                      <dt>{defs[key].label}</dt>
                      <dd>{formatValue(defs[key].kind, Number(row![key]))}</dd>
                    </div>
                  ))}
                </dl>
              </>
            );
          }}
        />
      ) : (
        <p className="ds-emptyLine">
          {rows.length === 1 ? `Sem dados ${shortSource} para esta data.` : `Sem ${def.label.toLowerCase()} neste período.`}
        </p>
      )}
    </section>
  );
}
