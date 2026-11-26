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
