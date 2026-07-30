import type { ShopifyTopProduct } from "../../app/types";
import { formatShopifyCurrency } from "../../app/shopifyUi";

type Props = {
  products: ShopifyTopProduct[];
};

export default function ShopifyTopProductsCard({ products }: Props) {
  return (
    <article className="shopifyListCard">
      <div className="shopifyListHead">
        <div>
          <div className="shopifyMiniLabel">Produtos mais vendidos</div>
          <p className="shopifyChartDescription">Os itens que mais puxaram volume e receita no período.</p>
        </div>
      </div>

      {products.length ? (
        <div className="shopifyListRows">
          {products.map((product, index) => (
            <div key={`${product.product_id || product.title}-${index}`} className="shopifyListRow">
              <div className="shopifyListRank">{String(index + 1).padStart(2, "0")}</div>
              <div className="shopifyListBody">
                <div className="shopifyTableTitle">{product.title}</div>
                <div className="shopifyTableSubtle">
                  {[product.variant_title, product.vendor].filter(Boolean).join(" • ") || "Produto Shopify"}
                </div>
              </div>
              <div className="shopifyListMetric">
                <span>{product.quantity_sold} un.</span>
                <strong>{formatShopifyCurrency(product.revenue)}</strong>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="shopifyEmptyCard">Ainda não há produtos vendidos neste período.</div>
      )}
    </article>
  );
}
