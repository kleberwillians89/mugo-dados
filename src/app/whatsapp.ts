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
  has_campaign?: boolean;
  last_message_at: string | null; service_window_expires_at: string | null;
  contact: { name: string | null; phone_masked: string; first_seen_at: string | null };
  origin: { bucket: WaOriginKey; label: string; ad_headline: string | null; entry_code: string | null; at: string | null };
  purchase: { orders: number; revenue: number; last_order: string | null; last_order_at: string | null } | null;
  last_message: { direction: string; at: string; text: string } | null;
  insight?: WaInsight | null;
  /** Atendente de IA (número ligado no MUGOVERSO): resposta pendente de aprovação e motivo da passagem para a equipe. */
  ai_suggestion?: WaAiSuggestion | null;
  ai_handoff_reason?: string | null;
};
export type WaAiProduct = { handle: string; title: string; price: number; url: string; image: string | null };
export type WaAiSuggestion = { reply: string; buttons: string[]; products: WaAiProduct[]; handoff: boolean; handoff_reason: string; created_at: string };
/** Mensagem da conversa; by_ai/payload só nos números ligados no MUGOVERSO. */
export type WaMessage = CrmMessage & { by_ai?: boolean; payload?: { campaign_id?: string; buttons?: string[]; products?: WaAiProduct[]; cards?: boolean } | null };
export type WhatsAppInbox = {
  ok: true; status: "available" | "no_brand_number" | "crm_unavailable"; reason?: CrmUnavailable["reason"];
  conversations: WaConversation[]; channel_provider?: "mugozap_crm" | null; reply_enabled?: boolean;
};

const base = (path = "") => clientClientPath(`/whatsapp${path}`);

export function getWhatsAppInsights(start: string, end: string) {
  return http<WhatsAppInsights>(base(`?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`));
}
export function getWhatsAppInbox() {
  return http<WhatsAppInbox>(base("/inbox"));
}
export function getWhatsAppMessages(conversationId: string) {
  return http<({ available: true; messages: WaMessage[] }) | CrmUnavailable>(
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
  id: string; waba_id: string; phone_number_id: string; meta_app_id?: string | null; display_phone_number: string | null; verified_name: string | null;
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
export function connectWhatsAppNumber(input: { waba_id: string; phone_number_id: string; access_token: string; meta_app_id?: string | null }) {
  return http<{ ok: true; number: WaNumber }>(base("/numbers"), { method: "POST", body: JSON.stringify(input), timeoutMs: 60_000 });
}
export function disconnectWhatsAppNumber(id: string) {
  return http<{ ok: true }>(base(`/numbers/${encodeURIComponent(id)}`), { method: "DELETE" });
}

/** Consultas/registro Roove: Meta status real, sem revelar token nem persistir PIN. */
export type WaMetaRegistration = {
  ok: true; phone_number_id: string; display_phone_number?: string;
  status?: string; code_verification_status?: string;
  registered?: boolean; can_register?: boolean; requires_confirmation?: boolean;
  registered_by_this_request: boolean; already_connected?: boolean;
  registration_requested?: boolean; note?: string;
};
export function getRooveMetaRegistrationStatus(numberId: string) {
  return http<WaMetaRegistration>(
    base(`/numbers/${encodeURIComponent(numberId)}/meta-registration`), { timeoutMs: 30_000 });
}
export function registerRooveMetaNumber(numberId: string, pin: string, confirmed: boolean) {
  return http<WaMetaRegistration>(
    base(`/numbers/${encodeURIComponent(numberId)}/meta-register`),
    { method: "POST", body: JSON.stringify({ pin, confirmed }), timeoutMs: 45_000 });
}

/** Verificação da posse do número secundário Roove. Requer confirmação na interface. */
export function requestRooveMetaCode(numberId: string, method: "SMS" | "VOICE", confirmed: boolean) {
  return http<{ ok: true; requested: boolean; method: string }>(
    base(`/numbers/${encodeURIComponent(numberId)}/meta-request-code`),
    { method: "POST", body: JSON.stringify({ method, confirmed }), timeoutMs: 45_000 });
}
export function verifyRooveMetaCode(numberId: string, code: string, confirmed: boolean) {
  return http<{ ok: true; verified: boolean; already_verified?: boolean }>(
    base(`/numbers/${encodeURIComponent(numberId)}/meta-verify-code`),
    { method: "POST", body: JSON.stringify({ code, confirmed }), timeoutMs: 45_000 });
}

/** Each tenant manages only its own WhatsApp Business Account message templates. */
export type WaTemplate = {
  name: string; language: string; status: string; category: string; body: string; variables: number;
  /** Topo do modelo: IMAGE/VIDEO/DOCUMENT pedem o arquivo no disparo. */
  header?: "TEXT" | "IMAGE" | "VIDEO" | "DOCUMENT" | null; header_variables?: number;
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
export const replyWhatsApp = (conversationId: string, text: string, requestId: string) =>
  http<{ status: string; at?: string; ai_paused_minutes?: number }>(base(`/conversations/${encodeURIComponent(conversationId)}/reply`),
    { method: "POST", body: JSON.stringify({ text, request_id: requestId }), timeoutMs: 60_000 });

/** Planejamento de disparos em massa: APIs não têm envio real. */
export type WaCampaignAudience = {
  ok: true; total_contacts: number; consent_claimed_count: number; consent_verified_count: number;
  sendable_count: number; truncated: boolean; reason: string; opted_out_count?: number;
};
export type WaCampaignDraft = {
  id: string; name: string; template_name: string; language: string;
  status: "draft" | "queued" | "sending" | "sent" | "partial" | "failed"; simulated_count: number; created_at: string;
  scheduled_at?: string | null; header_media_url?: string | null;
  audience_provider?: string;
  sent_count?: number; failed_count?: number; skipped_count?: number; recipients_count?: number;
  started_at?: string | null; finished_at?: string | null; last_error?: string | null;
};
/** Envia (ou retoma) a campanha para todos os contatos com telefone da origem, menos quem pediu para sair. */
export function sendWhatsAppCampaign(draftId: string, scheduledAt?: string | null, excludePreviousTemplateRecipients = true) {
  return http<{ ok: true; status: "queued"; scheduled_at: string | null; recipients_count: number }>(
    base(`/campaigns/drafts/${encodeURIComponent(draftId)}/send`),
    { method: "POST", body: JSON.stringify({ scheduled_at: scheduledAt || null, exclude_previous_template_recipients: excludePreviousTemplateRecipients }) });
}
export function testWhatsAppCampaign(input: {
  phone: string; template_name: string; language: string; header_media_url?: string;
}) {
  return http<{ ok: true; status: "accepted" }>(base("/campaigns/test"), {
    method: "POST", body: JSON.stringify(input),
  });
}
export function cancelWhatsAppCampaign(draftId: string) {
  return http<{ ok: true; status: "draft" }>(base(`/campaigns/drafts/${encodeURIComponent(draftId)}/cancel`), { method: "POST" });
}
export type WaCampaignReport = {
  sent: number; failed: number; skipped: number; replied: number; reply_rate: number;
  buyers: number; orders: number; revenue: number; sales_available: boolean; window: string;
};
export function getWhatsAppCampaignReport(draftId: string) {
  return http<{ ok: true } & WaCampaignReport>(base(`/campaigns/drafts/${encodeURIComponent(draftId)}/report`), { timeoutMs: 60_000 });
}
export function previewWhatsAppCampaignAudience(provider: "all" | "shopify" | "fbits" | "whatsapp" | "capture" | "planilha" = "all") {
  return http<WaCampaignAudience>(base(`/campaigns/audience-preview?provider=${encodeURIComponent(provider)}`));
}
export function listWhatsAppCampaignDrafts() {
  return http<{ ok: true; drafts: WaCampaignDraft[]; sending_enabled: boolean }>(base("/campaigns/drafts"));
}
export function preflightWhatsAppCampaignTemplate(template_name: string, language: string) {
  return http<{
    ok: true; provider: string; template_found: boolean; template_approved: boolean;
    template_status: string | null; can_send: boolean; reason: string; messages_sent: 0;
  }>(base("/campaigns/template-preflight"), {
    method: "POST", body: JSON.stringify({template_name, language}),
  });
}
export function createWhatsAppCampaignDraft(input: {
  name: string; template_name: string; language: string;
  provider: "all" | "shopify" | "fbits" | "whatsapp" | "capture" | "planilha";
  header_media_url?: string | null;
  /** Só na planilha: os contatos escolhidos à mão (vazio = todos da planilha). */
  selected_contacts?: string[];
}) {
  return http<{ ok: true; sending_enabled: boolean; draft: WaCampaignDraft; messages_sent: 0 }>(
    base("/campaigns/drafts"), {method: "POST", body: JSON.stringify(input)},
  );
}

/** Imports the selected tenant's previously synchronized contacts; never sends messages. */
export type WaContactImportResult = {
  ok: true; provider: string; source_records: number; contacts_synchronized: number;
  eligible_for_marketing: number; note: string;
};
export type WaContactImportStatus = {
  ok: true; total: number; truncated: boolean; by_provider: Record<string, number>;
  last_synced_at: string | null;
};
export function getWhatsAppContactImportStatus() {
  return http<WaContactImportStatus>("/api/relationship/contacts/status");
}
export function importExistingCommerceContacts() {
  return http<WaContactImportResult>("/api/relationship/contacts/sync", {
    method: "POST", timeoutMs: 90_000,
  });
}
/** Leads de uma planilha (Excel ou CSV) viram a origem "Planilha importada" do Disparo em massa. Não envia nada. */
export type WaSheetImportResult = { ok: true; provider: "planilha"; rows: number; contacts_imported: number; invalid: number;
  columns: { telefone: string; nome: string | null; email: string | null }; replaced: boolean };
export async function importContactsSheet(file: File, options: { replace: boolean; consent: boolean }) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return http<WaSheetImportResult>("/api/relationship/contacts/import-sheet", {
    method: "POST", timeoutMs: 120_000,
    body: JSON.stringify({ filename: file.name, content_base64: btoa(binary), replace: options.replace, consent_confirmed: options.consent }),
  });
}
export type WaSheetContact = { id: string; name: string; phone: string };
export function listSheetContacts(q = "") {
  return http<{ ok: true; total: number; matches: number; contacts: WaSheetContact[]; truncated: boolean }>(
    `/api/relationship/contacts/sheet?limit=500&q=${encodeURIComponent(q)}`);
}
export function importExistingWhatsAppConversations(days: number = 365) {
  return http<WaContactImportResult>(`/api/relationship/contacts/sync-whatsapp?days=${encodeURIComponent(String(days))}`, {
    method: "POST", timeoutMs: 90_000,
  });
}


/** Atendente de IA do WhatsApp (números ligados direto no MUGOVERSO). */
export type WaAiMode = "off" | "suggest" | "auto";
export type WaAiSettings = {
  mode: WaAiMode; instructions: string; welcome_buttons: string[]; featured_products: string[]; offers: string;
  catalog_id: string | null; product_cards: boolean; human_pause_minutes: number; updated_at?: string | null;
  /** Quem chega por anúncio (Click-to-WhatsApp) recebe este link uma vez. */
  ad_group_link?: string | null; ad_group_message?: string;
  /** Claude da própria marca: a chave nunca volta, só o final dela. */
  claude_model?: WaClaudeModel; has_claude_key?: boolean; claude_key_hint?: string | null; claude_key_source?: "tela" | "render" | null;
  /** Como as peças aparecem: carrossel com foto e botão (padrão), catálogo da Meta ou links. */
  product_style?: "carrossel" | "catalogo" | "links"; product_button?: string;
};
export type WaClaudeModel = "claude-haiku-5-5" | "claude-sonnet-5-5" | "claude-opus-5-5";
export const WA_CLAUDE_MODELS: { id: WaClaudeModel; label: string }[] = [
  { id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5 (recomendado)" },
  { id: "claude-haiku-5-5", label: "Claude Haiku 5.5 (mais rápido e barato)" },
  { id: "claude-opus-5-5", label: "Claude Opus 5.5 (mais caprichado, mais caro)" },
];
export type WaAiCatalogStatus = {
  shopify: { ok: boolean; domain?: string; products?: number; available?: number; error?: string };
  meta: { ok: boolean; catalog_id?: string; items?: number; matched_products?: number };
  featured: { name: string; found: { title: string; available: boolean }[] }[];
};
export type WaAiSimulation = {
  reply: string; buttons: string[]; products: WaAiProduct[]; handoff: boolean; handoff_reason: string;
  insight: WaInsight | null; catalog_loaded: boolean;
};
export const getWhatsAppAiSettings = () => http<{ settings: WaAiSettings }>(base("/ai-settings"));
export const saveWhatsAppAiSettings = (changes: Partial<WaAiSettings>) =>
  http<{ settings: WaAiSettings }>(base("/ai-settings"), { method: "PUT", body: JSON.stringify(changes) });
export const saveWhatsAppAiClaudeKey = (api_key: string, model: WaClaudeModel) =>
  http<{ settings: WaAiSettings }>(base("/ai-settings/claude-key"), { method: "PUT", body: JSON.stringify({ api_key, model }), timeoutMs: 45_000 });
export const removeWhatsAppAiClaudeKey = () =>
  http<{ settings: WaAiSettings }>(base("/ai-settings/claude-key"), { method: "DELETE" });
export const getWhatsAppAiCatalog = () => http<WaAiCatalogStatus>(base("/ai-settings/catalog"), { timeoutMs: 90_000 });
export const simulateWhatsAppAi = (conversation: { role: "cliente" | "marca"; text: string }[]) =>
  http<WaAiSimulation>(base("/ai-settings/simulate"), { method: "POST", body: JSON.stringify({ conversation }), timeoutMs: 90_000 });
export const sendWhatsAppAiSuggestion = (conversationId: string, text?: string) =>
  http<{ status: string; messages: number }>(base(`/conversations/${encodeURIComponent(conversationId)}/ai-suggestion/send`),
    { method: "POST", body: JSON.stringify(text === undefined ? {} : { text }), timeoutMs: 90_000 });
export const discardWhatsAppAiSuggestion = (conversationId: string) =>
  http<{ status: string }>(base(`/conversations/${encodeURIComponent(conversationId)}/ai-suggestion`), { method: "DELETE" });
export const resumeWhatsAppAi = (conversationId: string) =>
  http<{ status: string }>(base(`/conversations/${encodeURIComponent(conversationId)}/ai/resume`), { method: "POST", body: "{}" });
