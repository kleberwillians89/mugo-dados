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
  advanced?: number; top_objection?: WaObjectionRow | null;
};
export type WaLinkRow = { code: string; conversations: number; sales: number; revenue: number };
export type WaStageKey = "novo" | "interessada" | "negociando" | "comprou" | "recorrente" | "perdida" | "suporte";
export type WaStageRow = { key: WaStageKey; label: string; count: number; share: number };
export type WaObjectionRow = { key: string; label: string; count: number };
/** Ficha que a IA de atendimento do CRM da marca mantém de cada conversa. */
export type WaInsight = { stage: WaStageKey; interests: string[]; objections: string[]; next_step: string | null; summary: string | null; updated_at: string | null };
export const STAGE_LABELS: Record<WaStageKey, string> = {
  novo: "Lead novo", interessada: "Interessada", negociando: "Negociando", comprou: "Comprou",
  recorrente: "Recorrente", perdida: "Perdida", suporte: "Pós-venda",
};
export const OBJECTION_LABELS: Record<string, string> = {
  preco: "Preço", frete: "Frete", prazo: "Prazo de entrega", confianca: "Confiança na loja",
  pagamento: "Forma de pagamento", estoque: "Disponibilidade", produto: "Dúvida sobre o produto", outro: "Outro motivo",
};

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
  stages?: WaStageRow[];
  interpreted_conversations?: number;
  objections?: WaObjectionRow[];
};

export type WaConversation = {
  id: string; status: string | null; attendance_mode: string | null; unread_count: number | null;
  last_message_at: string | null; service_window_expires_at: string | null;
  contact: { name: string | null; phone_masked: string; first_seen_at: string | null };
  origin: { bucket: WaOriginKey; label: string; ad_headline: string | null; entry_code: string | null; at: string | null };
  purchase: { orders: number; revenue: number; last_order: string | null; last_order_at: string | null } | null;
  last_message: { direction: string; at: string; text: string } | null;
  insight?: WaInsight | null;
};
export type WhatsAppInbox = {
  ok: true; status: "available" | "no_brand_number" | "crm_unavailable"; reason?: CrmUnavailable["reason"];
  conversations: WaConversation[]; channel_provider?: "mugozap_crm" | null;
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
  ad: "#1e3f5a", instagram: "#4f86a8", link: "#c79830", site: "#e2c887", google: "#7a8b99", direct: "#c9cfd4",
};

/** Números ligados direto no MUGOVERSO (app da Mugô na Meta). Só a agência vê e cadastra. */
export type WaNumber = {
  id: string; waba_id: string; phone_number_id: string; display_phone_number: string | null; verified_name: string | null;
  status: "active" | "disconnected"; subscribed_at: string | null; created_at: string | null;
};
export type WaConnectionStatus = {
  ok: true; client_id: string; provider: "native" | "crm_bridge" | "mugozap_crm" | "not_connected";
  connected: boolean; crm_status_unavailable: boolean;
  native_connected: boolean; crm_bridge_configured: boolean;
  meta_credentials_saved: boolean; number_count: number; numbers: WaNumber[];
  requires_meta_credentials: boolean; notice: string;
};
export function getWhatsAppConnectionStatus() {
  return http<WaConnectionStatus>(base("/connection-status"));
}
export function listWhatsAppNumbers() {
  return http<{ ok: true; numbers: WaNumber[] }>(base("/numbers"));
}
export function connectWhatsAppNumber(input: { waba_id: string; phone_number_id: string; access_token: string }) {
  return http<{ ok: true; number: WaNumber }>(base("/numbers"), { method: "POST", body: JSON.stringify(input), timeoutMs: 60_000 });
}
export function disconnectWhatsAppNumber(id: string) {
  return http<{ ok: true }>(base(`/numbers/${encodeURIComponent(id)}`), { method: "DELETE" });
}

/** Each tenant manages only its own WhatsApp Business Account message templates. */
export type WaTemplate = {
  name: string; language: string; status: string; category: string; body: string; variables: number;
};
export type WaTemplateInput = {
  number_id?: string | null; name: string; category: "MARKETING" | "UTILITY";
  language: "pt_BR" | "en_US" | "es_ES"; body: string; footer?: string; examples: string[];
};
export function listWhatsAppTemplates(numberId?: string | null) {
  const suffix = numberId ? `?number_id=${encodeURIComponent(numberId)}` : "";
  return http<{ ok: true; templates: WaTemplate[] }>(base(`/templates${suffix}`));
}
export function submitWhatsAppTemplate(input: WaTemplateInput) {
  return http<{ ok: true; template: WaTemplate & { id: string; waba_id: string } }>(base("/templates"), {
    method: "POST", body: JSON.stringify(input), timeoutMs: 60_000,
  });
}

/** Direct do Instagram da marca (mesma tela do WhatsApp). */
export type IgThreadSummary = {
  sender_id: string; username: string | null; follows: boolean | null; last_at: string; last_text: string;
  last_direction: "in" | "out"; last_by_app: boolean; waiting: boolean; review: boolean; window_open: boolean; messages: number;
};
export type IgInbox = { threads: IgThreadSummary[]; counts: { conversations: number; waiting: number; review: number } };
export type IgMessage = { id: string; direction: "in" | "out"; text: string | null; by_app: boolean; status: string; reply_kind: "oi" | "ia" | null; at: string; note: string | null };
export type IgThread = { sender_id: string; username: string | null; follows: boolean | null; window_open: boolean; messages: IgMessage[] };
export const getInstagramInbox = () => http<IgInbox>(base("/instagram"));
export const getInstagramThread = (senderId: string) => http<IgThread>(base(`/instagram/${encodeURIComponent(senderId)}`));
export const replyInstagram = (senderId: string, text: string) =>
  http<{ status: string; at: string }>(base(`/instagram/${encodeURIComponent(senderId)}/reply`), { method: "POST", body: JSON.stringify({ text }), timeoutMs: 60_000 });

/** Equipe responde a conversa pelo número da marca (CRM da marca ou número ligado no MUGOVERSO). */
export const replyWhatsApp = (conversationId: string, text: string) =>
  http<{ status: string; at?: string; ai_paused_minutes?: number }>(base(`/conversations/${encodeURIComponent(conversationId)}/reply`),
    { method: "POST", body: JSON.stringify({ text }), timeoutMs: 60_000 });

/** Planejamento de disparos em massa: APIs não têm envio real. */
export type WaCampaignAudience = {
  ok: true; total_contacts: number; consent_verified_count: number;
  sendable_count: number; truncated: boolean; reason: string;
};
export type WaCampaignDraft = {
  id: string; name: string; template_name: string; language: string;
  status: "draft"; simulated_count: number; created_at: string;
  audience_provider?: string;
};
export function previewWhatsAppCampaignAudience(provider: "all" | "shopify" | "fbits" | "whatsapp" = "all") {
  return http<WaCampaignAudience>(base(`/campaigns/audience-preview?provider=${encodeURIComponent(provider)}`));
}
export function listWhatsAppCampaignDrafts() {
  return http<{ ok: true; drafts: WaCampaignDraft[]; sending_enabled: false }>(base("/campaigns/drafts"));
}
export function preflightWhatsAppCampaignTemplate(template_name: string, language: string) {
  return http<{
    ok: true; provider: string; template_found: boolean; template_approved: boolean;
    template_status: string | null; can_send: false; reason: string; messages_sent: 0;
  }>(base("/campaigns/template-preflight"), {
    method: "POST", body: JSON.stringify({template_name, language}),
  });
}
export function createWhatsAppCampaignDraft(input: {
  name: string; template_name: string; language: string;
  provider: "all" | "shopify" | "fbits" | "whatsapp";
}) {
  return http<{ ok: true; sending_enabled: false; draft: WaCampaignDraft; messages_sent: 0 }>(
    base("/campaigns/drafts"), {method: "POST", body: JSON.stringify(input)},
  );
}
