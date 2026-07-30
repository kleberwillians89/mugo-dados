import type { ShopifyCustomerRow } from "../../app/types";
import { formatShopifyCompactNumber, formatShopifyCurrency } from "../../app/shopifyUi";

type Props = {
  customers: ShopifyCustomerRow[];
};

function buildStructuredInsights(customers: ShopifyCustomerRow[]): string[] {
  if (!customers.length) {
    return [
      "Assim que houver clientes no período, este bloco pode resumir concentração de receita, recorrência e ritmo de recompra.",
    ];
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
    `${formatShopifyCompactNumber(highFrequency)} clientes fizeram 2 ou mais pedidos no período, sinalizando espaço real para retenção e recompra.`,
  ];
}

export default function ShopifyExecutiveSummaryCard({ customers }: Props) {
  const insights = buildStructuredInsights(customers);

  return (
    <article className="shopifyExecutiveCard">
      <div className="shopifyListHead">
        <div>
          <div className="shopifyMiniLabel">Resumo executivo opcional</div>
          <p className="shopifyChartDescription">
            Camada estruturada pronta para evoluir depois para comentários com OpenAI, sem depender disso no core da tela.
          </p>
        </div>
        <span className="pill pillSoft">Pronto para IA</span>
      </div>

      <div className="shopifyExecutiveList">
        {insights.map((insight) => (
          <div key={insight} className="shopifyExecutiveItem">
            <span className="shopifyExecutiveDot" />
            <p>{insight}</p>
          </div>
        ))}
      </div>
    </article>
  );
}
