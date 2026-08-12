import { describe, expect, it } from "vitest";
import { aggregateShopifyHistory } from "./shopifyHistory";
import type { DashboardDailyMetric } from "./DashboardDataContext";

const row = (metric_date: string, revenue: number, orders: number) => ({ metric_date, shopify_net_revenue: revenue, shopify_orders: orders } as DashboardDailyMetric);

describe("aggregateShopifyHistory", () => {
  it("agrega dia, semana segunda-domingo e mês com ticket ponderado", () => {
    const rows = [row("2026-08-03", 100, 1), row("2026-08-04", 900, 3), row("2026-08-10", 500, 1)];
    expect(aggregateShopifyHistory(rows, "day", "2026-08-03", "2026-08-10")).toHaveLength(3);
    const weeks = aggregateShopifyHistory(rows, "week", "2026-08-03", "2026-08-10");
    expect(weeks[0]).toMatchObject({ start: "2026-08-03", end: "2026-08-09", revenue: 1000, orders: 4, ticket: 250 });
    const months = aggregateShopifyHistory(rows, "month", "2026-08-03", "2026-08-10");
    expect(months[0]).toMatchObject({ revenue: 1500, orders: 5, ticket: 300, isPartial: true });
  });

  it("não cria meses sem cobertura e mantém zero real dentro da cobertura", () => {
    expect(aggregateShopifyHistory([row("2026-02-01", 0, 0)], "month", "2026-02-01", "2026-02-28"))
      .toMatchObject([{ key: "2026-02", revenue: 0, orders: 0, isPartial: false }]);
    expect(aggregateShopifyHistory([], "month", "2026-02-01", "2026-02-28")).toEqual([]);
  });
});
