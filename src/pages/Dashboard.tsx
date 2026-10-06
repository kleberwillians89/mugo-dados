import PeriodTransition from "../components/data/PeriodTransition";
import { startTransition, useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";

import { formatFreshness } from "../app/dataRefresh";
import Shell from "../components/Shell";
import { type KpiKey } from "../components/KpiGrid";
import MediaTable from "../components/MediaTable";
import CommentsPanel from "../components/CommentsPanel";
import NotesPanel from "../components/NotesPanel";
import MetaBlockBoundary from "../components/dashboard/MetaBlockBoundary";
import type { ExecutiveMetric } from "../components/dashboard/ExecutiveOverview";
import { changeOf } from "../components/dashboard/executiveNarrative";
import ChannelTodaySummary from "../components/dashboard/ChannelTodaySummary";
import { coveredShopifyDay } from "../components/dashboard/shopifyCoverage";
import PaidMediaReport from "../components/dashboard/PaidMediaReport";
import DataNotice from "../components/data/DataNotice";
import Delta from "../components/data/Delta";
import HeroFigure from "../components/data/HeroFigure";
import KpiFigure from "../components/data/KpiFigure";
import PageHeader from "../components/data/PageHeader";
import PeriodSelector from "../components/data/PeriodSelector";
import SegmentedControl from "../components/data/SegmentedControl";
import TrendChart from "../components/data/TrendChart";
import useClientIntegrations from "../hooks/useClientIntegrations";
import { readOnce } from "../hooks/dashboard/readOnce";
import useSectionDemand from "../hooks/useSectionDemand";
import {
  formatCalendarDateWords,
  formatCalendarRange,
  formatCompactInteger,
  formatCurrency,
  formatInteger,
  formatPercent,
  uniquePeak,
} from "../app/dataFormat";

import useDashboardSummary from "../hooks/dashboard/useDashboardSummary";
import useDashboardMonthlyContent from "../hooks/dashboard/useDashboardMonthlyContent";
import useDashboardPaid from "../hooks/dashboard/useDashboardPaid";
import useExecutiveDashboard from "../hooks/dashboard/useExecutiveDashboard";
import useCampaignsRanking from "../hooks/dashboard/useCampaignsRanking";
import {
  buildDashboardCacheKey,
  readDashboardCache,
  writeDashboardCache,
} from "../hooks/dashboard/cache";
import { resolveCommerceConnection, resolveOperationalMetaConnectionId, selectUniqueConnection } from "../app/connectionManager";
import { ensureDashboardPeriod, previousDashboardPeriod } from "../hooks/dashboard/period";
import { describeSyncError, runExclusiveSync } from "../app/syncOrchestrator";

import {
  refreshProviderData,
  listNotes,
  createNote,
  updateNote,
  listClientConnections,
  listGenericConnections,
  type GenericConnection,
} from "../app/api";
import { useDashboardSnapshot } from "../app/DashboardDataContext";
import { hasInstagramSnapshotData } from "../app/dashboardDataState";

import { getMonth, monthsList, pct } from "../app/aggregate";
import { aggregateInstagramOrganic, topInstagramContent, type ContentMetric } from "../app/instagramOrganic";
import { followerGrowthForPeriod } from "../app/followerGrowth";

import type {
  ClientIntegrationConnection,
  DashboardDailyRow,
  DashboardResponse,
  IgMediaItem,
  MetaConnection,
  MonthAgg,
  NoteItem,
} from "../app/types";

import {
  getActiveConnectionId,
  getSelectedConnectionId,
} from "../app/connectionState";
import { paidMediaNotice, providerEverHadData, providerValidUpdatedAt } from "../app/providerFreshness";
import { usePeriod } from "../app/PeriodContext";
import { formatSelectedPeriodLabel, getSelectedPeriodRange } from "../app/periodRange";
import {
  getActiveClientId,
  getActiveClient,
  getActiveClientName,
  getActiveClientConfigurationWarning,
} from "../app/activeClient";

import "../styles/dashboard.css";
import "../styles/channel-report.css";

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

type MetaMetricKey =
  | "impressions"
  | "reach"
  | "total_interactions"
  | "website_clicks"
  | "profile_views"
  | "accounts_engaged"
  | "followers";

type ChartGranularity = "daily" | "weekly" | "monthly";

const MONTH_SHORT_PT = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];

const META_METRIC_BY_KPI: Record<KpiKey, MetaMetricKey> = {
  reach: "reach",
  profile_views: "profile_views",
  website_clicks: "website_clicks",
  accounts_engaged: "accounts_engaged",
  total_interactions: "total_interactions",
  followers: "followers",
};

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

const ORGANIC_TREND_OPTIONS: Array<{ id: MetaMetricKey; label: string; peak: string }> = [
  { id: "reach", label: "Alcance", peak: "o maior alcance" },
  { id: "impressions", label: "Visualizações", peak: "o maior número de visualizações" },
  { id: "total_interactions", label: "Interações", peak: "o maior número de interações" },
  { id: "profile_views", label: "Visitas ao perfil", peak: "o maior número de visitas ao perfil" },
  { id: "website_clicks", label: "Cliques no link", peak: "o maior número de cliques no link" },
  { id: "followers", label: "Seguidores", peak: "o maior ganho de seguidores" },
];

const GRANULARITY_OPTIONS: Array<{ id: ChartGranularity; label: string; noun: string }> = [
  { id: "daily", label: "Diário", noun: "dia" },
  { id: "weekly", label: "Semanal", noun: "semana" },
  { id: "monthly", label: "Mensal", noun: "mês" },
];

type InstagramTrendProps = {
  dash: DashboardResponse;
  metric: MetaMetricKey;
  granularity: ChartGranularity;
  onMetric: (metric: MetaMetricKey) => void;
  onGranularity: (granularity: ChartGranularity) => void;
  periodLabel: string;
};

/**
 * Evolução do Instagram (mesma agregação de antes: soma por dia/semana/mês;
 * seguidores = variação entre um ponto e o anterior). O título só aponta o
 * pico quando há um único maior valor.
 */
function InstagramTrend({ dash, metric, granularity, onMetric, onGranularity, periodLabel }: InstagramTrendProps) {
  const option = ORGANIC_TREND_OPTIONS.find((item) => item.id === metric) || ORGANIC_TREND_OPTIONS[0];
  const noun = GRANULARITY_OPTIONS.find((item) => item.id === granularity)?.noun || "dia";
  const chartRows = useMemo(() => {
    const baseRows = Array.isArray(dash?.daily) && dash.daily.length
      ? dash.daily
      : Array.isArray(dash?.series?.daily)
        ? dash.series.daily
        : [];
    const availableKey = metric;
    if (dash.metric_coverage && !dash.metric_coverage[availableKey]) return [];
    return aggregateRowsByGranularity(baseRows.filter(row => !row.available_metrics || row.available_metrics.includes(availableKey)), granularity);
  }, [dash, granularity, metric]);

  const points = useMemo(() => chartRows.map((row, index) => {
    const value = option.id === "followers"
      ? safe(row.followers) - (index === 0 ? safe(row.followers) : safe(chartRows[index - 1]?.followers))
      : safe(row[option.id]);
    const start = parseIsoDate(String(row.start || row.date || "")) || new Date();
    const end = parseIsoDate(String(row.end || row.date || "")) || start;
    return { label: formatSeriesLabel(granularity, start, end), start: String(row.start || row.date || ""), value };
  }), [chartRows, granularity, option.id]);

  const peak = uniquePeak(points, (point) => point.value);
  const title = peak
    ? granularity === "monthly"
      ? `${peak.label} teve ${option.peak}`
      : granularity === "weekly"
        ? `A semana de ${formatCalendarDateWords(peak.start)} teve ${option.peak}`
        : `${formatCalendarDateWords(peak.start)} teve ${option.peak}`
    : `${option.label} por ${noun}`;

  return (
    <section className="ds-section ds-chartSection" aria-labelledby="instagram-trend-title">
      <div className="ds-sectionHead">
        <div className="ds-sectionHeadText">
          <h3 id="instagram-trend-title" className="ds-sectionTitle">{title}</h3>
          {peak ? <p className="ds-caption">{formatInteger(peak.value)} {option.label.toLowerCase()} nesse {noun}</p> : null}
        </div>
        <div className="ds-chartControls">
          <SegmentedControl
            ariaLabel="Métrica do gráfico do Instagram"
            value={option.id}
            onSelect={(id) => onMetric(id as MetaMetricKey)}
            options={ORGANIC_TREND_OPTIONS.map(({ id, label }) => ({ id, label }))}
          />
          <SegmentedControl
            ariaLabel="Agrupar por"
            value={granularity}
            onSelect={(id) => onGranularity(id as ChartGranularity)}
            options={GRANULARITY_OPTIONS.map(({ id, label }) => ({ id, label }))}
          />
        </div>
      </div>
      {points.length > 1 ? (
        <TrendChart
          data={points}
          xKey="label"
          primaryKey="value"
          formatX={(value) => value}
          formatY={formatCompactInteger}
          ariaLabel={`${option.label} do Instagram por ${noun}, ${periodLabel}.`}
          testId="instagram-trend-chart"
          renderTooltip={(point) => (
            <>
              <strong>{point.label}</strong>
              <dl><dt>{option.label}</dt><dd>{formatInteger(point.value)}</dd></dl>
            </>
          )}
        />
      ) : points.length === 1 ? (
        <p className="ds-emptyLine">
          {option.label}: {formatInteger(points[0].value)} em {points[0].label}. Escolha um agrupamento menor para ver a evolução.
        </p>
      ) : (
        <p className="ds-emptyLine">Sem dados do Instagram para desenhar a evolução neste período.</p>
      )}
    </section>
  );
}

const CONTENT_RANKING_OPTIONS: Array<{ id: ContentMetric; label: string }> = [
  { id: "reach", label: "Alcance" },
  { id: "views", label: "Views" },
  { id: "total_interactions", label: "Interações" },
  { id: "saved", label: "Salvamentos" },
  { id: "shares", label: "Compartilhamentos" },
  { id: "comments", label: "Comentários" },
];

const MONTH_COMPARE_ROWS: Array<{ key: "posts" | "reels" | "reach" | "views" | "interactions" | "profile_visits"; label: string }> = [
  { key: "reach", label: "Alcance dos conteúdos" },
  { key: "views", label: "Views" },
  { key: "interactions", label: "Interações" },
  { key: "profile_visits", label: "Visitas ao perfil" },
  { key: "posts", label: "Posts (feed)" },
  { key: "reels", label: "Reels" },
];

/**
 * Conexão Meta em uso, do contrato canônico (/integrations) já usado por
 * Integrações: a autorização escolhida para a empresa ou, sem escolha, a única.
 */
function pickMetaIntegration(connections: ClientIntegrationConnection[] | null, clientId: string) {
  const meta = (connections || []).filter((item) => item.provider === "meta");
  const selectedId = getSelectedConnectionId(clientId, "meta");
  return meta.find((item) => item.connection_id === selectedId) || (meta.length === 1 ? meta[0] : null);
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

function periodPresetFromRange(start: string, end: string): "day" | "7d" | "30d" | "month" | "custom" {
  if (start === end) return "day";
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

type MonthAggRow = MonthAgg;

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
  /** Sincronizações manuais exigem papel de gestão; viewer permanece somente leitura. */
  canSync?: boolean;
  bootstrapError?: string | null;
  onOpenSetup?: () => void;
  onOpenGoogleAnalytics?: () => void;
};

export default function Dashboard({
  isAuthenticated = false,
  canSync = false,
  bootstrapError,
  onOpenSetup,
}: DashboardProps) {
  const [syncing, setSyncing] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const {
    period: periodState,
    setPresetPeriod,
    setCurrentMonthPeriod,
    setMonthPeriod,
    setDayPeriod,
  } = usePeriod();
  const period = getSelectedPeriodRange(ensureDashboardPeriod(periodState));
  const [activeMetric, setActiveMetric] = useState<MetaMetricKey>(metricFromKpi("reach"));
  const [topContentMetric, setTopContentMetric] = useState<ContentMetric>("reach");
  const [chartGranularity, setChartGranularity] = useState<ChartGranularity>("daily");
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
  const [, setCommerceConnection] = useState<GenericConnection | null>(null);
  const [selectedPaidConnectionId, setSelectedPaidConnectionId] = useState<string | null>(() =>
    readDashboardCache<string>(paidConnectionIdCacheKey)
  );
  const [paidRefreshNoData, setPaidRefreshNoData] = useState<string | null>(null);
  const [refreshRuntime, setRefreshRuntime] = useState<Array<Record<string, unknown>>>([]);
  const [activeConnectionId, setActiveConnection] = useState<string | null>(() =>
    cachedConnectionsInitial.length ? pickDefaultConnectionId(cachedConnectionsInitial, getActiveConnectionId()) : null
  );
  const connectionScope = useRef(activeClientId);
  const [connectionReadError, setConnectionReadError] = useState<string | null>(null);
  if (connectionScope.current !== activeClientId) {
    connectionScope.current = activeClientId;
    const nextId = pickDefaultConnectionId(cachedConnectionsInitial, getActiveConnectionId());
    setConnections(cachedConnectionsInitial);
    setActiveConnection(nextId);
    setHasActiveConnection(nextId ? true : null);
    setConnectionReadError(null);
  }
  useEffect(() => {
    if (!isAuthenticated || !activeClientId) return;
    let alive = true;
    const apply = (rows: MetaConnection[]) => {
      if (!alive || connectionScope.current !== activeClientId) return;
      const own = rows.filter(row => row.client_id === activeClientId);
      const id = pickDefaultConnectionId(own, getActiveConnectionId());
      setConnections(own);
      setActiveConnection(id);
      setHasActiveConnection(Boolean(id));
      setConnectionReadError(null);
      writeDashboardCache(connectionsCacheKey, own, 300_000);
    };
    const cached = readDashboardCache<MetaConnection[]>(connectionsCacheKey);
    if (cached) apply(cached);
    else queueMicrotask(() => {
      if (!alive) return;
      void readOnce(connectionsCacheKey, () => listClientConnections(activeClientId))
        .then(response => apply(arrayOrEmpty<MetaConnection>(response.connections)))
        .catch(() => {
          if (!alive || connectionScope.current !== activeClientId) return;
          setHasActiveConnection(false);
          setConnectionReadError("Não foi possível resolver a conexão do Instagram.");
        });
    });
    return () => { alive = false; };
  }, [activeClientId, connectionsCacheKey, isAuthenticated]);
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
        start: period.start, end: period.end,
        extra: "available",
      }),
    [activeClientId, organicConnectionId, period.start, period.end]
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
  const demandScope = `${activeClientId}:${organicConnectionId}:${period.start}:${period.end}`;
  const dashboardSnapshot = useDashboardSnapshot();
  const organicReadsReady = isAuthenticated && Boolean(organicConnectionId) && !dashboardSnapshot.loading;
  const contentDemand = useSectionDemand(demandScope, organicReadsReady);
  const commentsDemand = useSectionDemand(demandScope, organicReadsReady);
  const monthlyDemand = useSectionDemand(demandScope, organicReadsReady);

  const {
    data: summaryData,
    reloadSummary,
    refreshingSummary,
    sectionLoading,
    sectionRefreshing,
    sectionErrors,
    sectionUpdatedAt,
  } = useDashboardSummary({
    isAuthenticated,
    activeClientId,
    activeConnectionId: organicConnectionId,
    secondaryEnabled: contentDemand.enabled || commentsDemand.enabled,
    commentsEnabled: commentsDemand.enabled,
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
  const refreshingComments = sectionRefreshing.comments || (refreshingSummary && comments.length > 0);
  
  const dashError = sectionErrors.dash;
  const mediaError = sectionErrors.media;
  const commentsError = sectionErrors.comments;
  const summarySettled = Boolean(dash) || Boolean(dashError);
  
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
    enabled: enableMonthlyStage && monthlyDemand.enabled,
    period,
  });
  const {
    paidData,
    loadingPaid,
    refreshingPaid,
    paidError,
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
  // Ativos da conexão em uso (Página, Instagram, conta de anúncios): mesma
  // leitura canônica de Integrações, só para identificar a fonte na página.
  const integrations = useClientIntegrations({ enabled: isAuthenticated && Boolean(activeClientId) && ["platform_admin", "agency_admin", "client_admin", "owner", "admin"].includes(String(getActiveClient()?.role || "").toLowerCase()) });
  const secondaryOrganicLoading =
    hasActiveConnection !== false && !contentDemand.enabled && !commentsDemand.enabled &&
    !mediaData.length &&
    !comments.length &&
    (loadingDash || refreshingDash || summarySettled);
  const paidPanelLoading = loadingPaid || (!enablePaidStage && !paidData);

  const onSelectPeriodPreset = useCallback(
    (preset: "day" | "7d" | "30d" | "month") => {
      if (preset === "day") {
        setDayPeriod(period.end);
        return;
      }
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
    [period.end, setCurrentMonthPeriod, setDayPeriod, setPresetPeriod]
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
    void options;
    try {
      // O agregado já informa os meses da janela; não pedir catálogo all-time.
      const rows = monthlyRows.map(row => row.month);
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
  }, [activeClientId, isAuthenticated, monthsCacheKey, organicConnectionId, monthlyRows]);

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
    if (!activeClientId) return;
    setErr(null);
    setSyncing(true);
    const startedAt = new Date().toISOString();
    const runtime = { tenant: activeClientId, provider: "meta", endpoint: `/api/clients/${activeClientId}/data-refresh/meta`, started_at: startedAt };
    console.info("[meta][manual_refresh_click]", { endpoint: runtime.endpoint });
    setRefreshRuntime([{ ...runtime, status: "running" }]);
    try {
      const result = await runExclusiveSync(
        { clientId: activeClientId, provider: "meta" },
        () => refreshProviderData("meta", period)
      );
      if (getActiveClientId() !== activeClientId) return;
      setPaidRefreshNoData(result.sources?.["Meta Ads"]?.status === "no_data" ? `${period.start}:${period.end}` : null);
      const snapshot = await dashboardSnapshot.refetch({ afterCurrent: true });
      if (!snapshot) throw new Error("Não foi possível reler os dados. Mantendo a última leitura disponível.");
      if (getActiveClientId() !== activeClientId) return;
      const summary = await reloadSummary({ snapshot, force: true, includeSecondary: true, loadStories: true });
      if (!summary) throw new Error("Não foi possível reler os dados. Mantendo a última leitura disponível.");
      console.info("[meta][ui_read_done]", { client_id: activeClientId });
      setRefreshRuntime([{ ...runtime, status: "success", finished_at: new Date().toISOString() }]);
    } catch (cause) {
      setRefreshRuntime([{ ...runtime, status: "error", finished_at: new Date().toISOString() }]);
      setErr(describeSyncError(cause, "Não foi possível atualizar. Mantendo a última leitura disponível."));
    } finally {
      setSyncing(false);
    }
  }

  const hasDash = !!dash?.ok;

  const configWarning = getActiveClientConfigurationWarning();

  const periodTotals = dash?.period_totals;
  const daily = dash?.daily || [];
  const followerGrowth = useMemo(
    () => followerGrowthForPeriod(dashboardSnapshot.snapshot?.daily || [], period.start, period.end),
    [dashboardSnapshot.snapshot?.daily, period.end, period.start]
  );
  const currentFollowers = followerGrowth.current ?? 0;
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
  const canonicalStorePeriod = useMemo(() => {
    const source = dashboardSnapshot.sources.find((item) => item.provider === "shopify");
    const covered = Boolean(source?.data_min_available && source?.data_max_available && source.data_min_available <= period.end && source.data_max_available >= period.start);
    if (!covered) return null;
    const rows = dashboardSnapshot.daily.filter((row) => row.metric_date >= period.start && row.metric_date <= period.end);
    const revenue = rows.reduce((sum, row) => sum + Number(row.shopify_net_revenue || 0), 0);
    const orders = rows.reduce((sum, row) => sum + Number(row.shopify_orders || 0), 0);
    return { revenue, orders, ticket: orders > 0 ? revenue / orders : null };
  }, [dashboardSnapshot.daily, dashboardSnapshot.sources, period.end, period.start]);
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
  const paidSyncStatus = String(paidConnection?.last_sync_status || "never").toLowerCase();
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
  const organicAvailable = (metric: string) => !dash?.metric_coverage || Boolean(dash.metric_coverage[metric]);
  const organicValue = (metric: string, value: number) => organicAvailable(metric) ? formatInteger(value) : "—";
  const organicRaw = (metric: string, value: number) => organicAvailable(metric) ? value : undefined;
  const accountHasCoverage = daily.length > 0;
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
    return [];
  }, [monthlyRows]);
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

  const periodPreset = useMemo(
    () => periodPresetFromRange(period.start, period.end),
    [period.end, period.start]
  );

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
  const organicContent = useMemo(() => aggregateInstagramOrganic(mediaFiltered), [mediaFiltered]);
  const deferredMediaFiltered = useDeferredValue(organicContent.content);
  const deferredComments = useDeferredValue(comments);
  const deferredTopWords = useDeferredValue(topWords);
  const deferredNotes = useDeferredValue(notes);
  const contentMetricCards = useMemo(() => [
    { label: "Publicações", value: organicContent.eligibleContentCount, coverage: null },
    { label: "Reels", value: organicContent.reelsCount, coverage: null },
    { label: "Feed", value: organicContent.feedCount, coverage: null },
    { label: "Alcance dos conteúdos", value: organicContent.metrics.reach.value, coverage: organicContent.metrics.reach },
    { label: "Views", value: organicContent.metrics.views.value, coverage: organicContent.metrics.views },
    { label: "Interações", value: organicContent.metrics.total_interactions.value, coverage: organicContent.metrics.total_interactions },
    { label: "Salvamentos", value: organicContent.metrics.saved.value, coverage: organicContent.metrics.saved },
    { label: "Compartilhamentos", value: organicContent.metrics.shares.value, coverage: organicContent.metrics.shares },
  ], [organicContent]);
  const mediaPanelLoading = loadingMedia || secondaryOrganicLoading;
  const commentsPanelLoading = loadingComments || (hasActiveConnection !== false && !commentsDemand.enabled && !comments.length);
  const monthlyPanelLoading = loadingMonthly || (hasActiveConnection !== false && !monthlyDemand.enabled && !monthlyRows.length);


  const handleLoadMoreComments = useCallback(() => {}, []);



  const topPostRanking = useMemo(() => {
    if (!deferredMediaFiltered.length) return [];
    const ranked = topInstagramContent(deferredMediaFiltered, topContentMetric)
      .map((media) => {
        const score = Number(media.insights?.[topContentMetric] || 0);
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
  }, [deferredMediaFiltered, topContentMetric]);

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
        label: "ROAS Meta",
        value:
          canonicalStorePeriod && paidExecutiveAvailable && safe(paidTotals?.spend) > 0
            ? canonicalStorePeriod.revenue / safe(paidTotals?.spend)
            : null,
        previous:
          comparablePaid && executiveData?.previous_period?.shopify?.connected && safe(previousPaidData?.totals?.spend) > 0
            ? safe(executiveData.previous_period.shopify.net_revenue) / safe(previousPaidData?.totals?.spend)
            : null,
        format: "ratio",
        context: "Receita real Shopify dividida pelo investimento Meta no mesmo período.",
        source: "Shopify + Meta Ads",
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
        label: "Seguidores ganhos",
        value: organicExecutiveAvailable ? followerGrowth.delta : null,
        previous: null,
        format: "number",
        context: followerGrowth.label
          ? `Variação líquida ${followerGrowth.label}, calculada somente entre snapshots comparáveis.`
          : "Aguardando um snapshot anterior comparável para calcular a variação.",
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
      followerGrowth,
      kpisFromDash,
      organicExecutiveAvailable,
      paidExecutiveAvailable,
      paidTotals,
      canonicalStorePeriod,
      executiveData,
      previousPaidData,
      previousTotals,
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

  // ===== Leitura da página (só apresentação: nada abaixo altera cálculo) =====
  const companyName = getActiveClientName();
  const isAgencyView = ["agency_admin", "platform_admin"].includes(String(getActiveClient()?.role || ""));
  const paidHasData = paidData?.has_data === true && paidTotals?.spend != null;
  // Leitura do read model ainda em curso ou com falha: nem "conectado", nem "sem dados".
  const readModelLoading = dashboardSnapshot.loading && !dashboardSnapshot.snapshot;
  const readModelError = !dashboardSnapshot.snapshot && !dashboardSnapshot.loading ? dashboardSnapshot.error : null;
  const organicHasData = hasDash && hasPersistedOrganicData;
  const metricChange = (key: string): number | null => {
    const metric = executiveMetrics.find((item) => item.key === key);
    return metric?.value != null && metric.previous != null ? changeOf(metric.value, metric.previous).percent : null;
  };
  const previousPeriodLabel = formatSelectedPeriodLabel(previousPaidPeriod);
  const hasPaidComparison = comparablePaid && ["spend", "revenue", "conversions"].some((key) => metricChange(key) != null);
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(new Date());
  const periodIncludesToday = period.start <= today && period.end >= today;
  const todayBlock = periodIncludesToday ? (
    <ChannelTodaySummary
      date={today}
      value={(() => {
        const row = executiveData?.daily?.find((item) => item.date === today)?.shopify;
        return coveredShopifyDay(executiveData?.shopify?.data_max_available, today, {
          revenue: row?.net_revenue,
          orders: row?.orders,
        });
      })()}
    />
  ) : null;
  const monthlyRowsForChart = monthAgg
    .filter((row) => row.reach > 0 || row.posts + row.reels > 0)
    .map((row) => ({ month: row.month, reach: row.reach, posts: row.posts + row.reels }));
  const monthlyPeak = uniquePeak(monthlyRowsForChart, (row) => row.reach);
  const monthlyTitle = monthlyPeak
    ? `${monthLabelPt(monthlyPeak.month)} teve o maior alcance de conteúdo`
    : "Conteúdo publicado e alcance por mês";
  const metaIntegration = pickMetaIntegration(integrations.lastValidConnections, activeClientId);
  const assets = metaIntegration?.assets || {};
  const assetRows = [
    { label: "Página", name: assets.facebook_page_name, id: assets.facebook_page_id },
    { label: "Instagram", name: assets.instagram_account_name ? `@${assets.instagram_account_name}` : null, id: assets.instagram_account_id },
    { label: "Conta de anúncios", name: assets.ad_account_name, id: assets.ad_account_id },
  ].filter((row) => row.name || row.id);
  // Conectado = conexão canônica com o ativo salvo, ou fonte com leitura no read model.
  const metaAdsConnected = hasPaidConnection || executiveData?.meta?.connected === true || Boolean(assets.ad_account_id);
  const instagramConnected = hasActiveConnection === true || executiveData?.instagram?.connected === true || Boolean(assets.instagram_account_id);
  const periodOption = periodPreset === "custom" ? (isFixedMonthPeriod ? "specific" : null) : periodPreset;
  const freshness = (label: string | null | undefined) => String(label || "").replace(/^Última atualização /, "atualizado em ");
  // Procedência: última leitura bem-sucedida da fonte no read model (o que a página mostra).
  const paidFreshness = formatFreshness(providerValidUpdatedAt(dashboardSnapshot.sources, "meta", {
    lastSuccessAt: executiveData?.meta?.last_success_at || paidConnection?.last_synced_at || paidConnection?.last_sync_at,
  }));
  const organicFreshness = formatFreshness(providerValidUpdatedAt(dashboardSnapshot.sources, "instagram", {
    lastSuccessAt: executiveData?.instagram?.last_success_at || organicConnection?.last_synced_at || organicConnection?.last_sync_at,
  }));
  const organicLead = !paidHasData && organicHasData;
  // "Já existiu dado" vem do read model (data_max_available), não da telemetria
  // de sync: um sync que não registrou last_success_at não pode fazer a tela
  // dizer "aguardando a primeira importação" para quem já tem números.
  const paidEverHadData = providerEverHadData(dashboardSnapshot.sources, "meta", {
    lastSuccessAt: executiveData?.meta?.last_success_at,
    hasDataNow: paidHasData,
  });
  const organicEverHadData = providerEverHadData(dashboardSnapshot.sources, "instagram", {
    lastSuccessAt: executiveData?.instagram?.last_success_at,
    hasDataNow: organicHasData,
  });
  const paidNotice = paidMediaNotice({
    provider: "Meta Ads",
    syncStatus: paidSyncStatus,
    everHadData: paidEverHadData,
  });
  const followersLine = followerGrowth.current != null
    ? `${formatInteger(followerGrowth.current)}${followerGrowth.delta != null ? ` (${followerGrowth.delta >= 0 ? "+" : "−"}${formatInteger(Math.abs(followerGrowth.delta))} ${followerGrowth.label})` : ""}`
    : "—";

  return (
    <PeriodTransition tenantId={activeClientId} period={period} ready={Boolean(dashboardSnapshot.snapshot) && dash?.client_id === activeClientId && dash?.start === period.start && dash?.end === period.end}>
    <Shell variant="editorial" themeClass="theme-editorial" title="Meta">
      <div className="ds-page metaReport">
        <div className="ds-group">
          <PageHeader
            company={companyName}
            title="Meta"
            dateline={
              <>
                <span>
                  <span className="ds-datelineSource">Meta Ads</span>{" "}
                  {readModelLoading ? "carregando" : readModelError ? "leitura indisponível" : paidFreshness ? `Dados atualizados ${paidFreshness}` : paidEverHadData ? "" : paidRefreshNoData === `${period.start}:${period.end}` ? "sem dados de anúncios no período consultado" : paidConnection?.last_sync_status === "skipped" ? "última consulta sem dados de anúncios" : metaAdsConnected ? "sem sincronização concluída" : "não conectado"}
                </span>
                <span>
                  <span className="ds-datelineSource">Instagram</span>{" "}
                  {readModelLoading ? "carregando" : readModelError ? "leitura indisponível" : organicFreshness ? `Dados atualizados ${organicFreshness}` : instagramConnected ? "sem sincronização concluída" : "não conectado"}
                </span>
                {isAuthenticated ? (
                  <span>
                    <button className="btn intelHeaderAction" onClick={() => void onRefresh()} disabled={syncing} type="button">
                      {syncing ? "Atualizando..." : "Atualizar dados"}
                    </button>
                  </span>
                ) : null}
              </>
            }
            controls={
              <PeriodSelector
                active={periodOption}
                onSelect={(id) => {
                  if (id === "specific") handleApplyMonthSelection(selectedYearValue, selectedMonthValue);
                  else onSelectPeriodPreset(id);
                }}
                month={selectedMonthValue}
                year={selectedYearValue}
                years={availableYearOptions}
                onMonthChange={(month) => handleApplyMonthSelection(selectedYearValue, month)}
                onYearChange={(year) => handleApplyMonthSelection(year, selectedMonthValue)}
              />
            }
            controlsNote={formatCalendarRange(period.start, period.end)}
          />

          {assetRows.length ? (
            <dl className="ds-assetLine" aria-label="Conexão Meta em uso" data-testid="meta-connection-assets">
              {assetRows.map((row) => (
                <div key={row.label}>
                  <dt>{row.label}</dt>
                  <dd>
                    {row.name || "Sem nome informado"}
                    {isAgencyView && row.id ? <span className="ds-assetId">{row.id}</span> : null}
                  </dd>
                </div>
              ))}
              {metaIntegration?.account?.name ? (
                <div><dt>Autorizado por</dt><dd>{metaIntegration.account.name}</dd></div>
              ) : null}
            </dl>
          ) : null}

          {metaIntegration?.authorization_status === "invalid" ? (
            <DataNotice
              tone="warning"
              role="status"
              title="A autorização Meta precisa ser renovada"
              actions={canSync && onOpenSetup ? <button className="ds-button" type="button" onClick={() => onOpenSetup()}>Ir para Integrações</button> : null}
            >
              Os números abaixo são da última leitura válida. {canSync ? "Conecte novamente para retomar as atualizações." : "Peça a um administrador da empresa para conectar novamente."}
            </DataNotice>
          ) : null}
          {configWarning ? <DataNotice tone="warning" title="Configuração da empresa">{configWarning}</DataNotice> : null}
          {dashboardError ? (
            <DataNotice tone="negative" role="alert" title="Parte das leituras não ficou disponível">{dashboardError}</DataNotice>
          ) : null}
          {syncing || refreshingSummary || refreshingPaid || refreshingMonthly ? (
            <p className="ds-status" role="status">Atualizando dados da Meta...</p>
          ) : null}
          {isAgencyView && getActiveClient()?.role === "agency_admin" ? (
            <p className="ds-footnote" data-testid="refresh-runtime-diagnostic">
              Atualizar dados — {refreshRuntime.length ? refreshRuntime.map((item) =>
                `${String(item.provider || "-")}: ${String(item.status || "-")} · ${String(item.endpoint || "-")} · conexão ${String(item.connection_id || "-")} · código ${String(item.code || "-")} · request_id ${String(item.request_id || "-")} · linhas ${String(item.rows_written ?? 0)} · ${String(item.started_at || "-")} → ${String(item.finished_at || "-")}`
              ).join(" | ") : "nenhuma ação disparada"}
            </p>
          ) : null}
        </div>

        {readModelError ? (
          <DataNotice tone="negative" role="alert" title="Não foi possível ler os dados da Meta">
            A leitura dos números falhou agora. A conexão não foi alterada; tente atualizar em instantes.
          </DataNotice>
        ) : null}

        {!readModelError && !readModelLoading && !metaAdsConnected && !instagramConnected && !paidHasData && !organicHasData && !loadingDash && !paidPanelLoading ? (
          <DataNotice
            title="Meta ainda não conectada"
            actions={canSync && onOpenSetup ? <button className="ds-button is-primary" type="button" onClick={() => onOpenSetup()}>Ir para Integrações</button> : null}
          >
            {canSync
              ? "Conecte Instagram e Meta Ads para ver investimento, alcance e conteúdo desta empresa."
              : "Os dados da Meta aparecem aqui quando a empresa conectar Instagram ou Meta Ads."}
          </DataNotice>
        ) : null}

        {/* ===== MÍDIA PAGA: o que foi investido e o que a Meta atribui ===== */}
        <MetaBlockBoundary resetKey={`paid:${metaRenderKey}`} title="Meta Ads" description="Leitura da mídia paga">
          {readModelError ? null : (paidPanelLoading && !paidData) || readModelLoading ? (
            <p className="ds-status" role="status">Carregando Meta Ads...</p>
          ) : paidError && !paidData ? (
            <DataNotice tone="negative" role="alert" title="Meta Ads indisponível">
              Não foi possível ler os dados de Meta Ads agora. O restante da página continua disponível.
            </DataNotice>
          ) : paidHasData && paidTotals ? (
            <div className="ds-stack">
            <PaidMediaReport
              source="Meta Ads"
              testId="meta-ads"
              totals={{
                spend: safe(paidTotals.spend),
                revenue: paidTotals.revenue,
                conversions: paidTotals.conversions,
                impressions: paidTotals.impressions,
                clicks: paidTotals.clicks,
                reach: paidTotals.reach,
                linkClicks: paidManagerMetrics?.link_clicks ?? null,
                videoViews: paidManagerMetrics?.video_views ?? null,
                ctr: paidTotals.ctr,
                cpc: paidTotals.cpc,
                cpm: paidTotals.cpm,
              }}
              changes={{
                spend: metricChange("spend"),
                revenue: metricChange("revenue"),
                conversions: metricChange("conversions"),
              }}
              comparisonNote={hasPaidComparison
                ? `Variações em relação a ${previousPeriodLabel}.`
                : `Sem base de comparação em ${previousPeriodLabel}.`}
              daily={(paidData?.daily || []).map((row) => {
                const shopify = executiveData?.daily?.find((item) => item.date === row.date)?.shopify;
                return {
                  ...row,
                  roas: row.spend != null && row.spend > 0 && shopify?.net_revenue != null ? shopify.net_revenue / row.spend : null,
                };
              })}
              // Resultado comercial = Shopify canônico (nunca atribuição Meta).
              store={canonicalStorePeriod?.revenue != null && canonicalStorePeriod?.orders != null ? {
                revenue: canonicalStorePeriod.revenue,
                orders: canonicalStorePeriod.orders,
                ticket: canonicalStorePeriod?.ticket ?? null,
                roas: safe(paidTotals?.spend) > 0 ? canonicalStorePeriod.revenue / safe(paidTotals?.spend) : null,
              } : null}
              today={canonicalStorePeriod ? todayBlock : null}
              campaigns={{ rows: campaignsData?.campaigns || [], loading: loadingCampaigns, error: campaignsError }}
            />
            {/* Criativos e filtros só existem quando a fonte devolve criativos
                (hoje o read model devolve lista vazia): sem dados, sem filtro. */}
            {paidFilterRows.length ? (
              <section className="ds-section" aria-labelledby="meta-creatives-title">
                <h2 id="meta-creatives-title" className="ds-sectionTitle">Criativos com investimento no período</h2>
                <div className="ds-filters" aria-label="Filtros Meta Ads">
                  <label className="ds-field">
                    <span>Campanha</span>
                    <input type="search" list="paid-campaign-options" placeholder="Buscar campanha" value={paidCampaignFilter} onChange={(event) => setPaidCampaignFilter(event.target.value)} />
                    <datalist id="paid-campaign-options">{paidFilterOptions.campaigns.map((option) => <option key={option} value={option} />)}</datalist>
                  </label>
                  <label className="ds-field">
                    <span>Conjunto</span>
                    <input type="search" list="paid-adset-options" placeholder="Buscar conjunto" value={paidAdsetFilter} onChange={(event) => setPaidAdsetFilter(event.target.value)} />
                    <datalist id="paid-adset-options">{paidFilterOptions.adsets.map((option) => <option key={option} value={option} />)}</datalist>
                  </label>
                  <label className="ds-field">
                    <span>Anúncio</span>
                    <input type="search" list="paid-ad-options" placeholder="Buscar anúncio" value={paidAdFilter} onChange={(event) => setPaidAdFilter(event.target.value)} />
                    <datalist id="paid-ad-options">{paidFilterOptions.ads.map((option) => <option key={option} value={option} />)}</datalist>
                  </label>
                  <label className="ds-field">
                    <span>Plataforma</span>
                    <select value={paidPlatformFilter} onChange={(event) => setPaidPlatformFilter(event.target.value)}>
                      <option value="">Todas as plataformas</option>
                      {paidFilterOptions.platforms.map((option) => <option key={option} value={option}>{option}</option>)}
                    </select>
                  </label>
                </div>
                {paidTopCreatives.length ? (
                  <div className="ds-tableWrap">
                    <table className="ds-table">
                      <thead>
                        <tr>
                          <th scope="col">Criativo</th>
                          <th scope="col" className="is-number">Investimento</th>
                          <th scope="col" className="is-number">Alcance</th>
                          <th scope="col" className="is-number">Impressões</th>
                          <th scope="col" className="is-number">Cliques</th>
                          <th scope="col" className="is-number">CTR</th>
                          <th scope="col" className="is-number">CPC</th>
                        </tr>
                      </thead>
                      <tbody>
                        {paidTopCreatives.slice(0, 12).map((creative, index) => (
                          <tr key={String(creative.ad_id || creative.post_id || `creative-${index}`)}>
                            <td className="is-primary">
                              {String(creative.ad_name || "Criativo sem nome")}
                              <span className="ds-tableSub">{creative.post_id ? `Post ${creative.post_id}` : String(creative.ad_id || "Sem ID")}</span>
                            </td>
                            <td className="is-number">{formatCurrency(safe(creative.spend))}</td>
                            <td className="is-number">{formatInteger(safe(creative.reach))}</td>
                            <td className="is-number">{formatInteger(safe(creative.impressions))}</td>
                            <td className="is-number">{formatInteger(safe(creative.clicks))}</td>
                            <td className="is-number">{formatPercent(safe(creative.ctr))}</td>
                            <td className="is-number">{formatCurrency(safe(creative.cpc))}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="ds-emptyLine">Nenhum criativo corresponde aos filtros.</p>
                )}
              </section>
            ) : null}
            </div>
          ) : metaAdsConnected ? (
            // Job "skipped"/parcial ou sem leitura válida nunca aparece como sucesso.
            <DataNotice
              role="status"
              title={paidNotice.title}
            >
              {paidNotice.body}
            </DataNotice>
          ) : organicHasData ? (
            <p className="ds-footnote">Meta Ads não conectado: a página mostra só o Instagram desta empresa.</p>
          ) : null}
        </MetaBlockBoundary>

        {/* ===== INSTAGRAM: atenção e conteúdo ===== */}
        <div ref={contentDemand.observe} data-testid="organic-demand">
        {connectionReadError ? <p role="status">{connectionReadError}</p> : null}
        <MetaBlockBoundary resetKey={`organic:${metaRenderKey}`} title="Instagram" description="Leitura orgânica">
          {readModelError ? null : (loadingDash && !hasDash) || readModelLoading ? (
            <p className="ds-status" role="status">Carregando Instagram...</p>
          ) : organicHasData ? (
            <div className="ds-stack" data-testid="instagram-report">
              <section className="ds-summary" aria-labelledby="instagram-title">
                {organicLead ? null : <h2 id="instagram-title" className="ds-headline">Instagram</h2>}
                {organicLead ? (
                  <HeroFigure
                    value={organicAvailable("reach") ? formatCompactInteger(kpisFromDash.reach) : "—"}
                    exactValue={organicValue("reach", kpisFromDash.reach)}
                    rawValue={organicRaw("reach", kpisFromDash.reach)}
                    label="contas alcançadas no Instagram no período"
                    delta={<Delta change={metricChange("reach")} showReference />}
                    testId="instagram-reach"
                  />
                ) : null}
                {organicLead ? <h2 id="instagram-title" className="ds-srOnly">Instagram</h2> : null}
                <div className={`ds-kpis${organicLead ? "" : " is-four"}`}>
                  {organicLead ? null : (
                    <KpiFigure label="Alcance" value={organicValue("reach", kpisFromDash.reach)} rawValue={organicRaw("reach", kpisFromDash.reach)} delta={<Delta change={metricChange("reach")} />} />
                  )}
                  <KpiFigure label="Interações" value={organicValue("total_interactions", kpisFromDash.total_interactions)} rawValue={organicRaw("total_interactions", kpisFromDash.total_interactions)} delta={<Delta change={metricChange("interactions")} />} />
                  <KpiFigure label="Visitas ao perfil" value={organicValue("profile_views", kpisFromDash.profile_views)} rawValue={organicRaw("profile_views", kpisFromDash.profile_views)} delta={<Delta change={metricChange("profile_views")} />} />
                  <KpiFigure label="Cliques no link" value={organicValue("website_clicks", kpisFromDash.website_clicks)} rawValue={organicRaw("website_clicks", kpisFromDash.website_clicks)} delta={<Delta change={metricChange("website_clicks")} />} />
                </div>
                <div className="ds-secondary">
                  <dl className="ds-inlineStats">
                    <div><dt>Visualizações</dt><dd>{organicValue("impressions", kpisFromDash.impressions)}</dd></div>
                    <div><dt>Seguidores</dt><dd>{organicAvailable("followers") ? followersLine : "—"}</dd></div>
                  </dl>
                  <p className="ds-footnote">
                    {isPartialCoverage ? `${partialCoverageLabel}. ` : null}
                    Sem base de comparação com o período anterior para as métricas da conta do Instagram.
                  </p>
                </div>
              </section>

              {accountHasCoverage && organicAvailable(activeMetric) ? (
                <InstagramTrend
                  dash={dash!}
                  metric={activeMetric}
                  granularity={chartGranularity}
                  onMetric={handleSelectMetric}
                  onGranularity={setChartGranularity}
                  periodLabel={formatSelectedPeriodLabel(period)}
                />
              ) : (
                <p className="ds-emptyLine">Sem cobertura histórica das métricas da conta neste período.</p>
              )}

              <section className="ds-section" aria-labelledby="instagram-content-title">
                <div className="ds-sectionHead">
                  <div className="ds-sectionHeadText">
                    <h3 id="instagram-content-title" className="ds-sectionTitle">
                      {organicContent.eligibleContentCount
                        ? `${formatInteger(organicContent.eligibleContentCount)} ${organicContent.eligibleContentCount === 1 ? "publicação" : "publicações"} no período`
                        : "Nenhuma publicação no período"}
                    </h3>
                    <p className="ds-caption">
                      {formatInteger(organicContent.reelsCount)} Reels · {formatInteger(organicContent.feedCount)} no feed · {formatInteger(organicContent.stories.length)} stories
                      {mediaLastUpdatedLabel ? ` · ${freshness(mediaLastUpdatedLabel)}` : ""}
                    </p>
                  </div>
                  {topPostRanking.length ? (
                    <SegmentedControl
                      ariaLabel="Métrica do ranking de conteúdos"
                      value={topContentMetric}
                      onSelect={(id) => setTopContentMetric(id as ContentMetric)}
                      options={CONTENT_RANKING_OPTIONS}
                    />
                  ) : null}
                </div>
                {mediaError && deferredMediaFiltered.length ? (
                  <DataNotice tone="warning" title="Atualização parcial das publicações">Exibindo a última leitura disponível.</DataNotice>
                ) : null}
                {organicContent.eligibleContentCount ? (
                  <dl className="ds-inlineStats">
                    {contentMetricCards.slice(3).map((card) => (
                      <div key={card.label}>
                        <dt>{card.label}</dt>
                        <dd>
                          {card.value == null ? "—" : formatInteger(card.value)}
                          {card.coverage && card.coverage.availableCount < card.coverage.eligibleCount
                            ? <span className="ds-kpiHint"> · {card.coverage.availableCount} de {card.coverage.eligibleCount} com dados</span>
                            : null}
                        </dd>
                      </div>
                    ))}
                  </dl>
                ) : null}
                {topPostRanking.length ? (
                  <ol className="ds-rankList" aria-label="Conteúdos com melhor resultado">
                    {topPostRanking.map((item, index) => (
                      <li key={item.id || `top-post-${index}`} className="ds-rankRow">
                        <span className="ds-rankName">{item.label}</span>
                        <span className="ds-rankValue">{formatInteger(item.score)}</span>
                        <span className="ds-rankMeta">Alcance {formatInteger(item.reach)} · Interações {formatInteger(item.interactions)}</span>
                        <span className="ds-rankBar" aria-hidden="true"><span style={{ width: `${item.widthPct}%` }} /></span>
                      </li>
                    ))}
                  </ol>
                ) : null}
                {deferredMediaFiltered.length ? <MediaTable media={deferredMediaFiltered} /> : null}
                {!deferredMediaFiltered.length && mediaPanelLoading ? <p className="ds-status" role="status">Carregando publicações...</p> : null}
                {!deferredMediaFiltered.length && !mediaPanelLoading && mediaError ? (
                  <DataNotice tone="negative" title="Publicações indisponíveis">Não foi possível carregar posts e reels agora.</DataNotice>
                ) : null}
                {!deferredMediaFiltered.length && !mediaPanelLoading && !mediaError ? (
                  <p className="ds-emptyLine">Nenhum post ou reel publicado neste período.</p>
                ) : null}
                {organicContent.stories.length > 0 && organicContent.storyWithInsightsCount === 0 ? (
                  <p className="ds-footnote">Insights históricos de Stories indisponíveis para este período.</p>
                ) : null}
              </section>

              <MetaBlockBoundary resetKey={`monthly:${metaRenderKey}`} title="Conteúdo por mês" description="Série mensal de conteúdo">
                <section ref={monthlyDemand.observe} data-testid="monthly-demand" className="ds-section ds-chartSection" aria-labelledby="instagram-monthly-title">
                  <div className="ds-sectionHead">
                    <div className="ds-sectionHeadText">
                      <h3 id="instagram-monthly-title" className="ds-sectionTitle">{monthlyTitle}</h3>
                      <p className="ds-caption">Conteúdo por mês dentro do período selecionado{monthlyLastUpdatedLabel ? ` · ${freshness(monthlyLastUpdatedLabel)}` : ""}.</p>
                    </div>
                    {monthlyRowsForChart.length > 1 ? (
                      <p className="ds-chartKey" aria-hidden="true">
                        <span className="is-line">Alcance</span>
                        <span className="is-bar">Publicações</span>
                        <span>por mês</span>
                      </p>
                    ) : null}
                  </div>
                  {monthlyRowsForChart.length > 1 ? (
                    <TrendChart
                      data={monthlyRowsForChart}
                      xKey="month"
                      primaryKey="reach"
                      secondaryKey="posts"
                      formatX={(value) => monthLabelPt(value)}
                      formatY={formatCompactInteger}
                      ariaLabel="Alcance e publicações do Instagram por mês."
                      testId="instagram-monthly-chart"
                      renderTooltip={(row) => (
                        <>
                          <strong>{monthLabelPt(row.month)}</strong>
                          <dl>
                            <dt>Alcance</dt><dd>{formatInteger(row.reach)}</dd>
                            <dt>Publicações</dt><dd>{formatInteger(row.posts)}</dd>
                          </dl>
                        </>
                      )}
                    />
                  ) : monthlyPanelLoading ? (
                    <p className="ds-status" role="status">Montando o histórico mensal...</p>
                  ) : monthlyError ? (
                    <DataNotice tone="negative" title="Série mensal indisponível">A série mensal não ficou disponível agora.</DataNotice>
                  ) : (
                    <p className="ds-emptyLine">O histórico mensal aparece quando houver mais de um mês com publicações.</p>
                  )}
                </section>

                {months.length > 1 && a && b ? (
                  <section className="ds-section" aria-labelledby="instagram-compare-title">
                    <div className="ds-sectionHead">
                      <h3 id="instagram-compare-title" className="ds-sectionTitle">Comparar meses</h3>
                      <div className="ds-customPeriod">
                        <label className="ds-field">
                          <span>Mês de referência</span>
                          <select value={monthA} onChange={(event) => setMonthA(event.target.value)} disabled={!enableExtrasStage}>
                            {months.map((month) => <option key={month} value={month}>{monthLabelPt(month)}</option>)}
                          </select>
                        </label>
                        <label className="ds-field">
                          <span>Mês comparado</span>
                          <select value={monthB} onChange={(event) => setMonthB(event.target.value)} disabled={!enableExtrasStage}>
                            {months.map((month) => <option key={month} value={month}>{monthLabelPt(month)}</option>)}
                          </select>
                        </label>
                      </div>
                    </div>
                    <div className="ds-tableWrap">
                      <table className="ds-table">
                        <thead>
                          <tr>
                            <th scope="col">Métrica</th>
                            <th scope="col" className="is-number">{monthLabelPt(monthA)}</th>
                            <th scope="col" className="is-number">{monthLabelPt(monthB)}</th>
                            <th scope="col" className="is-number">Variação</th>
                          </tr>
                        </thead>
                        <tbody>
                          {MONTH_COMPARE_ROWS.map((row) => (
                            <tr key={row.key}>
                              <td className="is-primary">{row.label}</td>
                              <td className="is-number">{formatInteger(a[row.key])}</td>
                              <td className="is-number">{formatInteger(b[row.key])}</td>
                              {/* Sem base no mês de referência: "—", nunca 0% ou 100% inventados. */}
                              <td className="is-number"><Delta change={a[row.key] > 0 ? pct(b[row.key], a[row.key]) : null} reference={monthLabelPt(monthA)} /></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </section>
                ) : null}
              </MetaBlockBoundary>

              <MetaBlockBoundary resetKey={`comments:${metaRenderKey}`} title="Comentários" description="Comentários e palavras mais citadas">
                <div ref={commentsDemand.observe} data-testid="comments-demand">
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
                </div>
              </MetaBlockBoundary>
            </div>
          ) : instagramConnected ? (
            <DataNotice
              role="status"
              title={dashError ? "Instagram indisponível" : organicEverHadData ? "Ainda não há dados do Instagram para este período" : "Ainda não há dados do Instagram"}
              tone={dashError ? "negative" : "neutral"}
            >
              {dashError
                ? "Não foi possível carregar as métricas do Instagram agora."
                : "A conta está conectada e os números aparecem aqui quando houver publicações com alcance no período."}
            </DataNotice>
          ) : paidHasData ? (
            <p className="ds-footnote">Instagram não conectado: a página mostra só Meta Ads desta empresa.</p>
          ) : null}
        </MetaBlockBoundary>
        </div>
        {SHOW_PRESENTATION_EXTRAS ? (
          <MetaBlockBoundary resetKey={`notes:${metaRenderKey}`} title="Notas do cliente" description="Anotações internas da conta">
            <NotesPanel
              notes={deferredNotes}
              loading={loadingNotes}
              available={notesAvailable}
              message={notesMessage}
              error={notesError}
              onCreate={handleCreateNote}
              onUpdate={handleUpdateNote}
            />
          </MetaBlockBoundary>
        ) : null}
      </div>
    </Shell>
    </PeriodTransition>
  );
}
