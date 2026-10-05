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
import { formatFreshness } from "../app/dataRefresh";
import "../styles/customers.css";

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
  if (customer.email) return customer.email;
  if (customer.phone) return phoneDisplay(customer.phone);
  return "—";
}

function phoneDisplay(phone: string | null): string {
  const digits = String(phone || "").replace(/\D+/g, "");
  if (!digits) return "";
  const local = digits.length > 11 ? digits.slice(-11) : digits;
  if (local.length === 11) return `(${local.slice(0, 2)}) ${local.slice(2, 7)}-${local.slice(7)}`;
  if (local.length === 10) return `(${local.slice(0, 2)}) ${local.slice(2, 6)}-${local.slice(6)}`;
  return local;
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

export default function Customers() {
  const clientId = getActiveClientId();
  const base = readDashboardCache<CachedBase>(baseCacheKey(clientId));
  const cached = base?.payload.client_id === clientId ? base : null;
  const [storedData, setData] = useState<CustomerListResponse | null>(cached?.payload || null);
  const data = storedData?.client_id === clientId ? storedData : null;
  const [refreshedAt, setRefreshedAt] = useState<string | null>(cached?.refreshedAt || null);
  const [tick, setTick] = useState(() => Date.now());
  // Último estado válido já na tela: só mostra "carregando" quando não há
  // nada persistido para mostrar.
  const [loading, setLoading] = useState(!cached);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [applied, setApplied] = useState("");
  const [page, setPage] = useState(1);
  const [storedSelected, setSelected] = useState<CustomerDetailResponse | null>(null);
  const selected = storedSelected?.client_id === clientId ? storedSelected : null;
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
      if (signal.aborted || request !== generation.current || getActiveClientId() !== clientId) return;
      if (
        payload.client_id !== clientId || !Array.isArray(payload.customers) ||
        typeof payload.connected !== "boolean" ||
        payload.customers.some((customer) => customer.client_id !== clientId)
      ) {
        throw new Error("A resposta de clientes não corresponde à empresa selecionada.");
      }
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
      if (signal.aborted || request !== generation.current || getActiveClientId() !== clientId) return;
      setError(
        reason instanceof Error && reason.message
          ? reason.message
          : "A base de clientes não pôde ser carregada agora.",
      );
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [clientId]);

  // Só move os rótulos relativos; não busca nada.
  useEffect(() => {
    const timer = setInterval(() => setTick(Date.now()), 15_000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(applied, page, controller.signal);
    return () => {
      generation.current += 1;
      controller.abort();
    };
  }, [applied, page, load]);

  const detailGeneration = useRef(0);
  const invalidateDetail = useCallback(() => { detailGeneration.current++; }, []);
  useEffect(() => invalidateDetail, [clientId, invalidateDetail]);

  const openCustomer = useCallback((customerId: string) => {
    if (getActiveClientId() !== clientId) return;
    const request = ++detailGeneration.current;
    setDetailLoading(true);
    setDetailError("");
    setSelected(null);
    getCustomerDetail(customerId)
      .then((payload) => {
        if (request !== detailGeneration.current || getActiveClientId() !== clientId) return;
        if (payload.client_id !== clientId || payload.customer.client_id !== clientId) throw new Error("O cliente não corresponde à empresa selecionada.");
        setSelected(payload);
      })
      .catch((reason: unknown) => {
        if (request !== detailGeneration.current || getActiveClientId() !== clientId) return;
        setDetailError(
          reason instanceof Error && reason.message
            ? reason.message
            : "Este cliente não pôde ser aberto agora.",
        );
      })
      .finally(() => { if (request === detailGeneration.current) setDetailLoading(false); });
  }, [clientId]);

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
      />
      <p className="customerLead">Conheça e acompanhe a base de clientes desta empresa.</p>

      {error ? <DataNotice tone="negative" role="alert" title="Não foi possível carregar os clientes.">{error}</DataNotice> : null}

      {loading && !data ? <p className="customerEmpty" role="status">Carregando clientes...</p> : null}

      {!error && !loading && !connected ? (
        <DataNotice tone="neutral" title="Nenhum cliente encontrado para esta empresa.">
          Nenhuma loja conectada. Conecte a loja desta empresa para ver a base de clientes aqui.
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
              Os dados persistidos ainda não têm nome, e-mail ou telefone dos clientes.
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
            {!loading && !error && customers.length === 0 ? (
              <p className="customerEmpty">
                {applied
                  ? "Nenhum cliente encontrado para esta busca."
                  : "Nenhum cliente encontrado para esta empresa."}
              </p>
            ) : (
              <table className="customerTable">
                <thead>
                  <tr>
                    <th scope="col">Cliente</th>
                    <th scope="col">Pedidos</th>
                    <th scope="col">Receita</th>
                    <th scope="col">Ticket médio</th>
                    <th scope="col">Última compra</th>
                    <th scope="col">Origem</th>
                  </tr>
                </thead>
                <tbody>
                  {customers.map((customer) => {
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
                          <span className={`customerContactLine${customer.email ? "" : " is-muted"}`} aria-label="E-mail">{customer.email || "—"}</span>
                          <span className={`customerContactLine${customer.phone ? "" : " is-muted"}`} aria-label="Telefone">{phoneDisplay(customer.phone) || "—"}</span>
                        </td>
                        <td>{count(customer.orders_count)}</td>
                        <td>{money(customer.total_revenue)}</td>
                        <td>{money(customer.average_ticket)}</td>
                        <td>{day(customer.last_order_at)}</td>
                        <td>
                          <span className={`customerOrigin is-${customer.provider}`}>
                            {customer.provider_label}
                          </span>
                          <small className="customerRowNote">{STATUS_LABEL[customer.status]}</small>
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
          invalidateDetail();
          setDetailLoading(false);
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
                <dt>Nome</dt><dd>{selected.customer.name || "Não informado"}</dd>
              </div>
              <div>
                <dt>Email</dt><dd>{selected.customer.email || "Não informado"}</dd>
              </div>
              <div>
                <dt>Telefone</dt><dd>{phoneDisplay(selected.customer.phone) || "Não informado"}</dd>
              </div>
              <div>
                <dt>Origem</dt>
                <dd>{selected.customer.provider_label}</dd>
              </div>
              <div>
                <dt>Receita</dt>
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
