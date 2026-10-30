import { http, clientClientPath } from "./api";

export type AutomationState = {
  automation_enabled: boolean; template_approved: boolean; integration_configured: boolean; operational: boolean;
  simulated_only: boolean; problems: string[];
};
export type AutomationTemplate = {
  category: string | null; language: string; status: string; rejected_reason: string | null; body_param_count: number;
  button_url_dynamic: boolean; quick_replies: string[]; synced_at: string;
} | null;
export type Automation = {
  key: string; template_name: string; language: string; owner: "dados" | "crm" | "tecnico"; audience: "cliente" | "equipe" | "lead";
  expected_category: string; trigger_label: string; automation_enabled: boolean; schedule: { time?: string; weekdays?: number[] };
  lead_minutes: number | null; recipients: Record<string, unknown>; variable_map: string[]; crm_reference: string | null; notes: string | null;
  template: AutomationTemplate; state: AutomationState;
};
export type CalendarStatus = {
  status: "desconectado" | "aguardando_calendario" | "ativo" | "reautorizar" | "erro"; account_email: string | null;
  calendar_id: string | null; calendar_summary: string | null; last_sync_at: string | null; last_error: string | null;
  channel_expires_at: string | null; webhook: boolean;
};
export type Overview = {
  flags: { send_enabled: boolean; mugozap_configured: boolean; catalog_configured: boolean; catalog_synced_at: string | null; calendar: CalendarStatus };
  automations: Automation[]; other_templates: { name: string; language: string; category: string | null; status: string }[];
};
export type OutboxItem = {
  id: string; automation_key: string; template_name: string; client_id: string | null; audience: string; recipient_name: string | null;
  recipient_phone: string; source_type: string; scheduled_for: string; status: string; attempts: number; next_attempt_at: string | null;
  last_error: string | null; delivery_status: string | null; sent_at: string | null; cancelled_reason: string | null; created_at: string;
};
export type ResponseItem = { id: string; client_id: string | null; phone_masked: string | null; answer_raw: string | null; answer_key: string | null; result: string | null; received_at: string };
export type Usage = { month_start: string; by_status: Record<string, number>; sent_by_category: Record<string, number>; estimated_cost_brl: number | null; cost_note: string };
export type TeamMember = { id: string; name: string; email: string; phone: string | null; active: boolean; receives_internal: boolean; receives_campaign_alerts: boolean };
export type TeamInput = Omit<TeamMember, "id">;
export type Simulation = { automation: string; template_name: string; would_send: boolean; blocked_reason: string | null; text: string | null; real_send: false };
export type Meeting = { google_event_id: string; summary: string | null; start_at: string; end_at: string | null; all_day: boolean; kind: string; client_id?: string | null; html_link?: string | null };

const base = "/api/automations";
const json = (method: string, body?: unknown) => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

export const getOverview = () => http<Overview>(base);
export const updateAutomation = (key: string, patch: Partial<Pick<Automation, "automation_enabled" | "lead_minutes" | "schedule" | "variable_map">>) =>
  http<Automation>(`${base}/${encodeURIComponent(key)}`, json("PATCH", patch));
export const syncCatalog = () => http<{ templates: number; approved: number }>(`${base}/catalog/sync`, json("POST"));
export const getOutbox = (status?: string) => http<{ items: OutboxItem[] }>(`${base}/outbox${status ? `?status=${encodeURIComponent(status)}` : ""}`);
export const getResponses = () => http<{ items: ResponseItem[] }>(`${base}/responses`);
export const getUsage = () => http<Usage>(`${base}/usage`);
export const processQueue = () => http<Record<string, number | boolean>>(`${base}/process`, json("POST"));
export const simulateAutomation = (key: string, params: Record<string, string>, phone?: string) =>
  http<Simulation>(`${base}/${encodeURIComponent(key)}/simulate`, json("POST", { params, phone: phone || null }));
export const listTeam = () => http<{ items: TeamMember[] }>(`${base}/team`);
export const saveTeamMember = (input: TeamInput, id?: string) =>
  http<TeamMember>(`${base}/team${id ? `/${encodeURIComponent(id)}` : ""}`, json(id ? "PATCH" : "POST", input));
export const deleteTeamMember = (id: string) => http(`${base}/team/${encodeURIComponent(id)}`, json("DELETE"));
export const calendarStart = () => http<{ url: string }>(`${base}/google-calendar/start`);
export const listGoogleCalendars = () => http<{ items: { id: string; summary: string; primary: boolean }[] }>(`${base}/google-calendar/calendars`);
export const selectGoogleCalendar = (calendar_id: string) => http<{ changed: number }>(`${base}/google-calendar/select`, { ...json("POST", { calendar_id }), timeoutMs: 120_000 });
export const syncGoogleCalendar = () => http<{ changed: number }>(`${base}/google-calendar/sync`, { ...json("POST"), timeoutMs: 120_000 });
export const listAllMeetings = (start: string, end: string) => http<{ items: Meeting[] }>(`${base}/meetings?${new URLSearchParams({ start, end })}`);
export const listClientMeetings = (start: string, end: string) => http<{ items: Meeting[] }>(clientClientPath(`/meetings?${new URLSearchParams({ start, end })}`));

export const OUTBOX_STATUS: Record<string, string> = {
  agendado: "Agendado", processando: "Processando", enviado: "Enviado", falhou: "Falhou", cancelado: "Cancelado", bloqueado: "Bloqueado", simulado: "Simulado",
};
export const DELIVERY: Record<string, string> = { accepted: "aceito pela Meta", sent: "enviado", delivered: "entregue", read: "lido", failed: "falha na entrega" };
export const OWNER: Record<Automation["owner"], string> = { dados: "Mugô Dados", crm: "CRM Mugô", tecnico: "Técnico" };
export const AUDIENCE: Record<Automation["audience"], string> = { cliente: "Cliente", equipe: "Equipe Mugô", lead: "Lead" };
export const when = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";
