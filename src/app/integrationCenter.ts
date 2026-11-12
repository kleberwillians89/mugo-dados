import { http } from "./api";

/** Central de saúde das integrações (só a equipe Mugô; o backend exige agency/platform admin). */
export type SourceState = "reauth_required" | "attention" | "stale" | "updating" | "no_data" | "synced" | "not_connected";
export type CenterSource = {
  provider: string; label: string; state: SourceState; severity: number;
  action: "reconnect" | "review" | "sync" | "wait" | "check" | "none"; hint: string; error_code: string | null;
  last_success_at: string | null; last_attempt_at: string | null; last_data_at: string | null; coverage_end: string | null; failures_7d: number;
};
export type CenterCompany = { id: string; name: string; status: string; sources: CenterSource[]; worst: number;
  queue: { waiting: number; failed: number }; error: string | null };
export type IntegrationCenter = {
  generated_at: string; window: { start: string; end: string };
  summary: { connections: number; ok: number; updating: number; problems: number; stale: number; no_data: number; reauth: number;
    failures_7d: number; companies_with_problem: number };
  queue: { waiting: number; failed: number }; companies: CenterCompany[];
};
export const getIntegrationCenter = () => http<IntegrationCenter & { ok: boolean }>("/api/admin/health/overview", { timeoutMs: 90_000 });

export const STATE_LABEL: Record<SourceState, string> = {
  reauth_required: "Reconectar", attention: "Com erro", stale: "Atrasada", updating: "Sincronizando",
  no_data: "Sem dado", synced: "Em dia", not_connected: "Não conectada",
};
