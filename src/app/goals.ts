import { http, clientClientPath } from "./api";
export const GOAL_METRICS = {
  revenue: ["Faturamento", "currency"], orders: ["Pedidos", "count"], average_ticket: ["Ticket médio", "currency"],
  ad_spend: ["Investimento em anúncios", "currency"], roas: ["ROAS", "multiple"], conversions: ["Compras atribuídas (Meta Ads)", "count"],
  followers: ["Seguidores (Instagram)", "count"], reach: ["Alcance único", "count"], impressions: ["Impressões (Instagram)", "count"], engagement: ["Interações (Instagram)", "count"],
} as const;
export type GoalMetric = keyof typeof GOAL_METRICS;
export type GoalInput = { metric: GoalMetric; label: string; target_value: number; period_start: string; period_end: string };
export type Goal = GoalInput & { id: string; client_id: string; actual: number | null; available: boolean; origin: string | null; reason: string | null; progress_percent: number | null; elapsed_percent: number; pace_delta: number | null; projected_value: number | null; remaining: number | null; status: string };
export async function getGoals(start?: string, end?: string): Promise<{ client_id: string; goals: Goal[] }> {
  const query = new URLSearchParams(); if (start) query.set("start", start); if (end) query.set("end", end);
  return http(clientClientPath(`/goals${query.size ? `?${query}` : ""}`));
}
export async function saveGoal(input: GoalInput, id?: string) {
  return http(clientClientPath(`/goals${id ? `/${encodeURIComponent(id)}` : ""}`), { method: id ? "PUT" : "POST", body: JSON.stringify(input) });
}
export async function deleteGoal(id: string) { return http(clientClientPath(`/goals/${encodeURIComponent(id)}`), { method: "DELETE" }); }
export function goalNumber(value: number | null, metric: GoalMetric) {
  if (value == null) return "—";
  const unit = GOAL_METRICS[metric][1];
  return unit === "currency" ? value.toLocaleString("pt-BR", { style: "currency", currency: "BRL" }) : value.toLocaleString("pt-BR", { maximumFractionDigits: 2 }) + (unit === "multiple" ? "x" : "");
}
export const GOAL_STATUS: Record<string, string> = { META_ATINGIDA: "Meta atingida", NO_RITMO: "No ritmo", ATENCAO: "Atenção", ABAIXO_DO_RITMO: "Abaixo do ritmo", FUTURA: "Período futuro", INDISPONIVEL: "Indisponível" };
