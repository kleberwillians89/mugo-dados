import { useCallback, useEffect, useMemo, useState } from "react";

import { formatFreshness } from "../app/dataRefresh";
import Shell from "../components/Shell";
import useDashboardGa4 from "../hooks/dashboard/useDashboardGa4";
import useCampaignsRanking from "../hooks/dashboard/useCampaignsRanking";
import useClientIntegrations from "../hooks/useClientIntegrations";
import { refreshProviderData } from "../app/api";
import { describeSyncError, runExclusiveSync } from "../app/syncOrchestrator";
import {
  getCampaignDisplayName,
  getGa4ChannelLabel,
  getGa4EventLabel,
  getGa4EventTechnicalDetail,
} from "../app/ga4Labels";
import { usePeriod } from "../app/PeriodContext";
import { getSelectedPeriodRange } from "../app/periodRange";
import type {
  ClientIntegrationConnection,
  Ga4CampaignRow,
  Ga4ChannelRow,
  Ga4EventGroup,
  Ga4ReportResponse,
} from "../app/types";
import {
  getActiveClient,
  getActiveClientId,
  getActiveClientName,
  getActiveClientConfigurationWarning,
} from "../app/activeClient";
import { getSelectedConnectionId } from "../app/connectionState";
import {
  formatCalendarDate,
  formatCalendarDateWords,
  formatCalendarRange,
  formatCompactInteger,
  formatCurrency,
  formatCurrencyShort,
  formatInteger,
  uniquePeak,
} from "../app/dataFormat";
import ChannelTodaySummary from "../components/dashboard/ChannelTodaySummary";
import { coveredShopifyDay } from "../components/dashboard/shopifyCoverage";
import PaidMediaReport from "../components/dashboard/PaidMediaReport";
import DataNotice from "../components/data/DataNotice";
import HeroFigure from "../components/data/HeroFigure";
import KpiFigure from "../components/data/KpiFigure";
import PageHeader from "../components/data/PageHeader";
import PeriodSelector from "../components/data/PeriodSelector";
import SegmentedControl from "../components/data/SegmentedControl";
import TrendChart from "../components/data/TrendChart";
import { useDashboardSnapshot } from "../app/DashboardDataContext";

import "../styles/dashboard.css";
import "../styles/channel-report.css";

type Props = {
  onLogout: () => void | Promise<void>;
  onOpenDashboard: () => void;
  isAuthenticated?: boolean;
  /** O sync do GA4 exige papel de gestão; viewer permanece somente leitura. */
  canSync?: boolean;
  /** Canal aberto ao entrar; sem valor, abre no canal que tem dado. */
  initialView?: "ads" | "ga4";
};

type PeriodPreset = "day" | "7d" | "30d" | "month" | "specific";

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
  if (start === end) return "day";
  const now = new Date();
  const currentMonthStart = toDateInput(new Date(now.getFullYear(), now.getMonth(), 1));
  const today = toDateInput(now);

  if (days === 7) return "7d";
  if (days === 30) return "30d";
  if (start === currentMonthStart && end === today) return "month";
  return "specific";
}

function formatPct(value: number) {
  return `${Number.isFinite(value) ? value.toFixed(value >= 10 ? 0 : 1) : "0.0"}%`;
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

type GoogleView = "ads" | "ga4";
type Ga4Detail = "daily" | "channels" | "campaigns" | "events";

/** IDs do Google Ads como aparecem na interface do Google: 592-799-3611. */
function formatCustomerId(value: string | null | undefined): string {
  const digits = String(value || "").replace(/\D/g, "");
  return digits.length === 10 ? `${digits.slice(0, 3)}-${digits.slice(3, 6)}-${digits.slice(6)}` : String(value || "");
}

/** Conexão em uso, do contrato canônico: a escolhida para a empresa ou a única. */
function pickIntegration(connections: ClientIntegrationConnection[] | null, provider: "ga4" | "google_ads", clientId: string) {
  const items = (connections || []).filter((item) => item.provider === provider);
  const selectedId = getSelectedConnectionId(clientId, provider);
  return items.find((item) => item.connection_id === selectedId) || (items.length === 1 ? items[0] : null);
}

function GoogleGroupTable({ group, id }: { group: Ga4EventGroup; id: string }) {
  if (!group.items.length) return null;
  return (
    <section className="ds-section" id={id} aria-labelledby={`${id}-title`}>
      <div className="ds-sectionHead">
        <div className="ds-sectionHeadText">
          <h3 id={`${id}-title`} className="ds-subTitle">{group.title}</h3>
          {group.description ? <p className="ds-caption">{group.description}</p> : null}
        </div>
        <p className="ds-caption">{formatInteger(group.total_events)} ocorrências · {formatInteger(group.total_users)} usuários (soma por dia e evento)</p>
      </div>
      <div className="ds-tableWrap">
        <table className="ds-table">
          <thead>
            <tr>
              <th scope="col">Evento</th>
              <th scope="col" className="is-number">Ocorrências</th>
              <th scope="col" className="is-number">Usuários (soma diária)</th>
            </tr>
          </thead>
          <tbody>
            {group.items.map((item) => (
              <tr key={item.event_name}>
                <td className="is-primary">
                  {item.label}
                  {item.description ? <span className="ds-tableSub">{item.description}</span> : null}
                </td>
                <td className="is-number">{formatInteger(item.event_count)}</td>
                <td className="is-number">{formatInteger(item.total_users)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** Ranking com participação: quem trouxe mais sessões no período. */
function SessionsRanking({ rows, testId, label }: {
  rows: Array<{ id: string; label: string; meta: string; sessions: number }>;
  testId: string;
  label: string;
}) {
  const total = rows.reduce((sum, row) => sum + row.sessions, 0);
  return (
    <ol className="ds-rankList" data-testid={testId} aria-label={label}>
      {rows.map((row) => {
        const share = total > 0 ? (row.sessions / total) * 100 : 0;
        return (
          <li key={row.id} className="ds-rankRow">
            <span className="ds-rankName">{row.label}</span>
            <span className="ds-rankValue">{formatInteger(row.sessions)} sessões</span>
            <span className="ds-rankMeta">{row.meta}</span>
            <span className="ds-rankShare">{share.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%</span>
            <span className="ds-rankBar" aria-hidden="true"><span style={{ width: `${Math.min(100, share)}%` }} /></span>
          </li>
        );
      })}
    </ol>
  );
}

export default function GoogleAnalytics({
  isAuthenticated = false,
  canSync = false,
  initialView,
}: Props) {
  const { period, periodDays, setDayPeriod, setCurrentMonthPeriod, setMonthPeriod, setPresetPeriod } = usePeriod();
  const [preset, setPreset] = useState<PeriodPreset>(() =>
    resolveInitialPreset(period.start, period.end, periodDays)
  );
  const initialDate = todayDateInput();
  const [selectedMonth, setSelectedMonth] = useState(initialDate.month);
  const [selectedYear, setSelectedYear] = useState(initialDate.year);
  const [selectedGa4ClientId, setSelectedGa4ClientId] = useState(resolveInitialGa4ClientId);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [chosenView, setChosenView] = useState<GoogleView | null>(initialView ?? null);
  const [ga4Detail, setGa4Detail] = useState<Ga4Detail>("daily");
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
        roas: row.google_ads_spend != null && row.google_ads_spend > 0 && row.google_ads_conversion_value != null
          ? row.google_ads_conversion_value / row.google_ads_spend : null,
      })),
    };
  }, [adsModel.daily]);
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(new Date());
  const googleAdsUpdatedAt = formatFreshness(adsModel.sources.find((source) => source.provider === "google_ads")?.last_success_at);
  const shopifyStore = useMemo(() => {
    const rows = adsModel.daily.filter((row) => row.shopify_net_revenue != null || row.shopify_orders != null);
    const source = adsModel.sources.find((item) => item.provider === "shopify");
    const covered = Boolean(source?.data_min_available && source?.data_max_available && source.data_min_available <= selectedRange.end && source.data_max_available >= selectedRange.start);
    if (!covered) return null;
    const revenue = rows.reduce((total, row) => total + Number(row.shopify_net_revenue || 0), 0);
    const orders = rows.reduce((total, row) => total + Number(row.shopify_orders || 0), 0);
    return { revenue, orders, ticket: orders > 0 ? revenue / orders : null, coverage: source?.data_max_available || null };
  }, [adsModel.daily, adsModel.sources, selectedRange.end, selectedRange.start]);
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
    formatFreshness(ga4Report?.meta.last_synced_at || ga4UpdatedAt);

  const dailyRows = useMemo(() => ga4Report?.trends.daily || [], [ga4Report?.trends.daily]);
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

  // Campanhas Google Ads do mesmo read model já carregado (provider google_ads).
  const googleCampaigns = useCampaignsRanking({
    isAuthenticated, activeClientId: activeGa4ClientId, period: selectedRange, provider: "google_ads",
  });
  const { reloadCampaigns } = googleCampaigns;
  // Conta/propriedade em uso: contrato canônico de Integrações (só leitura).
  const integrations = useClientIntegrations({ enabled: isAuthenticated && Boolean(activeGa4ClientId) });

  // Esta página mostra GA4 e campanhas do Google Ads: atualizar precisa
  // sincronizar os dois. Eles são independentes — um indisponível não impede
  // o outro de receber dados novos. A fachada devolve somente um aviso sanitizado.
  const handleRefresh = useCallback(async () => {
    setRefreshError(null);
    setSyncing(true);
    try {
      await runExclusiveSync(
        { clientId: activeGa4ClientId, provider: "google" },
        () => refreshProviderData("google", selectedRange)
      );
      if (getActiveClientId() !== activeGa4ClientId) return;
      await Promise.allSettled([reloadGa4({ force: true }), reloadCampaigns()]);
    } catch (cause) {
      setRefreshError(describeSyncError(cause, "Não foi possível atualizar. Mantendo a última leitura disponível."));
    } finally {
      setSyncing(false);
    }
  }, [activeGa4ClientId, reloadCampaigns, reloadGa4, selectedRange]);

  function handlePresetChange(nextPreset: PeriodPreset) {
    setPreset(nextPreset);
    if (nextPreset === "day") { setDayPeriod(period.end); return; }
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

  // ===== Leitura da página (só apresentação: nada abaixo altera cálculo) =====
  // Sem escolha explícita, abre no canal que tem dado (Google Ads primeiro).
  const view: GoogleView = chosenView ?? (googleAds ? "ads" : hasData ? "ga4" : "ads");
  const isAgencyView = ["agency_admin", "platform_admin"].includes(String(getActiveClient()?.role || ""));
  const adsIntegration = pickIntegration(integrations.lastValidConnections, "google_ads", activeGa4ClientId);
  const ga4Integration = pickIntegration(integrations.lastValidConnections, "ga4", activeGa4ClientId);
  const adsAssets = adsIntegration?.assets || {};
  const ga4Assets = ga4Integration?.assets || {};
  const googleAdsSource = adsModel.sources.find((source) => source.provider === "google_ads");
  const ga4Source = adsModel.sources.find((source) => source.provider === "ga4");
  const sumAds = (key: "impressions" | "clicks") => {
    const values = (googleAds?.daily || []).map((row) => row[key]).filter((value): value is number => value != null);
    return values.length ? values.reduce((total, value) => total + Number(value), 0) : null;
  };
  const adsImpressions = sumAds("impressions");
  const adsClicks = sumAds("clicks");
  const periodIncludesToday = selectedRange.start <= today && selectedRange.end >= today;
  const todayBlock = periodIncludesToday && shopifyStore ? (
    <ChannelTodaySummary
      date={today}
      value={coveredShopifyDay(shopifyStore.coverage, today, {
        revenue: shopifyToday?.shopify_net_revenue,
        orders: shopifyToday?.shopify_orders,
      })}
    />
  ) : null;
  // GA4: compras e receita só aparecem quando a fonte trouxe esses campos
  // (o read model guarda null quando não há; somar null como 0 seria inventar).
  const ga4HasPurchases = adsModel.daily.some((row) => row.ga4_purchases != null);
  const ga4HasRevenue = adsModel.daily.some((row) => row.ga4_revenue != null);
  const journey = ga4Report?.commerce_journey.summary;
  const hasFunnel = Boolean(journey && (journey.view_item > 0 || journey.add_to_cart > 0 || journey.begin_checkout > 0 || journey.add_payment_info > 0));
  const eventGroups = ga4Report ? [
    { id: "google-behavior", group: ga4Report.behavior },
    { id: "google-engagement", group: ga4Report.engagement },
    { id: "google-merchandising", group: ga4Report.merchandising },
  ] : [];
  const hasEvents = Boolean(ga4Report?.events.length) || eventGroups.some((item) => item.group.items.length > 0);
  const detail: Ga4Detail = ga4Detail === "events" && !hasEvents ? "daily" : ga4Detail;
  const hasStepColumns = dailyRows.some((row) => row.view_item_count > 0 || row.add_to_cart_count > 0 || row.begin_checkout_count > 0);
  const usersDiffer = dailyRows.some((row) => row.active_users !== row.total_users)
    || Boolean(ga4Report && ga4Report.summary.active_users !== ga4Report.summary.total_users);
  const sortedChannels = [...filteredChannels].sort((a, b) => b.sessions - a.sessions);
  const sortedCampaigns = [...filteredCampaigns].sort((a, b) => b.sessions - a.sessions);
  const channelTotal = sortedChannels.reduce((sum, row) => sum + row.sessions, 0);
  const topChannel = sortedChannels[0];
  const acquisitionTitle = topChannel && channelTotal > 0
    ? `${getGa4ChannelLabel(topChannel.source_medium)} trouxe ${((topChannel.sessions / channelTotal) * 100).toLocaleString("pt-BR", { maximumFractionDigits: 0 })}% das sessões`
    : "Origem das sessões";
  const sessionsPeak = uniquePeak(dailyRows, (row) => row.sessions);
  const eventsPerSession = ga4Report && ga4Report.summary.sessions > 0 ? ga4Report.summary.event_count / ga4Report.summary.sessions : null;
  const refreshButton = isAuthenticated ? (
    <span>
      <button className="btn intelHeaderAction" onClick={() => void handleRefresh()} disabled={syncing} type="button">
        {syncing ? "Atualizando..." : "Atualizar dados"}
      </button>
    </span>
  ) : null;

  return (
    <Shell variant="editorial" themeClass="theme-editorial" title={view === "ads" ? "Google Ads" : "Google Analytics"}>
      <div className="ds-page googleReport">
        <div className="ds-group">
          <PageHeader
            company={activeGa4ClientName}
            title={view === "ads" ? "Google Ads" : "Google Analytics"}
            subnav={
              <SegmentedControl
                ariaLabel="Canal Google"
                value={view}
                onSelect={(id) => setChosenView(id as GoogleView)}
                options={[
                  { id: "ads", label: "Google Ads" },
                  { id: "ga4", label: "Google Analytics" },
                ]}
              />
            }
            dateline={view === "ads" ? (
              <>
                <span>
                  <span className="ds-datelineSource">Google Ads</span>{" "}
                  {googleAdsUpdatedAt ? `Dados atualizados ${googleAdsUpdatedAt}` : "sem sincronização concluída"}
                </span>
                {refreshButton}
              </>
            ) : (
              <>
                <span>
                  <span className="ds-datelineSource">Google Analytics 4</span>{" "}
                  {lastSyncedLabel ? `Dados atualizados ${lastSyncedLabel}` : "sem sincronização concluída"}
                </span>
                {syncing || refreshingGa4 ? <span>sincronizando...</span> : null}
                {refreshButton}
              </>
            )}
            controls={
              <PeriodSelector
                active={preset}
                onSelect={(id) => handlePresetChange(id)}
                month={selectedMonth}
                year={selectedYear}
                years={years}
                onMonthChange={handleMonthChange}
                onYearChange={handleYearChange}
              />
            }
            controlsNote={formatCalendarRange(selectedRange.start, selectedRange.end)}
          />

          {view === "ads" && (adsAssets.customer_id || adsAssets.customer_name) ? (
            <dl className="ds-assetLine" aria-label="Conta Google Ads em uso" data-testid="google-ads-account">
              <div>
                <dt>Conta Google Ads</dt>
                <dd>
                  {adsAssets.customer_name || "Sem nome informado"}
                  {isAgencyView && adsAssets.customer_id ? <span className="ds-assetId">{formatCustomerId(adsAssets.customer_id)}</span> : null}
                </dd>
              </div>
              {adsAssets.login_customer_id && adsAssets.login_customer_id !== adsAssets.customer_id ? (
                <div>
                  <dt>Acesso</dt>
                  <dd>
                    pela conta gerenciadora (MCC)
                    {isAgencyView ? <span className="ds-assetId">{formatCustomerId(adsAssets.login_customer_id)}</span> : null}
                  </dd>
                </div>
              ) : adsAssets.customer_id ? (
                <div><dt>Acesso</dt><dd>direto à conta</dd></div>
              ) : null}
            </dl>
          ) : null}
          {view === "ga4" && (ga4Assets.property_id || ga4Assets.property_name) ? (
            <dl className="ds-assetLine" aria-label="Propriedade GA4 em uso" data-testid="ga4-property">
              <div>
                <dt>Propriedade</dt>
                <dd>
                  {ga4Assets.property_name || "Sem nome informado"}
                  {isAgencyView && ga4Assets.property_id ? <span className="ds-assetId">{ga4Assets.property_id}</span> : null}
                </dd>
              </div>
              {ga4Assets.stream_name ? <div><dt>Fluxo de dados</dt><dd>{ga4Assets.stream_name}</dd></div> : null}
            </dl>
          ) : null}

          {(view === "ads" ? adsIntegration : ga4Integration)?.authorization_status === "invalid" ? (
            <DataNotice tone="warning" role="status" title={`A autorização ${view === "ads" ? "do Google Ads" : "do Google Analytics"} precisa ser renovada`}>
              Os números abaixo são da última leitura válida. {canSync ? "Conecte novamente em Integrações para retomar as atualizações." : "Peça a um administrador da empresa para conectar novamente."}
            </DataNotice>
          ) : null}
          {configWarning ? <DataNotice tone="warning" title="Configuração da empresa">{configWarning}</DataNotice> : null}
          {refreshError ? <DataNotice tone="negative" role="alert" title="Não foi possível atualizar">{refreshError}</DataNotice> : null}
        </div>

        {view === "ads" ? (
          <section className="googleCommercialSection" aria-label="Google Ads no período">
            {adsModel.loading && !adsModel.snapshot ? (
              <p className="ds-status" role="status">Carregando Google Ads...</p>
            ) : adsModel.error && !googleAds ? (
              <DataNotice tone="negative" role="alert" title="Google Ads indisponível">
                Não foi possível ler os dados do Google Ads agora.
              </DataNotice>
            ) : googleAds ? (
              <PaidMediaReport
                source="Google Ads"
                testId="google-ads"
                totals={{
                  spend: googleAds.spend,
                  revenue: googleAds.revenue,
                  conversions: googleAds.conversions,
                  impressions: adsImpressions,
                  clicks: adsClicks,
                  ctr: adsClicks != null && adsImpressions ? (adsClicks * 100) / adsImpressions : null,
                  cpc: adsClicks ? googleAds.spend / adsClicks : null,
                  cpm: adsImpressions ? (googleAds.spend * 1000) / adsImpressions : null,
                }}
                comparisonNote="Sem comparação com o período anterior para o Google Ads nesta leitura."
                daily={googleAds.daily}
                store={shopifyStore ? {
                  revenue: shopifyStore.revenue,
                  orders: shopifyStore.orders,
                  ticket: shopifyStore.ticket,
                  roas: googleAds.spend && shopifyStore.revenue != null ? shopifyStore.revenue / googleAds.spend : null,
                } : null}
                today={todayBlock}
                campaigns={{
                  rows: googleCampaigns.campaignsData?.campaigns || [],
                  loading: googleCampaigns.loadingCampaigns,
                  error: googleCampaigns.campaignsError,
                }}
              />
            ) : (
              <DataNotice role="status" title={googleAdsSource ? "Sem dados do Google Ads neste período" : "Google Ads ainda não sincronizado"}>
                {googleAdsSource
                  ? "A conta está sincronizada, mas não há investimento registrado no período selecionado."
                  : "Os números aparecem aqui depois que a conta Google Ads da empresa for conectada e sincronizada em Integrações."}
              </DataNotice>
            )}
          </section>
        ) : (
          <section className="ga4Report" aria-label="Google Analytics no período">
            {loadingGa4 && !ga4Report ? (
              <p className="ds-status" role="status">Carregando Google Analytics...</p>
            ) : (combinedError && !ga4Report) || (adsModel.error && !adsModel.snapshot) ? (
              <DataNotice tone="negative" role="alert" title="Google Analytics indisponível">
                Não foi possível carregar os dados do Google Analytics agora. Tente atualizar em instantes.
              </DataNotice>
            ) : ga4Report && !hasData ? (
              <DataNotice role="status" title={ga4Source ? "Sem dados do Google Analytics neste período" : "Google Analytics ainda não sincronizado"}>
                {ga4Source
                  ? "A propriedade está sincronizada, mas não registrou sessões no período selecionado."
                  : "Os números aparecem aqui depois que a propriedade GA4 da empresa for conectada e sincronizada em Integrações."}
              </DataNotice>
            ) : ga4Report ? (
              <div className="ds-stack">
                {combinedError ? (
                  <DataNotice tone="warning" title="Atualização parcial">A última base carregada continua visível.</DataNotice>
                ) : null}

                {/* AQUISIÇÃO → COMPORTAMENTO → CONVERSÃO, só com o que a fonte trouxe. */}
                <section className="ds-summary" id="google-summary" aria-label="Resumo do site">
                  <HeroFigure
                    value={formatCompactInteger(ga4Report.summary.sessions)}
                    exactValue={formatInteger(ga4Report.summary.sessions)}
                    rawValue={ga4Report.summary.sessions}
                    label="sessões no site no período"
                    testId="ga4-sessions"
                  />
                  <div className="ds-kpis is-four">
                    <KpiFigure label="Usuários (soma diária)" value={formatInteger(ga4Report.summary.total_users)} rawValue={ga4Report.summary.total_users} />
                    <KpiFigure label="Eventos" value={formatCompactInteger(ga4Report.summary.event_count)} exactValue={formatInteger(ga4Report.summary.event_count)} rawValue={ga4Report.summary.event_count} />
                    {ga4HasPurchases ? (
                      <KpiFigure label="Compras registradas" value={formatInteger(ga4Report.summary.purchases)} rawValue={ga4Report.summary.purchases} />
                    ) : null}
                    {ga4HasRevenue ? (
                      <KpiFigure label="Receita GA4" value={formatCurrencyShort(ga4Report.summary.purchase_revenue)} exactValue={formatCurrency(ga4Report.summary.purchase_revenue)} rawValue={ga4Report.summary.purchase_revenue} />
                    ) : null}
                  </div>
                  <div className="ds-secondary">
                    <dl className="ds-inlineStats">
                      {eventsPerSession != null ? (
                        <div><dt>Eventos por sessão</dt><dd>{eventsPerSession.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}</dd></div>
                      ) : null}
                      {usersDiffer ? <div><dt>Usuários ativos (soma diária)</dt><dd>{formatInteger(ga4Report.summary.active_users)}</dd></div> : null}
                      {ga4Report.summary.engaged_sessions != null ? <div><dt>Sessões engajadas</dt><dd>{formatInteger(ga4Report.summary.engaged_sessions)}</dd></div> : null}
                      {ga4Report.summary.screen_page_views != null ? <div><dt>Visualizações</dt><dd>{formatInteger(ga4Report.summary.screen_page_views)}</dd></div> : null}
                      {ga4Report.summary.key_events != null ? <div><dt>Eventos principais</dt><dd>{formatInteger(ga4Report.summary.key_events)}</dd></div> : null}
                      <div><dt>Média diária de usuários ativos</dt><dd>{formatInteger(ga4Report.summary.average_daily_active_users)}</dd></div>
                    </dl>
                    <p className="ds-footnote">
                      Fonte: Google Analytics 4. Os valores de receita seguem a atribuição do GA4 e podem diferir da loja e das plataformas de mídia.
                      {" "}Usuários são somas diárias; a mesma pessoa pode aparecer em mais de um dia. O total de usuários únicos do período não está disponível.
                      {" "}Sem comparação com o período anterior nesta fonte.
                    </p>
                  </div>
                </section>

                <section className="ds-section ds-chartSection" aria-labelledby="ga4-trend-title">
                  <div className="ds-sectionHead">
                    <div className="ds-sectionHeadText">
                      <h2 id="ga4-trend-title" className="ds-sectionTitle">
                        {sessionsPeak ? `${formatCalendarDateWords(sessionsPeak.date)} concentrou o maior número de sessões` : "Sessões por dia"}
                      </h2>
                      {sessionsPeak ? <p className="ds-caption">{formatInteger(sessionsPeak.sessions)} sessões nesse dia</p> : null}
                    </div>
                  </div>
                  {dailyRows.length > 1 ? (
                    <TrendChart
                      data={dailyRows}
                      xKey="date"
                      primaryKey="sessions"
                      formatX={(value) => formatCalendarDate(value)}
                      formatY={formatCompactInteger}
                      ariaLabel={`Sessões por dia, ${formatCalendarRange(selectedRange.start, selectedRange.end)}.`}
                      testId="ga4-sessions-chart"
                      renderTooltip={(row) => (
                        <>
                          <strong>{formatCalendarDate(row.date, "long")}</strong>
                          <dl>
                            <dt>Sessões</dt><dd>{formatInteger(row.sessions)}</dd>
                            <dt>Usuários</dt><dd>{formatInteger(row.total_users)}</dd>
                            <dt>Eventos</dt><dd>{formatInteger(row.event_count)}</dd>
                          </dl>
                        </>
                      )}
                    />
                  ) : (
                    <p className="ds-emptyLine">Selecione um período com mais de um dia para ver a evolução das sessões.</p>
                  )}
                </section>

                <section className="ds-section" aria-labelledby="ga4-acquisition-title">
                  <div className="ds-sectionHeadText">
                    <h2 id="ga4-acquisition-title" className="ds-sectionTitle">{acquisitionTitle}</h2>
                    <p className="ds-caption">Aquisição: de onde vieram as sessões do período.</p>
                  </div>
                  <div className="ds-split">
                    <div className="ds-group">
                      <h3 className="ds-subTitle">Canais</h3>
                      {sortedChannels.length ? (
                        <SessionsRanking
                          testId="ga4-top-channels"
                          label="Canais com mais sessões"
                          rows={sortedChannels.slice(0, 5).map((row) => ({
                            id: row.source_medium || `${row.source || "source"}-${row.medium || "medium"}`,
                            label: getGa4ChannelLabel(row.source_medium),
                            meta: `${formatInteger(row.total_users)} usuários (soma diária) · ${formatInteger(row.event_count)} eventos`,
                            sessions: row.sessions,
                          }))}
                        />
                      ) : <p className="ds-emptyLine">Ainda não há canais neste período.</p>}
                    </div>
                    <div className="ds-group">
                      <h3 className="ds-subTitle">Campanhas</h3>
                      {sortedCampaigns.length ? (
                        <SessionsRanking
                          testId="ga4-top-campaigns"
                          label="Campanhas com mais sessões"
                          rows={sortedCampaigns.slice(0, 5).map((row) => ({
                            id: `${row.campaign_name}-${row.source_medium || "campaign"}`,
                            label: getCampaignDisplayName(row.campaign_name, { source: row.source, medium: row.medium }),
                            meta: `${getGa4ChannelLabel(row.source_medium)} · ${formatInteger(row.event_count)} eventos`,
                            sessions: row.sessions,
                          }))}
                        />
                      ) : <p className="ds-emptyLine">Ainda não há campanhas com sessões neste período.</p>}
                    </div>
                  </div>
                </section>

                {hasFunnel && journey ? (
                  <section className="ds-section" id="google-funnel" aria-labelledby="ga4-funnel-title">
                    <div className="ds-sectionHeadText">
                      <h2 id="ga4-funnel-title" className="ds-sectionTitle">
                        {formatInteger(journey.view_item)} visualizações de produto, {formatInteger(journey.purchase)} compras
                      </h2>
                      <p className="ds-caption">Comportamento e conversão: etapas registradas pelo GA4, com a taxa de avanço sobre a etapa anterior.</p>
                    </div>
                    <ol className="ds-funnel">
                      {[
                        { label: "Visualizou produto", value: journey.view_item, rate: null },
                        { label: "Adicionou ao carrinho", value: journey.add_to_cart, rate: journey.add_to_cart_rate },
                        { label: "Iniciou checkout", value: journey.begin_checkout, rate: journey.checkout_rate },
                        { label: "Informou pagamento", value: journey.add_payment_info, rate: journey.payment_info_rate },
                        { label: "Compra (evento purchase)", value: journey.purchase, rate: journey.purchase_rate },
                      ].map((step) => (
                        <li key={step.label}>
                          <span className="ds-funnelLabel">{step.label}</span>
                          <strong className="ds-funnelValue">{formatInteger(step.value)}</strong>
                          <span className="ds-funnelRate">{step.rate == null ? "base" : `${formatPct(step.rate)} da etapa anterior`}</span>
                        </li>
                      ))}
                    </ol>
                  </section>
                ) : (
                  <p className="ds-footnote">
                    Etapas do funil (produto visto, carrinho, checkout) não fazem parte do resumo do GA4 desta leitura: só sessões, usuários, eventos e compras.
                  </p>
                )}

                <section className="ds-section" aria-labelledby="ga4-detail-title">
                  <div className="ds-sectionHead">
                    <h2 id="ga4-detail-title" className="ds-sectionTitle">Detalhamento</h2>
                    <SegmentedControl
                      ariaLabel="Detalhamento do Google Analytics"
                      value={detail}
                      onSelect={(id) => setGa4Detail(id as Ga4Detail)}
                      options={[
                        { id: "daily", label: "Dia a dia" },
                        { id: "channels", label: "Canais" },
                        { id: "campaigns", label: "Campanhas" },
                        ...(hasEvents ? [{ id: "events", label: "Eventos" }] : []),
                      ]}
                    />
                  </div>

                  {detail === "daily" ? (
                    <div id="google-daily">
                      {dailyRows.length ? (
                        <div className="ds-tableWrap">
                          <table className="ds-table">
                            <thead>
                              <tr>
                                <th scope="col">Data</th>
                                <th scope="col" className="is-number">Sessões</th>
                                {usersDiffer ? (
                                  <>
                                    <th scope="col" className="is-number">Usuários ativos</th>
                                    <th scope="col" className="is-number">Usuários totais</th>
                                  </>
                                ) : <th scope="col" className="is-number">Usuários</th>}
                                <th scope="col" className="is-number">Eventos</th>
                                {ga4HasPurchases ? <th scope="col" className="is-number">Compras</th> : null}
                                {hasStepColumns ? (
                                  <>
                                    <th scope="col" className="is-number">Produto visto</th>
                                    <th scope="col" className="is-number">Carrinho</th>
                                    <th scope="col" className="is-number">Checkout</th>
                                  </>
                                ) : null}
                              </tr>
                            </thead>
                            <tbody>
                              {dailyRows.map((row) => (
                                <tr key={row.date}>
                                  <td className="is-primary">{formatCalendarDate(row.date, "long")}</td>
                                  <td className="is-number">{formatInteger(row.sessions)}</td>
                                  {usersDiffer ? (
                                    <>
                                      <td className="is-number">{formatInteger(row.active_users)}</td>
                                      <td className="is-number">{formatInteger(row.total_users)}</td>
                                    </>
                                  ) : <td className="is-number">{formatInteger(row.total_users)}</td>}
                                  <td className="is-number">{formatInteger(row.event_count)}</td>
                                  {ga4HasPurchases ? <td className="is-number">{formatInteger(row.purchase_count || row.ecommerce_purchases)}</td> : null}
                                  {hasStepColumns ? (
                                    <>
                                      <td className="is-number">{formatInteger(row.view_item_count)}</td>
                                      <td className="is-number">{formatInteger(row.add_to_cart_count)}</td>
                                      <td className="is-number">{formatInteger(row.begin_checkout_count)}</td>
                                    </>
                                  ) : null}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : <p className="ds-emptyLine">Sem série diária neste período.</p>}
                    </div>
                  ) : null}

                  {detail === "channels" ? (
                    <div id="google-channels" className="ds-group">
                      <div className="ds-filters" aria-label="Filtros de canais">
                        <label className="ds-field">
                          <span>Canal</span>
                          <select value={channelFilter} onChange={(event) => setChannelFilter(event.target.value)}>
                            <option value="">Todos os canais</option>
                            {channelOptions.map((option) => <option key={option} value={option}>{option}</option>)}
                          </select>
                        </label>
                        <label className="ds-field">
                          <span>Origem / mídia</span>
                          <select value={sourceMediumFilter} onChange={(event) => setSourceMediumFilter(event.target.value)}>
                            <option value="">Todas as origens</option>
                            {sourceMediumOptions.map((option) => <option key={option} value={option}>{option}</option>)}
                          </select>
                        </label>
                        {platformOptions.length ? (
                          <label className="ds-field">
                            <span>Plataforma</span>
                            <select value={platformFilter} onChange={(event) => setPlatformFilter(event.target.value)}>
                              <option value="">Todas as plataformas</option>
                              {platformOptions.map((option) => <option key={option} value={option}>{option}</option>)}
                            </select>
                          </label>
                        ) : null}
                        {deviceOptions.length ? (
                          <label className="ds-field">
                            <span>Dispositivo</span>
                            <select value={deviceFilter} onChange={(event) => setDeviceFilter(event.target.value)}>
                              <option value="">Todos os dispositivos</option>
                              {deviceOptions.map((option) => <option key={option} value={option}>{option}</option>)}
                            </select>
                          </label>
                        ) : null}
                      </div>
                      {filteredChannels.length ? (
                        <div className="ds-tableWrap">
                          <table className="ds-table">
                            <thead>
                              <tr>
                                <th scope="col">Canal</th>
                                <th scope="col">Origem</th>
                                <th scope="col">Mídia</th>
                                <th scope="col" className="is-number">Sessões</th>
                                <th scope="col" className="is-number">Usuários ativos (soma diária)</th>
                                <th scope="col" className="is-number">Usuários totais (soma diária)</th>
                                <th scope="col" className="is-number">Eventos</th>
                              </tr>
                            </thead>
                            <tbody>
                              {filteredChannels.map((row) => (
                                <tr key={`${row.source_medium}-${row.source}-${row.medium}`}>
                                  <td className="is-primary">{getGa4ChannelLabel(row.source_medium)}</td>
                                  <td>{row.source || "—"}</td>
                                  <td>{row.medium || "—"}</td>
                                  <td className="is-number">{formatInteger(row.sessions)}</td>
                                  <td className="is-number">{formatInteger(row.active_users)}</td>
                                  <td className="is-number">{formatInteger(row.total_users)}</td>
                                  <td className="is-number">{formatInteger(row.event_count)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : <p className="ds-emptyLine">Nenhum canal corresponde aos filtros neste período.</p>}
                    </div>
                  ) : null}

                  {detail === "campaigns" ? (
                    <div id="google-campaigns" className="ds-group">
                      <div className="ds-filters" aria-label="Filtros de campanhas">
                        <label className="ds-field">
                          <span>Campanha</span>
                          <input type="search" list="ga4-campaign-options" placeholder="Buscar campanha" value={campaignFilter} onChange={(event) => setCampaignFilter(event.target.value)} />
                          <datalist id="ga4-campaign-options">
                            {campaignOptions.map((option) => <option key={option} value={option} />)}
                          </datalist>
                        </label>
                      </div>
                      {filteredCampaigns.length ? (
                        <div className="ds-tableWrap">
                          <table className="ds-table">
                            <thead>
                              <tr>
                                <th scope="col">Campanha</th>
                                <th scope="col">Canal</th>
                                <th scope="col" className="is-number">Sessões</th>
                                <th scope="col" className="is-number">Usuários ativos (soma diária)</th>
                                <th scope="col" className="is-number">Usuários totais (soma diária)</th>
                                <th scope="col" className="is-number">Eventos</th>
                              </tr>
                            </thead>
                            <tbody>
                              {filteredCampaigns.map((row) => (
                                <tr key={`${row.campaign_name}-${row.source_medium}`}>
                                  <td className="is-primary">
                                    {getCampaignDisplayName(row.campaign_name, { source: row.source, medium: row.medium })}
                                    <span className="ds-tableSub">{row.source || "—"} / {row.medium || "—"}</span>
                                  </td>
                                  <td>{getGa4ChannelLabel(row.source_medium) || "—"}</td>
                                  <td className="is-number">{formatInteger(row.sessions)}</td>
                                  <td className="is-number">{formatInteger(row.active_users)}</td>
                                  <td className="is-number">{formatInteger(row.total_users)}</td>
                                  <td className="is-number">{formatInteger(row.event_count)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : <p className="ds-emptyLine">Nenhuma campanha corresponde aos filtros neste período.</p>}
                    </div>
                  ) : null}

                  {detail === "events" ? (
                    <div className="ds-stack">
                      {ga4Report.events.length ? (
                        <div id="google-events" className="ds-tableWrap">
                          <table className="ds-table">
                            <thead>
                              <tr>
                                <th scope="col">Evento</th>
                                <th scope="col" className="is-number">Ocorrências</th>
                                <th scope="col" className="is-number">Usuários (soma diária)</th>
                                <th scope="col">Primeira leitura</th>
                                <th scope="col">Última leitura</th>
                              </tr>
                            </thead>
                            <tbody>
                              {ga4Report.events.map((row) => (
                                <tr key={row.event_name}>
                                  <td className="is-primary">
                                    {row.label && row.label !== row.event_name ? row.label : getGa4EventLabel(row.event_name)}
                                    {row.description || getGa4EventTechnicalDetail(row.event_name)
                                      ? <span className="ds-tableSub">{row.description || getGa4EventTechnicalDetail(row.event_name)}</span>
                                      : null}
                                  </td>
                                  <td className="is-number">{formatInteger(row.event_count)}</td>
                                  <td className="is-number">{formatInteger(row.total_users)}</td>
                                  <td>{row.first_seen_at ? formatCalendarDate(row.first_seen_at.slice(0, 10), "long") : "—"}</td>
                                  <td>{row.last_seen_at ? formatCalendarDate(row.last_seen_at.slice(0, 10), "long") : "—"}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : null}
                      {eventGroups.map((item) => <GoogleGroupTable key={item.id} id={item.id} group={item.group} />)}
                    </div>
                  ) : null}
                </section>
              </div>
            ) : null}
          </section>
        )}
      </div>
    </Shell>
  );
}
