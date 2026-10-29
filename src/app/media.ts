import { http, clientClientPath } from "./api";

export const CHANNELS = { meta: "Meta Ads", google_ads: "Google Ads" } as const;
export type Channel = keyof typeof CHANNELS;
export const OBJECTIVES = { vendas: "Vendas", leads: "Leads/cadastros", trafego: "Tráfego para o site", alcance: "Alcance e marca" } as const;
export type Objective = keyof typeof OBJECTIVES;
export const CONFIDENCE = { boa: "Dados bons", baixa: "Poucos dados", sem_dados: "Sem investimento", desconectado: "Não conectado" } as const;

export type ChannelMetrics = {
  spend: number; impressions: number; clicks: number; conversions: number; conversion_value: number; days_covered: number;
  cpm: number | null; cpc: number | null; ctr: number | null; conversion_rate: number | null; cpa: number | null;
  value_per_conversion: number | null; roas: number | null; monthly_spend: number; confidence: keyof typeof CONFIDENCE;
};
export type Assumption = { cpm: number | null; cpc: number | null; conversion_rate: number | null; value_per_conversion: number | null; monthly_spend?: number | null };
export type Baseline = { period: { start: string; end: string; days: number }; channels: Record<Channel, ChannelMetrics>; assumptions: Record<Channel, Assumption> };
export type Scenario = { impressions: number | null; clicks: number | null; conversions: number | null; revenue: number | null; cpa: number | null; roas: number | null };
export type Simulation = {
  budget: number; warnings: string[]; method: string; assumptions: Record<Channel, Assumption>;
  channels: { channel: Channel; spend: number; pct?: number; saturation?: number; missing?: boolean; scenarios: Partial<Record<"conservador" | "esperado" | "otimista", Scenario>> }[];
  totals: Record<"conservador" | "esperado" | "otimista", { conversions: number; revenue: number; cpa: number | null; roas: number | null }>;
};
export type MediaPlan = { id: string; month: string; objective: Objective; budget: number; allocation: Partial<Record<Channel, number>>; assumptions: Partial<Record<Channel, Assumption>>; notes: string | null; status: "rascunho" | "aprovado" };
export type PlanVsActual = { month: string; plan: MediaPlan | null; elapsed_days: number; days_in_month: number; through?: string;
  channels: { channel: Channel; label: string; planned_spend: number | null; spent: number; projected_spend: number | null; pace: number | null; expected_to_date: number | null; clicks: number | null; conversions: number | null; conversion_value: number | null; cpc: number | null; cpa: number | null; roas: number | null }[] };
export type Recommendation = { allocation: Partial<Record<Channel, number>>; rationale: string; main_risk: string; next_steps: string[]; simulation: Simulation; assumptions: Record<Channel, Assumption> };

const base = (path: string) => clientClientPath(`/studio/media${path}`);
type SimInput = { budget: number; allocation: Partial<Record<Channel, number>>; assumptions?: Partial<Record<Channel, Partial<Assumption>>> };

export function getBaseline() { return http<Baseline>(base("/baseline"), { timeoutMs: 60_000 }); }
export function runSimulation(input: SimInput) { return http<Simulation>(base("/simulate"), { method: "POST", body: JSON.stringify(input), timeoutMs: 60_000 }); }
export function getPlan(month: string) { return http<PlanVsActual>(base(`/plan?month=${encodeURIComponent(month)}`), { timeoutMs: 60_000 }); }
export function savePlan(input: SimInput & { month: string; objective: Objective; notes?: string; status: "rascunho" | "aprovado" }) {
  return http<{ plan: MediaPlan }>(base("/plan"), { method: "PUT", body: JSON.stringify(input), timeoutMs: 60_000 });
}
export function recommendPlan(input: { month: string; budget: number; objective: Objective }) {
  return http<Recommendation>(base("/recommend"), { method: "POST", body: JSON.stringify(input), timeoutMs: 120_000 });
}

export const allocationTotal = (a: Partial<Record<Channel, number>>) => Math.round(Object.values(a).reduce((s, v) => s + (Number(v) || 0), 0) * 10) / 10;
export const money = (v: number | null | undefined) => v == null ? "—" : v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: v < 100 ? 2 : 0 });
export const num = (v: number | null | undefined, digits = 0) => v == null ? "—" : v.toLocaleString("pt-BR", { maximumFractionDigits: digits });
export const percent = (v: number | null | undefined, digits = 2) => v == null ? "—" : `${(v * 100).toLocaleString("pt-BR", { maximumFractionDigits: digits })}%`;
