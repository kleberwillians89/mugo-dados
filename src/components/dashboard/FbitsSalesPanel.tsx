import { useMemo, useState } from "react";
import type { FbitsOrderRow, FbitsOrdersResponse, FbitsOrdersSummaryResponse } from "../../app/types";
import { formatSelectedPeriodLabel } from "../../app/periodRange";
import MetaStateNotice from "./MetaStateNotice";

type Props = {
  data: FbitsOrdersSummaryResponse | null;
  orders?: FbitsOrdersResponse | null;
  loading: boolean;
  error: string | null;
  variant?: "full" | "compact";
};

function fmt(value: number) {
  return Number(value || 0).toLocaleString("pt-BR");
}

function fmtCurrency(value: number) {
  return Number(value || 0).toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    maximumFractionDigits: 2,
  });
}

function shortDate(value: string | null | undefined) {
  const raw = String(value || "").trim();
  if (!raw) return "-";
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw.slice(0, 10);
  return parsed.toLocaleDateString("pt-BR");
}

function orderClient(order: FbitsOrderRow) {
  return order.cliente_nome || order.cliente_email || order.cliente_id || "Cliente não identificado";
}

function orderStatus(order: FbitsOrderRow) {
  return order.situacao_pedido || (order.situacao_pedido_id ? `Status ${order.situacao_pedido_id}` : "Pedido válido");
}

function uniqueOptions(values: Array<string | number | null | undefined>) {
  return Array.from(
    new Set(
      values
        .map((value) => String(value || "").trim())
        .filter(Boolean)
    )
  ).sort((left, right) => left.localeCompare(right, "pt-BR"));
}

export default function FbitsSalesPanel({ data, orders, loading, error, variant = "full" }: Props) {
  const summary = data?.summary;
  const connected = Boolean(data?.connected);
  const noValidOrders = connected && summary && summary.pedidos <= 0;
  const detailedOrders = useMemo(() => orders?.items || [], [orders?.items]);
  const topProducts = useMemo(() => orders?.top_products || [], [orders?.top_products]);
  const topCustomers = useMemo(() => orders?.top_customers || [], [orders?.top_customers]);
  const [productFilter, setProductFilter] = useState("");
  const [customerFilter, setCustomerFilter] = useState("");
  const [paymentFilter, setPaymentFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const normalizedProductFilter = productFilter.trim().toLowerCase();
  const normalizedCustomerFilter = customerFilter.trim().toLowerCase();
  const normalizedPaymentFilter = paymentFilter.trim().toLowerCase();
  const normalizedStatusFilter = statusFilter.trim().toLowerCase();
  const productOptions = useMemo(
    () =>
      uniqueOptions([
        ...topProducts.flatMap((product) => [product.produto, product.sku]),
        ...detailedOrders.flatMap((order) =>
          (order.produtos || []).flatMap((product) => [product.produto, product.sku])
        ),
      ]),
    [detailedOrders, topProducts]
  );
  const customerOptions = useMemo(
    () =>
      uniqueOptions([
        ...topCustomers.flatMap((customer) => [customer.cliente, customer.email]),
        ...detailedOrders.flatMap((order) => [
          order.cliente_nome,
          order.cliente_email,
          order.cliente_documento,
          order.cliente_id,
        ]),
      ]),
    [detailedOrders, topCustomers]
  );
  const paymentOptions = useMemo(
    () => uniqueOptions(detailedOrders.flatMap((order) => [order.forma_pagamento, order.status_pagamento])),
    [detailedOrders]
  );
  const statusOptions = useMemo(
    () => uniqueOptions(detailedOrders.flatMap((order) => [orderStatus(order), order.situacao_pedido_id])),
    [detailedOrders]
  );
  const filteredOrders = useMemo(
    () =>
      detailedOrders.filter((order) => {
        const customerHaystack = [
          order.cliente_nome,
          order.cliente_email,
          order.cliente_documento,
          order.cliente_id,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        const productHaystack = (order.produtos || [])
          .map((product) => `${product.produto} ${product.sku || ""}`)
          .join(" ")
          .toLowerCase();
        return (
          (!normalizedCustomerFilter || customerHaystack.includes(normalizedCustomerFilter)) &&
          (!normalizedProductFilter || productHaystack.includes(normalizedProductFilter)) &&
          (!normalizedPaymentFilter ||
            `${order.forma_pagamento || ""} ${order.status_pagamento || ""}`
              .toLowerCase()
              .includes(normalizedPaymentFilter)) &&
          (!normalizedStatusFilter ||
            `${orderStatus(order)} ${order.situacao_pedido_id || ""}`
              .toLowerCase()
              .includes(normalizedStatusFilter))
        );
      }),
    [
      detailedOrders,
      normalizedCustomerFilter,
      normalizedPaymentFilter,
      normalizedProductFilter,
      normalizedStatusFilter,
    ]
  );
  const filteredProducts = useMemo(
    () =>
      topProducts.filter((product) =>
        `${product.produto} ${product.sku || ""}`.toLowerCase().includes(normalizedProductFilter)
      ),
    [normalizedProductFilter, topProducts]
  );
  const filteredCustomers = useMemo(
    () =>
      topCustomers.filter((customer) =>
        `${customer.cliente} ${customer.email || ""}`.toLowerCase().includes(normalizedCustomerFilter)
      ),
    [normalizedCustomerFilter, topCustomers]
  );
  const hasOrderDetail = Boolean(orders?.detail_available && detailedOrders.length);
  const hasCustomerMetric = Boolean(summary && summary.clientes > 0);
  const hasProductMetric = Boolean(summary && summary.produtos_vendidos > 0);
  const sourceLabel = data?.period
    ? `Fonte: FBits · ${formatSelectedPeriodLabel(data.period)}`
    : "Fonte: FBits";

  return (
    <section className={`card cardWide fbitsSalesPanel is-${variant}`}>
      <div className="sectionHeader">
        <div>
          <div className="h1">Vendas oficiais</div>
          <div className="p">Leitura oficial de vendas via FBits.</div>
        </div>
        <span className="pill">{sourceLabel}</span>
      </div>

      {loading && !data ? <div className="fbitsSalesLoading">Carregando vendas oficiais...</div> : null}

      {!loading && !connected && !error ? (
        <MetaStateNotice
          title="FBits ainda não conectada"
          description="As métricas de vendas oficiais entram aqui quando a integração estiver pronta."
          message="FBits ainda não conectada."
          tone="empty"
        />
      ) : null}

      {error && !data ? (
        <MetaStateNotice
          title="Vendas oficiais indisponíveis"
          description="O restante do dashboard continua disponível."
          message={error}
          tone="unavailable"
        />
      ) : null}

      {noValidOrders && !error ? (
        <div className="fbitsZeroState">FBits conectada, aguardando dados do período.</div>
      ) : null}

      {connected && summary ? (
        <div className="fbitsSalesGrid">
          <div className="fbitsSalesCard isPrimary">
            <span>Receita oficial</span>
            <strong>{fmtCurrency(summary.receita_oficial)}</strong>
            <small>Lista oficial da FBits no período</small>
          </div>
          <div className="fbitsSalesCard">
            <span>Pedidos</span>
            <strong>{fmt(summary.pedidos)}</strong>
            <small>Pedidos válidos no período</small>
          </div>
          <div className="fbitsSalesCard">
            <span>Ticket médio</span>
            <strong>{fmtCurrency(summary.ticket_medio)}</strong>
            <small>Receita oficial por pedido</small>
          </div>
          {variant === "full" && hasCustomerMetric ? (
            <>
              <div className="fbitsSalesCard">
                <span>Clientes</span>
                <strong>{fmt(summary.clientes)}</strong>
                <small>Clientes identificados</small>
              </div>
            </>
          ) : null}
          {variant === "full" && hasProductMetric ? (
            <>
              <div className="fbitsSalesCard">
                <span>Produtos vendidos</span>
                <strong>{fmt(summary.produtos_vendidos)}</strong>
                <small>Itens retornados pela FBits</small>
              </div>
            </>
          ) : null}
        </div>
      ) : null}

      {variant === "full" && connected && summary && (!hasCustomerMetric || !hasProductMetric) ? (
        <div className="fbitsDetailHint">Aguardando detalhe de pedidos da FBits para clientes e produtos vendidos.</div>
      ) : null}

      {variant === "full" && connected ? (
        <div className="fbitsFilters" aria-label="Filtros FBits">
          <label>
            <span>Produto</span>
            <select
              className="select"
              onChange={(event) => setProductFilter(event.target.value)}
              value={productFilter}
            >
              <option value="">Todos os produtos / SKUs</option>
              {productOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Cliente</span>
            <select
              className="select"
              onChange={(event) => setCustomerFilter(event.target.value)}
              value={customerFilter}
            >
              <option value="">Todos os clientes</option>
              {customerOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Pagamento</span>
            <select
              className="select"
              onChange={(event) => setPaymentFilter(event.target.value)}
              value={paymentFilter}
            >
              <option value="">Todos os pagamentos</option>
              {paymentOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Status</span>
            <select
              className="select"
              onChange={(event) => setStatusFilter(event.target.value)}
              value={statusFilter}
            >
              <option value="">Todos os status</option>
              {statusOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
        </div>
      ) : null}

      {variant === "full" && connected ? (
        <div className="fbitsDetailGrid">
          <article className="fbitsDetailCard">
            <div className="fbitsDetailHead">
              <div>
                <div className="h1">Pedidos FBits</div>
                <div className="p">Pedidos oficiais com cliente, pagamento e itens do período.</div>
              </div>
            </div>
            {hasOrderDetail ? (
              <div className="tableWrap fbitsTableWrap">
                <table className="table fbitsTable">
                  <thead>
                    <tr>
                      <th>Data</th>
                      <th>Pedido</th>
                      <th>Cliente</th>
                      <th>Status</th>
                      <th>Pagamento</th>
                      <th>Status pagamento</th>
                      <th>Valor</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredOrders.slice(0, 12).map((order) => (
                      <tr key={order.pedido_id}>
                        <td>{shortDate(order.data_pagamento || order.data)}</td>
                        <td>{order.pedido_codigo || order.pedido_id}</td>
                        <td>{orderClient(order)}</td>
                        <td>{orderStatus(order)}</td>
                        <td>{order.forma_pagamento || "-"}</td>
                        <td>{order.status_pagamento || "-"}</td>
                        <td>{fmtCurrency(order.receita_oficial)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="fbitsDetailEmpty">Detalhamento de pedidos ainda não disponível pela FBits para este período.</div>
            )}
            {filteredOrders.some((order) => (order.produtos || []).length) ? (
              <div className="tableWrap fbitsTableWrap fbitsItemsWrap">
                <table className="table fbitsTable">
                  <thead>
                    <tr>
                      <th>Produto</th>
                      <th>SKU</th>
                      <th>Pedido</th>
                      <th>Qtd.</th>
                      <th>Unitário</th>
                      <th>Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredOrders
                      .flatMap((order) => (order.produtos || []).map((product) => ({ order, product })))
                      .slice(0, 18)
                      .map(({ order, product }) => (
                        <tr key={`${order.pedido_id}-${product.product_id || product.sku || product.produto}`}>
                          <td>
                            <div className="fbitsProductCell">
                              {product.imagem ? <img alt="" src={product.imagem} /> : <span />}
                              <div className="cellTitle">{product.produto}</div>
                            </div>
                          </td>
                          <td>{product.sku || "-"}</td>
                          <td>{order.pedido_codigo || order.pedido_id}</td>
                          <td>{fmt(product.quantidade)}</td>
                          <td>{fmtCurrency(product.valor_unitario || 0)}</td>
                          <td>{fmtCurrency(product.receita)}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </article>

          <article className="fbitsDetailCard">
            <div className="fbitsDetailHead">
              <div>
                <div className="h1">Produtos vendidos</div>
                <div className="p">Ranking de itens quando o pedido detalhado traz produtos.</div>
              </div>
            </div>
            {filteredProducts.length ? (
              <div className="tableWrap fbitsTableWrap">
                <table className="table fbitsTable">
                  <thead>
                    <tr>
                      <th>Produto</th>
                      <th>SKU</th>
                      <th>Quantidade</th>
                      <th>Receita</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredProducts.slice(0, 10).map((product) => (
                      <tr key={product.product_id || product.produto}>
                        <td>
                          <div className="fbitsProductCell">
                            {product.imagem ? <img alt="" src={product.imagem} /> : <span />}
                            <div className="cellTitle">{product.produto}</div>
                          </div>
                        </td>
                        <td>{product.sku || "-"}</td>
                        <td>{fmt(product.quantidade)}</td>
                        <td>{fmtCurrency(product.receita)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="fbitsDetailEmpty">Detalhamento de produtos ainda não disponível pela FBits para este período.</div>
            )}
          </article>

          <article className="fbitsDetailCard">
            <div className="fbitsDetailHead">
              <div>
                <div className="h1">Top clientes</div>
                <div className="p">Clientes identificados nos pedidos oficiais do período.</div>
              </div>
            </div>
            {filteredCustomers.length ? (
              <div className="tableWrap fbitsTableWrap">
                <table className="table fbitsTable">
                  <thead>
                    <tr>
                      <th>Cliente</th>
                      <th>Pedidos</th>
                      <th>Receita</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredCustomers.slice(0, 10).map((customer) => (
                      <tr key={customer.customer_id || customer.email || customer.cliente}>
                        <td>
                          <div className="cellTitle">{customer.cliente}</div>
                          {customer.email ? <div className="cellMuted">{customer.email}</div> : null}
                        </td>
                        <td>{fmt(customer.pedidos)}</td>
                        <td>{fmtCurrency(customer.receita)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="fbitsDetailEmpty">Clientes detalhados aparecem quando a FBits retornar identificação no pedido.</div>
            )}
          </article>
        </div>
      ) : null}
    </section>
  );
}
