import type { DashboardDailyMetric } from "./DashboardDataContext";

export type ShopifyHistoryGranularity = "day" | "week" | "month";
export type ShopifyHistoryPoint = {
  key: string; label: string; start: string; end: string;
  revenue: number; orders: number; ticket: number; isPartial: boolean;
  revenueVariation: number | null; ordersVariation: number | null;
};

function civilDate(value: string) {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day, 12));
}

function iso(value: Date) { return value.toISOString().slice(0, 10); }
function addDays(value: string, days: number) { const date = civilDate(value); date.setUTCDate(date.getUTCDate() + days); return iso(date); }
function monthEnd(value: string) { const date = civilDate(value); return iso(new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0, 12))); }
function variation(current: number, previous: number) { return previous ? ((current - previous) / Math.abs(previous)) * 100 : null; }

function bucketFor(date: string, granularity: ShopifyHistoryGranularity) {
  if (granularity === "day") return { key: date, start: date, end: date };
  const parsed = civilDate(date);
  if (granularity === "month") {
    const start = `${parsed.getUTCFullYear()}-${String(parsed.getUTCMonth() + 1).padStart(2, "0")}-01`;
    return { key: start.slice(0, 7), start, end: monthEnd(start) };
  }
  const mondayOffset = (parsed.getUTCDay() + 6) % 7;
  const start = addDays(date, -mondayOffset);
  return { key: start, start, end: addDays(start, 6) };
}

export function aggregateShopifyHistory(
  rows: DashboardDailyMetric[], granularity: ShopifyHistoryGranularity,
  coverageStart: string | null, coverageEnd: string | null,
): ShopifyHistoryPoint[] {
  if (!coverageStart || !coverageEnd) return [];
  const buckets = new Map<string, { start: string; end: string; revenue: number; orders: number }>();
  rows.filter((row) => row.metric_date >= coverageStart && row.metric_date <= coverageEnd &&
    (row.shopify_net_revenue != null || row.shopify_orders != null)).forEach((row) => {
    const bucket = bucketFor(row.metric_date, granularity);
    const current = buckets.get(bucket.key) || { ...bucket, revenue: 0, orders: 0 };
    current.revenue += Number(row.shopify_net_revenue || 0);
    current.orders += Number(row.shopify_orders || 0);
    buckets.set(bucket.key, current);
  });
  const points = [...buckets.entries()].sort(([left], [right]) => left.localeCompare(right)).map(([key, bucket]) => ({
    key, start: bucket.start, end: bucket.end,
    label: granularity === "month" ? civilDate(bucket.start).toLocaleDateString("pt-BR", { month: "long", year: "numeric", timeZone: "UTC" }) :
      granularity === "week" ? `${civilDate(bucket.start).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", timeZone: "UTC" })} – ${civilDate(bucket.end).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", timeZone: "UTC" })}` :
      civilDate(bucket.start).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", timeZone: "UTC" }),
    revenue: bucket.revenue, orders: bucket.orders, ticket: bucket.orders ? bucket.revenue / bucket.orders : 0,
    isPartial: coverageStart > bucket.start || coverageEnd < bucket.end,
    revenueVariation: null, ordersVariation: null,
  }));
  return points.map((point, index) => ({ ...point,
    revenueVariation: index && !point.isPartial && !points[index - 1].isPartial ? variation(point.revenue, points[index - 1].revenue) : null,
    ordersVariation: index && !point.isPartial && !points[index - 1].isPartial ? variation(point.orders, points[index - 1].orders) : null,
  }));
}
