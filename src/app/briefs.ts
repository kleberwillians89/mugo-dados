import { clientClientPath, http } from "./api";
import type { BriefingRole } from "./studio";

/** Briefing: pedido → briefing curto com o contexto do cliente → destinos e tarefa de cada pessoa. */
export type BriefDestination = "social_media" | "midia_on" | "clipping" | "redacao" | "criadores";
export type BriefStatus = "aguardando_equipe" | "pronto" | "distribuido" | "arquivado";
export type BriefContent = {
  title: string; summary?: string; objective?: string; key_message?: string; audience?: string; deadline?: string | null;
  deliverables?: string[]; avoid?: string[]; goal?: string; client_summary?: string;
  destinations?: { key: BriefDestination; why: string }[]; roles?: { role: BriefingRole; what: string }[];
  media?: { objective: string | null; budget: number | null }; clipping_terms?: string[]; creators_type?: string | null;
};
export type BriefSent = { status: "feito" | "falhou"; detail: string; at: string; ref?: Record<string, unknown> };
export type Brief = {
  id: string; status: BriefStatus; request: string; links?: string[]; brief: BriefContent; created_at: string;
  created_side: "mugo" | "cliente"; created_by_name?: string | null;
  destinations?: Partial<Record<BriefDestination, BriefSent>>;
  tasks?: { task_id: string; role: BriefingRole; name: string; user_id?: string | null; at: string }[];
  progress?: { done: number; total: number };
};
export type BriefPatch = Partial<Pick<BriefContent, "title" | "summary" | "objective" | "key_message" | "audience" | "goal" | "client_summary" | "deliverables" | "avoid">>
  & { deadline?: string | null; status?: "arquivado" | "pronto" };

const base = (path = "") => clientClientPath(`/studio/briefs${path}`);
const one = (id: string, rest = "") => base(`/${encodeURIComponent(id)}${rest}`);
export function listBriefs() {
  return http<{ briefs: Brief[]; team: boolean; destinations: Record<BriefDestination, string>; roles: Record<BriefingRole, string> }>(base());
}
export function createBrief(request: string, links: string[] = []) {
  return http<{ brief: Brief }>(base(), { method: "POST", body: JSON.stringify({ request, links }), timeoutMs: 120_000 });
}
export function updateBrief(id: string, patch: BriefPatch) { return http<{ brief: Brief }>(one(id), { method: "PATCH", body: JSON.stringify(patch) }); }
export function regenerateBrief(id: string, instruction?: string) {
  return http<{ brief: Brief }>(one(id, "/regenerate"), { method: "POST", body: JSON.stringify(instruction ? { instruction } : {}), timeoutMs: 120_000 });
}
export function approveBrief(id: string) { return http<{ brief: Brief }>(one(id, "/approve"), { method: "POST" }); }
export function sendBrief(id: string, destination: BriefDestination) {
  return http<{ brief: Brief }>(one(id, `/send/${destination}`), { method: "POST", timeoutMs: 180_000 });
}
export function briefTask(id: string, input: { role: BriefingRole; assignee_user_id?: string | null; assignee_name?: string | null; due_date?: string | null; note?: string | null }) {
  return http<{ brief: Brief }>(one(id, "/tasks"), { method: "POST", body: JSON.stringify(input) });
}
