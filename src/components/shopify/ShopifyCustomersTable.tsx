import type { ShopifyCustomerRow } from "../../app/types";
import {
  formatShopifyCurrency,
  formatShopifyLongDate,
  getShopifyCustomerStatusLabel,
  getShopifyStatusTone,
} from "../../app/shopifyUi";

type Props = {
  customers: ShopifyCustomerRow[];
};

export default function ShopifyCustomersTable({ customers }: Props) {
  if (!customers.length) {
    return <div className="shopifyEmptyCard">Nenhum cliente encontrado com os filtros atuais.</div>;
  }

  return (
    <div className="shopifyTableWrap">
      <table className="shopifyTable">
        <thead>
          <tr>
            <th>Nome</th>
            <th>Email</th>
            <th>Total de pedidos</th>
            <th>Valor total comprado</th>
            <th>Ticket médio</th>
            <th>Última compra</th>
            <th>Primeira compra</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {customers.map((customer) => {
            const tone = getShopifyStatusTone(customer.status);
            return (
              <tr key={customer.customer_key}>
                <td>
                  <div className="shopifyTableTitle">{customer.name}</div>
                  <div className="shopifyTableSubtle">
                    {customer.shopify_customer_id ? `Shopify ID ${customer.shopify_customer_id}` : "Cliente por e-mail"}
                  </div>
                </td>
                <td>{customer.email || "Sem e-mail"}</td>
                <td>{customer.total_orders}</td>
                <td>{formatShopifyCurrency(customer.total_spent)}</td>
                <td>{formatShopifyCurrency(customer.average_ticket)}</td>
                <td>{formatShopifyLongDate(customer.last_purchase_at)}</td>
                <td>{formatShopifyLongDate(customer.first_purchase_at)}</td>
                <td>
                  <span className={`shopifyStatusPill is-${tone}`.trim()}>
                    {getShopifyCustomerStatusLabel(customer.status)}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
