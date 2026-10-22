import { http, clientClientPath } from "./api";

export type SalesOriginRow = {
  orders: number;
  revenue: number;
  average_ticket: number | null;
  share_of_revenue: number | null;
};
export type SalesOriginChannel = SalesOriginRow & { channel: string; label: string };
export type SalesOriginCampaign = SalesOriginRow & {
  channel: string; channel_label: string; source: string | null; medium: string | null; campaign: string | null;
};
export type SalesByOrigin = {
  ok: true;
  status: "available" | "partial" | "not_connected" | "migration_pending";
  provider: "shopify" | "fbits" | null;
  period: { start: string; end: string };
  attribution_model: string;
  attribution_model_label: string;
  truncated?: boolean;
  notes?: string[];
  totals: null | {
    orders: number; revenue: number; average_ticket: number | null;
    orders_with_origin: number; orders_with_utm: number;
    origin_coverage_percent: number | null; utm_coverage_percent: number | null;
  };
  channels: SalesOriginChannel[];
  campaigns: SalesOriginCampaign[];
};

export async function getSalesByOrigin(start?: string, end?: string): Promise<SalesByOrigin> {
  const query = new URLSearchParams();
  if (start) query.set("start", start);
  if (end) query.set("end", end);
  return http(clientClientPath(`/sales-by-origin${query.size ? `?${query}` : ""}`));
}
