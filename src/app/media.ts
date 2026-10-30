import { http, clientClientPath } from "./api";

export const CHANNELS = { meta: "Meta Ads", google_ads: "Google Ads" } as const;
export type Channel = keyof typeof CHANNELS;
export const OBJECTIVES = { vendas: "Vendas", leads: "Leads", trafego: "Tráfego", alcance: "Alcance" } as const;
export type Objective = keyof typeof OBJECTIVES;
export type Metric = "revenue" | "conversions" | "clicks" | "impressions";
export const CONFIDENCE = { boa: "Dados consistentes", baixa: "Poucos dados", sem_dados: "Sem investimento", referencia: "Estimativa (sem histórico)" } as const;
export const ACTIONS = { escalar: "Escalar", manter: "Manter", otimizar: "Otimizar", pausar: "Pausar", aprender: "Aprender", testar: "Testar", impulsionar: "Impulsionar posts" } as const;
export const DISTRIBUTIONS = { equilibrado: "Equilibrado", hiperfoco: "Hiperfoco" } as const;
export type Distribution = keyof typeof DISTRIBUTIONS;
export type Action = keyof typeof ACTIONS;
export const SCENARIO_KEYS = ["ritmo_atual", "meta", "eficiencia", "personalizado"] as const;
export type ScenarioKey = (typeof SCENARIO_KEYS)[number];

export type Totals = { spend: number; impressions: number; clicks: number; conversions: number; revenue: number; cpm: number | null; cpc: number | null; ctr: number | null; cpa: number | null; roas: number | null; conversion_rate: number | null };
export type Diagnosis = { channel: Channel; label: string; recent: Totals; previous: Totals; window: Totals; changes: Record<"spend" | "revenue" | "roas" | "cpa" | "cpm" | "ctr" | "conversions", number | null>;
  confidence: keyof typeof CONFIDENCE; days_with_spend: number; monthly_spend: number; findings: Finding[] };
export type Finding = { level: "alerta" | "oportunidade" | "info"; text: string };
export type Curve = { a: number; b: number; fit: "medida" | "estimada" | "referencia" | "sem_dados"; r2: number | null; points: number };
export type ChannelOutcome = { spend: number; revenue: number; conversions: number; clicks: number; impressions: number; roas: number | null; cpa: number | null; cpc: number | null; cpm: number | null };
export type Outcome = { channels: Partial<Record<Channel, ChannelOutcome>>; totals: { spend: number; revenue: number; conversions: number; clicks: number; impressions: number; roas: number | null; cpa: number | null } };
export type Scenario = { key: ScenarioKey; label: string; budget: number; why: string; allocation: Partial<Record<Channel, number>>; allocation_pct: Partial<Record<Channel, number | null>>;
  change_vs_current: Partial<Record<Channel, number | null>>; result: Outcome; marginal_roas: number | null; goal?: { goal: number; capped: boolean } };
export type CampaignAction = { channel: Channel; campaign: string; action: Action; why: string; spend: number; conversions: number; revenue: number; roas: number | null; cpa: number | null; share: number | null;
  planned_budget: number; suggested?: boolean; boost?: boolean; concentrated?: boolean; learning?: string; memory?: { month: string; action: Action; roas: number | null; cpa: number | null; planned_budget: number | null };
  /** Verba ou ação alterada pela equipe: vira aprendizado no próximo plano. */
  edited?: boolean };
export type ReferenceInputs = { cpm: number; ctr: number; cvr: number; ticket: number | null; cvr_source: string; ticket_source: string | null };
export type Week = { start: string; end: string; budget: number; share: number; daily: number; phase: "base" | "aquecimento" | "pico"; dates: string[]; prepares: string[] };
export type Guardrail = { channel: Channel; label: string; daily_budget: number; target_cpa: number | null; max_cpa: number | null; target_roas: number | null; min_roas: number | null; breakeven_roas: number | null; rule: string };
export type BoostPost = { item_id: string; title: string; format: string; status: string; posted: string; start: string; end: string; phase: string; seasonal: string | null; score: number; budget: number; daily: number; impressions: number | null; why: string };
export type Narrative = { headline: string; thesis: string; channel_roles: { channel: Channel; role: string; rationale: string }[]; campaign_notes: { campaign: string; note: string }[];
  creative_guidance: string[]; risks: string[]; next_7_days: string[] };
export type Strategy = {
  month: string; objective: Objective; metric: Metric; metric_label: string; days: number; window: { start: string; end: string; days: number };
  diagnosis: Diagnosis[]; store: { revenue?: number; orders?: number; investment?: number; roas?: number }; goal_revenue: number | null; margin: number | null;
  briefing?: { text: string; summary: string | null; applied: string[]; error: string | null } | null;
  distribution?: Distribution; reference_inputs?: Partial<Record<Channel, ReferenceInputs>>; channel_kind?: Partial<Record<Channel, "dados" | "referencia">>; learned?: number;
  curves: Partial<Record<Channel, Record<Metric, Curve>>>; current_budget: number; scenarios: Scenario[]; recommended: ScenarioKey; selected: ScenarioKey;
  weeks: Week[]; guardrails: Guardrail[]; campaigns: CampaignAction[]; waste: number; findings: Finding[]; method: string;
  boosts: { pool: number; share: number; posts: BoostPost[]; note: string | null };
  narrative: Narrative | null; narrative_error?: string;
  /** Gravação no histórico: id e hora; aviso se não foi possível gravar. */
  strategy_id?: string | null; generated_at?: string | null; history_warning?: string; custom_budget?: number | null;
};
export type StrategySummary = { id: string; month: string; objective: Objective; margin: number | null; custom_budget: number | null; selected: ScenarioKey | null; budget: number | null; headline: string | null; created_at: string };
export type SavedStrategy = Omit<Strategy, "scenarios"> & { scenario: Scenario; scenarios?: Scenario[] };
export type MediaPlan = { id: string; month: string; objective: Objective; budget: number; allocation: Partial<Record<Channel, number>>; scenario: ScenarioKey | null; margin: number | null;
  strategy: SavedStrategy | Record<string, never>; notes: string | null; status: "rascunho" | "aprovado"; updated_at?: string };
export type PlanVsActual = { month: string; plan: MediaPlan | null; elapsed_days: number; days_in_month: number; through?: string;
  channels: { channel: Channel; label: string; planned_spend: number | null; spent: number; expected_to_date: number | null; projected_spend: number; pace: number | null;
    conversions: number | null; revenue: number | null; cpa: number | null; roas: number | null; target_cpa: number | null; target_roas: number | null }[] };

const base = (path: string) => clientClientPath(`/studio/media${path}`);

export function generateStrategy(input: { month: string; objective: Objective; margin?: number; budget?: number; distribution?: Distribution; briefing?: string; with_narrative?: boolean }) {
  return http<Strategy>(base("/strategy"), { method: "POST", body: JSON.stringify(input), timeoutMs: 150_000 });
}
/** Mínimo de verba diária por canal e por impulsionamento (a Meta aceita ~R$ 6; abaixo de R$ 10 a entrega não aprende). */
export const MIN_DAILY = 10;
export function belowMinimum(allocation: Partial<Record<Channel, number>>, days: number): Channel[] {
  return (Object.entries(allocation) as [Channel, number][]).filter(([, v]) => v > 0 && v / days < MIN_DAILY).map(([c]) => c);
}
/**
 * Mantém a verba das campanhas fechando com a do canal: linhas editadas pela equipe (e o impulsionamento) ficam
 * como estão; as demais se ajustam na proporção do que já tinham.
 */
export function rescaleCampaigns(campaigns: CampaignAction[], allocation: Partial<Record<Channel, number>>): CampaignAction[] {
  const out = campaigns.map((c) => ({ ...c }));
  for (const channel of Object.keys(CHANNELS) as Channel[]) {
    const rows = out.filter((c) => c.channel === channel);
    const budget = allocation[channel] || 0;
    const fixed = rows.filter((c) => c.edited || c.boost).reduce((s, c) => s + (c.planned_budget || 0), 0);
    const free = rows.filter((c) => !c.edited && !c.boost && c.action !== "pausar" && (c.planned_budget > 0 || c.suggested));
    const freeTotal = free.reduce((s, c) => s + (c.planned_budget || 0), 0);
    const target = Math.max(budget - fixed, 0);
    for (const c of free) c.planned_budget = Math.round((freeTotal ? (c.planned_budget / freeTotal) * target : target / free.length) * 100) / 100;
    if (!budget) for (const c of rows) if (!c.edited) c.planned_budget = 0;
  }
  return out;
}
export const campaignTotals = (campaigns: CampaignAction[]) => campaigns.reduce<Partial<Record<Channel, number>>>((acc, c) => ({ ...acc, [c.channel]: (acc[c.channel] || 0) + (c.planned_budget || 0) }), {});
export const campaignsBelowMinimum = (campaigns: CampaignAction[], days: number) => campaigns.filter((c) => c.planned_budget > 0 && c.planned_budget / days < MIN_DAILY);
export function listStrategies(month: string) { return http<{ strategies: StrategySummary[] }>(base(`/strategies?month=${encodeURIComponent(month)}`)); }
export function getStrategy(id: string) { return http<Strategy>(base(`/strategies/${encodeURIComponent(id)}`), { timeoutMs: 60_000 }); }
/** Abre a estratégia mais recente: a última gerada, a não ser que o plano tenha sido salvo depois dela. */
export function latestSource(planUpdatedAt: string | null | undefined, history: StrategySummary[]): "plan" | "history" | null {
  const last = history[0]?.created_at;
  if (!last) return planUpdatedAt ? "plan" : null;
  if (!planUpdatedAt) return "history";
  return new Date(last).getTime() > new Date(planUpdatedAt).getTime() ? "history" : "plan";
}
export function getPlan(month: string) { return http<PlanVsActual>(base(`/plan?month=${encodeURIComponent(month)}`), { timeoutMs: 60_000 }); }
export function savePlan(input: { month: string; objective: Objective; scenario: ScenarioKey; budget: number; allocation: Partial<Record<Channel, number>>; margin?: number; strategy: SavedStrategy; notes?: string; status: "rascunho" | "aprovado" }) {
  return http<{ plan: MediaPlan }>(base("/plan"), { method: "PUT", body: JSON.stringify(input), timeoutMs: 60_000 });
}

/** Mesma fórmula do backend: y = a·(gasto semanal)^b × semanas. */
export function project(curve: Curve | undefined, monthlySpend: number, days: number): number {
  if (!curve || !curve.a || monthlySpend <= 0) return 0;
  const weeks = days / 7;
  return curve.a * (monthlySpend / weeks) ** curve.b * weeks;
}

export function outcomeFor(curves: Strategy["curves"], allocation: Partial<Record<Channel, number>>, days: number): Outcome {
  const channels: Outcome["channels"] = {};
  for (const [c, spend] of Object.entries(allocation) as [Channel, number][]) {
    const set = curves[c];
    if (!set) continue;
    const p = { revenue: project(set.revenue, spend, days), conversions: project(set.conversions, spend, days), clicks: project(set.clicks, spend, days), impressions: project(set.impressions, spend, days) };
    channels[c] = { spend, ...p, roas: spend ? p.revenue / spend : null, cpa: p.conversions ? spend / p.conversions : null, cpc: p.clicks ? spend / p.clicks : null, cpm: p.impressions ? (spend * 1000) / p.impressions : null };
  }
  const list = Object.values(channels) as ChannelOutcome[];
  const sum = (k: keyof ChannelOutcome) => list.reduce((s, ch) => s + (Number(ch[k]) || 0), 0);
  const spend = sum("spend"), revenue = sum("revenue"), conversions = sum("conversions");
  return { channels, totals: { spend, revenue, conversions, clicks: sum("clicks"), impressions: sum("impressions"), roas: spend ? revenue / spend : null, cpa: conversions ? spend / conversions : null } };
}

/** Pontos da curva de retorno de um canal, de 0 a 2,5x a verba de referência. */
export function curvePoints(curve: Curve | undefined, reference: number, days: number, steps = 24) {
  const max = Math.max(reference * 2.5, 1);
  return Array.from({ length: steps + 1 }, (_, i) => { const spend = (max * i) / steps; return { spend, value: project(curve, spend, days) }; });
}

export const money = (v: number | null | undefined, digits?: number) => v == null || !Number.isFinite(v) ? "—"
  : v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: digits ?? (Math.abs(v) < 100 ? 2 : 0) });
export const num = (v: number | null | undefined, digits = 0) => v == null || !Number.isFinite(v) ? "—" : v.toLocaleString("pt-BR", { maximumFractionDigits: digits });
export const percent = (v: number | null | undefined, digits = 1) => v == null || !Number.isFinite(v) ? "—" : `${(v * 100).toLocaleString("pt-BR", { maximumFractionDigits: digits })}%`;
export const ratio = (v: number | null | undefined) => v == null || !Number.isFinite(v) ? "—" : v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const shortDate = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" }).replace(".", "");
export const metricValue = (metric: Metric, v: number | null | undefined) => metric === "revenue" ? money(v) : num(v);
