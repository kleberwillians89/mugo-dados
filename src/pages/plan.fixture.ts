import type { AdminPlans, PlanOverview, SaasPlan } from "../app/saas";

export const PLANS: SaasPlan[] = [
  { id: "essencial", name: "Essencial", price_month_cents: 49700, limits: { users: 3, email_sends_month: 10000, whatsapp_month: 500, ai_actions_month: 10, competitors: 3, monitored_products: 20 }, features: [], active: true, sort: 1 },
  { id: "crescimento", name: "Crescimento", price_month_cents: 99700, limits: { users: 8, email_sends_month: 50000, whatsapp_month: 3000, ai_actions_month: 40, competitors: 8, monitored_products: 80 }, features: [], active: true, sort: 2 },
  { id: "escala", name: "Escala", price_month_cents: 199700, limits: { users: 25, email_sends_month: 200000, whatsapp_month: 15000, ai_actions_month: 200, competitors: 20, monitored_products: 200 }, features: [], active: true, sort: 3 },
];
export const PLAN_FIXTURE: PlanOverview = {
  plans: PLANS,
  subscription: { client_id: "roove", plan_id: "crescimento", status: "ativa", trial_ends_at: null, billing_day: 5, plan: PLANS[1] },
  meters: [
    { key: "users", label: "Usuários", used: 5, limit: 8, remaining: 3 },
    { key: "email_sends_month", label: "E-mails no mês", used: 41200, limit: 50000, remaining: 8800 },
    { key: "whatsapp_month", label: "WhatsApp no mês", used: 940, limit: 3000, remaining: 2060 },
    { key: "ai_actions_month", label: "Ações da IA no mês", used: 4, limit: 40, remaining: 36 },
    { key: "competitors", label: "Concorrentes", used: 5, limit: 8, remaining: 3 },
    { key: "monitored_products", label: "Produtos monitorados", used: 24, limit: 80, remaining: 56 },
  ],
  invoices: [
    { id: "i2", period: "2026-11", plan_id: "crescimento", amount_cents: 99700, status: "aberta", due_date: "2026-11-05", paid_at: null, payment_url: null },
    { id: "i1", period: "2026-10", plan_id: "crescimento", amount_cents: 99700, status: "paga", due_date: "2026-10-05", paid_at: "2026-10-04T12:00:00Z", payment_url: null },
  ],
  onboarding: [
    { key: "loja", label: "Conectar a loja (Shopify ou FBITS)", done: true, route: "integrations" },
    { key: "meta", label: "Conectar Meta (anúncios e Instagram)", done: true, route: "integrations" },
    { key: "ga4", label: "Conectar o Google Analytics 4", done: true, route: "integrations" },
    { key: "google_ads", label: "Conectar o Google Ads", done: false, route: "integrations" },
    { key: "remetente", label: "Configurar o remetente de e-mail", done: true, route: "email_marketing" },
    { key: "whatsapp", label: "Ligar o número de WhatsApp da marca", done: false, route: "whatsapp" },
    { key: "jornada", label: "Montar a jornada do cliente", done: true, route: "customers" },
    { key: "fluxo", label: "Ligar o primeiro fluxo automático", done: false, route: "email_marketing" },
    { key: "concorrente", label: "Cadastrar um concorrente no benchmarking", done: true, route: "benchmark" },
  ],
};
export const ADMIN_FIXTURE: AdminPlans = {
  plans: PLANS, mrr_cents: 99700 + 49700,
  companies: [
    { client_id: "roove", name: "Roove", subscription: { client_id: "roove", plan_id: "crescimento", status: "ativa", trial_ends_at: null, billing_day: 5 }, plan_name: "Crescimento", mrr_cents: 99700, open_cents: 99700, overdue: false },
    { client_id: "ruah", name: "Ruah Parfums", subscription: { client_id: "ruah", plan_id: "essencial", status: "atrasada", trial_ends_at: null, billing_day: 10 }, plan_name: "Essencial", mrr_cents: 49700, open_cents: 49700, overdue: true },
    { client_id: "curavino", name: "Curavino", subscription: null, plan_name: null, mrr_cents: 0, open_cents: 0, overdue: false },
  ],
};
