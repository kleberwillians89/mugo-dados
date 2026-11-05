import { describe, expect, it } from "vitest";
import type { CrmTask } from "../app/crm";
import { sortTasks } from "./Tasks";

const t = (id: string, over: Partial<CrmTask>): CrmTask => ({ id, title: id, status: "pending", priority: null, due_date: null, due_time: null,
  starts_at: null, category: null, task_type: null, tags: [], notes: null, updated_at: null, assignee: null, ...over });

describe("sortTasks", () => {
  it("atrasadas primeiro, depois prazo, depois prioridade", () => {
    const today = new Date(2026, 10, 5);
    const list = [t("sem-prazo", {}), t("amanha-baixa", { due_date: "2026-11-06", priority: "low" }),
      t("amanha-urgente", { due_date: "2026-11-06", priority: "urgent" }), t("atrasada", { due_date: "2026-11-01" })];
    expect(sortTasks(list, today).map((x) => x.id)).toEqual(["atrasada", "amanha-urgente", "amanha-baixa", "sem-prazo"]);
  });
});
