import type { DashboardDailyMetric } from "./DashboardDataContext";

export function countUniqueShopifyCustomers(rows: DashboardDailyMetric[]): number {
  const commerceRows = rows.filter((row) =>
    row.shopify_orders != null || row.shopify_net_revenue != null
  );
  const projectionComplete = commerceRows.every((row) =>
    Number(row.shopify_orders || 0) === 0 || (row.shopify_customer_keys?.length || 0) > 0
  );
  if (!projectionComplete) {
    return commerceRows.reduce((sum, row) => sum + Number(row.shopify_customers || 0), 0);
  }
  return new Set(commerceRows.flatMap((row) => row.shopify_customer_keys || [])).size;
}
