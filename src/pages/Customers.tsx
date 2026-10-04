import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { getCustomerDetail, getCustomers } from "../app/api";
import { formatDateTimeSaoPaulo } from "../app/dataFormat";
import type {
  CustomerDetailResponse,
  CustomerListResponse,
  CustomerSummary,
} from "../app/intelligenceTypes";
import DataNotice from "../components/data/DataNotice";
import PageHeader from "../components/data/PageHeader";
import Drawer from "../components/Drawer";
import Shell from "../components/Shell";
import { buildDashboardCacheKey, readDashboardCache, writeDashboardCache } from "../hooks/dashboard/cache";
import { cooldownFrom, cooldownHint, formatFreshness } from "../app/dataRefresh";
import "../styles/customers.css";

type Props = {
  onLogout: () => void | Promise<void>;
};

const PAGE_SIZE = 25;

type CachedBase = { payload: CustomerListResponse; refreshedAt: string };

/** Última base válida do tenant, para a tela abrir com conteúdo em vez de
 * skeleton. Só a primeira página sem busca: é o que a abertura mostra. */
function baseCacheKey(clientId: string): string {
  return buildDashboardCacheKey("customers-base", { clientId });
}

function money(value: number | null | undefined): string {
  if (value == null) return "—";
  return value.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    maximumFractionDigits: 2,
  });
}

function count(value: number | null | undefined): string {
  return value == null ? "—" : value.toLocaleString("pt-BR");
}

function day(value: string | null): string {
  if (!value) return "—";
  const formatted = formatDateTimeSaoPaulo(value);
  return formatted ? formatted.split(" ")[0] : "—";
}

/** Nome quando existe; nunca um nome inventado. */
function displayName(customer: CustomerSummary): string {
  const name = String(customer.name || "").trim();
  if (name) return name;
  if (customer.external_id) return `Cliente ${customer.external_id}`;
  if (customer.email) return customer.email;
  return "Cliente sem identificação";
}

function phoneDisplay(phone: string | null): string {
  const digits = String(phone || "").replace(/\D+/g, "");
  if (!digits) return "";
  const local = digits.length > 11 ? digits.slice(-11) : digits;
  if (local.length === 11) return `(${local.slice(0, 2)}) ${local.slice(2, 7)}-${local.slice(7)}`;
  if (local.length === 10) return `(${local.slice(0, 2)}) ${local.slice(2, 6)}-${local.slice(6)}`;
  return local;
}

function contactLines(customer: CustomerSummary): string[] {
  return [customer.email || "", phoneDisplay(customer.phone)].filter(Boolean);
}

const STATUS_LABEL: Record<CustomerSummary["status"], string> = {
  recurring: "Recorrente",
  single: "Primeira compra",
  no_purchase: "Sem compra registrada",
};

function SummaryCard({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <article className="customerCard">
      <span className="customerCardLabel">{label}</span>
      <strong className="customerCardValue">{value}</strong>
      {note ? <small className="customerCardNote">{note}</small> : null}
    </article>
  );
}

export default function Customers({ onLogout }: Props) {
  const clientId = getActiveClientId();
  const cached = readDashboardCache<CachedBase>(baseCacheKey(clientId));
  const [data, setData] = useState<CustomerListResponse | null>(cached?.payload || null);
  const [refreshedAt, setRefreshedAt] = useState<string | null>(cached?.refreshedAt || null);
  const [lastRefreshAt, setLastRefreshAt] = useState<number | null>(null);
  const [tick, setTick] = useState(() => Date.now());
  // Último estado válido já na tela: só mostra "carregando" quando não há
  // nada persistido para mostrar.
  const [loading, setLoading] = useState(!cached);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [applied, setApplied] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<CustomerDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const company = getActiveClientName();

  // A busca espera o usuário parar de digitar: uma requisição por termo, não
  // uma por tecla.
  useEffect(() => {
    const timer = setTimeout(() => {
      setApplied(search.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  // Uma leitura por termo/página. `generation` descarta a resposta de uma
  // requisição que já foi substituída por outra mais nova.
  const generation = useRef(0);
  const load = useCallback(async (term: string, wanted: number, signal: AbortSignal) => {
    const request = ++generation.current;
    setLoading(true);
    setError("");
    try {
      const payload = await getCustomers(
        { search: term, page: wanted, pageSize: PAGE_SIZE },
        { signal },
      );
      if (request !== generation.current) return;
      setData(payload);
      const now = new Date().toISOString();
      setRefreshedAt(now);
      // Só a primeira página sem busca representa a base da empresa.
      if (!term && wanted === 1) {
        writeDashboardCache<CachedBase>(
          baseCacheKey(clientId), { payload, refreshedAt: now }, 600_000,
        );
      }
    } catch (reason: unknown) {
      if (signal.aborted || request !== generation.current) return;
      setError(
        reason instanceof Error && reason.message
          ? reason.message
          : "A base de clientes não pôde ser carregada agora.",
      );
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [clientId]);

  // Só move os rótulos relativos e libera o cooldown; não busca nada.
  useEffect(() => {
    const timer = setInterval(() => setTick(Date.now()), 15_000);
    return () => clearInterval(timer);
  }, []);

  const cooldown = cooldownFrom(lastRefreshAt, tick);
  const refreshData = useCallback(() => {
    if (!cooldown.ready || loading) return;
    setLastRefreshAt(Date.now());
    const controller = new AbortController();
    void load(applied, page, controller.signal);
  }, [applied, cooldown.ready, load, loading, page]);

  useEffect(() => {
    const controller = new AbortController();
    void load(applied, page, controller.signal);
    return () => {
      generation.current += 1;
      controller.abort();
    };
  }, [applied, page, load]);

  const openCustomer = useCallback((customerId: string) => {
    setDetailLoading(true);
    setDetailError("");
    setSelected(null);
    getCustomerDetail(customerId)
      .then(setSelected)
      .catch((reason: unknown) => {
        setDetailError(
          reason instanceof Error && reason.message
            ? reason.message
            : "Este cliente não pôde ser aberto agora.",
        );
      })
      .finally(() => setDetailLoading(false));
  }, []);

  const totals = data?.totals;
  const pages = useMemo(
    () => Math.max(1, Math.ceil((data?.total || 0) / (data?.page_size || PAGE_SIZE))),
    [data?.total, data?.page_size],
  );
  const customers = data?.customers || [];
  const freshnessLabel = formatFreshness(refreshedAt, tick);
  const connected = Boolean(data?.connected);

  return (
    <Shell
      title="Clientes"
      variant="editorial"
      right={
        <button type="button" className="ds-utilityAction" onClick={() => void onLogout()}>
          Sair
        </button>
      }
    >
      <PageHeader
        company={company}
        title="Clientes"
        dateline={
          <>
            {connected && data?.provider_label ? (
              <span>Base de clientes de {data.provider_label}</span>
            ) : null}
            {freshnessLabel ? <span> · Dados atualizados {freshnessLabel}</span> : null}
          </>
        }
        controls={
          <button
            type="button"
            className="ds-button"
            onClick={refreshData}
            disabled={loading || !cooldown.ready}
            data-testid="customers-refresh"
            title={cooldownHint(cooldown) || undefined}
          >
            {loading ? "Atualizando..." : "Atualizar dados"}
          </button>
        }
        controlsNote={cooldownHint(cooldown)}
      />
      <p className="customerLead">Conheça e acompanhe a base de clientes desta empresa.</p>

      {error ? <DataNotice tone="negative" role="alert" title="Não foi possível carregar">{error}</DataNotice> : null}

      {!error && !loading && !connected ? (
        <DataNotice tone="neutral" title="Nenhuma loja conectada">
          Conecte a loja desta empresa para ver a base de clientes aqui.
        </DataNotice>
      ) : null}

      {connected ? (
        <>
          <section className="customerCards" aria-label="Resumo da base">
            <SummaryCard label="Total de clientes" value={count(totals?.customers)} />
            <SummaryCard
              label="Clientes recorrentes"
              value={count(totals?.recurring_customers)}
              note="Com mais de uma compra"
            />
            <SummaryCard label="Receita da base" value={money(totals?.total_revenue)} />
            <SummaryCard label="Ticket médio" value={money(totals?.average_ticket ?? null)} />
          </section>

          {data && !data.contact_details_available ? (
            <DataNotice tone="neutral" title="Contatos não disponíveis nesta loja">
              A loja desta empresa não compartilha nome, e-mail e telefone dos clientes.
              O histórico de compras é real e aparece abaixo.
            </DataNotice>
          ) : null}

          {data?.truncated ? (
            <DataNotice tone="warning" title="Base muito grande">
              Estamos mostrando os pedidos mais recentes. Alguns clientes antigos podem não
              aparecer nas somas.
            </DataNotice>
          ) : null}

          <section className="customerSearch">
            <label className="customerSearchLabel" htmlFor="customer-search">
              Buscar cliente
            </label>
            <input
              id="customer-search"
              className="customerSearchInput"
              type="search"
              placeholder="Nome, e-mail ou telefone"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              autoComplete="off"
            />
          </section>

          <section className="customerTableWrap" aria-label="Clientes">
            {loading ? (
              <p className="customerEmpty">Carregando clientes…</p>
            ) : customers.length === 0 ? (
              <p className="customerEmpty">
                {applied
                  ? "Nenhum cliente encontrado para esta busca."
                  : "Ainda não há clientes com compras registradas."}
              </p>
            ) : (
              <table className="customerTable">
                <thead>
                  <tr>
                    <th scope="col">Cliente</th>
                    <th scope="col">Contato</th>
                    <th scope="col">Pedidos</th>
                    <th scope="col">Receita</th>
                    <th scope="col">Ticket médio</th>
                    <th scope="col">Última compra</th>
                    <th scope="col">Origem</th>
                  </tr>
                </thead>
                <tbody>
                  {customers.map((customer) => {
                    const contacts = contactLines(customer);
                    return (
                      <tr key={customer.id}>
                        <td>
                          <button
                            type="button"
                            className="customerNameButton"
                            onClick={() => openCustomer(customer.id)}
                          >
                            {displayName(customer)}
                          </button>
                          <small className="customerRowNote">{STATUS_LABEL[customer.status]}</small>
                        </td>
                        <td>
                          {contacts.length ? (
                            contacts.map((line) => (
                              <span key={line} className="customerContactLine">
                                {line}
                              </span>
                            ))
                          ) : (
                            <span className="customerContactLine is-muted">Não informado</span>
                          )}
                        </td>
                        <td>{count(customer.orders_count)}</td>
                        <td>{money(customer.total_revenue)}</td>
                        <td>{money(customer.average_ticket)}</td>
                        <td>{day(customer.last_order_at)}</td>
                        <td>
                          <span className={`customerOrigin is-${customer.provider}`}>
                            {customer.provider_label}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </section>

          {pages > 1 ? (
            <nav className="customerPager" aria-label="Páginas de clientes">
              <button
                type="button"
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                disabled={page <= 1 || loading}
              >
                Anterior
              </button>
              <span>
                Página {page} de {pages}
              </span>
              <button
                type="button"
                onClick={() => setPage((current) => Math.min(pages, current + 1))}
                disabled={page >= pages || loading}
              >
                Próxima
              </button>
            </nav>
          ) : null}
        </>
      ) : null}

      <Drawer
        open={Boolean(selected) || detailLoading || Boolean(detailError)}
        title={selected ? displayName(selected.customer) : "Cliente"}
        description={selected ? STATUS_LABEL[selected.customer.status] : undefined}
        width="lg"
        onClose={() => {
          setSelected(null);
          setDetailError("");
        }}
      >
        {detailLoading ? <p className="customerEmpty">Carregando cliente…</p> : null}
        {detailError ? (
          <DataNotice tone="negative" role="alert" title="Não foi possível abrir">{detailError}</DataNotice>
        ) : null}
        {selected ? (
          <>
            <dl className="customerDetailGrid">
              <div>
                <dt>Contato</dt>
                <dd>
                  {contactLines(selected.customer).length
                    ? contactLines(selected.customer).join(" · ")
                    : "Não informado"}
                </dd>
              </div>
              <div>
                <dt>Origem</dt>
                <dd>{selected.customer.provider_label}</dd>
              </div>
              <div>
                <dt>Total comprado</dt>
                <dd>{money(selected.customer.total_revenue)}</dd>
              </div>
              <div>
                <dt>Pedidos</dt>
                <dd>{count(selected.customer.orders_count)}</dd>
              </div>
              <div>
                <dt>Ticket médio</dt>
                <dd>{money(selected.customer.average_ticket)}</dd>
              </div>
              <div>
                <dt>Primeira compra</dt>
                <dd>{day(selected.customer.first_order_at)}</dd>
              </div>
              <div>
                <dt>Última compra</dt>
                <dd>{day(selected.customer.last_order_at)}</dd>
              </div>
            </dl>

            <h3 className="customerDetailHeading">Histórico de pedidos</h3>
            {selected.orders.length === 0 ? (
              <p className="customerEmpty">Nenhum pedido registrado.</p>
            ) : (
              <table className="customerTable customerOrdersTable">
                <thead>
                  <tr>
                    <th scope="col">Data</th>
                    <th scope="col">Pedido</th>
                    <th scope="col">Valor</th>
                    <th scope="col">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {selected.orders.map((order) => (
                    <tr key={order.order_id} className={order.counts_as_revenue ? "" : "is-excluded"}>
                      <td>{day(order.happened_at)}</td>
                      <td>{order.reference}</td>
                      <td>{money(order.value)}</td>
                      <td>{order.status || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        ) : null}
      </Drawer>
    </Shell>
  );
}
