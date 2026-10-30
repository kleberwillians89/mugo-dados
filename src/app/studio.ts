import { http, clientClientPath, publicHttp } from "./api";
import type { StudioAsset } from "./studioAssets";

export const STUDIO_FORMATS = { reels: "Reels", carrossel: "Carrossel", imagem: "Imagem", stories: "Stories", video: "Vídeo" } as const;
export type StudioFormat = keyof typeof STUDIO_FORMATS;
export const STUDIO_STATUS = { rascunho: "Rascunho", em_revisao: "Em revisão", aprovado: "Aprovado", rejeitado: "Rejeitado", publicado: "Publicado" } as const;
export type StudioStatus = keyof typeof STUDIO_STATUS;

export type BrandPillar = { name: string; weight: number; description: string };
export type BrandProfile = {
  tone_of_voice: string; personality: string; audience: string; pillars: BrandPillar[];
  keywords_use: string[]; keywords_avoid: string[]; hashtags: string[]; restrictions: string;
  posts_per_week: number; formats_enabled: StudioFormat[]; custom_dates: { date: string; label: string }[];
};

export type CalendarSignals = {
  basis?: { reason?: string; hours?: string; weekday_reach_index?: number | null; slot_reach_index?: number | null; confidence?: string | null };
  seasonal?: string | null;
  trend?: { topic: string; source_url: string; researched_at: string };
  palavras_evitar_encontradas?: string[];
};

export type CalendarItem = {
  id: string; client_id: string; month: string; scheduled_at: string; format: StudioFormat;
  pillar: string | null; title: string; hook: string | null; caption_draft: string | null; rationale: string | null;
  signals: CalendarSignals; status: StudioStatus; review_note: string | null; origin: "ia" | "manual";
  reviewed_by: string | null; reviewed_at: string | null; updated_at?: string;
  /** Arte anexada, na ordem dos slides; URLs assinadas de curta duração. */
  assets?: StudioAsset[];
  /** Impulsionamento previsto no plano do Mídia On salvo para o mês (só na tela). */
  boost?: { start: string; end: string; budget: number; why: string };
};

export type ItemPatch = Partial<Pick<CalendarItem, "scheduled_at" | "format" | "pillar" | "title" | "hook" | "caption_draft" | "rationale" | "status" | "review_note">>;

const base = (path: string) => clientClientPath(`/studio${path}`);

export function getBrandProfile(): Promise<{ profile: BrandProfile; saved: boolean; updated_at?: string | null }> {
  return http(base("/brand-profile"));
}
export function saveBrandProfile(profile: BrandProfile) {
  return http<{ profile: BrandProfile }>(base("/brand-profile"), { method: "PUT", body: JSON.stringify(profile) });
}
export function getCalendar(month: string): Promise<{ month: string; items: CalendarItem[] }> {
  return http(base(`/calendar?month=${encodeURIComponent(month)}`));
}
export function generateCalendar(month: string): Promise<{ created: number; kept: number; items: CalendarItem[]; observacoes: string[] }> {
  // Gera com IA: pode levar mais que o timeout padrão de leitura.
  return http(base("/calendar/generate"), { method: "POST", body: JSON.stringify({ month }), timeoutMs: 150_000 });
}
export function updateCalendarItem(id: string, patch: ItemPatch) {
  return http<{ item: CalendarItem }>(base(`/calendar/items/${encodeURIComponent(id)}`), { method: "PATCH", body: JSON.stringify(patch) });
}
export function createCalendarItem(item: Required<Pick<CalendarItem, "scheduled_at" | "format" | "title">> & ItemPatch) {
  return http<{ item: CalendarItem }>(base("/calendar/items"), { method: "POST", body: JSON.stringify(item) });
}
export function deleteCalendarItem(id: string) {
  return http(base(`/calendar/items/${encodeURIComponent(id)}`), { method: "DELETE" });
}

const SP = "America/Sao_Paulo";
export function localParts(iso: string) {
  const d = new Date(iso);
  const date = new Intl.DateTimeFormat("en-CA", { timeZone: SP, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
  const time = new Intl.DateTimeFormat("pt-BR", { timeZone: SP, hour: "2-digit", minute: "2-digit", hour12: false }).format(d);
  const weekday = new Intl.DateTimeFormat("pt-BR", { timeZone: SP, weekday: "long" }).format(d);
  const label = new Intl.DateTimeFormat("pt-BR", { timeZone: SP, day: "2-digit", month: "short" }).format(d);
  return { date, time, weekday, label };
}
/** "2026-11-03" + "19:00" no fuso de São Paulo (UTC-3, sem horário de verão). */
export function toSaoPauloIso(date: string, time: string) {
  return `${date}T${time}:00-03:00`;
}
export function nextMonth(): string {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth() + 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
export const listToText = (values: string[] | undefined) => (values || []).join(", ");
export const textToList = (value: string) => value.split(/[,\n]/).map((v) => v.trim()).filter(Boolean);

// ------------------------------------------------------------ aprovação do cliente
export type ApprovalRequest = { id: string; month: string; items: number; contact_name: string | null; status: "aberto" | "concluido" | "cancelado" | "expirado"; expires_at: string; created_at: string; completed_at: string | null; last_reminded_at?: string | null };
export type ApprovalCreated = { request_id: string; link: string; expires_at: string; whatsapp_text: string; whatsapp_url: string; whatsapp?: MessageResult | { status: "falhou"; detail: string } };
export function listApprovals(): Promise<{ requests: ApprovalRequest[] }> { return http(base("/approvals")); }
export function sendForApproval(input: { month: string; item_ids: string[]; contact_name?: string; contact_phone?: string; message?: string; contact_id?: string; send_whatsapp?: boolean }) {
  return http<ApprovalCreated>(base("/approvals"), { method: "POST", body: JSON.stringify(input) });
}
export function cancelApproval(id: string) { return http(base(`/approvals/${encodeURIComponent(id)}`), { method: "DELETE" }); }

export type PublicApprovalItem = Pick<CalendarItem, "id" | "scheduled_at" | "format" | "pillar" | "title" | "hook" | "caption_draft" | "assets"> & { decision: "aprovado" | "ajuste_solicitado" | null; comment: string | null };
export type PublicApproval = { client_name: string; month: string; contact_name: string | null; status: string; expires_at: string; items: PublicApprovalItem[] };
export function getPublicApproval(token: string) { return publicHttp<PublicApproval>(`/api/public/approvals/${encodeURIComponent(token)}`); }
export function decidePublicApproval(token: string, itemId: string, body: { action: "aprovado" | "ajuste_solicitado"; comment?: string; reviewer_name?: string }) {
  return publicHttp<{ ok: boolean }>(`/api/public/approvals/${encodeURIComponent(token)}/items/${encodeURIComponent(itemId)}`, { method: "POST", body: JSON.stringify(body) });
}

// ------------------------------------------------------------ inteligência e motores de conteúdo
export type BasedOn = { kpis: number; campanhas: number; posts_analisados: number; metas: number; aprovados: number; ajustes: number; lacunas: string[] };
export const GAP_LABELS: Record<string, string> = {
  perfil_da_marca_vazio: "perfil da marca vazio", contexto_do_negocio_vazio: "contexto do negócio vazio", sem_kpis_no_periodo: "sem KPIs no período",
  sem_historico_de_posts: "sem histórico de posts", sem_metas_no_mes: "sem metas no mês", kpis_e_campanhas: "KPIs indisponíveis agora",
  posts_instagram: "posts indisponíveis agora", melhores_horarios: "horários indisponíveis agora", metas: "metas indisponíveis agora",
  ultima_analise: "análise indisponível agora", aprendizados_de_aprovacao: "aprendizados indisponíveis agora",
  perfil_da_marca: "perfil indisponível agora", contexto_do_negocio: "contexto indisponível agora",
};
export function basedOnText(b?: BasedOn | null): string {
  if (!b) return "";
  const parts = [b.posts_analisados ? `${b.posts_analisados} posts analisados` : "", b.aprovados ? `${b.aprovados} pauta(s) aprovada(s)` : "",
    b.ajustes ? `${b.ajustes} ajuste(s) pedido(s)` : "", b.campanhas ? `${b.campanhas} campanha(s)` : "", b.kpis ? `${b.kpis} KPI(s)` : "",
    b.metas ? `${b.metas} meta(s)` : ""].filter(Boolean);
  return parts.length ? `Com base em ${parts.join(", ")}.` : "Sem dados suficientes da conta: a IA usou só o perfil e a pauta.";
}

export const ASSIST_ACTIONS = { legenda: "Legenda final", variacoes: "3 variações", ganchos: "5 ganchos", hashtags: "Hashtags", roteiro_reels: "Roteiro de Reels", revisar: "Revisar" } as const;
export type AssistAction = keyof typeof ASSIST_ACTIONS;
export type AssistResult =
  | { action: "legenda"; result: { caption: string; cta: string; why: string } }
  | { action: "variacoes"; result: { variations: { angle: string; caption: string }[]; recommended_index: number; why: string } }
  | { action: "ganchos"; result: { hooks: { hook: string; angle: string }[] } }
  | { action: "hashtags"; result: { hashtags: string[]; why: string } }
  | { action: "roteiro_reels"; result: { duration_seconds: number; cover_text: string; audio_suggestion: string; scenes: { seconds: string; visual: string; text_on_screen: string; voiceover: string }[] } }
  | { action: "revisar"; result: { issues: { problem: string; fix: string }[]; improved_caption: string } };
export type AssistResponse = AssistResult & { flags: string[]; based_on: BasedOn };
export function runAssist(action: AssistAction, item: { format: StudioFormat; title: string; pillar?: string; hook?: string; caption_draft?: string; scheduled_at?: string }, instruction?: string) {
  return http<AssistResponse>(base("/assist"), { method: "POST", body: JSON.stringify({ action, item, instruction: instruction || undefined }), timeoutMs: 100_000 });
}
export type ChatTurn = { role: "user" | "assistant"; content: string };
export function strategyChat(month: string, messages: ChatTurn[]) {
  return http<{ reply: string; suggested_actions: string[]; based_on: BasedOn }>(base("/strategy/chat"), { method: "POST", body: JSON.stringify({ month, messages }), timeoutMs: 100_000 });
}
export function suggestBrandProfile(guideAssetId?: string) {
  return http<{ profile: BrandProfile; notes: string[]; used_guide: boolean; based_on: BasedOn }>(base("/brand-profile/suggest"), { method: "POST", body: JSON.stringify({ guide_asset_id: guideAssetId || undefined }), timeoutMs: 120_000 });
}

// ------------------------------------------------------------ aprovação: funil, contatos e mensagens
export const STAGES = { rascunho: "Rascunho", revisao_interna: "Revisão interna", com_cliente: "Com o cliente", ajuste: "Ajuste pedido", aprovado: "Aprovado", publicado: "Publicado" } as const;
export type Stage = keyof typeof STAGES;
/** Status gravado quando a pauta é arrastada para a coluna; "com o cliente" só via envio do link. */
export const STAGE_STATUS: Partial<Record<Stage, StudioStatus>> = { rascunho: "rascunho", revisao_interna: "em_revisao", ajuste: "rejeitado", aprovado: "aprovado", publicado: "publicado" };
export type PipelineItem = CalendarItem & { stage: Stage; request: { request_id: string; sent_at: string; contact_name: string | null; expires_at: string; last_reminded_at: string | null } | null;
  client_feedback: { action: "aprovado" | "ajuste_solicitado"; comment: string | null; reviewer_name: string | null; created_at: string } | null };
export function getPipeline(month: string) {
  return http<{ month: string; stages: Stage[]; counts: Record<Stage, number>; items: PipelineItem[] }>(base(`/approvals/pipeline?month=${encodeURIComponent(month)}`));
}

export const RECEIVES = { conteudo: "Conteúdo", trafego: "Tráfego pago", resultados: "Resultados do mês" } as const;
export type Receives = keyof typeof RECEIVES;
export type ClientContact = { id: string; name: string; phone: string; role: string | null; receives: Receives[]; is_primary: boolean };
export type ContactInput = { name: string; phone: string; role?: string; receives: Receives[]; is_primary: boolean };
export function listContacts() { return http<{ contacts: ClientContact[]; whatsapp_channel: "mugozap" | "wa_link" }>(base("/contacts")); }
export function createContact(input: ContactInput) { return http<{ contact: ClientContact }>(base("/contacts"), { method: "POST", body: JSON.stringify(input) }); }
export function updateContact(id: string, input: ContactInput) { return http<{ contact: ClientContact }>(base(`/contacts/${encodeURIComponent(id)}`), { method: "PUT", body: JSON.stringify(input) }); }
export function deleteContact(id: string) { return http(base(`/contacts/${encodeURIComponent(id)}`), { method: "DELETE" }); }

export const MESSAGE_KINDS = { aprovacao: "Pautas para aprovar", lembrete: "Lembrete de aprovação", agenda: "Agenda da semana", trafego: "Relatório de tráfego (7 dias)", resultados: "Resultados do mês" } as const;
export type MessageKind = keyof typeof MESSAGE_KINDS;
export type MessagePreview = { kind: MessageKind; template_name: string; params: Record<string, string>; text: string; editable: string[];
  contact: { id: string; name: string; role: string | null }; phone_masked: string; header_image: string | null; channel: "mugozap" | "wa_link" };
export type MessageResult = { status: "enviado" | "link_gerado"; channel: "mugozap" | "wa_link"; whatsapp_url?: string; text: string; already_sent?: boolean };
export type MessageLog = { id: string; contact_name: string | null; phone_masked: string | null; kind: MessageKind; template_name: string | null; channel: string; status: string; error_code: string | null; preview: { text?: string }; created_at: string };
type MessageInput = { kind: MessageKind; contact_id?: string; request_id?: string; overrides?: Record<string, string> };
export function previewMessage(input: MessageInput) { return http<MessagePreview>(base("/messages/preview"), { method: "POST", body: JSON.stringify(input), timeoutMs: 60_000 }); }
export function sendMessage(input: MessageInput) { return http<MessageResult>(base("/messages/send"), { method: "POST", body: JSON.stringify(input), timeoutMs: 60_000 }); }
export function listMessages() { return http<{ messages: MessageLog[]; templates: string[]; whatsapp_channel: "mugozap" | "wa_link" }>(base("/messages")); }
