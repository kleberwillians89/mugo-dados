import { clientClientPath, http } from "./api";
import type { Brief } from "./briefs";

/** Planejamento (CSO) e Evento (produção RTV e eventos): quadro + plano curto da IA + copiloto → Briefing. */
export type ProjectKind = "planejamento" | "evento";
export type ProjectStatus = "fila" | "em_andamento" | "aprovacao_interna" | "finalizado";
export const PROJECT_COLUMNS: { key: ProjectStatus; label: string }[] = [
  { key: "fila", label: "Fila" }, { key: "em_andamento", label: "Em andamento" },
  { key: "aprovacao_interna", label: "Aprovação interna" }, { key: "finalizado", label: "Finalizado" },
];
export type ProjectInputs = { objective?: string; audience?: string; idea?: string; budget?: string; location?: string; notes?: string };
export type StrategyPlan = {
  context?: string; challenge?: string; insight?: string; strategy?: string; big_idea?: string; messages?: string[];
  channels?: { channel: string; role: string }[]; phases?: { phase: string; when: string; what: string }[];
  kpis?: { kpi: string; target: string }[]; risks?: string[];
};
export type BudgetCategory = "equipe" | "equipamento" | "locacao" | "logistica" | "pos_producao" | "outros";
export const BUDGET_LABELS: Record<BudgetCategory, string> = {
  equipe: "Equipe", equipamento: "Equipamento", locacao: "Locação", logistica: "Logística", pos_producao: "Pós-produção", outros: "Outros",
};
export type ProductionPlan = {
  summary?: string; timeline?: { date: string; phase: string; task: string }[]; staff?: { role: string; qty: number; note: string }[];
  budget?: { category: BudgetCategory; item: string; value: number }[]; budget_total?: number;
  risks?: { risk: string; impact: "baixo" | "medio" | "alto"; mitigation: string }[]; checklist?: string[];
};
export type ChatMessage = { role: "equipe" | "copiloto"; content: string; author?: string; at: string };
export type Project = {
  id: string; kind: ProjectKind; title: string; status: ProjectStatus; format?: string | null; target_date?: string | null;
  inputs: ProjectInputs; plan: Omit<StrategyPlan, "risks"> & Omit<ProductionPlan, "risks"> & { risks?: StrategyPlan["risks"] | ProductionPlan["risks"] }; chat: ChatMessage[]; brief_id?: string | null;
  created_at: string; updated_at: string;
};

const base = (kind: ProjectKind, path = "") => clientClientPath(`/studio/projects/${kind}${path}`);
const one = (kind: ProjectKind, id: string, rest = "") => base(kind, `/${encodeURIComponent(id)}${rest}`);

export function listProjects(kind: ProjectKind) { return http<{ projects: Project[]; formats: string[] }>(base(kind)); }
export function createProject(kind: ProjectKind, input: { title: string; format?: string; target_date?: string; inputs: ProjectInputs }) {
  return http<{ project: Project }>(base(kind), { method: "POST", body: JSON.stringify(input) });
}
export function updateProject(kind: ProjectKind, id: string, patch: Partial<Pick<Project, "title" | "status" | "format" | "target_date" | "inputs" | "plan">>) {
  return http<{ project: Project }>(one(kind, id), { method: "PATCH", body: JSON.stringify(patch) });
}
export function deleteProject(kind: ProjectKind, id: string) { return http<{ ok: true }>(one(kind, id), { method: "DELETE" }); }
export function generateProject(kind: ProjectKind, id: string, opts: { use_chat?: boolean; instruction?: string } = {}) {
  return http<{ project: Project }>(one(kind, id, "/generate"), { method: "POST", body: JSON.stringify(opts), timeoutMs: 150_000 });
}
export function chatProject(kind: ProjectKind, id: string, message: string) {
  return http<{ project: Project }>(one(kind, id, "/chat"), { method: "POST", body: JSON.stringify({ message }), timeoutMs: 90_000 });
}
export function projectToBrief(kind: ProjectKind, id: string) {
  return http<{ brief: Brief }>(one(kind, id, "/brief"), { method: "POST", timeoutMs: 150_000 });
}

export function brl(n?: number | null): string {
  return (n || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
}
