import { useMemo, useState } from "react";
import { Line } from "react-chartjs-2";
import type { ChartData, ChartOptions } from "chart.js";
import type { PaidTotals } from "../../app/types";
import { CHART_COLORS, formatDatePtBr, formatFullNumber } from "./chartTheme";

type MetricKey = "revenue" | "spend" | "reach" | "impressions" | "clicks" | "roas" | "conversions";

const METRIC_TABS: { key: MetricKey; label: string }[] = [
  { key: "revenue", label: "Receita" },
  { key: "spend", label: "Investimento" },
  { key: "reach", label: "Alcance" },
  { key: "impressions", label: "Impressões" },
  { key: "clicks", label: "Cliques" },
  { key: "roas", label: "ROAS" },
  { key: "conversions", label: "Compras" },
];

const METRIC_QUESTIONS: Record<MetricKey, string> = {
  revenue: "Como a receita evoluiu?",
  spend: "Como o investimento evoluiu?",
  reach: "Como o alcance evoluiu?",
  impressions: "Como as impressões evoluíram?",
  clicks: "Como os cliques evoluíram?",
  roas: "Como o ROAS evoluiu?",
  conversions: "Como as compras evoluíram?",
};

function formatValue(metric: MetricKey, value: number | null): string {
  if (value == null) return "Sem dados";
  if (metric === "revenue" || metric === "spend") {
    return value.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
  }
  if (metric === "roas") return `${value.toFixed(2)}x`;
  return formatFullNumber(value);
}

export default function PerformanceChart({
  daily,
  source = "Meta Ads",
}: {
  daily: Array<{ date: string; missing?: boolean } & PaidTotals> | undefined;
  source?: "Meta Ads" | "Google Ads";
}) {
  const [metric, setMetric] = useState<MetricKey>("revenue");
  const rows = useMemo(() => daily || [], [daily]);
  const hasData = rows.some((row) => row[metric] != null);
  const coveredDays = rows.filter((row) => !row.missing && row[metric] != null).length;
  const coverageLabel = rows.length > 0 && coveredDays < rows.length
    ? `Cobertura: ${coveredDays} de ${rows.length} dias`
    : null;

  const labels = useMemo(() => rows.map((row) => formatDatePtBr(row.date).replace(/ de \d{4}$/, "")), [rows]);
  const series = useMemo(() => rows.map((row) => row[metric] == null ? null : Number(row[metric])), [rows, metric]);

  const chartData: ChartData<"line", Array<number | null>, string> = useMemo(
    () => ({
      labels,
      datasets: [
        {
          label: METRIC_TABS.find((tab) => tab.key === metric)?.label || "",
          data: series,
          borderColor: CHART_COLORS.organic,
          backgroundColor: "rgba(45,108,223,0.08)",
          borderWidth: 2.4,
          tension: 0.35,
          pointRadius: 0,
          pointHitRadius: 16,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: CHART_COLORS.organic,
          pointHoverBorderColor: "#fff",
          pointHoverBorderWidth: 2,
          fill: true,
        },
      ],
    }),
    [labels, metric, series]
  );

  const options: ChartOptions<"line"> = useMemo(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          enabled: true,
          backgroundColor: CHART_COLORS.tooltipBg,
          borderColor: CHART_COLORS.tooltipBorder,
          borderWidth: 1,
          titleColor: CHART_COLORS.tooltipText,
          bodyColor: CHART_COLORS.tooltipText,
          padding: 12,
          displayColors: false,
          callbacks: {
            title: (items) => `Data: ${labels[items[0]?.dataIndex ?? 0] || ""}`,
            label: (item) => `${formatValue(metric, item.parsed.y == null ? null : Number(item.parsed.y))} · Fonte: ${source}`,
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: CHART_COLORS.axis, maxRotation: 0, minRotation: 0, maxTicksLimit: 8, font: { weight: 600 } },
        },
        y: {
          beginAtZero: true,
          grace: "10%",
          grid: { color: CHART_COLORS.grid },
          ticks: {
            color: CHART_COLORS.axis,
            maxTicksLimit: 5,
            callback: (value) => formatValue(metric, Number(value)),
            font: { weight: 600 },
          },
        },
      },
    }),
    [labels, metric, source]
  );

  return (
    <div className="performanceChart">
      <div className="performanceChartHead">
        <div>
          <span className="performanceChartTitle">{METRIC_QUESTIONS[metric]}</span>
          <div className="smallMuted">Evolução diária no período selecionado · Fonte: Meta Ads</div>
          {coverageLabel ? <div className="smallMuted">{coverageLabel}</div> : null}
        </div>
        <div className="performanceChartTabs" role="tablist" aria-label="Métrica do gráfico de desempenho">
          {METRIC_TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={metric === tab.key}
              className={`performanceChartTab${metric === tab.key ? " is-active" : ""}`}
              onClick={() => setMetric(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>
      <div className="performanceChartViewport">
        {hasData ? (
          <Line data={chartData} options={options} />
        ) : (
          <div className="chartEmptyState">
            <div className="smallMuted">Sem {METRIC_TABS.find((t) => t.key === metric)?.label.toLowerCase()} neste período.</div>
            <div className="smallMuted">O gráfico aparece assim que a Meta sincronizar dados diários.</div>
          </div>
        )}
      </div>
    </div>
  );
}
