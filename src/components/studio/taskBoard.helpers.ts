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

/** Mês "YYYY-MM" no fuso de São Paulo (0 = este mês, 1 = o próximo). */
export const monthKey = (offset: number) => {
  const now = new Date(new Date().toLocaleString("en-US", { timeZone: "America/Sao_Paulo" }));
  const d = new Date(now.getFullYear(), now.getMonth() + offset, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};

/** Handle do Instagram a partir do nome da empresa (prévia do post no celular). */
export const handleFromName = (name: string) => "@" + name.toLowerCase().normalize("NFD").replace(/[^a-z0-9]/g, "");
