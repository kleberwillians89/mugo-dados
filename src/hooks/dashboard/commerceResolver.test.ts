import { describe, expect, it } from "vitest";

import { resolveCommerceConnection } from "./useDashboardFbits";

describe("commerce provider resolution", () => {
  it("selects Shopify for Roove and never falls through to FBits", () => {
    const selected = resolveCommerceConnection([
      { provider: "fbits", status: "connected", metadata: {} },
      {
        provider: "shopify",
        status: "connected",
        metadata: { selected_for_reporting: true, shop_domain: "roove.myshopify.com" },
      },
    ]);
    expect(selected?.provider).toBe("shopify");
  });

  it("does not treat Google as a commerce provider", () => {
    const selected = resolveCommerceConnection([
      { provider: "ga4", status: "connected", metadata: {} },
      { provider: "google_ads", status: "connected", metadata: {} },
    ]);
    expect(selected).toBeNull();
  });

  it("does not choose the first commerce connection when selection is ambiguous", () => {
    const selected = resolveCommerceConnection([
      { provider: "shopify", status: "connected", metadata: {} },
      { provider: "fbits", status: "connected", metadata: {} },
    ]);
    expect(selected).toBeNull();
  });
});
