import { clientClientPath, http } from "./api";

/** Consumo de IA por cliente (só a equipe Mugô; o backend exige agency/platform admin). */
export type UsageBucket = { calls: number; errors: number; input_tokens: number; output_tokens: number; total_tokens: number; cost_usd: number };
export type UsageError = { code: string | null; at: string; feature: string | null; client?: string };
export type ClientUsage = UsageBucket & { client_id: string | null; name: string; features: (UsageBucket & { feature: string })[]; last_error: UsageError | null; last_call: string | null };
export type AiUsageReport = {
  period: { start: string; end: string }; currency: "USD"; estimated: boolean;
  totals: UsageBucket; clients: ClientUsage[]; features: (UsageBucket & { feature: string })[];
  daily: (UsageBucket & { date: string })[]; last_error: UsageError | null; quota_exhausted: boolean; unpriced_models: string[];
};

export function getAiUsage(start: string, end: string) {
  const q = new URLSearchParams({ start, end });
  return http<AiUsageReport & { ok: boolean }>(`/api/admin/ai-usage?${q.toString()}`);
}

/** Nome amigável do recurso que chamou a IA (schema da chamada). */
export function featureLabel(feature: string): string {
  const map: Record<string, string> = {
    studio_content_matrix: "Matriz de conteúdo", studio_matrix_refine: "Matriz: refinar", studio_calendar_month: "Calendário: gerar mês",
    studio_doc_escrever: "Redação: escrever", studio_doc_continuar: "Redação: continuar", studio_doc_reescrever: "Redação: reescrever",
    studio_doc_encurtar: "Redação: encurtar", studio_doc_expandir: "Redação: expandir", studio_doc_corrigir: "Redação: corrigir",
    studio_doc_titles: "Redação: títulos", ai_summary: "Resumo com IA",
    studio_matrix_content: "Matriz: criar conteúdo", ig_comment_reply: "Comentários: respostas da IA", ig_trigger_greeting: "Comentários: oi do gatilho",
    media_briefing: "Mídia On: briefing", media_strategy_narrative: "Mídia On: estratégia", social_report_insights: "Relatório social",
    studio_calendar_import: "Calendário: importar", studio_message_sentence: "Mensagens ao cliente", studio_strategy_chat: "Estratégia (chat)",
  };
  if (map[feature]) return map[feature];
  if (feature.startsWith("intelligence:")) return "Inteligência (chat/relatório)";
  if (feature.startsWith("studio_campaign")) return "Campanhas";
  if (feature.startsWith("studio_clipping")) return "Clipping";
  if (feature.startsWith("creator")) return "Criadores";
  if (feature.startsWith("brand") || feature.startsWith("studio_brand") || feature.startsWith("studio_profile")) return "IA da marca / Perfil";
  return feature;
}

/** Erro da OpenAI em português. */
export function errorLabel(code: string | null | undefined): string {
  const c = String(code || "");
  if (c.includes("insufficient_quota") || c.includes("billing_hard_limit")) return "Sem crédito na OpenAI";
  if (c.includes("invalid_api_key") || c.startsWith("http_401")) return "Chave da OpenAI inválida";
  if (c.startsWith("http_429")) return "Limite de uso por minuto da OpenAI";
  if (c === "timeout") return "A IA demorou demais";
  if (c === "network") return "Falha de conexão com a OpenAI";
  if (c.startsWith("http_5")) return "OpenAI fora do ar";
  return c || "Erro";
}


/** Consumo de UMA empresa (Central da marca): hoje, mês, média por chamada, 30 dias e recursos do mês. */
export type ClientAiUsage = {
  client_id: string; currency: "USD"; estimated: true; today: UsageBucket; month: UsageBucket; per_call: UsageBucket;
  days: (UsageBucket & { day: string })[]; features: (UsageBucket & { feature: string })[]; last_error: UsageError | null;
};
export function getClientAiUsage() {
  return http<ClientAiUsage>(clientClientPath("/studio/ai-usage"));
}
/** Câmbio de referência para estimar em reais (mesmo do CRM Ruah). */
export const USD_BRL = 5.5;
export const formatUsd = (v: number) => `US$ ${v < 0.01 && v > 0 ? v.toFixed(4) : v.toFixed(2)}`.replace(".", ",");
export const formatBrl = (usd: number) => (usd * USD_BRL).toLocaleString("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: 2 });
export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(".", ",")} mi`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1).replace(".", ",")} mil`;
  return String(Math.round(n));
}
