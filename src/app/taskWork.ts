import { http, clientClientPath } from "./api";
import type { TaskStatus } from "./crm";

/** Kanban → produção: seletor de tarefas e leitor do briefing, compartilhados pelos módulos de criação. */
export type WorkModule = "email_marketing" | "social_media" | "midia_on" | "redacao" | "calendar" | "whatsapp";
export type PickableTask = { id: string; title: string; status: TaskStatus; due_date: string | null; category: string | null; assignees: string[] };
export type TaskWorkLink = { id: string; module: WorkModule; deliverable: string; record_id: string; created_at: string };
export type TaskBriefContext = {
  title?: string; summary?: string; objective?: string; key_message?: string; offer?: string; audience?: string;
  deadline?: string; goal?: string; deliverables: string[]; avoid: string[]; your_part: string | null; notes: string;
};
export type TaskContext = {
  client_id: string; client_name: string;
  task: { id: string; title: string; status: TaskStatus; due_date: string | null; category: string | null; deliverable_url: string | null };
  brief_id: string | null; source: "briefing" | "notas"; context: TaskBriefContext;
  module: WorkModule | null; deliverables_for_module: string[]; suggested_deliverable: string | null; links: TaskWorkLink[];
  existing?: LinkedCampaign[];
};
export type LinkedCampaign = { id: string; name: string; subject: string; status: string; deliverable: string };

const base = (path: string) => clientClientPath(`/crm/work${path}`);
const json = (method: string, body: unknown) => ({ method, body: JSON.stringify(body) });

export const listWorkTasks = (q = "") =>
  http<{ available: boolean; client_name: string; tasks: PickableTask[] }>(base(`/tasks${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`));
export const getTaskContext = (taskId: string, module: WorkModule) =>
  http<TaskContext>(base(`/tasks/${encodeURIComponent(taskId)}?module=${module}`));
export const createEmailFromTask = (taskId: string, input: { deliverable: string; mode: "ia" | "branco"; new_version?: boolean; instruction?: string }) =>
  http<{ created: { id: string; name: string; status: string } | null; existing: LinkedCampaign[] }>(
    base(`/tasks/${encodeURIComponent(taskId)}/email`), { ...json("POST", input), timeoutMs: 120_000 });

/** "Ir para o job": o que foi produzido a partir da tarefa (e-mail, texto, matriz, post, anúncio) e onde abrir. */
export type ProducedItem = {
  module: WorkModule; module_label: string; record_id: string; deliverable: string; created_at: string | null;
  name: string; removed: boolean; status: string; route: string | null; query: string | null;
};
export const listProduced = (taskId: string) =>
  http<{ task_id: string; items: ProducedItem[] }>(base(`/tasks/${encodeURIComponent(taskId)}/produced`));

/** Kanban → Redação: documento a partir do briefing (IA da marca) ou em branco, ligado à tarefa. */
export const createDocumentFromTask = (taskId: string, input: { mode: "ia" | "branco"; deliverable: string; new_version?: boolean }) =>
  http<{ created: { id: string; title: string; kind: string } | null; existing: { id: string; title: string; deliverable?: string }[] }>(
    clientClientPath(`/studio/documents/from-task/${encodeURIComponent(taskId)}`), { ...json("POST", input), timeoutMs: 150_000 });
/** Grava na tarefa o que foi criado a partir dela em outro módulo (matriz do Social Media, post…). */
export const linkTaskWork = (taskId: string, input: { module: WorkModule; record_id: string; deliverable?: string }) =>
  http<{ ok: true }>(base(`/tasks/${encodeURIComponent(taskId)}/links`), json("POST", input));

/** Texto da tarefa para orientar a IA (quando a tarefa não veio de um briefing cadastrado). */
export function taskDirection(ctx: TaskContext, deliverable: string): string {
  const c = ctx.context;
  return [ctx.task.title, deliverable && `Entregável: ${deliverable}`, c.summary, c.objective && `Objetivo: ${c.objective}`,
    c.key_message && `Mensagem: ${c.key_message}`, c.offer && `Oferta: ${c.offer}`, c.audience && `Público: ${c.audience}`,
    c.deadline && `Prazo: ${c.deadline}`, c.avoid.length ? `Evitar: ${c.avoid.join("; ")}` : ""]
    .filter(Boolean).join(". ").slice(0, 1000);
}
