import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Shell from "../components/Shell";
import ShopifyChartCard from "../components/shopify/ShopifyChartCard";
import ShopifyCustomerFilters from "../components/shopify/ShopifyCustomerFilters";
import ShopifyCustomersTable from "../components/shopify/ShopifyCustomersTable";
import ShopifyExecutiveSummaryCard from "../components/shopify/ShopifyExecutiveSummaryCard";
import ShopifyKpiCard from "../components/shopify/ShopifyKpiCard";
import ShopifyOrdersTable from "../components/shopify/ShopifyOrdersTable";
import ShopifySectionHeader from "../components/shopify/ShopifySectionHeader";
import ShopifyTopProductsCard from "../components/shopify/ShopifyTopProductsCard";
import ShopifyWebhookStatusCard from "../components/shopify/ShopifyWebhookStatusCard";
import { usePeriod } from "../app/PeriodContext";
import { getShopifyCustomers, getShopifyReport } from "../app/api";
import { getActiveClientName, MUGO_APP_NAME } from "../app/activeClient";
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

type PeriodPreset = "7d" | "30d" | "month" | "specific";
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

function toErrorMessage(error: unknown) {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  return "Não foi possível carregar os dados da Shopify.";
}

function asFilterNumber(value: string): number | null {
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
  const [preset, setPreset] = useState<PeriodPreset>(() =>
    resolveInitialPreset(period.start, period.end, periodDays)
  );
  const initialDate = todayDateInput();
  const [selectedMonth, setSelectedMonth] = useState(initialDate.month);
  const [selectedYear, setSelectedYear] = useState(initialDate.year);
  const [report, setReport] = useState<ShopifyReportResponse | null>(null);
  const [customerData, setCustomerData] = useState<ShopifyCustomersResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [customersLoading, setCustomersLoading] = useState(true);
  const [customersRefreshing, setCustomersRefreshing] = useState(false);
  const [customersError, setCustomersError] = useState<string | null>(null);
  const [customerSearch, setCustomerSearch] = useState("");
  const [minTotalSpent, setMinTotalSpent] = useState("");
  const [maxTotalSpent, setMaxTotalSpent] = useState("");
  const [minOrders, setMinOrders] = useState("");
  const [customerLifecycle, setCustomerLifecycle] = useState<CustomerLifecycleFilter>("all");
  const [customerSortBy, setCustomerSortBy] = useState<CustomerSortBy>("total_spent");
  const customerDataRef = useRef<ShopifyCustomersResponse | null>(null);

  useEffect(() => {
    customerDataRef.current = customerData;
  }, [customerData]);

  useEffect(() => {
    const startDate = new Date(`${period.start}T00:00:00`);
    if (Number.isNaN(startDate.getTime())) return;
    setSelectedMonth(startDate.getMonth() + 1);
    setSelectedYear(startDate.getFullYear());
    setPreset(resolveInitialPreset(period.start, period.end, periodDays));
  }, [period.end, period.start, periodDays]);

  const loadReport = useCallback(
    async (mode: "initial" | "refresh" = "initial") => {
      if (mode === "refresh") {
        setRefreshing(true);
      } else {
        setLoading(true);
      }
      setError(null);

      try {
        const next = await getShopifyReport({
          start: period.start,
          end: period.end,
          days: periodDays,
        });
        setReport(next);
      } catch (requestError: unknown) {
        setError(toErrorMessage(requestError));
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [period.end, period.start, periodDays]
  );

  useEffect(() => {
    void loadReport();
  }, [loadReport]);

  const loadCustomers = useCallback(async (mode: "initial" | "refresh" = "initial") => {
    if (mode === "refresh" && customerDataRef.current) {
      setCustomersRefreshing(true);
    } else {
      setCustomersLoading(true);
    }
    setCustomersError(null);

    try {
      const next = await getShopifyCustomers({
        start: period.start,
        end: period.end,
        days: periodDays,
      });
      setCustomerData(next);
    } catch (requestError: unknown) {
      setCustomersError(toErrorMessage(requestError));
    } finally {
      setCustomersLoading(false);
      setCustomersRefreshing(false);
    }
  }, [period.end, period.start, periodDays]);

  useEffect(() => {
    void loadCustomers();
  }, [loadCustomers]);

  const currency = report?.recent_orders[0]?.currency || "BRL";
  const summary = report?.summary;
  const hasBusinessData = Boolean((summary?.orders || 0) > 0 || (report?.top_products.length || 0) > 0);
  const years = useMemo(() => {
    const currentYear = new Date().getFullYear();
    return Array.from({ length: 5 }).map((_, index) => currentYear - index);
  }, []);

  const summaryCards = useMemo(() => {
    if (!summary) return [];
    return [
      {
        label: "Faturamento total",
        value: formatShopifyCurrency(summary.revenue_total, currency),
        hint: `${summary.paid_orders} pedidos pagos no período`,
        tone: "accent" as const,
      },
      {
        label: "Pedidos",
        value: formatShopifyCompactNumber(summary.orders),
        hint: `${summary.customers} clientes atendidos`,
        tone: "default" as const,
      },
      {
        label: "Ticket médio",
        value: formatShopifyCurrency(summary.average_ticket, currency),
        hint: "Média por pedido no período",
        tone: "default" as const,
      },
      {
        label: "Clientes",
        value: formatShopifyCompactNumber(summary.customers),
        hint: "Base com compra registrada",
        tone: "default" as const,
      },
      {
        label: "Pedidos pagos",
        value: formatShopifyCompactNumber(summary.paid_orders),
        hint: `${summary.orders ? Math.round((summary.paid_orders / summary.orders) * 100) : 0}% do total de pedidos`,
        tone: "default" as const,
      },
      {
        label: "Cancelados / reembolsados",
        value: `${formatShopifyCompactNumber(summary.cancelled_orders)} / ${formatShopifyCompactNumber(summary.refunds_count)}`,
        hint: `${formatShopifyCurrency(summary.refunded_amount, currency)} em reembolsos`,
        tone: "default" as const,
      },
    ];
  }, [currency, summary]);

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
              Dados Google
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
              <span className="pill">{report?.shop_domain || "Loja ainda não conectada"}</span>
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
              disabled={refreshing || customersRefreshing}
              onClick={() => {
                void Promise.all([loadReport("refresh"), loadCustomers("refresh")]);
              }}
              type="button"
            >
              {refreshing || customersRefreshing ? "Atualizando..." : "Atualizar dados"}
            </button>
          </div>
        </section>

        {loading && !report ? <ShopifyReportSkeleton /> : null}

        {!loading && error ? (
          <div className="shopifyFeedbackCard isError">Não foi possível carregar os dados da Shopify. {error}</div>
        ) : null}

        {!loading && !error && report ? (
          <>
            {!hasBusinessData ? (
              <div className="shopifyFeedbackCard">
                Ainda não há dados da Shopify neste período.
              </div>
            ) : null}

            <section className="shopifySection" id="shopify-overview">
              <ShopifySectionHeader
                eyebrow="Resumo geral"
                title="Operação consolidada"
                description="Uma leitura rápida dos principais números para apresentação e acompanhamento executivo."
              />
              <div className="shopifyKpiGrid">
                {summaryCards.map((card) => (
                  <ShopifyKpiCard
                    key={card.label}
                    hint={card.hint}
                    label={card.label}
                    tone={card.tone}
                    value={card.value}
                  />
                ))}
              </div>
            </section>

            <section className="shopifySection">
              <ShopifySectionHeader
                eyebrow="Evolução"
                title="Ritmo da operação"
                description="Gráficos simples para leitura rápida de tendência ao longo do período selecionado."
              />
              <div className="shopifyChartGrid">
                <ShopifyChartCard
                  color="#1a1718"
                  data={report.trends.daily}
                  dataKey="revenue"
                  description="Faturamento diário"
                  title="Faturamento"
                  valueFormatter={(value) => formatShopifyCurrency(value, currency)}
                />
                <ShopifyChartCard
                  color="#7b8470"
                  data={report.trends.daily}
                  dataKey="orders"
                  description="Pedidos diários"
                  title="Pedidos"
                />
                <ShopifyChartCard
                  color="#c7b299"
                  data={report.trends.daily}
                  dataKey="customers"
                  description="Clientes por período"
                  title="Clientes"
                />
                <ShopifyChartCard
                  color="#d7db6a"
                  data={report.trends.daily}
                  dataKey="average_ticket"
                  description="Ticket médio por período"
                  title="Ticket médio"
                  valueFormatter={(value) => formatShopifyCurrency(value, currency)}
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
                    {customersRefreshing ? <span className="pill">Atualizando...</span> : null}
                    <span className="pill">{formatShopifyCompactNumber(filteredCustomers.length)} clientes</span>
                  </div>
                }
              />

              {customersLoading && !customerData ? (
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

              {!customersLoading && customersError ? (
                <div className="shopifyFeedbackCard isError">
                  Não foi possível carregar a visão de clientes Shopify. {customersError}
                </div>
              ) : null}

              {!customersLoading && !customersError && customerData ? (
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

              <div>
                <ShopifySectionHeader
                  eyebrow="Apoio técnico"
                  title="Saúde da integração"
                  description="Bloco discreto para acompanhamento da entrada de webhooks e possíveis falhas."
                />
                <ShopifyWebhookStatusCard technical={report.technical} />
              </div>
            </section>
          </>
        ) : null}
      </div>
    </Shell>
  );
}
