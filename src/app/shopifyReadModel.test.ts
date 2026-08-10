import { describe, expect, it } from "vitest";
import type { DashboardDailyMetric } from "./DashboardDataContext";
import { countUniqueShopifyCustomers } from "./shopifyReadModel";

const row = (overrides: Partial<DashboardDailyMetric>): DashboardDailyMetric => ({
  client_id: "test", metric_date: "2026-08-05", updated_at: "2026-08-10T00:00:00Z",
  shopify_net_revenue: null, shopify_gross_revenue: null, shopify_orders: null,
  shopify_paid_orders: null, shopify_customers: null, shopify_customer_keys: null,
  shopify_refunds: null, meta_spend: null, meta_attributed_revenue: null,
  meta_purchases: null, meta_impressions: null, meta_reach: null, meta_clicks: null,
  meta_link_clicks: null, meta_video_views: null, google_ads_spend: null,
  google_ads_conversion_value: null, google_ads_conversions: null,
  google_ads_impressions: null, google_ads_clicks: null, ga4_sessions: null,
  ga4_users: null, ga4_revenue: null, ga4_purchases: null, ga4_events: null,
  instagram_reach: null, instagram_impressions: null, instagram_interactions: null,
  instagram_profile_views: null, instagram_website_clicks: null, instagram_followers: null,
  ...overrides,
});

describe("Shopify period customer aggregation", () => {
  it("counts a returning customer once across different days", () => {
    const rows = [
      row({ shopify_orders: 1, shopify_customers: 1, shopify_customer_keys: ["customer:1"] }),
      row({ metric_date: "2026-08-06", shopify_orders: 1, shopify_customers: 1, shopify_customer_keys: ["customer:1"] }),
      row({ metric_date: "2026-08-07", shopify_orders: 1, shopify_customers: 1, shopify_customer_keys: ["customer:3"] }),
    ];
    expect(countUniqueShopifyCustomers(rows)).toBe(2);
  });

  it("uses legacy daily counts only until the new projection is populated", () => {
    const rows = [
      row({ shopify_orders: 1, shopify_customers: 1, shopify_customer_keys: [] }),
      row({ metric_date: "2026-08-06", shopify_orders: 1, shopify_customers: 1, shopify_customer_keys: [] }),
    ];
    expect(countUniqueShopifyCustomers(rows)).toBe(2);
  });
});
