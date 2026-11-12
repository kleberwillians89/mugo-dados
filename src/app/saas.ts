import { http } from "./api";
import type { AppRoute } from "./routes";

export type LimitKey = "users" | "email_sends_month" | "whatsapp_month" | "ai_actions_month" | "competitors" | "monitored_products";
export type SaasPlan = { id: string; name: string; price_month_cents: number; limits: Partial<Record<LimitKey, number>>; features: string[]; active: boolean; sort: number };
export type SubStatus = "teste" | "ativa" | "atrasada" | "cancelada" | "cortesia";
export type Subscription = { client_id: string; plan_id: string; status: SubStatus; trial_ends_at: string | null; billing_day: number; notes?: string | null; plan?: SaasPlan | null };
export type Meter = { key: LimitKey; label: string; used: number; limit: number | null; remaining: number | null };
export type Invoice = { id: string; period: string; plan_id: string; amount_cents: number; status: "aberta" | "paga" | "vencida" | "cancelada"; due_date: string; paid_at: string | null; payment_url: string | null };
export type OnboardingStep = { key: string; label: string; done: boolean; route: AppRoute };
export type PlanOverview = { subscription: Subscription | null; meters: Meter[]; invoices: Invoice[]; onboarding: OnboardingStep[]; plans: SaasPlan[] };
export type AdminCompany = { client_id: string; name: string; subscription: Subscription | null; plan_name: string | null; mrr_cents: number; open_cents: number; overdue: boolean };
export type AdminPlans = { companies: AdminCompany[]; plans: SaasPlan[]; mrr_cents: number };

const json = (body: unknown) => ({ body: JSON.stringify(body), headers: { "Content-Type": "application/json" } });
export const getMyPlan = () => http<PlanOverview>("/api/plan", { timeoutMs: 60_000 });
export const getAdminPlans = () => http<AdminPlans>("/api/admin/plans/overview", { timeoutMs: 60_000 });
export const savePlan = (id: string, body: Partial<SaasPlan>) => http<{ plan: SaasPlan }>(`/api/admin/plans/${encodeURIComponent(id)}`, { method: "PUT", ...json(body) });
export const saveSubscription = (clientId: string, body: { plan_id: string; status: SubStatus; trial_days?: number; billing_day?: number; notes?: string }) =>
  http<{ subscription: Subscription }>(`/api/admin/subscriptions/${encodeURIComponent(clientId)}`, { method: "PUT", ...json(body) });
export const removeSubscription = (clientId: string) => http<{ ok: boolean }>(`/api/admin/subscriptions/${encodeURIComponent(clientId)}`, { method: "DELETE" });
export const markInvoicePaid = (clientId: string, invoiceId: string) =>
  http<{ invoice: Invoice }>(`/api/admin/invoices/${encodeURIComponent(clientId)}/${encodeURIComponent(invoiceId)}/paid`, { method: "POST" });

export const STATUS_LABEL: Record<SubStatus, string> = { teste: "Em teste", ativa: "Ativa", atrasada: "Pagamento atrasado", cancelada: "Cancelada", cortesia: "Cortesia" };
export const brl = (cents: number) => (cents / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
