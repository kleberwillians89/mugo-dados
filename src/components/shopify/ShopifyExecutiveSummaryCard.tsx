import type { ShopifyCustomerRow } from "../../app/types";
import { formatShopifyCompactNumber, formatShopifyCurrency } from "../../app/shopifyUi";

type Props = {
  customers: ShopifyCustomerRow[];
};

/** Fatos sobre a base filtrada — derivados só dos clientes listados, sem interpretação. */
function buildStructuredInsights(customers: ShopifyCustomerRow[]): string[] {
  if (!customers.length) {
    return ["Sem clientes no filtro atual."];
  }

  const totalRevenue = customers.reduce((sum, customer) => sum + customer.total_spent, 0);
  const recurring = customers.filter((customer) => customer.status === "recurring");
  const topCustomer = customers[0];
  const topShare = totalRevenue > 0 ? Math.round((topCustomer.total_spent / totalRevenue) * 100) : 0;
  const recurringShare = customers.length > 0 ? Math.round((recurring.length / customers.length) * 100) : 0;
  const highFrequency = customers.filter((customer) => customer.total_orders >= 2).length;

  return [
    `${topCustomer.name} lidera o período com ${formatShopifyCurrency(topCustomer.total_spent)} e ${topShare}% da receita observada.`,
    `${formatShopifyCompactNumber(recurring.length)} clientes recorrentes representam ${recurringShare}% da base ativa deste recorte.`,
    `${formatShopifyCompactNumber(highFrequency)} clientes fizeram 2 ou mais pedidos no período.`,
  ];
}

export default function ShopifyExecutiveSummaryCard({ customers }: Props) {
  const insights = buildStructuredInsights(customers);

  return (
    <div className="ds-observations">
      <h3 className="ds-subTitle">Na base filtrada</h3>
      <ul>
        {insights.map((insight) => (
          <li key={insight}>{insight}</li>
        ))}
      </ul>
    </div>
  );
}
