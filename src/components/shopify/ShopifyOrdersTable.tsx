import type { ShopifyRecentOrder } from "../../app/types";
import {
  formatShopifyCurrency,
  formatShopifyShortDate,
  getShopifyFinancialStatusLabel,
  getShopifyStatusTone,
} from "../../app/shopifyUi";

type Props = {
  orders: ShopifyRecentOrder[];
};

const TONE_CLASS: Record<string, string> = { positive: " is-positive", warning: " is-warning", danger: " is-negative", neutral: "" };

export default function ShopifyOrdersTable({ orders }: Props) {
  if (!orders.length) {
    return <p className="ds-emptyLine">Ainda não há pedidos da Shopify neste período.</p>;
  }

  return (
    <div className="ds-tableWrap">
      <table className="ds-table">
        <thead>
          <tr>
            <th scope="col">Pedido</th>
            <th scope="col">Cliente</th>
            <th scope="col">Status financeiro</th>
            <th scope="col" className="is-number">Valor total</th>
            <th scope="col">Data</th>
            <th scope="col" className="is-number">Itens</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => {
            const statusTone = getShopifyStatusTone(order.financial_status);
            return (
              <tr key={order.shopify_order_id}>
                <td className="is-primary">
                  {order.name || `#${order.order_number || order.shopify_order_id}`}
                  <span className="ds-tableSub">ID {order.shopify_order_id}</span>
                </td>
                <td>
                  {order.customer_name}
                  <span className="ds-tableSub">{order.customer_email || "Sem e-mail"}</span>
                </td>
                <td>
                  <span className="ds-statusInline">
                    <span className={`ds-statusDot${TONE_CLASS[statusTone] || ""}`} aria-hidden="true" />
                    {getShopifyFinancialStatusLabel(order.financial_status)}
                  </span>
                </td>
                <td className="is-number">{formatShopifyCurrency(order.total_price, order.currency)}</td>
                <td>{formatShopifyShortDate(order.created_at_shopify)}</td>
                <td className="is-number">{order.items_count}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
