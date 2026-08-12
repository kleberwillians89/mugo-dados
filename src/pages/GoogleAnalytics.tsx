import { useCallback, useEffect, useMemo, useState } from "react";
import "../app/chartSetup";
import { Line } from "react-chartjs-2";
import type { ChartData, ChartOptions } from "chart.js";

import Shell from "../components/Shell";
import DashboardHeader from "../components/dashboard/DashboardHeader";
import useDashboardGa4 from "../hooks/dashboard/useDashboardGa4";
import { syncGa4 } from "../app/api";
import { describeSyncError, isSyncAlreadyRunningError, runExclusiveSync } from "../app/syncOrchestrator";
import {
  getCampaignDisplayName,
  getGa4ChannelLabel,
  getGa4EventLabel,
  getGa4EventTechnicalDetail,
} from "../app/ga4Labels";
import { usePeriod } from "../app/PeriodContext";
import { formatSelectedPeriodLabel, getSelectedPeriodRange } from "../app/periodRange";
import type {
  Ga4CampaignRow,
  Ga4ChannelRow,
  Ga4DailyStatRow,
  Ga4EventGroup,
  Ga4EventRow,
  Ga4ReportResponse,
} from "../app/types";
import {
  getActiveClientId,
  getActiveClientName,
  getActiveClientConfigurationWarning,
} from "../app/activeClient";
import { CHART_COLORS, formatDatePtBr, formatFullNumber } from "../components/dashboard/chartTheme";
import ChannelTodaySummary from "../components/dashboard/ChannelTodaySummary";
import { coveredShopifyDay } from "../components/dashboard/shopifyCoverage";
import PerformanceChart from "../components/dashboard/PerformanceChart";
import StoreMediaSummary from "../components/dashboard/StoreMediaSummary";
import { useDashboardSnapshot } from "../app/DashboardDataContext";

import "../styles/dashboard.css";
import "../styles/google-analytics.css";

type Props = {
  onLogout: () => void | Promise<void>;
  onOpenDashboard: () => void;
  isAuthenticated?: boolean;
};

type PeriodPreset = "7d" | "30d" | "month" | "specific";

function toDateInput(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function todayDateInput() {
  const now = new Date();
  return {
    month: now.getMonth() + 1,
    year: now.getFullYear(),
  };
}

function resolveInitialPreset(start: string, end: string, days: number): PeriodPreset {
  const now = new Date();
  const currentMonthStart = toDateInput(new Date(now.getFullYear(), now.getMonth(), 1));
  const today = toDateInput(now);

  if (days === 7) return "7d";
  if (days === 30) return "30d";
  if (start === currentMonthStart && end === today) return "month";
  return "specific";
}

function toErrorMessage(error: unknown) {
  console.warn("[google-ga4]", error);
  return "Não foi possível atualizar os dados agora. Tente novamente em instantes.";
}

function formatPct(value: number) {
  return `${Number.isFinite(value) ? value.toFixed(value >= 10 ? 0 : 1) : "0.0"}%`;
}

function formatUpdatedAtLabel(value: string | null | undefined): string | null {
  const raw = String(value || "").trim();
  if (!raw) return null;
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function hasGa4Data(report: Ga4ReportResponse | null) {
  if (!report) return false;
  return (
    report.summary.sessions > 0 ||
    report.summary.event_count > 0
  );
}

function resolveInitialGa4ClientId() {
  return getActiveClientId();
}

function uniqueGa4Options(values: Array<string | null | undefined>) {
  return Array.from(
    new Set(
      values
        .map((value) => String(value || "").trim())
        .filter(Boolean)
    )
  ).sort((left, right) => left.localeCompare(right, "pt-BR"));
}

function shortDateLabel(value: string) {
  const parsed = new Date(`${String(value || "").trim()}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
  });
}

function GoogleMetricCard({
  label,
  value,
  hint,
  accent = false,
}: {
  label: string;
  value: string;
  hint: string;
  accent?: boolean;
}) {
  return (
    <article className={`googleKpiCard ${accent ? "isAccent" : ""}`.trim()}>
      <div className="googleKpiLabel">{label}</div>
      <div className="googleKpiValue">{value}</div>
      <div className="googleKpiHint">{hint}</div>
    </article>
  );
}

function GoogleGroupTable({
  group,
  emptyMessage,
}: {
  group: Ga4EventGroup;
  emptyMessage: string;
}) {
  return (
    <article className="ga4GroupCard googleGroupCard cardWide">
      <div className="ga4GroupHead">
        <div>
          <div className="h1">{group.title}</div>
          <div className="p">{group.description}</div>
        </div>
        <div className="ga4GroupSummary">
          <span>{formatFullNumber(group.total_events)} ocorrências</span>
          <span>{formatFullNumber(group.total_users)} usuários</span>
        </div>
      </div>

      {group.items.length ? (
        <div className="tableWrap ga4TableWrap">
          <table className="table ga4GroupTable">
            <thead>
              <tr>
                <th>Evento</th>
                <th>Ocorrências</th>
                <th>Usuários</th>
              </tr>
            </thead>
            <tbody>
              {group.items.map((item) => (
                <tr key={item.event_name}>
                  <td>
                    <div className="cellTitle">{item.label}</div>
                    {item.description ? <div className="cellMuted">{item.description}</div> : null}
                  </td>
                  <td>{formatFullNumber(item.event_count)}</td>
                  <td>{formatFullNumber(item.total_users)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="googleEmptyCard">{emptyMessage}</div>
      )}
    </article>
  );
}

function GoogleTopList({
  title,
  description,
  items,
  emptyMessage,
}: {
  title: string;
  description: string;
  items: Array<{
    id: string;
    label: string;
    meta: string;
    value: string;
    subvalue: string;
  }>;
  emptyMessage: string;
}) {
  return (
    <article className="googleListCard">
      <div className="googleListHead">
        <div>
          <div className="googleMiniLabel">{title}</div>
          <p className="googleChartDescription">{description}</p>
        </div>
      </div>

      {items.length ? (
        <div className="googleListRows">
          {items.map((item, index) => (
            <div key={item.id} className="googleListRow">
              <div className="googleListRank">{String(index + 1).padStart(2, "0")}</div>
              <div className="googleListBody">
                <div className="googleTableTitle">{item.label}</div>
                <div className="googleTableSubtle">{item.meta}</div>
              </div>
              <div className="googleListMetric">
                <strong>{item.value}</strong>
                <span>{item.subvalue}</span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="googleEmptyCard">{emptyMessage}</div>
      )}
    </article>
  );
}

function GoogleDailyTable({ rows }: { rows: Ga4DailyStatRow[] }) {
  if (!rows.length) {
    return <div className="googleEmptyCard">Sem dados no período.</div>;
  }
  return (
    <article className="googleListCard googleTableCard">
      <div className="tableWrap googleDataTableWrap">
        <table className="table googleDataTable">
          <thead>
            <tr>
              <th>Data</th>
              <th>Sessões</th>
              <th>Usuários ativos</th>
              <th>Usuários totais</th>
              <th>Eventos</th>
              <th>Evento purchase GA4</th>
              <th>View item</th>
              <th>Add cart</th>
              <th>Checkout</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.date}>
                <td>{formatDatePtBr(row.date)}</td>
                <td>{formatFullNumber(row.sessions)}</td>
                <td>{formatFullNumber(row.active_users)}</td>
                <td>{formatFullNumber(row.total_users)}</td>
                <td>{formatFullNumber(row.event_count)}</td>
                <td>{formatFullNumber(row.purchase_count || row.ecommerce_purchases)}</td>
                <td>{formatFullNumber(row.view_item_count)}</td>
                <td>{formatFullNumber(row.add_to_cart_count)}</td>
                <td>{formatFullNumber(row.begin_checkout_count)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function GoogleChannelsTable({ rows }: { rows: Ga4ChannelRow[] }) {
  if (!rows.length) {
    return <div className="googleEmptyCard">Sem dados no período.</div>;
  }
  return (
    <article className="googleListCard googleTableCard">
      <div className="tableWrap googleDataTableWrap">
        <table className="table googleDataTable">
          <thead>
            <tr>
              <th>Canal</th>
              <th>Source</th>
              <th>Medium</th>
              <th>Sessões</th>
              <th>Usuários ativos</th>
              <th>Usuários totais</th>
              <th>Eventos</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.source_medium}-${row.source}-${row.medium}`}>
                <td>
                  <div className="cellTitle">{getGa4ChannelLabel(row.source_medium)}</div>
                </td>
                <td>{row.source || "-"}</td>
                <td>{row.medium || "-"}</td>
                <td>{formatFullNumber(row.sessions)}</td>
                <td>{formatFullNumber(row.active_users)}</td>
                <td>{formatFullNumber(row.total_users)}</td>
                <td>{formatFullNumber(row.event_count)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function GoogleCampaignsTable({ rows }: { rows: Ga4CampaignRow[] }) {
  if (!rows.length) {
    return <div className="googleEmptyCard">Sem dados no período.</div>;
  }
  return (
    <article className="googleListCard googleTableCard">
      <div className="tableWrap googleDataTableWrap">
        <table className="table googleDataTable">
          <thead>
            <tr>
              <th>Campanha</th>
              <th>Origem / mídia</th>
              <th>Sessões</th>
              <th>Usuários ativos</th>
              <th>Usuários totais</th>
              <th>Eventos</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.campaign_name}-${row.source_medium}`}>
                <td>
                  <div className="cellTitle">
                    {getCampaignDisplayName(row.campaign_name, { source: row.source, medium: row.medium })}
                  </div>
                  <div className="cellMuted">{row.source || "-"} / {row.medium || "-"}</div>
                </td>
                <td>{getGa4ChannelLabel(row.source_medium) || "-"}</td>
                <td>{formatFullNumber(row.sessions)}</td>
                <td>{formatFullNumber(row.active_users)}</td>
                <td>{formatFullNumber(row.total_users)}</td>
                <td>{formatFullNumber(row.event_count)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function GoogleEventsTable({ rows }: { rows: Ga4EventRow[] }) {
  if (!rows.length) {
    return <div className="googleEmptyCard">Sem dados no período.</div>;
  }
  return (
    <article className="googleListCard googleTableCard">
      <div className="tableWrap googleDataTableWrap">
        <table className="table googleDataTable">
          <thead>
            <tr>
              <th>Evento</th>
              <th>Ocorrências</th>
              <th>Usuários</th>
              <th>Primeira leitura</th>
              <th>Última leitura</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.event_name}>
                <td>
                  <div className="cellTitle">
                    {row.label && row.label !== row.event_name ? row.label : getGa4EventLabel(row.event_name)}
                  </div>
                  {row.description ? (
                    <div className="cellMuted">{row.description}</div>
                  ) : getGa4EventTechnicalDetail(row.event_name) ? (
                    <div className="cellMuted">{getGa4EventTechnicalDetail(row.event_name)}</div>
                  ) : null}
                </td>
                <td>{formatFullNumber(row.event_count)}</td>
                <td>{formatFullNumber(row.total_users)}</td>
                <td>{row.first_seen_at ? formatDatePtBr(row.first_seen_at.slice(0, 10)) : "-"}</td>
                <td>{row.last_seen_at ? formatDatePtBr(row.last_seen_at.slice(0, 10)) : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function GoogleAnalyticsSkeleton() {
  return (
    <div className="googleSkeletonLayout" aria-hidden="true">
      <div className="googleSkeletonHero skeleton" />
      <div className="googleSkeletonGrid">
        {Array.from({ length: 6 }).map((_, index) => (
          <div key={index} className="googleSkeletonCard skeleton" />
        ))}
      </div>
      <div className="googleSkeletonCharts">
        <div className="googleSkeletonChart skeleton" />
        <div className="googleSkeletonChart skeleton" />
      </div>
      <div className="googleSkeletonTall skeleton" />
      <div className="googleSkeletonTall skeleton" />
      <div className="googleSkeletonTall skeleton" />
    </div>
  );
}

export default function GoogleAnalytics({
  onLogout,
  onOpenDashboard,
  isAuthenticated = false,
}: Props) {
  const { period, periodDays, setCurrentMonthPeriod, setMonthPeriod, setPresetPeriod } = usePeriod();
  const [preset, setPreset] = useState<PeriodPreset>(() =>
    resolveInitialPreset(period.start, period.end, periodDays)
  );
  const initialDate = todayDateInput();
  const [selectedMonth, setSelectedMonth] = useState(initialDate.month);
  const [selectedYear, setSelectedYear] = useState(initialDate.year);
  const [selectedGa4ClientId, setSelectedGa4ClientId] = useState(resolveInitialGa4ClientId);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [ga4Tab, setGa4Tab] = useState<"overview" | "acquisition" | "behavior">("overview");
  const [channelFilter, setChannelFilter] = useState("");
  const [sourceMediumFilter, setSourceMediumFilter] = useState("");
  const [campaignFilter, setCampaignFilter] = useState("");
  const [platformFilter, setPlatformFilter] = useState("");
  const [deviceFilter, setDeviceFilter] = useState("");
  const [syncing, setSyncing] = useState(false);
  const activeGa4ClientId = selectedGa4ClientId || getActiveClientId();
  const activeGa4ClientName = getActiveClientName();
  const selectedRange = useMemo(
    () => getSelectedPeriodRange(period, selectedMonth, selectedYear),
    [period, selectedMonth, selectedYear]
  );

  const {
    ga4Report,
    loadingGa4,
    refreshingGa4,
    ga4Error,
    ga4UpdatedAt,
    reloadGa4,
  } = useDashboardGa4({
    isAuthenticated,
    activeClientId: activeGa4ClientId,
    period: selectedRange,
  });
  const adsModel = useDashboardSnapshot(selectedRange.start, selectedRange.end);
  const googleAds = useMemo(() => {
    const rows = adsModel.daily;
    const available = rows.some((row) =>
      row.google_ads_spend != null || row.google_ads_conversion_value != null || row.google_ads_conversions != null
    );
    if (!available) return null;
    const spend = rows.reduce((total, row) => total + Number(row.google_ads_spend || 0), 0);
    const revenue = rows.reduce((total, row) => total + Number(row.google_ads_conversion_value || 0), 0);
    const conversions = rows.reduce((total, row) => total + Number(row.google_ads_conversions || 0), 0);
    return {
      spend,
      revenue,
      conversions,
      attributedRoas: spend > 0 ? revenue / spend : null,
      ticket: conversions > 0 ? revenue / conversions : null,
      daily: rows.map((row) => ({
        date: row.metric_date,
        spend: row.google_ads_spend,
        revenue: row.google_ads_conversion_value,
        conversions: row.google_ads_conversions,
        impressions: row.google_ads_impressions,
        clicks: row.google_ads_clicks,
        reach: null,
        cpc: row.google_ads_spend != null && row.google_ads_clicks ? row.google_ads_spend / row.google_ads_clicks : null,
        cpm: row.google_ads_spend != null && row.google_ads_impressions ? row.google_ads_spend * 1000 / row.google_ads_impressions : null,
        ctr: row.google_ads_clicks != null && row.google_ads_impressions ? row.google_ads_clicks * 100 / row.google_ads_impressions : null,
        roas: row.google_ads_spend != null && row.google_ads_spend > 0 && row.shopify_net_revenue != null
          ? row.shopify_net_revenue / row.google_ads_spend : null,
      })),
    };
  }, [adsModel.daily]);
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(new Date());
  const googleAdsUpdatedAt = formatUpdatedAtLabel(adsModel.sources.find((source) => source.provider === "google_ads")?.last_success_at);
  const shopifyStore = useMemo(() => {
    const rows = adsModel.daily.filter((row) => row.shopify_net_revenue != null || row.shopify_orders != null);
    const source = adsModel.sources.find((item) => item.provider === "shopify");
    if (!source && !rows.length) return null;
    const revenue = rows.reduce((total, row) => total + Number(row.shopify_net_revenue || 0), 0);
    const orders = rows.reduce((total, row) => total + Number(row.shopify_orders || 0), 0);
    return { revenue, orders, ticket: orders > 0 ? revenue / orders : 0, coverage: source?.data_max_available || null };
  }, [adsModel.daily, adsModel.sources]);
  const shopifyToday = adsModel.daily.find((row) => row.metric_date === today);
  useEffect(() => {
    if (selectedGa4ClientId === activeGa4ClientId) return;
    setSelectedGa4ClientId(activeGa4ClientId);
  }, [activeGa4ClientId, selectedGa4ClientId]);

  useEffect(() => {
    const startDate = new Date(`${period.start}T00:00:00`);
    if (Number.isNaN(startDate.getTime())) return;
    setSelectedMonth(startDate.getMonth() + 1);
    setSelectedYear(startDate.getFullYear());
    setPreset(resolveInitialPreset(period.start, period.end, periodDays));
  }, [period.end, period.start, periodDays]);

  const years = useMemo(() => {
    const currentYear = new Date().getFullYear();
    return Array.from({ length: 5 }).map((_, index) => currentYear - index);
  }, []);

  const hasData = hasGa4Data(ga4Report);
  const combinedError = refreshError || ga4Error;
  const configWarning = getActiveClientConfigurationWarning();
  const lastSyncedLabel =
    formatUpdatedAtLabel(ga4Report?.meta.last_synced_at) || formatUpdatedAtLabel(ga4UpdatedAt);
  const pagePeriodLabel = `${formatDatePtBr(selectedRange.start)} - ${formatDatePtBr(selectedRange.end)}`;

  const dailyRows = useMemo(() => ga4Report?.trends.daily || [], [ga4Report?.trends.daily]);
  const trafficChartData = useMemo<ChartData<"line">>(
    () => ({
      labels: dailyRows.map((row) => shortDateLabel(row.date)),
      datasets: [
        {
          label: "Sessões",
          data: dailyRows.map((row) => row.sessions),
          borderColor: "#1a1718",
          backgroundColor: "rgba(26,23,24,.14)",
          borderWidth: 2.5,
          tension: 0.35,
          pointRadius: 0,
          pointHoverRadius: 4,
          fill: true,
        },
        {
          label: "Usuários ativos",
          data: dailyRows.map((row) => row.active_users),
          borderColor: "#c79830",
          backgroundColor: "rgba(199,152,48,.12)",
          borderWidth: 2,
          tension: 0.35,
          pointRadius: 0,
          pointHoverRadius: 4,
          fill: false,
        },
      ],
    }),
    [dailyRows]
  );

  const lineOptions = useMemo<ChartOptions<"line">>(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "top",
          align: "start",
          labels: {
            boxWidth: 12,
            color: CHART_COLORS.axis,
            font: {
              weight: 700,
            },
          },
        },
        tooltip: {
          backgroundColor: CHART_COLORS.tooltipBg,
          borderColor: CHART_COLORS.tooltipBorder,
          borderWidth: 1,
          titleColor: CHART_COLORS.tooltipText,
          bodyColor: CHART_COLORS.tooltipText,
        },
      },
      scales: {
        x: {
          grid: {
            display: false,
          },
          ticks: {
            color: CHART_COLORS.axis,
          },
        },
        y: {
          beginAtZero: true,
          grid: {
            color: CHART_COLORS.grid,
          },
          ticks: {
            color: CHART_COLORS.axis,
          },
        },
      },
    }),
    []
  );

  const filteredChannels = useMemo(() => {
    const channelNeedle = channelFilter.trim().toLowerCase();
    const sourceNeedle = sourceMediumFilter.trim().toLowerCase();
    const platformNeedle = platformFilter.trim().toLowerCase();
    const deviceNeedle = deviceFilter.trim().toLowerCase();
    return (ga4Report?.channels || []).filter((row) => {
      const dynamic = row as Ga4ChannelRow & { platform?: string; device?: string; device_category?: string };
      return (
        (!channelNeedle || String(row.source_medium || "").toLowerCase().includes(channelNeedle)) &&
        (!sourceNeedle || `${row.source || ""} ${row.medium || ""} ${row.source_medium || ""}`.toLowerCase().includes(sourceNeedle)) &&
        (!platformNeedle || String(dynamic.platform || "").toLowerCase().includes(platformNeedle)) &&
        (!deviceNeedle || `${dynamic.device || ""} ${dynamic.device_category || ""}`.toLowerCase().includes(deviceNeedle))
      );
    });
  }, [channelFilter, deviceFilter, ga4Report?.channels, platformFilter, sourceMediumFilter]);

  const filteredCampaigns = useMemo(() => {
    const campaignNeedle = campaignFilter.trim().toLowerCase();
    const sourceNeedle = sourceMediumFilter.trim().toLowerCase();
    const platformNeedle = platformFilter.trim().toLowerCase();
    const deviceNeedle = deviceFilter.trim().toLowerCase();
    return (ga4Report?.campaigns || []).filter((row) => {
      const dynamic = row as Ga4CampaignRow & { platform?: string; device?: string; device_category?: string };
      return (
        (!campaignNeedle || String(row.campaign_name || "").toLowerCase().includes(campaignNeedle)) &&
        (!sourceNeedle || `${row.source || ""} ${row.medium || ""} ${row.source_medium || ""}`.toLowerCase().includes(sourceNeedle)) &&
        (!platformNeedle || String(dynamic.platform || "").toLowerCase().includes(platformNeedle)) &&
        (!deviceNeedle || `${dynamic.device || ""} ${dynamic.device_category || ""}`.toLowerCase().includes(deviceNeedle))
      );
    });
  }, [campaignFilter, deviceFilter, ga4Report?.campaigns, platformFilter, sourceMediumFilter]);
  const channelOptions = useMemo(
    () => uniqueGa4Options((ga4Report?.channels || []).map((row) => row.source_medium)),
    [ga4Report?.channels]
  );
  const sourceMediumOptions = useMemo(
    () =>
      uniqueGa4Options([
        ...(ga4Report?.channels || []).map((row) => row.source_medium || `${row.source || ""} / ${row.medium || ""}`),
        ...(ga4Report?.campaigns || []).map((row) => row.source_medium || `${row.source || ""} / ${row.medium || ""}`),
      ]),
    [ga4Report?.campaigns, ga4Report?.channels]
  );
  const campaignOptions = useMemo(
    () => uniqueGa4Options((ga4Report?.campaigns || []).map((row) => row.campaign_name)),
    [ga4Report?.campaigns]
  );
  const platformOptions = useMemo(
    () =>
      uniqueGa4Options([
        ...(ga4Report?.channels || []).map((row) => (row as Ga4ChannelRow & { platform?: string }).platform),
        ...(ga4Report?.campaigns || []).map((row) => (row as Ga4CampaignRow & { platform?: string }).platform),
      ]),
    [ga4Report?.campaigns, ga4Report?.channels]
  );
  const deviceOptions = useMemo(
    () =>
      uniqueGa4Options([
        ...(ga4Report?.channels || []).flatMap((row) => {
          const dynamic = row as Ga4ChannelRow & { device?: string; device_category?: string };
          return [dynamic.device, dynamic.device_category];
        }),
        ...(ga4Report?.campaigns || []).flatMap((row) => {
          const dynamic = row as Ga4CampaignRow & { device?: string; device_category?: string };
          return [dynamic.device, dynamic.device_category];
        }),
      ]),
    [ga4Report?.campaigns, ga4Report?.channels]
  );

  const topChannels = useMemo(
    () =>
      [...filteredChannels]
        .sort((a, b) => b.sessions - a.sessions)
        .slice(0, 5)
        .map((row: Ga4ChannelRow) => ({
          id: row.source_medium || `${row.source || "source"}-${row.medium || "medium"}`,
          label: getGa4ChannelLabel(row.source_medium),
          meta: `${formatFullNumber(row.total_users)} usuários • ${formatFullNumber(row.event_count)} eventos`,
          value: `${formatFullNumber(row.sessions)} sessões`,
          subvalue: `${formatFullNumber(row.active_users)} usuários ativos`,
        })),
    [filteredChannels]
  );

  const topCampaigns = useMemo(
    () =>
      [...filteredCampaigns]
        .sort((a, b) => b.sessions - a.sessions)
        .slice(0, 5)
        .map((row: Ga4CampaignRow) => ({
          id: `${row.campaign_name}-${row.source_medium || "campaign"}`,
          label: getCampaignDisplayName(row.campaign_name, { source: row.source, medium: row.medium }),
          meta: `${getGa4ChannelLabel(row.source_medium)} • ${formatFullNumber(row.event_count)} eventos`,
          value: `${formatFullNumber(row.sessions)} sessões`,
          subvalue: `${formatFullNumber(row.active_users)} usuários ativos`,
        })),
    [filteredCampaigns]
  );

  const handleRefresh = useCallback(async () => {
    setRefreshError(null);
    setSyncing(true);
    try {
      await runExclusiveSync(
        { clientId: activeGa4ClientId, provider: "ga4" },
        () =>
          syncGa4({
            start: selectedRange.start,
            end: selectedRange.end,
            days: periodDays,
          }, {
            clientId: activeGa4ClientId,
          })
      );
      await reloadGa4({ force: true });
    } catch (error: unknown) {
      setRefreshError(isSyncAlreadyRunningError(error) ? describeSyncError(error, "") : toErrorMessage(error));
    } finally {
      setSyncing(false);
    }
  }, [activeGa4ClientId, periodDays, reloadGa4, selectedRange.end, selectedRange.start]);

  function handlePresetChange(nextPreset: PeriodPreset) {
    setPreset(nextPreset);
    if (nextPreset === "7d") {
      setPresetPeriod(7);
      return;
    }
    if (nextPreset === "30d") {
      setPresetPeriod(30);
      return;
    }
    if (nextPreset === "month") {
      setCurrentMonthPeriod();
      return;
    }
    setMonthPeriod(selectedYear, selectedMonth);
  }

  function handleMonthChange(nextMonth: number) {
    setSelectedMonth(nextMonth);
    setPreset("specific");
    setMonthPeriod(selectedYear, nextMonth);
  }

  function handleYearChange(nextYear: number) {
    setSelectedYear(nextYear);
    setPreset("specific");
    setMonthPeriod(nextYear, selectedMonth);
  }

  if (!isAuthenticated) {
    return null;
  }

  return (
    <Shell
      themeClass="theme-client"
      title=""
      right={
        <DashboardHeader
          activeView="google"
          backgroundRefreshing={refreshingGa4}
          onLogout={onLogout}
          onOpenGoogleAnalytics={() => {}}
          onOpenMeta={onOpenDashboard}
          onRefresh={handleRefresh}
          onSelectPeriodPreset={(nextPreset) => handlePresetChange(nextPreset)}
          periodPreset={preset === "specific" ? "custom" : preset}
          refreshing={syncing}
          statusChips={[
            {
              connected: Boolean(ga4Report),
              label: `${ga4Report ? "GA4 com dados" : "GA4 aguardando dados"}${lastSyncedLabel ? ` • ${lastSyncedLabel}` : ""}`,
            },
          ]}
        />
      }
    >
      <div className="googleReportPage">
        {configWarning ? <div className="googleFeedbackCard isWarning">{configWarning}</div> : null}
        <section className="googleHero">
          <div className="googleHeroCopy">
            <div className="googlePageEyebrow">Google Analytics 4</div>
            <h1 className="googlePageTitle">Google Analytics 4</h1>
            <p className="googlePageSubtitle">
              Visão clara do comportamento do site, da jornada comercial e dos sinais de merchandising da{" "}
              {activeGa4ClientName}. Dados provenientes do Google Analytics 4.
            </p>
            <div className="googleHeroMeta">
              <span className="pill">{pagePeriodLabel}</span>
              <span className="pill">Fonte: GA4 · {formatSelectedPeriodLabel(selectedRange)}</span>
              <span className="googleHeroTimestamp">
                Última leitura: {lastSyncedLabel || "aguardando sincronização"}
              </span>
            </div>
            <div className="googleTabs" role="tablist" aria-label="Seções do Analytics">
              <button type="button" role="tab" aria-selected={ga4Tab === "overview"} className={`googleTab${ga4Tab === "overview" ? " is-active" : ""}`} onClick={() => setGa4Tab("overview")}>
                Visão geral
              </button>
              <button type="button" role="tab" aria-selected={ga4Tab === "acquisition"} className={`googleTab${ga4Tab === "acquisition" ? " is-active" : ""}`} onClick={() => setGa4Tab("acquisition")}>
                Aquisição
              </button>
              <button type="button" role="tab" aria-selected={ga4Tab === "behavior"} className={`googleTab${ga4Tab === "behavior" ? " is-active" : ""}`} onClick={() => setGa4Tab("behavior")}>
                Comportamento
              </button>
            </div>
            <p className="googleAttributionNotice">
              Fonte: Google Analytics 4. Os valores de receita seguem a atribuição do GA4 e podem diferir da loja e das plataformas de mídia.
            </p>
          </div>

          <div className="googleFilterCard">
            <label className="googleFilterField">
              <span>Período</span>
              <select
                className="select"
                value={preset}
                onChange={(event) => handlePresetChange(event.target.value as PeriodPreset)}
              >
                <option value="7d">Últimos 7 dias</option>
                <option value="30d">Últimos 30 dias</option>
                <option value="month">Mês atual</option>
                <option value="specific">Mês específico</option>
              </select>
            </label>

            <label className="googleFilterField">
              <span>Mês</span>
              <select
                className="select"
                value={selectedMonth}
                onChange={(event) => handleMonthChange(Number(event.target.value))}
              >
                {Array.from({ length: 12 }).map((_, index) => {
                  const month = index + 1;
                  return (
                    <option key={month} value={month}>
                      {new Date(2026, index, 1).toLocaleDateString("pt-BR", { month: "long" })}
                    </option>
                  );
                })}
              </select>
            </label>

            <label className="googleFilterField">
              <span>Ano</span>
              <select
                className="select"
                value={selectedYear}
                onChange={(event) => handleYearChange(Number(event.target.value))}
              >
                {years.map((year) => (
                  <option key={year} value={year}>
                    {year}
                  </option>
                ))}
              </select>
            </label>

            <div className="googleStatusLine">
              {syncing || refreshingGa4
                ? "Sincronizando dados do GA4..."
                : hasData
                  ? "GA4 com dados carregados para o período."
                  : "GA4 carregado, mas sem dados relevantes neste período."}
            </div>

          </div>
        </section>

        <section className="googleSection googleCommercialSection" aria-labelledby="google-commercial-title">
          <div className="sectionHeader">
            <div><div className="googlePageEyebrow">Resultado</div><div className="h1" id="google-commercial-title">Performance Google Ads</div></div>
            <span className="dashboardTimestamp">{googleAdsUpdatedAt ? `Atualizado em ${googleAdsUpdatedAt}` : "Aguardando sincronização"}</span>
          </div>
          <StoreMediaSummary
            channel="Google"
            store={{ revenue: shopifyStore?.revenue ?? null, orders: shopifyStore?.orders ?? null, ticket: shopifyStore?.ticket ?? null }}
            media={{
              spend: googleAds?.spend ?? null,
              roas: googleAds?.spend && shopifyStore?.revenue != null ? shopifyStore.revenue / googleAds.spend : null,
              attributedRoas: googleAds?.attributedRoas ?? null,
              attributedRevenue: googleAds?.revenue ?? null,
              attributedOrders: googleAds?.conversions ?? null,
            }}
            roasBasis="shopify"
          />
          {selectedRange.start <= today && selectedRange.end >= today ? <ChannelTodaySummary
            date={today}
            value={coveredShopifyDay(shopifyStore?.coverage, today, {
              revenue: shopifyToday?.shopify_net_revenue,
              orders: shopifyToday?.shopify_orders,
            })}
          /> : null}
          {googleAds ? <PerformanceChart daily={googleAds.daily} source="Google Ads" /> : null}
        </section>

        {loadingGa4 && !ga4Report ? <GoogleAnalyticsSkeleton /> : null}

        {combinedError && !ga4Report ? (
          <div className="googleFeedbackCard isError">
            Não foi possível carregar os dados do Google Analytics agora. Tente atualizar em instantes.
          </div>
        ) : null}

        {ga4Report ? (
          <>
            {!hasData ? (
              <div className="googleFeedbackCard">
                Sem dados no período.
              </div>
            ) : null}

            {combinedError && hasData ? (
              <div className="googleFeedbackCard isWarning">
                Atualização parcial: a última base carregada continua visível.
              </div>
            ) : null}

            {ga4Tab === "overview" ? (
            <section className="googleSection" id="google-summary">
              <div className="sectionHeader">
                <div>
                  <div className="h1">Visão geral GA4</div>
                  <div className="p">Resumo executivo de tráfego, base de usuários e eventos observados no GA4.</div>
                </div>
                {lastSyncedLabel ? (
                  <div className="dashboardSectionMeta">
                    <span className="dashboardTimestamp">Atualizado em {lastSyncedLabel}</span>
                  </div>
                ) : null}
              </div>

              <div className="googleKpiGrid">
                <GoogleMetricCard
                  label="Sessões"
                  value={formatFullNumber(ga4Report.summary.sessions)}
                  hint={`${periodDays} dias analisados`}
                />
                <GoogleMetricCard
                  label="Usuários ativos"
                  value={formatFullNumber(ga4Report.summary.active_users)}
                  hint={`${formatFullNumber(ga4Report.summary.average_daily_active_users)} em média por dia`}
                />
                <GoogleMetricCard
                  label="Usuários totais"
                  value={formatFullNumber(ga4Report.summary.total_users)}
                  hint="Base total identificada no período"
                />
                <GoogleMetricCard
                  label="Eventos"
                  value={formatFullNumber(ga4Report.summary.event_count)}
                  hint={`${formatPct(
                    ga4Report.summary.sessions
                      ? (ga4Report.summary.event_count / ga4Report.summary.sessions) * 100
                      : 0
                  )} de eventos por 100 sessões`}
                />
              </div>

              <div className="googleChartGrid">
                <article className="googleChartCard">
                  <div className="googleChartCardHead">
                    <div>
                      <div className="googleMiniLabel">Tendência diária</div>
                      <p className="googleChartDescription">
                        Sessões e usuários ativos para entender o ritmo do site ao longo do período.
                      </p>
                    </div>
                    <div className="googleChartValue">{formatFullNumber(ga4Report.summary.sessions)}</div>
                  </div>
                  <div className="googleChartViewport">
                    {dailyRows.length ? (
                      <Line data={trafficChartData} options={lineOptions} />
                    ) : (
                      <div className="googleChartEmptyState">Sem série diária disponível para o período.</div>
                    )}
                  </div>
                </article>

              </div>

              <div className="googleSecondaryGrid">
                <GoogleTopList
                  title="Top canais"
                  description="As origens que mais trouxeram sessões e usuários no período."
                  items={topChannels}
                  emptyMessage="Ainda não há canais suficientes para ordenar neste período."
                />
                <GoogleTopList
                  title="Top campanhas"
                  description="Campanhas com maior contribuição de tráfego na leitura do GA4."
                  items={topCampaigns}
                  emptyMessage="Ainda não há campanhas com dados relevantes neste período."
                />
              </div>
            </section>
            ) : null}

            {ga4Tab === "behavior" ? (
            <section className="googleSection" id="google-funnel">
              <div className="sectionHeader">
                <div>
                  <div className="h1">Funnel</div>
                  <div className="p">
                    Jornada comercial principal do site com as taxas de avanço entre as etapas.
                  </div>
                </div>
              </div>

              <div className="ga4JourneyCard">
                <div className="ga4JourneyHead">
                  <div>
                    <div className="h1">Funil principal do site</div>
                    <div className="p">
                      Etapas mais importantes entre descoberta de produto, checkout e compra final.
                    </div>
                  </div>
                  <span className="pill">Tracking comportamental GA4</span>
                </div>

                <div className="ga4JourneyGrid">
                  <div className="ga4JourneyStep">
                    <span className="smallMuted">Visualizou produto</span>
                    <strong>{formatFullNumber(ga4Report.commerce_journey.summary.view_item)}</strong>
                    <span className="ga4JourneyHint">Base do funil</span>
                  </div>
                  <div className="ga4JourneyStep">
                    <span className="smallMuted">Adicionou ao carrinho</span>
                    <strong>{formatFullNumber(ga4Report.commerce_journey.summary.add_to_cart)}</strong>
                    <span className="ga4JourneyHint">Conversão a partir do produto</span>
                    <span className="ga4JourneyRate">
                      {formatPct(ga4Report.commerce_journey.summary.add_to_cart_rate)}
                    </span>
                  </div>
                  <div className="ga4JourneyStep">
                    <span className="smallMuted">Iniciou checkout</span>
                    <strong>{formatFullNumber(ga4Report.commerce_journey.summary.begin_checkout)}</strong>
                    <span className="ga4JourneyHint">Avanço do carrinho</span>
                    <span className="ga4JourneyRate">
                      {formatPct(ga4Report.commerce_journey.summary.checkout_rate)}
                    </span>
                  </div>
                  <div className="ga4JourneyStep">
                    <span className="smallMuted">Informou pagamento</span>
                    <strong>{formatFullNumber(ga4Report.commerce_journey.summary.add_payment_info)}</strong>
                    <span className="ga4JourneyHint">Checkout qualificado</span>
                    <span className="ga4JourneyRate">
                      {formatPct(ga4Report.commerce_journey.summary.payment_info_rate)}
                    </span>
                  </div>
                  <div className="ga4JourneyStep">
                    <span className="smallMuted">Evento purchase GA4</span>
                    <strong>{formatFullNumber(ga4Report.commerce_journey.summary.purchase)}</strong>
                    <span className="ga4JourneyHint">Conversão final</span>
                    <span className="ga4JourneyRate">
                      {formatPct(ga4Report.commerce_journey.summary.purchase_rate)}
                    </span>
                  </div>
                </div>
              </div>
            </section>
            ) : null}

            {ga4Tab === "overview" ? (
            <section className="googleSection" id="google-daily">
              <div className="sectionHeader">
                <div>
                  <div className="h1">Evolução diária</div>
                  <div className="p">
                    Série de tráfego, usuários, eventos e passos do funil por dia.
                  </div>
                </div>
              </div>
              <GoogleDailyTable rows={dailyRows} />
            </section>
            ) : null}

            {ga4Tab === "acquisition" ? (
            <>
            <section className="googleSection" id="google-channels">
              <div className="sectionHeader">
                <div>
                  <div className="h1">Canais</div>
                  <div className="p">
                    Origem e mídia com sessões, usuários e eventos no período.
                  </div>
                </div>
              </div>
              <div className="googleSourceFilters">
                <label>
                  <span>Canal</span>
                  <select className="select" value={channelFilter} onChange={(event) => setChannelFilter(event.target.value)}>
                    <option value="">Todos os canais</option>
                    {channelOptions.map((option) => <option key={option} value={option}>{option}</option>)}
                  </select>
                </label>
                <label>
                  <span>Source / medium</span>
                  <select className="select" value={sourceMediumFilter} onChange={(event) => setSourceMediumFilter(event.target.value)}>
                    <option value="">Todas as origens</option>
                    {sourceMediumOptions.map((option) => <option key={option} value={option}>{option}</option>)}
                  </select>
                </label>
                <label>
                  <span>Plataforma</span>
                  <select className="select" value={platformFilter} onChange={(event) => setPlatformFilter(event.target.value)}>
                    <option value="">Todas as plataformas</option>
                    {platformOptions.map((option) => <option key={option} value={option}>{option}</option>)}
                  </select>
                </label>
                <label>
                  <span>Dispositivo</span>
                  <select className="select" value={deviceFilter} onChange={(event) => setDeviceFilter(event.target.value)}>
                    <option value="">Todos os dispositivos</option>
                    {deviceOptions.map((option) => <option key={option} value={option}>{option}</option>)}
                  </select>
                </label>
              </div>
              <GoogleChannelsTable rows={filteredChannels} />
            </section>

            <section className="googleSection" id="google-campaigns">
              <div className="sectionHeader">
                <div>
                  <div className="h1">Campanhas</div>
                  <div className="p">
                    Campanhas capturadas pelo GA4 com contribuição de tráfego e eventos.
                  </div>
                </div>
              </div>
              <div className="googleSourceFilters isCampaign">
                <label>
                  <span>Campanha GA4</span>
                  <input
                    className="select"
                    type="search"
                    list="ga4-campaign-options"
                    placeholder="Buscar campanha"
                    value={campaignFilter}
                    onChange={(event) => setCampaignFilter(event.target.value)}
                  />
                  <datalist id="ga4-campaign-options">
                    {campaignOptions.map((option) => <option key={option} value={option} />)}
                  </datalist>
                </label>
              </div>
              <GoogleCampaignsTable rows={filteredCampaigns} />
            </section>
            </>
            ) : null}

            {ga4Tab === "behavior" ? (
            <>
            <section className="googleSection" id="google-events">
              <div className="sectionHeader">
                <div>
                  <div className="h1">Eventos</div>
                  <div className="p">
                    Eventos brutos do GA4 com contagem de ocorrências, usuários e janela de leitura.
                  </div>
                </div>
              </div>
              <GoogleEventsTable rows={ga4Report.events} />
            </section>

            <section className="googleSection" id="google-behavior">
              <div className="sectionHeader">
                <div>
                  <div className="h1">Behavior</div>
                  <div className="p">
                    Eventos que mostram como as pessoas navegam, exploram páginas e avançam dentro do site.
                  </div>
                </div>
              </div>
              <GoogleGroupTable
                group={ga4Report.behavior}
                emptyMessage="Ainda não há eventos de comportamento para detalhar neste período."
              />
            </section>

            <section className="googleSection" id="google-engagement">
              <div className="sectionHeader">
                <div>
                  <div className="h1">Engagement</div>
                  <div className="p">
                    Interações que ajudam a medir interesse, consumo de conteúdo e qualidade de navegação.
                  </div>
                </div>
              </div>
              <GoogleGroupTable
                group={ga4Report.engagement}
                emptyMessage="Ainda não há eventos de engajamento para detalhar neste período."
              />
            </section>

            <section className="googleSection" id="google-merchandising">
              <div className="sectionHeader">
                <div>
                  <div className="h1">Merchandising</div>
                  <div className="p">
                    Sinais comerciais ligados a produto, vitrine, carrinho e intenção de compra.
                  </div>
                </div>
              </div>
              <GoogleGroupTable
                group={ga4Report.merchandising}
                emptyMessage="Ainda não há eventos de merchandising para detalhar neste período."
              />
            </section>
            </>
            ) : null}
          </>
        ) : null}
      </div>
    </Shell>
  );
}
