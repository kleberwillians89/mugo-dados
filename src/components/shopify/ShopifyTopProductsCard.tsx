import type { ShopifyTopProduct } from "../../app/types";
import { formatShopifyCurrency } from "../../app/shopifyUi";

type Props = {
  products: ShopifyTopProduct[];
};

/** Ranking de produtos: nome, receita e unidades; a barra só compara com o primeiro da lista. */
export default function ShopifyTopProductsCard({ products }: Props) {
  if (!products.length) {
    return <p className="ds-emptyLine">Ainda não há produtos vendidos neste período.</p>;
  }
  const maxRevenue = Math.max(0, ...products.map((product) => Number(product.revenue || 0)));

  return (
    <ol className="ds-rankList shopifyRankList">
      {products.map((product, index) => {
        const detail = [product.variant_title, product.vendor].filter(Boolean).join(" · ");
        const width = maxRevenue > 0 ? (Number(product.revenue || 0) / maxRevenue) * 100 : 0;
        return (
          <li key={`${product.product_id || product.title}-${index}`} className="ds-rankRow">
            <span className="ds-rankName">{product.title}</span>
            <span className="ds-rankValue">{formatShopifyCurrency(product.revenue)}</span>
            <span className="ds-rankMeta">{detail ? `${detail} · ` : ""}{product.quantity_sold} un.</span>
            <span className="ds-rankBar" aria-hidden="true">
              <span style={{ width: `${Math.min(100, Math.max(0, width))}%` }} />
            </span>
          </li>
        );
      })}
    </ol>
  );
}
