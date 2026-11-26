// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Goal } from "../../app/goals";

const api = vi.hoisted(() => ({ getGoalDiagnosis: vi.fn(), recommendGoal: vi.fn(), taskFromRecommendation: vi.fn(), useGoals: vi.fn() }));
vi.mock("../../app/goals", async (original) => ({ ...(await original<typeof import("../../app/goals")>()),
  getGoalDiagnosis: api.getGoalDiagnosis, recommendGoal: api.recommendGoal, taskFromRecommendation: api.taskFromRecommendation }));
vi.mock("../../hooks/useGoals", () => ({ default: api.useGoals }));
vi.mock("../../app/activeClient", () => ({ getActiveClientId: () => "ruah" }));
import GoalActions from "./GoalActions";
import GoalAlerts from "./GoalAlerts";
import MediaGoals from "./MediaGoals";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); window.localStorage.clear(); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const btn = (t: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.trim() === t)!;
const goal = (o: Partial<Goal> = {}): Goal => ({ id: "g1", client_id: "ruah", metric: "revenue", label: "Faturamento", target_value: 100000, period_start: "2026-11-01",
  period_end: "2026-11-30", actual: 34000, available: true, origin: "Shopify", reason: null, progress_percent: 34, elapsed_percent: 80, pace_delta: -46, projected_value: null,
  remaining: 66000, status: "ABAIXO_DO_RITMO", direction: "min", additive: true, days_left: 6, required_daily: 11000, pace_note: "O ritmo observado está 87% abaixo do necessário por dia.", ...o });

describe("Diagnóstico e ações da meta", () => {
  it("separa fato de hipótese, recomenda no clique e só cria tarefa após confirmar responsável e prazo", async () => {
    api.getGoalDiagnosis.mockResolvedValue({ available: true, periods: [["2026-11-01", "2026-11-10"], ["2026-11-11", "2026-11-20"]],
      facts: ["Pedidos por dia: caiu (-30%…)."], hypothesis: "O desvio parece vir de pedidos (caiu), já que ticket médio ficou estável. É uma leitura dos números, não uma causa comprovada." });
    api.recommendGoal.mockResolvedValue({ id: "r1", saved: true, leitura: "Pedidos caíram.", diagnosis: {}, items: [
      { titulo: "Revisar verba entre campanhas", tipo: "recomendacao", evidencia: "pedidos -30%", justificativa: "tráfego caiu", acao: "Mover R$ 20/dia", task_id: null }] });
    api.taskFromRecommendation.mockResolvedValue({ task_id: "t9", created: true });
    await act(async () => { root.render(<GoalActions goal={goal()} people={[{ user_id: "u2", name: "Julia" }]} canCreateTasks />); });
    await act(async () => {});
    expect(host.textContent).toContain("Fato");
    expect(host.textContent).toContain("Hipótese");
    expect(api.recommendGoal).not.toHaveBeenCalled();
    const area = host.querySelector("textarea")!;
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(area, "sem aumentar verba"); area.dispatchEvent(new Event("input", { bubbles: true })); });
    await act(async () => btn("Analisar oportunidades de melhoria").click());
    expect(api.recommendGoal).toHaveBeenCalledWith("g1", "sem aumentar verba");
    expect(host.textContent).toContain("Evidência: pedidos -30%");
    await act(async () => btn("Criar tarefa").click());
    expect(api.taskFromRecommendation).not.toHaveBeenCalled();
    expect(btn("Confirmar e criar tarefa").disabled).toBe(true);  // falta responsável e prazo
    const [select] = [...host.querySelectorAll("select")];
    await act(async () => { select.value = "u2"; select.dispatchEvent(new Event("change", { bubbles: true })); });
    const date = host.querySelector<HTMLInputElement>("input[type=date]")!;
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(date, "2026-11-28"); date.dispatchEvent(new Event("input", { bubbles: true })); });
    await act(async () => btn("Confirmar e criar tarefa").click());
    expect(api.taskFromRecommendation).toHaveBeenCalledWith("g1", "r1", 0, { assignee_user_ids: ["u2"], due_date: "2026-11-28" });
    expect(host.textContent).toContain("Virou tarefa no Kanban");
  });

  it("sem permissão de tarefas, não oferece criar", async () => {
    api.getGoalDiagnosis.mockResolvedValue({ available: false, reason: "curto" });
    api.recommendGoal.mockResolvedValue({ id: "r1", saved: true, leitura: "", diagnosis: {}, items: [{ titulo: "X", tipo: "investigacao", evidencia: "e", justificativa: "j", acao: "a", task_id: null }] });
    await act(async () => { root.render(<GoalActions goal={goal()} people={[]} canCreateTasks={false} />); });
    await act(async () => btn("Analisar oportunidades de melhoria").click());
    expect(host.textContent).not.toContain("Criar tarefa");
  });
});

describe("Alertas de metas", () => {
  it("prioriza desempenho, separa falha de dado e dispensa sem repetir no dia", async () => {
    const goals = [goal({ id: "a", label: "Pedidos", status: "INDISPONIVEL", available: false, reason: "Sem Shopify" }), goal({ id: "b" }), goal({ id: "c", status: "NO_RITMO" })];
    await act(async () => { root.render(<GoalAlerts goals={goals} />); });
    const items = [...host.querySelectorAll(".goalAlerts li")];
    expect(items.map((li) => li.className)).toEqual(["is-desempenho", "is-dado"]);
    expect(items[1].textContent).toContain("Coleta de dados");
    await act(async () => { (items[0].querySelector("button") as HTMLButtonElement).click(); });
    expect(host.querySelectorAll(".goalAlerts li")).toHaveLength(1);
    act(() => root.unmount()); root = createRoot(host);
    await act(async () => { root.render(<GoalAlerts goals={goals} />); });
    expect(host.querySelectorAll(".goalAlerts li")).toHaveLength(1);  // continua dispensado hoje
  });
});

describe("Metas na Mídia On", () => {
  it("mostra só metas de mídia, sem faturamento total, e leva ao Planejamento", async () => {
    api.useGoals.mockReturnValue({ goals: [goal(), goal({ id: "m", metric: "cpa_meta", label: "CPA", direction: "max", status: "DENTRO_DO_TETO", target_value: 60, actual: 45, additive: false, required_daily: null })], loading: false, error: null });
    const open = vi.fn();
    await act(async () => { root.render(<MediaGoals onOpenPlanning={open} />); });
    expect(host.textContent).toContain("CPA");
    expect(host.textContent).not.toContain("Faturamento");
    expect(host.textContent).toContain("não são somadas");
    await act(async () => btn("Abrir metas no Planejamento").click());
    expect(open).toHaveBeenCalled();
  });
});
