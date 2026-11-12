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

export const AUDIT_FIXTURE: import("../app/integrationCenter").DataAudit = {
  client_id: "roove", period: { start: "2026-10-12", end: "2026-11-10" },
  store: { provider: "shopify", status: "available", orders: 412, revenue: 96400, origin_coverage_percent: 61.4 },
  summary: { ok: 3, warn: 3, bad: 1, na: 0 },
  checks: [
    { key: "ga4_orders", title: "GA4 enxerga as vendas da loja", status: "warn", value: 71.6, unit: "%", detail: "295 compras no GA4 para 412 pedidos da loja.",
      cause: "O evento de compra não dispara em parte das vendas (checkout externo, página de obrigado sem tag, bloqueador de anúncio ou consentimento de cookies).",
      todo: "Conferir a tag de compra no checkout (GTM/app da loja) e o modo de consentimento." },
    { key: "overlap", title: "Atribuição de Meta + Google × receita da loja", status: "bad", value: 163.2, unit: "%", detail: "Meta R$ 118.300 + Google R$ 39.000 = R$ 157.300, para R$ 96.400 vendidos na loja.",
      cause: "Cada plataforma reivindica a mesma venda (janelas de atribuição que se sobrepõem, view-through da Meta).",
      todo: "Usar a Origem das vendas (CRM) para decidir verba; tratar a receita das plataformas como sinal, não como faturamento." },
    { key: "origin", title: "Pedidos com origem identificada", status: "warn", value: 61.4, unit: "%", detail: "253 de 412 pedidos com UTM, referência ou GA4.",
      cause: "Anúncios ou links sem UTM, compras pelo app/WhatsApp sem rastreio.", todo: "Padronizar UTMs (Meta: parâmetros de URL no nível do anúncio; Google: auto-tagging + modelo de rastreamento)." },
    { key: "ga4_match", title: "Pedidos da loja achados no GA4 pela transação", status: "warn", value: 66.0, unit: "%", detail: "272 de 412 pedidos têm o mesmo ID de transação no GA4.",
      cause: "O GA4 recebe a compra com um transaction_id diferente do número do pedido (ou sem ID).", todo: "Enviar no purchase o mesmo ID do pedido da loja; é ele que liga cada venda à campanha." },
    { key: "coverage_meta_spend", title: "Dias com dado: Meta Ads", status: "ok", value: 30, unit: "dias", detail: "30 de 30 dias com dado.", cause: "", todo: "" },
    { key: "coverage_ga4_sessions", title: "Dias com dado: GA4", status: "ok", value: 30, unit: "dias", detail: "30 de 30 dias com dado.", cause: "", todo: "" },
    { key: "duplicates", title: "Pedidos repetidos na loja", status: "ok", value: 0, unit: "itens", detail: "Nenhum pedido repetido.", cause: "", todo: "" },
  ],
};
