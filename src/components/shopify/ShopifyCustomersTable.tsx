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

const TONE_CLASS: Record<string, string> = { positive: " is-positive", warning: " is-warning", danger: " is-negative", neutral: "" };

export default function ShopifyCustomersTable({ customers }: Props) {
  if (!customers.length) {
    return <p className="ds-emptyLine">Nenhum cliente encontrado com os filtros atuais.</p>;
  }

  return (
    <div className="ds-tableWrap">
      <table className="ds-table">
        <thead>
          <tr>
            <th scope="col">Nome</th>
            <th scope="col">Email</th>
            <th scope="col" className="is-number">Pedidos</th>
            <th scope="col" className="is-number">Valor comprado</th>
            <th scope="col" className="is-number">Ticket médio</th>
            <th scope="col">Última compra</th>
            <th scope="col">Primeira compra</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {customers.map((customer) => {
            const tone = getShopifyStatusTone(customer.status);
            return (
              <tr key={customer.customer_key}>
                <td className="is-primary">
                  {customer.name}
                  <span className="ds-tableSub">
                    {customer.shopify_customer_id ? `Shopify ID ${customer.shopify_customer_id}` : "Cliente por e-mail"}
                  </span>
                </td>
                <td>{customer.email || "Sem e-mail"}</td>
                <td className="is-number">{customer.total_orders}</td>
                <td className="is-number">{formatShopifyCurrency(customer.total_spent)}</td>
                <td className="is-number">{formatShopifyCurrency(customer.average_ticket)}</td>
                <td>{formatShopifyLongDate(customer.last_purchase_at)}</td>
                <td>{formatShopifyLongDate(customer.first_purchase_at)}</td>
                <td>
                  <span className="ds-statusInline">
                    <span className={`ds-statusDot${TONE_CLASS[tone] || ""}`} aria-hidden="true" />
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
