import { http } from "./api";

/** E-mail marketing (Resend) e recuperação de carrinho. O backend confere papel e empresa em cada chamada. */

export type BlockType = "logo" | "titulo" | "texto" | "imagem" | "botao" | "produtos" | "divisor" | "espaco";
export type EmailBlock = { type: BlockType; text?: string; url?: string; href?: string; alt?: string; label?: string; align?: "left" | "center" };
export type EmailDesign = { blocks: EmailBlock[] };
export type Segment = "consentimento" | "todos" | "compraram" | "sem_compra" | "recompra";
export type Audience = { segment: Segment; days: number; only_consent: boolean };
export type CampaignStatus = "rascunho" | "agendada" | "enviando" | "enviada" | "falhou" | "cancelada";

export type EmailSettings = {
  from_name: string | null; from_email: string | null; reply_to: string | null; brand_color: string | null;
  logo_url: string | null; footer_text: string | null; store_url: string | null; updated_at?: string | null;
};
export type SenderStatus = {
  configured: boolean; send_enabled: boolean; from_email: string | null; domain: string | null;
  domain_status: string | null; ready: boolean;
};
export type CampaignStats = {
  total: number; queued: number; sent: number; delivered: number; bounced: number; spam: number; failed: number; simulated: number;
  opened: number; clicked: number; open_rate: number | null; click_rate: number | null; audience?: number;
};
export type CampaignSummary = {
  id: string; name: string; subject: string; status: CampaignStatus; scheduled_at: string | null; started_at: string | null;
  finished_at: string | null; stats: Partial<CampaignStats>; created_at: string; updated_at: string;
};
export type Campaign = CampaignSummary & { preheader: string; design: EmailDesign; custom_html: string | null; audience: Audience };
export type AudiencePreview = {
  provider: string | null; count: number; base: number; with_consent: number; blocked: number; consent_known: boolean; audience: Audience;
};

export type CartStep = { channel: "email" | "whatsapp"; delay_minutes: number };
export type CartSettings = {
  enabled: boolean; steps: CartStep[]; email_subject: string; email_design: EmailDesign; email_custom_html: string | null; email_consent: "todos" | "consentimento";
  whatsapp_number_id: string | null; whatsapp_template: string | null; whatsapp_language: string;
  whatsapp_variables: ("nome" | "produto" | "valor" | "link")[]; whatsapp_consent: "consentimento" | "consentimento_ou_conversa";
  attribution_days: number; webhooks_registered_at: string | null;
};
export type CartStatus = "aberto" | "recuperado" | "comprou_sem_contato" | "expirado" | "sem_contato" | "pausado";
export type CartRow = {
  checkout_id: string; created_at: string | null; value: number; items: number; first_item: string | null; status: CartStatus;
  steps_done: number; recovered_value: number | null;
  last_touch: { channel: "email" | "whatsapp"; status: "enviado" | "simulado" | "pulado" | "falhou"; reason: string | null; at: string } | null;
};
export type CartOverview = {
  days: number; provider: string | null; settings: CartSettings; recent: CartRow[]; simulated: { email: boolean; whatsapp: boolean };
  summary: {
    carts: number; abandoned_value: number; contacted: number; recovered: number; recovered_value: number; recovery_rate: number | null;
    bought_without_contact: number; open: number; by_channel: Record<string, Record<string, number>>;
  };
};
export type HtmlReport = {
  bytes: number; too_big: boolean; gmail_clip: boolean; full_document: boolean; variables: string[]; has_unsubscribe: boolean; removed_unsafe: boolean;
};
export type EmailPreviewResult = { subject: string; html: string; report?: HtmlReport | null };
export type WaTemplate = { name: string; language: string; status: string; category: string; body: string; variables: number };
export type WaNumber = { id: string; display_phone_number: string | null; verified_name: string | null; status: string };

const json = (body: unknown) => ({ body: JSON.stringify(body), headers: { "Content-Type": "application/json" } });

export const getEmailSettings = () => http<{ settings: EmailSettings; status: SenderStatus }>("/api/email/settings", { timeoutMs: 30_000 });
export const saveEmailSettings = (patch: Partial<EmailSettings>) =>
  http<{ settings: EmailSettings; status: SenderStatus }>("/api/email/settings", { method: "PUT", ...json(patch) });
export const previewAudience = (audience: Audience) =>
  http<AudiencePreview>("/api/email/audience", { method: "POST", ...json({ audience }), timeoutMs: 60_000 });
export const previewEmail = (campaign: Partial<Campaign>) =>
  http<EmailPreviewResult>("/api/email/preview", { method: "POST", ...json(campaign) });

export const listCampaigns = () => http<{ campaigns: CampaignSummary[] }>("/api/email/campaigns");
export const getCampaign = (id: string) =>
  http<{ campaign: Campaign; stats: CampaignStats | null }>(`/api/email/campaigns/${encodeURIComponent(id)}`);
export const createCampaign = (body: Partial<Campaign> = {}) =>
  http<{ campaign: Campaign }>("/api/email/campaigns", { method: "POST", ...json(body) });
export const updateCampaign = (id: string, body: Partial<Campaign>) =>
  http<{ campaign: Campaign }>(`/api/email/campaigns/${encodeURIComponent(id)}`, { method: "PUT", ...json(body) });
export const deleteCampaign = (id: string) => http<{ ok: boolean }>(`/api/email/campaigns/${encodeURIComponent(id)}`, { method: "DELETE" });
export const sendTestEmail = (id: string, to: string) =>
  http<{ status: string }>(`/api/email/campaigns/${encodeURIComponent(id)}/test`, { method: "POST", ...json({ to }) });
export const scheduleCampaign = (id: string, at: string | null) =>
  http<{ campaign: Campaign }>(`/api/email/campaigns/${encodeURIComponent(id)}/schedule`, { method: "POST", ...json({ at }) });
export const cancelCampaign = (id: string) =>
  http<{ campaign: Campaign }>(`/api/email/campaigns/${encodeURIComponent(id)}/cancel`, { method: "POST" });

export const getCartRecovery = (days = 30) => http<CartOverview>(`/api/cart-recovery?days=${days}`, { timeoutMs: 60_000 });
export const saveCartSettings = (patch: Partial<CartSettings>) =>
  http<{ settings: CartSettings }>("/api/cart-recovery/settings", { method: "PUT", ...json(patch) });
export const registerCartWebhooks = () =>
  http<{ registered: string[]; existing: string[]; failed: { topic: string; status: number }[] }>("/api/cart-recovery/webhooks", { method: "POST" });
export const getWaTemplates = () => http<{ numbers: WaNumber[]; templates: WaTemplate[] }>("/api/cart-recovery/whatsapp-templates");
export const previewCartEmail = (email_design: EmailDesign, email_subject: string, email_custom_html?: string | null) =>
  http<EmailPreviewResult>("/api/cart-recovery/preview", { method: "POST", ...json({ email_design, email_subject, email_custom_html }) });

export const SEGMENT_LABEL: Record<Segment, string> = {
  consentimento: "Quem aceitou receber e-mails",
  todos: "Todos os clientes com e-mail",
  compraram: "Compraram nos últimos dias",
  sem_compra: "Sem comprar há um tempo",
  recompra: "Compraram 2 vezes ou mais",
};
export const STATUS_LABEL: Record<CampaignStatus, string> = {
  rascunho: "Rascunho", agendada: "Agendada", enviando: "Enviando", enviada: "Enviada", falhou: "Falhou", cancelada: "Cancelada",
};
export const CART_STATUS_LABEL: Record<CartStatus, string> = {
  aberto: "Em andamento", recuperado: "Recuperado", comprou_sem_contato: "Comprou sozinho", expirado: "Não voltou",
  sem_contato: "Sem contato", pausado: "Pausado",
};
export const BLOCK_LABEL: Record<BlockType, string> = {
  logo: "Logo", titulo: "Título", texto: "Texto", imagem: "Imagem", botao: "Botão", produtos: "Produtos do carrinho", divisor: "Divisor", espaco: "Espaço",
};
export const VARIABLE_HINT = "{{primeiro_nome}} · {{nome}} · {{marca}} · {{link_loja}}";
export const CART_VARIABLE_HINT = "{{primeiro_nome}} · {{link_carrinho}} · {{valor_carrinho}} · {{marca}}";

export function delayLabel(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  if (minutes < 1440) return `${Math.round(minutes / 60)} h`;
  const days = minutes / 1440;
  return `${Number.isInteger(days) ? days : days.toFixed(1)} ${days === 1 ? "dia" : "dias"}`;
}

const DOMAIN_LABEL: Record<string, string> = {
  verified: "Domínio verificado", pending: "Verificação pendente no Resend", not_started: "Verificação não iniciada no Resend",
  failed: "Verificação falhou no Resend", nao_cadastrado: "Domínio não cadastrado no Resend", indisponivel: "Resend indisponível agora",
};

export function senderNotice(status: SenderStatus | null): string | null {
  if (!status) return null;
  if (!status.configured) return "Falta a chave do Resend no servidor (RESEND_API_KEY). Sem ela nada é enviado.";
  if (!status.from_email) return "Configure o remetente na aba Remetente antes de enviar.";
  if (status.domain_status !== "verified") return `${DOMAIN_LABEL[status.domain_status || ""] || "Domínio sem verificação"}: ${status.domain}.`;
  if (!status.send_enabled) return "Modo simulado: tudo roda e fica registrado, mas nenhum e-mail sai até EMAIL_SEND_ENABLED=true.";
  return null;
}

// ---------------------------------------------------------------- fluxos comerciais

export type FlowKind = "boas_vindas" | "pos_venda" | "segunda_compra" | "reativacao";
export type CommercialFlow = {
  kind: FlowKind; label: string; enabled: boolean; channel: "email" | "whatsapp"; delay_days: number; consent: "consentimento" | "todos";
  subject: string; preheader: string; design: EmailDesign; custom_html: string | null; whatsapp_template: string | null;
  whatsapp_language: string; whatsapp_variables: ("nome" | "marca" | "link")[]; updated_at?: string | null;
  result: { sent: number; skipped: number; failed: number; buyers: number; revenue: number; conversion: number | null };
};
export type FlowsOverview = { days: number; flows: CommercialFlow[]; journey_built_at: string | null; simulated: { email: boolean; whatsapp: boolean } };

export const getFlows = (days = 30) => http<FlowsOverview>(`/api/flows?days=${days}`, { timeoutMs: 60_000 });
export const saveFlow = (kind: FlowKind, patch: Partial<CommercialFlow>) =>
  http<{ flow: CommercialFlow }>(`/api/flows/${kind}`, { method: "PUT", ...json(patch) });
export const previewFlow = (kind: FlowKind, flow: Partial<CommercialFlow>) =>
  http<EmailPreviewResult>(`/api/flows/${kind}/preview`, { method: "POST", ...json(flow) });

export const FLOW_HELP: Record<FlowKind, { when: string; delay: string }> = {
  boas_vindas: { when: "Primeira compra", delay: "dias depois da primeira compra" },
  pos_venda: { when: "Depois de cada compra", delay: "dias depois da compra" },
  segunda_compra: { when: "Quem comprou 1 vez e não voltou", delay: "dias depois da primeira compra" },
  reativacao: { when: "Quem parou de comprar", delay: "dias sem comprar" },
};
