import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const source = readFileSync(new URL("./Shopify.tsx", import.meta.url), "utf8");

describe("Shopify page consistency contract", () => {
  it("loads customer and order details with the exact global period", () => {
    expect(source).toContain("const selectedPeriod = { start: period.start, end: period.end, days: periodDays }");
    expect(source).toContain("getShopifyReport(selectedPeriod)");
    expect(source).toContain("getShopifyCustomers(selectedPeriod)");
  });

  it("uses recognized net revenue in every commercial revenue card", () => {
    expect(source).not.toContain("formatShopifyCurrency(summary?.revenue_total");
    expect(source.match(/formatShopifyCurrency\(summary\?\.net_revenue/g)?.length).toBeGreaterThanOrEqual(2);
  });

  it("does not manufacture empty customers or recent orders", () => {
    expect(source).not.toContain("summary: { total_customers: 0");
    expect(source).not.toContain("recent_orders: []");
  });
});
