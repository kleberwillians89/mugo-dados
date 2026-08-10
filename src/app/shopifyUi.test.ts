import { describe, expect, it } from "vitest";
import { formatShopifyLongDate, formatShopifyShortDate } from "./shopifyUi";

describe("Shopify civil DATE formatting", () => {
  it("never shifts YYYY-MM-DD to the previous day", () => {
    expect(formatShopifyLongDate("2026-08-01")).toBe("01/08/2026");
    expect(formatShopifyShortDate("2026-08-01").toLowerCase()).toContain("01");
  });
});
