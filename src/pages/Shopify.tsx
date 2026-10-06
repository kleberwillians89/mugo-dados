import { readOnce } from "../hooks/dashboard/readOnce";
import useSectionDemand from "../hooks/useSectionDemand";
import { buildDashboardCacheKey, readDashboardCache, writeDashboardCache } from "../hooks/dashboard/cache";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Shell from "../components/Shell";
import DataNotice from "../components/data/DataNotice";
import HeroFigure from "../components/data/HeroFigure";
import KpiFigure from "../components/data/KpiFigure";
import PageHeader from "../components/data/PageHeader";
import SegmentedControl from "../components/data/SegmentedControl";
import TrendChart from "../components/data/TrendChart";
import ShopifyCustomerFilters from "../components/shopify/ShopifyCustomerFilters";
import ShopifyCustomersTable from "../components/shopify/ShopifyCustomersTable";
import ShopifyExecutiveSummaryCard from "../components/shopify/ShopifyExecutiveSummaryCard";
import ShopifyOrdersTable from "../components/shopify/ShopifyOrdersTable";
import ShopifyTopProductsCard from "../components/shopify/ShopifyTopProductsCard";
import ShopifySalesHistory from "../components/shopify/ShopifySalesHistory";
import DayPeriodControl from "../components/DayPeriodControl";
import { usePeriod } from "../app/PeriodContext";
import {
  formatCalendarDate,
  formatCalendarDateWords,
  formatCalendarRange,
  formatCurrencyAxis,
  formatCurrencyShort,
  formatInteger,
  uniquePeak,
} from "../app/dataFormat";
import {
  getShopifyCustomers,
  getShopifyReport,
  refreshProviderData,
} from "../app/api";
import { useDashboardSnapshot } from "../app/DashboardDataContext";
import { countUniqueShopifyCustomers } from "../app/shopifyReadModel";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { describeSyncError, runExclusiveSync } from "../app/syncOrchestrator";
import {
  formatShopifyCompactNumber,
  formatShopifyCurrency,
  formatShopifyMonthLabel,
} from "../app/shopifyUi";
import type {
  ShopifyCustomerRow,
  ShopifyCustomersResponse,
  ShopifyReportResponse,
} from "../app/types";
import "../styles/shopify-report.css";
import { formatFreshness } from "../app/dataRefresh";

type Props = {
  /** Permissão administrativa; refresh de dados usa membership no backend. */
  canSync: boolean;
  onLogout: () => void | Promise<void>;
  onOpenDashboard: () => void;
  onOpenGoogleReport?: () => void;
};


type PeriodPreset = "day" | "7d" | "30d" | "month" | "previous_month" | "ytd" | "specific" | "custom";
type ShopifyMetricKey = "revenue" | "orders" | "customers" | "average_ticket";

const SHOPIFY_METRIC_TABS: { key: ShopifyMetricKey; label: string; description: string }[] = [
  { key: "revenue", label: "Receita", description: "Faturamento diário" },
  { key: "orders", label: "Pedidos", description: "Pedidos diários" },
  { key: "customers", label: "Clientes", description: "Clientes por período" },
  { key: "average_ticket", label: "Ticket médio", description: "Ticket médio por período" },
];
const SHOPIFY_PERIOD_OPTIONS: Array<{ id: PeriodPreset; label: string }> = [
  { id: "day", label: "Dia" },
  { id: "7d", label: "7 dias" },
  { id: "30d", label: "30 dias" },
  { id: "month", label: "Este mês" },
  { id: "previous_month", label: "Mês passado" },
  { id: "ytd", label: "Este ano" },
];
const SHOPIFY_PEAK_TITLE: Record<ShopifyMetricKey, (when: string) => string> = {
  revenue: (when) => `${when} concentrou o maior volume de vendas`,
  orders: (when) => `${when} teve o maior número de pedidos`,
  customers: (when) => `${when} teve o maior número de clientes`,
  average_ticket: (when) => `${when} teve o maior ticket médio`,
};

function shopifyTrendTitle(peak: { date: string } | null, metric: ShopifyMetricKey): string {
  if (!peak) return metric === "revenue" ? "Vendas ao longo do período" : `${SHOPIFY_METRIC_TABS.find((tab) => tab.key === metric)?.label || ""} ao longo do período`;
  return SHOPIFY_PEAK_TITLE[metric](formatCalendarDateWords(peak.date));
}

type CustomerLifecycleFilter = "all" | "new" | "recurring";
type CustomerSortBy = "total_spent" | "total_orders" | "last_purchase_at";

function toDateInput(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function canonicalTodayIso() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Sao_Paulo", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date());
}

function formatCivilDate(value: string) {
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit", month: "2-digit", year: "numeric", timeZone: "America/Sao_Paulo",
  }).format(new Date(Date.UTC(year, month - 1, day, 12)));
}

function todayDateInput() {
  const [year, month] = canonicalTodayIso().split("-").map(Number);
  return {
    month,
    year,
  };
}

function resolveInitialPreset(start: string, end: string, days: number): PeriodPreset {
  if (start === end) return "day";
  const now = new Date();
  const currentMonthStart = toDateInput(new Date(now.getFullYear(), now.getMonth(), 1));
  const today = toDateInput(now);
  const previousMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const previousStart = toDateInput(previousMonth);
  const previousEnd = toDateInput(new Date(now.getFullYear(), now.getMonth(), 0));

  if (days === 7) return "7d";
  if (days === 30) return "30d";
  if (start === currentMonthStart && end === today) return "month";
  if (start === previousStart && end === previousEnd) return "previous_month";
  if (start === `${now.getFullYear()}-01-01` && end === today) return "ytd";
  return "specific";
}

function asFilterNumber(value: string): number | null {
  // Campo vazio significa "sem filtro" — Number("") é 0, não deve ser
  // tratado como um limite real (senão "valor máximo" vazio esconde
  // todo cliente com gasto positivo por padrão).
  if (value.trim() === "") return null;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  return numeric;
}

function buildCustomerSummary(customers: ShopifyCustomerRow[]) {
  const recurringCustomers = customers.filter((customer) => customer.status === "recurring").length;
  const multiOrderCustomers = customers.filter((customer) => customer.total_orders > 1).length;
  const topCustomer = customers.reduce<ShopifyCustomerRow | null>((current, customer) => {
    if (!current || customer.total_spent > current.total_spent) {
      return customer;
    }
    return current;
  }, null);

  return {
    totalCustomers: customers.length,
    recurringCustomers,
    multiOrderCustomers,
    topCustomer,
  };
}

// Navegação e saída vivem na sidebar global (onLogout segue no tipo por compatibilidade).
export default function Shopify({ onOpenDashboard, onOpenGoogleReport }: Props) {
  const { period, periodDays, setPeriod, setDayPeriod, setCurrentMonthPeriod, setMonthPeriod, setPresetPeriod } = usePeriod();
  const [shopifyChartMetric, setShopifyChartMetric] = useState<ShopifyMetricKey>("revenue");
  const [preset, setPreset] = useState<PeriodPreset>(() =>
    resolveInitialPreset(period.start, period.end, periodDays)
  );
  const initialDate = todayDateInput();
  const [selectedMonth, setSelectedMonth] = useState(initialDate.month);
  const [selectedYear, setSelectedYear] = useState(initialDate.year);
  const model = useDashboardSnapshot(period.start, period.end);
  const historicalModel = useDashboardSnapshot();
  const [error, setError] = useState<string | null>(null);
  const [syncingShopify, setSyncingShopify] = useState(false);
  const [syncNotice, setSyncNotice] = useState<string | null>(null);
  const [customerSearch, setCustomerSearch] = useState("");
  const [minTotalSpent, setMinTotalSpent] = useState("");
  const [maxTotalSpent, setMaxTotalSpent] = useState("");
  const [minOrders, setMinOrders] = useState("");
  const [customerLifecycle, setCustomerLifecycle] = useState<CustomerLifecycleFilter>("all");
  const [customerSortBy, setCustomerSortBy] = useState<CustomerSortBy>("total_spent");
  const detailKey = buildDashboardCacheKey("shopify-details", { clientId: getActiveClientId(), start: period.start, end: period.end });
  const cachedDetails = readDashboardCache<{ report: ShopifyReportResponse | null; customers: ShopifyCustomersResponse | null }>(detailKey);
  const [customerData, setCustomerData] = useState<ShopifyCustomersResponse | null>(cachedDetails?.customers || null);
  const [detailReport, setDetailReport] = useState<ShopifyReportResponse | null>(cachedDetails?.report || null);
  const [detailsLoading, setDetailsLoading] = useState(true);
  const [showCustom, setShowCustom] = useState(false);
  const currentDetails = useRef(detailKey);
  const requestedDetails = useRef(new Set<string>());
  const customerDemand = useSectionDemand(`${detailKey}:customers`, !model.loading);
  const orderDemand = useSectionDemand(`${detailKey}:orders`, !model.loading);
  if (currentDetails.current !== detailKey) {
    currentDetails.current = detailKey;
    setCustomerData(cachedDetails?.customers || null);
    setDetailReport(cachedDetails?.report || null);
    setDetailsLoading(!cachedDetails);
  }

  useEffect(() => {
    const startDate = new Date(`${period.start}T00:00:00`);
    if (Number.isNaN(startDate.getTime())) return;
    setSelectedMonth(startDate.getMonth() + 1);
    setSelectedYear(startDate.getFullYear());
    if (preset !== "custom") setPreset(resolveInitialPreset(period.start, period.end, periodDays));
  }, [period.end, period.start, periodDays, preset]);

  useEffect(() => {
    let active = true;
    const cached = readDashboardCache<{ report: ShopifyReportResponse | null; customers: ShopifyCustomersResponse | null }>(detailKey);
    setDetailsLoading(customerDemand.enabled && !cached?.customers);
    setCustomerData(cached?.customers || null);
    setDetailReport(cached?.report || null);
    const selectedPeriod = { start: period.start, end: period.end, days: periodDays };
    const save = (patch: { report?: ShopifyReportResponse; customers?: ShopifyCustomersResponse }) => {
      if (currentDetails.current !== detailKey) return;
      writeDashboardCache(detailKey, { report: null, customers: null, ...cached, ...readDashboardCache<{ report: ShopifyReportResponse | null; customers: ShopifyCustomersResponse | null }>(detailKey), ...patch }, 180_000);
    };
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      const requestReport = orderDemand.enabled && !requestedDetails.current.has(`${detailKey}:report`);
      const requestCustomers = customerDemand.enabled && !requestedDetails.current.has(`${detailKey}:customers`);
      if (requestReport) requestedDetails.current.add(`${detailKey}:report`);
      if (requestCustomers) requestedDetails.current.add(`${detailKey}:customers`);
      void Promise.allSettled([
        ...(requestReport ? [readOnce(`${detailKey}:report`, () => getShopifyReport(selectedPeriod)).then(next => { if (currentDetails.current === detailKey) { setDetailReport(next); save({ report: next }); } })] : []),
        ...(requestCustomers ? [readOnce(`${detailKey}:customers`, () => getShopifyCustomers(selectedPeriod)).then(next => { if (currentDetails.current === detailKey) { setCustomerData(next); save({ customers: next }); } })] : []),
      ]).then(results => {
        if (!active) return;
        if (results.some(result => result.status === "rejected")) setError("Não foi possível carregar todos os detalhes da Shopify.");
        setDetailsLoading(false);
      });
    });
    return () => {
      active = false;
      cancelled = true;
    };
  }, [customerDemand.enabled, detailKey, orderDemand.enabled, period.end, period.start, periodDays]);

  const report = useMemo<ShopifyReportResponse | null>(() => {
    if (!model.snapshot && model.loading) return null;
    const total = (key: keyof (typeof model.daily)[number]) => model.daily.reduce((sum, row) => sum + Number(row[key] || 0), 0);
    const orders = total("shopify_orders"), net = total("shopify_net_revenue"), gross = total("shopify_gross_revenue"), refunds = total("shopify_refunds");
    const source = model.sources.find((item) => item.provider === "shopify");
    return { ok: true, client_id: getActiveClientId(), period: { start: period.start, end: period.end, days: periodDays },
      coverage: { data_min_in_period: model.daily[0]?.metric_date || null, data_max_in_period: model.daily.at(-1)?.metric_date || null, data_max_available: source?.data_max_available || null, has_data_in_period: model.daily.length > 0 },
      summary: { revenue_total: gross, net_revenue: net, orders, average_ticket: orders ? net / orders : 0, customers: countUniqueShopifyCustomers(model.daily), paid_orders: total("shopify_paid_orders"), cancelled_orders: 0, refunds_count: refunds ? 1 : 0, refunded_amount: refunds, refunds_occurred_in_period_count: refunds ? 1 : 0, refunds_occurred_in_period_amount: refunds },
      trends: { daily: model.daily.map((row) => ({ date: row.metric_date, revenue: Number(row.shopify_net_revenue || 0), orders: Number(row.shopify_orders || 0), customers: Number(row.shopify_customers || 0), average_ticket: Number(row.shopify_orders) ? Number(row.shopify_net_revenue || 0) / Number(row.shopify_orders) : 0 })) },
      recent_orders: detailReport?.recent_orders || [], top_products: model.products.map((row) => ({ product_id: String(row.product_id), title: String(row.product_title || "Produto"), variant_title: String(row.variant || ""), quantity_sold: Number(row.quantity || 0), revenue: Number(row.net_revenue || 0) })),
      technical: { last_success_at: source?.last_success_at || null, last_received_at: source?.last_success_at || null, processed_count: 0, error_count: 0, recent_errors: [], recent_webhooks: [] } };
  }, [detailReport?.recent_orders, model, period.end, period.start, periodDays]);

  const onRefreshData = useCallback(async () => {
    const requestedClientId = getActiveClientId();
    setSyncNotice(null);
    setSyncingShopify(true);
    try {
      await runExclusiveSync(
        { clientId: requestedClientId, provider: "shopify" },
        () => refreshProviderData("shopify", { start: period.start, end: period.end })
      );
      if (getActiveClientId() !== requestedClientId) return;
      // Só depois do sucesso, relê os dados persistidos.
      await model.refetch();
      if (getActiveClientId() !== requestedClientId) return;
      const selectedPeriod = { start: period.start, end: period.end, days: periodDays };
      const [nextReport, nextCustomers] = await Promise.all([
        getShopifyReport(selectedPeriod),
        getShopifyCustomers(selectedPeriod),
      ]);
      if (getActiveClientId() !== requestedClientId || nextReport.client_id !== requestedClientId || nextCustomers.client_id !== requestedClientId) return;
      setDetailReport(nextReport);
      setCustomerData(nextCustomers);
    } catch (cause) {
      setError(describeSyncError(cause, "Não foi possível atualizar a loja. Mantendo os dados anteriores."));
    } finally {
      setSyncingShopify(false);
    }
  }, [model, period.end, period.start, periodDays]);

  const currency = report?.recent_orders[0]?.currency || "BRL";
  const summary = report?.summary;
  const today = canonicalTodayIso();
  const todayRow = model.snapshot?.daily?.find((row) => row.metric_date === today) || null;
  const shopifyCoverage = model.sources.find((source) => source.provider === "shopify")?.data_max_available || null;
  const todayCovered = Boolean(shopifyCoverage && shopifyCoverage >= today);
  const hasBusinessData = Boolean((summary?.orders || 0) > 0 || (report?.top_products.length || 0) > 0);
  const chartRows = report?.trends.daily || [];
  const chartLabel = SHOPIFY_METRIC_TABS.find((tab) => tab.key === shopifyChartMetric)?.label || "Receita";
  const chartHasData = chartRows.some((row) => Number(row[shopifyChartMetric] || 0) !== 0);
  const chartPeak = uniquePeak(chartRows, (row) => Number(row[shopifyChartMetric] || 0));
  const years = useMemo(() => {
    const currentYear = new Date().getFullYear();
    return Array.from({ length: 5 }).map((_, index) => currentYear - index);
  }, []);

  const filteredCustomers = useMemo(() => {
    const rows = customerData?.items || [];
    const normalizedSearch = customerSearch.trim().toLowerCase();
    const minSpent = asFilterNumber(minTotalSpent);
    const maxSpent = asFilterNumber(maxTotalSpent);
    const minOrdersCount = asFilterNumber(minOrders);

    const filtered = rows.filter((customer) => {
      const matchesSearch =
        !normalizedSearch ||
        customer.name.toLowerCase().includes(normalizedSearch) ||
        String(customer.email || "").toLowerCase().includes(normalizedSearch);
      const matchesMinSpent = minSpent === null || customer.total_spent >= minSpent;
      const matchesMaxSpent = maxSpent === null || customer.total_spent <= maxSpent;
      const matchesMinOrders = minOrdersCount === null || customer.total_orders >= minOrdersCount;
      const matchesLifecycle =
        customerLifecycle === "all" || customer.status === customerLifecycle;

      return matchesSearch && matchesMinSpent && matchesMaxSpent && matchesMinOrders && matchesLifecycle;
    });

    return filtered.sort((left, right) => {
      if (customerSortBy === "total_orders") {
        return right.total_orders - left.total_orders || right.total_spent - left.total_spent;
      }
      if (customerSortBy === "last_purchase_at") {
        return (
          new Date(right.last_purchase_at || 0).getTime() -
            new Date(left.last_purchase_at || 0).getTime() ||
          right.total_spent - left.total_spent
        );
      }
      return right.total_spent - left.total_spent || right.total_orders - left.total_orders;
    });
  }, [
    customerData?.items,
    customerLifecycle,
    customerSearch,
    customerSortBy,
    maxTotalSpent,
    minOrders,
    minTotalSpent,
  ]);

  const customerSummary = useMemo(() => buildCustomerSummary(filteredCustomers), [filteredCustomers]);
  const newCustomers = Math.max(customerSummary.totalCustomers - customerSummary.recurringCustomers, 0);

  const customerSummaryCards = useMemo(() => {
    return [
      {
        label: "Total de clientes",
        value: formatShopifyCompactNumber(customerSummary.totalCustomers),
        hint: undefined,
      },
      {
        label: "Clientes recorrentes",
        value: formatShopifyCompactNumber(customerSummary.recurringCustomers),
        hint: undefined,
      },
      {
        label: "Com mais de 1 pedido",
        value: formatShopifyCompactNumber(customerSummary.multiOrderCustomers),
        hint: undefined,
      },
      {
        label: "Maior comprador",
        value: customerSummary.topCustomer
          ? formatShopifyCurrency(customerSummary.topCustomer.total_spent)
          : formatShopifyCurrency(0),
        hint: customerSummary.topCustomer?.name || "Sem comprador líder no período",
      },
    ];
  }, [customerSummary]);

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
      const today = todayDateInput();
      setSelectedMonth(today.month);
      setSelectedYear(today.year);
      setCurrentMonthPeriod();
      return;
    }
    if (nextPreset === "previous_month") {
      const previous = new Date();
      previous.setMonth(previous.getMonth() - 1);
      setSelectedMonth(previous.getMonth() + 1);
      setSelectedYear(previous.getFullYear());
      setMonthPeriod(previous.getFullYear(), previous.getMonth() + 1);
      return;
    }
    if (nextPreset === "ytd") {
      const today = canonicalTodayIso();
      setPeriod({ start: `${today.slice(0, 4)}-01-01`, end: today });
      return;
    }
    if (nextPreset === "custom") return;
    setMonthPeriod(selectedYear, selectedMonth);
  }

  // Personalizado abre/fecha o painel (mês específico ou datas). Abrir equivale
  // a escolher "Período personalizado" no seletor anterior; os demais atalhos
  // chamam exatamente o mesmo handlePresetChange.
  function selectPeriod(id: string) {
    if (id === "custom") {
      setShowCustom((open) => !open);
      if (preset !== "custom" && preset !== "specific") handlePresetChange("custom");
      return;
    }
    setShowCustom(false);
    handlePresetChange(id as PeriodPreset);
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

  return (
    <Shell variant="editorial" themeClass="theme-editorial" title="Ecommerce">
      <div className="ds-page shopifyReportPage">
        {/* Onde estou: empresa › Ecommerce; procedência e atualização discretas;
            período com os mesmos atalhos e a mesma lógica de antes. */}
        <PageHeader
          company={getActiveClientName()}
          title="Ecommerce"
          dateline={
            <>
              <span className="ds-datelineSource">Shopify</span>
              <span>{report?.technical.last_success_at ? `Dados atualizados ${formatFreshness(report.technical.last_success_at)}` : "Sem atualização concluída"}</span>
              <span>
                  <button
                    className="btn intelHeaderAction"
                    disabled={syncingShopify || model.refreshing}
                    onClick={() => {
                      void onRefreshData();
                    }}
                    type="button"
                  >
                    {syncingShopify || model.refreshing ? "Atualizando..." : "Atualizar dados"}
                  </button>
                </span>
            </>
          }
          controls={
            <SegmentedControl
              ariaLabel="Período"
              value={showCustom || preset === "custom" || preset === "specific" ? "custom" : preset}
              onSelect={selectPeriod}
              options={[
                ...SHOPIFY_PERIOD_OPTIONS,
                { id: "custom", label: "Personalizado", expanded: showCustom },
              ]}
            />
          }
          panel={
            showCustom ? (
              <div className="ds-customPeriod">
                <label className="ds-field">
                  <span>Mês</span>
                  <select value={selectedMonth} onChange={(event) => handleMonthChange(Number(event.target.value))}>
                    {Array.from({ length: 12 }).map((_, index) => {
                      const month = index + 1;
                      return (
                        <option key={month} value={month}>
                          {formatShopifyMonthLabel(month)}
                        </option>
                      );
                    })}
                  </select>
                </label>
                <label className="ds-field">
                  <span>Ano</span>
                  <select value={selectedYear} onChange={(event) => handleYearChange(Number(event.target.value))}>
                    {years.map((year) => (
                      <option key={year} value={year}>
                        {year}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="ds-field">
                  <span>Data inicial</span>
                  <input type="date" value={period.start} onChange={(event) => { setPreset("custom"); setPeriod({ start: event.target.value, end: period.end }); }} />
                </label>
                <label className="ds-field">
                  <span>Data final</span>
                  <input type="date" value={period.end} onChange={(event) => { setPreset("custom"); setPeriod({ start: period.start, end: event.target.value }); }} />
                </label>
              </div>
            ) : preset === "day" ? (
              <DayPeriodControl />
            ) : null
          }
          controlsNote={formatCalendarRange(period.start, period.end)}
        />

        {syncNotice ? <p className="ds-status" role="status">{syncNotice}</p> : null}

        {model.loading && !report ? <p className="ds-status" role="status">Carregando vendas da Shopify...</p> : null}

        {!model.loading && error && !report ? (
          <DataNotice tone="negative" role="alert" title="Vendas Shopify indisponíveis">
            Não foi possível carregar os dados da Shopify. {error}
          </DataNotice>
        ) : null}

        {!model.loading && report ? (
          <div className="ds-stack">
            {error || model.error ? (
              <DataNotice tone="warning" title="Não foi possível atualizar agora">
                Exibindo a última leitura disponível.
              </DataNotice>
            ) : null}

            {!hasBusinessData ? <DataNotice title="Ainda não há dados da Shopify neste período." /> : null}

            {/* Mesma leitura do FBITS: quanto vendeu; depois o que explica; por fim o operacional. */}
            <section className="ds-summary" id="shopify-overview" aria-label="Resumo do período">
              <HeroFigure
                value={formatCurrencyShort(summary?.net_revenue || 0)}
                exactValue={formatShopifyCurrency(summary?.net_revenue || 0, currency)}
                rawValue={summary?.net_revenue || 0}
                label="vendidos no período"
                testId="shopify-receita"
              />
              <div className="ds-kpis">
                <KpiFigure label="Pedidos" value={formatShopifyCompactNumber(summary?.orders || 0)} rawValue={summary?.orders || 0} />
                <KpiFigure
                  label="Ticket médio"
                  value={summary?.orders ? formatShopifyCurrency(summary.average_ticket || 0, currency) : "—"}
                  rawValue={summary?.average_ticket || 0}
                />
                <KpiFigure label="Clientes" value={formatShopifyCompactNumber(summary?.customers || 0)} rawValue={summary?.customers || 0} />
              </div>
              <div className="ds-secondary">
                <dl className="ds-inlineStats">
                  <div>
                    <dt>Hoje, {formatCivilDate(today)}</dt>
                    <dd>
                      {todayCovered
                        ? `${formatShopifyCurrency(todayRow?.shopify_net_revenue || 0, currency)} em ${formatShopifyCompactNumber(todayRow?.shopify_orders || 0)} pedidos${
                            todayRow?.shopify_orders
                              ? ` · ticket ${formatShopifyCurrency(Number(todayRow.shopify_net_revenue || 0) / Number(todayRow.shopify_orders), currency)}`
                              : ""
                          }`
                        : "Ainda não atualizado"}
                    </dd>
                  </div>
                  {summary ? <div><dt>Pedidos pagos</dt><dd>{formatShopifyCompactNumber(summary.paid_orders)}</dd></div> : null}
                  {summary && (summary.cancelled_orders || summary.refunds_count) ? (
                    <>
                      <div><dt>Cancelados</dt><dd>{formatShopifyCompactNumber(summary.cancelled_orders)}</dd></div>
                      <div><dt>Reembolsos</dt><dd>{formatShopifyCompactNumber(summary.refunds_count)} · {formatShopifyCurrency(summary.refunded_amount, currency)}</dd></div>
                    </>
                  ) : null}
                </dl>
                <p className="ds-footnote">
                  Receita real da loja, líquida.{todayCovered ? " Os dados de hoje ainda podem sofrer alterações." : ""}
                </p>
              </div>
            </section>

            <section className="ds-section ds-chartSection" aria-labelledby="shopify-trend-title">
              <div className="ds-sectionHead">
                <div className="ds-sectionHeadText">
                  <h2 id="shopify-trend-title" className="ds-sectionTitle">{shopifyTrendTitle(chartPeak, shopifyChartMetric)}</h2>
                  {chartPeak && shopifyChartMetric === "revenue" ? (
                    <p className="ds-caption">
                      {formatShopifyCurrency(chartPeak.revenue, currency)} em {formatShopifyCompactNumber(chartPeak.orders)} {chartPeak.orders === 1 ? "pedido" : "pedidos"}
                    </p>
                  ) : null}
                </div>
                <SegmentedControl
                  ariaLabel="Métrica do gráfico"
                  value={shopifyChartMetric}
                  onSelect={(id) => setShopifyChartMetric(id as ShopifyMetricKey)}
                  options={SHOPIFY_METRIC_TABS.map((tab) => ({ id: tab.key, label: tab.label }))}
                />
              </div>
              {chartHasData ? (
                <TrendChart
                  data={chartRows}
                  xKey="date"
                  primaryKey={shopifyChartMetric}
                  secondaryKey={shopifyChartMetric === "revenue" ? "orders" : undefined}
                  formatX={(value) => formatCalendarDate(value)}
                  formatY={shopifyChartMetric === "revenue" || shopifyChartMetric === "average_ticket" ? formatCurrencyAxis : formatInteger}
                  ariaLabel={`${chartLabel} por dia, ${formatCalendarRange(period.start, period.end)}.`}
                  testId="shopify-sales-chart"
                  renderTooltip={(row) => (
                    <>
                      <strong>{formatCalendarDate(row.date, "long")}</strong>
                      <dl>
                        <dt>Receita</dt><dd>{formatShopifyCurrency(row.revenue, currency)}</dd>
                        <dt>Pedidos</dt><dd>{formatShopifyCompactNumber(row.orders)}</dd>
                        <dt>Clientes</dt><dd>{formatShopifyCompactNumber(row.customers)}</dd>
                        <dt>Ticket médio</dt><dd>{formatShopifyCurrency(row.average_ticket, currency)}</dd>
                      </dl>
                    </>
                  )}
                />
              ) : (
                <p className="ds-emptyLine">Sem dados de {chartLabel.toLowerCase()} neste período.</p>
              )}
            </section>

            <section className="ds-section" aria-labelledby="shopify-products-title">
              <h2 id="shopify-products-title" className="ds-sectionTitle">Produtos mais vendidos</h2>
              {model.snapshot?.productsLoading && !model.products.length
                ? <p role="status">Carregando produtos...</p>
                : model.snapshot?.secondaryErrors?.includes("products")
                  ? <p role="alert">Não foi possível carregar produtos.</p>
                  : <ShopifyTopProductsCard products={report.top_products} />}
            </section>

            <section ref={customerDemand.observe} className="ds-section" id="shopify-customers" aria-labelledby="shopify-customers-title">
              <div className="ds-sectionHead">
                <h2 id="shopify-customers-title" className="ds-sectionTitle">Clientes</h2>
                <p className="ds-caption">
                  {model.refreshing ? "Atualizando… · " : ""}
                  {formatShopifyCompactNumber(filteredCustomers.length)} {filteredCustomers.length === 1 ? "cliente" : "clientes"} no filtro
                </p>
              </div>

              {detailsLoading && !customerData ? <p className="ds-status" role="status">Carregando clientes...</p> : null}

              {!model.loading && customerData ? (
                <div className="ds-group">
                  <div className="ds-kpis is-four">
                    {customerSummaryCards.map((card) => (
                      <div className="ds-kpi" key={card.label}>
                        <span className="ds-kpiValue">{card.value}</span>
                        <span className="ds-kpiLabel">{card.label}</span>
                        {card.hint ? <span className="ds-kpiHint">{card.hint}</span> : null}
                      </div>
                    ))}
                  </div>

                  {customerSummary.totalCustomers > 0 ? (
                    <div className="shopifyLifecycleBar" aria-label="Novos contra recorrentes">
                      <div className="shopifyLifecycleBarTrack">
                        <span
                          className="is-new"
                          style={{ width: `${(newCustomers / customerSummary.totalCustomers) * 100}%` }}
                        />
                        <span
                          className="is-recurring"
                          style={{ width: `${(customerSummary.recurringCustomers / customerSummary.totalCustomers) * 100}%` }}
                        />
                      </div>
                      <div className="shopifyLifecycleBarLegend">
                        <span><i className="is-new" /> Novos — {formatShopifyCompactNumber(newCustomers)}</span>
                        <span><i className="is-recurring" /> Recorrentes — {formatShopifyCompactNumber(customerSummary.recurringCustomers)}</span>
                      </div>
                    </div>
                  ) : null}

                  <div className="ds-split shopifyCustomerTools">
                    <ShopifyExecutiveSummaryCard customers={filteredCustomers} />
                    <div className="shopifyFilterPanel">
                      <h3 className="ds-subTitle">Filtrar clientes</h3>
                      <ShopifyCustomerFilters
                        lifecycle={customerLifecycle}
                        maxTotalSpent={maxTotalSpent}
                        minOrders={minOrders}
                        minTotalSpent={minTotalSpent}
                        onLifecycleChange={setCustomerLifecycle}
                        onMaxTotalSpentChange={setMaxTotalSpent}
                        onMinOrdersChange={setMinOrders}
                        onMinTotalSpentChange={setMinTotalSpent}
                        onSearchChange={setCustomerSearch}
                        onSortByChange={setCustomerSortBy}
                        search={customerSearch}
                        sortBy={customerSortBy}
                      />
                    </div>
                  </div>

                  <ShopifyCustomersTable customers={filteredCustomers} />
                </div>
              ) : null}
            </section>

            <section ref={orderDemand.observe} className="ds-section" id="shopify-operations" aria-labelledby="shopify-orders-title">
              <h2 id="shopify-orders-title" className="ds-sectionTitle">Pedidos recentes</h2>
              <ShopifyOrdersTable orders={report.recent_orders} />
            </section>

            <ShopifySalesHistory
              rows={historicalModel.daily}
              coverageStart={historicalModel.sources.find((source) => source.provider === "shopify")?.data_min_available || null}
              coverageEnd={historicalModel.sources.find((source) => source.provider === "shopify")?.data_max_available || null}
            />

            <section className="ds-section" id="shopify-attribution" aria-labelledby="shopify-attribution-title">
              <div className="ds-sectionHeadText">
                <h2 id="shopify-attribution-title" className="ds-sectionTitle">Receita em cada plataforma</h2>
                <p className="ds-caption">Cada plataforma mede a receita à sua maneira. Os valores não devem ser somados.</p>
              </div>
              <dl className="ds-sourceList">
                <div>
                  <dt>Shopify</dt>
                  <dd>
                    <strong>{formatShopifyCurrency(summary?.net_revenue || 0, currency)}</strong>
                    <span>Receita real da loja no período — a referência para faturamento.</span>
                  </dd>
                </div>
                <div>
                  <dt>Meta Ads</dt>
                  <dd>
                    <button type="button" className="ds-link" onClick={onOpenDashboard}>Ver em Meta</button>
                    <span>Receita atribuída pelo modelo de atribuição da própria Meta.</span>
                  </dd>
                </div>
                <div>
                  <dt>Google Analytics 4</dt>
                  <dd>
                    {onOpenGoogleReport ? <button type="button" className="ds-link" onClick={onOpenGoogleReport}>Ver em Google</button> : null}
                    <span>Receita observada pela navegação no site, não pela loja.</span>
                  </dd>
                </div>
                <div>
                  <dt>Google Ads</dt>
                  <dd>
                    {onOpenGoogleReport ? <button type="button" className="ds-link" onClick={onOpenGoogleReport}>Ver em Google</button> : null}
                    <span>Retorno atribuído pelo Google Ads no período selecionado.</span>
                  </dd>
                </div>
              </dl>
            </section>
          </div>
        ) : null}
      </div>
    </Shell>
  );
}
