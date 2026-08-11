import { startTransition, useCallback, useDeferredValue, useEffect, useMemo, useState } from "react";
import "../app/chartSetup";
import { Bar, Line } from "react-chartjs-2";
import type { ChartData, ChartOptions } from "chart.js";

import Shell from "../components/Shell";
import { type KpiKey } from "../components/KpiGrid";
import MediaTable from "../components/MediaTable";
import CommentsPanel from "../components/CommentsPanel";
import NotesPanel from "../components/NotesPanel";
import { MonthCompareLines, MonthMixChart } from "../components/Charts";
import DashboardHeader from "../components/dashboard/DashboardHeader";
import MetaBlockBoundary from "../components/dashboard/MetaBlockBoundary";
import MetaStateNotice from "../components/dashboard/MetaStateNotice";
import ExecutiveOverview, {
  type ExecutiveMetric,
  type ExecutiveSource,
} from "../components/dashboard/ExecutiveOverview";
import ChannelTodaySummary from "../components/dashboard/ChannelTodaySummary";

import useDashboardSummary from "../hooks/dashboard/useDashboardSummary";
import useDashboardMonthlyContent from "../hooks/dashboard/useDashboardMonthlyContent";
import useDashboardPaid from "../hooks/dashboard/useDashboardPaid";
import useExecutiveDashboard from "../hooks/dashboard/useExecutiveDashboard";
import useCampaignsRanking from "../hooks/dashboard/useCampaignsRanking";
import TopCampaignsRanking from "../components/dashboard/TopCampaignsRanking";
import AttentionPanel from "../components/dashboard/AttentionPanel";
import PerformanceChart from "../components/dashboard/PerformanceChart";
import {
  buildDashboardCacheKey,
  readDashboardCache,
  writeDashboardCache,
} from "../hooks/dashboard/cache";
import { resolveCommerceConnection, resolveOperationalMetaConnectionId, selectUniqueConnection } from "../app/connectionManager";
import { ensureDashboardPeriod, previousDashboardPeriod } from "../hooks/dashboard/period";
import { describeSyncError, runExclusiveSync } from "../app/syncOrchestrator";

import {
  refreshAll,
  listMonthsByConnection,
  listNotes,
  createNote,
  updateNote,
  listClientConnections,
  listGenericConnections,
  selectUsableGoogleConnection,
  syncAds,
  syncGa4,
  syncGoogleConnection,
  syncShopifyConnection,
  ApiError,
  type GenericConnection,
} from "../app/api";
import { useDashboardSnapshot } from "../app/DashboardDataContext";
import { hasInstagramSnapshotData } from "../app/dashboardDataState";

import { buildMonthAgg, classifyInstagramMedia, getMonth, monthsList, pct } from "../app/aggregate";

import type {
  DashboardDailyRow,
  DashboardResponse,
  DashboardTotals,
  IgMediaItem,
  MetaConnection,
  NoteItem,
  PaidDashboardResponse,
  RefreshAllResponse,
} from "../app/types";
import {
  CHART_COLORS,
  formatCompactNumber,
  formatDatePtBr,
  formatFullNumber,
} from "../components/dashboard/chartTheme";

import {
  getActiveConnectionId,
  getSelectedConnectionId,
} from "../app/connectionState";
import { usePeriod } from "../app/PeriodContext";
import { formatSelectedPeriodLabel, getSelectedPeriodRange } from "../app/periodRange";
import {
  getActiveClientId,
  getActiveClient,
  getActiveClientName,
  getActiveClientConfigurationWarning,
} from "../app/activeClient";

import "../styles/dashboard.css";

const DASH_DEBUG =
  import.meta.env.DEV && import.meta.env.VITE_DASH_DEBUG === "true";
const SHOW_PRESENTATION_EXTRAS = false;
function dashLog(step: string, data?: Record<string, unknown>) {
  if (!DASH_DEBUG) return;
  try {
    if (data) console.log(`[dash-debug] ${step}`, data);
    else console.log(`[dash-debug] ${step}`);
  } catch {
    // no-op
  }
}

function safe(v: unknown) {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string") {
    const parsed = Number(v);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}
function fmt(n: number) {
  try {
    return n.toLocaleString("pt-BR");
  } catch {
    return String(n);
  }
}
function fmtCurrency(n: number) {
  try {
    return n.toLocaleString("pt-BR", {
      style: "currency",
      currency: "BRL",
      maximumFractionDigits: 2,
    });
  } catch {
    return String(n);
  }
}
function growthPct(current: number, previous: number) {
  if (!previous) return current > 0 ? 100 : 0;
  return ((current - previous) / previous) * 100;
}

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  return fallback;
}

function arrayOrEmpty<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

type NotesCachePayload = {
  notes: NoteItem[];
  available: boolean;
  message: string | null;
};

function formatUpdatedAtLabel(value: string | null | undefined): string | null {
  const raw = String(value || "").trim();
  if (!raw) return null;
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return null;
  return `Última atualização ${parsed.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })}`;
}

function providerFreshnessDetail(provider: {
  data_max_available?: string | null;
  last_success_at?: string | null;
  stale?: boolean;
  sync_state?: string;
  last_error?: string | null;
} | null | undefined): string {
  const parts: string[] = [];
  if (provider?.data_max_available) parts.push(`Dados até ${formatDatePtBr(provider.data_max_available)}`);
  const updated = formatUpdatedAtLabel(provider?.last_success_at);
  if (updated) parts.push(updated);
  if (provider?.stale || provider?.sync_state === "error") parts.push("última atualização pendente");
  return parts.join(" · ") || "Sem snapshot persistido";
}

type DashboardMetricKey = keyof DashboardTotals;

type MetaMetricKey =
  | "impressions"
  | "reach"
  | "total_interactions"
  | "website_clicks"
  | "profile_views"
  | "accounts_engaged"
  | "followers";

type ChartGranularity = "daily" | "weekly" | "monthly";

const DASHBOARD_LINE_WIDTH = 2;
const DASHBOARD_TENSION = 0.4;
const DASHBOARD_POINT_RADIUS = 3;
const DASHBOARD_POINT_HOVER_RADIUS = 5;
const MONTH_SHORT_PT = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];

const METRIC_CONTEXT: Record<MetaMetricKey, string> = {
  impressions: "Visualizações no período",
  reach: "Contas alcançadas",
  total_interactions: "Interações totais",
  website_clicks: "Cliques em link",
  profile_views: "Visitas ao perfil",
  accounts_engaged: "Contas engajadas",
  followers: "Variação de seguidores",
};

const META_METRIC_BY_KPI: Record<KpiKey, MetaMetricKey> = {
  reach: "reach",
  profile_views: "profile_views",
  website_clicks: "website_clicks",
  accounts_engaged: "accounts_engaged",
  total_interactions: "total_interactions",
  followers: "followers",
};

type MetaCardProps = {
  title: string;
  metric: MetaMetricKey;
  dash: DashboardResponse;
  paidData?: PaidDashboardResponse | null;
  days: number;
  periodLabel: string;
  granularity: ChartGranularity;
  highlighted?: boolean;
  variant?: "primary" | "secondary";
};

function granularityLabel(granularity: ChartGranularity): string {
  if (granularity === "weekly") return "Semanal";
  if (granularity === "monthly") return "Mensal";
  return "Diário";
}

function formatSeriesLabel(
  granularity: ChartGranularity,
  startDate: Date,
  endDate: Date
): string {
  if (granularity === "monthly") {
    const month = MONTH_SHORT_PT[endDate.getMonth()] || "Mês";
    const year = String(endDate.getFullYear()).slice(-2);
    return `${month} ${year}`;
  }
  if (granularity === "weekly") {
    const week = getIsoWeekNumber(startDate);
    return `Semana ${week}`;
  }
  return endDate.toLocaleDateString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
  });
}

function getIsoWeekNumber(date: Date): number {
  const copy = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNum = copy.getUTCDay() || 7;
  copy.setUTCDate(copy.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(copy.getUTCFullYear(), 0, 1));
  return Math.ceil((((copy.getTime() - yearStart.getTime()) / 86400000) + 1) / 7);
}

function mediaInsightValue(media: IgMediaItem, key: string): number {
  const insights = media?.insights || {};
  return safe((insights as Record<string, unknown>)[key]);
}

function mediaImpactScore(media: IgMediaItem): number {
  const reach = mediaInsightValue(media, "reach");
  const views = mediaInsightValue(media, "views");
  const interactions = mediaInsightValue(media, "total_interactions");
  const saved = mediaInsightValue(media, "saved");
  const shares = mediaInsightValue(media, "shares");
  const comments = mediaInsightValue(media, "comments");
  const likes = mediaInsightValue(media, "likes");
  const isReels = String(media.media_product_type || "").toUpperCase() === "REELS";

  return Math.round(
    reach * 1 +
      (isReels ? views * 0.7 : 0) +
      interactions * 3 +
      saved * 4 +
      shares * 4 +
      comments * 2 +
      likes * 0.5
  );
}

const FLOW_METRIC_KEYS = [
  "impressions",
  "reach",
  "total_interactions",
  "website_clicks",
  "profile_views",
  "accounts_engaged",
] as const;

type FlowMetricKey = (typeof FLOW_METRIC_KEYS)[number];

function parseIsoDate(value: string): Date | null {
  const text = String(value || "").trim();
  if (!text) return null;
  const parsed = new Date(`${text}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
}

function toIsoDate(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
    date.getDate()
  ).padStart(2, "0")}`;
}

function startOfWeek(date: Date): Date {
  const copy = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const day = copy.getDay();
  const diff = day === 0 ? -6 : 1 - day;
  copy.setDate(copy.getDate() + diff);
  return copy;
}

function startOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

function bucketKey(date: Date, granularity: ChartGranularity): string {
  if (granularity === "weekly") return toIsoDate(startOfWeek(date));
  if (granularity === "monthly") return toIsoDate(startOfMonth(date));
  return toIsoDate(date);
}

function aggregateRowsByGranularity(
  rows: DashboardDailyRow[],
  granularity: ChartGranularity
): DashboardDailyRow[] {
  const normalized = rows
    .map((row) => {
      const date = parseIsoDate(String(row?.date || ""));
      if (!date) return null;
      return {
        date,
        row,
      };
    })
    .filter((item): item is { date: Date; row: DashboardDailyRow } => Boolean(item))
    .sort((a, b) => a.date.getTime() - b.date.getTime());

  if (!normalized.length) return [];

  type Bucket = {
    startDate: Date;
    endDate: Date;
    start: string;
    end: string;
    followers: number;
    sums: Record<FlowMetricKey, number>;
  };

  const buckets = new Map<string, Bucket>();

  for (const item of normalized) {
    const key = bucketKey(item.date, granularity);
    const followers = safe(item.row.followers);
    const sumsFromRow: Record<FlowMetricKey, number> = {
      impressions: safe(item.row.impressions),
      reach: safe(item.row.reach),
      total_interactions: safe(item.row.total_interactions),
      website_clicks: safe(item.row.website_clicks),
      profile_views: safe(item.row.profile_views),
      accounts_engaged: safe(item.row.accounts_engaged),
    };

    const existing = buckets.get(key);
    if (!existing) {
      buckets.set(key, {
        startDate: item.date,
        endDate: item.date,
        start: toIsoDate(item.date),
        end: toIsoDate(item.date),
        followers,
        sums: sumsFromRow,
      });
      continue;
    }

    if (item.date.getTime() < existing.startDate.getTime()) {
      existing.startDate = item.date;
      existing.start = toIsoDate(item.date);
    }
    if (item.date.getTime() >= existing.endDate.getTime()) {
      existing.endDate = item.date;
      existing.end = toIsoDate(item.date);
      existing.followers = followers;
    }
    for (const metricKey of FLOW_METRIC_KEYS) {
      existing.sums[metricKey] += sumsFromRow[metricKey];
    }
  }

  return Array.from(buckets.values())
    .sort((a, b) => a.startDate.getTime() - b.startDate.getTime())
    .map((bucket) => ({
      date: bucket.end,
      start: bucket.start,
      end: bucket.end,
      impressions: bucket.sums.impressions,
      reach: bucket.sums.reach,
      total_interactions: bucket.sums.total_interactions,
      website_clicks: bucket.sums.website_clicks,
      profile_views: bucket.sums.profile_views,
      accounts_engaged: bucket.sums.accounts_engaged,
      followers: bucket.followers,
    }));
}

function MetaChartCard({
  title,
  metric,
  dash,
  paidData,
  days,
  periodLabel,
  granularity,
  highlighted = false,
  variant = "secondary",
}: MetaCardProps) {
  const chartRows = useMemo(() => {
    const baseRows = Array.isArray(dash?.daily) && dash.daily.length
      ? dash.daily
      : Array.isArray(dash?.series?.daily)
        ? dash.series.daily
        : [];
    return aggregateRowsByGranularity(baseRows, granularity);
  }, [dash, granularity]);

  const rawSeries = useMemo(() => {
    if (metric === "followers") {
      const deltas: number[] = [];
      for (let i = 0; i < chartRows.length; i++) {
        const cur = safe(chartRows[i]?.followers);
        const prev = i === 0 ? cur : safe(chartRows[i - 1]?.followers);
        deltas.push(cur - prev);
      }
      return deltas;
    }
    return chartRows.map((d) => safe(d[metric]));
  }, [chartRows, metric]);

  const points = useMemo(
    () =>
      chartRows
        .map((row, index) => {
          const dateText = String(row?.date || "").trim();
          const parsed = new Date(`${dateText}T00:00:00`);
          const startText = String(row?.start || dateText).trim();
          const endText = String(row?.end || dateText).trim();
          const parsedStart = new Date(`${startText}T00:00:00`);
          const parsedEnd = new Date(`${endText}T00:00:00`);
          const value = safe(rawSeries[index]);
          if (!dateText || Number.isNaN(parsed.getTime()) || !Number.isFinite(value)) return null;
          return {
            date: parsed,
            start: Number.isNaN(parsedStart.getTime()) ? parsed : parsedStart,
            end: Number.isNaN(parsedEnd.getTime()) ? parsed : parsedEnd,
            value,
          };
        })
        .filter(
          (item): item is { date: Date; start: Date; end: Date; value: number } =>
            Boolean(item)
        ),
    [chartRows, rawSeries]
  );

  const labels = useMemo(
    () => points.map((point) => formatSeriesLabel(granularity, point.start, point.end)),
    [granularity, points]
  );
  const series = useMemo(() => points.map((point) => point.value), [points]);
  const bucketKeys = useMemo(
    () =>
      chartRows.map((row) => {
        const startDate = parseIsoDate(String(row?.start || row?.date || ""));
        if (!startDate) return "";
        return bucketKey(startDate, granularity);
      }),
    [chartRows, granularity]
  );
  const pointDates = useMemo(
    () =>
      points.map(
        (point) =>
          `${point.end.getFullYear()}-${pad2(point.end.getMonth() + 1)}-${pad2(point.end.getDate())}`
      ),
    [points]
  );

  const todayValue = series.length ? safe(series[series.length - 1]) : 0;
  const lastPointLabel =
    granularity === "monthly"
      ? "Último mês"
      : granularity === "weekly"
        ? "Última semana"
        : "Último dia";

  const periodTotal =
    metric === "followers"
      ? safe(dash?.period_totals?.followers_growth ?? dash?.followers_growth_last_days ?? 0)
      : series.reduce((total, value) => total + safe(value), 0);

  const previousPeriodTotal =
    metric === "followers"
      ? safe(
          (dash?.period_previous_totals?.followers_growth ??
            dash?.followers_growth_previous_period ??
            dash?.last_month_followers_growth) || 0
        )
      : safe(
          (dash?.period_previous_totals?.[metric as DashboardMetricKey] ??
            dash?.totals_previous_period?.[metric as DashboardMetricKey] ??
            dash?.last_month_totals?.[metric as DashboardMetricKey]) ||
            0
        );

  const g = growthPct(periodTotal, previousPeriodTotal);
  const isPartialCoverage = Boolean(dash?.coverage?.is_partial);
  const coveredDays = safe(dash?.coverage?.covered_days);
  const expectedDays = safe(dash?.coverage?.expected_days);
  const partialCoverageText =
    isPartialCoverage && expectedDays > 0 ? `Dados parciais: ${coveredDays}/${expectedDays} dias` : "";
  const growthSummary =
    isPartialCoverage
      ? partialCoverageText || "Dados parciais"
      : previousPeriodTotal > 0
        ? `${g >= 0 ? "+" : "-"}${Math.abs(g).toFixed(Math.abs(g) >= 10 ? 0 : 1)}% vs período anterior`
        : "Sem base comparável no período anterior";

  const paidMetricKey =
    metric === "impressions"
      ? "impressions"
      : metric === "reach"
        ? "reach"
        : metric === "website_clicks"
          ? "clicks"
          : null;

  const paidByBucket = useMemo(() => {
    const map = new Map<string, number>();
    const rows = Array.isArray(paidData?.daily) ? paidData!.daily : [];
    if (!paidMetricKey) return map;
    for (const row of rows) {
      const dateText = String(row?.date || "").trim();
      const parsed = parseIsoDate(dateText);
      if (!parsed) continue;
      const key = bucketKey(parsed, granularity);
      let value = 0;
      if (paidMetricKey === "impressions") value = safe(row?.impressions);
      if (paidMetricKey === "reach") value = safe(row?.reach);
      if (paidMetricKey === "clicks") value = safe(row?.clicks);
      map.set(key, safe(map.get(key)) + value);
    }
    return map;
  }, [granularity, paidData, paidMetricKey]);

  const paidOverlaySeries = useMemo(() => {
    if (!paidMetricKey) return [];
    return bucketKeys.map((key) => safe(paidByBucket.get(key) ?? null));
  }, [bucketKeys, paidByBucket, paidMetricKey]);

  const hasOverlay = paidOverlaySeries.some((value) => Number.isFinite(value) && value > 0);
  const pointCount = series.length;
  const hasMainLine = pointCount > 1;
  const hasOverlayLine = paidOverlaySeries.length > 1;
  const singlePointValue = pointCount === 1 ? safe(series[0]) : null;
  const isSinglePoint = pointCount === 1;
  // Séries temporais com muitos pontos usam linha/área suave (acabamento premium);
  // barras verticais ficam reservadas para 2-6 categorias, evitando barras estreitas
  // e desproporcionais em séries diárias longas.
  const useBarChart = pointCount >= 2 && pointCount <= 6;
  const useLineChart = pointCount >= 7;
  const usesBarVisualization = useBarChart;
  const barMaxThickness = pointCount <= 4 ? 48 : 32;
  const isPrimary = variant === "primary";
  const comparisonText =
    previousPeriodTotal > 0
      ? `${fmt(periodTotal)} vs ${fmt(previousPeriodTotal)}`
      : "Período anterior sem base comparável";

  const lineData: ChartData<"line", number[], string> = useMemo(() => {
    const datasets: ChartData<"line", number[], string>["datasets"] = [
      {
        label: "Orgânico",
        data: series,
        tension: DASHBOARD_TENSION,
        borderWidth: DASHBOARD_LINE_WIDTH,
        pointRadius: DASHBOARD_POINT_RADIUS,
        pointHitRadius: 14,
        pointHoverRadius: DASHBOARD_POINT_HOVER_RADIUS,
        borderColor: isPartialCoverage ? CHART_COLORS.organicMuted : CHART_COLORS.organic,
        backgroundColor: CHART_COLORS.organicSoft,
        fill: false,
        showLine: hasMainLine,
        spanGaps: true,
      },
    ];
    if (hasOverlay) {
      datasets.push({
        label: "Ads",
        data: paidOverlaySeries,
        tension: DASHBOARD_TENSION,
        borderWidth: DASHBOARD_LINE_WIDTH,
        pointRadius: DASHBOARD_POINT_RADIUS,
        pointHitRadius: 14,
        pointHoverRadius: DASHBOARD_POINT_HOVER_RADIUS,
        borderColor: CHART_COLORS.ads,
        backgroundColor: CHART_COLORS.adsSoft,
        borderDash: [6, 5],
        fill: false,
        showLine: hasOverlayLine,
        spanGaps: true,
      });
    }
    return { labels, datasets };
  }, [hasMainLine, hasOverlay, hasOverlayLine, isPartialCoverage, labels, paidOverlaySeries, series]);

  const barData: ChartData<"bar", number[], string> = useMemo(() => {
    const datasets: ChartData<"bar", number[], string>["datasets"] = [
      {
        label: "Orgânico",
        data: series,
        borderWidth: 1,
        borderRadius: 10,
        maxBarThickness: barMaxThickness,
        borderColor: isPartialCoverage ? CHART_COLORS.organicMuted : CHART_COLORS.organic,
        backgroundColor: CHART_COLORS.organicSoft,
      },
    ];
    if (hasOverlay) {
      datasets.push({
        label: "Ads",
        data: paidOverlaySeries,
        borderWidth: 1,
        borderRadius: 10,
        maxBarThickness: barMaxThickness,
        borderColor: CHART_COLORS.ads,
        backgroundColor: CHART_COLORS.adsSoft,
      });
    }
    return { labels, datasets };
  }, [barMaxThickness, hasOverlay, isPartialCoverage, labels, paidOverlaySeries, series]);

  const hasSeries = series.some((value) => Number.isFinite(value));
  const lineOptions: ChartOptions<"line"> = useMemo(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: "index",
        intersect: false,
      },
      plugins: {
        legend: {
          display: isPrimary && hasOverlay,
          labels: {
            color: CHART_COLORS.axis,
            boxWidth: 12,
            usePointStyle: true,
            pointStyle: "line",
          },
        },
        tooltip: {
          enabled: true,
          backgroundColor: CHART_COLORS.tooltipBg,
          borderColor: CHART_COLORS.tooltipBorder,
          borderWidth: 1,
          titleColor: CHART_COLORS.tooltipText,
          bodyColor: CHART_COLORS.tooltipText,
          padding: 12,
          callbacks: {
            title: (items) => {
              const index = items[0]?.dataIndex ?? 0;
              if (granularity === "weekly") {
                return labels[index] || "";
              }
              if (granularity === "monthly") {
                return `Mês: ${labels[index] || ""}`;
              }
              return `Data: ${formatDatePtBr(pointDates[index] || "")}`;
            },
            label: (item) => {
              const datasetLabel = String(item.dataset.label || title);
              const value = formatFullNumber(item.parsed.y);
              return `${datasetLabel}: ${value} • ${METRIC_CONTEXT[metric]}`;
            },
          },
        },
      },
      scales: {
        x: {
          offset: !hasMainLine,
          grid: { display: false },
          ticks: {
            color: CHART_COLORS.axis,
            autoSkip: hasMainLine,
            maxRotation: 0,
            minRotation: 0,
            maxTicksLimit:
              granularity === "monthly" ? 8 : granularity === "weekly" ? 9 : days <= 15 ? 8 : 10,
            font: { weight: 600 },
          },
        },
        y: {
          beginAtZero: true,
          grace: "8%",
          suggestedMin: 0,
          suggestedMax:
            singlePointValue === null
              ? undefined
              : singlePointValue <= 0
                ? 1
                : Math.max(singlePointValue * 1.12, 1),
          grid: { color: CHART_COLORS.grid },
          ticks: {
            color: CHART_COLORS.axis,
            maxTicksLimit: 6,
            callback: (value) => formatCompactNumber(value),
            font: { weight: 600 },
          },
        },
      },
    }),
    [days, granularity, hasMainLine, hasOverlay, isPrimary, labels, metric, pointDates, singlePointValue, title]
  );
  const barOptions: ChartOptions<"bar"> = useMemo(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: "index",
        intersect: false,
      },
      plugins: {
        legend: {
          display: isPrimary && hasOverlay,
          labels: {
            color: CHART_COLORS.axis,
            boxWidth: 12,
            usePointStyle: true,
            pointStyle: "rectRounded",
          },
        },
        tooltip: {
          enabled: true,
          backgroundColor: CHART_COLORS.tooltipBg,
          borderColor: CHART_COLORS.tooltipBorder,
          borderWidth: 1,
          titleColor: CHART_COLORS.tooltipText,
          bodyColor: CHART_COLORS.tooltipText,
          padding: 12,
          callbacks: {
            title: (items) => {
              const index = items[0]?.dataIndex ?? 0;
              if (granularity === "weekly") {
                return labels[index] || "";
              }
              if (granularity === "monthly") {
                return `Mês: ${labels[index] || ""}`;
              }
              return `Data: ${formatDatePtBr(pointDates[index] || "")}`;
            },
            label: (item) => {
              const datasetLabel = String(item.dataset.label || title);
              const value = formatFullNumber(item.parsed.y);
              return `${datasetLabel}: ${value} • ${METRIC_CONTEXT[metric]}`;
            },
          },
        },
      },
      scales: {
        x: {
          offset: true,
          grid: { display: false },
          ticks: {
            color: CHART_COLORS.axis,
            autoSkip: pointCount > 8,
            maxRotation: 0,
            minRotation: 0,
            maxTicksLimit:
              granularity === "monthly" ? 8 : pointCount > 18 ? 8 : pointCount > 10 ? 7 : 6,
            font: { weight: 600 },
          },
        },
        y: {
          beginAtZero: true,
          grace: "8%",
          suggestedMin: 0,
          suggestedMax:
            singlePointValue === null
              ? undefined
              : singlePointValue <= 0
                ? 1
                : Math.max(singlePointValue * 1.12, 1),
          grid: { color: CHART_COLORS.grid },
          ticks: {
            color: CHART_COLORS.axis,
            maxTicksLimit: 6,
            callback: (value) => formatCompactNumber(value),
            font: { weight: 600 },
          },
        },
      },
    }),
    [granularity, hasOverlay, isPrimary, labels, metric, pointCount, pointDates, singlePointValue, title]
  );

  return (
    <div
      className={`card chartCard ${
        highlighted ? "cardMetricHighlight" : ""
      } ${isPrimary ? "chartCardPrimary" : "chartCardSecondary"} ${isPartialCoverage ? "chartPartial" : ""} ${
        isSinglePoint ? "chartCardSinglePoint" : ""
      } ${useBarChart ? "chartCardFewPoints" : ""} ${usesBarVisualization ? "chartCardBars" : ""}`}
    >
      <div className="cardHead">
        <div>
          <div className="cardTitle">{title}</div>
          <div className="cardSub">
            {isPartialCoverage
              ? `${periodLabel} • ${granularityLabel(granularity)} • leitura parcial`
              : `${periodLabel} • ${granularityLabel(granularity)} • comparado ao período anterior`}
          </div>
        </div>
        <div className="smallMuted chartMetaSummary">{growthSummary}</div>
      </div>

      <div className="cardKpiRow">
        <div>
          <div className="cardValue">{fmt(periodTotal)}</div>
          <div className="cardHint">
            {lastPointLabel}: <b>{fmt(todayValue)}</b>
          </div>
        </div>
      </div>

      {isSinglePoint ? (
        <div className="chartSinglePointState">
          <div className="chartSinglePointRow">
            <span className="smallMuted">Período</span>
            <strong>{periodLabel}</strong>
          </div>
          <div className="chartSinglePointRow">
            <span className="smallMuted">Comparação</span>
            <strong>{comparisonText}</strong>
          </div>
          {isPartialCoverage ? <div className="smallMuted">{partialCoverageText || "Dados parciais"}</div> : null}
        </div>
      ) : (
        <div className="cardChart">
          {hasSeries ? (
            usesBarVisualization ? (
              <Bar data={barData} options={barOptions} />
            ) : useLineChart ? (
              <Line data={lineData} options={lineOptions} />
            ) : null
          ) : (
            <div className="chartEmptyState">
              <div className="smallMuted">Sem dados ainda para esse gráfico.</div>
              <div className="smallMuted">Aguardando sincronização do período selecionado.</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function isCurrentMonthRange(start: string, end: string): boolean {
  const startDate = new Date(`${String(start || "").trim()}T00:00:00`);
  const endDate = new Date(`${String(end || "").trim()}T00:00:00`);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return false;
  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
  return (
    startDate.getFullYear() === monthStart.getFullYear() &&
    startDate.getMonth() === monthStart.getMonth() &&
    startDate.getDate() === 1 &&
    endDate.getFullYear() === now.getFullYear() &&
    endDate.getMonth() === now.getMonth() &&
    endDate.getDate() === now.getDate()
  );
}

function isWholeMonthRange(start: string, end: string): boolean {
  const startDate = new Date(`${String(start || "").trim()}T00:00:00`);
  const endDate = new Date(`${String(end || "").trim()}T00:00:00`);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return false;
  if (startDate.getFullYear() !== endDate.getFullYear()) return false;
  if (startDate.getMonth() !== endDate.getMonth()) return false;
  if (startDate.getDate() !== 1) return false;
  const lastDay = new Date(startDate.getFullYear(), startDate.getMonth() + 1, 0).getDate();
  return endDate.getDate() === lastDay;
}

function formatPeriodLabel(start: string, end: string): string {
  const startDate = new Date(`${String(start || "").trim()}T00:00:00`);
  const endDate = new Date(`${String(end || "").trim()}T00:00:00`);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return "Período personalizado";
  if (isCurrentMonthRange(start, end)) return "Mês atual";
  const format = (value: Date) =>
    value.toLocaleDateString("pt-BR", {
      day: "2-digit",
      month: "2-digit",
    });
  return `${format(startDate)} - ${format(endDate)}`;
}

function periodPresetFromRange(start: string, end: string): "7d" | "30d" | "month" | "custom" {
  if (isCurrentMonthRange(start, end)) return "month";
  const startDate = new Date(`${String(start || "").trim()}T00:00:00`);
  const endDate = new Date(`${String(end || "").trim()}T00:00:00`);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return "custom";
  const diff = Math.floor((endDate.getTime() - startDate.getTime()) / 86_400_000) + 1;
  if (diff === 7) return "7d";
  if (diff === 30) return "30d";
  return "custom";
}

function metricFromKpi(kpi: KpiKey): MetaMetricKey {
  return META_METRIC_BY_KPI[kpi] || "impressions";
}

const MONTHS_PT = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
function pad2(n: number) {
  return String(n).padStart(2, "0");
}
function monthLabelPt(monthKey: string) {
  const [y, m] = monthKey.split("-");
  const idx = Math.max(0, Math.min(11, Number(m) - 1));
  return `${MONTHS_PT[idx]} ${y}`;
}

function monthKeyFromIsoDate(value: string): string {
  const text = String(value || "").trim();
  if (/^\d{4}-\d{2}/.test(text)) return text.slice(0, 7);
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return "";
  return `${parsed.getUTCFullYear()}-${pad2(parsed.getUTCMonth() + 1)}`;
}

type MonthAggRow = ReturnType<typeof buildMonthAgg>[number];

function makeEmptyMonthAgg(month: string): MonthAggRow {
  return {
    month,
    posts: 0,
    reels: 0,
    reach: 0,
    views: 0,
    interactions: 0,
    profile_visits: 0,
    likes: 0,
    comments: 0,
    shares: 0,
    saved: 0,
    avg_watch_ms: 0,
    skip_rate_avg: 0,
  };
}

const pickDefaultConnectionId = (connections: MetaConnection[], preferredConnectionId: string | null) =>
  resolveOperationalMetaConnectionId(connections, "organic", preferredConnectionId);

const pickSelectedPaidConnectionId = (connections: MetaConnection[], selectedConnectionId: string | null) =>
  resolveOperationalMetaConnectionId(connections, "paid", selectedConnectionId);

type DashboardProps = {
  onLogout?: () => Promise<void> | void;
  isAuthenticated?: boolean;
  bootstrapError?: string | null;
  onOpenSetup?: () => void;
  onOpenGoogleAnalytics?: () => void;
};

export default function Dashboard({
  onLogout,
  isAuthenticated = false,
  bootstrapError,
  onOpenSetup,
  onOpenGoogleAnalytics,
}: DashboardProps) {
  const [syncing, setSyncing] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const {
    period: periodState,
    setPresetPeriod,
    setCurrentMonthPeriod,
    setMonthPeriod,
    periodDays,
  } = usePeriod();
  const period = getSelectedPeriodRange(ensureDashboardPeriod(periodState));
  const rangeDays = periodDays;
  const [activeMetric, setActiveMetric] = useState<MetaMetricKey>(metricFromKpi("reach"));
  const [chartGranularity, setChartGranularity] = useState<ChartGranularity>("monthly");
  const [paidCampaignFilter, setPaidCampaignFilter] = useState("");
  const [paidAdsetFilter, setPaidAdsetFilter] = useState("");
  const [paidAdFilter, setPaidAdFilter] = useState("");
  const [paidPlatformFilter, setPaidPlatformFilter] = useState("");
  const [monthA, setMonthA] = useState<string>("");
  const [monthB, setMonthB] = useState<string>("");
  const activeClientId = getActiveClientId();
  const connectionsCacheKey = useMemo(
    () =>
      buildDashboardCacheKey("meta-connections", {
        clientId: activeClientId,
        extra: "dashboard",
      }),
    [activeClientId]
  );
  const [availableMonths, setAvailableMonths] = useState<string[]>([]);
  const [notes, setNotes] = useState<NoteItem[]>([]);
  const [loadingNotes, setLoadingNotes] = useState(false);
  const [notesAvailable, setNotesAvailable] = useState(true);
  const [notesMessage, setNotesMessage] = useState<string | null>(null);
  const [notesError, setNotesError] = useState<string | null>(null);
  // Estado inicial lido de forma síncrona do cache (sessionStorage/memória),
  // não via useEffect: ao trocar de tela e voltar (remount), o componente
  // volta a montar com connections=[] por um frame se o valor inicial for
  // vazio, apagando temporariamente KPIs orgânicos e o dashboard pago
  // mesmo com dado válido em cache — este era um ponto real de "dado some
  // ao trocar de tela".
  const paidConnectionIdCacheKey = useMemo(
    () => buildDashboardCacheKey("meta-paid-connection-id", { clientId: activeClientId, extra: "dashboard" }),
    [activeClientId]
  );
  const cachedConnectionsInitial = useMemo(
    () => readDashboardCache<MetaConnection[]>(connectionsCacheKey) || [],
    [connectionsCacheKey]
  );
  const [hasActiveConnection, setHasActiveConnection] = useState<boolean | null>(() =>
    cachedConnectionsInitial.length
      ? Boolean(pickDefaultConnectionId(cachedConnectionsInitial, getActiveConnectionId()))
      : null
  );
  const [connections, setConnections] = useState<MetaConnection[]>(cachedConnectionsInitial);
  const [commerceConnection, setCommerceConnection] = useState<GenericConnection | null>(null);
  const [selectedPaidConnectionId, setSelectedPaidConnectionId] = useState<string | null>(() =>
    readDashboardCache<string>(paidConnectionIdCacheKey)
  );
  const [refreshRuntime, setRefreshRuntime] = useState<Array<Record<string, unknown>>>([]);
  const [activeConnectionId, setActiveConnection] = useState<string | null>(() =>
    cachedConnectionsInitial.length ? pickDefaultConnectionId(cachedConnectionsInitial, getActiveConnectionId()) : null
  );
  // Leituras persistidas de Ads e do executivo começam junto com o orgânico.
  // Nenhuma delas chama upstream; postergar esta etapa fazia Shopify/Meta
  // parecerem ausentes enquanto Instagram ainda carregava.
  const [enablePaidStage, setEnablePaidStage] = useState(true);
  const [enableMonthlyStage, setEnableMonthlyStage] = useState(false);
  const [enableExtrasStage, setEnableExtrasStage] = useState(false);
  const organicConnectionId = String(activeConnectionId || "").trim() || null;
  const monthsCacheKey = useMemo(
    () =>
      buildDashboardCacheKey("meta-months", {
        clientId: activeClientId,
        connectionId: organicConnectionId || "-",
        extra: "available",
      }),
    [activeClientId, organicConnectionId]
  );
  const notesCacheKey = useMemo(
    () =>
      buildDashboardCacheKey("meta-notes", {
        clientId: activeClientId,
        connectionId: organicConnectionId || "-",
        extra: "list",
      }),
    [activeClientId, organicConnectionId]
  );
  const paidConnectionId = useMemo(
    () => pickSelectedPaidConnectionId(connections, selectedPaidConnectionId),
    [connections, selectedPaidConnectionId]
  );

  const {
    data: summaryData,
    refreshingSummary,
    sectionLoading,
    sectionRefreshing,
    sectionErrors,
    sectionUpdatedAt,
  } = useDashboardSummary({
    isAuthenticated,
    activeClientId,
    activeConnectionId: organicConnectionId,
    secondaryEnabled: enableExtrasStage,
    autoLoadStories: false,
    period,
  });
  
  const dash = (summaryData.dash as DashboardResponse | null) || null;
  const mediaData = summaryData.media;
  const comments = summaryData.comments;
  const commentsTotal = safe(summaryData.commentsTotal);
  const topWords = summaryData.topWords;
  
  const loadingDash = sectionLoading.dash;
  const loadingMedia = sectionLoading.media;
  const loadingComments = sectionLoading.comments;
  const refreshingDash = sectionRefreshing.dash || (refreshingSummary && !!dash);
  const refreshingMedia = sectionRefreshing.media || (refreshingSummary && mediaData.length > 0);
  const refreshingComments = sectionRefreshing.comments || (refreshingSummary && comments.length > 0);
  
  const dashError = sectionErrors.dash;
  const mediaError = sectionErrors.media;
  const commentsError = sectionErrors.comments;
  const summarySettled = Boolean(dash) || Boolean(dashError);
  
  const mediaHasMore = false;
  const commentsHasMore = false;
  const hasSummaryOrganicData =
    mediaData.length > 0 ||
    comments.length > 0 ||
    commentsTotal > 0 ||
    safe(dash?.period_totals?.followers_current) > 0;
  const {
    monthlyRows,
    loadingMonthly,
    refreshingMonthly,
    monthlyError,
    monthlyUpdatedAt,
  } = useDashboardMonthlyContent({
    isAuthenticated,
    activeClientId,
    activeConnectionId: organicConnectionId,
    enabled: enableMonthlyStage,
    period,
  });
  const {
    paidData,
    loadingPaid,
    refreshingPaid,
    paidError,
    paidUpdatedAt,
  } = useDashboardPaid({
    isAuthenticated,
    activeClientId,
    activeConnectionId: paidConnectionId,
    enabled: enablePaidStage,
    period,
    filters: {
      campaign: paidCampaignFilter,
      adset: paidAdsetFilter,
      ad: paidAdFilter,
      platform: paidPlatformFilter,
    },
  });
  // Janela imediatamente anterior de mesma duração — única fonte usada para
  // a narrativa "+X% vs período anterior" do hero de mídia paga. Reaproveita
  // o mesmo hook/cache/endpoint já usado para o período atual; nunca inventa
  // comparação quando essa segunda leitura ainda não chegou.
  const previousPaidPeriod = useMemo(() => previousDashboardPeriod(period), [period]);
  const { paidData: previousPaidData } = useDashboardPaid({
    isAuthenticated,
    activeClientId,
    activeConnectionId: paidConnectionId,
    enabled: enablePaidStage,
    period: previousPaidPeriod,
    filters: {
      campaign: paidCampaignFilter,
      adset: paidAdsetFilter,
      ad: paidAdFilter,
      platform: paidPlatformFilter,
    },
  });
  const {
    executiveData,
    executiveError,
  } = useExecutiveDashboard({
    isAuthenticated,
    activeClientId,
    enabled: enablePaidStage,
    period,
  });
  const {
    campaignsData,
    loadingCampaigns,
    campaignsError,
  } = useCampaignsRanking({
    isAuthenticated,
    activeClientId,
    activeConnectionId: paidConnectionId,
    enabled: enablePaidStage,
    period,
  });
  const secondaryOrganicLoading =
    !enableExtrasStage &&
    !mediaData.length &&
    !comments.length &&
    (loadingDash || refreshingDash || summarySettled);
  const paidPanelLoading = loadingPaid || (!enablePaidStage && !paidData);
  const dashboardSnapshot = useDashboardSnapshot();
  const onLogoutClick = useCallback(async () => {
    if (onLogout) {
      await onLogout();
      return;
    }
  }, [onLogout]);

  const onSelectPeriodPreset = useCallback(
    (preset: "7d" | "30d" | "month") => {
      if (preset === "7d") {
        setPresetPeriod(7);
        return;
      }
      if (preset === "30d") {
        setPresetPeriod(30);
        return;
      }
      setCurrentMonthPeriod();
    },
    [setCurrentMonthPeriod, setPresetPeriod]
  );

  useEffect(() => {
    // Meta Ads persistido deve carregar mesmo quando o orgânico ainda não foi configurado.
    if (summarySettled || hasActiveConnection === false) {
      setEnablePaidStage(true);
    }
  }, [hasActiveConnection, summarySettled]);

  useEffect(() => {
    if (!enablePaidStage) return;
    if (!paidConnectionId || paidData || paidError) {
      setEnableMonthlyStage(true);
    }
  }, [enablePaidStage, paidConnectionId, paidData, paidError]);

  useEffect(() => {
    if (!enableMonthlyStage) return;
    if (!organicConnectionId || monthlyRows.length || monthlyError || monthlyUpdatedAt) {
      setEnableExtrasStage(true);
    }
  }, [enableMonthlyStage, organicConnectionId, monthlyRows.length, monthlyError, monthlyUpdatedAt]);

  const loadNotesData = useCallback(async (options?: { force?: boolean }) => {
    if (!isAuthenticated || !activeClientId) {
      setNotes([]);
      setNotesAvailable(true);
      setNotesMessage(null);
      setNotesError(null);
      return;
    }
    if (!organicConnectionId) {
      setNotes([]);
      setNotesAvailable(true);
      setNotesMessage(null);
      setNotesError(null);
      return;
    }
    const force = !!options?.force;
    const cached = !force ? readDashboardCache<NotesCachePayload>(notesCacheKey) : null;
    if (cached) {
      setLoadingNotes(false);
      startTransition(() => {
        setNotes(arrayOrEmpty<NoteItem>(cached.notes));
        setNotesAvailable(cached.available !== false);
        setNotesMessage(cached.message || null);
        setNotesError(null);
      });
      return;
    }
    setLoadingNotes(true);
    try {
      const res = await listNotes({ limit: 80, connectionId: organicConnectionId });
      const nextNotes = arrayOrEmpty<NoteItem>(res.notes);
      const nextAvailable = res.available !== false;
      const nextMessage =
        typeof res.message === "string" && res.message.trim() ? res.message : null;
      dashLog("loadNotesData", { notes: nextNotes.length });
      startTransition(() => {
        setNotes(nextNotes);
        setNotesAvailable(nextAvailable);
        setNotesMessage(nextMessage);
        setNotesError(null);
      });
      writeDashboardCache<NotesCachePayload>(
        notesCacheKey,
        {
          notes: nextNotes,
          available: nextAvailable,
          message: nextMessage,
        },
        300_000
      );
    } catch (error: unknown) {
      const message = errorMessage(error, "Erro ao carregar notas");
      dashLog("loadNotesData:error", { message });
      startTransition(() => {
        setNotesAvailable(false);
        setNotesMessage("Notas indisponíveis no momento.");
        setNotesError(message);
      });
    } finally {
      setLoadingNotes(false);
    }
  }, [activeClientId, isAuthenticated, notesCacheKey, organicConnectionId]);

  const loadAvailableMonths = useCallback(async (options?: { force?: boolean }): Promise<string[]> => {
    if (!isAuthenticated || !activeClientId) {
      setAvailableMonths([]);
      return [];
    }
    if (!organicConnectionId) {
      setAvailableMonths([]);
      return [];
    }
    const force = !!options?.force;
    const cached = !force ? readDashboardCache<string[]>(monthsCacheKey) : null;
    if (cached) {
      const nextMonths = arrayOrEmpty<string>(cached);
      startTransition(() => {
        setAvailableMonths(nextMonths);
      });
      return nextMonths;
    }
    try {
      const res = await listMonthsByConnection({ connectionId: organicConnectionId });
      const rows = arrayOrEmpty<string>(res.months);
      const normalized = rows
        .map((value) => String(value || "").trim())
        .filter((value) => /^\d{4}-\d{2}$/.test(value))
        .sort();
      startTransition(() => {
        setAvailableMonths(normalized);
      });
      writeDashboardCache<string[]>(monthsCacheKey, normalized, 300_000);
      dashLog("loadAvailableMonths", { count: normalized.length });
      return normalized;
    } catch (error: unknown) {
      setAvailableMonths([]);
      dashLog("loadAvailableMonths:error", { message: errorMessage(error, "failed") });
      return [];
    }
  }, [activeClientId, isAuthenticated, monthsCacheKey, organicConnectionId]);

  const handleCreateNote = useCallback(async (): Promise<NoteItem | null> => {
    const res = await createNote({ title: "Nova nota", body: "" });
    const created = res.note;
    setNotes((prev) => {
      const nextNotes = [created, ...prev.filter((n) => n.id !== created.id)];
      writeDashboardCache<NotesCachePayload>(
        notesCacheKey,
        {
          notes: nextNotes,
          available: true,
          message: null,
        },
        300_000
      );
      return nextNotes;
    });
    return created;
  }, [notesCacheKey]);

  const handleUpdateNote = useCallback(
    async (noteId: string, patch: { title?: string; body?: string }) => {
      const res = await updateNote(noteId, patch);
      const updated = res.note;
      setNotes((prev) => {
        const nextNotes = prev.map((n) => (n.id === updated.id ? updated : n));
        writeDashboardCache<NotesCachePayload>(
          notesCacheKey,
          {
            notes: nextNotes,
            available: true,
            message: null,
          },
          300_000
        );
        return nextNotes;
      });
    },
    [notesCacheKey]
  );

  useEffect(() => {
    if (!isAuthenticated || !activeClientId || !organicConnectionId) {
      setAvailableMonths([]);
      return;
    }
    if (!enableExtrasStage) return;
    void loadAvailableMonths();
  }, [enableExtrasStage, isAuthenticated, activeClientId, organicConnectionId, loadAvailableMonths]);

  useEffect(() => {
    if (!isAuthenticated || !activeClientId || !organicConnectionId) {
      setNotes([]);
      setNotesAvailable(true);
      setNotesMessage(null);
      setNotesError(null);
      return;
    }
    if (!SHOW_PRESENTATION_EXTRAS) return;
    if (!enableExtrasStage) return;
    void loadNotesData();
  }, [enableExtrasStage, isAuthenticated, activeClientId, organicConnectionId, loadNotesData]);

  useEffect(() => {
    if (!isAuthenticated || !activeClientId) {
      setHasActiveConnection(null);
      setConnections([]);
      setCommerceConnection(null);
      setActiveConnection(null);
      return;
    }

    // Conexões são configuração administrativa e não participam do first paint.
    // A descoberta necessária ao sync manual acontece somente em onRefresh.
    if (!SHOW_PRESENTATION_EXTRAS) {
      setEnablePaidStage(true);
      setEnableMonthlyStage(true);
      setEnableExtrasStage(false);
      return;
    }

    let alive = true;
    const cachedConnections = readDashboardCache<MetaConnection[]>(connectionsCacheKey);
    if (cachedConnections?.length) {
      const nextConnections = arrayOrEmpty<MetaConnection>(cachedConnections);
      setConnections(nextConnections);
      const preferredConnectionId = getActiveConnectionId();
      const nextActiveConnectionId = pickDefaultConnectionId(
        nextConnections,
        preferredConnectionId
      );
      setActiveConnection(nextActiveConnectionId);
      setHasActiveConnection(Boolean(nextActiveConnectionId));
    }

    Promise.allSettled([listClientConnections(), listGenericConnections()])
      .then(([metaResult, genericResult]) => {
        if (!alive) return;
        if (genericResult.status === "fulfilled") {
          const commerceId = getSelectedConnectionId(activeClientId, "shopify") ||
            getSelectedConnectionId(activeClientId, "fbits");
          const commerce = resolveCommerceConnection(genericResult.value.connections, commerceId);
          setCommerceConnection(commerce || null);
        }
        if (metaResult.status === "rejected") {
          if (!cachedConnections?.length) {
            setHasActiveConnection(null);
            setConnections([]);
            setActiveConnection(null);
          }
          return;
        }
        const response = metaResult.value;
        const nextConnections = arrayOrEmpty<MetaConnection>(response.connections);
        if (genericResult.status === "fulfilled") {
          const selectedMetaAuthorizationId = getSelectedConnectionId(activeClientId, "meta");
          const selectedMetaAuthorization = selectUniqueConnection(
            genericResult.value.connections,
            (item) => item.id === selectedMetaAuthorizationId && item.client_id === activeClientId && item.provider === "meta"
          );
          const selectedAdAccountId = String(selectedMetaAuthorization?.metadata?.selected_ad_account_id || "");
          const paid = selectUniqueConnection(nextConnections, (item) =>
            String(item.ad_account_id || "") === selectedAdAccountId && String(item.status || "").toLowerCase() !== "disconnected"
          );
          const paidCandidates = nextConnections.filter((item) =>
            String(item.platform || "").toLowerCase() === "meta_ads" &&
            String(item.connection_type || "").toLowerCase() === "paid" &&
            String(item.status || "").toLowerCase() !== "disconnected" &&
            item.requires_reauth !== true
          );
          // Se o ponteiro salvo (autorização em cache -> ad_account_id) não
          // encontrou correspondência, mas existe exatamente UMA conexão paid
          // ativa, usá-la evita exibir zero/dado antigo de uma conta que
          // permanece conectada — a ambiguidade real (>1 conta) continua
          // exigindo seleção explícita do usuário.
          const paidFallbackId = !paid && paidCandidates.length === 1 ? paidCandidates[0].id : null;
          const nextPaidConnectionId = String(paid?.id || paidFallbackId || "") || null;
          setSelectedPaidConnectionId(nextPaidConnectionId);
          writeDashboardCache<string | null>(paidConnectionIdCacheKey, nextPaidConnectionId, 300_000);
        } else {
          setSelectedPaidConnectionId(null);
        }
        writeDashboardCache<MetaConnection[]>(connectionsCacheKey, nextConnections, 300_000);
        setConnections(nextConnections);

        const preferredConnectionId = getActiveConnectionId();
        const nextActiveConnectionId = pickDefaultConnectionId(
          nextConnections,
          preferredConnectionId
        );
        setActiveConnection(nextActiveConnectionId);

        setHasActiveConnection(Boolean(nextActiveConnectionId));
      })
      .catch(() => {
        if (!alive) return;
        if (!cachedConnections?.length) {
          setHasActiveConnection(null);
          setConnections([]);
          setActiveConnection(null);
        }
      });

    return () => {
      alive = false;
    };
  }, [activeClientId, connectionsCacheKey, paidConnectionIdCacheKey, isAuthenticated]);

  async function onRefresh() {
    if (!activeClientId) {
      setErr("Client_id do cliente ativo não configurado para atualização.");
      return;
    }
    setErr(null);
    setSyncing(true);
    const startedAt = new Date().toISOString();
    let metaConnections: MetaConnection[] = [];
    let genericConnections: GenericConnection[] = [];
    try {
      const [metaResult, genericResult] = await Promise.all([
        listClientConnections(),
        listGenericConnections(),
      ]);
      metaConnections = arrayOrEmpty<MetaConnection>(metaResult.connections);
      genericConnections = arrayOrEmpty<GenericConnection>(genericResult.connections);
    } catch (connectionError: unknown) {
      setErr(describeSyncError(connectionError, "Não foi possível preparar a atualização agora."));
      setSyncing(false);
      return;
    }
    const refreshOrganicConnectionId = resolveOperationalMetaConnectionId(
      metaConnections, "organic", organicConnectionId || getActiveConnectionId()
    );
    const paidCandidates = metaConnections.filter((item) =>
      String(item.platform || "").toLowerCase() === "meta_ads" &&
      String(item.connection_type || "").toLowerCase() === "paid" &&
      String(item.status || "").toLowerCase() !== "disconnected" &&
      item.requires_reauth !== true
    );
    const refreshPaidConnectionId = paidCandidates.some((item) => item.id === paidConnectionId)
      ? paidConnectionId
      : paidCandidates.length === 1 ? paidCandidates[0].id : null;
    const shopifyConnection = resolveCommerceConnection(
      genericConnections.filter((item) => item.provider === "shopify"),
      getSelectedConnectionId(activeClientId, "shopify")
    );
    const ga4Connection = selectUsableGoogleConnection(
      genericConnections, "ga4", activeClientId, getSelectedConnectionId(activeClientId, "ga4")
    );
    const googleAdsConnection = selectUsableGoogleConnection(
      genericConnections, "google_ads", activeClientId, getSelectedConnectionId(activeClientId, "google_ads")
    );
    const refreshDays = Math.max(
      1,
      Math.round((Date.parse(period.end) - Date.parse(period.start)) / 86_400_000) + 1
    );
    const syncTasks: Array<{ provider: string; connectionId: string; endpoint: string; promise: Promise<unknown> }> = [];
    if (refreshOrganicConnectionId) {
      syncTasks.push({
        provider: "meta_organic", connectionId: refreshOrganicConnectionId,
        endpoint: "/api/ig/refresh_all",
        promise: runExclusiveSync(
          { clientId: activeClientId, provider: "meta_organic", connectionId: refreshOrganicConnectionId },
          () =>
            refreshAll(200, {
              connectionId: refreshOrganicConnectionId,
              start: period.start,
              end: period.end,
            })
        ),
      });
    } else {
      dashLog("onRefresh:refreshAll:skip", {
        reason: "missing_organic_connection",
      });
    }
    if (refreshPaidConnectionId) {
      syncTasks.push({
        provider: "meta_ads", connectionId: refreshPaidConnectionId,
        endpoint: "/api/ads/sync",
        promise: runExclusiveSync(
          { clientId: activeClientId, provider: "meta_ads", connectionId: refreshPaidConnectionId },
          () =>
            syncAds(
              {
                start: period.start,
                end: period.end,
              },
              {
                connectionId: refreshPaidConnectionId,
                clientId: activeClientId,
              }
            )
        ),
      });
    }
    if (shopifyConnection) {
      syncTasks.push({
        provider: "shopify", connectionId: shopifyConnection.id,
        endpoint: `/api/oauth/shopify/${shopifyConnection.id}/sync`,
        promise: runExclusiveSync(
          { clientId: activeClientId, provider: "shopify", connectionId: shopifyConnection.id },
          () => syncShopifyConnection(shopifyConnection.id, refreshDays)
        ),
      });
    }
    if (ga4Connection) {
      syncTasks.push({
        provider: "ga4", connectionId: ga4Connection.id,
        endpoint: "/api/google/ga4/sync",
        promise: runExclusiveSync(
          { clientId: activeClientId, provider: "ga4", connectionId: ga4Connection.id },
          () => syncGa4(period, { clientId: activeClientId, connectionId: ga4Connection.id })
        ),
      });
    }
    if (googleAdsConnection) {
      syncTasks.push({
        provider: "google_ads", connectionId: googleAdsConnection.id,
        endpoint: `/api/oauth/google/${googleAdsConnection.id}/sync`,
        promise: runExclusiveSync(
          { clientId: activeClientId, provider: "google_ads", connectionId: googleAdsConnection.id },
          () => syncGoogleConnection(googleAdsConnection.id)
        ),
      });
    }
    if (!syncTasks.length) {
      setErr("Nenhuma fonte configurada para atualização.");
      setRefreshRuntime([{
        tenant: activeClientId, status: "blocked", code: "CONNECTION_SELECTION_REQUIRED",
        started_at: startedAt, finished_at: new Date().toISOString(), rows_written: 0,
      }]);
      setSyncing(false);
      return;
    }
    setRefreshRuntime(syncTasks.map((task) => ({
      tenant: activeClientId, provider: task.provider, connection_id: task.connectionId,
      endpoint: task.endpoint, status: "running", code: "-", request_id: "-",
      started_at: startedAt, finished_at: "-", rows_written: 0,
    })));
    try {
      const syncResults = await Promise.allSettled(syncTasks.map((task) => task.promise));
      const runtime = syncResults.map((result, index) => {
        const task = syncTasks[index];
        const value = result.status === "fulfilled" && result.value && typeof result.value === "object"
          ? result.value as Record<string, unknown> : {};
        const failure = result.status === "rejected" ? result.reason : null;
        return {
          tenant: activeClientId, provider: task.provider, connection_id: task.connectionId,
          endpoint: task.endpoint, status: result.status,
          code: failure instanceof ApiError ? failure.code : String(value.code || "OK"),
          request_id: failure instanceof ApiError ? failure.requestId : String(value.request_id || ""),
          started_at: startedAt, finished_at: new Date().toISOString(),
          rows_written: Number(value.rows_written || value.saved_count || value.comments_saved || 0),
        };
      });
      setRefreshRuntime(runtime);
      const organicIndex = syncTasks.findIndex((task) => task.provider === "meta_organic");
      const organicSync = organicIndex >= 0 ? syncResults[organicIndex] : null;
      if (organicSync?.status === "fulfilled") {
        const res = organicSync.value as RefreshAllResponse;
        dashLog("onRefresh:refreshAll", {
          ok: !!res.ok,
          media: (res.media || []).length,
          comments_saved: res.comments_saved || 0,
          warnings: res.warnings || [],
          block_status: res.block_status || {},
        });
        if (!res.ok) {
          const warning = Array.isArray(res.warnings) ? String(res.warnings[0] || "").trim() : "";
          setErr(warning || "Atualização orgânica finalizada com alertas.");
        }
      }
      const rejectedSync = syncResults.find((result) => result.status === "rejected");
      if (rejectedSync?.status === "rejected") {
        dashLog("onRefresh:sync:error", {
          message: errorMessage(rejectedSync.reason, "failed"),
        });
        const failure = rejectedSync.reason;
        setErr(describeSyncError(
          failure,
          errorMessage(failure, "Falha parcial ao atualizar. Mantendo a última leitura disponível.")
        ));
      }
      await dashboardSnapshot.refetch();
      setConnections(metaConnections);
      setCommerceConnection(shopifyConnection || null);
      writeDashboardCache<MetaConnection[]>(connectionsCacheKey, metaConnections, 300_000);
    } catch (error: unknown) {
      setErr(errorMessage(error, "Erro ao atualizar dados"));
    } finally {
      setSyncing(false);
    }
  }

  const hasDash = !!dash?.ok;

  const configWarning = getActiveClientConfigurationWarning();
  const themeClass = "theme-client";

  const periodTotals = dash?.period_totals;
  const daily = dash?.daily || [];
  const currentFollowers =
    typeof periodTotals?.followers_current === "number"
      ? safe(periodTotals.followers_current)
      : daily.length && typeof daily[daily.length - 1]?.followers === "number"
        ? safe(daily[daily.length - 1].followers)
        : 0;
  const kpisFromDash = useMemo<Record<string, number>>(
    () => ({
      reach: safe(periodTotals?.reach),
      profile_views: safe(periodTotals?.profile_views),
      website_clicks: safe(periodTotals?.website_clicks),
      accounts_engaged: safe(periodTotals?.accounts_engaged),
      total_interactions: safe(periodTotals?.total_interactions) || safe(periodTotals?.accounts_engaged),
      impressions: safe(periodTotals?.impressions),
      followers: currentFollowers,
    }),
    [currentFollowers, periodTotals]
  );

  const paidTotals = paidData?.totals;
  const hasPaidConnection = Boolean(paidData?.connection_id || paidConnectionId);
  const organicConnection = useMemo(
    () => selectUniqueConnection(
      arrayOrEmpty<MetaConnection>(connections),
      (connection) => connection.id === organicConnectionId
    ),
    [connections, organicConnectionId]
  );
  const paidConnection = useMemo(
    () => selectUniqueConnection(
      arrayOrEmpty<MetaConnection>(connections),
      (connection) => connection.id === paidConnectionId
    ),
    [connections, paidConnectionId]
  );
  const paidConnectionStatus = String(paidConnection?.status || "").toLowerCase();
  const paidSyncStatus = String(paidConnection?.last_sync_status || "never").toLowerCase();
  const organicLastUpdatedLabel =
    formatUpdatedAtLabel(sectionUpdatedAt.dash) ||
    formatUpdatedAtLabel(organicConnection?.last_synced_at || organicConnection?.last_sync_at);
  const paidLastUpdatedLabel =
    ["success", "partial"].includes(paidSyncStatus)
      ? formatUpdatedAtLabel(paidConnection?.last_synced_at || paidConnection?.last_sync_at) ||
        formatUpdatedAtLabel(paidUpdatedAt)
      : "";
  const mediaLastUpdatedLabel =
    formatUpdatedAtLabel(sectionUpdatedAt.media) ||
    formatUpdatedAtLabel(organicConnection?.last_synced_at || organicConnection?.last_sync_at);
  const commentsLastUpdatedLabel =
    formatUpdatedAtLabel(sectionUpdatedAt.comments) ||
    formatUpdatedAtLabel(organicConnection?.last_synced_at || organicConnection?.last_sync_at);
  const monthlyLastUpdatedLabel =
    formatUpdatedAtLabel(monthlyUpdatedAt) ||
    formatUpdatedAtLabel(organicConnection?.last_synced_at || organicConnection?.last_sync_at);
  const paidRowCount = safe(paidData?.row_count);
  const paidSourceRows = safe(paidData?.sources?.rows?.aggregated_rows);
  const paidHasRows = paidRowCount > 0 || paidSourceRows > 0;
  const hasPaidData =
    safe(paidTotals?.spend) > 0 ||
    safe(paidTotals?.impressions) > 0 ||
    safe(paidTotals?.clicks) > 0;
  const paidStatusLabel = !hasPaidConnection
    ? "Sem conexão de Ads"
    : paidConnectionStatus === "needs_reauth" || paidConnection?.requires_reauth === true
      ? "Conexão de Ads com erro"
    : loadingPaid
      ? "Carregando Ads"
      : refreshingPaid
        ? "Atualizando Ads"
      : paidSyncStatus === "skipped"
        ? "Ads sem dados no período"
      : paidSyncStatus === "partial"
        ? "Ads com dados parciais"
      : hasPaidData
        ? "Ads com dados"
        : paidHasRows
          ? "Ads sem gasto"
          : "Aguardando atualização";
  const paidEmptyMessage = !hasPaidConnection
    ? "Sem conexão de Ads ativa para o cliente ativo."
    : paidConnectionStatus === "needs_reauth" || paidConnection?.requires_reauth === true
      ? "A conexão de Ads precisa de atenção antes da próxima sincronização."
      : loadingPaid
        ? "Carregando dados de Ads..."
        : refreshingPaid
          ? "Atualizando dados de Ads em background..."
        : paidSyncStatus === "skipped"
          ? paidConnection?.last_error || "A Meta retornou zero agregados para o período."
        : paidSyncStatus === "partial"
          ? paidConnection?.last_error || "A importação foi concluída parcialmente."
        : paidError
          ? "A leitura de Meta Ads não ficou disponível agora."
        : paidHasRows
          ? "Conexão ativa, sem gasto no período selecionado."
          : "Meta Ads conectado, sem campanhas no período.";
  const paidTopCreatives = useMemo(
    () => {
      const campaignNeedle = paidCampaignFilter.trim().toLowerCase();
      const adsetNeedle = paidAdsetFilter.trim().toLowerCase();
      const adNeedle = paidAdFilter.trim().toLowerCase();
      const platformNeedle = paidPlatformFilter.trim().toLowerCase();
      return (Array.isArray(paidData?.top_creatives) ? paidData.top_creatives : []).filter((creative) => (
        (!campaignNeedle || String(creative.campaign_name || "").toLowerCase().includes(campaignNeedle)) &&
        (!adsetNeedle || `${creative.adset_name || ""} ${creative.adset_id || ""}`.toLowerCase().includes(adsetNeedle)) &&
        (!adNeedle || `${creative.ad_name || ""} ${creative.ad_id || ""}`.toLowerCase().includes(adNeedle)) &&
        (!platformNeedle || String(creative.source_platform || "").toLowerCase().includes(platformNeedle))
      ));
    },
    [paidAdFilter, paidAdsetFilter, paidCampaignFilter, paidData, paidPlatformFilter]
  );
  const paidFilterRows = useMemo(
    () => Array.isArray(paidData?.top_creatives) ? paidData.top_creatives : [],
    [paidData]
  );
  const paidFilterOptions = useMemo(() => {
    const unique = (values: Array<string | null | undefined>) =>
      Array.from(new Set(values.map((value) => String(value || "").trim()).filter(Boolean))).sort((left, right) =>
        left.localeCompare(right, "pt-BR")
      );
    return {
      campaigns: unique(paidFilterRows.map((row) => row.campaign_name)),
      adsets: unique(paidFilterRows.flatMap((row) => [row.adset_name, row.adset_id])),
      ads: unique(paidFilterRows.flatMap((row) => [row.ad_name, row.ad_id])),
      platforms: unique(paidFilterRows.map((row) => row.source_platform)),
    };
  }, [paidFilterRows]);
  const paidManagerMetrics = paidData?.manager_metrics;
  const paidDateRangeLabel = useMemo(() => {
    const since = String(paidData?.date_range?.since || paidData?.first_stat_date || "").trim();
    const until = String(paidData?.date_range?.until || paidData?.last_stat_date || "").trim();
    if (!since || !until) return formatPeriodLabel(period.start, period.end);
    return `${formatDatePtBr(since)} - ${formatDatePtBr(until)}`;
  }, [paidData, period.end, period.start]);
  const paidCoverageLabel = paidData?.coverage?.is_partial
    ? `Dado parcial · até ${paidData.last_stat_date ? formatDatePtBr(paidData.last_stat_date) : "sem data"} · ${safe(paidData.coverage.covered_days)}/${safe(paidData.coverage.expected_days)} dias`
    : "";
  const dashboardError = err || dashError || bootstrapError || null;
  const coverage = dash?.coverage;
  const coveredDays = safe(coverage?.covered_days);
  const expectedDays = safe(coverage?.expected_days);
  const isPartialCoverage = Boolean(coverage?.is_partial) && expectedDays > 0;
  const hasPersistedOrganicData = hasInstagramSnapshotData({
    summaryHasData: hasSummaryOrganicData,
    coveredDays,
    metricValues: Object.values(kpisFromDash),
  });
  const organicAwaitingMetrics = hasDash && !hasPersistedOrganicData;
  const partialCoverageLabel = `Dados parciais: ${coveredDays}/${expectedDays} dias`;

  const monthAggRaw = useMemo(() => {
    if (monthlyRows.length) {
      return monthlyRows.map((row) => ({
        month: row.month,
        posts: row.posts,
        reels: row.reels,
        reach: row.reach,
        views: row.views,
        interactions: row.interactions,
        profile_visits: row.profile_visits,
        likes: row.likes,
        comments: row.comments,
        shares: row.shares,
        saved: row.saved,
        avg_watch_ms: 0,
        skip_rate_avg: 0,
      }));
    }
    return Array.isArray(mediaData) ? buildMonthAgg(mediaData) : [];
  }, [mediaData, monthlyRows]);
  const monthAgg = useMemo(() => {
    const byMonth = new Map<string, MonthAggRow>();
    for (const row of monthAggRaw) byMonth.set(row.month, row);

    const preferredMonthKeys = availableMonths.length ? availableMonths : monthsList(monthAggRaw);
    const mergedMonthKeys = new Set<string>([
      ...preferredMonthKeys,
      ...monthAggRaw.map((row) => row.month),
    ]);

    return Array.from(mergedMonthKeys)
      .sort()
      .map((monthKey) => byMonth.get(monthKey) || makeEmptyMonthAgg(monthKey));
  }, [availableMonths, monthAggRaw]);
  const months = useMemo(() => {
    if (availableMonths.length) return availableMonths;
    return monthsList(monthAgg);
  }, [availableMonths, monthAgg]);

  useEffect(() => {
    if (!months.length) return;
    const last = months[months.length - 1] || "";
    const prev = months[months.length - 2] || "";
    if (!monthB || !months.includes(monthB)) setMonthB(last);
    if (!monthA || !months.includes(monthA)) setMonthA(prev || last);
  }, [months, monthA, monthB]);

  const isFixedMonthPeriod = useMemo(
    () => isWholeMonthRange(period.start, period.end),
    [period.end, period.start]
  );
  const selectedMonthKey = useMemo(() => {
    if (!isFixedMonthPeriod) return "";
    return monthKeyFromIsoDate(period.start);
  }, [isFixedMonthPeriod, period.start]);

  const selectedMonthValue = useMemo(() => {
    const mk = selectedMonthKey;
    if (!/^\d{4}-\d{2}$/.test(mk)) return new Date().getMonth() + 1;
    return Math.max(1, Math.min(12, Number(mk.slice(5, 7))));
  }, [selectedMonthKey]);

  const selectedYearValue = useMemo(() => {
    const mk = selectedMonthKey;
    if (!/^\d{4}-\d{2}$/.test(mk)) return new Date().getFullYear();
    return Number(mk.slice(0, 4));
  }, [selectedMonthKey]);

  const availableMonthKeys = useMemo(() => {
    const set = new Set<string>();
    for (const key of availableMonths) {
      const mk = monthKeyFromIsoDate(key);
      if (mk) set.add(mk);
    }
    if (selectedMonthKey) set.add(selectedMonthKey);
    return Array.from(set).sort();
  }, [availableMonths, selectedMonthKey]);

  const availableYearOptions = useMemo(() => {
    const set = new Set<number>();
    for (const key of availableMonthKeys) {
      const year = Number(key.slice(0, 4));
      if (Number.isFinite(year)) set.add(year);
    }
    set.add(selectedYearValue);
    set.add(new Date().getFullYear());
    return Array.from(set).sort((a, b) => a - b);
  }, [availableMonthKeys, selectedYearValue]);

  const periodLabel = useMemo(
    () => formatPeriodLabel(period.start, period.end),
    [period.end, period.start]
  );
  const periodPreset = useMemo(
    () => periodPresetFromRange(period.start, period.end),
    [period.end, period.start]
  );
  const selectedMonthLabel =
    isFixedMonthPeriod && selectedMonthKey ? monthLabelPt(selectedMonthKey) : periodLabel;
  const monthContextStatus = !hasDash
    ? "Sem dados consolidados"
    : loadingDash && !dash
      ? "Carregando dados..."
      : refreshingDash
        ? `${organicLastUpdatedLabel || "Com base anterior disponível"} • atualizando em background`
      : isPartialCoverage
        ? partialCoverageLabel
        : organicLastUpdatedLabel || "Dados atualizados";

  const a = monthA ? getMonth(monthAgg, monthA) || makeEmptyMonthAgg(monthA) : undefined;
  const b = monthB ? getMonth(monthAgg, monthB) || makeEmptyMonthAgg(monthB) : undefined;

  function handleSelectMetric(metric: MetaMetricKey) {
    setActiveMetric(metric);
  }

  function handleApplyMonthSelection(nextYear: number, nextMonth: number) {
    setMonthPeriod(nextYear, nextMonth);
  }

  const mediaFiltered: IgMediaItem[] = useMemo(() => {
    const all = arrayOrEmpty<IgMediaItem>(mediaData);
    if (!isFixedMonthPeriod || !selectedMonthKey) return all;
    return all.filter((m) => {
      const k = monthKeyFromIsoDate(m.timestamp || "");
      return !!k && k === selectedMonthKey;
    });
  }, [isFixedMonthPeriod, mediaData, selectedMonthKey]);
  const deferredMediaFiltered = useDeferredValue(mediaFiltered);
  const deferredComments = useDeferredValue(comments);
  const deferredTopWords = useDeferredValue(topWords);
  const deferredNotes = useDeferredValue(notes);
  const organicContentCounts = useMemo(() => {
    const rows = arrayOrEmpty<IgMediaItem>(mediaFiltered);
    const reels = rows.filter((media) => classifyInstagramMedia(media) === "reel").length;
    const posts = rows.filter((media) => classifyInstagramMedia(media) === "post").length;
    const mediaCommentCount = rows.reduce(
      (total, media) => total + mediaInsightValue(media, "comments"),
      0
    );
    return {
      posts,
      reels,
      comments: Math.max(commentsTotal, arrayOrEmpty(comments).length, mediaCommentCount),
    };
  }, [comments, commentsTotal, mediaFiltered]);
  const organicMetricCards = useMemo(
    () => [
      { label: "Seguidores", value: kpisFromDash.followers },
      { label: "Alcance", value: kpisFromDash.reach },
      { label: "Impressões", value: kpisFromDash.impressions },
      { label: "Interações", value: kpisFromDash.total_interactions },
      { label: "Visitas ao perfil", value: kpisFromDash.profile_views },
      { label: "Cliques no link", value: kpisFromDash.website_clicks },
      { label: "Posts", value: organicContentCounts.posts },
      { label: "Reels", value: organicContentCounts.reels },
      { label: "Comentários", value: organicContentCounts.comments },
    ],
    [kpisFromDash, organicContentCounts]
  );
  const mediaPanelLoading = loadingMedia || secondaryOrganicLoading;
  const commentsPanelLoading = loadingComments || secondaryOrganicLoading;
  const monthlyPanelLoading = loadingMonthly || (!enableMonthlyStage && !monthlyRows.length);

  const handleLoadMoreMedia = useCallback(() => {}, []);

  const handleLoadMoreComments = useCallback(() => {}, []);

  const metricCards = useMemo(
    () => [
      { title: "Visualizações", metric: "impressions" as const },
      { title: "Alcance", metric: "reach" as const },
      { title: "Interações", metric: "total_interactions" as const },
      { title: "Cliques no link", metric: "website_clicks" as const },
      { title: "Visitas ao perfil", metric: "profile_views" as const },
      { title: "Contas engajadas", metric: "accounts_engaged" as const },
      { title: "Seguidores", metric: "followers" as const },
    ],
    []
  );

  const activeMetricLabel = useMemo(() => {
    const found = metricCards.find((card) => card.metric === activeMetric);
    return found?.title || "Visualizações";
  }, [activeMetric, metricCards]);

  const topPostRanking = useMemo(() => {
    if (!deferredMediaFiltered.length) return [];
    const ranked = [...deferredMediaFiltered]
      .map((media) => {
        const score = mediaImpactScore(media);
        const reach = mediaInsightValue(media, "reach");
        const interactions = mediaInsightValue(media, "total_interactions");
        const rawLabel = String(media.caption || "").replace(/\s+/g, " ").trim();
        const fallbackLabel = String(media.media_product_type || media.media_type || "Post").trim() || "Post";
        const label = rawLabel ? (rawLabel.length > 52 ? `${rawLabel.slice(0, 52)}…` : rawLabel) : fallbackLabel;
        return {
          id: String(media.id || ""),
          media,
          score,
          reach,
          interactions,
          label,
        };
      })
      .sort((a, b) => b.score - a.score)
      .slice(0, 6);
    const maxScore = Math.max(...ranked.map((item) => safe(item.score)), 1);
    return ranked.map((item) => ({
      ...item,
      widthPct: Math.max(10, Math.round((safe(item.score) / maxScore) * 100)),
    }));
  }, [deferredMediaFiltered]);

  const organicExecutiveAvailable = hasDash && hasPersistedOrganicData;
  const paidExecutiveAvailable = Boolean(paidData && (paidHasRows || hasPaidData));
  const previousTotals = dash?.period_previous_totals;
  const comparableOrganic = organicExecutiveAvailable && !isPartialCoverage;
  const comparablePaid = paidExecutiveAvailable && previousPaidData?.has_data === true;
  const executiveMetrics = useMemo<ExecutiveMetric[]>(
    () => [
      {
        key: "revenue",
        label: "Receita atribuída Meta",
        value: paidExecutiveAvailable ? safe(paidTotals?.revenue) : null,
        previous: comparablePaid ? safe(previousPaidData?.totals?.revenue) : null,
        format: "currency",
        context: "Receita atribuída pela Meta às campanhas ativas no período.",
        source: "Meta Ads",
      },
      {
        key: "spend",
        label: "Investimento em mídia",
        value: paidExecutiveAvailable ? safe(paidTotals?.spend) : null,
        previous: comparablePaid ? safe(previousPaidData?.totals?.spend) : null,
        format: "currency",
        context: "Valor investido nas campanhas Meta disponíveis no período.",
        source: "Meta Ads",
      },
      {
        key: "roas",
        label: "ROAS reportado",
        value:
          paidExecutiveAvailable && typeof paidTotals?.roas === "number" && Number.isFinite(paidTotals.roas)
            ? paidTotals.roas
            : null,
        previous:
          comparablePaid && typeof previousPaidData?.totals?.roas === "number" && Number.isFinite(previousPaidData.totals.roas)
            ? previousPaidData.totals.roas
            : null,
        format: "ratio",
        context: "Retorno reportado a partir da receita atribuída pela plataforma de mídia.",
        source: "Meta Ads",
      },
      {
        key: "conversions",
        label: "Compras Meta",
        value: paidExecutiveAvailable ? safe(paidTotals?.conversions) : null,
        previous: comparablePaid ? safe(previousPaidData?.totals?.conversions) : null,
        format: "number",
        context: "Compras atribuídas pela Meta às campanhas ativas no período.",
        source: "Meta Ads",
      },
      {
        key: "ticket",
        label: "Ticket médio Meta",
        value:
          paidExecutiveAvailable && safe(paidTotals?.conversions) > 0
            ? safe(paidTotals?.revenue) / safe(paidTotals?.conversions)
            : null,
        previous:
          comparablePaid && safe(previousPaidData?.totals?.conversions) > 0
            ? safe(previousPaidData?.totals?.revenue) / safe(previousPaidData?.totals?.conversions)
            : null,
        format: "currency",
        context: "Receita atribuída à Meta dividida pelas compras atribuídas à Meta.",
        source: "Meta Ads",
      },
      {
        key: "followers",
        label: "Seguidores no período",
        value: organicExecutiveAvailable ? safe(dash?.period_totals?.followers_growth) : null,
        previous: comparableOrganic ? safe(previousTotals?.followers_growth) : null,
        format: "number",
        context: "Variação líquida entre os snapshots de seguidores disponíveis no período.",
        source: "Instagram Graph",
      },
      {
        key: "reach",
        label: "Alcance orgânico",
        value: organicExecutiveAvailable ? kpisFromDash.reach : null,
        previous: comparableOrganic ? safe(previousTotals?.reach) : null,
        format: "number",
        context: "Contas únicas alcançadas pelo conteúdo orgânico.",
        source: "Instagram Graph",
      },
      {
        key: "interactions",
        label: "Interações",
        value: organicExecutiveAvailable ? kpisFromDash.total_interactions : null,
        previous: comparableOrganic ? safe(previousTotals?.total_interactions) : null,
        format: "number",
        context: "Ações de engajamento registradas pelo Instagram.",
        source: "Instagram Graph",
      },
      {
        key: "profile_views",
        label: "Visitas ao perfil",
        value: organicExecutiveAvailable ? kpisFromDash.profile_views : null,
        previous: comparableOrganic ? safe(previousTotals?.profile_views) : null,
        format: "number",
        context: "Sinal de intenção após o contato com o conteúdo.",
        source: "Instagram Graph",
      },
      {
        key: "website_clicks",
        label: "Cliques no link",
        value: organicExecutiveAvailable ? kpisFromDash.website_clicks : null,
        previous: comparableOrganic ? safe(previousTotals?.website_clicks) : null,
        format: "number",
        context: "Tráfego encaminhado pelo perfil para o destino configurado.",
        source: "Instagram Graph",
      },
    ],
    [
      comparableOrganic,
      comparablePaid,
      dash?.period_totals?.followers_growth,
      kpisFromDash,
      organicExecutiveAvailable,
      paidExecutiveAvailable,
      paidTotals,
      previousPaidData,
      previousTotals,
    ]
  );
  const executiveSources = useMemo<ExecutiveSource[]>(
    () => [
      {
        label: "Instagram orgânico",
        state: dashError
          ? "error"
          : hasActiveConnection === true
            ? organicExecutiveAvailable
              ? "connected"
              : "waiting"
            : "waiting",
        detail: dashError
          ? "Falha parcial na leitura"
          : organicExecutiveAvailable
            ? organicLastUpdatedLabel || "Dados disponíveis"
            : hasActiveConnection
              ? "Aguardando sincronização"
              : "Fonte não conectada",
      },
      {
        label: "Meta Ads",
        state: paidError
          ? "error"
          : hasPaidConnection
            ? paidExecutiveAvailable
              ? "connected"
              : "waiting"
            : "waiting",
        detail: paidError
          ? "Falha parcial na leitura"
          : paidExecutiveAvailable
            ? providerFreshnessDetail(executiveData?.meta) || paidLastUpdatedLabel || "Dados disponíveis"
            : paidSyncStatus === "skipped"
              ? paidConnection?.last_error || "Nenhum agregado retornado no período"
              : paidSyncStatus === "partial"
                ? paidConnection?.last_error || "Importação parcial"
            : hasPaidConnection
              ? "Aguardando sincronização válida"
              : "Fonte não conectada",
      },
      {
        label: "Shopify",
        state: executiveData?.shopify?.connected ? "connected" : executiveError ? "error" : "waiting",
        detail: executiveData?.shopify?.connected
          ? executiveData.shopify.orders > 0
            ? `${executiveData.shopify.orders.toLocaleString("pt-BR")} pedidos · ${providerFreshnessDetail(executiveData.shopify)}`
            : executiveData.shopify.data_min_in_period && executiveData.shopify.data_max_in_period
              ? `Sem pedidos no recorte; cobertura ${formatDatePtBr(executiveData.shopify.data_min_in_period)} a ${formatDatePtBr(executiveData.shopify.data_max_in_period)}`
              : "Sem pedidos Shopify persistidos"
          : executiveError
            ? "Falha parcial na leitura Shopify"
            : "Sem dados Shopify para este período",
      },
      {
        label: "GA4",
        state: executiveData?.ga4?.connected ? "connected" : executiveError ? "error" : "waiting",
        detail: executiveData?.ga4?.connected
          ? providerFreshnessDetail(executiveData.ga4)
          : executiveError
            ? "Falha parcial na leitura GA4"
            : "Sem snapshot GA4 persistido",
      },
    ],
    [
      dashError,
      hasActiveConnection,
      hasPaidConnection,
      organicExecutiveAvailable,
      organicLastUpdatedLabel,
      paidError,
      paidExecutiveAvailable,
      paidLastUpdatedLabel,
      paidConnection?.last_error,
      paidSyncStatus,
      executiveData?.shopify,
      executiveData?.meta,
      executiveData?.ga4,
      executiveError,
    ]
  );
  const metaRenderKey = [
    organicConnectionId || "-",
    paidConnectionId || "-",
    period.start,
    period.end,
  ].join(":");

  const dashDailyLen = dash?.daily?.length ?? 0;
  useEffect(() => {
    dashLog("renderSummary", {
      activeClientId,
      hasDash: !!dash?.ok,
      dashDaily: dashDailyLen,
  
      mediaData: mediaData.length,
      mediaFiltered: deferredMediaFiltered.length,
      comments: comments.length,
      notes: notes.length,
      err: err || "",
    });
  }, [
    activeClientId,
    dash?.ok,
    dashDailyLen,
    mediaData.length,
    deferredMediaFiltered.length,
    comments.length,
    notes.length,
    err,
  ]);

  if (!isAuthenticated) {
    return null;
  }

  return (
    <Shell
      themeClass={themeClass}
      title=""
      right={
          <DashboardHeader
          activeView="meta"
          statusChips={[
            {
              connected: hasActiveConnection === true || executiveData?.instagram?.connected === true,
              label: `${hasActiveConnection === true || executiveData?.instagram?.connected === true ? "Orgânico conectado" : "Orgânico sem dados"}${organicLastUpdatedLabel ? ` • ${organicLastUpdatedLabel}` : ""}`,
            },
            {
              connected: hasPaidConnection || executiveData?.meta?.connected === true,
              label: `${hasPaidConnection || executiveData?.meta?.connected === true ? "Ads conectado" : "Ads sem dados"}${paidLastUpdatedLabel ? ` • ${paidLastUpdatedLabel}` : ""}`,
            },
          ]}
          periodPreset={periodPreset}
          onSelectPeriodPreset={onSelectPeriodPreset}
          backgroundRefreshing={refreshingSummary || refreshingMonthly || refreshingPaid}
          onOpenMeta={() => {}}
          onOpenGoogleAnalytics={onOpenGoogleAnalytics}
          refreshing={syncing}
          onRefresh={onRefresh}
          onLogout={onLogoutClick}
        />
      }
    >
      <div className={`layout ${SHOW_PRESENTATION_EXTRAS ? "" : "layoutPresentation"}`.trim()}>
        {/* COLUNA PRINCIPAL */}
        <div className="panel">
          {configWarning ? (
            <div className="panelBlock">
              <div className="pill pillDanger">{configWarning}</div>
            </div>
          ) : null}

          <div className="panelHead panelHead-minimal">
            <div className="monthControls">
              <select
                className="select"
                value={String(selectedMonthValue)}
                onChange={(event) =>
                  handleApplyMonthSelection(selectedYearValue, Number(event.target.value))
                }
                aria-label="Selecionar mês"
              >
                {MONTHS_PT.map((label, index) => {
                  const month = index + 1;
                  return (
                    <option key={label} value={month}>
                      {label}
                    </option>
                  );
                })}
              </select>
              <select
                className="select selectYear"
                value={String(selectedYearValue)}
                onChange={(event) =>
                  handleApplyMonthSelection(Number(event.target.value), selectedMonthValue)
                }
                aria-label="Selecionar ano"
              >
                {availableYearOptions.map((year) => (
                  <option key={year} value={year}>
                    {year}
                  </option>
                ))}
              </select>
              <span className="smallMuted monthStatusText">
                {selectedMonthLabel} • {monthContextStatus}
              </span>
            </div>
          </div>
          {getActiveClient()?.role === "agency_admin" ? (
            <div className="smallMuted" data-testid="refresh-runtime-diagnostic">
              Atualizar dados — {refreshRuntime.length ? refreshRuntime.map((item) =>
                `${String(item.provider || "-")}: ${String(item.status || "-")} · ${String(item.endpoint || "-")} · conexão ${String(item.connection_id || "-")} · código ${String(item.code || "-")} · request_id ${String(item.request_id || "-")} · linhas ${String(item.rows_written ?? 0)} · ${String(item.started_at || "-")} → ${String(item.finished_at || "-")}`
              ).join(" | ") : "nenhuma ação disparada"}
            </div>
          ) : null}

          <ExecutiveOverview
            companyName={commerceConnection?.account_name || getActiveClientName() || "E-commerce conectado"}
            commercePlatform={
              commerceConnection?.provider === "shopify"
                ? "Shopify"
                : executiveData?.shopify?.connected
                  ? "Shopify"
                : commerceConnection?.provider
                  ? "Plataforma de comércio"
                  : null
            }
            periodLabel={periodLabel}
            comparisonLabel={
              isPartialCoverage
                ? "Indisponível com cobertura parcial"
                : organicExecutiveAvailable
                  ? "Período anterior equivalente"
                  : "Dados insuficientes"
            }
            updatedLabel="Atualizações individuais por fonte"
            partialCoverage={isPartialCoverage ? partialCoverageLabel : null}
            metrics={executiveMetrics}
            sources={executiveSources}
            loading={loadingDash || loadingPaid}
            error={dashboardError}
          />

          {period.start <= new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(new Date()) &&
          period.end >= new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(new Date()) ? <ChannelTodaySummary
            channel="Meta"
            date={new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(new Date())}
            value={(() => {
              const today = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(new Date());
              const row = paidData?.daily?.find((item) => item.date === today);
              return row?.revenue != null && row.conversions != null
                ? { revenue: row.revenue, orders: row.conversions }
                : null;
            })()}
          /> : null}

          {paidExecutiveAvailable ? <PerformanceChart daily={paidData?.daily} /> : null}

          {hasActiveConnection === false && !executiveData?.instagram?.connected ? (
            <div className="panelBlock">
              <div className="card cardWide">
                <div className="sectionHeader">
                  <div>
                    <div className="h1">Conexão ainda não configurada</div>
                    <div className="p">
                      O dashboard continua disponível. Conecte o Instagram Graph para preencher as métricas orgânicas.
                    </div>
                  </div>
                  {onOpenSetup ? (
                    <button className="btn btnGhost" type="button" onClick={() => onOpenSetup()}>
                      Configurar agora
                    </button>
                  ) : null}
                </div>
              </div>
            </div>
          ) : null}

          <div className="panelBlock">
            {loadingDash && !hasDash ? (
              <div className="kpiGrid">
                <div className="skeleton skeletonKpi" />
                <div className="skeleton skeletonKpi" />
                <div className="skeleton skeletonKpi" />
                <div className="skeleton skeletonKpi" />
                <div className="skeleton skeletonKpi" />
                <div className="skeleton skeletonKpi" />
              </div>
            ) : hasDash ? (
              <>
                <div className="organicSourceHeader">
                  <div>
                    <div className="h1">Meta Orgânico / Instagram</div>
                    <div className="p">Posts, reels, alcance, engajamento e comentários vindos da conexão orgânica.</div>
                  </div>
                  <span className="pill">Fonte: Instagram Graph · {formatSelectedPeriodLabel(period)}</span>
                </div>
                {organicAwaitingMetrics ? (
                  <div className="organicWaitingState">Instagram orgânico conectado, aguardando sincronização.</div>
                ) : null}
                <div className="organicMetricGrid">
                  {organicMetricCards.map((card) => (
                    <div className="organicMetricCard" key={card.label}>
                      <span>{card.label}</span>
                      <strong>{fmt(card.value)}</strong>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="card cardWide">
                <MetaStateNotice
                  title={hasActiveConnection === false ? "Instagram orgânico ainda não conectado" : "Instagram orgânico aguardando dados"}
                  description={
                    hasActiveConnection === false
                      ? "Conecte o Instagram Graph para ler alcance, interações, mídia e comentários."
                      : "A conexão pode estar pronta enquanto as métricas do período são atualizadas."
                  }
                  tone={dashError ? "unavailable" : "empty"}
                  message={
                    dashError
                      ? "Não foi possível carregar o resumo principal agora."
                      : hasActiveConnection === false
                        ? "Instagram orgânico ainda não conectado."
                        : "Instagram orgânico conectado, aguardando sincronização."
                  }
                  secondaryMessage="Comentários e reels aparecem quando houver detalhamento persistido."
                />
              </div>
            )}
          </div>

          <div className="panelBlock">
            <div className="sectionHeader">
              <div>
                <div className="h1">Evolução Temporal</div>
                <div className="p">
                  Métrica ativa ({activeMetricLabel}) com comparação por período.
                </div>
              </div>

              <div className="metricHeaderActions">
                <span className="smallMuted" style={{ marginRight: 8 }}>
                  Agrupar por:
                </span>
                <div className="metricGranularityToggle" role="group" aria-label="Granularidade do gráfico">
                  <button
                    type="button"
                    className={`btn btnGhost metricGranularityBtn ${chartGranularity === "monthly" ? "isActive" : ""}`}
                    onClick={() => setChartGranularity("monthly")}
                  >
                    Mensal
                  </button>
                  <button
                    type="button"
                    className={`btn btnGhost metricGranularityBtn ${chartGranularity === "weekly" ? "isActive" : ""}`}
                    onClick={() => setChartGranularity("weekly")}
                  >
                    Semanal
                  </button>
                  <button
                    type="button"
                    className={`btn btnGhost metricGranularityBtn ${chartGranularity === "daily" ? "isActive" : ""}`}
                    onClick={() => setChartGranularity("daily")}
                  >
                    Diário
                  </button>
                </div>
              </div>
            </div>

            <div className="metricSelectorCompact">
              <label htmlFor="mainMetricSelect" className="smallMuted">
                Métrica do gráfico
              </label>
              <select
                id="mainMetricSelect"
                className="select metricSelectInput"
                value={activeMetric}
                onChange={(event) => handleSelectMetric(event.target.value as MetaMetricKey)}
              >
                {metricCards.map((card) => (
                  <option key={card.metric} value={card.metric}>
                    {card.title}
                  </option>
                ))}
              </select>
            </div>
            {dashboardError ? (
              <div className="smallMuted dashboardInlineError">
                Algumas leituras não ficaram disponíveis agora.
              </div>
            ) : null}

            <MetaBlockBoundary
              resetKey={`main-chart:${metaRenderKey}:${activeMetric}:${chartGranularity}`}
              title="Evolução temporal"
              description="Leitura principal da Meta"
            >
              <div className="dashboardMainChart">
                {loadingDash && !hasDash ? (
                  <div className="card cardWide">
                    <MetaStateNotice
                      title="Carregando visão principal"
                      description="O orgânico é o primeiro bloco a estabilizar."
                      tone="loading"
                      message="Preparando a leitura principal da Meta..."
                    />
                  </div>
                ) : hasDash ? (
                  <MetaChartCard
                    key={activeMetric}
                    title={`${activeMetricLabel} no período`}
                    metric={activeMetric}
                    dash={dash!}
                    days={rangeDays}
                    periodLabel={periodLabel}
                    granularity={chartGranularity}
                    highlighted
                    variant="primary"
                  />
                ) : (
                  <div className="card cardWide">
                    <MetaStateNotice
                      title="Sem leitura principal"
                      description="A página continua utilizável mesmo sem esse gráfico."
                      tone={dashError ? "unavailable" : "empty"}
                      message={
                        dashError
                          ? "Não foi possível montar o gráfico principal agora."
                          : "Clique em “Atualizar dados” para sincronizar esse período."
                      }
                    />
                  </div>
                )}
              </div>
            </MetaBlockBoundary>

          </div>

          <div className="panelBlock" id="ads-fbits">
            <MetaBlockBoundary
              resetKey={`paid:${metaRenderKey}`}
              title="Campanhas de Ads"
              description="Leitura consolidada da mídia paga"
            >
            <div className="card cardWide">
              <div className="sectionHeader">
                <div>
                  <div className="h1">Campanhas de Ads</div>
                  <div className="p">Leitura consolidada da conta Meta Ads.</div>
                </div>
                <div className="dashboardSectionMeta">
                  {paidLastUpdatedLabel ? <span className="dashboardTimestamp">{paidLastUpdatedLabel}</span> : null}
                  <span className="pill">Fonte: Meta Ads · {formatSelectedPeriodLabel(period)}</span>
                  <div className="smallMuted">
                    Status Ads: {paidStatusLabel} • {paidDateRangeLabel}
                  </div>
                  {paidCoverageLabel ? <div className="smallMuted">{paidCoverageLabel}</div> : null}
                </div>
              </div>

              {paidPanelLoading && !paidData ? (
                <MetaStateNotice
                  title="Carregando Ads"
                  description="A mídia paga entra depois do orgânico."
                  tone="loading"
                  message="Preparando a leitura consolidada de Ads..."
                />
              ) : null}

              {!paidPanelLoading && paidError && !paidData ? (
                <MetaStateNotice
                  title="Ads indisponíveis"
                  description="A falha desse bloco não derruba o restante da página."
                  tone="unavailable"
                  message="A leitura de Meta Ads não ficou disponível agora."
                />
              ) : null}

              {paidData && hasPaidData ? (
                <div className="paidFilters" aria-label="Filtros Meta Ads">
                  <label>
                    <span>Campanha Meta</span>
                    <input
                      className="select"
                      type="search"
                      list="paid-campaign-options"
                      placeholder="Buscar campanha (ex.: Advantage)"
                      onChange={(event) => setPaidCampaignFilter(event.target.value)}
                      value={paidCampaignFilter}
                    />
                    <datalist id="paid-campaign-options">
                      {paidFilterOptions.campaigns.map((option) => <option key={option} value={option} />)}
                    </datalist>
                  </label>
                  <label>
                    <span>Conjunto</span>
                    <input
                      className="select"
                      type="search"
                      list="paid-adset-options"
                      placeholder="Buscar conjunto"
                      onChange={(event) => setPaidAdsetFilter(event.target.value)}
                      value={paidAdsetFilter}
                    />
                    <datalist id="paid-adset-options">
                      {paidFilterOptions.adsets.map((option) => <option key={option} value={option} />)}
                    </datalist>
                  </label>
                  <label>
                    <span>Anúncio</span>
                    <input
                      className="select"
                      type="search"
                      list="paid-ad-options"
                      placeholder="Buscar anúncio"
                      onChange={(event) => setPaidAdFilter(event.target.value)}
                      value={paidAdFilter}
                    />
                    <datalist id="paid-ad-options">
                      {paidFilterOptions.ads.map((option) => <option key={option} value={option} />)}
                    </datalist>
                  </label>
                  <label>
                    <span>Plataforma</span>
                    <select
                      className="select"
                      onChange={(event) => setPaidPlatformFilter(event.target.value)}
                      value={paidPlatformFilter}
                    >
                      <option value="">Todas as plataformas</option>
                      {paidFilterOptions.platforms.map((option) => <option key={option} value={option}>{option}</option>)}
                    </select>
                  </label>
                </div>
              ) : null}

              {paidData && hasPaidData ? (
                <div className="paidSummaryGrid">
                  <div className="paidSummaryItem">
                    <span className="smallMuted">Investimento</span>
                    <strong>{fmtCurrency(safe(paidTotals?.spend))}</strong>
                  </div>
                  <div className="paidSummaryItem">
                    <span className="smallMuted">Alcance</span>
                    <strong>{fmt(safe(paidTotals?.reach))}</strong>
                  </div>
                  <div className="paidSummaryItem">
                    <span className="smallMuted">Impressões</span>
                    <strong>{fmt(safe(paidTotals?.impressions))}</strong>
                  </div>
                  <div className="paidSummaryItem">
                    <span className="smallMuted">Cliques totais</span>
                    <strong>{fmt(safe(paidTotals?.clicks))}</strong>
                  </div>
                  <div className="paidSummaryItem">
                    <span className="smallMuted">Cliques no link</span>
                    <strong>{fmt(safe(paidManagerMetrics?.link_clicks))}</strong>
                  </div>
                  <div className="paidSummaryItem">
                    <span className="smallMuted">Views de vídeo</span>
                    <strong>{fmt(safe(paidManagerMetrics?.video_views))}</strong>
                  </div>
                  <div className="paidSummaryItem">
                    <span className="smallMuted">CTR</span>
                    <strong>{safe(paidTotals?.ctr).toFixed(2)}%</strong>
                  </div>
                  <div className="paidSummaryItem">
                    <span className="smallMuted">CPC</span>
                    <strong>{fmtCurrency(safe(paidTotals?.cpc))}</strong>
                  </div>
                  <div className="paidSummaryItem">
                    <span className="smallMuted">CPM</span>
                    <strong>{fmtCurrency(safe(paidTotals?.cpm))}</strong>
                  </div>
                  <div className="paidSummaryItem">
                    <span className="smallMuted">ROAS</span>
                    <strong>
                      {typeof paidTotals?.roas === "number" && Number.isFinite(paidTotals.roas)
                        ? `${paidTotals.roas.toFixed(2)}x`
                        : "Sem dados"}
                    </strong>
                  </div>
                </div>
              ) : null}
              {paidData && hasPaidData ? (
                <p className="smallMuted" style={{ marginTop: 4 }}>
                  Investimento: {fmtCurrency(safe(paidTotals?.spend))} · Receita atribuída:{" "}
                  {fmtCurrency(safe(paidTotals?.revenue))} · ROAS ={" "}
                  {typeof paidTotals?.roas === "number" && Number.isFinite(paidTotals.roas)
                    ? `${paidTotals.roas.toFixed(2)}x`
                    : "Sem dados"}
                </p>
              ) : null}

              {paidData && hasPaidData ? (
                <div className="campaignsAttentionGrid">
                  <TopCampaignsRanking
                    campaigns={campaignsData?.campaigns || []}
                    loading={loadingCampaigns}
                    error={campaignsError}
                  />
                  <AttentionPanel metrics={executiveMetrics} />
                </div>
              ) : null}

              {paidError && paidData ? (
                <div className="metaInlineNotice">Falha parcial ao atualizar Ads. Exibindo a última leitura disponível.</div>
              ) : null}

              {paidData && paidTopCreatives.length ? (
                <div className="adsAccountsSection">
                  <div className="sectionHeader sectionHeaderSecondary">
                    <div>
                      <div className="h1">Top criativos pagos</div>
                      <div className="p">Ranking dos criativos com melhor desempenho no período.</div>
                    </div>
                  </div>
                  <div className="tableWrap">
                    <table className="table adsAccountsTable">
                      <thead>
                        <tr>
                          <th>Criativo / Post</th>
                          <th>Investimento</th>
                          <th>Alcance</th>
                          <th>Impressões</th>
                          <th>Cliques</th>
                          <th>CTR</th>
                          <th>CPC</th>
                        </tr>
                      </thead>
                      <tbody>
                        {paidTopCreatives.slice(0, 12).map((creative, index) => (
                          <tr key={String(creative.ad_id || creative.post_id || `creative-${index}`)}>
                            <td>
                              <div className="cellTitle">{String(creative.ad_name || "Criativo sem nome")}</div>
                              <div className="cellMuted">
                                {creative.post_id
                                  ? `Post ${creative.post_id}`
                                  : String(creative.ad_id || "Sem ID")}
                              </div>
                            </td>
                            <td>{fmtCurrency(safe(creative.spend))}</td>
                            <td>{fmt(safe(creative.reach))}</td>
                            <td>{fmt(safe(creative.impressions))}</td>
                            <td>{fmt(safe(creative.clicks))}</td>
                            <td>{safe(creative.ctr).toFixed(2)}%</td>
                            <td>{fmtCurrency(safe(creative.cpc))}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : null}

              {paidData && !paidTopCreatives.length && hasPaidData ? (
                <div className="smallMuted">Nenhum criativo retornado para detalhamento no período.</div>
              ) : null}

              {!paidPanelLoading && (!paidData || (!hasPaidData && !paidHasRows)) ? (
                <MetaStateNotice
                  title="Ads sem leitura no período"
                  description="A conexão pode estar ativa mesmo sem gasto ou sem sincronização recente."
                  tone={hasPaidConnection ? "empty" : "unavailable"}
                  message={paidEmptyMessage}
                />
              ) : null}
            </div>
            </MetaBlockBoundary>
          </div>

          <div className="panelBlock">
            <MetaBlockBoundary
              resetKey={`monthly:${metaRenderKey}`}
              title="Conteúdo publicado x alcance mensal"
              description="Série mensal de conteúdo"
            >
            <div className="sectionHeader">
              <div>
                            <div className="h1">Conteúdo publicado x alcance mensal</div>
                <div className="p">Barras: quantidade de posts • Linha: alcance total por mês.</div>
              </div>
              <div className="dashboardSectionMeta">
                {monthlyLastUpdatedLabel ? <span className="dashboardTimestamp">{monthlyLastUpdatedLabel}</span> : null}
                {refreshingMonthly ? <span className="pill">Atualizando...</span> : null}
              </div>
            </div>

            {monthAgg.length ? (
              <div className="card cardWide">
                <MonthMixChart data={monthAgg} />
              </div>
            ) : (
              <div className="card">
                {monthlyPanelLoading ? (
                  <MetaStateNotice
                    title="Preparando série mensal"
                    description="Esse bloco entra depois do núcleo principal."
                    tone="loading"
                    message="Montando o histórico mensal de conteúdo..."
                  />
                ) : monthlyError ? (
                  <MetaStateNotice
                    title="Série mensal indisponível"
                    description="A comparação mensal falhou, mas o restante da tela continua utilizável."
                    tone="unavailable"
                    message="A série mensal não ficou disponível agora."
                  />
                ) : (
                  <MetaStateNotice
                    title="Sem histórico mensal"
                    description="A série mensal aparece quando houver histórico suficiente de mídia."
                    tone="empty"
                    message="Sem dados mensais para exibir."
                  />
                )}
              </div>
            )}
            </MetaBlockBoundary>
          </div>

          <div className="panelBlock">
            <MetaBlockBoundary
              resetKey={`month-compare:${metaRenderKey}`}
              title="Comparar meses"
              description="Comparação de conteúdo por mês"
            >
            <div className="sectionHeader">
              <div>
                <div className="h1">Comparar meses</div>
                <div className="p">Selecione dois meses para comparar produção e performance do conteúdo.</div>
              </div>
              <div className="row">
                <select
                  className="select"
                  value={monthA}
                  onChange={(e) => setMonthA(e.target.value)}
                  disabled={!enableExtrasStage || !months.length}
                >
                  <option value="">Mês de referência</option>
                  {months.map((m) => (
                    <option key={m} value={m}>
                      {monthLabelPt(m)}
                    </option>
                  ))}
                </select>
                <select
                  className="select"
                  value={monthB}
                  onChange={(e) => setMonthB(e.target.value)}
                  disabled={!enableExtrasStage || !months.length}
                >
                  <option value="">Mês comparado</option>
                  {months.map((m) => (
                    <option key={m} value={m}>
                      {monthLabelPt(m)}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {a && b ? (
              <>
                {(a.posts + a.reels + a.reach + a.views + a.interactions + b.posts + b.reels + b.reach + b.views + b.interactions) ===
                0 ? (
                  <div className="smallMuted">
                    Meses encontrados no histórico, mas sem métricas de conteúdo orgânico nesses meses.
                  </div>
                ) : null}
                <div className="deltaRow">
                  <div className="deltaCard">
                    <div className="deltaLabel">Alcance</div>
                    <div className="deltaValue">{fmt(b.reach)}</div>
                    <div className={`deltaPill ${pct(b.reach, a.reach) >= 0 ? "up" : "down"}`}>
                      {pct(b.reach, a.reach) >= 0 ? "↑" : "↓"} {Math.abs(pct(b.reach, a.reach))}%
                    </div>
                  </div>
                  <div className="deltaCard">
                    <div className="deltaLabel">Views</div>
                    <div className="deltaValue">{fmt(b.views)}</div>
                    <div className={`deltaPill ${pct(b.views, a.views) >= 0 ? "up" : "down"}`}>
                      {pct(b.views, a.views) >= 0 ? "↑" : "↓"} {Math.abs(pct(b.views, a.views))}%
                    </div>
                  </div>
                  <div className="deltaCard">
                    <div className="deltaLabel">Interações</div>
                    <div className="deltaValue">{fmt(b.interactions)}</div>
                    <div className={`deltaPill ${pct(b.interactions, a.interactions) >= 0 ? "up" : "down"}`}>
                      {pct(b.interactions, a.interactions) >= 0 ? "↑" : "↓"} {Math.abs(pct(b.interactions, a.interactions))}%
                    </div>
                  </div>
                  <div className="deltaCard">
                    <div className="deltaLabel">Reels</div>
                    <div className="deltaValue">{fmt(b.reels)}</div>
                    <div className={`deltaPill ${pct(b.reels, a.reels) >= 0 ? "up" : "down"}`}>
                      {pct(b.reels, a.reels) >= 0 ? "↑" : "↓"} {Math.abs(pct(b.reels, a.reels))}%
                    </div>
                  </div>
                </div>

                <div className="card cardWide">
                  <MonthCompareLines
                    aLabel={monthLabelPt(monthA)}
                    bLabel={monthLabelPt(monthB)}
                    a={a}
                    b={b}
                  />
                </div>
              </>
            ) : (
              <div className="card">
                <MetaStateNotice
                  title={!enableExtrasStage && !months.length ? "Preparando comparação" : "Selecione dois meses"}
                  description="Esse bloco depende do histórico mensal ficar pronto."
                  tone={!enableExtrasStage && !months.length ? "loading" : "empty"}
                  message={
                    !enableExtrasStage && !months.length
                      ? "Preparando o histórico mensal para comparação..."
                      : "Selecione os dois meses depois que o histórico mensal carregar."
                  }
                />
              </div>
            )}
            </MetaBlockBoundary>
          </div>

          <div className="panelBlock">
            <MetaBlockBoundary
              resetKey={`media:${metaRenderKey}:${selectedMonthKey || "all"}`}
              title="Conteúdo orgânico"
              description="Prévia visual e ranking do conteúdo orgânico"
            >
            <div className="sectionHeader">
              <div>
                <div className="h1">Conteúdo orgânico</div>
                <div className="p">
                  Reels e posts com leitura visual, métricas e link. Conteúdos no período: {deferredMediaFiltered.length}.
                </div>
              </div>
              <div className="dashboardSectionMeta">
                {mediaLastUpdatedLabel ? <span className="dashboardTimestamp">{mediaLastUpdatedLabel}</span> : null}
                {refreshingMedia ? <span className="pill">Atualizando...</span> : null}
              </div>
            </div>

            <div className="card cardWide">
              {mediaError && deferredMediaFiltered.length ? (
                <div className="metaInlineNotice">Falha parcial ao atualizar mídias. Exibindo a última leitura disponível.</div>
              ) : null}
              {topPostRanking.length ? (
                <div className="topPostRanking">
                  <div className="smallMuted topPostRankingTitle">Ranking visual dos conteúdos com maior impacto.</div>
                  {topPostRanking.map((item, index) => (
                    <div key={item.id || `top-post-${index}`} className="topPostRankingRow">
                      <div className="topPostRankingHead">
                        <span className="topPostRankingIndex">#{index + 1}</span>
                        <div className="topPostRankingInfo">
                          <div className="topPostRankingLabel">{item.label}</div>
                          <div className="cellMuted">
                            Alcance {fmt(item.reach)} • Interações {fmt(item.interactions)} • Score {fmt(item.score)}
                          </div>
                        </div>
                      </div>
                      <div className="topPostRankingBar">
                        <span style={{ width: `${item.widthPct}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
              {deferredMediaFiltered.length ? <MediaTable media={deferredMediaFiltered} /> : null}
              {!deferredMediaFiltered.length && mediaPanelLoading ? (
                <MetaStateNotice
                  title="Carregando mídias"
                  description="A tabela entra depois do resumo principal."
                  tone="loading"
                  message="Buscando as mídias do período selecionado..."
                />
              ) : null}
              {!deferredMediaFiltered.length && !mediaPanelLoading && mediaError ? (
                <MetaStateNotice
                  title="Mídias indisponíveis"
                  description="Esse bloco falhou isoladamente e não derruba a página."
                  tone="unavailable"
                  message={
                    hasPersistedOrganicData
                      ? "Não foi possível carregar posts e reels agora."
                      : "Posts e reels ainda não sincronizados."
                  }
                />
              ) : null}
              {!deferredMediaFiltered.length && !mediaPanelLoading && !mediaError ? (
                <MetaStateNotice
                  title={hasPersistedOrganicData ? "Sem posts ou reels no período" : "Posts e reels ainda não sincronizados"}
                  description={
                    hasPersistedOrganicData
                      ? "A leitura orgânica está disponível e não retornou mídias nesse recorte."
                      : "Quando a sincronização orgânica trouxer mídias nesse recorte, elas aparecem aqui."
                  }
                  tone="empty"
                  message={
                    hasPersistedOrganicData
                      ? "Sem dados no período."
                      : "Posts ainda não sincronizados. Reels ainda não sincronizados."
                  }
                />
              ) : null}
              {mediaHasMore ? (
                <div className="panelActionsRow">
                  <button
                    type="button"
                    className="btn btnGhost"
                    onClick={handleLoadMoreMedia}
                    disabled={loadingMedia}
                  >
                    {loadingMedia ? "Carregando..." : "Ver mais mídias"}
                  </button>
                </div>
              ) : null}
            </div>
            </MetaBlockBoundary>
          </div>

          <div className="panelBlock">
            <MetaBlockBoundary
              resetKey={`comments:${metaRenderKey}`}
              title="Comentários"
              description="Comentários e nuvem de palavras"
            >
              <CommentsPanel
                comments={deferredComments}
                topWords={deferredTopWords}
                loading={commentsPanelLoading}
                refreshing={refreshingComments}
                updatedAtLabel={commentsLastUpdatedLabel}
                hasMore={commentsHasMore}
                total={commentsTotal}
                hasOrganicData={hasPersistedOrganicData}
                error={commentsError}
                onLoadMore={handleLoadMoreComments}
              />
            </MetaBlockBoundary>
          </div>

        </div>

        {SHOW_PRESENTATION_EXTRAS ? (
        <aside className="sidebar">
          <MetaBlockBoundary
            resetKey={`notes:${metaRenderKey}`}
            title="Notas do cliente"
            description="Anotações internas da conta"
          >
            {enableExtrasStage || deferredNotes.length || !notesAvailable || Boolean(notesError) ? (
              <NotesPanel
                notes={deferredNotes}
                loading={loadingNotes}
                available={notesAvailable}
                message={notesMessage}
                error={notesError}
                onCreate={handleCreateNote}
                onUpdate={handleUpdateNote}
              />
            ) : (
              <div className="card cardWide notesPanel">
                <MetaStateNotice
                  title="Preparando notas"
                  description="Notas e extras entram depois do núcleo principal."
                  tone="loading"
                  message="Preparando notas e extras..."
                />
              </div>
            )}
          </MetaBlockBoundary>
        </aside>
        ) : null}
      </div>
    </Shell>
  );
}
