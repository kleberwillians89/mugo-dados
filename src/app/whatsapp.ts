import { http, clientClientPath } from "./api";
import type { CrmMessage, CrmUnavailable } from "./crm";

/** WhatsApp da marca: origem das conversas → vendas, e a caixa de entrada do número da própria marca. */
export type WaOriginKey = "ad" | "instagram" | "link" | "site" | "google" | "direct";

export type WaOriginRow = { key: WaOriginKey; label: string; conversations: number; sales: number; orders: number; revenue: number; share: number };
export type WaVerdict = { code: "scale" | "keep" | "weak" | "talk_no_sale"; label: string };
export type WaAdRow = {
  ad_id: string; ad_name: string | null; headline: string | null; campaign_name: string | null;
  spend: number | null; conversations: number; sales: number; orders: number; revenue: number;
  cost_per_conversation: number | null; cost_per_sale: number | null; roas: number | null; verdict: WaVerdict | null;
};
export type WaLinkRow = { code: string; conversations: number; sales: number; revenue: number };

export type WhatsAppInsights = {
  ok: true;
  status: "available" | "partial" | "no_brand_number" | "crm_unavailable";
  reason?: CrmUnavailable["reason"];
  provider?: string | null;
  period: { start: string; end: string };
  attribution_label: string;
  window_days: number;
  truncated?: boolean;
  notes?: string[];
  totals?: {
    conversations: number; converted_conversations: number; conversion_rate: number | null; orders: number; revenue: number;
    store_revenue: number; share_of_store_revenue: number | null; ad_spend: number | null;
    cost_per_conversation: number | null; cost_per_sale: number | null; ads_roas: number | null;
  };
  origins?: WaOriginRow[];
  ads?: WaAdRow[];
  links?: WaLinkRow[];
  alerts?: { ad_id: string; text: string }[];
};

export type WaConversation = {
  id: string; status: string | null; attendance_mode: string | null; unread_count: number | null;
  last_message_at: string | null; service_window_expires_at: string | null;
  contact: { name: string | null; phone_masked: string; first_seen_at: string | null };
  origin: { bucket: WaOriginKey; label: string; ad_headline: string | null; entry_code: string | null; at: string | null };
  purchase: { orders: number; revenue: number; last_order: string | null; last_order_at: string | null } | null;
  last_message: { direction: string; at: string; text: string } | null;
};
export type WhatsAppInbox = {
  ok: true; status: "available" | "no_brand_number" | "crm_unavailable"; reason?: CrmUnavailable["reason"];
  conversations: WaConversation[];
};

const base = (path = "") => clientClientPath(`/whatsapp${path}`);

export function getWhatsAppInsights(start: string, end: string) {
  return http<WhatsAppInsights>(base(`?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`));
}
export function getWhatsAppInbox() {
  return http<WhatsAppInbox>(base("/inbox"));
}
export function getWhatsAppMessages(conversationId: string) {
  return http<({ available: true; messages: CrmMessage[] }) | CrmUnavailable>(
    base(`/conversations/${encodeURIComponent(conversationId)}/messages`),
  );
}

/** O CRM grava "in"/"out"; versões antigas da ponte usavam "inbound"/"outbound". */
export const isOutbound = (direction: string | null | undefined) => direction === "out" || direction === "outbound";

export const ORIGIN_COLORS: Record<WaOriginKey, string> = {
  ad: "#004f6e", instagram: "#4f86a8", link: "#c79830", site: "#e2c887", google: "#7a8b99", direct: "#c9cfd4",
};
