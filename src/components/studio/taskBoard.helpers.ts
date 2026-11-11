import { dueInfo, type CrmTask, type TaskStatus } from "../../app/crm";

export const OPEN: TaskStatus[] = ["pending", "in_progress", "internal_review", "client_review", "changes"];
const PRIORITY_RANK: Record<string, number> = { urgent: 0, high: 1, medium: 2, low: 3 };

/** Ordem do card dentro da coluna: atrasadas primeiro, depois prazo mais próximo, depois prioridade. */
export function sortTasks(list: CrmTask[], today = new Date()): CrmTask[] {
  return [...list].sort((a, b) => {
    const la = dueInfo(a.due_date, today).late && OPEN.includes(a.status) ? 0 : 1;
    const lb = dueInfo(b.due_date, today).late && OPEN.includes(b.status) ? 0 : 1;
    if (la !== lb) return la - lb;
    const da = a.due_date || "9999", db = b.due_date || "9999";
    if (da !== db) return da < db ? -1 : 1;
    return (PRIORITY_RANK[a.priority || ""] ?? 9) - (PRIORITY_RANK[b.priority || ""] ?? 9);
  });
}
