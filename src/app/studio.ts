import { http, clientClientPath, publicHttp } from "./api";

export const STUDIO_FORMATS = { reels: "Reels", carrossel: "Carrossel", imagem: "Imagem", stories: "Stories", video: "Vídeo" } as const;
export type StudioFormat = keyof typeof STUDIO_FORMATS;
export const STUDIO_STATUS = { rascunho: "Rascunho", em_revisao: "Em revisão", aprovado: "Aprovado", rejeitado: "Rejeitado" } as const;
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
export type ApprovalRequest = { id: string; month: string; items: number; contact_name: string | null; status: "aberto" | "concluido" | "cancelado" | "expirado"; expires_at: string; created_at: string; completed_at: string | null };
export type ApprovalCreated = { request_id: string; link: string; expires_at: string; whatsapp_text: string; whatsapp_url: string };
export function listApprovals(): Promise<{ requests: ApprovalRequest[] }> { return http(base("/approvals")); }
export function sendForApproval(input: { month: string; item_ids: string[]; contact_name?: string; contact_phone?: string; message?: string }) {
  return http<ApprovalCreated>(base("/approvals"), { method: "POST", body: JSON.stringify(input) });
}
export function cancelApproval(id: string) { return http(base(`/approvals/${encodeURIComponent(id)}`), { method: "DELETE" }); }

export type PublicApprovalItem = Pick<CalendarItem, "id" | "scheduled_at" | "format" | "pillar" | "title" | "hook" | "caption_draft"> & { decision: "aprovado" | "ajuste_solicitado" | null; comment: string | null };
export type PublicApproval = { client_name: string; month: string; contact_name: string | null; status: string; expires_at: string; items: PublicApprovalItem[] };
export function getPublicApproval(token: string) { return publicHttp<PublicApproval>(`/api/public/approvals/${encodeURIComponent(token)}`); }
export function decidePublicApproval(token: string, itemId: string, body: { action: "aprovado" | "ajuste_solicitado"; comment?: string; reviewer_name?: string }) {
  return publicHttp<{ ok: boolean }>(`/api/public/approvals/${encodeURIComponent(token)}/items/${encodeURIComponent(itemId)}`, { method: "POST", body: JSON.stringify(body) });
}
