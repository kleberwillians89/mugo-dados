import { useCallback, useEffect, useMemo, useState } from "react";
import Shell from "../components/Shell";
import ShopifyChartCard from "../components/shopify/ShopifyChartCard";
import ShopifyCustomerFilters from "../components/shopify/ShopifyCustomerFilters";
import ShopifyCustomersTable from "../components/shopify/ShopifyCustomersTable";
import ShopifyExecutiveSummaryCard from "../components/shopify/ShopifyExecutiveSummaryCard";
import ShopifyKpiCard from "../components/shopify/ShopifyKpiCard";
import ShopifyOrdersTable from "../components/shopify/ShopifyOrdersTable";
import ShopifySectionHeader from "../components/shopify/ShopifySectionHeader";
import ShopifyTopProductsCard from "../components/shopify/ShopifyTopProductsCard";
import { usePeriod } from "../app/PeriodContext";
import {
  getShopifyCustomers,
  getShopifyReport,
  resolveShopifyConnectionIdForRead,
  syncShopifyConnection,
} from "../app/api";
import { useDashboardSnapshot } from "../app/DashboardDataContext";
import { countUniqueShopifyCustomers } from "../app/shopifyReadModel";
import { getActiveClientId, getActiveClientName, MUGO_APP_NAME } from "../app/activeClient";
import { describeSyncError, isSyncAlreadyRunningError, runExclusiveSync } from "../app/syncOrchestrator";
import {
  formatShopifyCompactNumber,
  formatShopifyCurrency,
  formatShopifyDateTime,
  formatShopifyMonthLabel,
} from "../app/shopifyUi";
import type {
  ShopifyCustomerRow,
  ShopifyCustomersResponse,
  ShopifyReportResponse,
} from "../app/types";
import "../styles/shopify-report.css";

type Props = {
  onLogout: () => void | Promise<void>;
  onOpenDashboard: () => void;
  onOpenGoogleReport?: () => void;
};

// Regra operacional do piloto: o botão manual sincroniza os últimos 60 dias
// (histórico recente), nunca o histórico completo — evita reprocessar anos
// de pedidos a cada clique.
const SHOPIFY_MANUAL_SYNC_DAYS = 60;

type PeriodPreset = "7d" | "30d" | "month" | "specific";
type ShopifyMetricKey = "revenue" | "orders" | "customers" | "average_ticket";

const SHOPIFY_METRIC_TABS: { key: ShopifyMetricKey; label: string; description: string }[] = [
  { key: "revenue", label: "Receita", description: "Faturamento diário" },
  { key: "orders", label: "Pedidos", description: "Pedidos diários" },
  { key: "customers", label: "Clientes", description: "Clientes por período" },
  { key: "average_ticket", label: "Ticket médio", description: "Ticket médio por período" },
];
type CustomerLifecycleFilter = "all" | "new" | "recurring";
type CustomerSortBy = "total_spent" | "total_orders" | "last_purchase_at";

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

function ShopifyReportSkeleton() {
  return (
    <div className="shopifySkeletonLayout" aria-hidden="true">
      <div className="shopifySkeletonHero skeletonBlock" />
      <div className="shopifySkeletonGrid">
        {Array.from({ length: 6 }).map((_, index) => (
          <div key={index} className="shopifySkeletonCard skeletonBlock" />
        ))}
      </div>
      <div className="shopifySkeletonCharts">
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index} className="shopifySkeletonChart skeletonBlock" />
        ))}
      </div>
      <div className="shopifySkeletonTable skeletonBlock" />
    </div>
  );
}

export default function Shopify({ onLogout, onOpenDashboard, onOpenGoogleReport }: Props) {
  const { period, periodDays, setCurrentMonthPeriod, setMonthPeriod, setPresetPeriod } = usePeriod();
  const [shopifyChartMetric, setShopifyChartMetric] = useState<ShopifyMetricKey>("revenue");
  const [preset, setPreset] = useState<PeriodPreset>(() =>
    resolveInitialPreset(period.start, period.end, periodDays)
  );
  const initialDate = todayDateInput();
  const [selectedMonth, setSelectedMonth] = useState(initialDate.month);
  const [selectedYear, setSelectedYear] = useState(initialDate.year);
  const model = useDashboardSnapshot(period.start, period.end);
  const [error, setError] = useState<string | null>(null);
  const [syncingShopify, setSyncingShopify] = useState(false);
  const [syncNotice, setSyncNotice] = useState<string | null>(null);
  const [customerSearch, setCustomerSearch] = useState("");
  const [minTotalSpent, setMinTotalSpent] = useState("");
  const [maxTotalSpent, setMaxTotalSpent] = useState("");
  const [minOrders, setMinOrders] = useState("");
  const [customerLifecycle, setCustomerLifecycle] = useState<CustomerLifecycleFilter>("all");
  const [customerSortBy, setCustomerSortBy] = useState<CustomerSortBy>("total_spent");
  const [customerData, setCustomerData] = useState<ShopifyCustomersResponse | null>(null);
  const [detailReport, setDetailReport] = useState<ShopifyReportResponse | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(true);

  useEffect(() => {
    const startDate = new Date(`${period.start}T00:00:00`);
    if (Number.isNaN(startDate.getTime())) return;
    setSelectedMonth(startDate.getMonth() + 1);
    setSelectedYear(startDate.getFullYear());
    setPreset(resolveInitialPreset(period.start, period.end, periodDays));
  }, [period.end, period.start, periodDays]);

  useEffect(() => {
    let active = true;
    setDetailsLoading(true);
    setCustomerData(null);
    setDetailReport(null);
    const selectedPeriod = { start: period.start, end: period.end, days: periodDays };
    void Promise.all([getShopifyReport(selectedPeriod), getShopifyCustomers(selectedPeriod)])
      .then(([nextReport, nextCustomers]) => {
        if (!active) return;
        setDetailReport(nextReport);
        setCustomerData(nextCustomers);
      })
      .catch((loadError: unknown) => {
        if (!active) return;
        setError(loadError instanceof Error ? loadError.message : "Não foi possível carregar os detalhes da Shopify.");
      })
      .finally(() => {
        if (active) setDetailsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [period.end, period.start, periodDays]);

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
    setSyncNotice(null);
    setSyncingShopify(true);
    try {
      const connectionId = await resolveShopifyConnectionIdForRead(getActiveClientId());
      if (connectionId) {
        try {
          await runExclusiveSync(
            { clientId: getActiveClientId(), provider: "shopify", connectionId },
            () => syncShopifyConnection(connectionId, SHOPIFY_MANUAL_SYNC_DAYS)
          );
        } catch (syncError: unknown) {
          if (isSyncAlreadyRunningError(syncError)) {
            // Estado válido, nunca erro vermelho — outra sincronização
            // (ex.: reconciliação periódica) já está rodando para esta loja.
            setSyncNotice("Importação já está em andamento.");
          } else {
            // Preserva os dados já carregados (report/customerData não são
            // tocados aqui) e mostra mensagem humana, sem reler os dados —
            // a última leitura persistida válida continua na tela.
            setError(describeSyncError(syncError, "Não foi possível sincronizar a loja Shopify agora."));
            return;
          }
        }
      }
      // Sync concluído (ou já em andamento) — relê os dados persistidos.
      await model.refetch();
      const selectedPeriod = { start: period.start, end: period.end, days: periodDays };
      const [nextReport, nextCustomers] = await Promise.all([
        getShopifyReport(selectedPeriod),
        getShopifyCustomers(selectedPeriod),
      ]);
      setDetailReport(nextReport);
      setCustomerData(nextCustomers);
    } finally {
      setSyncingShopify(false);
    }
  }, [model, period.end, period.start, periodDays]);

  const currency = report?.recent_orders[0]?.currency || "BRL";
  const summary = report?.summary;
  const hasBusinessData = Boolean((summary?.orders || 0) > 0 || (report?.top_products.length || 0) > 0);
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
        hint: "Clientes ativos no período filtrado",
      },
      {
        label: "Clientes recorrentes",
        value: formatShopifyCompactNumber(customerSummary.recurringCustomers),
        hint: "Base com recompra registrada",
      },
      {
        label: "Com mais de 1 pedido",
        value: formatShopifyCompactNumber(customerSummary.multiOrderCustomers),
        hint: "Clientes com maior profundidade de compra",
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

  return (
    <Shell
      themeClass="theme-client"
      title={MUGO_APP_NAME}
      subtitle="Relatório executivo da operação Shopify"
      right={
        <div className="shopifyShellActions">
          <button className="btn btnGhost" onClick={onOpenDashboard} type="button">
            Dados Meta
          </button>
          {onOpenGoogleReport ? (
            <button className="btn btnGhost" onClick={onOpenGoogleReport} type="button">
              Analytics
            </button>
          ) : null}
          <button className="btnLogout" onClick={() => onLogout()} type="button">
            Sair
          </button>
        </div>
      }
    >
      <div className="shopifyReportPage">
        <section className="shopifyHero">
          <div className="shopifyHeroCopy">
            <div className="shopifyPageEyebrow">Relatório Shopify</div>
            <h1 className="shopifyPageTitle">Dados da Shopify</h1>
            <p className="shopifyPageSubtitle">Visão da operação da loja da {getActiveClientName()}.</p>
            <div className="shopifyHeroMeta">
              <span className="pill">Shopify</span>
              <span className="shopifyHeroTimestamp">
                Última leitura: {formatShopifyDateTime(report?.technical.last_received_at)}
              </span>
            </div>
            <div className="shopifyQuickNav">
              <a className="shopifyQuickNavLink" href="#shopify-overview">
                Visão geral
              </a>
              <a className="shopifyQuickNavLink" href="#shopify-customers">
                Clientes
              </a>
              <a className="shopifyQuickNavLink" href="#shopify-operations">
                Operação
              </a>
            </div>
          </div>

          <div className="shopifyFilterCard">
            <label className="shopifyFilterField">
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

            <label className="shopifyFilterField">
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
                      {formatShopifyMonthLabel(month)}
                    </option>
                  );
                })}
              </select>
            </label>

            <label className="shopifyFilterField">
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

            <button
              className="btn btnPrimary shopifyRefreshButton"
              disabled={syncingShopify || model.refreshing}
              onClick={() => {
                void onRefreshData();
              }}
              type="button"
            >
              {syncingShopify || model.refreshing ? "Atualizando..." : "Atualizar dados"}
            </button>
          </div>
        </section>

        {syncNotice ? <div className="shopifyFeedbackCard">{syncNotice}</div> : null}

        {model.loading && !report ? <ShopifyReportSkeleton /> : null}

        {!model.loading && error && !report ? (
          <div className="shopifyFeedbackCard isError">Não foi possível carregar os dados da Shopify. {error}</div>
        ) : null}

        {!model.loading && report ? (
          <>
            {error ? (
              <div className="shopifyFeedbackCard">
                Não foi possível atualizar agora. Exibindo a última leitura disponível.
              </div>
            ) : null}

            {!hasBusinessData ? (
              <div className="shopifyFeedbackCard">
                Ainda não há dados da Shopify neste período.
              </div>
            ) : null}

            <section className="shopifySection" id="shopify-overview">
              <div className="shopifyPerformanceHero">
                <span className="shopifyPerformanceEyebrow">Operação Shopify</span>
                <p className="shopifyPerformanceNarrative">A receita real da loja no período selecionado.</p>
                <div className="shopifyPerformanceMain">
                  <strong>{formatShopifyCurrency(summary?.net_revenue || 0, currency)}</strong>
                  <span>Receita da loja</span>
                </div>
                <div className="shopifyPerformanceSub">
                  <div><span>Pedidos</span><b>{formatShopifyCompactNumber(summary?.orders || 0)}</b></div>
                  <div><span>Ticket médio</span><b>{formatShopifyCurrency(summary?.average_ticket || 0, currency)}</b></div>
                  <div><span>Clientes</span><b>{formatShopifyCompactNumber(summary?.customers || 0)}</b></div>
                </div>
                {summary ? (
                  <span className="shopifyPerformanceFooter">
                    {formatShopifyCompactNumber(summary.paid_orders)} pedidos pagos
                    {summary.cancelled_orders || summary.refunds_count
                      ? ` · ${formatShopifyCompactNumber(summary.cancelled_orders)} cancelados · ${formatShopifyCompactNumber(summary.refunds_count)} reembolsos (${formatShopifyCurrency(summary.refunded_amount, currency)})`
                      : ""}
                  </span>
                ) : null}
                <span className="shopifyPerformanceSource">Fonte: Shopify</span>
              </div>
            </section>

            <section className="shopifySection">
              <div className="shopifyChartHead">
                <span className="shopifyChartHeadTitle">Ritmo da operação</span>
                <div className="shopifyChartTabs" role="tablist" aria-label="Métrica do gráfico">
                  {SHOPIFY_METRIC_TABS.map((tab) => (
                    <button
                      key={tab.key}
                      type="button"
                      role="tab"
                      aria-selected={shopifyChartMetric === tab.key}
                      className={`shopifyChartTab${shopifyChartMetric === tab.key ? " is-active" : ""}`}
                      onClick={() => setShopifyChartMetric(tab.key)}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="shopifyChartGrid shopifyChartGrid-single">
                <ShopifyChartCard
                  color="#1a1718"
                  data={report.trends.daily}
                  dataKey={shopifyChartMetric}
                  description={SHOPIFY_METRIC_TABS.find((tab) => tab.key === shopifyChartMetric)?.description || ""}
                  title={SHOPIFY_METRIC_TABS.find((tab) => tab.key === shopifyChartMetric)?.label || ""}
                  periodValue={
                    shopifyChartMetric === "average_ticket"
                      ? summary?.average_ticket
                      : shopifyChartMetric === "customers"
                        ? summary?.customers
                        : undefined
                  }
                  valueFormatter={
                    shopifyChartMetric === "revenue" || shopifyChartMetric === "average_ticket"
                      ? (value) => formatShopifyCurrency(value, currency)
                      : undefined
                  }
                />
              </div>
            </section>

            <section className="shopifySection" id="shopify-customers">
              <ShopifySectionHeader
                eyebrow="Clientes"
                title="Quem mais compra na Mugô Dados"
                description="Visão comercial da base Shopify para identificar os melhores compradores, recorrência e profundidade de compra."
                action={
                  <div className="shopifySectionStatus">
                    {model.refreshing ? <span className="pill">Atualizando...</span> : null}
                    <span className="pill">{formatShopifyCompactNumber(filteredCustomers.length)} clientes</span>
                  </div>
                }
              />

              {detailsLoading && !customerData ? (
                <div className="shopifyCustomerSkeleton">
                  <div className="shopifyCustomerSummaryGrid">
                    {Array.from({ length: 4 }).map((_, index) => (
                      <div key={index} className="shopifySkeletonCard skeletonBlock" />
                    ))}
                  </div>
                  <div className="shopifyCustomerFeatureGrid">
                    <div className="shopifySkeletonChart skeletonBlock" />
                    <div className="shopifySkeletonChart skeletonBlock" />
                  </div>
                  <div className="shopifySkeletonTable skeletonBlock" />
                </div>
              ) : null}

              {!model.loading && customerData ? (
                <>
                  <div className="shopifyCustomerSummaryGrid">
                    {customerSummaryCards.map((card) => (
                      <ShopifyKpiCard
                        key={card.label}
                        hint={card.hint}
                        label={card.label}
                        value={card.value}
                      />
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

                  <div className="shopifyCustomerFeatureGrid">
                    <ShopifyExecutiveSummaryCard customers={filteredCustomers} />
                    <article className="shopifyFilterPanel">
                      <div className="shopifyListHead">
                        <div>
                          <div className="shopifyMiniLabel">Filtros comerciais</div>
                          <p className="shopifyChartDescription">
                            Refine a carteira por valor, frequência, momento de compra e recorrência.
                          </p>
                        </div>
                      </div>
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
                    </article>
                  </div>

                  <ShopifyCustomersTable customers={filteredCustomers} />
                </>
              ) : null}
            </section>

            <section className="shopifySection" id="shopify-operations">
              <ShopifySectionHeader
                eyebrow="Pedidos recentes"
                title="Leitura operacional"
                description="Pedidos mais novos para conferência rápida de cliente, status financeiro e volume."
              />
              <ShopifyOrdersTable orders={report.recent_orders} />
            </section>

            <section className="shopifySection shopifySecondaryGrid">
              <div>
                <ShopifySectionHeader
                  eyebrow="Produtos"
                  title="Itens com mais tração"
                  description="Os principais produtos do período por volume vendido e receita gerada."
                />
                <ShopifyTopProductsCard products={report.top_products} />
              </div>

            </section>

            <section className="shopifySection" id="shopify-attribution">
              <ShopifySectionHeader
                eyebrow="Atribuição"
                title="Shopify, Meta, GA4 e Google Ads"
                description="Cada plataforma mede a receita à sua própria maneira."
              />
              <div className="shopifyAttributionGrid">
                <article className="shopifyAttributionCard is-known">
                  <span>Shopify</span>
                  <strong>{formatShopifyCurrency(summary?.net_revenue || 0, currency)}</strong>
                  <small>Receita real da loja no período — fonte de verdade para faturamento.</small>
                </article>
                <article className="shopifyAttributionCard">
                  <span>Meta Ads</span>
                  <strong>Ver no Dashboard</strong>
                  <small>Receita atribuída pela Meta, calculada com o modelo de atribuição da própria plataforma.</small>
                  <button type="button" className="btn btnGhost" onClick={onOpenDashboard}>Abrir Dashboard</button>
                </article>
                <article className="shopifyAttributionCard">
                  <span>Google Analytics 4</span>
                  <strong>Ver em Analytics</strong>
                  <small>Receita observada pelo GA4 a partir do comportamento de navegação, não da loja.</small>
                  {onOpenGoogleReport ? (
                    <button type="button" className="btn btnGhost" onClick={onOpenGoogleReport}>Abrir Analytics</button>
                  ) : null}
                </article>
                <article className="shopifyAttributionCard">
                  <span>Google Ads</span>
                  <strong>Ver no Dashboard</strong>
                  <small>Retorno atribuído pelo Google Ads no período selecionado.</small>
                </article>
              </div>
              <p className="shopifyAttributionNotice">
                Essas plataformas utilizam modelos de atribuição diferentes. Os valores não devem ser somados.
              </p>
            </section>
          </>
        ) : null}
      </div>
    </Shell>
  );
}
