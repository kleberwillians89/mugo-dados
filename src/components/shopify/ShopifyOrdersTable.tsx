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

export default function ShopifyOrdersTable({ orders }: Props) {
  if (!orders.length) {
    return <div className="shopifyEmptyCard">Ainda não há pedidos da Shopify neste período.</div>;
  }

  return (
    <div className="shopifyTableWrap">
      <table className="shopifyTable">
        <thead>
          <tr>
            <th>Pedido</th>
            <th>Cliente</th>
            <th>Status financeiro</th>
            <th>Valor total</th>
            <th>Data</th>
            <th>Itens</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => {
            const statusTone = getShopifyStatusTone(order.financial_status);
            return (
              <tr key={order.shopify_order_id}>
                <td>
                  <div className="shopifyTableTitle">{order.name || `#${order.order_number || order.shopify_order_id}`}</div>
                  <div className="shopifyTableSubtle">ID {order.shopify_order_id}</div>
                </td>
                <td>
                  <div className="shopifyTableTitle">{order.customer_name}</div>
                  <div className="shopifyTableSubtle">{order.customer_email || "Sem e-mail"}</div>
                </td>
                <td>
                  <span className={`shopifyStatusPill is-${statusTone}`.trim()}>
                    {getShopifyFinancialStatusLabel(order.financial_status)}
                  </span>
                </td>
                <td>{formatShopifyCurrency(order.total_price, order.currency)}</td>
                <td>{formatShopifyShortDate(order.created_at_shopify)}</td>
                <td>{order.items_count}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
