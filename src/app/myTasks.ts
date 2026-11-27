import { http } from "./api";
import type { CrmTask, TaskStatus } from "./crm";

/** Minhas Tarefas: as tarefas em que a pessoa logada é responsável, em todas as empresas que ela vê. */
export type MyTask = CrmTask & { client_id: string; client_name: string };
export type MyTasksResult = { ok: true; tasks: MyTask[]; clients: { client_id: string; name: string }[]; truncated: boolean };
export type MyTasksFilter = { clientId?: string; status?: "open" | TaskStatus; q?: string };

export function listMyTasks(filter: MyTasksFilter = {}) {
  const params = new URLSearchParams();
  if (filter.clientId) params.set("client_id", filter.clientId);
  if (filter.status && filter.status !== "open") params.set("status", filter.status);
  if (filter.q?.trim()) params.set("q", filter.q.trim());
  const query = params.toString();
  return http<MyTasksResult>(`/api/me/tasks${query ? `?${query}` : ""}`);
}

export type MyTaskGroup = "late" | "today" | "next" | "none";
export const MY_TASK_GROUPS: { key: MyTaskGroup; label: string }[] = [
  { key: "late", label: "Atrasadas" },
  { key: "today", label: "Para hoje" },
  { key: "next", label: "Próximas" },
  { key: "none", label: "Sem prazo" },
];

function dayKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

/** Agrupa pelo prazo (dia local de quem vê). Dentro do grupo, o prazo mais cedo primeiro. */
export function groupMyTasks(tasks: MyTask[], today = new Date()): Record<MyTaskGroup, MyTask[]> {
  const now = dayKey(today);
  const out: Record<MyTaskGroup, MyTask[]> = { late: [], today: [], next: [], none: [] };
  for (const task of tasks) {
    const due = (task.due_date || "").slice(0, 10);
    const key: MyTaskGroup = !due ? "none" : due < now ? "late" : due === now ? "today" : "next";
    out[key].push(task);
  }
  const byDue = (a: MyTask, b: MyTask) => `${a.due_date || ""} ${a.due_time || ""}`.localeCompare(`${b.due_date || ""} ${b.due_time || ""}`);
  out.late.sort(byDue); out.today.sort(byDue); out.next.sort(byDue);
  return out;
}
