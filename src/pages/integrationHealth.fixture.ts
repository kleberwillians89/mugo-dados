/** Dados de exemplo da Central de saúde das integrações (testes e revisão visual). */
import type { CenterSource, IntegrationCenter } from "../app/integrationCenter";

const src = (provider: string, label: string, state: CenterSource["state"], extra: Partial<CenterSource> = {}): CenterSource => ({
  provider, label, state, severity: 0, action: "none", hint: "Tudo certo.", error_code: null,
  last_success_at: new Date(Date.now() - 40 * 60000).toISOString(), last_attempt_at: null, last_data_at: "2026-11-11", coverage_end: "2026-11-11",
  failures_7d: 0, ...extra,
});
export const CENTER_FIXTURE: IntegrationCenter = {
  generated_at: new Date().toISOString(), window: { start: "2026-11-05", end: "2026-11-11" },
  summary: { connections: 9, ok: 6, updating: 0, problems: 1, stale: 1, no_data: 1, reauth: 1, failures_7d: 4, companies_with_problem: 2 },
  queue: { waiting: 2, failed: 1 },
  companies: [
    { id: "roove", name: "Roove", status: "active", worst: 0, error: null, queue: { waiting: 0, failed: 0 }, sources: [
      src("meta_ads", "Meta Ads", "reauth_required", { action: "reconnect", hint: "Reconectar em Integrações: o acesso expirou ou foi revogado.", error_code: "REAUTH_REQUIRED", failures_7d: 3, last_success_at: new Date(Date.now() - 52 * 3600000).toISOString() }),
      src("shopify", "Shopify", "synced"), src("instagram", "Instagram", "synced"), src("ga4", "GA4", "synced"),
      src("google_ads", "Google Ads", "not_connected")] },
    { id: "ruah", name: "Ruah", status: "active", worst: 2, error: null, queue: { waiting: 2, failed: 1 }, sources: [
      src("instagram", "Instagram", "stale", { action: "sync", hint: "Atrasada: rodar a sincronização agora e conferir se o agendamento está ativo.", failures_7d: 1, last_success_at: new Date(Date.now() - 30 * 3600000).toISOString() }),
      src("shopify", "Shopify", "no_data", { action: "check", hint: "Conectada, mas sem dado no período: conferir a conta selecionada.", last_data_at: null })] },
    { id: "curavino", name: "Curavino", status: "active", worst: 5, error: null, queue: { waiting: 0, failed: 0 }, sources: [
      src("fbits", "FBITS", "synced"), src("meta_ads", "Meta Ads", "synced")] },
  ],
};
