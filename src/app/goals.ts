import { http, clientClientPath } from "./api";
export const GOAL_METRICS = {
  revenue: ["Faturamento", "currency"], orders: ["Pedidos", "count"], average_ticket: ["Ticket médio", "currency"],
  ad_spend: ["Investimento em anúncios", "currency"], roas: ["ROAS", "multiple"], conversions: ["Compras atribuídas (Meta Ads)", "count"],
  followers: ["Seguidores (Instagram)", "count"], reach: ["Alcance único", "count"], impressions: ["Impressões (Instagram)", "count"], engagement: ["Interações (Instagram)", "count"],
  cpa_meta: ["CPA (Meta Ads)", "currency"], google_conversions: ["Conversões (Google Ads)", "count"], sessions: ["Sessões (GA4)", "count"],
  conversion_rate: ["Taxa de conversão (GA4)", "percent"], followers_gained: ["Seguidores ganhos (Instagram)", "count"],
} as const;
export type GoalMetric = keyof typeof GOAL_METRICS;
export type GoalDirection = "min" | "max";
/** Teto por padrão (pode mudar no formulário); as demais nascem como mínima. */
export const DEFAULT_DIRECTION: Partial<Record<GoalMetric, GoalDirection>> = { ad_spend: "max", cpa_meta: "max" };
export type ScenarioChoice = { key: string; label: string; value: number; premises: GoalSuggestion["premises"]; uncertainty: string };
export type GoalInput = { metric: GoalMetric; label: string; target_value: number | null; period_start: string; period_end: string;
  direction?: GoalDirection; is_primary?: boolean; parent_goal_id?: string | null; relation?: string | null; owner_user_id?: string | null;
  suggestion?: ScenarioChoice | null };
export type Goal = Omit<GoalInput, "target_value"> & { target_value: number; id: string; client_id: string; actual: number | null; available: boolean; origin: string | null; reason: string | null;
  progress_percent: number | null; elapsed_percent: number; pace_delta: number | null; projected_value: number | null; remaining: number | null; status: string;
  direction: GoalDirection; additive?: boolean; days_total?: number; days_left?: number; required_daily?: number | null; observed_daily?: number | null;
  covered_days?: number | null; pace_model?: "linear" | null; pace_note?: string | null };
export async function getGoals(start?: string, end?: string, includeActuals = true): Promise<{ client_id: string; goals: Goal[] }> {
  const query = new URLSearchParams(); if (start) query.set("start", start); if (end) query.set("end", end);
  if (!includeActuals) query.set("include_actuals", "false");
  return http(clientClientPath(`/goals${query.size ? `?${query}` : ""}`));
}
export async function saveGoal(input: GoalInput, id?: string) {
  return http(clientClientPath(`/goals${id ? `/${encodeURIComponent(id)}` : ""}`), { method: id ? "PUT" : "POST", body: JSON.stringify(input) });
}
export async function deleteGoal(id: string) { return http(clientClientPath(`/goals/${encodeURIComponent(id)}`), { method: "DELETE" }); }

export type GoalDriver = { metric: GoalMetric; label: string; available: boolean; actual: number | null; origin: string | null; reason: string | null;
  needed: number | null; direction: GoalDirection };
export function getGoalDrivers(id: string) {
  return http<{ relation: string | null; drivers: GoalDriver[]; note: string }>(clientClientPath(`/goals/${encodeURIComponent(id)}/drivers`));
}
export type GoalHistoryEvent = { action: "criada" | "editada" | "excluida"; before: Partial<Goal> | null; after: Partial<Goal> | null; actor: string | null; created_at: string };
export function getGoalHistory(id: string) {
  return http<{ available: boolean; events: GoalHistoryEvent[] }>(clientClientPath(`/goals/${encodeURIComponent(id)}/history`));
}
export type GoalSuggestion = { available: boolean; reason?: string; direction?: GoalDirection; uncertainty?: string; trend_percent?: number | null;
  scenarios?: { key: string; label: string; value: number }[];
  premises?: { history: { start: string; end: string; value: number | null; coverage: number; origin: string | null; reason: string | null }[];
    model: string; commercial_dates: string[]; seasonality_note: string | null } };
export function suggestGoal(metric: GoalMetric, start: string, end: string) {
  return http<GoalSuggestion>(clientClientPath(`/goals/suggest?${new URLSearchParams({ metric, start, end })}`), { timeoutMs: 60_000 });
}

export function goalNumber(value: number | null | undefined, metric: GoalMetric) {
  if (value == null) return "—";
  const unit = GOAL_METRICS[metric][1];
  if (unit === "currency") return value.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  if (unit === "percent") return `${value.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}%`;
  return value.toLocaleString("pt-BR", { maximumFractionDigits: 2 }) + (unit === "multiple" ? "x" : "");
}
export const GOAL_STATUS: Record<string, string> = { META_ATINGIDA: "Meta atingida", NO_RITMO: "No ritmo", ATENCAO: "Atenção", ABAIXO_DO_RITMO: "Abaixo do ritmo",
  ABAIXO_DA_META: "Abaixo da meta", FUTURA: "Período futuro", INDISPONIVEL: "Dados indisponíveis",
  DENTRO_DO_TETO: "Dentro do teto", RISCO_DE_PASSAR: "Risco de passar do teto", ACIMA_DO_TETO: "Acima do teto" };
/** Uma frase do que exige atenção (ou nada). Só usa números calculados no servidor. */
export function goalReading(goal: Goal): string {
  const n = (v: number | null | undefined) => goalNumber(v, goal.metric);
  if (!goal.available) return goal.reason || "Dados indisponíveis para este indicador.";
  if (goal.status === "FUTURA") return "O período ainda não começou.";
  if (goal.direction === "max") {
    if (goal.status === "ACIMA_DO_TETO") return `Passou do teto de ${n(goal.target_value)}.`;
    if (goal.required_daily != null && goal.days_left) return `Ainda cabem ${n(goal.remaining)} até o teto: até ${n(goal.required_daily)} por dia nos ${goal.days_left} dias restantes.`;
    return `Dentro do teto de ${n(goal.target_value)}.`;
  }
  if (goal.status === "META_ATINGIDA") return "Meta atingida.";
  if (goal.required_daily != null && goal.days_left)
    return `Faltam ${n(goal.remaining)}. Com ${goal.days_left} dia${goal.days_left > 1 ? "s" : ""} restante${goal.days_left > 1 ? "s" : ""}, é preciso ${n(goal.required_daily)} por dia.`;
  if (!goal.additive) return `Hoje está em ${n(goal.actual)}; o alvo é ${n(goal.target_value)}.`;
  return `Faltam ${n(goal.remaining)}.`;
}
