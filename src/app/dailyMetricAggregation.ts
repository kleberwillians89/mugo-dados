import type { DashboardDailyMetric } from "./DashboardDataContext";

export type MetaAggregate = { spend: number | null; purchases: number | null; attributedRevenue: number | null };

export function aggregateMetaDays(rows: DashboardDailyMetric[]): MetaAggregate {
  const available = rows.filter((row) => row.meta_spend != null || row.meta_purchases != null || row.meta_attributed_revenue != null);
  if (!available.length) return { spend: null, purchases: null, attributedRevenue: null };
  const sum = (key: "meta_spend" | "meta_purchases" | "meta_attributed_revenue") =>
    Math.round(available.reduce((total, row) => total + Number(row[key] || 0), 0) * 1_000_000) / 1_000_000;
  return {
    spend: sum("meta_spend"),
    purchases: sum("meta_purchases"),
    attributedRevenue: sum("meta_attributed_revenue"),
  };
}
